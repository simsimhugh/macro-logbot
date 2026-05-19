"""PoC evaluate.py 단위 테스트 — score_1a + comparison.md 작성 검증."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALUATE_PATH = REPO_ROOT / "poc" / "scripts" / "evaluate.py"


def _load(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


evaluate_mod = _load("poc_evaluate", EVALUATE_PATH)


def test_score_1a_full_match() -> None:
    ground_truth: dict[str, Any] = {
        "location": {"file": "snake.py", "line": 90},
        "root_cause_keywords": ["AttributeError", "NoneType", "head"],
    }
    analysis = (
        "snake.py 의 line 90 부근에서 AttributeError 발생. "
        "self.head 가 NoneType 인 상태로 .x 접근. head 초기화 누락."
    )
    score = evaluate_mod.score_1a(analysis, ground_truth)
    assert score["file_match"] is True
    assert score["line_match"] is True
    assert score["keyword_hits"] == 3
    assert score["naive_score_0_to_1"] == 1.0


def test_score_1a_partial_match() -> None:
    ground_truth: dict[str, Any] = {
        "location": {"file": "snake.py", "line": 90},
        "root_cause_keywords": ["AttributeError", "NoneType"],
    }
    # file 만 매칭, line 없음, keyword 1/2.
    analysis = "snake.py 에서 AttributeError 비슷한 문제로 보입니다."
    score = evaluate_mod.score_1a(analysis, ground_truth)
    assert score["file_match"] is True
    assert score["line_match"] is False
    assert score["keyword_hits"] == 1
    # 0.4 (file) + 0 + 0.3 * (1/2) = 0.55
    assert score["naive_score_0_to_1"] == 0.55


def test_score_1a_empty_ground_truth() -> None:
    score = evaluate_mod.score_1a("아무 분석", {})
    assert score["file_match"] is False
    assert score["line_match"] is False
    assert score["keyword_hits"] == 0
    assert score["naive_score_0_to_1"] == 0.0


def test_write_comparison_renders_table(tmp_path: Path) -> None:
    results: list[dict[str, Any]] = [
        {
            "case_id": "E001",
            "score_1a": {
                "file_match": True,
                "line_match": True,
                "keyword_hits": 2,
                "naive_score_0_to_1": 0.85,
            },
        },
        {
            "case_id": "E002",
            "error": "trigger failed",
        },
    ]
    path = evaluate_mod.write_comparison(tmp_path, results)
    text = path.read_text(encoding="utf-8")
    assert "| E001 |" in text
    assert "0.85" in text
    assert "trigger failed" in text


def test_write_report_dumps_json(tmp_path: Path) -> None:
    result: dict[str, Any] = {"case_id": "E001", "score_1a": {"naive_score_0_to_1": 0.5}}
    path = evaluate_mod.write_report(tmp_path, "E001", result)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["case_id"] == "E001"
    assert loaded["score_1a"]["naive_score_0_to_1"] == 0.5


# ---------------------------------------------------------------------------
# --judge-api-key / env-var auto-detect (PR #31)
# ---------------------------------------------------------------------------


def test_main_groq_judge_env_auto_detect(tmp_path: Path) -> None:
    """GROQ_API_KEY env 자동 감지 — --judge-api-key 미지정 시 env 사용."""
    env = {**os.environ, "GROQ_API_KEY": "gsk_autodetect", "MACRO_LOGBOT_API_KEY": "test-key"}

    fake_result: dict[str, Any] = {
        "case_id": "E001",
        "started_at": "2026-01-01T00:00:00+00:00",
        "score_1a": {
            "file_match": False,
            "line_match": False,
            "keyword_hits": 0,
            "naive_score_0_to_1": 0.0,
        },
    }

    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(evaluate_mod, "evaluate_case", return_value=fake_result) as mock_eval,
        patch.object(evaluate_mod, "write_report", return_value=tmp_path / "E001.json"),
        patch.object(evaluate_mod, "write_comparison", return_value=tmp_path / "comparison.md"),
    ):
        rc = evaluate_mod.main(
            [
                "--cases", "E001",
                "--judge", "groq/llama-3.3-70b-versatile",
                "--api-key", "test-key",
                "--reports-dir", str(tmp_path),
            ]
        )
    assert rc == 0
    _, kwargs = mock_eval.call_args
    assert kwargs["judge_model"] == "groq/llama-3.3-70b-versatile"
    assert kwargs["judge_api_key"] == "gsk_autodetect"


def test_main_judge_api_key_flag_takes_precedence(tmp_path: Path) -> None:
    """--judge-api-key 명시 시 env 보다 우선."""
    env = {**os.environ, "GROQ_API_KEY": "gsk_from_env", "MACRO_LOGBOT_API_KEY": "test-key"}

    fake_result: dict[str, Any] = {
        "case_id": "E001",
        "started_at": "2026-01-01T00:00:00+00:00",
        "score_1a": {
            "file_match": False,
            "line_match": False,
            "keyword_hits": 0,
            "naive_score_0_to_1": 0.0,
        },
    }

    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(evaluate_mod, "evaluate_case", return_value=fake_result) as mock_eval,
        patch.object(evaluate_mod, "write_report", return_value=tmp_path / "E001.json"),
        patch.object(evaluate_mod, "write_comparison", return_value=tmp_path / "comparison.md"),
    ):
        rc = evaluate_mod.main(
            [
                "--cases", "E001",
                "--judge", "groq/llama-3.3-70b-versatile",
                "--judge-api-key", "gsk_explicit",
                "--api-key", "test-key",
                "--reports-dir", str(tmp_path),
            ]
        )
    assert rc == 0
    _, kwargs = mock_eval.call_args
    assert kwargs["judge_api_key"] == "gsk_explicit"


def test_main_judge_missing_api_key_returns_2(tmp_path: Path) -> None:
    """API key 없을 때 rc=2 + stderr 메시지."""
    import io

    excluded = ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
    env = {k: v for k, v in os.environ.items() if k not in excluded}
    env["MACRO_LOGBOT_API_KEY"] = "test-key"

    with patch.dict(os.environ, env, clear=True):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            rc = evaluate_mod.main(
                [
                    "--cases", "E001",
                    "--judge", "groq/llama-3.3-70b-versatile",
                    "--api-key", "test-key",
                    "--reports-dir", str(tmp_path),
                ]
            )
    assert rc == 2
    assert "GROQ_API_KEY" in buf.getvalue()
