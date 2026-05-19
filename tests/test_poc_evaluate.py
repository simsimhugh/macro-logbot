"""PoC evaluate.py 단위 테스트 — score_1a + comparison.md 작성 검증."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

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
