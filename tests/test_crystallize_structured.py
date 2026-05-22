"""_crystallize_report_node 강화 — structured JSON 추출 + traceback fallback 테스트.

task-AGENT-011: structured Report 변환 강화.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from macro_logbot.agent.core import (
    AgentState,
    Report,
    _crystallize_report_node,
    _location_from_traceback,
    _parse_structured_json,
)
from macro_logbot.gateway import (
    ChatCompletionResponse,
    Choice,
    LLMGateway,
    Message,
    Usage,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _resp(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-test",
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


def _mock_gateway(responses: list[ChatCompletionResponse]) -> LLMGateway:
    gw = LLMGateway.__new__(LLMGateway)
    gw.default_model = "openai/gpt-4o-mini"
    gw.complete = AsyncMock(side_effect=responses)  # type: ignore[method-assign]
    return gw


def _base_state(
    messages: list[Message],
    gateway: LLMGateway | None = None,
) -> AgentState:
    """테스트용 최소 AgentState. gateway 미지정 시 빈 mock (complete 미정의)."""
    if gateway is None:
        gateway = LLMGateway.__new__(LLMGateway)
    return AgentState(
        messages=messages,
        iteration=0,
        max_iters=20,
        last_response=None,
        report=None,
        session_id=None,
        event_id=None,
        _model=None,
        _generation_kwargs={},
        _gateway=gateway,
    )


_VALID_JSON = """{
  "root_cause": "NullPointerException in parse_record()",
  "location": {"file": "parser.py", "function": "parse_record", "line": 42},
  "fix_hint": "None チェックを追加する",
  "confidence": 0.85,
  "reasoning_summary": "parse_record 에서 None 체크 누락"
}"""

_VALID_JSON_NULL_LOCATION = """{
  "root_cause": "설정 파일 오류",
  "location": null,
  "fix_hint": "config.yaml 확인",
  "confidence": 0.6,
  "reasoning_summary": "설정 파일 누락"
}"""


# ---------------------------------------------------------------------------
# unit: _parse_structured_json
# ---------------------------------------------------------------------------


def test_parse_structured_json_valid() -> None:
    result = _parse_structured_json(_VALID_JSON)
    assert result is not None
    assert result["root_cause"] == "NullPointerException in parse_record()"
    assert result["confidence"] == 0.85


def test_parse_structured_json_with_code_fence() -> None:
    fenced = f"```json\n{_VALID_JSON}\n```"
    result = _parse_structured_json(fenced)
    assert result is not None
    assert result["root_cause"] == "NullPointerException in parse_record()"


def test_parse_structured_json_invalid_returns_none() -> None:
    assert _parse_structured_json("not json at all") is None
    assert _parse_structured_json('{"unclosed": ') is None


def test_parse_structured_json_list_returns_none() -> None:
    assert _parse_structured_json("[1, 2, 3]") is None


# ---------------------------------------------------------------------------
# unit: _location_from_traceback
# ---------------------------------------------------------------------------


def test_location_from_traceback_extracts_last_frame() -> None:
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "/app/macro_logbot/intake/parser.py", line 10, in parse_macro_log\n'
        "    record = _parse(text)\n"
        '  File "/app/macro_logbot/agent/core.py", line 55, in _inner\n'
        '    raise ValueError("boom")\n'
    )
    loc = _location_from_traceback(stderr)
    assert loc is not None
    assert loc.file == "core.py"
    assert loc.line == 55
    assert loc.function == "_inner"


def test_location_from_traceback_no_traceback_returns_none() -> None:
    assert _location_from_traceback("just a plain error message") is None
    assert _location_from_traceback("") is None


def test_location_from_traceback_single_frame() -> None:
    stderr = 'File "/srv/app/utils.py", line 7, in helper\n    pass\n'
    loc = _location_from_traceback(stderr)
    assert loc is not None
    assert loc.file == "utils.py"
    assert loc.line == 7
    assert loc.function == "helper"


# ---------------------------------------------------------------------------
# _crystallize_report_node: structured JSON LLM 답 → Report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crystallize_structured_json_answer() -> None:
    """LLM 이 valid JSON 답변 → Report 필드 정확 추출."""
    gw = _mock_gateway([_resp(_VALID_JSON)])
    state = _base_state(
        [
            Message(role="user", content="ERROR: something failed"),
            Message(role="assistant", content="분석 결과: parser.py 42번 줄에서 NPE"),
        ],
        gateway=gw,
    )
    result = await _crystallize_report_node(state)
    report = result["report"]
    assert isinstance(report, Report)
    assert report.root_cause == "NullPointerException in parse_record()"
    assert report.fix_hint == "None チェックを追加する"
    assert report.confidence == pytest.approx(0.85)
    assert report.reasoning_summary == "parse_record 에서 None 체크 누락"
    assert report.location is not None
    assert report.location.file == "parser.py"
    assert report.location.line == 42
    assert report.location.function == "parse_record"


@pytest.mark.asyncio
async def test_crystallize_null_location_uses_traceback_fallback() -> None:
    """LLM 이 location=null 반환 → user message traceback 에서 fallback 추출."""
    gw = _mock_gateway([_resp(_VALID_JSON_NULL_LOCATION)])
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "/app/macro_logbot/intake/parser.py", line 99, in load\n'
        '    raise IOError("missing config")\n'
    )
    state = _base_state(
        [
            Message(role="user", content=stderr),
            Message(role="assistant", content="설정 파일이 없습니다"),
        ],
        gateway=gw,
    )
    result = await _crystallize_report_node(state)
    report = result["report"]
    assert isinstance(report, Report)
    assert report.location is not None
    assert report.location.file == "parser.py"
    assert report.location.line == 99
    assert report.location.function == "load"


@pytest.mark.asyncio
async def test_crystallize_schema_violation_retries_once_then_succeeds() -> None:
    """첫 번째 응답이 schema 미준수(plain text) → 재시도 1회 후 valid JSON 으로 성공."""
    gw = _mock_gateway(
        [
            _resp("죄송합니다, 분석 결과를 정리하겠습니다."),  # schema 미준수
            _resp(_VALID_JSON),  # retry 성공
        ]
    )
    state = _base_state(
        [
            Message(role="user", content="ERROR: boom"),
            Message(role="assistant", content="파서에서 오류"),
        ],
        gateway=gw,
    )
    result = await _crystallize_report_node(state)
    report = result["report"]
    assert isinstance(report, Report)
    assert report.root_cause == "NullPointerException in parse_record()"
    assert report.location is not None
    assert report.location.line == 42
    # gateway 가 2회 호출됐는지 확인.
    assert gw.complete.call_count == 2  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_crystallize_no_traceback_location_remains_none() -> None:
    """LLM location=null + user message 에 traceback 없음 → location=None."""
    gw = _mock_gateway([_resp(_VALID_JSON_NULL_LOCATION)])
    state = _base_state(
        [
            Message(role="user", content="일반적인 에러 메시지 (traceback 없음)"),
            Message(role="assistant", content="설정 파일 오류"),
        ],
        gateway=gw,
    )
    result = await _crystallize_report_node(state)
    report = result["report"]
    assert isinstance(report, Report)
    assert report.location is None


@pytest.mark.asyncio
async def test_crystallize_both_attempts_fail_mvp_fallback() -> None:
    """2회 모두 schema 미준수 → MVP fallback (root_cause = last assistant content)."""
    gw = _mock_gateway(
        [
            _resp("plain text 1"),
            _resp("plain text 2"),
        ]
    )
    last_content = "LLM 최종 분석 내용"
    state = _base_state(
        [
            Message(role="user", content="ERROR: test"),
            Message(role="assistant", content=last_content),
        ],
        gateway=gw,
    )
    result = await _crystallize_report_node(state)
    report = result["report"]
    assert isinstance(report, Report)
    assert report.root_cause == last_content
    assert report.confidence == pytest.approx(0.5)
    assert report.location is None


@pytest.mark.asyncio
async def test_crystallize_confidence_clamped_to_range() -> None:
    """confidence 가 범위 초과(예: 1.5) → 1.0 로 clamp."""
    out_of_range_json = """{
      "root_cause": "오류 원인",
      "location": null,
      "fix_hint": "수정 힌트",
      "confidence": 1.5,
      "reasoning_summary": "요약"
    }"""
    gw = _mock_gateway([_resp(out_of_range_json)])
    state = _base_state(
        [Message(role="assistant", content="분석")],
        gateway=gw,
    )
    result = await _crystallize_report_node(state)
    assert result["report"] is not None
    assert result["report"].confidence == pytest.approx(1.0)
