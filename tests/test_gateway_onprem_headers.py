"""사내 DS API HUB custom header (x-dep-ticket) 통합 — env-driven 설정 verify."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_logbot.gateway.client import LLMGateway


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """온프렘 헤더 env 4종 깨끗하게 제거 — env-driven 동작 검증을 위함."""
    for k in (
        "MACRO_LOGBOT_LLM_X_DEP_TICKET",
        "MACRO_LOGBOT_LLM_SEND_SYSTEM_NAME",
        "MACRO_LOGBOT_LLM_USER_ID",
        "MACRO_LOGBOT_LLM_USER_TYPE",
    ):
        monkeypatch.delenv(k, raising=False)


def test_extra_headers_none_when_ticket_not_set(clean_env: None) -> None:
    """x-dep-ticket env 미설정 시 _extra_headers = None (backward compat)."""
    gw = LLMGateway()
    assert gw._extra_headers is None


def test_extra_headers_populated_when_ticket_set(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """x-dep-ticket env 설정 시 4 static header 가 _extra_headers 에 포함."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_X_DEP_TICKET", "test-ticket-123")
    monkeypatch.setenv("MACRO_LOGBOT_LLM_SEND_SYSTEM_NAME", "test-sys")
    monkeypatch.setenv("MACRO_LOGBOT_LLM_USER_ID", "user-abc")
    monkeypatch.setenv("MACRO_LOGBOT_LLM_USER_TYPE", "AD_ID")
    gw = LLMGateway()
    assert gw._extra_headers == {
        "x-dep-ticket": "test-ticket-123",
        "Send-System-Name": "test-sys",
        "User-Id": "user-abc",
        "User-Type": "AD_ID",
    }
    # Prompt-Msg-Id / Completion-Msg-Id 는 static 에 포함되지 않음 (매 호출 생성).
    assert "Prompt-Msg-Id" not in gw._extra_headers
    assert "Completion-Msg-Id" not in gw._extra_headers


def test_extra_headers_none_when_ticket_whitespace_only(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """공백만 있는 ticket env → _extra_headers None (운영자 실수 방어)."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_X_DEP_TICKET", "   ")
    gw = LLMGateway()
    assert gw._extra_headers is None


def test_extra_headers_uses_defaults_when_optional_not_set(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """x-dep-ticket 만 설정 시 optional env 들은 'macro-logbot' / 'AD_ID' default."""
    monkeypatch.setenv("MACRO_LOGBOT_LLM_X_DEP_TICKET", "ticket-only")
    gw = LLMGateway()
    assert gw._extra_headers == {
        "x-dep-ticket": "ticket-only",
        "Send-System-Name": "macro-logbot",
        "User-Id": "macro-logbot",
        "User-Type": "AD_ID",
    }


@pytest.mark.asyncio
async def test_complete_injects_extra_headers_with_fresh_msg_ids(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """complete() 호출 시 _extra_headers + 매번 새 Prompt/Completion-Msg-Id 가 LiteLLM 에 전달.

    LiteLLM acompletion 응답 mock 은 복잡 (ModelResponse 객체 필요) — kwargs capture 후
    raise 로 끊어서 LiteLLM 호출 시점의 kwargs 만 검증.
    """
    monkeypatch.setenv("MACRO_LOGBOT_LLM_X_DEP_TICKET", "tkt")
    gw = LLMGateway()

    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop — kwargs captured")

    from macro_logbot.gateway.models import Message

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete([Message(role="user", content="hi")], model="m")
        with pytest.raises(RuntimeError):
            await gw.complete([Message(role="user", content="hi")], model="m")

    assert len(captured) == 2
    h1 = captured[0]["extra_headers"]
    h2 = captured[1]["extra_headers"]
    # static 부분 동일
    assert h1["x-dep-ticket"] == "tkt"
    assert h1["Send-System-Name"] == "macro-logbot"
    # Prompt-Msg-Id / Completion-Msg-Id 가 매 호출 새 UUID
    assert h1["Prompt-Msg-Id"] != h2["Prompt-Msg-Id"]
    assert h1["Completion-Msg-Id"] != h2["Completion-Msg-Id"]
    # UUID 형식 (8-4-4-4-12)
    import re

    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    assert uuid_re.match(h1["Prompt-Msg-Id"])
    assert uuid_re.match(h1["Completion-Msg-Id"])


@pytest.mark.asyncio
async def test_complete_no_extra_headers_when_ticket_not_set(clean_env: None) -> None:
    """x-dep-ticket 미설정 시 LiteLLM 호출 kwargs 에 extra_headers 미포함 (backward compat)."""
    gw = LLMGateway()
    captured: list[dict] = []

    async def fake_ac(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        raise RuntimeError("stop — kwargs captured")

    from macro_logbot.gateway.models import Message

    with patch("macro_logbot.gateway.client.litellm.acompletion", side_effect=fake_ac):
        with pytest.raises(RuntimeError):
            await gw.complete([Message(role="user", content="hi")], model="m")
    assert "extra_headers" not in captured[0]
