#!/usr/bin/env bash
# 사내 LLM baseline 측정 (one-shot 스크립트, PR #54 + PR #57 robustness)
#
# 사전 조건:
#   1. .env.bak 가 사내 LLM endpoint + key 로 설정됨 (docs/process/04-PoC-운영가이드.md §9.1)
#   2. docker compose up -d 로 backend 기동 + healthy
#   3. /tmp/poc-cases 가 backend container 에 read-only mount 됨
#   4. host Python 3.8+ + pyyaml 설치 (PoC 스크립트 의존성, backend 의 3.14 와 별개)
#      예: python3 -m pip install --user pyyaml
#
# Usage:
#   ./poc/scripts/run-onprem-baseline.sh           # N=3 (default)
#   ./poc/scripts/run-onprem-baseline.sh 5         # N=5
#   ./poc/scripts/run-onprem-baseline.sh 3 E001,E002,E003  # subset cases
#
# Env overrides:
#   PYTHON_BIN=python3.11                          # 사내 host Python 3.14 미지원 시
#   MACRO_LOGBOT_BACKEND_CONTAINER=my-backend      # docker-compose service 이름 다를 때
#   RATE_LIMIT_COOLDOWN=2                          # 사내 LLM rate limit 대응 (sec)
#
# 출력:
#   /tmp/baseline-onprem-<YYYYMMDD>-<HHMMSS>/
#     ├── reports/N{1..N}/<YYYY-MM-DD>/E*.json   # raw output
#     ├── reports/N{1..N}/<YYYY-MM-DD>/comparison.md
#     ├── run-N{1..N}.log                         # run 별 실행 log (진행상황 + 디버깅)
#     ├── started_at.txt                          # 측정 시작 시각 (invariant 의 session 범위 제한)
#     └── invariant-check.txt                     # §7.5 invariant 자동 검증 결과
#
# 사외 Claude 와 공유:
#   tar czf onprem-baseline.tar.gz -C /tmp/baseline-onprem-* reports/ invariant-check.txt
#   (secret redact 절차는 §9.4 참조)

set -euo pipefail

# --- 인자 검증 + default ---
N="${1:-3}"
CASES="${2:-E001,E002,E003,E004,E005,E006,E007,E008,E009,E010}"

if ! [[ "$N" =~ ^[0-9]+$ ]] || [ "$N" -lt 1 ] || [ "$N" -gt 20 ]; then
    echo "ERROR: N must be integer in [1, 20], got: $N" >&2
    exit 1
fi
if ! [[ "$CASES" =~ ^E[0-9]{3}(,E[0-9]{3})*$ ]]; then
    echo "ERROR: CASES format invalid (expected: E001,E002,...), got: $CASES" >&2
    exit 1
fi

# --- env override ---
# PYTHON_BIN 은 아래 "host Python 자동 검출" 에서 처리 (.venv 우선).
RATE_LIMIT_COOLDOWN="${RATE_LIMIT_COOLDOWN:-0}"

# --- repo root 자동 검출 ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# --- env load (.env 단일화 — 사외/사내 동일) ---
# 이전: .env.bak 우선 → .env fallback (사외 dev 의 pytest 충돌 회피 가설 — 본 PoC 의
# pyproject.toml/conftest 에서 dotenv 자동 load 안 함 → 본 가설은 무근거. .env 단일화.
if [ -f .env ]; then
    ENV_FILE=.env
else
    echo "ERROR: .env not found in $REPO_ROOT" >&2
    echo "       사내 LLM endpoint 설정 — docs/process/04-PoC-운영가이드.md §9.1" >&2
    exit 1
fi
set -a; . "$ENV_FILE"; set +a

# --- host Python 자동 검출 (PYTHON_BIN env override → .venv → system) ---
if [ -n "${PYTHON_BIN:-}" ]; then
    PYTHON="$PYTHON"
elif [ -x "${REPO_ROOT}/.venv/bin/python3" ]; then
    PYTHON="${REPO_ROOT}/.venv/bin/python3"
else
    PYTHON="python3"
fi

if ! "$PYTHON" -c "import sys; assert sys.version_info >= (3, 8), sys.version" 2>/dev/null; then
    echo "ERROR: $PYTHON 미지원 (Python 3.8+ 필요). PYTHON_BIN=python3.11 같이 override." >&2
    exit 1
fi
if ! "$PYTHON" -c "import yaml" 2>/dev/null; then
    echo "ERROR: $PYTHON 에 PyYAML 미설치. $PYTHON -m pip install --user pyyaml" >&2
    exit 1
fi

# --- backend healthy 확인 ---
if ! curl -sf --max-time 5 http://localhost:8000/health > /dev/null; then
    echo "ERROR: backend not healthy at http://localhost:8000/health" >&2
    echo "       docker compose ps + docker compose logs backend 확인" >&2
    exit 1
fi

# --- docker 명령 자동 검출 (사내 사용자 docker group 미가입 시 sudo 필요) ---
# 사용자 사내 평가 (2026-05-21) 발견: docker compose 가 sudo 없이 권한 오류 → 본 스크립트
# 의 BACKEND_CONTAINER 가 빈 string → invariant check 의 docker exec "" 실패.
# Fix: DOCKER_CMD env 명시 override > docker (group 가입) > sudo -n docker (passwordless) 순.
if [ -n "${DOCKER_CMD:-}" ]; then
    :  # explicit override (e.g. DOCKER_CMD="sudo docker" 또는 DOCKER_CMD="podman")
elif docker info >/dev/null 2>&1; then
    DOCKER_CMD="docker"
elif sudo -n docker info >/dev/null 2>&1; then
    DOCKER_CMD="sudo docker"
else
    echo "ERROR: docker not accessible — tried 'docker' (group) + 'sudo -n docker' (passwordless)" >&2
    echo "       해결책: (1) 사용자를 docker group 에 추가 또는 (2) sudo passwordless 설정" >&2
    echo "       또는 DOCKER_CMD=\"sudo docker\" ./poc/scripts/run-onprem-baseline.sh" >&2
    exit 1
fi
echo "Docker command:    $DOCKER_CMD"

# --- backend container 자동 검출 ---
if [ -n "${MACRO_LOGBOT_BACKEND_CONTAINER:-}" ]; then
    BACKEND_CONTAINER="$MACRO_LOGBOT_BACKEND_CONTAINER"
else
    BACKEND_CONTAINER="$($DOCKER_CMD compose ps -q macro-logbot-backend 2>/dev/null | xargs -r $DOCKER_CMD inspect --format '{{.Name}}' 2>/dev/null | sed 's|^/||' | head -1)"
    BACKEND_CONTAINER="${BACKEND_CONTAINER:-macro-logbot-backend}"
fi

# --- output dir + 측정 시작 시각 (invariant SQL session 범위 제한용) ---
TS=$(date +%Y%m%d-%H%M%S)
ROOT="/tmp/baseline-onprem-$TS"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%S.000000+00:00)"
mkdir -p "$ROOT"
echo "$STARTED_AT" > "$ROOT/started_at.txt"

echo "=== onprem baseline N=$N, cases=$CASES ==="
echo "Output:           $ROOT"
echo "Model:            ${MACRO_LOGBOT_DEFAULT_MODEL:-default}"
echo "LLM endpoint:     ${MACRO_LOGBOT_LLM_BASE_URL:-<not-set>}"
echo "Backend container: $BACKEND_CONTAINER"
echo "Started at:       $STARTED_AT"
echo "Python:           $PYTHON ($("$PYTHON" -c 'import platform;print(platform.python_version())'))"
echo "Rate limit cooldown: ${RATE_LIMIT_COOLDOWN}s"
echo ""

# --- 측정 실행 (run 별 log 분리 + tee 로 진행상황 화면 출력) ---
for i in $(seq 1 "$N"); do
    LOG_FILE="$ROOT/run-N$i.log"
    {
        echo "=== Run N$i start $(date +%H:%M:%S) ==="
        "$PYTHON" poc/scripts/evaluate.py \
            --cases "$CASES" \
            --model "${MACRO_LOGBOT_DEFAULT_MODEL:?MACRO_LOGBOT_DEFAULT_MODEL not set}" \
            --api-url "http://localhost:8000" \
            --reports-dir "$ROOT/reports/N$i" \
            --judge none \
            --rate-limit-cooldown "$RATE_LIMIT_COOLDOWN"
        echo "=== Run N$i done $(date +%H:%M:%S) ==="
    } 2>&1 | tee "$LOG_FILE"
done

echo ""
echo "=== Measurement done — invariant check ==="
echo ""

# --- §7.5 invariant 자동 검증 (docker exec 실패 시에도 측정 결과 보존) ---
INVARIANT_FILE="$ROOT/invariant-check.txt"
{
    echo "# §7.5 invariant 자동 검증 ($TS)"
    echo "started_at: $STARTED_AT"
    echo "container:  $BACKEND_CONTAINER"
    echo ""
    echo "## #1 Tool result success rate (session 범위: started_at 이후만)"
    # docker exec 실패해도 측정 결과 abort 안 하도록 set +e 격리
    set +e
    $DOCKER_CMD exec "$BACKEND_CONTAINER" python3 -c "
import sqlite3, json
conn = sqlite3.connect('/app/.macro-logbot-sessions.db')
started_at = '$STARTED_AT'
ok = err = 0
# 측정 시작 시각 이후의 session 만 (이전 측정/디버깅 session 격리)
for (blob,) in conn.execute(
    'SELECT messages_json FROM sessions WHERE created_at >= ? ORDER BY created_at ASC',
    (started_at,),
):
    for m in json.loads(blob):
        if m.get('role') != 'tool':
            continue
        c = m.get('content', '')
        # JSON parse 후 error key 검사 (substring match 의 false positive 회피)
        is_err = False
        try:
            obj = json.loads(c) if c.startswith('{') else None
            if isinstance(obj, dict) and 'error' in obj:
                is_err = True
        except (ValueError, TypeError):
            pass
        if is_err:
            err += 1
        else:
            ok += 1
total_tool = ok + err
if total_tool > 0:
    rate = ok / total_tool * 100
    print(f'tool result: {ok}/{total_tool} = {rate:.1f}%')
    print(f'invariant #1 (>= 80%): {\"PASS\" if rate >= 80 else \"FAIL\"}')
else:
    print('no tool calls in session range — backend tool 호출 자체가 없음 (model tool 미지원 의심)')
    print('invariant #1: UNKNOWN')
" 2>&1
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
        echo "WARN: docker exec invariant check failed (rc=$rc) — 측정 결과는 보존됨"
    fi

    echo ""
    echo "## #2 traceback echo 구별 (§7.5.2 — file/line match 가 통과해도 tool 호출 0 인 case)"
    # session 별 messages 검사: tool_calls 가 0 또는 모두 error 인데 score_1a.file_match 또는
    # .line_match 가 True 인 case = traceback echo (LLM 이 stack 의 path/line 그대로 인용 + 진짜 code read 안 함).
    set +e
    echo_count=0
    for f in "$ROOT"/reports/N*/*/E*.json; do
        [ -f "$f" ] || continue
        # score_1a.file_match || line_match 통과 case 만 검사
        passed=$(python3 -c "
import json, sys
try:
    d = json.load(open('$f'))
    s = d.get('score_1a') or {}
    print('1' if (s.get('file_match') or s.get('line_match')) else '0')
except Exception:
    print('0')
" 2>/dev/null)
        [ "$passed" = "1" ] || continue
        # tool call success 여부 — score JSON 의 backend_response.analysis 가 tool_calls 의 result 까지
        # 포함하지 않으므로 session DB 접근 필요. 본 chunk 는 host file 만 보고 heuristic: analysis
        # 본문에 'matches' 또는 'content' 같은 tool result fingerprint 가 없으면 의심.
        no_tool_fp=$(python3 -c "
import json
try:
    d = json.load(open('$f'))
    br = d.get('backend_response') or {}
    txt = br.get('analysis','')
    has_fp = any(k in txt for k in ['matches','snake.py:', 'read_file'])
    print('1' if not has_fp else '0')
except Exception:
    print('0')
" 2>/dev/null)
        if [ "$no_tool_fp" = "1" ]; then
            echo_count=$((echo_count + 1))
            echo "  suspect traceback echo: $f"
        fi
    done
    set -e
    echo "suspect traceback echo cases: $echo_count"
    echo "invariant #2 (suspect == 0): $([ "$echo_count" -eq 0 ] && echo PASS || echo WARN)"

    echo ""
    echo "## #3 infra_error flag case (PR #53 fail-fast guard)"
    count=$(grep -l '"infra_error"' "$ROOT"/reports/N*/*/E*.json 2>/dev/null | wc -l)
    expected=$((N * 10))
    echo "case with infra_error flag: $count / $expected"
    echo "invariant #3 (infra_error == 0): $([ "$count" -eq 0 ] && echo PASS || echo FAIL)"

    echo ""
    echo "## #4 raw output 완전성 (§7.6.1)"
    actual=$(find "$ROOT/reports" -name 'E*.json' | wc -l)
    echo "raw JSON: $actual / $expected 파일"
    echo "invariant #4 (actual == expected): $([ "$actual" = "$expected" ] && echo PASS || echo FAIL)"

    echo ""
    echo "## INVARIANT SUMMARY (사외 Claude 가 본 line 우선 확인)"
    # 본 라인 = 측정 신뢰도 판정의 single line. 모든 invariant FAIL 0 이어야 본인이 score 신뢰.
    sum_fail=0
    [ "$count" -gt 0 ] && sum_fail=$((sum_fail + 1))
    [ "$actual" != "$expected" ] && sum_fail=$((sum_fail + 1))
    [ "$echo_count" -gt 0 ] && sum_fail=$((sum_fail + 1))
    if [ "$sum_fail" -eq 0 ]; then
        echo "INVARIANT: ALL PASS — 측정 결과 신뢰 가능, score 진행 OK"
    else
        echo "INVARIANT: $sum_fail FAIL/WARN — 측정 결과 신뢰 어려움, 별 분석 필요"
    fi
} | tee "$INVARIANT_FILE"

echo ""
echo "=== DONE ==="
echo "Output: $ROOT"
echo ""
echo "다음 step (사외 Claude 와 공유):"
echo "  1. secret redact (docs/process/04-PoC-운영가이드.md §9.4 참조)"
echo "  2. tar czf onprem-baseline-$TS.tar.gz -C $ROOT reports/ invariant-check.txt started_at.txt run-N*.log"
echo "  3. 본 tar.gz 를 conversation 에 첨부"
