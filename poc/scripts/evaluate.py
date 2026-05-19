"""Evaluate macro-logbot against each error case.

Spec ref: docs/process/04-PoC-운영가이드.md §5.3 + §6, docs/design/02-설계문서.md §10.1.

흐름 (per case):
    1. tempfile.mkdtemp() → workdir
    2. inject.inject(case, workdir) — error 주입
    3. trigger.trigger(workdir) → traceback 캡처
    4. POST <api>/agent/analyze with traceback + Bearer auth → response JSON
    5. response.analysis vs ground_truth → 결정론 채점 (1-A only — file/line substring 매칭)
    6. case 결과 dump → poc/reports/<YYYY-MM-DD>/<case>.json
    7. (선택) case 간 cooldown — Gemini 5 RPM 회피

본 PR scope:
    - 1-A 결정론 채점만 (file:line substring + 카테고리/keyword 단순 매칭).
    - 1-B/2-A/2-B Claude judge 는 task-POC-001 후속.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

# poc/scripts 안에서 sibling import.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from inject import inject  # noqa: E402
from trigger import trigger  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent.parent
REPORTS_ROOT = REPO_ROOT / "poc" / "reports"

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_MODEL = "gemini/gemini-2.5-flash"
DEFAULT_COOLDOWN_SEC = 60  # Gemini free tier 5 RPM 보호.
DEFAULT_HTTP_TIMEOUT = 120


def call_backend(
    api_url: str,
    api_key: str,
    log_text: str,
    model: str | None,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
) -> dict[str, Any]:
    """POST <api_url>/agent/analyze. 실패 시 {'error': ...} 반환."""
    payload: dict[str, Any] = {"log_text": log_text}
    if model:
        payload["model"] = model
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


def score_1a(analysis: str, ground_truth: dict[str, Any]) -> dict[str, Any]:
    """1-A 결정론 채점 — analysis 가 file:line / 키워드 substring 매칭하는지.

    Returns:
      {
        "file_match": bool,       # location.file substring in analysis
        "line_match": bool,       # str(location.line) substring in analysis
        "keyword_hits": int,      # root_cause_keywords 중 substring 매치 수
        "naive_score_0_to_1": float,
      }
    """
    if not isinstance(ground_truth, dict):
        return {
            "file_match": False,
            "line_match": False,
            "keyword_hits": 0,
            "naive_score_0_to_1": 0.0,
        }
    location = ground_truth.get("location", {}) or {}
    file_name = str(location.get("file", ""))
    line_no = location.get("line")
    keywords = list(ground_truth.get("root_cause_keywords", []) or [])

    file_match = bool(file_name) and file_name in analysis
    line_match = line_no is not None and str(line_no) in analysis
    keyword_hits = sum(1 for kw in keywords if kw and str(kw) in analysis)

    # 단순 가중: file_match 0.4 + line_match 0.3 + keyword 비율 0.3.
    kw_ratio = (keyword_hits / len(keywords)) if keywords else 0.0
    naive = 0.4 * float(file_match) + 0.3 * float(line_match) + 0.3 * kw_ratio
    return {
        "file_match": file_match,
        "line_match": line_match,
        "keyword_hits": keyword_hits,
        "naive_score_0_to_1": round(naive, 3),
    }


def evaluate_case(
    case_id: str,
    api_url: str,
    api_key: str,
    model: str | None,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
) -> dict[str, Any]:
    """단일 case 실행 — inject → trigger → POST /agent/analyze → 채점."""
    workdir = Path(tempfile.mkdtemp(prefix=f"poc-{case_id}-"))
    started_at = _dt.datetime.now(_dt.UTC).isoformat()
    case_meta = inject(case_id, workdir)
    exit_code, stderr_text = trigger(workdir)
    if exit_code != 0:
        return {
            "case_id": case_id,
            "started_at": started_at,
            "error": "trigger failed (clean exit or timeout — no traceback captured)",
            "trigger_exit_code": exit_code,
            "trigger_stderr": stderr_text,
        }
    backend_response = call_backend(api_url, api_key, stderr_text, model, timeout)
    analysis_text = ""
    if "analysis" in backend_response:
        analysis_text = str(backend_response.get("analysis") or "")
    score = score_1a(analysis_text, case_meta.get("ground_truth", {}))
    return {
        "case_id": case_id,
        "started_at": started_at,
        "model": model or "default",
        "trigger_exit_code": exit_code,
        "traceback": stderr_text,
        "backend_response": backend_response,
        "ground_truth": case_meta.get("ground_truth", {}),
        "score_1a": score,
    }


def write_report(date_dir: Path, case_id: str, result: dict[str, Any]) -> Path:
    """case 결과를 JSON 파일로 저장. 경로 반환."""
    date_dir.mkdir(parents=True, exist_ok=True)
    path = date_dir / f"{case_id}.json"
    with path.open("w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)
    return path


def write_comparison(date_dir: Path, results: list[dict[str, Any]]) -> Path:
    """모든 case 의 요약 표를 comparison.md 로 저장."""
    path = date_dir / "comparison.md"
    lines = [
        "# macro-logbot PoC 평가 결과",
        "",
        f"date: {date_dir.name}",
        "",
        "## 1-A 결정론 채점 (file:line substring + keyword 매칭)",
        "",
        "| case | file_match | line_match | keyword_hits | naive_score |",
        "|---|---|---|---|---|",
    ]
    for res in results:
        if "score_1a" not in res:
            lines.append(
                f"| {res.get('case_id', '?')} | — | — | — | (trigger failed) |"
            )
            continue
        s = res["score_1a"]
        lines.append(
            f"| {res['case_id']} | {s['file_match']} | {s['line_match']}"
            f" | {s['keyword_hits']} | {s['naive_score_0_to_1']} |"
        )
    lines.append("")
    lines.append(
        "> 1-B/2-A/2-B Claude judge 채점은 별도 — task-POC-001 (`docs/process/FOLLOWUP-TASKS.md`)"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate macro-logbot against PoC cases.")
    parser.add_argument(
        "--cases",
        required=True,
        help="콤마 구분 case id 목록 (예: E001,E002,E003)",
    )
    parser.add_argument("--model", default=None, help=f"LLM 모델 (기본: {DEFAULT_MODEL})")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("MACRO_LOGBOT_API_URL", DEFAULT_API_URL),
        help=f"backend URL (기본 env MACRO_LOGBOT_API_URL or {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MACRO_LOGBOT_API_KEY", ""),
        help="Bearer auth key (기본 env MACRO_LOGBOT_API_KEY)",
    )
    parser.add_argument(
        "--rate-limit-cooldown",
        type=int,
        default=DEFAULT_COOLDOWN_SEC,
        help=f"case 간 sleep 초 (기본 {DEFAULT_COOLDOWN_SEC})",
    )
    parser.add_argument(
        "--http-timeout",
        type=int,
        default=DEFAULT_HTTP_TIMEOUT,
        help=f"HTTP timeout (기본 {DEFAULT_HTTP_TIMEOUT})",
    )
    parser.add_argument(
        "--reports-dir",
        default=str(REPORTS_ROOT),
        help=f"리포트 root (기본 {REPORTS_ROOT})",
    )
    args = parser.parse_args(argv)

    if not args.api_key:
        print("error: --api-key 또는 MACRO_LOGBOT_API_KEY 필요", file=sys.stderr)
        return 2
    case_ids = [c.strip() for c in args.cases.split(",") if c.strip()]
    if not case_ids:
        print("error: --cases 가 비어 있음", file=sys.stderr)
        return 2

    date_dir = (
        Path(args.reports_dir) / _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    )
    model = args.model or DEFAULT_MODEL
    results: list[dict[str, Any]] = []
    for idx, case_id in enumerate(case_ids):
        print(f"=== {case_id} ({idx + 1}/{len(case_ids)}) ===")
        result = evaluate_case(case_id, args.api_url, args.api_key, model, args.http_timeout)
        report_path = write_report(date_dir, case_id, result)
        print(f"  -> {report_path}")
        results.append(result)
        # 다음 case 가 있으면 cooldown.
        if idx < len(case_ids) - 1 and args.rate_limit_cooldown > 0:
            time.sleep(args.rate_limit_cooldown)
    comp_path = write_comparison(date_dir, results)
    print(f"summary -> {comp_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
