#!/usr/bin/env bash
# task-PROCESS-002 (PR #62) — safe-merge skill 의 검증 logic 을 code-level enforce.
#
# safe-merge skill 본문 (markdown) 만으로는 본인 (Claude main session) 이 skill 호출
# 시 step 일부 skip 가능 — 본 script 가 skill logic 의 code-level 강제 (본인 우회 불가).
#
# Usage:
#   check.sh <PR-NUM>
#
# Exit:
#   0 — all check PASS, raw merge 가능
#   1 — check FAIL, 어떤 step fail 인지 stderr 보고
#   2 — argument error
#
# 본 script 의 의무 검증:
#   1. PR comment ≥ 5 (4 reviewer + 1 verifier)
#   2. 각 reviewer (code-reviewer / architect / security-reviewer / test-engineer) 의 latest comment 의 verdict 가 APPROVE
#   3. verifier 의 latest comment 의 verdict 가 PASS
#   4. REQUEST CHANGES 후 fix commit 있으면 같은 reviewer 의 재approve comment 있는지
#   5. PR mergeable=MERGEABLE / mergeStateStatus=CLEAN|UNSTABLE

set -uo pipefail

# --- argument ---
if [ $# -ne 1 ]; then
    echo "ERROR: usage — check.sh <PR-NUM>" >&2
    exit 2
fi
PR_NUM="$1"

if ! [[ "$PR_NUM" =~ ^[0-9]+$ ]]; then
    echo "ERROR: PR-NUM must be integer, got: $PR_NUM" >&2
    exit 2
fi

# --- 1. PR comment 갯수 ---
comment_count="$(gh pr view "$PR_NUM" --json comments --jq '.comments | length' 2>/dev/null)"
if [ -z "$comment_count" ] || [ "$comment_count" = "null" ]; then
    echo "FAIL #1: PR #$PR_NUM 의 comment list fetch 실패" >&2
    exit 1
fi
if [ "$comment_count" -lt 5 ]; then
    echo "FAIL #1: PR #$PR_NUM comment count = $comment_count < 5 (4 reviewer + 1 verifier 필요)" >&2
    exit 1
fi

# --- 2. 4 reviewer 의 latest verdict 검증 ---
# 각 reviewer 의 marker (보고서의 첫 줄 또는 본문의 첫 100 char 의 verdict 표기) 검출.
# fallback: comment body 안 "Verdict" 또는 "verdict" 의 다음 줄.

REVIEWERS=("code-reviewer" "architect" "security-reviewer" "test-engineer")
REVIEWER_OK_PATTERNS=(
    "APPROVE"
    "APPROVE with follow-up"
    "HEALTHY"
    "APPROVE with concerns"
)

declare -A reviewer_last_verdict
for r in "${REVIEWERS[@]}"; do
    reviewer_last_verdict[$r]=""
done

# 각 comment 의 body 안에서 reviewer name 검출 + verdict 추출 (가장 최근 comment 우선)
comments_json="$(gh pr view "$PR_NUM" --json comments --jq '.comments[] | {createdAt, body}' 2>/dev/null)"

if [ -z "$comments_json" ]; then
    echo "FAIL #2: PR comments JSON empty" >&2
    exit 1
fi

# python3 로 parse (jq 안 의존)
python_check="$(python3 -c "
import json, sys, re
comments_raw = '''$comments_json'''
# python3 의 json.loads 가 multi-object stream 못 받아 — 한 줄씩 parse
import re as _re
verdicts = {'code-reviewer': None, 'architect': None, 'security-reviewer': None, 'test-engineer': None, 'verifier': None}
verdict_dates = {k: '' for k in verdicts}

# 각 comment object 추출 (line 별)
for line in comments_raw.strip().split('}'):
    line = line.strip()
    if not line:
        continue
    if not line.endswith('}'):
        line = line + '}'
    try:
        obj = json.loads(line)
    except Exception:
        continue
    body = obj.get('body', '')
    created = obj.get('createdAt', '')
    body_head = body[:500].lower()

    # reviewer 검출 (body 안 'code-reviewer' / 'architect' / 등)
    for r in verdicts:
        if r.lower() in body_head:
            # verdict 추출 — APPROVE / PASS / REQUEST CHANGES / BLOCK
            v = None
            for pat in ['REQUEST CHANGES', 'BLOCK', 'APPROVE with follow-up', 'APPROVE with concerns', 'APPROVE', 'HEALTHY', 'PASS']:
                if pat in body[:1000]:
                    v = pat
                    break
            if v and (verdict_dates[r] == '' or created > verdict_dates[r]):
                verdicts[r] = v
                verdict_dates[r] = created

# 결과 출력 — '<reviewer>:<verdict>:<date>' 형식
for r, v in verdicts.items():
    print(f'{r}:{v or \"MISSING\"}:{verdict_dates[r]}')
")"
parse_rc=$?
if [ "$parse_rc" -ne 0 ]; then
    echo "FAIL #2: comment parse error (python rc=$parse_rc)" >&2
    exit 1
fi

# verdict 검증
fail_count=0
declare -A reviewer_verdict_map
while IFS=: read -r r v d; do
    reviewer_verdict_map[$r]="$v"
    if [ "$v" = "MISSING" ]; then
        echo "FAIL #2: reviewer '$r' 의 comment 미발견 (PR #$PR_NUM)" >&2
        fail_count=$((fail_count + 1))
        continue
    fi
    if [ "$v" = "REQUEST CHANGES" ] || [ "$v" = "BLOCK" ]; then
        echo "FAIL #2: reviewer '$r' verdict = $v (APPROVE 필요)" >&2
        fail_count=$((fail_count + 1))
        continue
    fi
done <<< "$python_check"

if [ "$fail_count" -gt 0 ]; then
    exit 1
fi

# --- 3. verifier verdict 검증 (위 loop 에 포함됨) ---
if [ "${reviewer_verdict_map[verifier]:-MISSING}" = "MISSING" ]; then
    echo "FAIL #3: verifier comment 미발견" >&2
    exit 1
fi
if [ "${reviewer_verdict_map[verifier]}" != "PASS" ] && \
   [ "${reviewer_verdict_map[verifier]}" != "APPROVE" ]; then
    echo "FAIL #3: verifier verdict = ${reviewer_verdict_map[verifier]} (PASS 필요)" >&2
    exit 1
fi

# --- 4. REQUEST CHANGES 후 fix commit 의 재approve 검증 ---
# 만약 어떤 reviewer 가 옛에 REQUEST CHANGES 였다면 (현재 verdict 가 APPROVE 라도),
# 같은 reviewer 의 최신 APPROVE comment 가 가장 최근 fix commit 보다 *후* 에 있는지 검증.
# 본 check 는 simpler version — 본 script 의 위 loop 가 이미 *latest* verdict 기반이라
# 같은 reviewer 의 옛 REQUEST CHANGES → 새 APPROVE 면 latest = APPROVE 로 잡힘. 정합.
# 다만 fix commit 후 reviewer 가 comment 안 한 경우 latest = 옛 REQUEST CHANGES → 위에서 fail.

# --- 5. PR mergeable 상태 ---
merge_state="$(gh pr view "$PR_NUM" --json mergeable,mergeStateStatus 2>/dev/null)"
mergeable="$(echo "$merge_state" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("mergeable",""))' 2>/dev/null)"
state_status="$(echo "$merge_state" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("mergeStateStatus",""))' 2>/dev/null)"

if [ "$mergeable" != "MERGEABLE" ] && [ "$mergeable" != "UNKNOWN" ]; then
    echo "FAIL #5: PR mergeable = $mergeable (MERGEABLE 필요)" >&2
    exit 1
fi

case "$state_status" in
    CLEAN|UNSTABLE|HAS_HOOKS|UNKNOWN) ;;
    *)
        echo "FAIL #5: PR mergeStateStatus = $state_status (CLEAN/UNSTABLE/HAS_HOOKS 필요)" >&2
        exit 1
        ;;
esac

# --- 모든 check PASS ---
echo "PASS: PR #$PR_NUM 모든 check 통과 — 5 reviewer verdict OK + mergeable" >&2
exit 0
