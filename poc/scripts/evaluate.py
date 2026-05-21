"""Evaluate macro-logbot against each error case.

Spec ref: docs/process/04-PoC-운영가이드.md §5.3 + §6, docs/design/02-설계문서.md §10.1.

흐름 (per case):
    1. tempfile.mkdtemp() → workdir
    2. inject.inject(case, workdir) — error 주입
    3. trigger.trigger(workdir) → traceback 캡처
    4. POST <api>/agent/analyze with traceback + Bearer auth → response JSON
    5. response.analysis vs ground_truth → 결정론 채점 (1-A)
    6. (선택) --judge 지정 시 LLM judge 로 1-B/2-A/2-B 채점
    7. case 결과 dump → poc/reports/<YYYY-MM-DD>/<case>.json
    8. (선택) case 간 cooldown — Gemini 5 RPM 회피
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

from claude_judge import (  # noqa: E402
    _JUDGE_MODELS,
    judge_fix_direction,
    judge_root_cause,
    judge_tool_appropriateness,
)
from inject import inject  # noqa: E402
from trigger import trigger  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent.parent
REPORTS_ROOT = REPO_ROOT / "poc" / "reports"

DEFAULT_API_URL = "http://localhost:8000"
# repo root `.env.example` 의 MACRO_LOGBOT_DEFAULT_MODEL 과 정합 (PR #20 후 flash-lite default).
# Flash (50 RPD) → Flash-Lite (1000 RPD) 로 quota 안정성 ↑.
# Groq Llama 등 다른 provider 로 swap 시 --model 옵션 명시.
DEFAULT_MODEL = "gemini/gemini-2.5-flash-lite"
# spec §7.1 의 baseline 측정은 groq/llama-3.3-70b-versatile.
# evaluate.py 는 다양한 분석 모델 측정용 — baseline 측정 시 --model 명시 권장.
DEFAULT_COOLDOWN_SEC = 60  # Gemini free tier 5 RPM 보호.
# task-AGENT-024: reasoning_effort=high (gpt-oss 류) 호출은 분 단위 소요 가능 — 사용자 요구
# "latency 아무 상관없음, 10분 걸려도 OK". 120s 기존 default 는 high 측정 시 잘림. 900s (15분)
# 로 상향. 더 긴 호출이 필요하면 --http-timeout CLI override (line 372).
DEFAULT_HTTP_TIMEOUT = 900

# Tool-error sentinel — backend container 의 read_file/grep_codebase 가 fail 한 경우
# analysis text 에 echo 되는 키워드. PR #51 (N=10) 의 false positive 재발 방지용
# (docs/process/04-PoC-운영가이드.md §7.5.1 참조).
TOOL_ERROR_SENTINELS = (
    "Permission denied",
    "PermissionError",
    "not a file:",
    "[Errno 13]",
)


def call_backend(
    api_url: str,
    api_key: str,
    log_text: str,
    model: str | None,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
    session_id: str | None = None,
) -> dict[str, Any]:
    """POST <api_url>/agent/analyze. 실패 시 {'error': ...} 반환."""
    payload: dict[str, Any] = {
        "log_text": log_text,
        "temperature": 0,  # deterministic — spec §10.4 "seed=42 결정론적"
        "seed": 42,
    }
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
    except Exception as exc:  # noqa: BLE001 — 한 case 실패가 5 case loop 전체 죽이지 않도록
        return {"error": f"unexpected {type(exc).__name__}: {exc}"}


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


# judge 모델 화이트리스트는 claude_judge._JUDGE_MODELS 가 단일 source — argparse choices 에 활용.


def run_judge(
    ground_truth: dict[str, Any],
    analysis_text: str,
    tool_calls: list[dict[str, Any]],
    judge_model: str,
    judge_api_key: str | None = None,
) -> dict[str, Any]:
    """1-B/2-A/2-B LLM judge 채점. 결과 dict 반환.

    judge_api_key 명시 시 LiteLLM 호출에 직접 전달 — process env 미수정
    (sec WARN-2: setdefault 가 subprocess 환경 누출 회피).

    Returns:
        {
          "score_1b": {"score": float | None, "reasoning": str, ...},
          "score_2a": {...}, "score_2b": {...},
        }
    """
    root_cause_gt = str(ground_truth.get("root_cause") or "")
    fix_hint_gt = str(ground_truth.get("fix_hint") or "")
    expected_tools: list[str] = list(ground_truth.get("expected_tool_calls") or [])

    score_1b = judge_root_cause(root_cause_gt, analysis_text, judge_model, api_key=judge_api_key)
    score_2a = judge_tool_appropriateness(
        expected_tools, tool_calls, judge_model, api_key=judge_api_key
    )
    score_2b = judge_fix_direction(fix_hint_gt, analysis_text, judge_model, api_key=judge_api_key)

    return {"score_1b": score_1b, "score_2a": score_2a, "score_2b": score_2b}


def evaluate_case(
    case_id: str,
    api_url: str,
    api_key: str,
    model: str | None,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
    judge_model: str | None = None,
    judge_api_key: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """단일 case 실행 — inject → trigger → POST /agent/analyze → 채점.

    judge_model 지정 시 1-A 채점 후 LLM judge (1-B/2-A/2-B) 도 실행.
    session_id 지정 시 payload 에 포함 (spec §10.6 cumulative mode).
    """
    # workdir 위치 = docker-compose 의 backend volume mount (`/tmp/poc-cases:ro`) +
    # backend tool 의 `MACRO_LOGBOT_POC_WORKSPACE_ALLOWED` 와 정합. env override 지원.
    poc_cases_root = Path(os.environ.get("MACRO_LOGBOT_POC_CASES_ROOT", "/tmp/poc-cases"))
    poc_cases_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"{case_id}-", dir=str(poc_cases_root)))
    # tempfile.mkdtemp 의 default mode = 0o700 → backend container 의 uid (예: macrologbot
    # uid=10001) 가 host 의 evaluate.py 실행 uid (예: hugh uid=1000) 가 만든 폴더를 read 못함.
    # 본 PoC 의 workspace 는 read-only mount + tool allowlist 로 격리되어 있으므로 0o755 로
    # other-read 를 허용해도 안전 — backend 가 직접 호출하는 read_file/grep_codebase 가 정상
    # 동작하기 위함.
    workdir.chmod(0o755)
    started_at = _dt.datetime.now(_dt.UTC).isoformat()
    case_meta = inject(case_id, workdir)
    exit_code, stderr_text = trigger(workdir)
    # rc=0: traceback 캡쳐 성공. rc=1: clean exit, injection 실패. rc=2: timeout
    # (infinite loop = injection 성공, stderr partial 또는 timeout 메시지) — 측정 진행.
    # architect WARN-HIGH PR #30: E008 (spawn_food infinite loop) 같은 case 가 rc=2 인데
    # 이전엔 측정 실패로 처리됨 — backend 분석 못 받음. rc=1 만 fail.
    if exit_code == 1:
        return {
            "case_id": case_id,
            "started_at": started_at,
            "error": "trigger failed (clean exit — no injection effect captured)",
            "trigger_exit_code": exit_code,
            "trigger_stderr": stderr_text,
        }
    backend_response = call_backend(api_url, api_key, stderr_text, model, timeout, session_id=session_id)
    analysis_text = ""
    if "analysis" in backend_response:
        analysis_text = str(backend_response.get("analysis") or "")
    ground_truth = case_meta.get("ground_truth", {})
    score = score_1a(analysis_text, ground_truth)
    result: dict[str, Any] = {
        "case_id": case_id,
        "started_at": started_at,
        "model": model or "default",
        "trigger_exit_code": exit_code,
        "traceback": stderr_text,
        "backend_response": backend_response,
        "ground_truth": ground_truth,
        "score_1a": score,
    }
    # PR #53: tool-error sentinel 검출 — backend tool 호출이 fail 한 case 를 분류.
    # docs/process/04-PoC-운영가이드.md §7.5.1. score_1a 가 통과해도 (traceback echo
    # 만으로 file_match=True) 인프라 문제일 가능성을 보고서가 신뢰하지 못하도록.
    infra_hits = [s for s in TOOL_ERROR_SENTINELS if s in analysis_text]
    if infra_hits:
        result["infra_error"] = {
            "sentinels_hit": infra_hits,
            "reason": (
                "backend tool 호출 fail (workspace permission 등 인프라 문제). "
                "1-A heuristic 의 file:line 매칭은 traceback echo 가능성 — "
                "보고서 작성 시 본 case 의 'F2 해소' 증거 채택 금지."
            ),
        }
    if session_id:
        result["session_id"] = session_id
    if judge_model:
        tool_calls: list[dict[str, Any]] = []
        if isinstance(backend_response.get("tool_calls"), list):
            tool_calls = backend_response["tool_calls"]
        judge_scores = run_judge(
            ground_truth, analysis_text, tool_calls, judge_model, judge_api_key=judge_api_key
        )
        result.update(judge_scores)
        # spec §10.1: 4-channel 25%×4 총합 = 0.25·1A + 0.25·1B + 0.25·2A + 0.25·2B.
        # 측정 실패 (score=None) 항목은 0 으로 처리 — scored_axes < 4 면 명시적 표기.
        # (architect WARN-2: 측정 실패와 진짜 0 점 구분을 위해 scored_axes 동시 기록).
        s1b = judge_scores["score_1b"].get("score")
        s2a = judge_scores["score_2a"].get("score")
        s2b = judge_scores["score_2b"].get("score")
        scored_axes = 1 + sum(1 for s in (s1b, s2a, s2b) if s is not None)
        total = (
            0.25 * score["naive_score_0_to_1"]
            + 0.25 * float(s1b if s1b is not None else 0.0)
            + 0.25 * float(s2a if s2a is not None else 0.0)
            + 0.25 * float(s2b if s2b is not None else 0.0)
        )
        result["naive_score_total"] = round(total, 3)
        result["scored_axes"] = scored_axes  # 4 가 정상, < 4 면 일부 측정 실패.
    return result


def write_report(date_dir: Path, case_id: str, result: dict[str, Any]) -> Path:
    """case 결과를 JSON 파일로 저장. 경로 반환."""
    date_dir.mkdir(parents=True, exist_ok=True)
    path = date_dir / f"{case_id}.json"
    with path.open("w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)
    return path


def write_comparison(date_dir: Path, results: list[dict[str, Any]]) -> Path:
    """모든 case 의 요약 표를 comparison.md 로 저장.

    judge 채점 결과가 있으면 1-A/1-B/2-A/2-B/total 컬럼 확장.
    """
    path = date_dir / "comparison.md"
    has_judge = any("score_1b" in r for r in results)

    if has_judge:
        header = "| case | 1-A | 1-B | 2-A | 2-B | total |"
        separator = "|---|---|---|---|---|---|"
    else:
        header = "| case | file_match | line_match | keyword_hits | 1-A |"
        separator = "|---|---|---|---|---|"

    lines = [
        "# macro-logbot PoC 평가 결과",
        "",
        f"date: {date_dir.name}",
        "",
        "## 채점 결과 (spec §10.1 4단계 가중 합산)",
        "",
        header,
        separator,
    ]
    for res in results:
        cid = res.get("case_id", "?")
        if "score_1a" not in res:
            if has_judge:
                lines.append(f"| {cid} | — | — | — | — | (trigger failed) |")
            else:
                lines.append(f"| {cid} | — | — | — | (trigger failed) |")
            continue
        s = res["score_1a"]
        s1a = s["naive_score_0_to_1"]
        if has_judge:
            s1b = res.get("score_1b", {}).get("score", "—")
            s2a = res.get("score_2a", {}).get("score", "—")
            s2b = res.get("score_2b", {}).get("score", "—")
            total = res.get("naive_score_total", "—")
            lines.append(f"| {cid} | {s1a} | {s1b} | {s2a} | {s2b} | {total} |")
        else:
            lines.append(
                f"| {cid} | {s['file_match']} | {s['line_match']}"
                f" | {s['keyword_hits']} | {s1a} |"
            )
    lines.append("")
    if not has_judge:
        lines.append(
            "> 1-B/2-A/2-B LLM judge 채점: `--judge groq/llama-3.3-70b-versatile` 옵션 사용"
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
    parser.add_argument(
        "--judge",
        default="none",
        choices=("none", *_JUDGE_MODELS),
        help=(
            "LLM judge 모델 (1-B/2-A/2-B 채점). none 이면 1-A 만 (기본 none). "
            "주의: 현 2-A/2-B 는 1차 /agent/analyze 응답 기반 interim 채점 — "
            "spec §6.2 의 follow-up Q1/Q2/Q3 자동 호출 구현은 task-POC-001-x."
        ),
    )
    parser.add_argument(
        "--judge-api-key",
        default="",
        help=(
            "Judge LLM API key. 미지정 시 모델 provider 별 env 사용 — "
            "claude-* → ANTHROPIC_API_KEY, gemini/* → GEMINI_API_KEY, "
            "groq/* → GROQ_API_KEY."
        ),
    )
    parser.add_argument(
        "--continue-session",
        action="store_true",
        default=False,
        help=(
            "첫 case 응답의 session_id 를 받아 후속 case payload 에 echo. "
            "기본 off (매 case 신규 session)."
        ),
    )
    args = parser.parse_args(argv)

    if not args.api_key:
        print("error: --api-key 또는 MACRO_LOGBOT_API_KEY 필요", file=sys.stderr)
        return 2
    case_ids = [c.strip() for c in args.cases.split(",") if c.strip()]
    if not case_ids:
        print("error: --cases 가 비어 있음", file=sys.stderr)
        return 2

    judge_model: str | None = None
    judge_api_key: str | None = None
    if args.judge != "none":
        judge_model = args.judge
        # provider 별 default env 매핑 — LiteLLM 식별자 prefix 로 분기.
        # else "" 분기는 argparse choices 가 _JUDGE_MODELS 강제하므로 사실상
        # 도달 불가 (defensive — provider 추가 후 whitelist 갱신 누락 시 안전망).
        if judge_model.startswith("claude"):
            env_var = "ANTHROPIC_API_KEY"
        elif judge_model.startswith("gemini/"):
            env_var = "GEMINI_API_KEY"
        elif judge_model.startswith("groq/"):
            env_var = "GROQ_API_KEY"
        else:
            env_var = ""
        # API key 는 process env 수정 없이 LiteLLM 호출에 직접 전달 (sec WARN-2).
        # subprocess (trigger.py) 가 dict(os.environ) 으로 상속하는 누출 표면 회피.
        judge_api_key = args.judge_api_key or (os.environ.get(env_var, "") if env_var else "")
        if not judge_api_key:
            hint = f" 또는 {env_var}" if env_var else ""
            print(
                f"error: --judge {judge_model} 사용 시 --judge-api-key{hint} 필요",
                file=sys.stderr,
            )
            return 2

    date_dir = (
        Path(args.reports_dir) / _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    )
    model = args.model or DEFAULT_MODEL
    results: list[dict[str, Any]] = []
    continued_session_id: str | None = None
    for idx, case_id in enumerate(case_ids):
        print(f"=== {case_id} ({idx + 1}/{len(case_ids)}) ===")
        result = evaluate_case(
            case_id,
            args.api_url,
            args.api_key,
            model,
            args.http_timeout,
            judge_model=judge_model,
            judge_api_key=judge_api_key,
            session_id=continued_session_id,
        )
        # 첫 case 응답의 session_id 를 후속 case 에 echo (--continue-session 옵션).
        if args.continue_session and continued_session_id is None:
            resp_sid = result.get("backend_response", {}).get("session_id")
            if resp_sid:
                continued_session_id = str(resp_sid)
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
