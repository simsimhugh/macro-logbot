"""task-AGENT-024: gpt-oss reasoning_effort + timeout env-driven 동작 검증.

사용자 요구:
- LM Studio 의 gpt-oss-20b 로 모델 전환 + 32K context.
- LM Studio UI 의 Low/Medium/High 슬라이더 = OpenAI compat `reasoning_effort` parameter.
- "latency 아무 상관없음, 10분 걸려도 OK" — high effort 측정 시 LiteLLM timeout 늘림.

본 PoC 는 env-driven default 만 제공 — agent loop / endpoint 변경 없이 측정 환경 토글 가능.
explicit kwarg 우선, response 의 reasoning capture 검증.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from macro_logbot.gateway.client import LLMGateway
from macro_logbot.gateway.models import Message


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """reasoning_effort / timeout env 깨끗하게 — env-driven 동작 검증."""
    for k in (
        "MACRO_LOGBOT_LLM_REASONING_EFFORT",
        "MACRO_LOGBOT_LLM_TIMEOUT_SEC",
    ):
        monkeypatch.delenv(k, raising=False)


def test_defaults_none_when_env_unset(clean_env: None) -> None:
    """env 미설정 → self.reasoning_effort / self.timeout = None (backward compat)."""
    gw = LLMGateway()
    assert gw.reasoning_effort is None
    assert gw.timeout is None


@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_reasoning_effort_env_valid_values_normalized(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    """low/medium/high 3 값 모두 OK + uppercase / whitespace 도 normalize."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_REASONING_EFFORT", f"  {level.upper()}  ")
    gw = LLMGateway()
    assert gw.reasoning_effort == level


def test_reasoning_effort_env_invalid_raises(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """잘못된 값 → ValueError (fail-fast, silent corruption 방지)."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_REASONING_EFFORT", "extreme")
    with pytest.raises(ValueError, match="MACRO_LOGBOT_LLM_REASONING_EFFORT"):
        LLMGateway()


def test_timeout_env_valid_seconds_as_float(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """timeout env 가 float 으로 정규화 — LiteLLM acompletion(timeout=...) spec 정합."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_TIMEOUT_SEC", "900")
    gw = LLMGateway()
    assert gw.timeout == 900.0


@pytest.mark.parametrize("bad", ["abc", "-1", "0"])
def test_timeout_env_invalid_raises(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """non-numeric / 0 이하 timeout → ValueError."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_TIMEOUT_SEC", bad)
    with pytest.raises(ValueError, match="MACRO_LOGBOT_LLM_TIMEOUT_SEC"):
        LLMGateway()


def test_timeout_env_whitespace_only_treated_as_unset(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """공백만 있는 env → None (운영자 실수 방어, _extra_headers 와 일관 정책)."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_TIMEOUT_SEC", "   ")
    gw = LLMGateway()
    assert gw.timeout is None


@pytest.mark.asyncio
async def test_complete_forwards_env_defaults_to_litellm(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env=high + timeout=900 → LiteLLM acompletion kwargs 에 두 값 forward."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_REASONING_EFFORT", "high")
    monkeypatch.setenv("MACRO_LOGBOT_LLM_TIMEOUT_SEC", "900")
    gw = LLMGateway()

    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop — kwargs captured")

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete([Message(role="user", content="hi")], model="m")

    assert captured[0]["reasoning_effort"] == "high"
    assert captured[0]["timeout"] == 900.0


@pytest.mark.asyncio
async def test_explicit_kwarg_overrides_env(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """complete(reasoning_effort='low') 가 env=high 보다 우선 — task-SEC-003 정책 정합."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_REASONING_EFFORT", "high")
    gw = LLMGateway()

    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop — kwargs captured")

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete(
                [Message(role="user", content="hi")],
                model="m",
                reasoning_effort="low",
            )

    assert captured[0]["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_no_forward_when_env_unset(clean_env: None) -> None:
    """env 미설정 → kwargs 에 reasoning_effort / timeout 안 들어감 (backward compat)."""
    gw = LLMGateway()
    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop — kwargs captured")

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete([Message(role="user", content="hi")], model="m")

    assert "reasoning_effort" not in captured[0]
    assert "timeout" not in captured[0]


@pytest.mark.asyncio
async def test_response_reasoning_field_captured(clean_env: None) -> None:
    """gpt-oss 류 응답의 message.reasoning 이 Message.reasoning 에 capture.

    LM Studio v0 API 실측 응답 (2026-05-21):
        choices[0].message.reasoning = "The user says..."
        completion_tokens_details.reasoning_tokens = 118
    """
    gw = LLMGateway()
    mock_message = SimpleNamespace(
        role="assistant",
        content="OK",
        tool_calls=None,
        reasoning="The user wants OK. Output OK.",
    )
    mock_response = SimpleNamespace(
        id="chatcmpl-test",
        object="chat.completion",
        created=1700000000,
        model="openai/gpt-oss-20b",
        choices=[SimpleNamespace(index=0, message=mock_message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        return mock_response

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        result = await gw.complete([Message(role="user", content="hi")], model="m")

    assert result.choices[0].message.reasoning == "The user wants OK. Output OK."
    assert result.choices[0].message.content == "OK"


@pytest.mark.asyncio
async def test_response_no_reasoning_for_non_reasoning_model(clean_env: None) -> None:
    """비-reasoning model 응답 (reasoning attr 부재) → Message.reasoning = None.

    Gemma / Llama / Claude / Gemini 등 standard model 의 backward compat 보장.
    """
    gw = LLMGateway()
    mock_message = SimpleNamespace(role="assistant", content="hi", tool_calls=None)
    # 의도적으로 reasoning attr 없음 — getattr(default=None) 경로 검증
    mock_response = SimpleNamespace(
        id="x", object="chat.completion", created=0, model="gemma-3-12b",
        choices=[SimpleNamespace(index=0, message=mock_message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        return mock_response

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        result = await gw.complete([Message(role="user", content="hi")], model="m")

    assert result.choices[0].message.reasoning is None


@pytest.mark.asyncio
async def test_drop_params_true_forwarded_to_litellm(clean_env: None) -> None:
    """drop_params=True 가 항상 LiteLLM acompletion 에 forward — 비-reasoning model 도 안전.

    LM Studio 실측 (2026-05-21): gemini/gemini-2.5-flash-lite 에 reasoning_effort=high 보내면
    UnsupportedParamsError. drop_params=True 로 LiteLLM 이 model 별 미지원 param silent drop.
    """
    gw = LLMGateway()
    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop — kwargs captured")

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete([Message(role="user", content="hi")], model="m")

    assert captured[0].get("drop_params") is True


@pytest.mark.asyncio
async def test_response_empty_string_reasoning_normalized_to_none(clean_env: None) -> None:
    """reasoning = '' (빈 string) 도 None 으로 정규화 — JSON 직렬화 시 noise 제거."""
    gw = LLMGateway()
    mock_message = SimpleNamespace(
        role="assistant", content="hi", tool_calls=None, reasoning=""
    )
    mock_response = SimpleNamespace(
        id="x", object="chat.completion", created=0, model="m",
        choices=[SimpleNamespace(index=0, message=mock_message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        return mock_response

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        result = await gw.complete([Message(role="user", content="hi")], model="m")

    assert result.choices[0].message.reasoning is None
