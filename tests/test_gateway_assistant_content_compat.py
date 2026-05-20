"""DS API Gateway 호환 — tool_calls 있는 assistant 메시지에 content 필드 필수.

사내 gateway 규칙: assistant + tool_calls + content=null/missing → 422 Unprocessable
Entity. `model_dump(exclude_none=True)` 가 content=None 시 key 자체를 제외하므로
명시적 content="" 보강.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_logbot.gateway.client import LLMGateway
from macro_logbot.gateway.models import FunctionCall, Message, ToolCall


def _tc(name: str, args: str = "{}") -> ToolCall:
    return ToolCall(id="call-1", function=FunctionCall(name=name, arguments=args))


@pytest.mark.asyncio
async def test_assistant_with_tool_calls_gets_empty_content() -> None:
    """assistant + tool_calls + content=None → content='' 자동 보강."""
    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop")

    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content=None, tool_calls=[_tc("read_file")]),
    ]
    gw = LLMGateway()
    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete(messages, model="m")

    raw_messages = captured[0]["messages"]
    # 두 번째 메시지: assistant + tool_calls + content="" 보강 확인
    asst = raw_messages[1]
    assert asst["role"] == "assistant"
    assert "tool_calls" in asst
    assert asst["content"] == "", f"expected '', got {asst.get('content')!r}"


@pytest.mark.asyncio
async def test_assistant_with_existing_content_preserved() -> None:
    """assistant + tool_calls + content='ok' → content 보존 (덮어쓰지 않음)."""
    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop")

    messages = [
        Message(role="assistant", content="reasoning here", tool_calls=[_tc("read_file")]),
    ]
    gw = LLMGateway()
    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete(messages, model="m")

    asst = captured[0]["messages"][0]
    assert asst["content"] == "reasoning here"


@pytest.mark.asyncio
async def test_user_message_unchanged() -> None:
    """user 메시지는 영향 없음 (assistant 만 보강)."""
    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop")

    messages = [Message(role="user", content="hello")]
    gw = LLMGateway()
    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete(messages, model="m")

    user = captured[0]["messages"][0]
    assert user == {"role": "user", "content": "hello"}


@pytest.mark.asyncio
async def test_assistant_without_tool_calls_can_have_no_content() -> None:
    """assistant + content=None + tool_calls 없음 → content key 그대로 미포함
    (assistant 최종 답변 같은 edge case, 보강은 tool_calls 있을 때만)."""
    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop")

    messages = [Message(role="assistant", content=None)]
    gw = LLMGateway()
    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete(messages, model="m")

    asst = captured[0]["messages"][0]
    # tool_calls 없으므로 content 보강 안 함 — None 은 exclude_none 으로 제외됨
    assert "content" not in asst
    assert "tool_calls" not in asst


@pytest.mark.asyncio
async def test_tool_message_unchanged() -> None:
    """tool result 메시지는 영향 없음."""
    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop")

    messages = [Message(role="tool", content="{}", tool_call_id="call-1")]
    gw = LLMGateway()
    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete(messages, model="m")

    tool = captured[0]["messages"][0]
    assert tool == {"role": "tool", "content": "{}", "tool_call_id": "call-1"}
