"""FastAPI application entry point.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1 External Interfaces
"""

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from macro_logbot import __version__

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


# Spec §5.1 — Open WebUI 호환 OpenAI 형식 backend 라우터 자리.
# 실제 endpoint(chat/completions 등)는 후속 PR feat/llm-gateway에서 마운트.
v1_router = APIRouter(prefix="/v1")
app.include_router(v1_router)
