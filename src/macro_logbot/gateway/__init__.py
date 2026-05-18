"""LLM Gateway 패키지 — LiteLLM 기반 멀티 프로바이더 라우팅.

Spec reference: docs/design/02-설계문서.md (v1.1)
- §4 아키텍처 LG 컴포넌트
- §7 사내 LLM 통합 + 사외 PoC 무료 LLM
"""

from macro_logbot.gateway.client import LLMGateway
from macro_logbot.gateway.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    Message,
    Usage,
)

__all__ = [
    "LLMGateway",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "Choice",
    "Message",
    "Usage",
]
