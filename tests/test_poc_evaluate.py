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
# spec §10.6 — --continue-session (task-EVAL-001)
# ---------------------------------------------------------------------------


def test_main_continue_session_threads_session_id(tmp_path: Path) -> None:
    """--continue-session: 첫 case 응답 session_id 가 후속 case 에 전달됨."""
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
                "--continue-session",
            ]
        )

    assert rc == 0
    assert call_count == 2
    # 첫 case: session_id=None
    assert recorded_session_ids[0] is None
    # 두 번째 case: 첫 응답의 session_id echo
    assert recorded_session_ids[1] == "sess-from-backend"


def test_main_no_continue_session_default(tmp_path: Path) -> None:
    """--continue-session 미지정 시 session_id=None 유지."""
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


# ---------------------------------------------------------------------------
# PR #44 — inject workdir 위치 검증 (MACRO_LOGBOT_POC_CASES_ROOT)
# ---------------------------------------------------------------------------


def test_evaluate_case_workdir_inside_poc_cases_root(tmp_path: Path) -> None:
    """workdir 가 MACRO_LOGBOT_POC_CASES_ROOT 하위에 생성됨을 검증."""
    poc_root = tmp_path / "poc-cases"

    captured_workdir: list[Path] = []

    def _fake_inject(case_id: str, workdir: Path) -> dict[str, Any]:
        captured_workdir.append(workdir)
        return {"ground_truth": {}}

    with (
        patch.dict(os.environ, {"MACRO_LOGBOT_POC_CASES_ROOT": str(poc_root)}, clear=False),
        patch.object(evaluate_mod, "inject", side_effect=_fake_inject),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback")),
        patch.object(evaluate_mod, "call_backend", return_value={"analysis": "ok"}),
    ):
        evaluate_mod.evaluate_case(
            "E001",
            "http://localhost:8000",
            "test-key",
            None,
        )

    assert len(captured_workdir) == 1
    workdir = captured_workdir[0]
    # workdir 가 poc_root 하위인지 확인
    assert workdir.is_relative_to(poc_root), (
        f"workdir {workdir} 가 poc_root {poc_root} 하위가 아님"
    )
    # prefix 가 case_id 로 시작하는지 확인
    assert workdir.name.startswith("E001-"), (
        f"workdir 이름 {workdir.name!r} 이 'E001-' 로 시작하지 않음"
    )


def test_evaluate_case_workdir_env_override_uses_custom_root(tmp_path: Path) -> None:
    """MACRO_LOGBOT_POC_CASES_ROOT env override 시 해당 경로를 workdir root 로 사용."""
    custom_root = tmp_path / "custom-root"
    # custom_root 는 사전에 존재하지 않음 — evaluate_case 가 mkdir 해야 함.
    assert not custom_root.exists()

    captured_workdir: list[Path] = []

    def _fake_inject(case_id: str, workdir: Path) -> dict[str, Any]:
        captured_workdir.append(workdir)
        return {"ground_truth": {}}

    with (
        patch.dict(os.environ, {"MACRO_LOGBOT_POC_CASES_ROOT": str(custom_root)}, clear=False),
        patch.object(evaluate_mod, "inject", side_effect=_fake_inject),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback")),
        patch.object(evaluate_mod, "call_backend", return_value={"analysis": "ok"}),
    ):
        evaluate_mod.evaluate_case(
            "E002",
            "http://localhost:8000",
            "test-key",
            None,
        )

    assert len(captured_workdir) == 1
    workdir = captured_workdir[0]
    # evaluate_case 가 custom_root 를 mkdir 했는지 확인
    assert custom_root.exists(), "evaluate_case 가 poc_cases_root mkdir 를 수행하지 않음"
    # workdir 가 custom_root 하위인지 확인
    assert workdir.is_relative_to(custom_root)


def test_evaluate_case_workdir_default_is_tmp_poc_cases(tmp_path: Path) -> None:
    """MACRO_LOGBOT_POC_CASES_ROOT 미지정 시 default 는 /tmp/poc-cases."""
    captured_workdir: list[Path] = []

    def _fake_inject(case_id: str, workdir: Path) -> dict[str, Any]:
        captured_workdir.append(workdir)
        return {"ground_truth": {}}

    # MACRO_LOGBOT_POC_CASES_ROOT 를 env 에서 제거해 default 경로 테스트
    env_without_override = {
        k: v for k, v in os.environ.items() if k != "MACRO_LOGBOT_POC_CASES_ROOT"
    }
    with (
        patch.dict(os.environ, env_without_override, clear=True),
        patch.object(evaluate_mod, "inject", side_effect=_fake_inject),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback")),
        patch.object(evaluate_mod, "call_backend", return_value={"analysis": "ok"}),
    ):
        evaluate_mod.evaluate_case(
            "E003",
            "http://localhost:8000",
            "test-key",
            None,
        )

    assert len(captured_workdir) == 1
    workdir = captured_workdir[0]
    # default root = /tmp/poc-cases
    assert workdir.is_relative_to(Path("/tmp/poc-cases")), (
        f"default workdir {workdir} 가 /tmp/poc-cases 하위가 아님"
    )


# ---------------------------------------------------------------------------
# PR #52 — workdir mode 0o755 (backend container uid mismatch)
# ---------------------------------------------------------------------------


def test_evaluate_case_workdir_mode_is_0o755(tmp_path: Path) -> None:
    """PR #52 regression — evaluate_case 가 생성한 workdir 의 mode == 0o755.

    backend container 의 uid 가 host evaluator uid 와 다를 때 read 가능하도록.
    """
    poc_root = tmp_path / "poc-cases"
    captured_workdir: list[Path] = []

    def _fake_inject(case_id: str, workdir: Path) -> dict[str, Any]:
        captured_workdir.append(workdir)
        return {"ground_truth": {}}

    with (
        patch.dict(os.environ, {"MACRO_LOGBOT_POC_CASES_ROOT": str(poc_root)}, clear=False),
        patch.object(evaluate_mod, "inject", side_effect=_fake_inject),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback")),
        patch.object(evaluate_mod, "call_backend", return_value={"analysis": "ok"}),
    ):
        evaluate_mod.evaluate_case(
            "E001",
            "http://localhost:8000",
            "test-key",
            None,
        )

    assert len(captured_workdir) == 1
    mode = captured_workdir[0].stat().st_mode & 0o777
    assert mode == 0o755, f"workdir mode {oct(mode)} != 0o755"


# ---------------------------------------------------------------------------
# PR #53 — infra_error sentinel 검출 (false positive 재발 방지)
# docs/process/04-PoC-운영가이드.md §7.5.1
# ---------------------------------------------------------------------------


def test_evaluate_case_flags_infra_error_on_permission_denied(tmp_path: Path) -> None:
    """analysis 에 'Permission denied' 가 포함되면 result["infra_error"] flag 설정."""
    poc_root = tmp_path / "poc-cases"
    with (
        patch.dict(os.environ, {"MACRO_LOGBOT_POC_CASES_ROOT": str(poc_root)}, clear=False),
        patch.object(evaluate_mod, "inject", return_value={"ground_truth": {}}),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback")),
        patch.object(
            evaluate_mod,
            "call_backend",
            return_value={"analysis": "read_file failed: Permission denied on snake.py"},
        ),
    ):
        result = evaluate_mod.evaluate_case(
            "E001",
            "http://localhost:8000",
            "test-key",
            None,
        )

    assert "infra_error" in result, "fail-fast guard 가 Permission denied sentinel 미검출"
    assert "Permission denied" in result["infra_error"]["sentinels_hit"]
    assert "score_1a" in result, "infra_error 표시해도 score_1a 는 계산되어야 함 (분류만)"


def test_evaluate_case_no_infra_error_on_clean_analysis(tmp_path: Path) -> None:
    """clean analysis (sentinel 없음) 는 infra_error flag 없음."""
    poc_root = tmp_path / "poc-cases"
    with (
        patch.dict(os.environ, {"MACRO_LOGBOT_POC_CASES_ROOT": str(poc_root)}, clear=False),
        patch.object(evaluate_mod, "inject", return_value={"ground_truth": {}}),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback")),
        patch.object(
            evaluate_mod,
            "call_backend",
            return_value={"analysis": "snake.py line 90 의 head 초기화 누락 확인됨"},
        ),
    ):
        result = evaluate_mod.evaluate_case(
            "E001",
            "http://localhost:8000",
            "test-key",
            None,
        )

    assert "infra_error" not in result


def test_evaluate_case_infra_error_detects_multiple_sentinels(tmp_path: Path) -> None:
    """여러 sentinel 동시 hit 시 모두 기록."""
    poc_root = tmp_path / "poc-cases"
    analysis = "read_file: Permission denied, list_directory [Errno 13] not a file: snake.py"
    with (
        patch.dict(os.environ, {"MACRO_LOGBOT_POC_CASES_ROOT": str(poc_root)}, clear=False),
        patch.object(evaluate_mod, "inject", return_value={"ground_truth": {}}),
        patch.object(evaluate_mod, "trigger", return_value=(0, "traceback")),
        patch.object(evaluate_mod, "call_backend", return_value={"analysis": analysis}),
    ):
        result = evaluate_mod.evaluate_case(
            "E001",
            "http://localhost:8000",
            "test-key",
            None,
        )

    sentinels = result["infra_error"]["sentinels_hit"]
    assert "Permission denied" in sentinels
    assert "[Errno 13]" in sentinels
    assert "not a file:" in sentinels
