"""FastAPI application entry point.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1 External Interfaces
"""

import logging
import os
import threading
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel

from macro_logbot import __version__
from macro_logbot.agent import MAX_ITERS_DEFAULT, Report, run_agent
from macro_logbot.auth import verify_api_key
from macro_logbot.gateway import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMGateway,
    Message,
)
from macro_logbot.intake import IntakeRecord, parse_macro_log
from macro_logbot.knowledge_base import ArchivedCase, SQLiteKBStore
from macro_logbot.knowledge_base.store import Location
from macro_logbot.session import SQLiteSessionStore
from macro_logbot.tools import get_openai_tools_schema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton stores — module-level, lazy-init on first request.
# Double-checked locking (threading.Lock) 으로 TOCTOU race 방지.
# ---------------------------------------------------------------------------

_session_store: SQLiteSessionStore | None = None
_kb_store: SQLiteKBStore | None = None

_session_store_lock = threading.Lock()
_kb_store_lock = threading.Lock()


def _get_session_store() -> SQLiteSessionStore:
    global _session_store
    if _session_store is None:
        with _session_store_lock:
            if _session_store is None:
                db_path = os.getenv("MACRO_LOGBOT_SESSION_DB", ".macro-logbot-sessions.db")
                _session_store = SQLiteSessionStore(db_path)
    return _session_store


def _get_kb_store() -> SQLiteKBStore | None:
    """KB store — MACRO_LOGBOT_KB_PATH 설정 시에만 반환, 미설정 시 None."""
    global _kb_store
    # env 경로 확인은 lock 밖 (idempotent read-only).
    kb_path = os.getenv("MACRO_LOGBOT_KB_PATH")
    if kb_path is None:
        return None
    if _kb_store is None:
        with _kb_store_lock:
            if _kb_store is None:
                _kb_store = SQLiteKBStore(kb_path)
    return _kb_store


def _reset_singletons_for_test() -> None:
    """테스트 격리용 — monkeypatch internal 의존 회피 (code-r WARN-3 from PR #25)."""
    global _session_store, _kb_store
    _session_store = None
    _kb_store = None


app = FastAPI(
    title="macro-logbot",
    description="사내 에이전트 AI 플랫폼 — MACRO 에러 로그 자율 분석",
    version=__version__,
)


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """서비스 헬스 체크 엔드포인트."""
    return HealthResponse(status="ok", version=__version__)


def get_gateway() -> LLMGateway:
    """DI 팩토리 — 테스트에서 app.dependency_overrides 로 교체 가능."""
    return LLMGateway()


# Spec §5.1 — Open WebUI 호환 OpenAI 형식 backend 라우터
v1_router = APIRouter(prefix="/v1")


@v1_router.get(
    "/models",
    dependencies=[Depends(verify_api_key)],
)
async def list_models() -> dict[str, object]:
    """OpenAI 호환 모델 목록 — Open WebUI 가 모델 picker 채우려고 호출."""
    model = os.environ.get("MACRO_LOGBOT_DEFAULT_MODEL", "openai/gpt-4o-mini")
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": 0,
                "owned_by": "macro-logbot",
            }
        ],
    }


@v1_router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    dependencies=[Depends(verify_api_key)],
)
async def chat_completions(
    body: ChatCompletionRequest,
    agent: bool = True,
    gateway: LLMGateway = Depends(get_gateway),  # noqa: B008
) -> ChatCompletionResponse:
    """OpenAI 호환 chat completions 엔드포인트.

    동작 모드:
      - body.tools 가 명시되면 raw passthrough (호출자가 직접 tool 라운드트립 처리).
      - 그렇지 않고 agent=true (기본) 이면 agent loop 통과 — 자동으로 built-in
        tools schema 첨부 + tool 실행 라운드트립 수행.
      - agent=false 이면 raw 호출 (tools 미첨부).
    """
    # Open WebUI 기본 stream=true 송신 → SSE 본구현 없는 본 PR 에서는 거절 대신
    # silently non-stream 으로 처리 (demo 안전). SSE 본기능 지원은 FOLLOWUP
    # task-LG-003. 거절했던 PR #8 의 정책을 demo 진입 PR (#12) 부터 완화.
    # body 자체는 mutate 하지 않고 다운스트림 logging/audit 의도 보존을 위해
    # local var 만 사용 (CR LOW finding 반영).
    if body.stream:
        logger.warning(
            "stream=True downgraded to non-stream (SSE not implemented — task-LG-003)"
        )

    # raw passthrough: 호출자가 tools 를 직접 명시했거나 agent=false 인 경우.
    if body.tools is not None or not agent:
        optional_kwargs = body.model_dump(
            exclude_none=True,
            exclude={"messages", "model", "stream"},
        )
        return await gateway.complete(
            messages=body.messages,
            model=body.model,
            **optional_kwargs,
        )

    # agent loop — built-in tools 자동 첨부.
    # user-supplied 생성 파라미터(temperature/max_tokens/tool_choice 등) forward.
    # None 값은 LiteLLM 호환 위해 제외 (PR #8 fix 패턴과 동일).
    agent_kwargs = body.model_dump(
        exclude_none=True,
        exclude={"messages", "model", "stream", "tools"},
    )
    result = await run_agent(
        body.messages, gateway, model=body.model, **agent_kwargs
    )
    return result.response


app.include_router(v1_router)


class AgentAnalyzeRequest(BaseModel):
    """POST /agent/analyze 요청 body."""

    log_text: str
    model: str | None = None
    session_id: str | None = None


class AgentAnalyzeResponse(BaseModel):
    """POST /agent/analyze 응답.

    terminated_reason:
      - "final": agent loop 가 final answer (tool_calls 없음) 으로 정상 종료
      - "max_iters": max_iters 도달 — analysis 가 빈 문자열일 수 있음 (호출자가 가시화)

    report: crystallize_report 노드가 추출한 구조화 리포트 (MVP: last assistant 복사).
      None 이면 LLM 응답이 없었던 edge case.
    session_id: 분석 session uuid — 연속 호출 시 같은 id 로 컨텍스트 이어받기
      (task-MVP-004, PR #24).
    """

    analysis: str
    record: IntakeRecord
    iterations: int
    terminated_reason: Literal["final", "max_iters"]
    report: Report | None = None
    session_id: str | None = None


_ANALYZE_SYSTEM_PROMPT = (
    "당신은 MACRO 시스템의 에러 로그를 분석하는 시니어 엔지니어입니다.\n\n"
    "## 분석 절차 (반드시 순서대로)\n"
    "1. **먼저 tool 을 호출해 traceback 의 실제 코드를 확인하세요.** "
    "추측으로 답하지 말고, `grep_codebase` 로 함수/심볼을 찾거나 "
    "`read_file` 로 traceback file:line 의 실제 코드 본문을 직접 읽으세요.\n"
    "2. 본 시스템의 도구 호출은 의무입니다. 도구 호출 없이 분석만 답하는 것은 "
    "허용되지 않습니다 (단 traceback 이 명백히 없는 단순 질문은 예외).\n"
    "3. tool 결과를 근거로 원인 가설을 세우고, 추가 검증이 필요하면 "
    "다시 tool 을 호출하세요.\n"
    "4. 충분한 근거가 모이면 한국어로 원인 + 다음 조치를 명확히 답하세요.\n\n"
    "## 입력 노이즈 처리\n"
    "stderr 본문에 ALSA / pygame init / GPU driver / locale warning 등 "
    "**환경 noise** 가 섞여 있어도 무시하세요. 분석 대상은 "
    "`Traceback (most recent call last):` 로 시작하는 Python traceback 의 "
    "마지막 `<ErrorType>: <message>` 와 그 직전 frame (file:line) 입니다."
)


@app.post(
    "/agent/analyze",
    response_model=AgentAnalyzeResponse,
    dependencies=[Depends(verify_api_key)],
)
async def agent_analyze(
    body: AgentAnalyzeRequest,
    gateway: LLMGateway = Depends(get_gateway),  # noqa: B008
) -> AgentAnalyzeResponse:
    """MACRO 에러 로그를 받아 agent loop 으로 분석하고 결과 반환.

    session_id 가 제공되면 기존 session messages 를 컨텍스트로 로드.
    없으면 새 session 생성. 분석 후 messages 를 session 에 저장하고 session_id 반환.
    """
    # --- session 로드 또는 생성 ---
    session_store = _get_session_store()
    if body.session_id:
        session = session_store.get(body.session_id)
        if session is None:
            # 알 수 없는 id — 새 session 으로 안전하게 생성 (404 대신, IDOR 회피).
            # 보안 감사 위해 WARN 로깅 (security WARN-4) — id 앞 8자만 (full 노출 회피).
            logger.warning(
                "session_id %s... not found — issuing new session",
                body.session_id[:8],
            )
            session = session_store.create()
    else:
        session = session_store.create()

    record = parse_macro_log(body.log_text)
    user_prompt = (
        "다음 MACRO 에러 로그를 분석해 주세요.\n"
        "분석에 앞서 **반드시 tool 을 호출해** traceback file:line 의 "
        "실제 코드를 직접 확인하세요. 도구 호출 없이 답하지 마세요.\n\n"
        f"timestamp: {record.timestamp}\n"
        f"level: {record.level}\n"
        f"message: {record.message}\n"
    )
    if record.traceback:
        user_prompt += f"\ntraceback:\n{record.traceback}\n"
    user_prompt += f"\nraw:\n{record.raw}\n"

    # persona system + 기존 session messages + 새 user message.
    messages = [
        Message(role="system", content=_ANALYZE_SYSTEM_PROMPT),
        *session.messages,
        Message(role="user", content=user_prompt),
    ]
    # max_iters 를 명시 변수로 묶음 — terminated_reason 판정과 동일 값 비교 보장
    # (PR #23 test-e WARN-1: hardcoded MAX_ITERS_DEFAULT 비교 vs run_agent 호출 시
    # 사용한 max_iters 가 어긋날 수 있는 위험 제거).
    max_iters = MAX_ITERS_DEFAULT
    result = await run_agent(
        messages, gateway, max_iters=max_iters, model=body.model, session_id=session.id
    )

    # --- session messages 갱신 저장 ---
    # system message 는 매 호출마다 _ANALYZE_SYSTEM_PROMPT / intake 노드가 prepend 하므로
    # session 에는 저장 X — 다음 호출에서 중복 누적 방지 (architect WARN-2).
    session.messages = [m for m in result.messages if m.role != "system"]
    session_store.update(session)

    analysis = ""
    if result.response.choices:
        analysis = result.response.choices[0].message.content or ""
    # final answer 도달 여부 — 마지막 assistant message 가 tool_calls 없으면 정상 종료.
    # max_iters 도달 시 마지막 assistant 가 여전히 tool_calls 만 있을 수 있음.
    last_assistant_has_tool_calls = bool(
        result.response.choices
        and result.response.choices[0].message.tool_calls
    )
    terminated_reason: Literal["final", "max_iters"] = (
        "max_iters"
        if (result.iterations >= max_iters and last_assistant_has_tool_calls)
        else "final"
    )

    # --- KB auto-archive (env 활성화 + report 존재 시) ---
    # KB write 는 analytics side effect — 실패해도 분석 응답 자체는 200 유지
    # (code-r WARN-2: disk full / permission / schema drift 등이 endpoint 응답
    # 계약 본체에 영향 주면 안 됨).
    if os.getenv("MACRO_LOGBOT_KB_AUTO_ARCHIVE") == "true" and result.report:
        kb_store = _get_kb_store()
        if kb_store is not None:
            try:
                _kb_auto_archive(kb_store, result.report)
            except Exception as exc:
                logger.warning("KB auto-archive failed (non-fatal): %s", exc)

    return AgentAnalyzeResponse(
        analysis=analysis,
        record=record,
        iterations=result.iterations,
        terminated_reason=terminated_reason,
        report=result.report,
        session_id=session.id,
    )


def _kb_auto_archive(kb_store: SQLiteKBStore, report: Report) -> None:
    """분석 결과 Report 를 KB 에 자동 아카이빙 (env gating 후 호출)."""
    location = report.location or Location(file="unknown", function="", line=1)
    case = ArchivedCase(
        case_id=str(uuid4()),
        error_signature=report.root_cause[:80],
        category="auto/poc",
        root_cause=report.root_cause,
        location=location,
        fix_hint=report.fix_hint,
        confidence=report.confidence,
        source="poc",
    )
    kb_store.add(case)


# 미사용 import 방어 — get_openai_tools_schema 는 외부 모듈에서 import 가능하도록
# 재노출 목적. underscore prefix internal 헬퍼 (_reset_singletons_for_test 등) 는
# __all__ 에서 제외 — production `from app import *` 시 public surface 오염 방지
# (code-r/sec/test WARN: public/internal 신호 충돌). 테스트는 `from macro_logbot.app
# import _reset_singletons_for_test` 또는 `app_module._reset_singletons_for_test()`
# 로 명시 접근 가능 (관례 호환).
__all__ = ["app", "get_gateway", "get_openai_tools_schema"]
