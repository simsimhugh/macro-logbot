"""context truncate 단위 테스트 (task-AGENT-010).

_truncate_messages 의 4가지 핵심 동작을 검증:
  1. 작은 limit + 큰 누적 messages → truncate 실행.
  2. truncate 후 token count ≤ limit × 0.80 (high-watermark 기준).
  3. system prompt + 최신 user message 항상 보존.
  4. context limit 미달 시 truncate 안 함 — 원본 리스트 그대로.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_logbot.agent.core import _truncate_messages
from macro_logbot.gateway import Message


def _sys(content: str = "system prompt") -> Message:
    return Message(role="system", content=content)


def _user(content: str = "user query") -> Message:
    return Message(role="user", content=content)


def _assistant_tool(content: str | None = None) -> Message:
    """tool_calls 를 갖는 assistant 메시지 (content 없음)."""
    from macro_logbot.gateway import FunctionCall, ToolCall

    return Message(
        role="assistant",
        content=content,
        tool_calls=[
            ToolCall(
                id="call-x",
                function=FunctionCall(name="read_file", arguments='{"path":"f"}'),
            )
        ],
    )


def _tool(content: str = "tool result") -> Message:
    return Message(role="tool", tool_call_id="call-x", name="read_file", content=content)


def _assistant_final(content: str = "final answer") -> Message:
    return Message(role="assistant", content=content, tool_calls=None)


# ---------------------------------------------------------------------------
# 테스트용 token_counter 패치 — 메시지 수 × 100 tokens 로 단순 계산.
# ---------------------------------------------------------------------------


def _fake_token_counter(model: str, messages: list) -> int:  # noqa: ARG001
    return len(messages) * 100


@pytest.fixture(autouse=True)
def _patch_token_counter():
    with patch("macro_logbot.agent.core.litellm.token_counter", side_effect=_fake_token_counter):
        yield


# ---------------------------------------------------------------------------
# 테스트 1: limit=1000, 메시지 12개(1200 tokens) → truncate 실행.
# ---------------------------------------------------------------------------


def test_truncate_fires_when_over_high_watermark() -> None:
    """1200 tokens > 1000 × 80% = 800 → truncate 가 실행된다."""
    msgs = [
        _sys(),
        _user(),
        _assistant_tool(),
        _tool("r1"),
        _assistant_tool(),
        _tool("r2"),
        _assistant_tool(),
        _tool("r3"),
        _assistant_tool(),
        _tool("r4"),
        _assistant_tool(),
        _tool("r5"),
    ]  # 12 * 100 = 1200 tokens
    result = _truncate_messages(msgs, model="openai/gpt-4o-mini", limit=1000)
    assert len(result) < len(msgs), "truncate 가 실행되어야 한다"


# ---------------------------------------------------------------------------
# 테스트 2: truncate 후 token count ≤ limit × 0.80.
# ---------------------------------------------------------------------------


def test_truncate_result_within_high_watermark() -> None:
    """truncate 후 남은 메시지 token count ≤ limit × 0.80."""
    limit = 1000
    high = int(limit * 0.80)
    msgs = [
        _sys(),
        _user(),
        *[m for pair in [(_assistant_tool(), _tool(f"r{i}")) for i in range(8)] for m in pair],
    ]  # 2 + 16 = 18 메시지 → 1800 tokens
    result = _truncate_messages(msgs, model=None, limit=limit)
    token_count = len(result) * 100  # fake_token_counter 와 동일 계산
    assert token_count <= high, f"after={token_count}, high={high}"


# ---------------------------------------------------------------------------
# 테스트 3: system prompt + 최신 user message 항상 보존.
# ---------------------------------------------------------------------------


def test_system_and_latest_user_always_preserved() -> None:
    """truncate 후에도 system / user 메시지는 반드시 남아있어야 한다."""
    sys_msg = _sys("ANALYZE_SYSTEM_PROMPT")
    user_msg = _user("stderr: NullPointerException at line 42")
    msgs = [
        sys_msg,
        user_msg,
        *[m for pair in [(_assistant_tool(), _tool(f"r{i}")) for i in range(8)] for m in pair],
    ]
    result = _truncate_messages(msgs, model=None, limit=1000)
    roles = [m.role for m in result]
    assert "system" in roles, "system 메시지가 보존되어야 한다"
    assert "user" in roles, "user 메시지가 보존되어야 한다"
    # 원본 system/user 객체가 동일한지 확인.
    result_systems = [m for m in result if m.role == "system"]
    result_users = [m for m in result if m.role == "user"]
    assert any(m is sys_msg for m in result_systems), "원본 system 메시지 객체가 보존되어야 한다"
    assert any(m is user_msg for m in result_users), "원본 user 메시지 객체가 보존되어야 한다"


# ---------------------------------------------------------------------------
# 테스트 4: context limit 미달 시 truncate 안 함.
# ---------------------------------------------------------------------------


def test_no_truncate_when_under_limit() -> None:
    """token count < limit × 80% 이면 원본 리스트를 그대로 반환한다."""
    msgs = [_sys(), _user(), _assistant_final()]  # 3 * 100 = 300 tokens
    result = _truncate_messages(msgs, model=None, limit=1000)
    # 300 < 800 → 변경 없음.
    assert result is msgs or result == msgs, "truncate 없이 원본을 반환해야 한다"
    assert len(result) == len(msgs)


# ---------------------------------------------------------------------------
# 테스트 5: tool_call_id pair-atomicity — assistant(tool_calls) + tool 묶음 단위 제거.
# ---------------------------------------------------------------------------


def _assistant_tool_with_id(call_id: str) -> Message:
    """지정된 call_id 를 가진 assistant(tool_calls) 메시지."""
    from macro_logbot.gateway import FunctionCall, ToolCall

    return Message(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id=call_id,
                function=FunctionCall(name="read_file", arguments='{"path":"f"}'),
            )
        ],
    )


def _tool_with_id(call_id: str, content: str = "tool result") -> Message:
    """지정된 tool_call_id 를 가진 tool 메시지."""
    return Message(role="tool", tool_call_id=call_id, name="read_file", content=content)


def test_truncate_preserves_tool_call_pair_atomicity() -> None:
    """truncate 시 assistant(tool_calls) + 대응 tool 메시지를 group 단위로 제거한다.

    group 단위 제거이므로 제거된 group 에 속한 모든 메시지가 함께 사라져야 하고,
    보존된 group 의 메시지는 온전히 남아있어야 한다.
    """
    # group-A: call-a (오래된 turn — 제거 대상)
    # group-B: call-b (중간 turn — 제거 대상)
    # group-C: call-c (최근 turn 1 — 보존)
    # group-D: call-d (최근 turn 2 — 보존)
    msgs = [
        _sys(),
        _user(),
        _assistant_tool_with_id("call-a"),  # group-A start
        _tool_with_id("call-a", "res-a"),  # group-A end
        _assistant_tool_with_id("call-b"),  # group-B start
        _tool_with_id("call-b", "res-b"),  # group-B end
        _assistant_tool_with_id("call-c"),  # group-C start (보존)
        _tool_with_id("call-c", "res-c"),  # group-C end  (보존)
        _assistant_tool_with_id("call-d"),  # group-D start (보존)
        _tool_with_id("call-d", "res-d"),  # group-D end  (보존)
    ]  # 10 * 100 = 1000 tokens > 1000 * 80% = 800 → truncate 실행

    result = _truncate_messages(msgs, model=None, limit=1000)

    result_ids = {m.tool_call_id for m in result if m.role == "tool"}
    result_call_ids = {
        tc.id for m in result if m.role == "assistant" and m.tool_calls for tc in m.tool_calls
    }

    # group-C, group-D 는 보존되어야 한다.
    assert "call-c" in result_ids, "최근 group-C tool 메시지가 보존되어야 한다"
    assert "call-d" in result_ids, "최근 group-D tool 메시지가 보존되어야 한다"
    assert "call-c" in result_call_ids, "최근 group-C assistant 메시지가 보존되어야 한다"
    assert "call-d" in result_call_ids, "최근 group-D assistant 메시지가 보존되어야 한다"

    # 제거된 group 은 assistant + tool 이 함께 사라져야 한다 (pair-atomic).
    removed_tool_ids = {"call-a", "call-b"} - result_ids
    removed_call_ids = {"call-a", "call-b"} - result_call_ids
    # 둘 다 사라졌거나 둘 다 남아있어야 한다 (pair-atomic 보장).
    assert removed_tool_ids == removed_call_ids, (
        f"pair-atomic 위반: tool 제거={removed_tool_ids}, assistant 제거={removed_call_ids}"
    )


def test_truncate_no_orphan_tool_message() -> None:
    """truncate 후 모든 tool 메시지는 대응하는 assistant.tool_calls 가 존재해야 한다.

    즉 tool.tool_call_id 가 어떤 assistant message 의 tool_calls[*].id 에 있어야 한다.
    """
    msgs = [
        _sys(),
        _user(),
        _assistant_tool_with_id("call-1"),
        _tool_with_id("call-1", "r1"),
        _assistant_tool_with_id("call-2"),
        _tool_with_id("call-2", "r2"),
        _assistant_tool_with_id("call-3"),
        _tool_with_id("call-3", "r3"),
        _assistant_tool_with_id("call-4"),
        _tool_with_id("call-4", "r4"),
        _assistant_tool_with_id("call-5"),
        _tool_with_id("call-5", "r5"),
    ]  # 12 * 100 = 1200 tokens > 800 → truncate 실행

    result = _truncate_messages(msgs, model=None, limit=1000)

    # 결과에서 assistant message 의 모든 tool_call_id 수집.
    known_call_ids: set[str] = {
        tc.id
        for m in result
        if m.role == "assistant" and m.tool_calls
        for tc in m.tool_calls
        if tc.id is not None
    }
    # 모든 tool 메시지의 tool_call_id 가 known_call_ids 에 있어야 한다.
    for m in result:
        if m.role == "tool":
            assert m.tool_call_id in known_call_ids, (
                f"orphan tool 메시지 발견: tool_call_id={m.tool_call_id!r} 에 대응하는 "
                f"assistant message 없음. 남은 known_call_ids={known_call_ids}"
            )
