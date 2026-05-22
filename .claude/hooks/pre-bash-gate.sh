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
#   - gh pr merge ...           → Mergify auto-merge (PR 2 후) 또는 사용자 admin bypass (PR 2 전) 사용
#   - gh api .../merges ...     → Mergify auto-merge (PR 2 후) 또는 사용자 admin bypass (PR 2 전) 사용
#   - git push * main ...       → /safe-push skill 사용 (push 대상 = main branch)
#   - git update-ref refs/heads/main → 직접 ref 조작 우회
#   - git merge --ff-only origin/main → local fast-forward 우회
#
# 정책 본체: docs/process/03-개발-프로세스.md §<task-PROCESS-002>

set -uo pipefail

# stdin JSON 읽기 (없으면 빈 string)
input="$(cat 2>/dev/null || echo '{}')"

# tool_input.command 추출 — python3 의 json 모듈 사용. malformed JSON 시 fail-closed
# (PR #62 code-reviewer HIGH-2: 옛 except:pass 는 silent allow → 머지/푸시 명령 우회 가능).
parsed="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    cmd = d.get("tool_input", {}).get("command", "")
    print(cmd if isinstance(cmd, str) else "")
except Exception as exc:
    print(f"__JSON_PARSE_ERROR__:{exc}", file=sys.stderr)
    sys.exit(3)
' 2>&1)"
parse_rc=$?

if [ "$parse_rc" -ne 0 ]; then
    cat >&2 <<EOF
[task-PROCESS-002] hook 의 JSON parse 실패 — fail-closed (block).
입력 (head 200ch): $(printf '%s' "$input" | head -c 200)
parser error: $parsed
EOF
    exit 2
fi

command="$parsed"

# command 가 없으면 통과 (다른 tool 호출, 본 hook 무관)
[ -z "$command" ] && exit 0

# 차단 pattern (BRE 의 grep -E).
# PR #62 security v3 HIGH #2: regex-only 는 alias / variable / `git -c` 우회 가능.
# Fix: shlex tokenize → env prefix + `git -c k=v` / `-C path` strip → canonical form 검증
# (별 함수). 본 BLOCK_PATTERNS 은 1차 layer (정직한 명령 catch). canonical_check 가 2차 (우회 catch).
BLOCK_PATTERNS=(
    '\bgh[[:space:]]+pr[[:space:]]+merge'
    '\bgh[[:space:]]+api[[:space:]].*\bmerges?\b'
    '\bgit[[:space:]]+push[[:space:]].*\b(main|master)\b'
    '\bgit[[:space:]]+update-ref[[:space:]]+refs/heads/(main|master)'
    '\bgit[[:space:]]+merge[[:space:]].*--ff-only[[:space:]]+origin/(main|master)'
    '\beval[[:space:]]+.*\b(gh[[:space:]]+pr[[:space:]]+merge|git[[:space:]]+push[[:space:]].*\b(main|master)\b)'
)

# security v3 HIGH #2 fix: tokenize + canonical form 검증.
# 본 function 이 BLOCK_PATTERNS 의 보조 — alias / variable expansion 도 catch.
canonical_check() {
    local cmd="$1"
    # shlex tokenize + env prefix / git -c / -C 옵션 strip
    local canonical
    canonical="$(printf '%s' "$cmd" | python3 -c '
import shlex, sys, re
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception:
    print("__UNPARSEABLE__")
    sys.exit(0)
# env prefix (FOO=bar) drop
while toks and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0]):
    toks.pop(0)
# git -c key=val / -C path drop
if toks and toks[0].endswith("git"):
    i = 1
    while i < len(toks) and toks[i] in ("-c", "-C"):
        i += 2 if i + 1 < len(toks) else 1
    toks = [toks[0]] + toks[i:]
print(" ".join(toks[:8]))
' 2>/dev/null)"
    [ -z "$canonical" ] && return 0
    case "$canonical" in
        *"gh pr merge"*|*"/gh pr merge"*) return 1 ;;
        *"git push"*"main"*|*"git push"*"master"*|*"git push"*"+main"*|*"git push"*"+master"*) return 1 ;;
        *"git update-ref refs/heads/main"*|*"git update-ref refs/heads/master"*) return 1 ;;
        *"gh api"*"/merges"*|*"gh api"*"/merge "*) return 1 ;;
    esac
    return 0
}

# Mergify auto-merge (PR 2 후) 또는 사용자 admin bypass (PR 2 전) 안에서 호출되는 명령은 본 hook 의 detect 어려움 (skill context 별 표기 없음).
# settings.deny 가 1차 차단, 본 hook 는 2차 (deny 우회 시 catch).
# Skill 안 logic 가 모든 검증 통과 후 실제 raw 명령 호출 — 그 시점에 본 hook 가 또 block 하면 모순.
# 회피: skill 가 raw 명령 호출 시 env var (SAFE_MERGE_BYPASS=1) 명시. hook 가 본 env 확인.
if [ "${SAFE_MERGE_BYPASS:-}" = "1" ]; then
    exit 0
fi

# Layer 2: canonical form 검증 (tokenize 후 우회 시도 catch)
if ! canonical_check "$command"; then
    cat >&2 <<EOF
[task-PROCESS-002] Bash 명령 차단 — raw 머지/푸시 시도 감지 (canonical form, security v3 HIGH #2).

명령: $command
검출: tokenize 후 canonical form 의 머지/푸시 시도 (alias / variable / git -c / 우회 형식)

본 명령을 직접 사용 금지. 다음 skill 사용:
  (Mergify auto-merge — PR 2 후 server-side / 사용자 admin bypass — PR 2 전)
  /safe-push <BRANCH>           — 푸시 entry

skill 안 실제 raw 명령 호출 시 SAFE_MERGE_BYPASS=1 env 명시 (skill 의 일부).

정책 본체: docs/process/03-개발-프로세스.md §5.1
EOF
    exit 2
fi

# Layer 1: 정직한 명령 catch
for pat in "${BLOCK_PATTERNS[@]}"; do
    if printf '%s' "$command" | grep -qE "$pat"; then
        cat >&2 <<EOF
[task-PROCESS-002] Bash 명령 차단 — raw 머지/푸시 시도 감지.

명령: $command
매칭 pattern: $pat

본 명령을 직접 사용 금지. 다음 skill 사용:
  (Mergify auto-merge — PR 2 후 server-side / 사용자 admin bypass — PR 2 전) (reviewer 5 + verifier APPROVE 검증 → raw merge)
  /safe-push <BRANCH>           — 푸시 entry (commit 검증 + 자동 review trigger)

skill 안 실제 raw 명령 호출 시 SAFE_MERGE_BYPASS=1 env 명시 (skill 의 일부, 본인 manual 호출 금지).

정책 본체: docs/process/03-개발-프로세스.md §<task-PROCESS-002 — process enforcement>
EOF
        exit 2
    fi
done

exit 0
