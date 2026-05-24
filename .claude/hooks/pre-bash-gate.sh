#!/usr/bin/env bash
# PreToolUse hook on Bash.
#
# 목적: raw 머지/푸시/review 명령 시도 차단 (settings.deny 의 보조 safety net).
#       deny 가 catch 못한 우회 pattern 도 본 hook 가 catch.
#
# 동작:
#   - stdin: Claude Code PreToolUse hook JSON (tool_name + tool_input.command)
#   - exit 0: allow (다른 명령은 통과)
#   - exit 2: block — Claude main session 에 stderr 출력 (system reminder)
#
# 본 hook 가 차단하는 명령:
#   - gh pr merge ...                                       → 사용자 admin bypass / Mergify auto-merge 사용
#   - gh api .../merges ...                                 → 동일
#   - git push ...                                          → bash .claude/skills/safe-push/run.sh <BRANCH> 사용
#   - git update-ref refs/heads/main                        → 직접 ref 조작 우회
#   - git merge --ff-only origin/main                       → local fast-forward 우회
#   - gh pr review --approve|--request-changes|--comment    → /post-review skill 만 entry
#   - gh pr comment --body ...                              → /post-review skill 만 entry

set -uo pipefail

input="$(cat 2>/dev/null || echo '{}')"

# tool_input.command 추출 — python3 의 json 모듈 사용. malformed JSON 시 fail-closed.
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
[pre-bash-gate] hook 의 JSON parse 실패 — fail-closed (block).
입력 (head 200ch): $(printf '%s' "$input" | head -c 200)
parser error: $parsed
EOF
    exit 2
fi

command="$parsed"

# command 가 없으면 통과 (다른 tool 호출, 본 hook 무관)
[ -z "$command" ] && exit 0

# stdin JSON 에서 agent_type 추출 (없으면 empty — main session 에서는 field 자체 없음)
# NOTE: agent_type 은 Claude Code 의 내부 stdin 메타 필드. 버전 변경 시 silent break 가능.
# 본 hook 의 헤더 참조 — Claude Code stdin schema 의존성 위험 명시.
agent_type="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get("agent_type", "") or "")
except Exception:
    print("")
' 2>/dev/null || echo "")"

# post.sh 호출 detect — caller 정체성 검증 (self-impersonation 방어)
# argv0 또는 명시적 bash/sh 실행 인자로 post.sh 가 invoke 되는 경우만 체크.
# "git add .claude/skills/post-review/post.sh" 같은 file-path-as-argument 는 무시.
# finding C: shlex parse 불가 명령 → fail-closed (exit 2 block). 옛 except sys.exit(0) 는
#            fail-open 이었음 — obfuscated 명령이 post.sh detect 를 우회할 수 있는 hole.
# finding M: suffix match 강화 — "/.claude/skills/post-review/post.sh" 절대 경로 suffix 또는
#            basename == "post.sh" 의 양쪽 검사로 false-positive(다른 post.sh) 방어.
_POST_SH_CANONICAL_SUFFIX="/.claude/skills/post-review/post.sh"
_post_sh_invoked="$(printf '%s' "$command" | python3 -c '
import shlex, sys, os
suffix = sys.argv[1]
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception as exc:
    print(f"__UNPARSEABLE__:{exc}", file=sys.stderr)
    sys.exit(2)
def is_post_sh(t):
    return t.endswith(suffix) or (os.path.basename(t) == "post.sh" and suffix in t)
# post.sh 가 argv0 이거나 bash/sh 의 스크립트 인자인 경우만 invoked=true
for i, t in enumerate(toks):
    if is_post_sh(t):
        if i == 0:
            print("yes")  # argv0
        elif i > 0 and toks[i-1] in ("bash", "sh", "env"):
            print("yes")  # bash post.sh ... 형태
        # else: file path as argument (git add, cp 등) — 무시
        sys.exit(0)
' "$_POST_SH_CANONICAL_SUFFIX" 2>/dev/null)"
_post_sh_rc=$?
if [ "$_post_sh_rc" -eq 2 ]; then
    cat >&2 <<EOF
[pre-bash-gate] post.sh detect: shlex parse 불가 명령 — fail-closed (finding C).
명령: $command
EOF
    exit 2
fi
if [ "$_post_sh_invoked" = "yes" ]; then
    if [ -z "$agent_type" ]; then
        cat >&2 <<EOF
[pre-bash-gate] post.sh 호출 차단 — main session 의 직접 호출 금지 (self-impersonation 방어).

post.sh 는 reviewer agent invocation 안에서만 호출 가능.
main session (agent_type field 없음) 의 직접 호출은 self-impersonation 으로 차단.

post.sh 호출 방법: /post-review skill 을 통해 reviewer agent 가 호출.
EOF
        exit 2
    fi
    # role 추출 — post.sh 뒤 첫 positional token (shlex 기반 tokenize)
    # finding C: shlex parse 불가 → fail-closed (exit 2): role 확인 불가 = 차단
    role="$(printf '%s' "$command" | python3 -c '
import shlex, sys, os
suffix = sys.argv[1]
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception as exc:
    print(f"__UNPARSEABLE__:{exc}", file=sys.stderr)
    sys.exit(2)
def is_post_sh(t):
    return t.endswith(suffix) or os.path.basename(t) == "post.sh"
# post.sh 의 index 찾기
for i, t in enumerate(toks):
    if is_post_sh(t):
        nxt = toks[i+1] if i+1 < len(toks) else ""
        print(nxt)
        sys.exit(0)
' "$_POST_SH_CANONICAL_SUFFIX" 2>/dev/null)"
    _role_rc=$?
    if [ "$_role_rc" -eq 2 ]; then
        cat >&2 <<EOF
[pre-bash-gate] role 추출: shlex parse 불가 명령 — fail-closed (finding C).
명령: $command
EOF
        exit 2
    fi

    # empty role — fail-closed (finding B: empty role skip 에서 block 으로)
    if [ -z "$role" ]; then
        cat >&2 <<EOF
[pre-bash-gate] post.sh 호출 차단 — role 추출 실패 (empty). fail-closed (finding B).
명령: $command
EOF
        exit 2
    fi

    # exact-match table — F/M finding: glob *role* 의 too-permissive 방어
    case "$role" in
        architect)         expected_agent="oh-my-claudecode:architect" ;;
        code-reviewer)     expected_agent="oh-my-claudecode:code-reviewer" ;;
        security-reviewer) expected_agent="oh-my-claudecode:security-reviewer" ;;
        test-engineer)     expected_agent="oh-my-claudecode:test-engineer" ;;
        *)                 expected_agent="" ;;
    esac
    if [ -z "$expected_agent" ] || [ "$agent_type" != "$expected_agent" ]; then
        cat >&2 <<EOF
[pre-bash-gate] post.sh 호출 차단 — agent_type ↔ role mismatch.

agent_type: $agent_type
role 인자: $role
expected agent_type: ${expected_agent:-(unknown role)}

agent 가 다른 role 명의로 post.sh 호출 시도 감지.
각 reviewer agent 는 자신의 role 에 해당하는 post.sh 만 호출 가능.
EOF
        exit 2
    fi
fi

# tokenize + canonical form 검증 — alias / variable / git -c / -C 우회 시도 catch.
# Layer 1: canonical form 검증 (tokenize 후 우회 시도 catch, argv0 기준 정밀 판단)
canonical_check() {
    local cmd="$1"
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
    # argv0 기준 token 판단 — substring matching 폐기 (false-positive 방어)
    local argv0 sub1 sub2
    argv0="${canonical%% *}"
    argv0_base="${argv0##*/}"
    rest="${canonical#* }"
    sub1="${rest%% *}"
    sub2="${rest#* }"
    sub2="${sub2%% *}"
    case "$argv0_base" in
        gh)
            case "$sub1 $sub2" in
                "pr merge"|"api "*)
                    case "$canonical" in
                        *" pr merge"*|*"/merges"*|*"/merge"*) return 1 ;;
                    esac
                    ;;
                "pr review"|"pr comment") return 1 ;;
            esac
            ;;
        git)
            case "$sub1" in
                push) return 1 ;;
                update-ref)
                    case "$canonical" in
                        *"refs/heads/main"*|*"refs/heads/master"*) return 1 ;;
                    esac
                    ;;
            esac
            ;;
    esac
    return 0
}

if ! canonical_check "$command"; then
    cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — raw 머지/푸시/review 시도 감지 (canonical form).

명령: $command
검출: tokenize 후 canonical form 의 머지/푸시/review 시도 (alias / variable / git -c / 우회 형식)

본 명령을 직접 사용 금지. 다음 skill 사용:
  bash .claude/skills/safe-push/run.sh <BRANCH>   — feature branch push entry
  (main/master push 자체 금지 — PR 경로)
  .claude/skills/post-review/post.sh <role> <PR> <verdict> <findings>     — review/comment entry
EOF
    exit 2
fi

# Layer 2: 차단 pattern (grep -E) — argv0 기준 정밀화 (finding A).
# canonical_check (Layer 1) 가 shlex tokenize 기반으로 정확하게 판단.
# Layer 2 는 Layer 1 의 canonical_check 가 __UNPARSEABLE__ 반환한 경우(shlex 실패)에 대한
# 보조 catch — obfuscated / eval 우회 명령의 grep-level 보조 방어.
# argv0 추출 후 해당 argv0 에만 관련 패턴 적용 — 다른 명령의 args 안 substring false-positive 방지.
# (code-r LOW-3: "Layer 2 catch" promise ↔ 실제 logic 정합 — Layer 1 통과 후 보조 grep layer 역할)

# argv0 추출 (env prefix 제거 후 첫 token)
_argv0="$(printf '%s' "$command" | python3 -c '
import shlex, sys, re
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception:
    print("__UNPARSEABLE__")
    sys.exit(0)
while toks and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0]):
    toks.pop(0)
print(toks[0] if toks else "")
' 2>/dev/null || echo "__UNPARSEABLE__")"
_argv0_base="${_argv0##*/}"

case "$_argv0_base" in
    gh)
        BLOCK_PATTERNS=(
            '^[[:space:]]*([A-Za-z_][A-Za-z_0-9]*=[^[:space:]]*[[:space:]]+)*gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)'
            '^[[:space:]]*([A-Za-z_][A-Za-z_0-9]*=[^[:space:]]*[[:space:]]+)*gh[[:space:]]+api[[:space:]].*/(merges|merge)([[:space:]"/]|$)'
            '^[[:space:]]*([A-Za-z_][A-Za-z_0-9]*=[^[:space:]]*[[:space:]]+)*gh[[:space:]]+pr[[:space:]]+review([[:space:]]|$)'
            '^[[:space:]]*([A-Za-z_][A-Za-z_0-9]*=[^[:space:]]*[[:space:]]+)*gh[[:space:]]+pr[[:space:]]+comment([[:space:]]|$)'
        )
        for pat in "${BLOCK_PATTERNS[@]}"; do
            if printf '%s' "$command" | grep -qE "$pat"; then
                cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — raw gh merge/review/comment 시도 감지.

명령: $command
매칭 pattern: $pat

본 명령을 직접 사용 금지. 다음 skill 사용:
  .claude/skills/post-review/post.sh <role> <PR> <verdict> <findings>     — review/comment entry
EOF
                exit 2
            fi
        done
        ;;
    git)
        BLOCK_PATTERNS=(
            '^[[:space:]]*([A-Za-z_][A-Za-z_0-9]*=[^[:space:]]*[[:space:]]+)*(git|git[[:space:]]+-[cC][[:space:]]+[^[:space:]]+)[[:space:]]+push([[:space:]]|$)'
            '^[[:space:]]*([A-Za-z_][A-Za-z_0-9]*=[^[:space:]]*[[:space:]]+)*git[[:space:]]+push([[:space:]]|$)'
            '^[[:space:]]*([A-Za-z_][A-Za-z_0-9]*=[^[:space:]]*[[:space:]]+)*git[[:space:]]+update-ref[[:space:]]+refs/heads/(main|master)([[:space:]]|$)'
            '^[[:space:]]*([A-Za-z_][A-Za-z_0-9]*=[^[:space:]]*[[:space:]]+)*git[[:space:]]+merge[[:space:]].*--ff-only[[:space:]]+origin/(main|master)([[:space:]]|$)'
        )
        for pat in "${BLOCK_PATTERNS[@]}"; do
            if printf '%s' "$command" | grep -qE "$pat"; then
                cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — raw git push/merge 시도 감지.

명령: $command
매칭 pattern: $pat

본 명령을 직접 사용 금지. 다음 skill 사용:
  bash .claude/skills/safe-push/run.sh <BRANCH>   — feature branch push entry
  (main/master push 자체 금지 — PR 경로)
EOF
                exit 2
            fi
        done
        ;;
    bash|sh)
        # finding F: bash/sh -c 'gh pr merge ...' 우회 — -c 인자 내부 내용 검사
        _inner="$(printf '%s' "$command" | python3 -c '
import shlex, sys
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception:
    print("")
    sys.exit(0)
# -c <inner> 패턴 찾기
for i, t in enumerate(toks):
    if t == "-c" and i + 1 < len(toks):
        print(toks[i + 1])
        sys.exit(0)
' 2>/dev/null || echo "")"
        if [ -n "$_inner" ]; then
            # inner command 를 재귀적으로 canonical_check
            if ! canonical_check "$_inner"; then
                cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — bash/sh -c 우회 시도 감지 (finding F).

명령: $command
inner (-c 인자): $_inner
EOF
                exit 2
            fi
            # inner grep-level 보조 검사
            if printf '%s' "$_inner" | grep -qE 'gh[[:space:]]+pr[[:space:]]+(merge|review|comment)|git[[:space:]]+push'; then
                cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — bash/sh -c 내부 차단 패턴 감지 (finding F).

명령: $command
inner (-c 인자): $_inner
EOF
                exit 2
            fi
        fi
        ;;
    eval)
        # eval 우회 — 내부 명령 substring 검사
        if printf '%s' "$command" | grep -qE 'gh[[:space:]]+pr[[:space:]]+merge|git[[:space:]]+push'; then
            cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — eval 우회 시도 감지.

명령: $command
EOF
            exit 2
        fi
        ;;
    env)
        # WARN-env-wrapper-bypass: `env bash -c '...'` / `env python3 -c '...'` / `env perl -e '...'`
        # argv0=env のケース — env 자체는 허용이나 env 가 bash/python3/perl 를 wrapping 하면
        # bash/sh case 와 동일한 -c/-e inner 검사를 적용.
        _env_inner="$(printf '%s' "$command" | python3 -c '
import shlex, sys
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception:
    print("")
    sys.exit(0)
# env [VAR=val...] <cmd> [-c/-e <inner>] — skip env + VAR=val tokens, then find -c or -e
import re
while toks and (toks[0] == "env" or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0])):
    toks.pop(0)
# toks[0] is now the real command (bash/python3/perl/...)
for i, t in enumerate(toks):
    if t in ("-c", "-e") and i + 1 < len(toks):
        print(toks[i + 1])
        sys.exit(0)
' 2>/dev/null || echo "")"
        if [ -n "$_env_inner" ]; then
            if ! canonical_check "$_env_inner"; then
                cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — env wrapper 우회 시도 감지 (WARN-env-wrapper-bypass).

명령: $command
inner (-c/-e 인자): $_env_inner
EOF
                exit 2
            fi
            if printf '%s' "$_env_inner" | grep -qE 'gh[[:space:]]+pr[[:space:]]+(merge|review|comment)|git[[:space:]]+push'; then
                cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — env wrapper 내부 차단 패턴 감지 (WARN-env-wrapper-bypass).

명령: $command
inner (-c/-e 인자): $_env_inner
EOF
                exit 2
            fi
        fi
        ;;
    __UNPARSEABLE__)
        # shlex parse 불가 — fail-open (canonical_check 가 이미 처리)
        ;;
esac

exit 0
