"""POST /v1/chat/completions 엔드포인트 통합 테스트."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from macro_logbot.app import app, get_gateway
from macro_logbot.gateway import LLMGateway
from macro_logbot.gateway.models import (
    ChatCompletionResponse,
    Choice,
    Message,
    Usage,
)


def _make_mock_gateway() -> LLMGateway:
    """고정 응답을 반환하는 mock LLMGateway."""
    mock_response = ChatCompletionResponse(
        id="chatcmpl-mock-001",
        object="chat.completion",
        created=int(time.time()),
        model="openai/gpt-4o-mini",
        choices=[
            Choice(
                index=0,
                message=Message(role="assistant", content="Mock response"),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=8, completion_tokens=3, total_tokens=11),
    )
    gateway = LLMGateway.__new__(LLMGateway)
    gateway.default_model = "openai/gpt-4o-mini"
    gateway.complete = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]
    return gateway


@pytest.fixture
def client_with_mock_gateway() -> TestClient:
    """mock gateway 가 주입된 TestClient."""
    mock_gw = _make_mock_gateway()
    app.dependency_overrides[get_gateway] = lambda: mock_gw
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_chat_completions_happy_path(client_with_mock_gateway: TestClient) -> None:
    """정상 요청 시 200 OK 와 OpenAI 호환 응답 body 를 반환한다."""
    response = client_with_mock_gateway.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "chatcmpl-mock-001"
    assert body["object"] == "chat.completion"
    assert len(body["choices"]) == 1
    assert body["choices"][0]["message"]["content"] == "Mock response"
    assert body["usage"]["total_tokens"] == 11


def test_chat_completions_missing_messages(client_with_mock_gateway: TestClient) -> None:
    """messages 필드 누락 시 422 Unprocessable Entity 를 반환한다."""
    response = client_with_mock_gateway.post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4o-mini"},
    )
    assert response.status_code == 422


def test_chat_completions_missing_model(client_with_mock_gateway: TestClient) -> None:
    """model 필드 누락 시 422 Unprocessable Entity 를 반환한다."""
    response = client_with_mock_gateway.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )
    assert response.status_code == 422
