"""poc/scripts/demo/demo_session.py 단위 테스트 — mock HTTP, argparse 검증."""

from __future__ import annotations

import importlib.util
import json
import sys
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_PATH = REPO_ROOT / "scripts" / "demo_session.py"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


demo = _load("demo_session_under_test", DEMO_PATH)


def _mock_analyze_response(session_id: str, analysis: str) -> dict[str, Any]:
    """post_analyze 가 반환하는 dict 흉내."""
    return {
        "session_id": session_id,
        "analysis": analysis,
        "report": {"root_cause": analysis[:80], "confidence": 0.5},
    }


def test_argparse_requires_one_source() -> None:
    """--case / --log / --prompt 중 하나 필수 (mutually exclusive)."""
    with pytest.raises(SystemExit):
        demo.main(["--api-key", "k"])


def test_argparse_rejects_two_sources() -> None:
    """--case 와 --log 동시 사용 시 argparse 에러."""
    with pytest.raises(SystemExit):
        demo.main(["--case", "E001", "--log", "x", "--api-key", "k"])


def test_main_requires_api_key(capsys: pytest.CaptureFixture[str]) -> None:
    """--api-key 또는 env 없으면 종료."""
    with patch.dict("os.environ", {"MACRO_LOGBOT_API_KEY": ""}, clear=False):
        exit_code = demo.main(["--prompt", "hi"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "MACRO_LOGBOT_API_KEY" in captured.err


def test_main_first_turn_returns_session_id_then_loop_uses_it() -> None:
    """첫 호출은 session_id=None, 두 번째 호출은 같은 session_id 사용."""
    first = _mock_analyze_response("sess-abc-123", "첫 분석")
    second = _mock_analyze_response("sess-abc-123", "follow-up 답변")

    call_args: list[dict[str, Any]] = []

    def fake_post(api_url, api_key, log_text, model, session_id, timeout):
        call_args.append(
            {
                "log_text": log_text,
                "session_id": session_id,
            }
        )
        return first if len(call_args) == 1 else second

    # input() 한 번 응답 후 빈 입력으로 종료.
    inputs = iter(["추가 질문이요"])

    def fake_input(prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            return ""  # 종료 트리거.

    with (
        patch.object(demo, "post_analyze", side_effect=fake_post),
        patch("builtins.input", side_effect=fake_input),
    ):
        exit_code = demo.main(["--prompt", "안녕", "--api-key", "k"])
    assert exit_code == 0
    assert len(call_args) == 2
    # 첫 호출: session_id=None
    assert call_args[0]["session_id"] is None
    assert call_args[0]["log_text"] == "안녕"
    # 두 번째 호출: 같은 sid
    assert call_args[1]["session_id"] == "sess-abc-123"
    assert call_args[1]["log_text"] == "추가 질문이요"


def test_post_analyze_includes_session_id_in_body() -> None:
    """post_analyze body 에 session_id 가 들어가는지 검증 (없으면 키 제외)."""
    fake_resp = StringIO(json.dumps({"session_id": "x", "analysis": "ok"}))

    class FakeURLOpen:
        def __init__(self, _req, timeout=None):
            self.req = _req

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return fake_resp.getvalue().encode("utf-8")

    captured: list[bytes] = []

    def fake_urlopen(req, timeout=None):
        captured.append(req.data)
        return FakeURLOpen(req, timeout=timeout)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        # session_id 있는 경우
        demo.post_analyze("http://x", "k", "log", None, "sid-1", 10)
        # session_id 없는 경우
        demo.post_analyze("http://x", "k", "log2", None, None, 10)

    body_with_sid = json.loads(captured[0].decode("utf-8"))
    body_without_sid = json.loads(captured[1].decode("utf-8"))
    assert body_with_sid["session_id"] == "sid-1"
    assert body_with_sid["log_text"] == "log"
    assert "session_id" not in body_without_sid  # None 이면 제외
    assert body_without_sid["log_text"] == "log2"
