"""macro-logbot multi-turn 데모 CLI.

사용 예:
    # PoC case 자동 inject + trigger + 분석
    python scripts/demo_session.py --case E001

    # 직접 로그 분석
    python scripts/demo_session.py --log "$(cat /tmp/error.log)"

    # 직접 prompt
    python scripts/demo_session.py --prompt "안녕하세요"

흐름:
    1. 첫 호출 — POST /agent/analyze (session_id=None) → session_id + 분석 응답.
    2. 같은 session_id 로 follow-up loop (input() REPL) — Ctrl+C 또는 빈 입력 종료.

Spec ref: docs/process/04-PoC-운영가이드.md §5.3 + PR #25 (session_id 통합).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
POC_SCRIPTS = REPO_ROOT / "poc" / "scripts"

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 180


def post_analyze(
    api_url: str,
    api_key: str,
    log_text: str,
    model: str | None,
    session_id: str | None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """POST /agent/analyze — session_id 명시 시 follow-up 컨텍스트 이어짐."""
    payload: dict[str, Any] = {"log_text": log_text}
    if model:
        payload["model"] = model
    if session_id:
        payload["session_id"] = session_id
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=f"{api_url.rstrip('/')}/agent/analyze",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        # nosec B310 — URL 은 사용자 args, 사설 사내/로컬만 허용 의도.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
        return cast(dict[str, Any], json.loads(raw))
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"}
    except urllib.error.URLError as exc:
        return {"error": f"URLError: {exc}"}
    except (TimeoutError, json.JSONDecodeError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _build_initial_log(args: argparse.Namespace) -> str:
    """첫 turn 의 log_text 결정 — case/log/prompt 중 하나."""
    if args.case:
        if str(POC_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(POC_SCRIPTS))
        from inject import inject  # type: ignore[import-not-found]
        from trigger import trigger  # type: ignore[import-not-found]

        workdir = Path(tempfile.mkdtemp(prefix=f"demo-{args.case}-"))
        inject(args.case, workdir)
        exit_code, stderr_text = trigger(workdir)
        print(f"[case {args.case} inject + trigger 완료 — exit={exit_code}]", file=sys.stderr)
        return stderr_text
    if args.log:
        return args.log
    if args.prompt:
        return args.prompt
    raise RuntimeError("--case / --log / --prompt 중 하나 필요")


def _print_response(resp: dict[str, Any]) -> None:
    """응답 본문 + report 예쁘게 출력."""
    if "error" in resp:
        print(f"[ERROR] {resp['error']}", file=sys.stderr)
        return
    analysis = resp.get("analysis", "")
    print(f"\nBot> {analysis}")
    report = resp.get("report")
    if report:
        print("\n[Report]")
        print(f"  root_cause: {str(report.get('root_cause', ''))[:300]}")
        loc = report.get("location")
        if loc:
            print(f"  location:   {loc}")
        print(f"  confidence: {report.get('confidence')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="macro-logbot multi-turn 데모 (session_id 통합).",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--case", help="PoC error catalog case id (예: E001)")
    src.add_argument("--log", help="직접 로그 본문")
    src.add_argument("--prompt", help="단순 prompt (analyze 에 그대로 전달)")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("MACRO_LOGBOT_API_URL", DEFAULT_API_URL),
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MACRO_LOGBOT_API_KEY", ""),
        help="Bearer key — 기본 env MACRO_LOGBOT_API_KEY",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    if not args.api_key:
        print("error: --api-key 또는 MACRO_LOGBOT_API_KEY 필요", file=sys.stderr)
        return 2

    initial_log = _build_initial_log(args)
    print("[첫 분석 호출 중...]", file=sys.stderr)
    resp = post_analyze(args.api_url, args.api_key, initial_log, args.model, None, args.timeout)
    sid = resp.get("session_id")
    if not sid:
        print(f"[error] session_id 받지 못함: {resp.get('error', resp)}", file=sys.stderr)
        return 1
    print(f"\n[session: {sid[:12]}...]", file=sys.stderr)
    _print_response(resp)

    print("\n[Multi-turn 대화 — 빈 입력 또는 Ctrl+C 로 종료]", file=sys.stderr)
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except EOFError, KeyboardInterrupt:
            print("\n[종료]", file=sys.stderr)
            return 0
        if not user_input:
            print("[종료]", file=sys.stderr)
            return 0
        print("[follow-up 호출 중...]", file=sys.stderr)
        resp = post_analyze(args.api_url, args.api_key, user_input, args.model, sid, args.timeout)
        _print_response(resp)


if __name__ == "__main__":
    raise SystemExit(main())
