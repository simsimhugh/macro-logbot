"""task-AGENT-022 — agent 의 same-tool-args repeat detection (무한 loop break).

PR #54 baseline 후 발견된 패턴: agent 가 같은 (tool_name, args) 를 연속 반복하다
max_iters 도달 → final answer 없음 → 1-A=0.000. E001 N2 의 40-message 무한 loop
사례가 직접 motivation.
"""

from __future__ import annotations

from macro_logbot.agent.core import (
    REPEAT_TOOL_CALL_THRESHOLD,
    _is_repeating_tool_calls,
    _route_after_llm,
    _tool_call_signature,
)
from macro_logbot.gateway.models import FunctionCall, Message, ToolCall


def _tc(name: str, args: str, id_: str = "call-1") -> ToolCall:
    return ToolCall(id=id_, function=FunctionCall(name=name, arguments=args))


def _asst(*tool_calls: ToolCall) -> Message:
    return Message(role="assistant", content="", tool_calls=list(tool_calls))


def _tool_result(content: str = "ok", id_: str = "call-1") -> Message:
    return Message(role="tool", content=content, tool_call_id=id_)


# ---------------------------------------------------------------------------
# _tool_call_signature
# ---------------------------------------------------------------------------


def test_signature_returns_sorted_name_args_tuple() -> None:
    msg = _asst(_tc("read_file", '{"path":"/x"}', "c1"))
    sig = _tool_call_signature(msg)
    assert sig == (("read_file", '{"path":"/x"}'),)


def test_signature_returns_none_for_non_assistant() -> None:
    assert _tool_call_signature(Message(role="user", content="hi")) is None
    assert _tool_call_signature(_tool_result()) is None


def test_signature_returns_none_for_assistant_without_tool_calls() -> None:
    assert _tool_call_signature(Message(role="assistant", content="final")) is None


def test_signature_sorts_multiple_tool_calls() -> None:
    msg = _asst(
        _tc("grep_codebase", '{"q":"X"}', "c2"),
        _tc("read_file", '{"path":"/x"}', "c1"),
    )
    sig = _tool_call_signature(msg)
    # sorted by (name, args) tuple
    assert sig == (("grep_codebase", '{"q":"X"}'), ("read_file", '{"path":"/x"}'))


# ---------------------------------------------------------------------------
# _is_repeating_tool_calls
# ---------------------------------------------------------------------------


def test_repeat_detected_when_threshold_consecutive_same_signature() -> None:
    """최근 3 회 assistant tool_call 이 모두 같은 signature → True."""
    same = _tc("read_file", '{"path":"/x"}')
    messages = [
        Message(role="user", content="q"),
        _asst(same),
        _tool_result(),
        _asst(same),
        _tool_result(),
        _asst(same),
    ]
    assert _is_repeating_tool_calls(messages, threshold=3) is True


def test_repeat_not_detected_when_below_threshold() -> None:
    """N=2 회 반복은 threshold(3) 미만 → False."""
    same = _tc("read_file", '{"path":"/x"}')
    messages = [
        _asst(same),
        _tool_result(),
        _asst(same),
    ]
    assert _is_repeating_tool_calls(messages, threshold=3) is False


def test_repeat_not_detected_when_diverse() -> None:
    """signature 가 다르면 → False (정상 분석 진행)."""
    messages = [
        _asst(_tc("read_file", '{"path":"/x"}')),
        _tool_result(),
        _asst(_tc("grep_codebase", '{"q":"X"}')),
        _tool_result(),
        _asst(_tc("read_file", '{"path":"/y"}')),
    ]
    assert _is_repeating_tool_calls(messages, threshold=3) is False


def test_repeat_ignores_non_tool_call_messages_in_count() -> None:
    """tool result message 들은 count 에서 제외 — assistant tool_call message 만 본다."""
    same = _tc("read_file", '{"path":"/x"}')
    # assistant tool_call 만 3 회 (tool result 사이사이)
    messages = [
        _asst(same),
        _tool_result(),
        _tool_result(),  # extra tool message
        _asst(same),
        _tool_result(),
        _asst(same),
    ]
    assert _is_repeating_tool_calls(messages, threshold=3) is True


def test_repeat_empty_messages_returns_false() -> None:
    assert _is_repeating_tool_calls([], threshold=3) is False


# ---------------------------------------------------------------------------
# _route_after_llm — integration
# ---------------------------------------------------------------------------


def _state(messages: list[Message], iteration: int = 1, max_iters: int = 20) -> dict:
    """AgentState 의 minimal dict (routing 함수만 보면 됨)."""
    return {  # type: ignore[return-value]
        "messages": messages,
        "iteration": iteration,
        "max_iters": max_iters,
    }


def test_route_breaks_on_repeated_tool_calls() -> None:
    """task-AGENT-022 핵심 — 같은 tool_call 3 회 연속 시 crystallize_report 로 break."""
    same = _tc("read_file", '{"path":"/x"}')
    messages = [
        _asst(same),
        _tool_result(),
        _asst(same),
        _tool_result(),
        _asst(same),  # 3rd repeat
    ]
    assert _route_after_llm(_state(messages, iteration=5)) == "crystallize_report"


def test_route_continues_on_diverse_tool_calls() -> None:
    """signature 가 다르면 execute_tools 로 정상 진행."""
    messages = [
        _asst(_tc("read_file", '{"path":"/x"}')),
        _tool_result(),
        _asst(_tc("grep_codebase", '{"q":"X"}')),
        _tool_result(),
        _asst(_tc("read_file", '{"path":"/y"}')),  # 다른 args
    ]
    assert _route_after_llm(_state(messages, iteration=5)) == "execute_tools"


def test_route_breaks_on_max_iters() -> None:
    """max_iters 도달 시 crystallize_report (기존 동작 보존)."""
    messages = [_asst(_tc("read_file", '{"path":"/x"}'))]
    assert _route_after_llm(_state(messages, iteration=20, max_iters=20)) == "crystallize_report"


def test_threshold_constant_is_3() -> None:
    """REPEAT_TOOL_CALL_THRESHOLD 의 default 가 3 인지 — 변경 시 의도 확인."""
    assert REPEAT_TOOL_CALL_THRESHOLD == 3
