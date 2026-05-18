"""Built-in tool 구현체.

각 함수는 동기. agent loop 안에서 asyncio.to_thread 로 await 가능.
예외 catch → {"error": str(e)} 반환 (LLM 이 자체 처리).

보안 (MVP 수준):
  - path 가 절대 경로면 그대로, 상대면 Path.cwd() 기준 resolve.
  - 결과 경로가 cwd 밖이면 error 반환 (path traversal 차단).
  - subprocess 호출은 shell=False, 인자 리스트 형식만 사용.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.3
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# MVP 수준 — subprocess 호출 timeout 일괄 적용 (deadlock 방지).
_SUBPROCESS_TIMEOUT_SEC = 15


def _safe_resolve(path: str) -> Path | None:
    """cwd 안으로 제한된 절대 경로를 반환. 밖이면 None."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()
    cwd = Path.cwd().resolve()
    if not resolved.is_relative_to(cwd):
        return None
    return resolved


def grep_codebase(
    pattern: str,
    path: str = ".",
    max_results: int = 50,
) -> dict[str, Any]:
    """Python 파일 안에서 정규/문자열 패턴을 검색.

    Returns:
      {"matches": [{"file": str, "line": int, "text": str}, ...], "truncated": bool}
      혹은 {"error": str}.
    """
    safe = _safe_resolve(path)
    if safe is None:
        return {"error": "path outside working directory"}
    try:
        completed = subprocess.run(
            ["grep", "-rn", "--include=*.py", pattern, str(safe)],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}

    # grep returncode 1 = no match (정상). >=2 = 실제 오류.
    if completed.returncode >= 2:
        return {"error": completed.stderr.strip() or "grep failed"}

    matches: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        # 형식: "<file>:<lineno>:<text>"
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_path, line_no, text = parts
        try:
            line_no_int = int(line_no)
        except ValueError:
            continue
        matches.append({"file": file_path, "line": line_no_int, "text": text})
        if len(matches) >= max_results:
            break
    truncated = len(matches) >= max_results and (
        completed.stdout.count("\n") > max_results
    )
    return {"matches": matches, "truncated": truncated}


def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_lines: int = 200,
) -> dict[str, Any]:
    """파일 내용을 (옵션으로 라인 범위 슬라이스 하여) 반환.

    start_line / end_line 은 1-indexed, inclusive.
    max_lines 는 컨텍스트 폭주 가드 — slice 결과가 초과 시 truncate + `truncated=True`.
    """
    safe = _safe_resolve(path)
    if safe is None:
        return {"error": "path outside working directory"}
    if not safe.is_file():
        return {"error": f"not a file: {path}"}
    try:
        text = safe.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": str(exc)}

    lines = text.splitlines()
    total = len(lines)
    start_idx = (start_line - 1) if start_line else 0
    end_idx = end_line if end_line else total
    start_idx = max(0, start_idx)
    end_idx = min(total, end_idx)
    sliced = lines[start_idx:end_idx]
    truncated = False
    if len(sliced) > max_lines:
        sliced = sliced[:max_lines]
        truncated = True
        end_idx = start_idx + max_lines
    return {
        "path": str(safe),
        "content": "\n".join(sliced),
        "total_lines": total,
        "start_line": start_idx + 1 if sliced else None,
        "end_line": end_idx if sliced else None,
        "truncated": truncated,
    }


def list_directory(
    path: str = ".",
    recursive: bool = False,
) -> dict[str, Any]:
    """디렉토리 항목 나열. 숨김 파일(.) 제외."""
    safe = _safe_resolve(path)
    if safe is None:
        return {"error": "path outside working directory"}
    if not safe.is_dir():
        return {"error": f"not a directory: {path}"}

    entries: list[dict[str, Any]] = []
    try:
        iterator = safe.rglob("*") if recursive else safe.iterdir()
        for entry in iterator:
            # 숨김 항목 — 어느 부모라도 . 으로 시작하면 skip.
            if any(part.startswith(".") for part in entry.relative_to(safe).parts):
                continue
            entries.append(
                {
                    "name": str(entry.relative_to(safe)),
                    "type": "dir" if entry.is_dir() else "file",
                }
            )
    except OSError as exc:
        return {"error": str(exc)}

    entries.sort(key=lambda e: e["name"])
    return {"path": str(safe), "entries": entries}


def git_blame(
    path: str,
    start_line: int,
    end_line: int,
) -> dict[str, Any]:
    """git blame -L <start>,<end> -- <path> 결과를 raw text 로 반환."""
    safe = _safe_resolve(path)
    if safe is None:
        return {"error": "path outside working directory"}
    if not safe.is_file():
        return {"error": f"not a file: {path}"}
    try:
        completed = subprocess.run(
            [
                "git",
                "blame",
                "-L",
                f"{start_line},{end_line}",
                "--",
                str(safe),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
    if completed.returncode != 0:
        return {"error": completed.stderr.strip() or "git blame failed"}
    return {
        "path": str(safe),
        "start_line": start_line,
        "end_line": end_line,
        "blame": completed.stdout,
    }


def search_logs(
    pattern: str,
    log_dir: str,
) -> dict[str, Any]:
    """log_dir 내 .log/.txt 파일들에서 패턴 검색.

    Returns:
      {"matches": [{"file": str, "line": int, "text": str}, ...]} 혹은 {"error": str}.
    """
    safe = _safe_resolve(log_dir)
    if safe is None:
        return {"error": "path outside working directory"}
    if not safe.is_dir():
        return {"error": f"not a directory: {log_dir}"}
    try:
        completed = subprocess.run(
            [
                "grep",
                "-rn",
                "--include=*.log",
                "--include=*.txt",
                pattern,
                str(safe),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
    if completed.returncode >= 2:
        return {"error": completed.stderr.strip() or "grep failed"}

    matches: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_path, line_no, text = parts
        try:
            line_no_int = int(line_no)
        except ValueError:
            continue
        matches.append({"file": file_path, "line": line_no_int, "text": text})
    return {"matches": matches}
