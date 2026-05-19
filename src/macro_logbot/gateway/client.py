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
from typing import Any

import litellm

from macro_logbot.gateway.models import (
    ChatCompletionResponse,
    Choice,
    FunctionCall,
    Message,
    ToolCall,
    Usage,
)

_DEFAULT_MODEL_ENV = "MACRO_LOGBOT_DEFAULT_MODEL"
_FALLBACK_MODEL = "openai/gpt-4o-mini"

# 사내 LLM endpoint env (task-LG-002 / spec §7.3).
# arg > env > None 우선순위로 LLMGateway.__init__ 에서 흡수.
_LLM_BASE_URL_ENV = "MACRO_LOGBOT_LLM_BASE_URL"
_LLM_API_KEY_ENV = "MACRO_LOGBOT_LLM_API_KEY"
_LLM_PROVIDER_ENV = "MACRO_LOGBOT_LLM_PROVIDER"

# task-SEC-003: complete(**kwargs) 자유 패스스루 차단 → allowlist 외 ValueError.
# OpenAI / LiteLLM 호환 generation 파라미터 + tool calling 만 허용.
# agent loop (run_agent) 가 보내는 generation_kwargs (temperature/max_tokens 등) +
# /v1/chat/completions raw passthrough 가 보내는 body 필드 (tools/tool_choice) 모두 포함.
_ALLOWED_FORWARD_KWARGS: frozenset[str] = frozenset(
    {
        "temperature",
        "max_tokens",
        "top_p",
        "top_k",
        "frequency_penalty",
        "presence_penalty",
        "stop",
        "stream",
        "n",
        "seed",
        "response_format",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
    }
)


def _extract_tool_calls(raw_tool_calls: object) -> list[ToolCall] | None:
    """LiteLLM tool_calls 응답을 ToolCall 리스트로 정규화.

    LiteLLM 은 provider 에 따라 list[obj] 또는 list[dict] 로 반환할 수 있어
    양쪽 모두 처리한다.
    """
    if not raw_tool_calls:
        return None
    result: list[ToolCall] = []
    for tc in raw_tool_calls:  # type: ignore[attr-defined]
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            result.append(
                ToolCall(
                    id=tc.get("id", ""),
                    type="function",
                    function=FunctionCall(
                        name=fn.get("name", ""),
                        arguments=fn.get("arguments", "") or "",
                    ),
                )
            )
        else:
            fn = getattr(tc, "function", None)
            result.append(
                ToolCall(
                    id=getattr(tc, "id", "") or "",
                    type="function",
                    function=FunctionCall(
                        name=getattr(fn, "name", "") or "",
                        arguments=getattr(fn, "arguments", "") or "",
                    ),
                )
            )
    return result or None


class LLMGateway:
    """LiteLLM 을 통한 멀티 프로바이더 LLM 게이트웨이."""

    def __init__(
        self,
        default_model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        custom_llm_provider: str | None = None,
    ) -> None:
        # Priority: explicit arg → env var → hardcoded fallback / None.
        # 사내 LLM endpoint (spec §7.3 · task-LG-002) — base_url/api_key/provider
        # 는 미설정 시 None (LiteLLM 이 provider prefix 와 표준 env 키로 fallback).
        self.default_model: str = (
            default_model
            or os.environ.get(_DEFAULT_MODEL_ENV)
            or _FALLBACK_MODEL
        )
        self.base_url: str | None = base_url or os.environ.get(_LLM_BASE_URL_ENV)
        self.api_key: str | None = api_key or os.environ.get(_LLM_API_KEY_ENV)
        self.custom_llm_provider: str | None = custom_llm_provider or os.environ.get(
            _LLM_PROVIDER_ENV
        )

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: object,
    ) -> ChatCompletionResponse:
        """LiteLLM acompletion 을 호출하고 결과를 우리 응답 모델로 변환한다.

        kwargs 는 `_ALLOWED_FORWARD_KWARGS` allowlist 외 인자 시 `ValueError`
        (task-SEC-003). base_url/api_key/custom_llm_provider 는 None 제외 후
        forward (task-LG-002).
        """
        # task-SEC-003: allowlist 검증 — 자유 패스스루 차단.
        bad = set(kwargs) - _ALLOWED_FORWARD_KWARGS
        if bad:
            raise ValueError(
                f"disallowed kwargs forwarded to acompletion: {sorted(bad)}"
            )

        target_model = model or self.default_model
        # tool_calls / tool_call_id / name 등 None 이 아닌 모든 필드를 보존.
        raw_messages: list[dict[str, Any]] = [
            m.model_dump(exclude_none=True) for m in messages
        ]

        # task-LG-002: 사내 LLM endpoint forward — None 제외해 LiteLLM 기본 동작 보존.
        extra: dict[str, Any] = {}
        if self.base_url is not None:
            extra["base_url"] = self.base_url
        if self.api_key is not None:
            extra["api_key"] = self.api_key
        if self.custom_llm_provider is not None:
            extra["custom_llm_provider"] = self.custom_llm_provider

        response = await litellm.acompletion(
            model=target_model,
            messages=raw_messages,
            **extra,
            **kwargs,
        )

        choices = [
            Choice(
                index=c.index,
                message=Message(
                    role=c.message.role,
                    content=c.message.content or None,
                    tool_calls=_extract_tool_calls(
                        getattr(c.message, "tool_calls", None)
                    ),
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
