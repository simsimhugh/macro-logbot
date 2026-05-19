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

import platform
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

# MVP 수준 — subprocess 호출 timeout 일괄 적용 (deadlock 방지).
_SUBPROCESS_TIMEOUT_SEC = 15

# read_file 메모리 가드 — 거대 파일/바이너리 OOM 방지.
_READ_FILE_MAX_BYTES = 2_000_000

# git --oneline 출력의 hash 부분 검증 (4~40자 hex). control char/빈줄/오염 차단.
_GIT_HASH_RE = re.compile(r"[0-9a-f]{4,40}")


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
    truncated = False
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
            truncated = True
            break
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
        size = safe.stat().st_size
    except OSError as exc:
        return {"error": str(exc)}
    # 메모리 가드 — 큰 파일은 전체 로드 거절 (LLM 이 라인 범위 명시하도록).
    if size > _READ_FILE_MAX_BYTES:
        return {
            "error": (
                f"file too large: {size} bytes (max {_READ_FILE_MAX_BYTES}). "
                "specify start_line/end_line/max_lines to read a slice."
            )
        }
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
    max_results: int = 50,
) -> dict[str, Any]:
    """log_dir 내 .log/.txt 파일들에서 패턴 검색.

    Returns:
      {"matches": [{"file": str, "line": int, "text": str}, ...], "truncated": bool}
      혹은 {"error": str}.
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
    truncated = False
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
        if len(matches) >= max_results:
            truncated = True
            break
    return {"matches": matches, "truncated": truncated}


def git_log(
    path: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """git log --oneline -n<limit> [-- <path>] 결과를 파싱해 commits list 로 반환.

    path 미지정 시 전체 repo 의 최근 limit 건. path 지정 시 _safe_resolve 로 검증.

    Returns:
      {"commits": [{"hash": str, "message": str}, ...], "truncated": bool}
      혹은 {"error": str}.

    Note: `truncated` 는 commit 개수가 limit 에 도달했음을 의미하며, 실제로 더 많은
    commit 이 존재하는지 여부와는 별개 (정확히 limit 건만 있는 repo 도 True).
    """
    cmd = ["git", "log", "--oneline", f"-n{limit}"]
    if path is not None:
        safe = _safe_resolve(path)
        if safe is None:
            return {"error": "path outside working directory"}
        cmd.extend(["--", str(safe)])
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
    if completed.returncode != 0:
        return {"error": completed.stderr.strip() or "git log failed"}

    commits: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        # --oneline 형식: "<hash> <message>" — single space 구분.
        parts = line.split(" ", 1)
        commit_hash = parts[0] if parts else ""
        if not _GIT_HASH_RE.fullmatch(commit_hash):
            # hash 패턴 위반 (빈 줄, control char 포함 등) 은 skip.
            continue
        message = parts[1] if len(parts) > 1 else ""
        commits.append({"hash": commit_hash, "message": message})
    truncated = len(commits) >= limit
    return {"commits": commits, "truncated": truncated}


def find_test_history(
    test_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """MACRO 테스트 과거 실행 결과 — 사외 PoC 는 mock.

    사외 PoC 환경엔 사내 MACRO test DB 가 없으므로 빈 test_runs 반환.
    사내 운영 진입 시 후속 PR (task-MVP-003-x) 에서 실제 DB 연동.

    `limit` 인자는 인터페이스 호환용 — mock 단계에서는 무시됨 (실제 DB
    연동 PR 에서 적용).

    Returns:
      {"test_id": str, "test_runs": [], "note": str} 혹은 {"error": str}.
    """
    if not test_id or not isinstance(test_id, str):
        return {"error": "test_id required"}
    _ = limit
    return {
        "test_id": test_id,
        "test_runs": [],
        "note": "mock — 사내 MACRO test DB 연동은 후속 PR (task-MVP-003-x)",
    }


# get_environment_info 가 노출할 핵심 패키지 — 시크릿/env vars 일체 노출 X.
_ENV_INFO_PACKAGES = (
    "litellm",
    "fastapi",
    "langgraph",
    "pydantic",
    "pygame-ce",
    "pyyaml",
)


def get_environment_info(
    scope: str | None = None,
) -> dict[str, Any]:
    """현재 실행 환경 정보 — OS / Python / 핵심 패키지 버전.

    scope 는 인터페이스 호환용 — 현재는 무시하고 항상 동일 dict 반환.
    시크릿 (api_key 등) 및 env vars 는 노출 X.
    """
    # scope 는 향후 필터링용 — 현재는 정적 dict.
    _ = scope
    packages: dict[str, str] = {}
    for name in _ENV_INFO_PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = "not installed"
    return {
        "python": sys.version.split()[0],
        "os": platform.system(),
        "platform": platform.platform(),
        "packages": packages,
    }


def retrieve_similar_cases(
    error_signature: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """과거 유사 에러 분석 사례 — KB (spec §5.5) 미구현 placeholder.

    KB 구현 PR 후 실제 검색 로직 추가 (task-MVP-003-x).

    `top_k` 인자는 인터페이스 호환용 — placeholder 단계에서는 무시됨 (KB
    실구현 PR 에서 적용).

    Returns:
      {"error_signature": str, "similar_cases": [], "note": str} 혹은 {"error": str}.
    """
    if not error_signature or not isinstance(error_signature, str):
        return {"error": "error_signature required"}
    _ = top_k
    return {
        "error_signature": error_signature,
        "similar_cases": [],
        "note": "KB (spec §5.5) 미구현 placeholder — 후속 PR (task-MVP-003-x)",
    }
