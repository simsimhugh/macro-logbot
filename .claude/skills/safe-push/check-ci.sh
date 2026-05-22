#!/usr/bin/env bash
# task-AI-DLC-001 (PR 1) — safe-push skill 의 step 4 의 code-level enforce.
#
# 사용자 정책 (2026-05-22): reviewer cycle 시작 = GitHub Actions CI workflow
# 모두 pass 후. CI fail 시 reviewer cycle 진행 금지 — 본인 fix + 재 push + 재 wait.
#
# 본 script 가 safe-push skill 의 markdown 의 의지 layer 를 code-level 강제.
# (.claude/skills/safe-merge/check.sh 의 deprecated 패턴과 동일 form — single
# logic file 이 markdown spec 강제. 본 case 에서는 reviewer spawn timing 강제.)
#
# Usage:
#   check-ci.sh <PR-NUM> [TIMEOUT_SEC]
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
poll_interval=30  # 30s — gh API rate limit 보호 + CI completion 의 typical timing.

while true; do
    elapsed=$(($(date +%s) - start))
    if [ "$elapsed" -gt "$TIMEOUT" ]; then
        echo "FAIL: CI poll timeout (${TIMEOUT}s) — PR #${PR_NUM} 의 CI run 미완 또는 stuck" >&2
        exit 2
    fi

    # statusCheckRollup fetch — gh stdout → python stdin pipe (RCE 회피, PR #62 v3 HIGH #1 pattern).
    rollup_json="$(gh pr view "$PR_NUM" --json statusCheckRollup 2>/dev/null)"
    if [ -z "$rollup_json" ]; then
        echo "FAIL: gh pr view 실패 (PR #${PR_NUM} 존재 확인 필요)" >&2
        exit 1
    fi

    # state 분석 — python 으로 정직 처리.
    analysis="$(printf '%s' "$rollup_json" | python3 - <<'PY'
import json, sys
try:
    data = json.load(sys.stdin)
except Exception as exc:
    print(f"PARSE_ERROR:{exc}")
    sys.exit(3)

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
        EMPTY)
            echo "WAIT: CI run 미시작 (elapsed=${elapsed}s) — wait $poll_interval s..." >&2
            sleep "$poll_interval"
            ;;
        PENDING:*)
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
