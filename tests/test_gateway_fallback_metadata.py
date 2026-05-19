"""ChatCompletionResponse._fallback_used metadata 노출 테스트 — task-AGENT-009.

Layer 1 (BadRequestError retry) / Layer 2 (regex inject) / 정상 경로 각각
_fallback_used 및 _fallback_pattern 필드를 검증한다.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import litellm
import pytest

from macro_logbot.gateway import LLMGateway, Message


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_litellm_response(
    content: str = "Hello!",
    tool_calls: object = None,
    model: str = "groq/llama-3.3-70b-versatile",
) -> SimpleNamespace:
    msg = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        id="chatcmpl-meta-test",
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[SimpleNamespace(index=0, message=msg, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


# ---------------------------------------------------------------------------
# 정상 경로: _fallback_used is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_path_fallback_used_is_none() -> None:
    """정상 응답 — _fallback_used is None, _fallback_pattern is None."""
    fake = _make_litellm_response(content="정상 응답입니다.")
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=AsyncMock(return_value=fake)):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        result = await gateway.complete([Message(role="user", content="안녕")])

    assert result._fallback_used is None
    assert result._fallback_pattern is None


# ---------------------------------------------------------------------------
# Layer 1: BadRequestError(tool_use_failed) → layer1_no_tools_retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer1_fallback_used_metadata() -> None:
    """Layer 1: tool_use_failed retry → _fallback_used == 'layer1_no_tools_retry'."""
    retry_response = _make_litellm_response(content="retry 결과입니다.")
    call_count = 0

    async def side_effect(**kwargs: object) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise litellm.exceptions.BadRequestError(
                message="tool_use_failed: native parser error",
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

    assert result._fallback_used == "layer1_no_tools_retry"
    assert result._fallback_pattern is None  # Layer 1 전용: pattern 없음


# ---------------------------------------------------------------------------
# Layer 2: regex inject — 4 패턴 각각 _fallback_pattern 검증
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer2_function_xml_pattern() -> None:
    """Layer 2 — function_xml 패턴: _fallback_used + _fallback_pattern 검증."""
    content = '<function=search_logs>{"query": "error"}</function>'
    fake = _make_litellm_response(content=content)
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=AsyncMock(return_value=fake)):
        gateway = LLMGateway(default_model="groq/llama-3.3-70b-versatile")
        result = await gateway.complete([Message(role="user", content="찾아줘")])

    assert result._fallback_used == "layer2_regex_inject"
    assert result._fallback_pattern == "function_xml"


@pytest.mark.asyncio
async def test_layer2_tool_call_xml_pattern() -> None:
    """Layer 2 — tool_call_xml 패턴 (Qwen): _fallback_pattern == 'tool_call_xml'."""
    content = '<tool_call>{"name": "get_trace", "arguments": {"trace_id": "abc"}}</tool_call>'
    fake = _make_litellm_response(content=content)
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=AsyncMock(return_value=fake)):
        gateway = LLMGateway(default_model="groq/qwen-2.5-72b")
        result = await gateway.complete([Message(role="user", content="트레이스")])

    assert result._fallback_used == "layer2_regex_inject"
    assert result._fallback_pattern == "tool_call_xml"


@pytest.mark.asyncio
async def test_layer2_json_codeblock_pattern() -> None:
    """Layer 2 — json_codeblock 패턴: _fallback_pattern == 'json_codeblock'."""
    content = '```json\n{"name": "analyze_error", "arguments": {"code": "E500"}}\n```'
    fake = _make_litellm_response(content=content)
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=AsyncMock(return_value=fake)):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        result = await gateway.complete([Message(role="user", content="분석")])

    assert result._fallback_used == "layer2_regex_inject"
    assert result._fallback_pattern == "json_codeblock"


@pytest.mark.asyncio
async def test_layer2_python_tag_pattern() -> None:
    """Layer 2 — python_tag 패턴 (Llama 3.1): _fallback_pattern == 'python_tag'."""
    content = '<|python_tag|>search_kb.call({"keyword": "timeout"})'
    fake = _make_litellm_response(content=content)
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=AsyncMock(return_value=fake)):
        gateway = LLMGateway(default_model="groq/llama-3.1-70b-versatile")
        result = await gateway.complete([Message(role="user", content="검색")])

    assert result._fallback_used == "layer2_regex_inject"
    assert result._fallback_pattern == "python_tag"


# ---------------------------------------------------------------------------
# Layer 1 + Layer 2 동시: layer2 가 layer1 을 덮어씀
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer1_then_layer2_metadata() -> None:
    """Layer 1 retry 후 Layer 2 도 inject → _fallback_used == 'layer2_regex_inject'."""
    retry_content = '<function=search_logs>{"query": "retry"}</function>'
    retry_response = _make_litellm_response(content=retry_content)
    call_count = 0

    async def side_effect(**kwargs: object) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise litellm.exceptions.BadRequestError(
                message="tool_use_failed: parser error",
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

    # Layer 2 가 마지막으로 세팅 → layer2_regex_inject
    assert result._fallback_used == "layer2_regex_inject"
    assert result._fallback_pattern == "function_xml"
