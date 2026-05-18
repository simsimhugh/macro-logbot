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
    """LiteLLM を통한 멀티 프로바이더 LLM 게이트웨이."""

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
        usage_data = response.usage
        usage = Usage(
            prompt_tokens=usage_data.prompt_tokens,
            completion_tokens=usage_data.completion_tokens,
            total_tokens=usage_data.total_tokens,
        )

        return ChatCompletionResponse(
            id=response.id,
            object=response.object,
            created=response.created or int(time.time()),
            model=response.model,
            choices=choices,
            usage=usage,
        )
