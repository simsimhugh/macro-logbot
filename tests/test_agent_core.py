"""Agent loop 단위 테스트 (mocked gateway)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from macro_logbot.agent.core import MAX_ITERS_DEFAULT, run_agent
from macro_logbot.gateway import (
    ChatCompletionResponse,
    Choice,
    FunctionCall,
    LLMGateway,
    Message,
    ToolCall,
    Usage,
)


def _resp(
    content: str | None = None,
    tool_calls: list[ToolCall] | None = None,
    finish_reason: str = "stop",
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-test",
        object="chat.completion",
        created=int(time.time()),
        model="openai/gpt-4o-mini",
        choices=[
            Choice(
                index=0,
                message=Message(
                    role="assistant", content=content, tool_calls=tool_calls
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


def _mock_gateway(responses: list[ChatCompletionResponse]) -> LLMGateway:
    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    gw.complete = AsyncMock(side_effect=responses)  # type: ignore[method-assign]
    return gw


@pytest.mark.asyncio
async def test_run_agent_no_tool_calls_returns_immediately() -> None:
    gw = _mock_gateway([_resp(content="done", tool_calls=None)])
    result = await run_agent([Message(role="user", content="hi")], gw)
    assert result.iterations == 1
    assert result.response.choices[0].message.content == "done"
    # messages: [user, assistant].
    assert len(result.messages) == 2


@pytest.mark.asyncio
async def test_run_agent_executes_tool_round_trip(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_text("alpha\n", encoding="utf-8")

    first = _resp(
        content=None,
        tool_calls=[
            ToolCall(
                id="call-1",
                function=FunctionCall(
                    name="read_file",
                    arguments='{"path": "file.txt"}',
                ),
            )
        ],
        finish_reason="tool_calls",
    )
    second = _resp(content="analysis complete")
    gw = _mock_gateway([first, second])

    result = await run_agent([Message(role="user", content="read the file")], gw)
    assert result.iterations == 2
    assert result.response.choices[0].message.content == "analysis complete"
    # messages: [user, assistant(tool_calls), tool(result), assistant(final)]
    assert len(result.messages) == 4
    tool_msg = result.messages[2]
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == "call-1"
    assert tool_msg.content is not None
    assert "alpha" in tool_msg.content


@pytest.mark.asyncio
async def test_run_agent_handles_invalid_json_arguments(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    bad = _resp(
        content=None,
        tool_calls=[
            ToolCall(
                id="call-bad",
                function=FunctionCall(name="read_file", arguments="{not json"),
            )
        ],
        finish_reason="tool_calls",
    )
    final = _resp(content="recovered")
    gw = _mock_gateway([bad, final])

    result = await run_agent([Message(role="user", content="x")], gw)
    tool_msg = result.messages[2]
    assert tool_msg.role == "tool"
    assert tool_msg.content is not None
    assert "invalid JSON" in tool_msg.content


@pytest.mark.asyncio
async def test_run_agent_tool_error_propagates_to_messages(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    # read_file 에 path traversal — error 가 tool message 로 들어가야 한다.
    first = _resp(
        content=None,
        tool_calls=[
            ToolCall(
                id="call-x",
                function=FunctionCall(
                    name="read_file",
                    arguments='{"path": "../../etc/passwd"}',
                ),
            )
        ],
        finish_reason="tool_calls",
    )
    final = _resp(content="ok")
    gw = _mock_gateway([first, final])
    result = await run_agent([Message(role="user", content="x")], gw)
    tool_msg = result.messages[2]
    assert tool_msg.content is not None
    assert "outside working directory" in tool_msg.content


@pytest.mark.asyncio
async def test_run_agent_max_iters_termination() -> None:
    # 매번 tool_call 만 반환 → max_iters 도달 시 종료.
    forever = _resp(
        content=None,
        tool_calls=[
            ToolCall(
                id="loop",
                function=FunctionCall(name="list_directory", arguments="{}"),
            )
        ],
        finish_reason="tool_calls",
    )
    gw = _mock_gateway([forever] * 10)
    result = await run_agent(
        [Message(role="user", content="loop")], gw, max_iters=3
    )
    assert result.iterations == 3
    assert gw.complete.call_count == 3  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_run_agent_default_max_iters_constant() -> None:
    assert MAX_ITERS_DEFAULT == 8
