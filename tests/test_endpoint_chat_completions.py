"""POST /v1/chat/completions 엔드포인트 통합 테스트."""

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


def _mock_response(content: str = "Mock response") -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-mock-001",
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
        usage=Usage(prompt_tokens=8, completion_tokens=3, total_tokens=11),
    )


def _make_mock_gateway() -> LLMGateway:
    """고정 응답을 반환하는 mock LLMGateway."""
    gateway = LLMGateway.__new__(LLMGateway)
    gateway.default_model = "openai/gpt-4o-mini"
    gateway.complete = AsyncMock(return_value=_mock_response())  # type: ignore[method-assign]
    return gateway


@pytest.fixture
def client_with_mock_gateway() -> Iterator[TestClient]:
    """mock gateway 가 주입된 TestClient."""
    mock_gw = _make_mock_gateway()
    app.dependency_overrides[get_gateway] = lambda: mock_gw
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_chat_completions_happy_path_agent_mode(
    client_with_mock_gateway: TestClient,
) -> None:
    """기본 agent 모드 — body.tools 미명시 → run_agent 통과."""
    # run_agent 내부에서 gateway.complete 가 1회 호출되며 tool_calls 없으니
    # 즉시 final 로 종료.
    response = client_with_mock_gateway.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Mock response"


def test_chat_completions_raw_passthrough_when_tools_set(
    client_with_mock_gateway: TestClient,
) -> None:
    """body.tools 명시 → agent loop 우회, gateway 직접 호출 (tools forward)."""
    response = client_with_mock_gateway.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "custom",
                        "description": "x",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        },
    )
    assert response.status_code == 200
    mock_gw = app.dependency_overrides[get_gateway]()
    # call_args.kwargs 에 tools 가 forward 됐어야 함.
    call_kwargs = mock_gw.complete.call_args.kwargs
    assert "tools" in call_kwargs
    assert call_kwargs["tools"][0]["function"]["name"] == "custom"


def test_chat_completions_agent_false_query_param(
    client_with_mock_gateway: TestClient,
) -> None:
    """?agent=false 시 tools 미첨부 raw 호출."""
    response = client_with_mock_gateway.post(
        "/v1/chat/completions?agent=false",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
        },
    )
    assert response.status_code == 200
    mock_gw = app.dependency_overrides[get_gateway]()
    call_kwargs = mock_gw.complete.call_args.kwargs
    # raw 경로 — tools 자동 첨부 없음.
    assert "tools" not in call_kwargs


def test_chat_completions_missing_messages(
    client_with_mock_gateway: TestClient,
) -> None:
    response = client_with_mock_gateway.post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4o-mini"},
    )
    assert response.status_code == 422


def test_chat_completions_missing_model(
    client_with_mock_gateway: TestClient,
) -> None:
    response = client_with_mock_gateway.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )
    assert response.status_code == 422


def test_chat_completions_stream_rejected(
    client_with_mock_gateway: TestClient,
) -> None:
    response = client_with_mock_gateway.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        },
    )
    assert response.status_code == 400
    assert "streaming not yet supported" in response.json()["detail"]


def test_chat_completions_omits_none_kwargs() -> None:
    """raw passthrough 경로에서 None Optional 필드는 forward 안 한다."""
    mock_gw = LLMGateway.__new__(LLMGateway)
    mock_gw.default_model = "openai/gpt-4o-mini"
    mock_gw.complete = AsyncMock(return_value=_mock_response())  # type: ignore[method-assign]
    app.dependency_overrides[get_gateway] = lambda: mock_gw
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions?agent=false",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )
        assert response.status_code == 200
        call_kwargs = mock_gw.complete.call_args.kwargs
        assert "temperature" not in call_kwargs
        assert "max_tokens" not in call_kwargs
    finally:
        app.dependency_overrides.clear()


def test_chat_completions_agent_loop_uses_run_agent(
    client_with_mock_gateway: TestClient,
) -> None:
    """agent 모드 진입 시 run_agent 가 호출되는지 직접 검증."""
    fake_result = AgentRunResult(
        response=_mock_response(content="agent answered"),
        iterations=1,
        messages=[],
    )
    with patch(
        "macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_result)
    ) as mock_run:
        response = client_with_mock_gateway.post(
            "/v1/chat/completions",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "go"}],
            },
        )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "agent answered"
        mock_run.assert_called_once()
