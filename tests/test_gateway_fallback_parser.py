"""LLM-agnostic fallback parser 단위 테스트 — task-AGENT-008.

_parse_fallback_tool_calls 의 패턴 검출 + LLMGateway.complete 의
Layer 1 retry / Layer 2 inject 통합 테스트.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import litellm
import pytest

from macro_logbot.gateway import LLMGateway, Message
from macro_logbot.gateway.client import _parse_fallback_tool_calls

# ---------------------------------------------------------------------------
# _parse_fallback_tool_calls 단위 테스트 (7 케이스)
# ---------------------------------------------------------------------------


def test_llama33_function_tag() -> None:
    """Case 1: Llama 3.3 <function=name>{...}</function> → tool_calls 추출."""
    content = '<function=search_logs>{"query": "error", "limit": 10}</function>'
    result = _parse_fallback_tool_calls(content)
    assert result is not None
    calls, pattern_name = result
    assert len(calls) == 1
    tc = calls[0]
    assert tc["id"] == "fallback_0"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "search_logs"
    args = json.loads(tc["function"]["arguments"])
    assert args["query"] == "error"
    assert args["limit"] == 10
    assert pattern_name == "function_xml"


def test_qwen_tool_call_tag() -> None:
    """Case 2: Qwen <tool_call>{"name":..., "arguments":...}</tool_call> → 추출."""
    content = '<tool_call>{"name": "get_trace", "arguments": {"trace_id": "abc123"}}</tool_call>'
    result = _parse_fallback_tool_calls(content)
    assert result is not None
    calls, pattern_name = result
    assert len(calls) == 1
    tc = calls[0]
    assert tc["function"]["name"] == "get_trace"
    args = json.loads(tc["function"]["arguments"])
    assert args["trace_id"] == "abc123"
    assert pattern_name == "tool_call_xml"


def test_markdown_json_code_block() -> None:
    """Case 3: Markdown ```json {"name":...,"arguments":...} ``` → 추출."""
    content = '```json\n{"name": "analyze_error", "arguments": {"error_code": "E500"}}\n```'
    result = _parse_fallback_tool_calls(content)
    assert result is not None
    calls, pattern_name = result
    assert len(calls) == 1
    tc = calls[0]
    assert tc["function"]["name"] == "analyze_error"
    args = json.loads(tc["function"]["arguments"])
    assert args["error_code"] == "E500"
    assert pattern_name == "json_codeblock"


def test_llama31_python_tag() -> None:
    """Case 4: Llama 3.1 <|python_tag|>name.call({...}) → 추출."""
    content = '<|python_tag|>search_kb.call({"keyword": "timeout"})'
    result = _parse_fallback_tool_calls(content)
    assert result is not None
    calls, pattern_name = result
    assert len(calls) == 1
    tc = calls[0]
    assert tc["function"]["name"] == "search_kb"
    args = json.loads(tc["function"]["arguments"])
    assert args["keyword"] == "timeout"
    assert pattern_name == "python_tag"


def test_no_match_plain_text() -> None:
    """Case 5: 매칭 없는 plain text 본문 → None."""
    content = "I cannot find any relevant logs for this query."
    result = _parse_fallback_tool_calls(content)
    assert result is None


def test_invalid_json_skipped() -> None:
    """Case 6: JSON invalid → skip, 유효한 패턴만 반환 (매칭 없으면 None)."""
    content = "<function=broken_tool>{not valid json}</function>"
    result = _parse_fallback_tool_calls(content)
    assert result is None


def test_multi_tool_calls() -> None:
    """Case 7: 한 응답에 tool call 여러 개 → 모두 추출 (순서 보존)."""
    content = (
        '<function=search_logs>{"query": "error"}</function>\n'
        '<function=get_trace>{"trace_id": "xyz"}</function>'
    )
    result = _parse_fallback_tool_calls(content)
    assert result is not None
    calls, pattern_name = result
    assert len(calls) == 2
    assert calls[0]["function"]["name"] == "search_logs"
    assert calls[0]["id"] == "fallback_0"
    assert calls[1]["function"]["name"] == "get_trace"
    assert calls[1]["id"] == "fallback_1"
    assert pattern_name == "function_xml"


# ---------------------------------------------------------------------------
# LLMGateway.complete 통합 테스트 — Layer 1 + Layer 2
# ---------------------------------------------------------------------------


def _make_litellm_response(
    content: str = "Hello!",
    tool_calls: object = None,
    model: str = "groq/llama-3.3-70b-versatile",
) -> SimpleNamespace:
    """litellm.acompletion 반환 객체 mock."""
    msg = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        id="chatcmpl-fb-test",
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[SimpleNamespace(index=0, message=msg, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


@pytest.mark.asyncio
async def test_layer2_injects_tool_calls_from_content() -> None:
    """Layer 2: tool_calls 없고 content 에 Llama 패턴 → tool_calls inject + metadata."""
    llama_content = '<function=search_logs>{"query": "crash"}</function>'
    fake_response = _make_litellm_response(content=llama_content)
    mock = AsyncMock(return_value=fake_response)

    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="groq/llama-3.3-70b-versatile")
        result = await gateway.complete([Message(role="user", content="찾아줘")])

    assert result.choices[0].message.tool_calls is not None
    tc = result.choices[0].message.tool_calls[0]
    assert tc.function.name == "search_logs"
    assert json.loads(tc.function.arguments)["query"] == "crash"
    # task-AGENT-009: metadata 검증
    assert result._fallback_used == "layer2_regex_inject"
    assert result._fallback_pattern == "function_xml"


@pytest.mark.asyncio
async def test_layer2_skips_when_tool_calls_present() -> None:
    """Layer 2: 이미 tool_calls 있으면 fallback parser skip — 기존 path 회귀 가드."""
    existing_tc = SimpleNamespace(
        id="tc-001",
        type="function",
        function=SimpleNamespace(name="real_tool", arguments='{"x": 1}'),
    )
    fake_response = _make_litellm_response(
        content="some text",
        tool_calls=[existing_tc],
    )
    mock = AsyncMock(return_value=fake_response)

    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        result = await gateway.complete([Message(role="user", content="call")])

    tcs = result.choices[0].message.tool_calls
    assert tcs is not None
    assert len(tcs) == 1
    assert tcs[0].function.name == "real_tool"


@pytest.mark.asyncio
async def test_layer1_retries_on_tool_use_failed() -> None:
    """Layer 1: BadRequestError(tool_use_failed) 시 tools 제거 후 1회 retry."""
    retry_content = '<function=search_logs>{"query": "retry"}</function>'
    retry_response = _make_litellm_response(content=retry_content)

    call_count = 0

    async def side_effect(**kwargs: object) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise litellm.exceptions.BadRequestError(
                message="tool_use_failed: provider native parser error",
                model="groq/llama-3.3-70b-versatile",
                llm_provider="groq",
            )
        return retry_response

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=side_effect):
        gateway = LLMGateway(default_model="groq/llama-3.3-70b-versatile")
        tools = [{"type": "function", "function": {"name": "search_logs", "parameters": {}}}]
        result = await gateway.complete(
            [Message(role="user", content="찾아줘")],
            tools=tools,
        )

    assert call_count == 2
    tcs = result.choices[0].message.tool_calls
    assert tcs is not None
    assert tcs[0].function.name == "search_logs"
    # task-AGENT-009: Layer 1 + Layer 2 모두 발생 → layer2_regex_inject 가 최종값
    # (retry content 에 function_xml 패턴이 포함되어 Layer 2 도 inject 됨)
    assert result._fallback_used == "layer2_regex_inject"


@pytest.mark.asyncio
async def test_layer1_raises_non_tool_use_failed_error() -> None:
    """Layer 1: tool_use_failed 아닌 BadRequestError 는 그대로 raise."""

    async def side_effect(**kwargs: object) -> SimpleNamespace:
        raise litellm.exceptions.BadRequestError(
            message="model_not_found: unknown model",
            model="groq/nonexistent",
            llm_provider="groq",
        )

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=side_effect):
        gateway = LLMGateway(default_model="groq/nonexistent")
        with pytest.raises(litellm.exceptions.BadRequestError, match="model_not_found"):
            await gateway.complete([Message(role="user", content="hi")])


@pytest.mark.asyncio
async def test_layer1_raises_tool_use_failed_without_tools_kwarg() -> None:
    """Layer 1: tool_use_failed 지만 tools kwarg 없으면 retry 없이 raise."""

    async def side_effect(**kwargs: object) -> SimpleNamespace:
        raise litellm.exceptions.BadRequestError(
            message="tool_use_failed: unexpected",
            model="groq/llama-3.3-70b-versatile",
            llm_provider="groq",
        )

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=side_effect):
        gateway = LLMGateway(default_model="groq/llama-3.3-70b-versatile")
        with pytest.raises(litellm.exceptions.BadRequestError, match="tool_use_failed"):
            # tools kwarg 없이 호출
            await gateway.complete([Message(role="user", content="hi")])
