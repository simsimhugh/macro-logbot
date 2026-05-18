"""FastAPI application entry point.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1 External Interfaces
"""

from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from macro_logbot import __version__
from macro_logbot.agent import MAX_ITERS_DEFAULT, run_agent
from macro_logbot.auth import verify_api_key
from macro_logbot.gateway import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMGateway,
    Message,
)
from macro_logbot.intake import IntakeRecord, parse_macro_log
from macro_logbot.tools import get_openai_tools_schema

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
    # stream=True silent ignore 는 Open WebUI 가 SSE 파싱 실패로 멈출 수 있어
    # 명시적 400 으로 거절. SSE 본기능 지원은 후속 PR (FOLLOWUP task-LG-003).
    if body.stream:
        raise HTTPException(status_code=400, detail="streaming not yet supported")

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


class AgentAnalyzeResponse(BaseModel):
    """POST /agent/analyze 응답.

    terminated_reason:
      - "final": agent loop 가 final answer (tool_calls 없음) 으로 정상 종료
      - "max_iters": max_iters 도달 — analysis 가 빈 문자열일 수 있음 (호출자가 가시화)
    """

    analysis: str
    record: IntakeRecord
    iterations: int
    terminated_reason: Literal["final", "max_iters"]


_ANALYZE_SYSTEM_PROMPT = (
    "당신은 MACRO 시스템의 에러 로그를 분석하는 시니어 엔지니어입니다. "
    "필요하면 제공된 tool 을 호출해 코드/로그/blame 을 조사하고, "
    "원인 가설과 다음 조치를 한국어로 명확히 답하세요."
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
    """MACRO 에러 로그를 받아 agent loop 으로 분석하고 결과 반환."""
    record = parse_macro_log(body.log_text)
    user_prompt = (
        "다음 MACRO 에러 로그를 분석해 주세요. 필요 시 tool 을 호출하세요.\n\n"
        f"timestamp: {record.timestamp}\n"
        f"level: {record.level}\n"
        f"message: {record.message}\n"
    )
    if record.traceback:
        user_prompt += f"\ntraceback:\n{record.traceback}\n"
    user_prompt += f"\nraw:\n{record.raw}\n"

    messages = [
        Message(role="system", content=_ANALYZE_SYSTEM_PROMPT),
        Message(role="user", content=user_prompt),
    ]
    result = await run_agent(messages, gateway, model=body.model)
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
        if (result.iterations >= MAX_ITERS_DEFAULT and last_assistant_has_tool_calls)
        else "final"
    )
    return AgentAnalyzeResponse(
        analysis=analysis,
        record=record,
        iterations=result.iterations,
        terminated_reason=terminated_reason,
    )


# 미사용 import 방어 — get_openai_tools_schema 는 외부 모듈에서 import 가능하도록
# 재노출 목적. (linter 가 unused 로 잡지 않게 __all__ 명시.)
__all__ = ["app", "get_gateway", "get_openai_tools_schema"]
