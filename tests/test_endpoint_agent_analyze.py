"""POST /agent/analyze 엔드포인트 통합 테스트."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from macro_logbot.agent.core import AgentRunResult, Report
from macro_logbot.app import app, get_gateway
from macro_logbot.gateway import LLMGateway
from macro_logbot.gateway.models import (
    ChatCompletionResponse,
    Choice,
    Message,
    Usage,
)


def _final_response(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-analyze",
        object="chat.completion",
        created=int(time.time()),
        model="openai/gpt-4o-mini",
        choices=[
            Choice(
                index=0,
                message=Message(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


@pytest.fixture(autouse=True)
def reset_app_singletons() -> Iterator[None]:
    """각 테스트 전후로 app 모듈 레벨 singleton 을 초기화.

    _reset_singletons_for_test() 를 사용해 monkeypatch internal 의존 없이
    격리 보장 (code-r WARN-3 from PR #25).
    실제 SQLite DB 생성 없이 테스트 격리 보장.
    """
    import macro_logbot.app as app_module
    from macro_logbot.session import InMemorySessionStore

    app_module._reset_singletons_for_test()
    # _get_session_store() 가 호출되기 전에 InMemorySessionStore 로 pre-set.
    app_module._session_store = InMemorySessionStore()  # type: ignore[assignment]
    yield
    app_module._reset_singletons_for_test()


@pytest.fixture
def client_with_mock_gateway() -> Iterator[TestClient]:
    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    app.dependency_overrides[get_gateway] = lambda: gw
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_agent_analyze_happy_path(
    client_with_mock_gateway: TestClient,
) -> None:
    fake = AgentRunResult(
        response=_final_response("원인: DB 연결 실패. 조치: ..."),
        iterations=2,
        messages=[],
        report=Report(
            root_cause="원인: DB 연결 실패. 조치: ...",
            location=None,
            fix_hint="원인: DB 연결 실패. 조치: ...",
            confidence=0.5,
            reasoning_summary="원인: DB 연결 실패. 조치: ...",
        ),
    )
    log_text = (
        "2026-05-19 14:30:01 ERROR: DB connection failed\n"
        "Traceback (most recent call last):\n"
        "ConnectionError: refused\n"
    )
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": log_text},
        )
    assert response.status_code == 200
    body = response.json()
    assert "DB 연결 실패" in body["analysis"]
    assert body["iterations"] == 2
    record = body["record"]
    assert record["level"] == "ERROR"
    assert "DB connection failed" in record["message"]
    assert record["traceback"] is not None
    # raw 는 응답 직렬화에서 자동 제외 (사내 deploy 로그 본문 노출 방지).
    assert "raw" not in record
    # final answer 도달 (tool_calls 없는 응답) — terminated_reason="final".
    assert body["terminated_reason"] == "final"
    # report 필드 존재 및 구조 검증.
    assert "report" in body
    assert body["report"] is not None
    assert "root_cause" in body["report"]
    assert "fix_hint" in body["report"]
    assert "confidence" in body["report"]
    assert "reasoning_summary" in body["report"]
    assert body["report"]["confidence"] == 0.5
    # session_id 는 task-MVP-004 (PR #24) 에서 통합 — 항상 uuid str 반환.
    assert isinstance(body["session_id"], str)
    assert len(body["session_id"]) > 0


def test_agent_analyze_max_iters_terminates_with_flag(
    client_with_mock_gateway: TestClient,
) -> None:
    """max_iters 도달 + 마지막 assistant 가 tool_calls 보유 시 terminated_reason='max_iters'."""
    from macro_logbot.agent.core import MAX_ITERS_DEFAULT
    from macro_logbot.gateway.models import FunctionCall, ToolCall

    last_with_tool_calls = ChatCompletionResponse(
        id="chatcmpl-loop",
        object="chat.completion",
        created=int(time.time()),
        model="openai/gpt-4o-mini",
        choices=[
            Choice(
                index=0,
                message=Message(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="call-x",
                            function=FunctionCall(name="read_file", arguments="{}"),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )
    fake = AgentRunResult(
        response=last_with_tool_calls,
        iterations=MAX_ITERS_DEFAULT,
        messages=[],
    )
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "loop never ends"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["terminated_reason"] == "max_iters"
    assert body["iterations"] == MAX_ITERS_DEFAULT
    # AgentRunResult.report default=None — endpoint 가 그대로 직렬화 (PR #23 test WARN-6).
    assert body["report"] is None


def test_agent_analyze_requires_log_text(
    client_with_mock_gateway: TestClient,
) -> None:
    response = client_with_mock_gateway.post("/agent/analyze", json={})
    assert response.status_code == 422


def test_agent_analyze_no_choices_returns_empty_analysis(
    client_with_mock_gateway: TestClient,
) -> None:
    empty_resp = ChatCompletionResponse(
        id="chatcmpl-empty",
        object="chat.completion",
        created=int(time.time()),
        model="openai/gpt-4o-mini",
        choices=[],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )
    fake = AgentRunResult(response=empty_resp, iterations=1, messages=[], report=None)
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "unrecognized log"},
        )
    assert response.status_code == 200
    assert response.json()["analysis"] == ""


def test_agent_analyze_response_report_with_location(
    client_with_mock_gateway: TestClient,
) -> None:
    """report 에 location 이 포함된 경우 직렬화 구조를 검증한다."""
    from macro_logbot.agent.core import Location

    fake = AgentRunResult(
        response=_final_response("원인: app/main.py:99 에서 오류"),
        iterations=1,
        messages=[],
        report=Report(
            root_cause="원인: app/main.py:99 에서 오류",
            location=Location(file="app/main.py", line=99),
            fix_hint="app/main.py:99 수정",
            confidence=0.5,
            reasoning_summary="원인: app/main.py:99 에서 오류",
        ),
    )
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "2026-05-19 10:00:00 ERROR: crash"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["report"] is not None
    loc = body["report"]["location"]
    assert loc is not None
    assert loc["file"] == "app/main.py"
    assert loc["line"] == 99


def test_agent_analyze_response_report_none_when_no_report(
    client_with_mock_gateway: TestClient,
) -> None:
    """report=None 인 AgentRunResult 에서 응답 report 필드도 null 이다."""
    fake = AgentRunResult(
        response=_final_response("분석 결과"),
        iterations=1,
        messages=[],
        report=None,
    )
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "2026-05-19 10:00:00 INFO: ok"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["report"] is None


# ---------------------------------------------------------------------------
# task-MVP-004: session_id 통합 테스트 (PR #24)
# ---------------------------------------------------------------------------


def test_agent_analyze_creates_new_session_id_when_none(
    client_with_mock_gateway: TestClient,
) -> None:
    """session_id=None 요청 → 응답에 새 uuid str session_id 반환."""
    import macro_logbot.app as app_module
    from macro_logbot.session import InMemorySessionStore

    fake = AgentRunResult(
        response=_final_response("분석 결과"),
        iterations=1,
        messages=[
            Message(role="user", content="log"),
            Message(role="assistant", content="분석 결과"),
        ],
        report=None,
    )
    mem_store = InMemorySessionStore()
    with (
        patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)),
        patch.object(app_module, "_session_store", mem_store),
    ):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "2026-05-19 10:00:00 ERROR: crash"},
        )
    assert response.status_code == 200
    body = response.json()
    session_id = body["session_id"]
    assert isinstance(session_id, str)
    assert len(session_id) == 36  # uuid4 형식


def test_agent_analyze_continues_session_on_provided_id(
    client_with_mock_gateway: TestClient,
) -> None:
    """첫 호출 session_id 를 두 번째 호출에 전달 → session messages 이어짐."""
    import macro_logbot.app as app_module
    from macro_logbot.session import InMemorySessionStore

    first_messages = [
        Message(role="user", content="first"),
        Message(role="assistant", content="first reply"),
    ]
    second_messages = [
        Message(role="user", content="second"),
        Message(role="assistant", content="second reply"),
    ]

    fake_first = AgentRunResult(
        response=_final_response("first reply"),
        iterations=1,
        messages=first_messages,
        report=None,
    )
    fake_second = AgentRunResult(
        response=_final_response("second reply"),
        iterations=1,
        messages=second_messages,
        report=None,
    )

    mem_store = InMemorySessionStore()
    with patch.object(app_module, "_session_store", mem_store):
        # 첫 번째 호출 — session 생성
        with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_first)):
            r1 = client_with_mock_gateway.post(
                "/agent/analyze",
                json={"log_text": "2026-05-19 10:00:00 ERROR: first"},
            )
        assert r1.status_code == 200
        sid = r1.json()["session_id"]

        # 두 번째 호출 — 같은 session_id 전달
        with patch(
            "macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_second)
        ) as mock_run_second:
            r2 = client_with_mock_gateway.post(
                "/agent/analyze",
                json={"log_text": "2026-05-19 10:00:00 ERROR: second", "session_id": sid},
            )
        assert r2.status_code == 200
        assert r2.json()["session_id"] == sid

        # architect WARN-1: 두 번째 run_agent 호출 시 첫 호출의 assistant 메시지가
        # 컨텍스트로 주입되어야 spec §5.4 messages 누적 의미 충족.
        call_messages = mock_run_second.call_args[0][0]
        assistant_contents = [m.content for m in call_messages if m.role == "assistant"]
        assert "first reply" in assistant_contents, (
            "두 번째 호출 시 첫 호출 assistant 응답이 컨텍스트로 주입되지 않음 — "
            f"실제 messages: {call_messages}"
        )
        # architect WARN-2: system 메시지는 매 호출마다 새로 prepend 되므로 session
        # 에 누적 저장되면 안 됨. call_messages 의 system 은 정확히 1개 (ANALYZE_PROMPT)
        # — session 에서 system 안 가져와서 prepend 1회만 발생.
        system_count = sum(1 for m in call_messages if m.role == "system")
        assert system_count == 1, (
            f"system 메시지가 1개여야 함 (ANALYZE_PROMPT 만). 실측 {system_count}개 — "
            f"session 저장 시 system strip 누락 의심"
        )

    # session 에 두 번째 호출 messages 가 저장됐는지 확인 (system 제외).
    session = mem_store.get(sid)
    assert session is not None
    # second_messages 에 원래 system 없음 → 그대로 저장됨.
    assert session.messages == second_messages


# ---------------------------------------------------------------------------
# task-KB-002: KB auto-archive 테스트 (PR #24)
# ---------------------------------------------------------------------------


def test_agent_analyze_kb_auto_archive_enabled(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MACRO_LOGBOT_KB_AUTO_ARCHIVE=true + MACRO_LOGBOT_KB_PATH 설정 → KB.add 호출."""
    import macro_logbot.app as app_module
    from macro_logbot.agent.core import Location
    from macro_logbot.session import InMemorySessionStore

    monkeypatch.setenv("MACRO_LOGBOT_KB_AUTO_ARCHIVE", "true")
    monkeypatch.setenv("MACRO_LOGBOT_KB_PATH", "/tmp/test_kb_auto.db")

    fake_report = Report(
        root_cause="NullPointerException in UserService",
        location=Location(file="src/user.py", line=42),
        fix_hint="None 체크 추가",
        confidence=0.8,
        reasoning_summary="NullPointerException in UserService",
    )
    fake = AgentRunResult(
        response=_final_response("분석 결과"),
        iterations=1,
        messages=[],
        report=fake_report,
    )

    mock_kb = MagicMock()
    mem_store = InMemorySessionStore()
    with (
        patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)),
        patch.object(app_module, "_session_store", mem_store),
        patch.object(app_module, "_kb_store", None),
        patch.object(app_module, "_get_kb_store", return_value=mock_kb),
    ):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "2026-05-19 10:00:00 ERROR: NPE"},
        )
    assert response.status_code == 200
    mock_kb.add.assert_called_once()
    # 전달된 ArchivedCase 검증
    case = mock_kb.add.call_args[0][0]
    assert case.source == "poc"
    assert case.root_cause == fake_report.root_cause
    assert case.location.file == "src/user.py"


def test_agent_analyze_kb_auto_archive_disabled_default(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MACRO_LOGBOT_KB_AUTO_ARCHIVE 미설정 → KB.add 호출 안 됨."""
    import macro_logbot.app as app_module
    from macro_logbot.agent.core import Location
    from macro_logbot.session import InMemorySessionStore

    monkeypatch.delenv("MACRO_LOGBOT_KB_AUTO_ARCHIVE", raising=False)

    fake_report = Report(
        root_cause="some error",
        location=Location(file="src/main.py", line=1),
        fix_hint="fix it",
        confidence=0.5,
        reasoning_summary="some error",
    )
    fake = AgentRunResult(
        response=_final_response("분석"),
        iterations=1,
        messages=[],
        report=fake_report,
    )

    mock_kb = MagicMock()
    mem_store = InMemorySessionStore()
    with (
        patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)),
        patch.object(app_module, "_session_store", mem_store),
        patch.object(app_module, "_get_kb_store", return_value=mock_kb),
    ):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "2026-05-19 10:00:00 ERROR: something"},
        )
    assert response.status_code == 200
    mock_kb.add.assert_not_called()


def test_agent_analyze_unknown_session_id_creates_new_session(
    client_with_mock_gateway: TestClient,
) -> None:
    """존재하지 않는 session_id 전송 — 404 대신 새 session 생성 fallback (IDOR 회피).

    test-e WARN-1 + sec WARN-4 — branch coverage 보강.
    """
    import macro_logbot.app as app_module
    from macro_logbot.session import InMemorySessionStore

    fake = AgentRunResult(
        response=_final_response("ok"),
        iterations=1,
        messages=[],
        report=None,
    )
    mem_store = InMemorySessionStore()
    with (
        patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)),
        patch.object(app_module, "_session_store", mem_store),
    ):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={
                "log_text": "2026-05-19 10:00:00 ERROR: orphan",
                "session_id": "nonexistent-uuid-deadbeef",
            },
        )
    assert response.status_code == 200
    body = response.json()
    # 전달한 id 와 다른 새 id 가 반환 — fallback create.
    assert body["session_id"] != "nonexistent-uuid-deadbeef"
    assert len(body["session_id"]) == 36  # uuid4 length


def test_agent_analyze_kb_archive_failure_keeps_200(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KB.add 실패 (disk full / permission 등) → endpoint 는 여전히 200 반환.

    code-r WARN-2 + test-e WARN-2 — KB 는 analytics side effect, 응답 계약 본체에
    영향 X. exception 은 logger.warning 후 swallow.
    """
    import macro_logbot.app as app_module
    from macro_logbot.agent.core import Location
    from macro_logbot.session import InMemorySessionStore

    monkeypatch.setenv("MACRO_LOGBOT_KB_AUTO_ARCHIVE", "true")
    monkeypatch.setenv("MACRO_LOGBOT_KB_PATH", "/tmp/test_kb_failure.db")

    fake_report = Report(
        root_cause="disk-full test",
        location=Location(file="src/x.py", line=1),
        fix_hint="x",
        confidence=0.5,
        reasoning_summary="x",
    )
    fake = AgentRunResult(
        response=_final_response("ok"),
        iterations=1,
        messages=[],
        report=fake_report,
    )

    # mock KB 의 add 가 OperationalError raise — endpoint 가 swallow 해야 200.
    failing_kb = MagicMock()
    failing_kb.add.side_effect = sqlite3.OperationalError("disk full")
    mem_store = InMemorySessionStore()
    with (
        patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)),
        patch.object(app_module, "_session_store", mem_store),
        patch.object(app_module, "_get_kb_store", return_value=failing_kb),
    ):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "2026-05-19 10:00:00 ERROR: x"},
        )
    # KB 실패에도 200 + report 정상 반환.
    assert response.status_code == 200
    body = response.json()
    assert body["report"]["root_cause"] == "disk-full test"
    failing_kb.add.assert_called_once()


# ---------------------------------------------------------------------------
# task-MVP-004-x: singleton thread-safety + AgentState session_id
# ---------------------------------------------------------------------------


def test_singleton_thread_safety_double_checked_lock() -> None:
    """10 thread 동시 호출 시 _get_session_store() 가 인스턴스 1개만 생성."""
    import threading

    import macro_logbot.app as app_module
    from macro_logbot.session import SQLiteSessionStore

    # 싱글톤 초기화 — None 상태에서 경쟁 진입 보장.
    app_module._reset_singletons_for_test()

    results: list[SQLiteSessionStore] = []
    lock = threading.Lock()

    def call_get() -> None:
        store = app_module._get_session_store()
        with lock:
            results.append(store)

    threads = [threading.Thread(target=call_get) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    # 모든 호출이 동일 인스턴스를 반환해야 함 (identity check).
    first = results[0]
    assert all(r is first for r in results), (
        f"singleton 위반 — {len({id(r) for r in results})} 개 인스턴스 생성됨"
    )


@pytest.mark.asyncio
async def test_agent_state_includes_session_id_when_passed() -> None:
    """run_agent(session_id='x', event_id='e') 호출 시 graph state 에 보존됨 명시 검증.

    architect WARN-1 (MED): 단순 결과 검증으로는 initial_state 채움 라인이 누락돼도
    통과 — covenant 미보호. graph 의 모든 노드가 `{**state, ...}` 로 새 state 반환
    하므로 final_state 에 session_id/event_id 가 살아있어야 정합.
    """
    import time
    from unittest.mock import AsyncMock

    from macro_logbot.agent.core import _GRAPH, AgentState
    from macro_logbot.gateway import (
        ChatCompletionResponse,
        Choice,
        LLMGateway,
        Usage,
    )
    from macro_logbot.gateway.models import Message as GwMessage

    final_resp = ChatCompletionResponse(
        id="chatcmpl-sid",
        object="chat.completion",
        created=int(time.time()),
        model="openai/gpt-4o-mini",
        choices=[
            Choice(
                index=0,
                message=GwMessage(role="assistant", content="ok"),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    gw.complete = AsyncMock(return_value=final_resp)  # type: ignore[method-assign]

    initial_state: AgentState = {
        "messages": [GwMessage(role="user", content="hi")],
        "iteration": 0,
        "max_iters": 20,
        "last_response": None,
        "report": None,
        "session_id": "test-session-x",
        "event_id": "evt-001",
        "_model": None,
        "_generation_kwargs": {},
        "_gateway": gw,
    }
    final_state = await _GRAPH.ainvoke(initial_state)

    # graph 6 노드 통과 후에도 session_id / event_id 가 state 에 보존 — covenant 검증.
    assert final_state["session_id"] == "test-session-x"
    assert final_state["event_id"] == "evt-001"
    # 결과 자체도 정상.
    assert final_state["last_response"] is not None
    assert final_state["iteration"] == 1
