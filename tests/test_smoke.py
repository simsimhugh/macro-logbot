"""End-to-end smoke tests — mocked agent loop 으로 인증 + endpoint 흐름 검증."""

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
        id="chatcmpl-smoke",
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
        usage=Usage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
    )


@pytest.fixture
def smoke_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """API key 설정 + gateway DI mock 으로 e2e smoke 환경 구성."""
    monkeypatch.setenv("MACRO_LOGBOT_API_KEY", "smoke-test-key")
    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    app.dependency_overrides[get_gateway] = lambda: gw
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_smoke_chat_completion_with_auth_and_agent_loop(
    smoke_client: TestClient,
) -> None:
    """Open WebUI 가 보낼 흐름: Bearer 인증 + /v1/chat/completions agent 모드."""
    fake = AgentRunResult(
        response=_final_response("MACRO 분석 결과: DB 커넥션 풀 고갈"),
        iterations=2,
        messages=[],
    )
    with patch(
        "macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)
    ) as mock_run:
        response = smoke_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer smoke-test-key"},
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "MACRO 에러 분석해줘"}
                ],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "MACRO 분석 결과: DB 커넥션 풀 고갈"
    mock_run.assert_called_once()


def test_smoke_agent_analyze_with_auth(smoke_client: TestClient) -> None:
    """`/agent/analyze` Bearer 인증 + intake parsing + agent loop 결과 노출."""
    fake = AgentRunResult(
        response=_final_response("원인: 연결 거부, 조치: 네트워크 점검"),
        iterations=1,
        messages=[],
    )
    log_text = (
        "2026-05-19 14:30:01 ERROR: DB connection failed\n"
        "Traceback (most recent call last):\n"
        "ConnectionError: refused\n"
    )
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake)):
        response = smoke_client.post(
            "/agent/analyze",
            headers={"Authorization": "Bearer smoke-test-key"},
            json={"log_text": log_text},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["terminated_reason"] == "final"
    assert body["iterations"] == 1
    assert "원인" in body["analysis"]
    record = body["record"]
    assert record["level"] == "ERROR"
    # raw 는 응답 직렬화에서 제외돼야 한다 (사내 로그 본문 보호).
    assert "raw" not in record


def test_smoke_health_unauthenticated(smoke_client: TestClient) -> None:
    """헬스 체크는 인증 없이 접근 가능 — 로드 밸런서/모니터링 호환."""
    response = smoke_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
