"""단위 테스트 — poc/scripts/claude_judge.py (1-B/2-A/2-B judge 함수).

mock LiteLLM completion → happy path + JSON parse 실패 분기.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
JUDGE_PATH = REPO_ROOT / "poc" / "scripts" / "claude_judge.py"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


judge_mod = _load("poc_claude_judge", JUDGE_PATH)


def _make_litellm_response(content: str) -> MagicMock:
    """litellm.completion 반환값 흉내."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# 1-B judge_root_cause
# ---------------------------------------------------------------------------


def test_judge_root_cause_happy_path() -> None:
    payload = json.dumps({"score": 1.0, "reasoning": "exact match"})
    with patch("litellm.completion", return_value=_make_litellm_response(payload)):
        result = judge_mod.judge_root_cause(
            ground_truth="head 객체 미초기화 상태에서 .x 접근",
            response="AttributeError: self.head is None when accessing .x",
            model="claude-haiku-4-5",
        )
    assert result["score"] == 1.0
    assert result["reasoning"] == "exact match"


def test_judge_root_cause_json_parse_failure() -> None:
    with patch("litellm.completion", return_value=_make_litellm_response("not json")):
        result = judge_mod.judge_root_cause(
            ground_truth="some cause",
            response="some response",
            model="claude-haiku-4-5",
        )
    assert result["score"] == 0.0
    assert "JSON parse error" in result["reasoning"]


# ---------------------------------------------------------------------------
# 2-A judge_tool_appropriateness
# ---------------------------------------------------------------------------


def test_judge_tool_appropriateness_happy_path() -> None:
    payload = json.dumps({"score": 0.5, "reasoning": "partial — grep used, read_file missing"})
    with patch("litellm.completion", return_value=_make_litellm_response(payload)):
        result = judge_mod.judge_tool_appropriateness(
            expected_tools=["grep_codebase", "read_file"],
            actual_tool_calls=[{"tool": "grep_codebase", "args": {}}],
            model="gemini/gemini-2.5-flash-lite",
        )
    assert result["score"] == 0.5
    assert "partial" in result["reasoning"]


def test_judge_tool_appropriateness_json_parse_failure() -> None:
    with patch("litellm.completion", return_value=_make_litellm_response("{bad json")):
        result = judge_mod.judge_tool_appropriateness(
            expected_tools=["read_file"],
            actual_tool_calls=[],
            model="claude-haiku-4-5",
        )
    assert result["score"] == 0.0
    assert "JSON parse error" in result["reasoning"]


# ---------------------------------------------------------------------------
# 2-B judge_fix_direction
# ---------------------------------------------------------------------------


def test_judge_fix_direction_happy_path() -> None:
    payload = json.dumps({"score": 1.0, "reasoning": "same location and method"})
    with patch("litellm.completion", return_value=_make_litellm_response(payload)):
        result = judge_mod.judge_fix_direction(
            ground_truth_fix="init_game() 호출 후 guard 추가",
            response_fix="update_position 앞에 init guard 삽입",
            model="claude-haiku-4-5",
        )
    assert result["score"] == 1.0
    assert result["reasoning"] == "same location and method"


def test_judge_fix_direction_json_parse_failure() -> None:
    with patch("litellm.completion", return_value=_make_litellm_response("")):
        result = judge_mod.judge_fix_direction(
            ground_truth_fix="add guard",
            response_fix="",
            model="claude-haiku-4-5",
        )
    assert result["score"] == 0.0
    assert "JSON parse error" in result["reasoning"]
