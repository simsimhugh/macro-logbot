"""신규 LangGraph 노드 단위 테스트 (intake / crystallize_report / finalize).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.2 — PR #23 task-MVP-001-x
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from macro_logbot.agent.core import (
    AgentState,
    Location,
    Report,
    _crystallize_report_node,
    _finalize_node,
    _intake_node,
    run_agent,
)
from macro_logbot.gateway import (  # noqa: E402
    ChatCompletionResponse,
    Choice,
    FunctionCall,
    LLMGateway,
    Message,
    ToolCall,
    Usage,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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
                message=Message(role="assistant", content=content, tool_calls=tool_calls),
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


def _base_state(messages: list[Message]) -> AgentState:
    """테스트용 최소 AgentState."""
    return AgentState(
        messages=messages,
        iteration=0,
        max_iters=20,
        last_response=None,
        report=None,
        session_id=None,
        event_id=None,
        _model=None,
        _generation_kwargs={},
        _gateway=LLMGateway.__new__(LLMGateway),  # 노드 테스트에선 미사용
    )


# ---------------------------------------------------------------------------
# intake_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_node_adds_system_context() -> None:
    """intake_node 가 user message 에서 파싱 후 system 메시지를 prepend 한다."""
    log = "2026-05-19 10:00:00 ERROR: DB connection failed"
    state = _base_state([Message(role="user", content=log)])
    result = await _intake_node(state)

    assert result["messages"][0].role == "system"
    content = result["messages"][0].content
    assert content is not None
    assert content.startswith("[INTAKE]")
    assert "ERROR" in content
    # 원본 user message 는 보존됨.
    assert result["messages"][1].role == "user"


@pytest.mark.asyncio
async def test_intake_node_empty_log_noop() -> None:
    """빈 log_text 는 그대로 통과 (no-op)."""
    state = _base_state([Message(role="user", content="")])
    result = await _intake_node(state)
    # system message 추가 없이 원본 그대로.
    assert len(result["messages"]) == 1
    assert result["messages"][0].role == "user"


@pytest.mark.asyncio
async def test_intake_node_no_user_message_noop() -> None:
    """user message 가 없으면 no-op."""
    state = _base_state([Message(role="system", content="you are an assistant")])
    result = await _intake_node(state)
    assert len(result["messages"]) == 1


@pytest.mark.asyncio
async def test_intake_node_no_duplicate_on_reentry() -> None:
    """이미 [INTAKE] system 메시지가 있으면 중복 추가 방지."""
    intake_msg = Message(
        role="system",
        content="[INTAKE] level=ERROR, time=2026-05-19T10:00:00, hint=x",
    )
    user_msg = Message(role="user", content="2026-05-19 10:00:00 ERROR: repeat")
    state = _base_state([intake_msg, user_msg])
    result = await _intake_node(state)
    # [INTAKE] system 메시지가 1개만 유지.
    system_msgs = [m for m in result["messages"] if m.role == "system"]
    assert len(system_msgs) == 1


@pytest.mark.asyncio
async def test_intake_node_preserves_existing_persona_system_prompt() -> None:
    """기존 ANALYZE_PROMPT 같은 persona system 메시지가 0번째 자리 보존되는지.

    PR #23 code-r WARN-2 fix — 가드가 startswith("[INTAKE]") 만 보면 ANALYZE_PROMPT
    뒤에 INTAKE 가 prepend 되어 system 순서가 역전되는 버그 확인.
    """
    persona_msg = Message(role="system", content="You are an expert error analyst.")
    user_msg = Message(role="user", content="2026-05-19 10:00:00 ERROR: boom")
    state = _base_state([persona_msg, user_msg])
    result = await _intake_node(state)

    msgs = result["messages"]
    # 첫 번째는 여전히 persona system, [INTAKE] 는 그 뒤.
    assert msgs[0].role == "system"
    assert msgs[0].content == "You are an expert error analyst."
    assert msgs[1].role == "system"
    assert msgs[1].content is not None
    assert msgs[1].content.startswith("[INTAKE]")
    # user 메시지는 system 뒤.
    assert msgs[2].role == "user"


@pytest.mark.asyncio
async def test_intake_node_guard_works_when_intake_not_first() -> None:
    """[INTAKE] system 이 0번째가 아닐 때도 재진입 가드 작동 확인 (any 패턴).

    이전 버그: 가드가 `msgs[0].content.startswith("[INTAKE]")` 만 보면 persona system
    이 0번째에 있을 때 INTAKE 가 누적 prepend.
    """
    persona_msg = Message(role="system", content="You are an expert.")
    intake_msg = Message(role="system", content="[INTAKE] level=ERROR, time=x, hint=y")
    user_msg = Message(role="user", content="ERROR: again")
    state = _base_state([persona_msg, intake_msg, user_msg])
    result = await _intake_node(state)

    intake_msgs = [
        m
        for m in result["messages"]
        if m.role == "system" and m.content and m.content.startswith("[INTAKE]")
    ]
    assert len(intake_msgs) == 1


# ---------------------------------------------------------------------------
# crystallize_report_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crystallize_report_extracts_location_from_text() -> None:
    """*.py:N 패턴이 있으면 Location 으로 추출된다."""
    content = "원인: src/macro_logbot/agent/core.py:42 에서 NPE 발생"
    state = _base_state(
        [
            Message(role="user", content="log"),
            Message(role="assistant", content=content),
        ]
    )
    result = await _crystallize_report_node(state)
    report = result["report"]
    assert isinstance(report, Report)
    assert report.location is not None
    assert isinstance(report.location, Location)
    assert report.location.file == "src/macro_logbot/agent/core.py"
    assert report.location.line == 42


@pytest.mark.asyncio
async def test_crystallize_report_no_location_when_no_py_path() -> None:
    """파일 경로가 없으면 location=None."""
    content = "원인: 단순 로직 오류"
    state = _base_state(
        [
            Message(role="user", content="log"),
            Message(role="assistant", content=content),
        ]
    )
    result = await _crystallize_report_node(state)
    report = result["report"]
    assert isinstance(report, Report)
    assert report.location is None


@pytest.mark.asyncio
async def test_crystallize_report_line_zero_returns_none() -> None:
    """LLM 답변에 `file.py:0` 같이 line=0 매칭 — Location.line ge=1 ValidationError 가드.

    이전엔 graph 가 ValidationError 로 crash 했음 (PR #23 code-r WARN-1 fix).
    """
    content = "에러 위치 foo.py:0 — 0번 줄 표기 (line 1-indexed 위반)"
    state = _base_state(
        [
            Message(role="user", content="log"),
            Message(role="assistant", content=content),
        ]
    )
    result = await _crystallize_report_node(state)
    report = result["report"]
    assert isinstance(report, Report)
    # ValidationError 잡고 location=None 으로 fall-through.
    assert report.location is None


@pytest.mark.asyncio
async def test_crystallize_report_returns_default_confidence() -> None:
    """confidence 는 항상 0.5 (placeholder)."""
    state = _base_state(
        [
            Message(role="assistant", content="some analysis"),
        ]
    )
    result = await _crystallize_report_node(state)
    assert result["report"] is not None
    assert result["report"].confidence == 0.5


@pytest.mark.asyncio
async def test_crystallize_report_uses_last_assistant_message() -> None:
    """여러 assistant 메시지 중 마지막 것이 사용된다."""
    state = _base_state(
        [
            Message(role="user", content="log"),
            Message(role="assistant", content="first answer"),
            Message(role="user", content="follow-up"),
            Message(role="assistant", content="final answer here"),
        ]
    )
    result = await _crystallize_report_node(state)
    assert result["report"] is not None
    assert result["report"].root_cause == "final answer here"


@pytest.mark.asyncio
async def test_crystallize_report_empty_messages_uses_empty_string() -> None:
    """assistant 메시지가 전혀 없으면 빈 문자열로 Report 생성."""
    state = _base_state([Message(role="user", content="log")])
    result = await _crystallize_report_node(state)
    assert result["report"] is not None
    assert result["report"].root_cause == ""


# ---------------------------------------------------------------------------
# finalize_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_node_passthrough() -> None:
    """finalize_node 는 state 를 그대로 반환한다 (no-op)."""
    msgs = [Message(role="user", content="x")]
    state = _base_state(msgs)
    result = await _finalize_node(state)
    assert result["messages"] == msgs
    assert result["iteration"] == 0
    assert result["report"] is None


# ---------------------------------------------------------------------------
# full graph integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_runs_all_6_nodes(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """intake → llm_call → execute_tools → llm_call → crystallize → finalize 전체 flow."""
    import pathlib

    tmp = pathlib.Path(str(tmp_path))
    monkeypatch.chdir(tmp)
    (tmp / "file.txt").write_text("hello\n", encoding="utf-8")

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
    second = _resp(content="분석 완료: src/main.py:10 에서 오류 발생")
    gw = _mock_gateway([first, second])

    result = await run_agent(
        [Message(role="user", content="2026-05-19 10:00:00 ERROR: test log")],
        gw,
    )

    # LLM 2회 호출 (tool_call → final).
    assert result.iterations == 2
    assert result.response.choices[0].message.content is not None
    assert "분석 완료" in result.response.choices[0].message.content

    # report 가 생성됨.
    assert result.report is not None
    assert isinstance(result.report, Report)
    # location 추출 — src/main.py:10
    assert result.report.location is not None
    assert result.report.location.file == "src/main.py"
    assert result.report.location.line == 10

    # messages 에 intake system 메시지가 포함됨.
    system_msgs = [m for m in result.messages if m.role == "system"]
    assert any(m.content and "[INTAKE]" in m.content for m in system_msgs)


@pytest.mark.asyncio
async def test_max_iters_still_runs_crystallize() -> None:
    """max_iters 도달 시에도 crystallize_report 를 거쳐 Report 가 생성된다."""
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
    # max_iters=2 → 2회 llm_call 후 crystallize 로 빠져나감.
    # choices 가 있는 마지막 응답이 tool_calls 만 가짐 → last assistant content 는 None.
    gw = _mock_gateway([forever] * 10)
    result = await run_agent(
        [Message(role="user", content="loop test")],
        gw,
        max_iters=2,
    )

    assert result.iterations == 2
    # crystallize 가 실행됐으므로 report 는 None 이 아님.
    assert result.report is not None
    assert isinstance(result.report, Report)
    # assistant content 가 없으므로 root_cause 는 빈 문자열.
    assert result.report.root_cause == ""
