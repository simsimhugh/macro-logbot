"""LiteLLM 래퍼 — 멀티 프로바이더 LLM 클라이언트.

Spec reference: docs/design/02-설계문서.md (v1.1) §4 LG · §7

Supported model prefixes:
  openai/     — e.g. "openai/gpt-4o-mini"
  anthropic/  — e.g. "anthropic/claude-haiku-3-5"
  gemini/     — e.g. "gemini/gemini-1.5-flash"
  groq/       — e.g. "groq/llama3-8b-8192"

Provider API keys are read by LiteLLM directly from the environment:
  OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY
"""

from __future__ import annotations

import os
import time

import litellm

from macro_logbot.gateway.models import (
    ChatCompletionResponse,
    Choice,
    Message,
    Usage,
)

_DEFAULT_MODEL_ENV = "MACRO_LOGBOT_DEFAULT_MODEL"
_FALLBACK_MODEL = "openai/gpt-4o-mini"


class LLMGateway:
    """LiteLLM 을 통한 멀티 프로바이더 LLM 게이트웨이."""

    def __init__(self, default_model: str | None = None) -> None:
        # Priority: explicit arg → env var → hardcoded fallback
        self.default_model: str = (
            default_model
            or os.environ.get(_DEFAULT_MODEL_ENV)
            or _FALLBACK_MODEL
        )

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: object,
    ) -> ChatCompletionResponse:
        """LiteLLM acompletion 을 호출하고 결과를 우리 응답 모델로 변환한다."""
        target_model = model or self.default_model
        raw_messages = [{"role": m.role, "content": m.content} for m in messages]

        response = await litellm.acompletion(
            model=target_model,
            messages=raw_messages,
            **kwargs,
        )

        choices = [
            Choice(
                index=c.index,
                message=Message(
                    role=c.message.role,
                    content=c.message.content or "",
                ),
                finish_reason=c.finish_reason,
            )
            for c in response.choices
        ]
        # LiteLLM provider 일부(예: Anthropic prompt caching, Groq stream 종결)에서
        # response.usage 또는 그 하위 필드가 None 인 케이스 방어.
        usage_data = response.usage
        usage = Usage(
            prompt_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage_data, "total_tokens", 0) or 0,
        )

        # response.id / .object / .model 도 provider edge case 에서 None 가능 —
        # usage 와 동일 defensive 패턴 적용 (일관성).
        return ChatCompletionResponse(
            id=response.id or f"chatcmpl-litellm-{int(time.time())}",
            object=response.object or "chat.completion",
            created=response.created or int(time.time()),
            model=response.model or target_model,
            choices=choices,
            usage=usage,
        )
