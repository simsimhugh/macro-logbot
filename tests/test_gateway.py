"""LLMGateway 단위 테스트 — real network call 없음."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from macro_logbot.gateway import LLMGateway, Message
from macro_logbot.gateway.models import ChatCompletionResponse


def _make_litellm_response(model: str = "openai/gpt-4o-mini") -> SimpleNamespace:
    """litellm.acompletion 이 반환하는 객체를 흉내낸 SimpleNamespace."""
    return SimpleNamespace(
        id="chatcmpl-test-123",
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[
            SimpleNamespace(
                index=0,
                message=SimpleNamespace(role="assistant", content="Hello!"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


@pytest.mark.asyncio
async def test_complete_returns_valid_response() -> None:
    """정상 litellm 응답이 ChatCompletionResponse 로 올바르게 변환된다."""
    fake_response = _make_litellm_response()
    mock_completion = AsyncMock(return_value=fake_response)
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock_completion):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        messages = [Message(role="user", content="Hi")]
        result = await gateway.complete(messages)

    assert isinstance(result, ChatCompletionResponse)
    assert result.id == "chatcmpl-test-123"
    assert result.model == "openai/gpt-4o-mini"
    assert len(result.choices) == 1
    assert result.choices[0].message.content == "Hello!"
    assert result.usage.total_tokens == 15


@pytest.mark.asyncio
async def test_default_model_explicit_arg() -> None:
    """명시적 인자로 기본 모델이 설정된다."""
    gateway = LLMGateway(default_model="anthropic/claude-haiku-3-5")
    assert gateway.default_model == "anthropic/claude-haiku-3-5"


@pytest.mark.asyncio
async def test_default_model_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """MACRO_LOGBOT_DEFAULT_MODEL env var 로 기본 모델이 설정된다."""
    monkeypatch.setenv("MACRO_LOGBOT_DEFAULT_MODEL", "gemini/gemini-1.5-flash")
    gateway = LLMGateway()
    assert gateway.default_model == "gemini/gemini-1.5-flash"


@pytest.mark.asyncio
async def test_default_model_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """인자와 env 가 모두 없으면 hardcoded fallback 이 사용된다."""
    monkeypatch.delenv("MACRO_LOGBOT_DEFAULT_MODEL", raising=False)
    gateway = LLMGateway()
    assert gateway.default_model == "openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_complete_uses_model_override() -> None:
    """complete() 의 model 인자가 default_model 을 오버라이드한다."""
    fake_response = _make_litellm_response(model="groq/llama3-8b-8192")
    mock = AsyncMock(return_value=fake_response)
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        messages = [Message(role="user", content="Hi")]
        result = await gateway.complete(messages, model="groq/llama3-8b-8192")

    mock.assert_called_once()
    call_kwargs = mock.call_args
    assert call_kwargs.kwargs["model"] == "groq/llama3-8b-8192"
    assert result.model == "groq/llama3-8b-8192"
