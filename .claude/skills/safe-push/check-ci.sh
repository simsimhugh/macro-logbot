#!/usr/bin/env bash
# task-AI-DLC-001 (PR 1) — safe-push skill 의 step 4 의 code-level enforce.
#
# 사용자 정책 (2026-05-22): reviewer cycle 시작 = GitHub Actions CI workflow
# 모두 pass 후. CI fail 시 reviewer cycle 진행 금지 — 본인 fix + 재 push + 재 wait.
#
# 본 script 가 safe-push skill 의 markdown 의 의지 layer 를 code-level 강제.
# (단일 logic file 이 markdown spec 의 의무 의 code-level enforce — 본 case
# 에서는 CI all-green wait + reviewer spawn timing 강제.)
#
# Usage:
#   check-ci.sh <PR-NUM> [TIMEOUT_SEC]
#
# Env (optional):
#   EXPECTED_HEAD_SHA      — 방금 push 한 HEAD SHA. rollup 의 headRefOid 와 일치할
#                            때까지 poll (issue #105 stale-green 가드). 미지정 시
#                            가드 비활성(stderr WARN 1줄) + pre-fix 즉시 판정.
#                            safe-push run.sh 가 자동 주입.
#   CHECK_CI_POLL_INTERVAL — poll 간격 초 (default 30). test 시 단축용.
#
# Exit:
#   0 — 모든 CI check conclusion=success. reviewer cycle 시작 가능.
#   1 — 1+ check conclusion=FAILURE/CANCELLED/TIMED_OUT. 본인 fix 필요.
#   2 — argument error 또는 timeout 초과.

set -uo pipefail

# --- argument ---
if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "ERROR: usage — check-ci.sh <PR-NUM> [TIMEOUT_SEC]" >&2
    exit 2
fi
PR_NUM="$1"
TIMEOUT="${2:-1800}"  # 30분 default — typical workflow run < 5분, 보수적 buffer.

if ! [[ "$PR_NUM" =~ ^[0-9]+$ ]]; then
    echo "ERROR: PR-NUM must be integer, got: $PR_NUM" >&2
    exit 2
fi
if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]]; then
    echo "ERROR: TIMEOUT_SEC must be integer, got: $TIMEOUT" >&2
    exit 2
fi

# --- poll loop ---
start=$(date +%s)
poll_interval="${CHECK_CI_POLL_INTERVAL:-30}"  # 30s — gh API rate limit 보호 + CI completion 의 typical timing. (test 시 env 로 단축)

# push 직후 stale-green 가드 (issue #105): rollup 이 방금 push 한 commit 의 것인지
# headRefOid 로 검증. EXPECTED_HEAD_SHA 미지정(standalone) 시 가드 비활성 — local HEAD
# fallback 은 remote PR head 와 어긋날 때 무한 STALE→timeout 을 유발하므로 제거.
# 빈 EXPECTED_SHA 시 python 비교(if expected and ...)가 우회되어 pre-fix 즉시 판정 복원.
EXPECTED_SHA="${EXPECTED_HEAD_SHA:-}"
if [ -z "$EXPECTED_SHA" ]; then
    echo "WARN: EXPECTED_HEAD_SHA 미지정 — push 직후 stale-green 가드 비활성(standalone 모드). run.sh 경유 시 자동 주입." >&2
fi

empty_count=0
EMPTY_MAX=10  # finding R: EMPTY rollup N회 연속 시 early exit (CI workflow 미등록 PR 추정)

while true; do
    elapsed=$(($(date +%s) - start))
    if [ "$elapsed" -gt "$TIMEOUT" ]; then
        echo "FAIL: CI poll timeout (${TIMEOUT}s) — PR #${PR_NUM} 의 CI run 미완 또는 stuck" >&2
        exit 2
    fi

    # statusCheckRollup fetch (headRefOid 동반 — issue #105 SHA 정합성 가드용)
    rollup_json="$(gh pr view "$PR_NUM" --json headRefOid,statusCheckRollup 2>/dev/null)"
    if [ -z "$rollup_json" ]; then
        echo "FAIL: gh pr view 실패 (PR #${PR_NUM} 존재 확인 필요)" >&2
        exit 1
    fi

    # state 분석 — python heredoc + JSON 의 stdin pipe 충돌 회피 (PR #62 의 v3 CRITICAL #1
    # 패턴: heredoc 이 python stdin 점유, pipe stdout 은 lost → json.load(sys.stdin) 가
    # python script source 자체 parse 시도 → fail). env var 으로 JSON pass.
    analysis="$(ROLLUP_JSON="$rollup_json" EXPECTED_SHA="$EXPECTED_SHA" python3 <<'PY'
import json, os, sys
try:
    data = json.loads(os.environ["ROLLUP_JSON"])
except Exception as exc:
    print(f"PARSE_ERROR:{exc}")
    sys.exit(3)

# issue #105: rollup 이 방금 push 한 commit 의 것인지 검증. push 직후 GitHub 의
# 복제 지연으로 직전 commit 의 green rollup 이 잠깐 돌아오면 false-green (elapsed=0s).
# headRefOid 가 EXPECTED_SHA 와 불일치 = 아직 새 commit 미반영 → STALE (계속 poll).
expected = os.environ.get("EXPECTED_SHA", "").strip()
head = (data.get("headRefOid") or "").strip()
if expected and head != expected:
    print(f"STALE:{head}")
    sys.exit(0)

rollup = data.get("statusCheckRollup", [])
if not rollup:
    print("EMPTY")
    sys.exit(0)

# 미완 status: IN_PROGRESS / QUEUED / PENDING 또는 conclusion=None.
pending = []
failed = []
passed = []
for c in rollup:
    name = c.get("name") or c.get("context") or "?"
    status = c.get("status")
    conclusion = c.get("conclusion")
    if status in ("IN_PROGRESS", "QUEUED", "PENDING") or (status == "COMPLETED" and conclusion is None):
        pending.append(name)
    elif conclusion in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"):
        failed.append(f"{name}={conclusion}")
    elif conclusion in ("SUCCESS", "NEUTRAL", "SKIPPED"):
        passed.append(name)
    else:
        # 예외 state — conservative: fail 로 분류 (silent allow 차단).
        failed.append(f"{name}=UNKNOWN({status}/{conclusion})")

if pending:
    print(f"PENDING:{len(pending)}:{','.join(pending[:5])}")
elif failed:
    print(f"FAILED:{len(failed)}:{','.join(failed)}")
else:
    print(f"PASSED:{len(passed)}:{','.join(passed)}")
PY
)"

    case "$analysis" in
        PARSE_ERROR:*)
            echo "FAIL: rollup JSON parse error — ${analysis#PARSE_ERROR:}" >&2
            exit 1
            ;;
        STALE:*)
            # issue #105: rollup 이 직전 commit 의 것 → green 판정 금지, 새 commit 반영까지 poll.
            head="${analysis#STALE:}"
            echo "WAIT: rollup 이 push 한 SHA 미반영 (rollup head=${head:0:12}, expected=${EXPECTED_SHA:0:12}; elapsed=${elapsed}s) — wait $poll_interval s..." >&2
            sleep "$poll_interval"
            ;;
        EMPTY)
            empty_count=$((empty_count + 1))
            if [ "$empty_count" -ge "$EMPTY_MAX" ]; then
                echo "FAIL: statusCheckRollup 가 ${EMPTY_MAX}회 연속 빈 배열 — CI workflow 미등록 PR 추정. 수동 확인 필요." >&2
                exit 1
            fi
            echo "WAIT: CI run 미시작 (elapsed=${elapsed}s, empty=${empty_count}/${EMPTY_MAX}) — wait $poll_interval s..." >&2
            sleep "$poll_interval"
            ;;
        PENDING:*)
            # test-eng LOW-2: empty_count 초기화 조건 명시 — PENDING / PASSED 상태 시 초기화
            # (CI 가 시작됐음 = workflow 등록 확인됨 → EMPTY_MAX early exit 불필요)
            empty_count=0
            n="${analysis#PENDING:}"
            n="${n%%:*}"
            echo "WAIT: $n CI checks pending (elapsed=${elapsed}s) — wait $poll_interval s..." >&2
            sleep "$poll_interval"
            ;;
        FAILED:*)
            failed_list="${analysis#FAILED:*:}"
            echo "FAIL: CI 1+ check failed — $failed_list" >&2
            exit 1
            ;;
        PASSED:*)
            empty_count=0  # test-eng LOW-2: PASSED 시도 초기화 (workflow 등록 확인됨)
            n="${analysis#PASSED:}"
            n="${n%%:*}"
            echo "PASS: 모든 $n CI checks success (elapsed=${elapsed}s) — reviewer cycle 시작 가능" >&2
            exit 0
            ;;
        *)
            echo "FAIL: 예외 analysis state — $analysis" >&2
            exit 1
            ;;
    esac
done
