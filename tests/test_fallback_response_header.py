"""HTTP 응답 헤더 fallback 메타데이터 노출 테스트 — task-AGENT-009-b.

X-MacroLogBot-Fallback-Used / X-MacroLogBot-Fallback-Pattern 헤더가
/v1/chat/completions 와 /agent/analyze 에서 올바르게 설정되는지 검증.
"""

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

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_response(
    content: str = "ok",
    fallback_used: str | None = None,
    fallback_pattern: str | None = None,
) -> ChatCompletionResponse:
    r = ChatCompletionResponse(
        id="chatcmpl-hdr-test",
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
    r._fallback_used = fallback_used
    r._fallback_pattern = fallback_pattern
    return r


def _make_mock_gateway(chat_resp: ChatCompletionResponse) -> LLMGateway:
    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    gw.complete = AsyncMock(return_value=chat_resp)  # type: ignore[method-assign]
    return gw


@pytest.fixture(autouse=True)
def reset_app_singletons() -> Iterator[None]:
    """각 테스트 전후로 app 모듈 레벨 singleton 초기화."""
    import macro_logbot.app as app_module
    from macro_logbot.session import InMemorySessionStore

    app_module._reset_singletons_for_test()
    app_module._session_store = InMemorySessionStore()  # type: ignore[assignment]
    yield
    app_module._reset_singletons_for_test()


# ---------------------------------------------------------------------------
# /v1/chat/completions — raw passthrough 경로 (agent=false)
# ---------------------------------------------------------------------------


def test_chat_completions_layer1_header_raw_path() -> None:
    """raw passthrough 경로: Layer 1 fallback → X-MacroLogBot-Fallback-Used 헤더."""
    chat_resp = _make_response(fallback_used="layer1_no_tools_retry")
    mock_gw = _make_mock_gateway(chat_resp)
    app.dependency_overrides[get_gateway] = lambda: mock_gw
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions?agent=false",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200
        assert response.headers.get("x-macrologbot-fallback-used") == "layer1_no_tools_retry"
        assert "x-macrologbot-fallback-pattern" not in response.headers
    finally:
        app.dependency_overrides.clear()


def test_chat_completions_layer2_function_xml_header_raw_path() -> None:
    """raw passthrough 경로: Layer 2 function_xml → 두 헤더 모두 설정."""
    chat_resp = _make_response(
        fallback_used="layer2_regex_inject",
        fallback_pattern="function_xml",
    )
    mock_gw = _make_mock_gateway(chat_resp)
    app.dependency_overrides[get_gateway] = lambda: mock_gw
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions?agent=false",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200
        assert response.headers.get("x-macrologbot-fallback-used") == "layer2_regex_inject"
        assert response.headers.get("x-macrologbot-fallback-pattern") == "function_xml"
    finally:
        app.dependency_overrides.clear()


def test_chat_completions_normal_path_no_fallback_headers() -> None:
    """정상 경로 (raw): fallback 헤더 absent."""
    chat_resp = _make_response()  # _fallback_used=None, _fallback_pattern=None
    mock_gw = _make_mock_gateway(chat_resp)
    app.dependency_overrides[get_gateway] = lambda: mock_gw
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions?agent=false",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200
        assert "x-macrologbot-fallback-used" not in response.headers
        assert "x-macrologbot-fallback-pattern" not in response.headers
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /v1/chat/completions — agent loop 경로 (기본 agent=true)
# ---------------------------------------------------------------------------


def test_chat_completions_layer1_header_agent_path() -> None:
    """agent loop 경로: Layer 1 fallback → X-MacroLogBot-Fallback-Used 헤더."""
    chat_resp = _make_response(fallback_used="layer1_no_tools_retry")
    fake_result = AgentRunResult(response=chat_resp, iterations=1, messages=[])
    app.dependency_overrides[get_gateway] = lambda: _make_mock_gateway(chat_resp)
    try:
        with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_result)):
            client = TestClient(app)
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        assert response.status_code == 200
        assert response.headers.get("x-macrologbot-fallback-used") == "layer1_no_tools_retry"
        assert "x-macrologbot-fallback-pattern" not in response.headers
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "fallback_pattern",
    ["function_xml", "tool_call_xml", "json_codeblock", "python_tag"],
)
def test_chat_completions_layer2_patterns_agent_path(fallback_pattern: str) -> None:
    """agent loop 경로: Layer 2 4개 패턴 각각 헤더 검증."""
    chat_resp = _make_response(
        fallback_used="layer2_regex_inject",
        fallback_pattern=fallback_pattern,
    )
    fake_result = AgentRunResult(response=chat_resp, iterations=1, messages=[])
    app.dependency_overrides[get_gateway] = lambda: _make_mock_gateway(chat_resp)
    try:
        with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_result)):
            client = TestClient(app)
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": "check"}],
                },
            )
        assert response.status_code == 200
        assert response.headers.get("x-macrologbot-fallback-used") == "layer2_regex_inject"
        assert response.headers.get("x-macrologbot-fallback-pattern") == fallback_pattern
    finally:
        app.dependency_overrides.clear()


def test_chat_completions_normal_path_no_fallback_headers_agent_path() -> None:
    """agent loop 정상 경로: fallback 헤더 absent."""
    chat_resp = _make_response()
    fake_result = AgentRunResult(response=chat_resp, iterations=1, messages=[])
    app.dependency_overrides[get_gateway] = lambda: _make_mock_gateway(chat_resp)
    try:
        with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_result)):
            client = TestClient(app)
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        assert response.status_code == 200
        assert "x-macrologbot-fallback-used" not in response.headers
        assert "x-macrologbot-fallback-pattern" not in response.headers
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /agent/analyze
# ---------------------------------------------------------------------------


@pytest.fixture
def client_with_mock_gateway_analyze() -> Iterator[TestClient]:
    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    app.dependency_overrides[get_gateway] = lambda: gw
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_agent_analyze_layer1_header(
    client_with_mock_gateway_analyze: TestClient,
) -> None:
    """agent/analyze: Layer 1 fallback → X-MacroLogBot-Fallback-Used 헤더."""
    chat_resp = _make_response(
        content="분석 결과",
        fallback_used="layer1_no_tools_retry",
    )
    fake_result = AgentRunResult(response=chat_resp, iterations=1, messages=[])
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_result)):
        response = client_with_mock_gateway_analyze.post(
            "/agent/analyze",
            json={"log_text": "2026-05-20 10:00:00 ERROR: crash"},
        )
    assert response.status_code == 200
    assert response.headers.get("x-macrologbot-fallback-used") == "layer1_no_tools_retry"
    assert "x-macrologbot-fallback-pattern" not in response.headers


@pytest.mark.parametrize(
    "fallback_pattern",
    ["function_xml", "tool_call_xml", "json_codeblock", "python_tag"],
)
def test_agent_analyze_layer2_patterns(
    client_with_mock_gateway_analyze: TestClient,
    fallback_pattern: str,
) -> None:
    """agent/analyze: Layer 2 4개 패턴 각각 헤더 검증."""
    chat_resp = _make_response(
        content="분석 결과",
        fallback_used="layer2_regex_inject",
        fallback_pattern=fallback_pattern,
    )
    fake_result = AgentRunResult(response=chat_resp, iterations=1, messages=[])
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_result)):
        response = client_with_mock_gateway_analyze.post(
            "/agent/analyze",
            json={"log_text": "2026-05-20 10:00:00 ERROR: crash"},
        )
    assert response.status_code == 200
    assert response.headers.get("x-macrologbot-fallback-used") == "layer2_regex_inject"
    assert response.headers.get("x-macrologbot-fallback-pattern") == fallback_pattern


def test_agent_analyze_normal_path_no_fallback_headers(
    client_with_mock_gateway_analyze: TestClient,
) -> None:
    """agent/analyze 정상 경로: fallback 헤더 absent."""
    chat_resp = _make_response(content="정상 분석")
    fake_result = AgentRunResult(response=chat_resp, iterations=1, messages=[])
    with patch("macro_logbot.app.run_agent", new=AsyncMock(return_value=fake_result)):
        response = client_with_mock_gateway_analyze.post(
            "/agent/analyze",
            json={"log_text": "2026-05-20 10:00:00 INFO: all good"},
        )
    assert response.status_code == 200
    assert "x-macrologbot-fallback-used" not in response.headers
    assert "x-macrologbot-fallback-pattern" not in response.headers


# ---------------------------------------------------------------------------
# OpenAI 호환 body 무변경 확인
# ---------------------------------------------------------------------------


def test_chat_completions_body_unchanged_when_fallback() -> None:
    """fallback 헤더 설정 시에도 응답 body 에 fallback 필드 없음 (OpenAI 호환 유지)."""
    chat_resp = _make_response(
        fallback_used="layer2_regex_inject",
        fallback_pattern="function_xml",
    )
    mock_gw = _make_mock_gateway(chat_resp)
    app.dependency_overrides[get_gateway] = lambda: mock_gw
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions?agent=false",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200
        body = response.json()
        # PrivateAttr 는 body 에 절대 노출 안 됨.
        assert "_fallback_used" not in body
        assert "_fallback_pattern" not in body
        # OpenAI 표준 필드는 정상.
        assert "choices" in body
        assert "id" in body
    finally:
        app.dependency_overrides.clear()
