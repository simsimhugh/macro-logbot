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


# ---------------------------------------------------------------------------
# spec §10.4 — temperature=0 / seed=42 payload (task-EVAL-001)
# ---------------------------------------------------------------------------


def test_call_backend_payload_includes_temperature_and_seed(tmp_path: Path) -> None:
    """call_backend POST payload 에 temperature=0, seed=42 포함 검증."""
    import urllib.request
    from unittest.mock import MagicMock

    captured: dict[str, Any] = {}

    class _FakeResp:
        def read(self) -> bytes:
            return b'{"analysis": "ok"}'

        def __enter__(self) -> "_FakeResp":
            return self

        def __exit__(self, *_: object) -> None:
            pass

    def _fake_urlopen(req: Any, timeout: int = 0) -> _FakeResp:
        import json
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp()

    with patch.object(urllib.request, "urlopen", side_effect=_fake_urlopen):
        evaluate_mod.call_backend(
            "http://localhost:8000", "test-key", "some traceback", "test-model"
        )

    assert captured["payload"]["temperature"] == 0
    assert captured["payload"]["seed"] == 42


def test_call_backend_session_id_included_when_provided(tmp_path: Path) -> None:
    """session_id 전달 시 payload 에 포함됨 검증."""
    import urllib.request

    captured: dict[str, Any] = {}

    class _FakeResp:
        def read(self) -> bytes:
            return b'{"analysis": "ok"}'

        def __enter__(self) -> "_FakeResp":
            return self

        def __exit__(self, *_: object) -> None:
            pass

    def _fake_urlopen(req: Any, timeout: int = 0) -> _FakeResp:
        import json
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp()

    with patch.object(urllib.request, "urlopen", side_effect=_fake_urlopen):
        evaluate_mod.call_backend(
            "http://localhost:8000", "test-key", "traceback", None, session_id="sess-xyz"
        )

    assert captured["payload"]["session_id"] == "sess-xyz"


def test_call_backend_no_session_id_when_none() -> None:
    """session_id=None 이면 payload 에 session_id 키 없음."""
    import urllib.request

    captured: dict[str, Any] = {}

    class _FakeResp:
        def read(self) -> bytes:
            return b'{"analysis": "ok"}'

        def __enter__(self) -> "_FakeResp":
            return self

        def __exit__(self, *_: object) -> None:
            pass

    def _fake_urlopen(req: Any, timeout: int = 0) -> _FakeResp:
        import json
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp()

    with patch.object(urllib.request, "urlopen", side_effect=_fake_urlopen):
        evaluate_mod.call_backend(
            "http://localhost:8000", "test-key", "traceback", None
        )

    assert "session_id" not in captured["payload"]


# ---------------------------------------------------------------------------
# spec §10.1 — 4-channel 25%×4 total scoring (task-EVAL-001)
# ---------------------------------------------------------------------------


def test_evaluate_case_total_scoring_25pct_each(tmp_path: Path) -> None:
    """judge 모드 시 total = 0.25·1A + 0.25·1B + 0.25·2A + 0.25·2B."""
    from unittest.mock import MagicMock

    fake_backend: dict[str, Any] = {"analysis": "snake.py line 90 AttributeError"}
    fake_judge: dict[str, Any] = {
        "score_1b": {"score": 0.8, "reasoning": "ok"},
        "score_2a": {"score": 0.6, "reasoning": "ok"},
        "score_2b": {"score": 0.4, "reasoning": "ok"},
    }

    with (
        patch.object(evaluate_mod, "inject", return_value={
            "ground_truth": {
                "location": {"file": "snake.py", "line": 90},
                "root_cause_keywords": ["AttributeError"],
            }
        }),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback text")),
        patch.object(evaluate_mod, "call_backend", return_value=fake_backend),
        patch.object(evaluate_mod, "run_judge", return_value=fake_judge),
    ):
        result = evaluate_mod.evaluate_case(
            "E001",
            "http://localhost:8000",
            "test-key",
            "test-model",
            judge_model="groq/llama-3.3-70b-versatile",
            judge_api_key="gsk_test",
        )

    s1a = result["score_1a"]["naive_score_0_to_1"]
    expected_total = round(0.25 * s1a + 0.25 * 0.8 + 0.25 * 0.6 + 0.25 * 0.4, 3)
    assert result["naive_score_total"] == expected_total
    assert result["scored_axes"] == 4


def test_evaluate_case_total_scoring_partial_judge_failure(tmp_path: Path) -> None:
    """judge score=None 항목은 0 으로 처리, scored_axes < 4 기록."""
    fake_backend: dict[str, Any] = {"analysis": ""}
    fake_judge: dict[str, Any] = {
        "score_1b": {"score": 0.5, "reasoning": "ok"},
        "score_2a": {"score": None, "reasoning": "judge failed"},
        "score_2b": {"score": 0.4, "reasoning": "ok"},
    }

    with (
        patch.object(evaluate_mod, "inject", return_value={"ground_truth": {}}),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback")),
        patch.object(evaluate_mod, "call_backend", return_value=fake_backend),
        patch.object(evaluate_mod, "run_judge", return_value=fake_judge),
    ):
        result = evaluate_mod.evaluate_case(
            "E001",
            "http://localhost:8000",
            "test-key",
            "test-model",
            judge_model="groq/llama-3.3-70b-versatile",
            judge_api_key="gsk_test",
        )

    # scored_axes = 3 (2A 실패)
    assert result["scored_axes"] == 3
    # total = 0.25*0 + 0.25*0.5 + 0.25*0 + 0.25*0.4 = 0.225
    assert result["naive_score_total"] == round(0.25 * 0.0 + 0.25 * 0.5 + 0.25 * 0.0 + 0.25 * 0.4, 3)


# ---------------------------------------------------------------------------
# spec §10.6 — --session-cumulative (task-EVAL-001)
# ---------------------------------------------------------------------------


def test_main_session_cumulative_threads_session_id(tmp_path: Path) -> None:
    """--session-cumulative: 첫 case 응답 session_id 가 후속 case 에 전달됨."""
    call_count = 0
    recorded_session_ids: list[str | None] = []

    def _fake_evaluate_case(
        case_id: str,
        api_url: str,
        api_key: str,
        model: str | None,
        timeout: int,
        *,
        judge_model: str | None = None,
        judge_api_key: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        recorded_session_ids.append(session_id)
        return {
            "case_id": case_id,
            "started_at": "2026-01-01T00:00:00+00:00",
            "backend_response": {"session_id": "sess-from-backend"},
            "score_1a": {
                "file_match": False,
                "line_match": False,
                "keyword_hits": 0,
                "naive_score_0_to_1": 0.0,
            },
        }

    env = {**os.environ, "MACRO_LOGBOT_API_KEY": "test-key"}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(evaluate_mod, "evaluate_case", side_effect=_fake_evaluate_case),
        patch.object(evaluate_mod, "write_report", return_value=tmp_path / "x.json"),
        patch.object(evaluate_mod, "write_comparison", return_value=tmp_path / "c.md"),
    ):
        rc = evaluate_mod.main(
            [
                "--cases", "E001,E002",
                "--api-key", "test-key",
                "--rate-limit-cooldown", "0",
                "--reports-dir", str(tmp_path),
                "--session-cumulative",
            ]
        )

    assert rc == 0
    assert call_count == 2
    # 첫 case: session_id=None
    assert recorded_session_ids[0] is None
    # 두 번째 case: 첫 응답의 session_id echo
    assert recorded_session_ids[1] == "sess-from-backend"


def test_main_no_session_cumulative_default(tmp_path: Path) -> None:
    """--session-cumulative 미지정 시 session_id=None 유지."""
    recorded_session_ids: list[str | None] = []

    def _fake_evaluate_case(
        case_id: str,
        api_url: str,
        api_key: str,
        model: str | None,
        timeout: int,
        *,
        judge_model: str | None = None,
        judge_api_key: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        recorded_session_ids.append(session_id)
        return {
            "case_id": case_id,
            "started_at": "2026-01-01T00:00:00+00:00",
            "backend_response": {"session_id": "sess-ignored"},
            "score_1a": {
                "file_match": False,
                "line_match": False,
                "keyword_hits": 0,
                "naive_score_0_to_1": 0.0,
            },
        }

    env = {**os.environ, "MACRO_LOGBOT_API_KEY": "test-key"}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(evaluate_mod, "evaluate_case", side_effect=_fake_evaluate_case),
        patch.object(evaluate_mod, "write_report", return_value=tmp_path / "x.json"),
        patch.object(evaluate_mod, "write_comparison", return_value=tmp_path / "c.md"),
    ):
        rc = evaluate_mod.main(
            [
                "--cases", "E001,E002",
                "--api-key", "test-key",
                "--rate-limit-cooldown", "0",
                "--reports-dir", str(tmp_path),
            ]
        )

    assert rc == 0
    # 두 case 모두 session_id=None (cumulative off)
    assert all(sid is None for sid in recorded_session_ids)
