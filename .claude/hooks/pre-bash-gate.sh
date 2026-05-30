#!/usr/bin/env bash
# PreToolUse hook on Bash — raw 머지/푸시/review 차단 + caller identity 검증.
#
# stdin: Claude Code PreToolUse JSON (tool_input.command, agent_type).
# exit 0: allow / exit 2: block (stderr → main session).
#
# 차단:
#   - gh pr merge / gh api .../merges / gh pr review|comment / git push /
#     git update-ref refs/heads/main|master / git merge --ff-only origin/main
#   - post.sh (review 게시)  → sub-agent 전용 : main(agent_type 없음) 호출 차단
#   - run.sh  (safe-push)    → main 전용      : sub-agent(agent_type 있음) 호출 차단
#
# 모든 검사는 명령을 shell 연산자(&&/||/;/|/&/개행/()/{})로 segment 분해 후 segment 단위로 수행.
#
# agent_type 은 Claude Code 내부 미문서 stdin 필드 — 버전 변경 시 silent break 가능. 본 hook 는
# defense-in-depth(early block)이고 본질 보안 경계는 server-side(branch protection + Mergify).
# "agent_type 부재 = main" 추정은 모든 sub-agent 에 역할이 명시될 때만 성립 (run.sh 방향은 fail-open).

set -uo pipefail

_POST_SH_SUFFIX=".claude/skills/post-review/post.sh"
_RUN_SH_SUFFIX=".claude/skills/safe-push/run.sh"

input="$(cat 2>/dev/null || echo '{}')"

# tool_input.command 추출 — malformed JSON 은 fail-closed.
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
if [ $? -ne 0 ]; then
    cat >&2 <<EOF
[pre-bash-gate] hook 의 JSON parse 실패 — fail-closed (block).
입력 (head 200ch): $(printf '%s' "$input" | head -c 200)
parser error: $parsed
EOF
    exit 2
fi
command="$parsed"
[ -z "$command" ] && exit 0

# agent_type — main session 에서는 field 부재(empty), sub-agent 는 역할 문자열.
agent_type="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("agent_type", "") or "")
except Exception:
    print("")
' 2>/dev/null || echo "")"

# 명령을 shell 제어 연산자로 분해. 따옴표 내부 연산자/개행은 보존. segment 는 NUL 구분으로 출력
# (multi-line 따옴표 문자열이 segment 안에 있어도 안전). 순수 연산자 토큰(`&&(`·`;(`·`((` glued 포함)과
# brace 를 분리자로 처리 — glued subshell 우회 방어.
_seg_split() {
    printf '%s' "$1" | python3 -c '
import shlex, sys
s = sys.stdin.read()
# unquoted 개행 → ";" (separator). 따옴표 내부 개행은 보존 (multi-line 문자열 false-positive 방지).
res, quote, escaped = [], None, False
for c in s:
    if escaped:
        res.append(c); escaped = False; continue
    if quote == "\x27":
        res.append(c)
        if c == "\x27": quote = None
        continue
    if c == "\\":
        res.append(c); escaped = True; continue
    if quote == "\x22":
        res.append(c)
        if c == "\x22": quote = None
        continue
    if c in ("\x27", "\x22"):
        quote = c; res.append(c); continue
    res.append(";" if c == "\n" else c)
s = "".join(res)
PUNCT = set("();<>|&")
def is_sep(t):
    return t in ("{", "}") or (t != "" and all(c in PUNCT for c in t))
# redirect 연산자(`<`/`>`/`>&`/`<&` 등)는 separator 이지만, 바로 뒤 토큰은
# redirect TARGET(파일·fd) 이지 다음 명령의 argv0 가 아니다. target 을 drop 하지 않으면
# `>/tmp/x git push` 처럼 leading redirect 가 argv0 를 decapitate 해 차단을 우회한다.
def is_redir(t):
    return "<" in t or ">" in t
try:
    lex = shlex.shlex(s, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    toks = list(lex)
except Exception:
    sys.stdout.write(s); sys.exit(0)
out, cur, skip_next = [], [], False
for t in toks:
    if is_sep(t):
        if cur:
            out.append(" ".join(shlex.quote(x) for x in cur)); cur = []
        # redirect separator → 다음 non-sep 토큰(target) 1개 drop.
        skip_next = is_redir(t)
    else:
        if skip_next:
            skip_next = False  # redirect target — argv0 로 승격 금지.
            continue
        cur.append(t)
if cur:
    out.append(" ".join(shlex.quote(x) for x in cur))
sys.stdout.write("\x00".join(out))
'
}

# segment 의 caller identity 분류 — "RUNSH" / "POSTSH <role>" / "" / "UNPARSEABLE".
# env-prefix(VAR=val) drop 후 run.sh/post.sh 가 argv0 이거나 bash/sh/env/source/dot-source 의 인자인 경우만.
_classify_caller() {
    printf '%s' "$1" | python3 -c '
import shlex, sys, os, re
post_suf, run_suf = sys.argv[1], sys.argv[2]
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception:
    print("UNPARSEABLE"); sys.exit(0)
while toks and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0]):
    toks.pop(0)
if toks and toks[0] == "env":
    toks.pop(0)
    # skip env option flags before real argv0.
    # env -S / --split-string executes its payload as a command — hard-block.
    _OPTS_WITH_ARG = {"-u", "--unset", "-C", "--chdir"}
    while toks:
        if toks[0] == "--":
            toks.pop(0); break
        if toks[0].startswith("-"):
            opt = toks.pop(0)
            # env activates --split-string whenever S appears in a short-flag
            # cluster (-S, -vS, -uvS, -iS, ...) — not only when S is first.
            if opt == "--split-string" or opt.startswith("--split-string="):
                print("__ENV_S_BLOCKED__"); sys.exit(0)
            if opt.startswith("-") and not opt.startswith("--") \
                    and "S" in opt[1:].split("=", 1)[0]:
                print("__ENV_S_BLOCKED__"); sys.exit(0)
            if opt in _OPTS_WITH_ARG and toks:
                toks.pop(0)
        else:
            break
    while toks and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0]):
        toks.pop(0)
def matched(t, suf, base):
    n = os.path.normpath(t)
    return n.endswith(suf) or (os.path.basename(n) == base and suf in n)
for i, t in enumerate(toks):
    invoked = (i == 0) or (toks[i-1] in ("bash", "sh", "env", "source")) or (toks[i-1] == "." and i == 1)
    if not invoked:
        continue
    if matched(t, run_suf, "run.sh"):
        print("RUNSH"); sys.exit(0)
    if matched(t, post_suf, "post.sh"):
        print("POSTSH " + (toks[i+1] if i+1 < len(toks) else "")); sys.exit(0)
' "$_POST_SH_SUFFIX" "$_RUN_SH_SUFFIX" 2>/dev/null
}

# canonical form 검증 — alias / env-prefix / git -c·-C 우회 catch. argv0 기준 판단.
canonical_check() {
    local canonical
    canonical="$(printf '%s' "$1" | python3 -c '
import shlex, sys, re
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception:
    print("__UNPARSEABLE__")
    sys.exit(0)
while toks and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0]):
    toks.pop(0)
if toks and toks[0] == "env":
    toks.pop(0)
    # skip env option flags before real argv0.
    # env -S / --split-string executes its payload as a command — hard-block.
    _OPTS_WITH_ARG = {"-u", "--unset", "-C", "--chdir"}
    while toks:
        if toks[0] == "--":
            toks.pop(0); break
        if toks[0].startswith("-"):
            opt = toks.pop(0)
            # env activates --split-string whenever S appears in a short-flag
            # cluster (-S, -vS, -uvS, -iS, ...) — not only when S is first.
            if opt == "--split-string" or opt.startswith("--split-string="):
                print("__ENV_S_BLOCKED__"); sys.exit(0)
            if opt.startswith("-") and not opt.startswith("--") \
                    and "S" in opt[1:].split("=", 1)[0]:
                print("__ENV_S_BLOCKED__"); sys.exit(0)
            if opt in _OPTS_WITH_ARG and toks:
                toks.pop(0)
        else:
            break
    while toks and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0]):
        toks.pop(0)
if toks and toks[0].endswith("git"):
    i = 1
    while i < len(toks) and toks[i] in ("-c", "-C"):
        i += 2 if i + 1 < len(toks) else 1
    toks = [toks[0]] + toks[i:]
print(" ".join(toks[:8]))
' 2>/dev/null)"
    [ -z "$canonical" ] && return 0
    local argv0_base rest sub1 sub2
    argv0_base="${canonical%% *}"; argv0_base="${argv0_base##*/}"
    rest="${canonical#* }"; sub1="${rest%% *}"
    sub2="${rest#* }"; sub2="${sub2%% *}"
    case "$argv0_base" in
        __ENV_S_BLOCKED__) return 1 ;;
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

# segment 의 caller-identity 를 검사하고 위반 시 exit 2 하는 함수.
# 메인 segment 루프와 bash/sh/env -c 내부 segment 루프 양쪽에서 호출됨.
_caller_check() {
    local _seg="$1"
    local _kind="" _role="" _expected=""
    read -r _kind _role <<< "$(_classify_caller "$_seg")"
    case "$_kind" in
        __ENV_S_BLOCKED__)
            cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — env -S / --split-string payload 실행 차단.

명령: $command
검출 segment: $_seg

env -S / --split-string 은 payload 문자열을 명령으로 실행합니다 — 허용되지 않습니다.
EOF
            exit 2
            ;;
        UNPARSEABLE)
            cat >&2 <<EOF
[pre-bash-gate] caller 검증: shlex parse 불가 — fail-closed.
명령: $command
EOF
            exit 2
            ;;
        RUNSH)
            if [ -n "$agent_type" ]; then
                cat >&2 <<EOF
[pre-bash-gate] safe-push/run.sh 호출 차단 — sub-agent 의 push 금지 (push = main 전용).

agent_type: $agent_type
검출 segment: $_seg

run.sh (push) 는 main session 에서만 호출 가능. "review = sub-agent 전용 (post.sh)" 의 정반대 대칭.
EOF
                exit 2
            fi
            ;;
        POSTSH)
            if [ -z "$agent_type" ]; then
                cat >&2 <<EOF
[pre-bash-gate] post.sh 호출 차단 — main 의 직접 호출 금지 (self-impersonation 방어).

검출 segment: $_seg

post.sh 는 reviewer agent invocation 안에서만 호출 가능 (/post-review skill 경유).
EOF
                exit 2
            fi
            case "$_role" in
                architect)         _expected="oh-my-claudecode:architect" ;;
                code-reviewer)     _expected="oh-my-claudecode:code-reviewer" ;;
                security-reviewer) _expected="oh-my-claudecode:security-reviewer" ;;
                test-engineer)     _expected="oh-my-claudecode:test-engineer" ;;
                *)                 _expected="" ;;
            esac
            if [ -z "$_expected" ] || [ "$agent_type" != "$_expected" ]; then
                cat >&2 <<EOF
[pre-bash-gate] post.sh 호출 차단 — agent_type ↔ role mismatch.

agent_type: $agent_type
role 인자: ${_role:-(empty)}
expected: ${_expected:-(unknown role)}

각 reviewer agent 는 자신의 role 에 해당하는 post.sh 만 호출 가능.
EOF
                exit 2
            fi
            ;;
    esac
}

# 모든 검사를 segment 단위로. 하나라도 block 이면 전체 명령 차단.
mapfile -d '' -t _segments < <(_seg_split "$command")
for _seg in "${_segments[@]}"; do
    [ -z "$_seg" ] && continue

    # --- caller identity (post.sh = sub-agent 전용 / run.sh = main 전용) ---
    _caller_check "$_seg"

    # --- Layer 1: canonical form ---
    if ! canonical_check "$_seg"; then
        cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — raw 머지/푸시/review 시도 감지 (canonical form).

명령: $command
검출 segment: $_seg

직접 사용 금지:
  bash .claude/skills/safe-push/run.sh <BRANCH>   — feature branch push entry (main/master push 금지)
  .claude/skills/post-review/post.sh <role> <PR> <verdict> <findings>   — review/comment entry
EOF
        exit 2
    fi

    # --- Layer 2: argv0 별 grep 보조 catch (Layer 1 의 __UNPARSEABLE__ / obfuscated 대비) ---
    _argv0="$(printf '%s' "$_seg" | python3 -c '
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
                if printf '%s' "$_seg" | grep -qE "$pat"; then
                    cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — raw gh merge/review/comment 시도 감지.

명령: $command
검출 segment: $_seg

.claude/skills/post-review/post.sh <role> <PR> <verdict> <findings>   — review/comment entry
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
                if printf '%s' "$_seg" | grep -qE "$pat"; then
                    cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — raw git push/merge 시도 감지.

명령: $command
검출 segment: $_seg

bash .claude/skills/safe-push/run.sh <BRANCH>   — feature branch push entry (main/master push 금지)
EOF
                    exit 2
                fi
            done
            ;;
        bash|sh)
            # bash/sh -c '<inner>' 의 inner 를 재귀 검사 (inner 도 체인 가능 → _seg_split + canonical_check + caller_check).
            _inner="$(printf '%s' "$_seg" | python3 -c '
import shlex, sys
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception:
    print(""); sys.exit(0)
for i, t in enumerate(toks):
    if t == "-c" and i + 1 < len(toks):
        print(toks[i + 1]); sys.exit(0)
' 2>/dev/null || echo "")"
            if [ -n "$_inner" ]; then
                _inner_blocked=0
                mapfile -d '' -t _inner_segs < <(_seg_split "$_inner")
                for _inner_seg in "${_inner_segs[@]}"; do
                    [ -z "$_inner_seg" ] && continue
                    _caller_check "$_inner_seg"
                    canonical_check "$_inner_seg" || { _inner_blocked=1; break; }
                done
                if [ "$_inner_blocked" -eq 1 ] || printf '%s' "$_inner" | grep -qE 'gh[[:space:]]+pr[[:space:]]+(merge|review|comment)|git[[:space:]]+push'; then
                    cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — bash/sh -c 우회 시도 감지.

명령: $command
inner (-c 인자): $_inner
EOF
                    exit 2
                fi
            fi
            ;;
        eval)
            if printf '%s' "$_seg" | grep -qE 'gh[[:space:]]+pr[[:space:]]+merge|git[[:space:]]+push'; then
                cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — eval 우회 시도 감지.

명령: $command
검출 segment: $_seg
EOF
                exit 2
            fi
            ;;
        env)
            # env [VAR=v] bash/python3/perl -c/-e '<inner>' 의 inner 재귀 검사.
            _env_inner="$(printf '%s' "$_seg" | python3 -c '
import shlex, sys, re
try:
    toks = shlex.split(sys.stdin.read(), posix=True, comments=False)
except Exception:
    print(""); sys.exit(0)
while toks and (toks[0] == "env" or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0])):
    toks.pop(0)
for i, t in enumerate(toks):
    if t in ("-c", "-e") and i + 1 < len(toks):
        print(toks[i + 1]); sys.exit(0)
' 2>/dev/null || echo "")"
            if [ -n "$_env_inner" ]; then
                _env_blocked=0
                mapfile -d '' -t _env_segs < <(_seg_split "$_env_inner")
                for _env_seg in "${_env_segs[@]}"; do
                    [ -z "$_env_seg" ] && continue
                    _caller_check "$_env_seg"
                    canonical_check "$_env_seg" || { _env_blocked=1; break; }
                done
                if [ "$_env_blocked" -eq 1 ] || printf '%s' "$_env_inner" | grep -qE 'gh[[:space:]]+pr[[:space:]]+(merge|review|comment)|git[[:space:]]+push'; then
                    cat >&2 <<EOF
[pre-bash-gate] Bash 명령 차단 — env wrapper 우회 시도 감지.

명령: $command
inner (-c/-e 인자): $_env_inner
EOF
                    exit 2
                fi
            fi
            ;;
    esac
done

exit 0
