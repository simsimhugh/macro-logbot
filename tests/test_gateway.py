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
    assert gateway.default_model == "gemini/gemini-2.5-flash-lite"


@pytest.mark.asyncio
async def test_complete_handles_missing_usage() -> None:
    """provider 가 usage 를 부분/전체 None 으로 반환해도 0 으로 안전하게 변환된다."""
    response_without_usage = SimpleNamespace(
        id="chatcmpl-no-usage",
        object="chat.completion",
        created=int(time.time()),
        model="groq/llama3-8b-8192",
        choices=[
            SimpleNamespace(
                index=0,
                message=SimpleNamespace(role="assistant", content="ok"),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    mock = AsyncMock(return_value=response_without_usage)
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="groq/llama3-8b-8192")
        result = await gateway.complete([Message(role="user", content="Hi")])

    assert result.usage.prompt_tokens == 0
    assert result.usage.completion_tokens == 0
    assert result.usage.total_tokens == 0


@pytest.mark.asyncio
async def test_complete_handles_missing_response_id() -> None:
    """response.id/object/model None 반환 시 fallback 으로 안전하게 변환된다."""
    response_partial = SimpleNamespace(
        id=None,
        object=None,
        created=int(time.time()),
        model=None,
        choices=[
            SimpleNamespace(
                index=0,
                message=SimpleNamespace(role="assistant", content="ok"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    mock = AsyncMock(return_value=response_partial)
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="groq/llama3-8b-8192")
        result = await gateway.complete([Message(role="user", content="Hi")])

    assert result.id.startswith("chatcmpl-litellm-")
    assert result.object == "chat.completion"
    assert result.model == "groq/llama3-8b-8192"


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


# --- task-LG-002: 사내 LLM endpoint env override -----------------------------


@pytest.mark.asyncio
async def test_llm_gateway_base_url_from_arg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """__init__(base_url=...) 가 complete 호출 시 acompletion 으로 forward."""
    monkeypatch.delenv("MACRO_LOGBOT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MACRO_LOGBOT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MACRO_LOGBOT_LLM_PROVIDER", raising=False)
    mock = AsyncMock(return_value=_make_litellm_response())
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(
            default_model="openai/gpt-4o-mini",
            base_url="https://internal.example/llm",
        )
        await gateway.complete([Message(role="user", content="Hi")])

    assert gateway.base_url == "https://internal.example/llm"
    assert mock.call_args.kwargs["base_url"] == "https://internal.example/llm"
    # api_key / custom_llm_provider 미설정 — forward 안 함.
    assert "api_key" not in mock.call_args.kwargs
    assert "custom_llm_provider" not in mock.call_args.kwargs


@pytest.mark.asyncio
async def test_llm_gateway_base_url_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MACRO_LOGBOT_LLM_BASE_URL env 로 base_url 흡수."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_BASE_URL", "https://env.example/llm")
    monkeypatch.delenv("MACRO_LOGBOT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MACRO_LOGBOT_LLM_PROVIDER", raising=False)
    mock = AsyncMock(return_value=_make_litellm_response())
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        await gateway.complete([Message(role="user", content="Hi")])

    assert gateway.base_url == "https://env.example/llm"
    assert mock.call_args.kwargs["base_url"] == "https://env.example/llm"


@pytest.mark.asyncio
async def test_llm_gateway_api_key_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MACRO_LOGBOT_LLM_API_KEY env 로 api_key 흡수 후 forward."""
    monkeypatch.delenv("MACRO_LOGBOT_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("MACRO_LOGBOT_LLM_API_KEY", "internal-secret-key")
    monkeypatch.delenv("MACRO_LOGBOT_LLM_PROVIDER", raising=False)
    mock = AsyncMock(return_value=_make_litellm_response())
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        await gateway.complete([Message(role="user", content="Hi")])

    assert gateway.api_key == "internal-secret-key"
    assert mock.call_args.kwargs["api_key"] == "internal-secret-key"
    assert "base_url" not in mock.call_args.kwargs


@pytest.mark.asyncio
async def test_llm_gateway_custom_provider_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MACRO_LOGBOT_LLM_PROVIDER env 로 custom_llm_provider forward."""
    monkeypatch.delenv("MACRO_LOGBOT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MACRO_LOGBOT_LLM_API_KEY", raising=False)
    monkeypatch.setenv("MACRO_LOGBOT_LLM_PROVIDER", "openai")
    mock = AsyncMock(return_value=_make_litellm_response())
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        await gateway.complete([Message(role="user", content="Hi")])

    assert gateway.custom_llm_provider == "openai"
    assert mock.call_args.kwargs["custom_llm_provider"] == "openai"


@pytest.mark.asyncio
async def test_llm_gateway_arg_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """우선순위 검증: __init__ arg > env > None."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_BASE_URL", "https://env.example/llm")
    monkeypatch.setenv("MACRO_LOGBOT_LLM_API_KEY", "env-key")
    monkeypatch.setenv("MACRO_LOGBOT_LLM_PROVIDER", "env-provider")
    mock = AsyncMock(return_value=_make_litellm_response())
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(
            default_model="openai/gpt-4o-mini",
            base_url="https://arg.example/llm",
            api_key="arg-key",
            custom_llm_provider="arg-provider",
        )
        await gateway.complete([Message(role="user", content="Hi")])

    assert gateway.base_url == "https://arg.example/llm"
    assert gateway.api_key == "arg-key"
    assert gateway.custom_llm_provider == "arg-provider"
    fwd = mock.call_args.kwargs
    assert fwd["base_url"] == "https://arg.example/llm"
    assert fwd["api_key"] == "arg-key"
    assert fwd["custom_llm_provider"] == "arg-provider"


# --- task-SEC-003: complete kwargs allowlist ---------------------------------


@pytest.mark.asyncio
async def test_llm_gateway_kwargs_allowlist_rejects_unknown() -> None:
    """allowlist 밖 kwarg 는 ValueError — litellm.acompletion 호출조차 없음."""
    mock = AsyncMock(return_value=_make_litellm_response())
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        with pytest.raises(ValueError, match="disallowed kwargs"):
            await gateway.complete(
                [Message(role="user", content="Hi")],
                banana=1,  # type: ignore[arg-type]
            )
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_llm_gateway_kwargs_allowlist_accepts_known() -> None:
    """allowlist 안 kwarg (temperature/tool_choice 등) 는 정상 forward."""
    mock = AsyncMock(return_value=_make_litellm_response())
    with patch("macro_logbot.gateway.client.litellm.acompletion", new=mock):
        gateway = LLMGateway(default_model="openai/gpt-4o-mini")
        await gateway.complete(
            [Message(role="user", content="Hi")],
            temperature=0.7,
            max_tokens=128,
            tool_choice="auto",
        )

    fwd = mock.call_args.kwargs
    assert fwd["temperature"] == 0.7
    assert fwd["max_tokens"] == 128
    assert fwd["tool_choice"] == "auto"
