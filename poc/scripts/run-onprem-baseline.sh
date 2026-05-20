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

# --- env load (.env.bak 우선, 없으면 .env — 사외 dev vs 사내 운영 양쪽 호환) ---
if [ -f .env.bak ]; then
    ENV_FILE=.env.bak
elif [ -f .env ]; then
    ENV_FILE=.env
else
    echo "ERROR: neither .env.bak nor .env found in $REPO_ROOT" >&2
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

# --- backend container 자동 검출 ---
if [ -n "${MACRO_LOGBOT_BACKEND_CONTAINER:-}" ]; then
    BACKEND_CONTAINER="$MACRO_LOGBOT_BACKEND_CONTAINER"
else
    BACKEND_CONTAINER="$(docker compose ps -q macro-logbot-backend 2>/dev/null | xargs -r docker inspect --format '{{.Name}}' 2>/dev/null | sed 's|^/||' | head -1)"
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
    docker exec "$BACKEND_CONTAINER" python3 -c "
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
    echo "## infra_error flag case (PR #53 fail-fast guard)"
    count=$(grep -l '"infra_error"' "$ROOT"/reports/N*/*/E*.json 2>/dev/null | wc -l)
    expected=$((N * 10))
    echo "case with infra_error flag: $count / $expected"

    echo ""
    echo "## §7.6.1 raw output 확인"
    actual=$(find "$ROOT/reports" -name 'E*.json' | wc -l)
    echo "raw JSON: $actual / $expected 파일"
} | tee "$INVARIANT_FILE"

echo ""
echo "=== DONE ==="
echo "Output: $ROOT"
echo ""
echo "다음 step (사외 Claude 와 공유):"
echo "  1. secret redact (docs/process/04-PoC-운영가이드.md §9.4 참조)"
echo "  2. tar czf onprem-baseline-$TS.tar.gz -C $ROOT reports/ invariant-check.txt started_at.txt run-N*.log"
echo "  3. 본 tar.gz 를 conversation 에 첨부"
