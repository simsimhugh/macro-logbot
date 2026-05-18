"""src/macro_logbot/auth.py — API key 인증 미들웨어 테스트."""

from __future__ import annotations

import time
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from macro_logbot.agent.core import AgentRunResult
from macro_logbot.app import app, get_gateway
from macro_logbot.gateway import LLMGateway
from macro_logbot.gateway.models import (
    ChatCompletionResponse,
    Choice,
    Message,
    Usage,
)


def _final_response(content: str = "ok") -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-auth-test",
        object="chat.completion",
        created=int(time.time()),
        model="openai/gpt-4o-mini",
        choices=[
            Choice(
                index=0,
                message=Message(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


@pytest.fixture
def client_with_mock_gateway() -> Iterator[TestClient]:
    """gateway DI 만 mock — 인증은 본 모듈에서 직접 검증."""
    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    app.dependency_overrides[get_gateway] = lambda: gw
    yield TestClient(app)
    app.dependency_overrides.clear()


def _post_chat(client: TestClient, headers: dict[str, str] | None = None):
    return client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers=headers,
    )


def test_missing_api_key_returns_401(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """server key 설정됐는데 헤더 없이 호출 → 401."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-server-key")
    monkeypatch.delenv("MACRO_LOGBOT_AUTH_REQUIRED", raising=False)
    response = _post_chat(client_with_mock_gateway)
    assert response.status_code == 401
    assert response.json()["detail"] == "missing API key"
    assert response.headers.get("www-authenticate", "").lower() == "bearer"


def test_invalid_api_key_returns_401(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """틀린 key → 401 invalid API key."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-server-key")
    response = _post_chat(
        client_with_mock_gateway,
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid API key"


def test_valid_bearer_authorizes(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """올바른 Bearer 토큰 → 200."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-server-key")
    fake = AgentRunResult(response=_final_response("hi"), iterations=1, messages=[])
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = _post_chat(
            client_with_mock_gateway,
            headers={"Authorization": "Bearer secret-server-key"},
        )
    assert response.status_code == 200


def test_valid_x_api_key_authorizes(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """올바른 X-API-Key 헤더 → 200."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-server-key")
    fake = AgentRunResult(response=_final_response("hi"), iterations=1, messages=[])
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = _post_chat(
            client_with_mock_gateway,
            headers={"X-API-Key": "secret-server-key"},
        )
    assert response.status_code == 200


def test_health_unauthenticated(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/health 는 인증 제외 — key 설정돼 있어도 헤더 없이 200."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-server-key")
    response = client_with_mock_gateway.get("/health")
    assert response.status_code == 200


def test_auth_required_but_unset_returns_503(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH_REQUIRED=true + server key 미설정 → 503 misconfigured."""
    monkeypatch.delenv("MACRO_LOGBOT_API_KEY", raising=False)
    monkeypatch.setenv("MACRO_LOGBOT_AUTH_REQUIRED", "true")
    response = _post_chat(client_with_mock_gateway)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_auth_optional_unset_allows_request(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH_REQUIRED 미설정/false + server key 미설정 → 인증 skip + 200."""
    monkeypatch.delenv("MACRO_LOGBOT_API_KEY", raising=False)
    monkeypatch.delenv("MACRO_LOGBOT_AUTH_REQUIRED", raising=False)
    fake = AgentRunResult(response=_final_response("hi"), iterations=1, messages=[])
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = _post_chat(client_with_mock_gateway)
    assert response.status_code == 200


def test_bearer_scheme_case_insensitive(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RFC 7235 — Bearer scheme 은 case-insensitive."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-server-key")
    fake = AgentRunResult(response=_final_response("hi"), iterations=1, messages=[])
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = _post_chat(
            client_with_mock_gateway,
            headers={"Authorization": "bearer secret-server-key"},
        )
    assert response.status_code == 200


def test_empty_bearer_token_returns_401(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authorization: Bearer 만 있고 토큰이 비어 있으면 missing 으로 처리 → 401."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-server-key")
    response = _post_chat(
        client_with_mock_gateway,
        headers={"Authorization": "Bearer "},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "missing API key"


def test_agent_analyze_protected_by_auth(
    client_with_mock_gateway: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/agent/analyze 도 인증 dependency 가 걸려 있어야 한다."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-server-key")
    response = client_with_mock_gateway.post(
        "/agent/analyze",
        json={"log_text": "ERROR: x"},
    )
    assert response.status_code == 401
