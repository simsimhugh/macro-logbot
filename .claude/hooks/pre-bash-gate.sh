#!/usr/bin/env bash
# task-PROCESS-002 (2026-05-21) — PreToolUse hook on Bash.
#
# 목적: raw 머지/푸시 명령 시도 차단 (settings.deny 의 보조 safety net).
#       deny 가 catch 못한 우회 pattern 도 본 hook 가 catch.
#
# 동작:
#   - stdin: Claude Code PreToolUse hook JSON (tool_name + tool_input.command)
#   - exit 0: allow (다른 명령은 통과)
#   - exit 2: block — Claude main session 에 stderr 출력 (system reminder)
#
# 본 hook 가 차단하는 명령:
#   - gh pr merge ...           → /safe-merge skill 사용
#   - gh api .../merges ...     → /safe-merge skill 사용
#   - git push * main ...       → /safe-push skill 사용 (push 대상 = main branch)
#   - git update-ref refs/heads/main → 직접 ref 조작 우회
#   - git merge --ff-only origin/main → local fast-forward 우회
#
# 정책 본체: docs/process/03-개발-프로세스.md §<task-PROCESS-002>

set -uo pipefail

# stdin JSON 읽기 (없으면 빈 string)
input="$(cat 2>/dev/null || echo '{}')"

# tool_input.command 추출 — python3 의 json 모듈 사용 (jq 사내 mirror 미존재 가정).
command="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get("tool_input", {}).get("command", ""))
except Exception:
    pass
' 2>/dev/null)"

# command 가 없으면 통과 (다른 tool 호출, 본 hook 무관)
[ -z "$command" ] && exit 0

# 차단 pattern (BRE 의 grep -E)
BLOCK_PATTERNS=(
    '^[[:space:]]*gh[[:space:]]+pr[[:space:]]+merge'
    '^[[:space:]]*gh[[:space:]]+api[[:space:]].*(--method|-X)[[:space:]]+(PUT|POST)[[:space:]].*/merges?'
    '^[[:space:]]*git[[:space:]]+push[[:space:]].*\b(main|master)\b'
    '^[[:space:]]*git[[:space:]]+update-ref[[:space:]]+refs/heads/(main|master)'
    '^[[:space:]]*git[[:space:]]+merge[[:space:]].*--ff-only[[:space:]]+origin/(main|master)'
)

# /safe-merge skill 안에서 호출되는 명령은 본 hook 의 detect 어려움 (skill context 별 표기 없음).
# settings.deny 가 1차 차단, 본 hook 는 2차 (deny 우회 시 catch).
# Skill 안 logic 가 모든 검증 통과 후 실제 raw 명령 호출 — 그 시점에 본 hook 가 또 block 하면 모순.
# 회피: skill 가 raw 명령 호출 시 env var (SAFE_MERGE_BYPASS=1) 명시. hook 가 본 env 확인.
if [ "${SAFE_MERGE_BYPASS:-}" = "1" ]; then
    exit 0
fi

for pat in "${BLOCK_PATTERNS[@]}"; do
    if printf '%s' "$command" | grep -qE "$pat"; then
        cat >&2 <<EOF
[task-PROCESS-002] Bash 명령 차단 — raw 머지/푸시 시도 감지.

명령: $command
매칭 pattern: $pat

본 명령을 직접 사용 금지. 다음 skill 사용:
  /safe-merge <PR-NUM>         — 머지 entry (reviewer 5 + verifier APPROVE 검증 → raw merge)
  /safe-push <BRANCH>           — 푸시 entry (commit 검증 + 자동 review trigger)

skill 안 실제 raw 명령 호출 시 SAFE_MERGE_BYPASS=1 env 명시 (skill 의 일부, 본인 manual 호출 금지).

정책 본체: docs/process/03-개발-프로세스.md §<task-PROCESS-002 — process enforcement>
EOF
        exit 2
    fi
done

exit 0
