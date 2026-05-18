"""POST /agent/analyze 엔드포인트 통합 테스트."""

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


def _final_response(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-analyze",
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
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


@pytest.fixture
def client_with_mock_gateway() -> Iterator[TestClient]:
    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    app.dependency_overrides[get_gateway] = lambda: gw
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_agent_analyze_happy_path(
    client_with_mock_gateway: TestClient,
) -> None:
    fake = AgentRunResult(
        response=_final_response("원인: DB 연결 실패. 조치: ..."),
        iterations=2,
        messages=[],
    )
    log_text = (
        "2026-05-19 14:30:01 ERROR: DB connection failed\n"
        "Traceback (most recent call last):\n"
        "ConnectionError: refused\n"
    )
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": log_text},
        )
    assert response.status_code == 200
    body = response.json()
    assert "DB 연결 실패" in body["analysis"]
    assert body["iterations"] == 2
    record = body["record"]
    assert record["level"] == "ERROR"
    assert "DB connection failed" in record["message"]
    assert record["traceback"] is not None
    # raw 는 응답 직렬화에서 자동 제외 (사내 deploy 로그 본문 노출 방지).
    assert "raw" not in record


def test_agent_analyze_requires_log_text(
    client_with_mock_gateway: TestClient,
) -> None:
    response = client_with_mock_gateway.post("/agent/analyze", json={})
    assert response.status_code == 422


def test_agent_analyze_no_choices_returns_empty_analysis(
    client_with_mock_gateway: TestClient,
) -> None:
    empty_resp = ChatCompletionResponse(
        id="chatcmpl-empty",
        object="chat.completion",
        created=int(time.time()),
        model="openai/gpt-4o-mini",
        choices=[],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )
    fake = AgentRunResult(response=empty_resp, iterations=1, messages=[])
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = client_with_mock_gateway.post(
            "/agent/analyze",
            json={"log_text": "unrecognized log"},
        )
    assert response.status_code == 200
    assert response.json()["analysis"] == ""
