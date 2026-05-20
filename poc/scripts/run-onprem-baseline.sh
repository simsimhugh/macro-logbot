#!/usr/bin/env bash
# 사내 LLM baseline 측정 (one-shot 스크립트, PR #54 신규)
#
# 사전 조건:
#   1. .env.bak 가 사내 LLM endpoint + key 로 설정됨 (docs/process/04-PoC-운영가이드.md §9.1)
#   2. docker compose up -d 로 backend 기동 + healthy
#   3. /tmp/poc-cases 가 backend container 에 read-only mount 됨
#
# Usage:
#   ./poc/scripts/run-onprem-baseline.sh           # N=3 (default)
#   ./poc/scripts/run-onprem-baseline.sh 5         # N=5
#   ./poc/scripts/run-onprem-baseline.sh 3 E001,E002,E003  # subset cases
#
# 출력:
#   /tmp/baseline-onprem-<YYYYMMDD>-<HHMMSS>/
#     ├── reports/N{1..N}/<YYYY-MM-DD>/E*.json   # raw output
#     ├── reports/N{1..N}/<YYYY-MM-DD>/comparison.md
#     ├── run.log                                  # 전체 실행 log
#     └── invariant-check.txt                      # §7.5 invariant 자동 검증 결과
#
# 사외 Claude 와 공유:
#   tar czf onprem-baseline.tar.gz -C /tmp/baseline-onprem-* reports/ invariant-check.txt
#   (secret redact 절차는 §9.4 참조)

set -euo pipefail

# --- 인자 + default ---
N="${1:-3}"
CASES="${2:-E001,E002,E003,E004,E005,E006,E007,E008,E009,E010}"

# --- repo root 자동 검출 ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# --- env load ---
if [ ! -f .env.bak ]; then
    echo "ERROR: .env.bak not found in $REPO_ROOT" >&2
    echo "       사내 LLM endpoint 설정 — docs/process/04-PoC-운영가이드.md §9.1" >&2
    exit 1
fi
set -a; . .env.bak; set +a

# --- backend healthy 확인 ---
if ! curl -sf --max-time 5 http://localhost:8000/health > /dev/null; then
    echo "ERROR: backend not healthy at http://localhost:8000/health" >&2
    echo "       docker compose ps + docker compose logs backend 확인" >&2
    exit 1
fi

# --- output dir ---
TS=$(date +%Y%m%d-%H%M%S)
ROOT="/tmp/baseline-onprem-$TS"
mkdir -p "$ROOT"
echo "=== onprem baseline N=$N, cases=$CASES ==="
echo "Output: $ROOT"
echo "Model: ${MACRO_LOGBOT_DEFAULT_MODEL:-default}"
echo "LLM endpoint: ${MACRO_LOGBOT_LLM_BASE_URL:-<not-set>}"
echo ""

# --- 측정 실행 ---
{
  for i in $(seq 1 "$N"); do
    echo "=== Run N$i start $(date +%H:%M:%S) ==="
    python3 poc/scripts/evaluate.py \
        --cases "$CASES" \
        --model "${MACRO_LOGBOT_DEFAULT_MODEL:?MACRO_LOGBOT_DEFAULT_MODEL not set}" \
        --api-url "http://localhost:8000" \
        --reports-dir "$ROOT/reports/N$i" \
        --judge none \
        --rate-limit-cooldown 0
    echo "=== Run N$i done $(date +%H:%M:%S) ==="
  done
} > "$ROOT/run.log" 2>&1

echo "=== Measurement done ==="
echo ""

# --- §7.5 invariant 자동 검증 ---
BACKEND_CONTAINER="${MACRO_LOGBOT_BACKEND_CONTAINER:-macro-logbot-backend}"
echo "=== §7.5 invariant check ==="
{
  echo "# §7.5 invariant 자동 검증 ($TS)"
  echo ""
  echo "## #1 Tool result success rate"
  docker exec "$BACKEND_CONTAINER" python3 -c "
import sqlite3, json
conn = sqlite3.connect('/app/.macro-logbot-sessions.db')
ok = err = 0
total = $((N * 10))
for (blob,) in conn.execute('SELECT messages_json FROM sessions ORDER BY updated_at DESC LIMIT ' + str(total)):
    for m in json.loads(blob):
        if m.get('role') == 'tool':
            c = m.get('content', '')[:100]
            if '\"error\"' in c: err += 1
            else: ok += 1
total_tool = ok + err
if total_tool > 0:
    rate = ok / total_tool * 100
    print(f'tool result: {ok}/{total_tool} = {rate:.1f}%')
    print(f'invariant #1 (>= 80%): {\"PASS\" if rate >= 80 else \"FAIL\"}')
else:
    print('no tool calls — backend tool 호출 자체가 없음 (model tool 미지원 의심)')
    print('invariant #1: UNKNOWN')
"
  echo ""
  echo "## infra_error flag case (PR #53 fail-fast guard)"
  grep -l '"infra_error"' "$ROOT"/reports/N*/*/E*.json 2>/dev/null | wc -l | awk '{print "case with infra_error flag:", $1, "/ " '"$((N * 10))"'}'
  echo ""
  echo "## §7.6.1 raw output 확인"
  echo "raw JSON: $(find "$ROOT/reports" -name 'E*.json' | wc -l) / $((N * 10)) 파일"
} | tee "$ROOT/invariant-check.txt"

echo ""
echo "=== DONE ==="
echo "Output: $ROOT"
echo ""
echo "다음 step (사외 Claude 와 공유):"
echo "  1. secret redact (docs/process/04-PoC-운영가이드.md §9.4 참조)"
echo "  2. tar czf onprem-baseline-$TS.tar.gz -C $ROOT reports/ invariant-check.txt"
echo "  3. 본 tar.gz 를 conversation 에 첨부"
