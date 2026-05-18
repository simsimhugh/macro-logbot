"""FastAPI application entry point.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1 External Interfaces
"""

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from macro_logbot import __version__
from macro_logbot.gateway import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    LLMGateway,
)

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


@v1_router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    body: ChatCompletionRequest,
    gateway: LLMGateway = Depends(get_gateway),  # noqa: B008
) -> ChatCompletionResponse:
    """OpenAI 호환 chat completions 엔드포인트."""
    # stream=True silent ignore 는 Open WebUI 가 SSE 파싱 실패로 멈출 수 있어
    # 명시적 400 으로 거절. SSE 본기능 지원은 후속 PR (FOLLOWUP task-LG-003).
    if body.stream:
        raise HTTPException(status_code=400, detail="streaming not yet supported")
    # provider 일부 (Gemini, Groq) 는 명시적 None 을 거절하거나 default override 하므로
    # None 값은 forward 하지 않음 — model_dump(exclude_none=True).
    optional_kwargs = body.model_dump(
        exclude_none=True,
        exclude={"messages", "model", "stream"},
    )
    return await gateway.complete(
        messages=body.messages,
        model=body.model,
        **optional_kwargs,
    )


app.include_router(v1_router)
