"""GET /v1/models 엔드포인트 테스트 — Open WebUI 가 모델 picker 채우려고 호출."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from macro_logbot.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """dev 모드 — 인증 미설정 + AUTH_REQUIRED=false 로 인증 skip."""
    monkeypatch.delenv("MACRO_LOGBOT_API_KEY", raising=False)
    monkeypatch.setenv("MACRO_LOGBOT_AUTH_REQUIRED", "false")
    yield TestClient(app)


def test_list_models_returns_openai_compatible_shape(client: TestClient) -> None:
    """GET /v1/models 가 OpenAI 호환 형식 (object=list, data=[...]) 반환."""
    response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1
    model = body["data"][0]
    assert "id" in model
    assert model["object"] == "model"
    assert model["owned_by"] == "macro-logbot"


def test_list_models_reflects_default_model_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MACRO_LOGBOT_DEFAULT_MODEL env 가 모델 id 로 노출됨."""
    monkeypatch.setenv("MACRO_LOGBOT_DEFAULT_MODEL", "gemini/gemini-1.5-flash")
    monkeypatch.delenv("MACRO_LOGBOT_API_KEY", raising=False)
    monkeypatch.setenv("MACRO_LOGBOT_AUTH_REQUIRED", "false")
    client = TestClient(app)
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "gemini/gemini-1.5-flash"


def test_list_models_requires_auth_when_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API key 설정된 상태에서 인증 없이 호출 → 401."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-key")
    monkeypatch.setenv("MACRO_LOGBOT_AUTH_REQUIRED", "true")
    client = TestClient(app)
    response = client.get("/v1/models")
    assert response.status_code == 401


def test_list_models_accepts_bearer_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """올바른 Bearer key 로 호출 → 200."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "secret-key")
    monkeypatch.setenv("MACRO_LOGBOT_AUTH_REQUIRED", "true")
    client = TestClient(app)
    response = client.get("/v1/models", headers={"Authorization": "Bearer secret-key"})
    assert response.status_code == 200
