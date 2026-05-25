"""Run the injected snake.py and capture traceback from stderr.

Spec ref: docs/process/04-PoC-운영가이드.md §5.2, docs/design/02-설계문서.md §10.4.

Usage:
    python poc/scripts/eval/trigger.py --case E001 --workdir /tmp/snake-E001 [--timeout 15]

Stdout: prints traceback text (may be empty if injection failed / no error).
Exit code:
    0 — process raised an exception (good — injection worked)
    1 — process exited cleanly (injection produced no error — false negative)
    2 — process timed out
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT_SEC = 15


def trigger(workdir: Path, timeout: int = DEFAULT_TIMEOUT_SEC) -> tuple[int, str]:
    """workdir 안 snake.py 를 headless 로 실행하고 stderr 반환.

    Returns: (exit_code, stderr_text).
        exit_code:
          0 — process raised exception (good).
          1 — clean exit (no injection error).
          2 — timeout.
    """
    env = dict(os.environ)
    env["SDL_VIDEODRIVER"] = "dummy"
    try:
        completed = subprocess.run(
            [sys.executable, "snake.py", "--headless", "--auto-play", "5"],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return 2, f"timeout after {timeout}s: {exc}"
    # snake.py 가 정상 충돌 (die) 시에도 returncode 0 으로 종료할 수 있으므로
    # stderr 에 "Traceback" 본문이 있는지 양조건 확인 — injection 에러 캡처 robust.
    if completed.returncode != 0 or "Traceback" in completed.stderr:
        return 0, completed.stderr
    # 정상 종료 + traceback 없음 → injection 실패 (false negative).
    return 1, completed.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger an injected snake.py.")
    parser.add_argument("--case", required=True, help="case id (참고용, 라우팅엔 미사용)")
    parser.add_argument("--workdir", required=True, help="snake.py 가 있는 디렉토리")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"subprocess timeout seconds (default {DEFAULT_TIMEOUT_SEC})",
    )
    args = parser.parse_args(argv)
    workdir = Path(args.workdir).resolve()
    if not (workdir / "snake.py").is_file():
        print(f"error: {workdir}/snake.py not found — run inject.py first", file=sys.stderr)
        return 3
    exit_code, stderr_text = trigger(workdir, args.timeout)
    print(stderr_text, end="")
    if exit_code == 1:
        print(f"\n[trigger] {args.case}: clean exit (no error captured)", file=sys.stderr)
    elif exit_code == 2:
        print(f"\n[trigger] {args.case}: timeout", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
