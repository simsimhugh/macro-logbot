#!/usr/bin/env bash
# task-PROCESS-002 (PR #62) — enforcement layer self-test.
#
# 본 test 는 .claude/hooks/pre-bash-gate.sh + .githooks/pre-push 의 모든 차단/통과 case
# 자동 검증. 새 PR 마다 본 test 실행 가능 (e.g. pre-commit 또는 manual).
#
# 사용:
#   bash tests/shell/test_enforce_gate.sh
#
# Exit:
#   0 — all tests PASS
#   1 — N tests FAIL

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 1

HOOK="$REPO_ROOT/.claude/hooks/pre-bash-gate.sh"
PRE_PUSH="$REPO_ROOT/.githooks/pre-push"

PASS=0
FAIL=0
FAIL_CASES=()

assert_exit() {
    local desc="$1"
    local expected="$2"
    local actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        FAIL_CASES+=("$desc — expected exit $expected, got $actual")
    fi
}

# --- 1. pre-bash-gate.sh: block raw 명령 ---
echo "=== Test group 1: hook block raw 명령 ==="
for cmd in \
    "gh pr merge 60 --squash" \
    "gh pr merge 60" \
    "gh api repos/x/y/pulls/1/merges --method PUT" \
    "gh api --method PUT repos/x/y/pulls/1/merges" \
    "git push origin main" \
    "git push origin master" \
    "git push origin HEAD:main" \
    "git update-ref refs/heads/main abc" \
    "git update-ref refs/heads/master abc" \
    "git merge --ff-only origin/main" \
    "git push origin feature-branch"; do
    actual=$(printf '%s' "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$cmd\"}}" | "$HOOK" >/dev/null 2>&1; echo $?)
    assert_exit "block '$cmd'" 2 "$actual"
done
# 주: 현 정책은 feature branch 포함 모든 raw `git push` 차단 — push 는 safe-push/run.sh 전용.

# --- 2. pre-bash-gate.sh: block chain / env / eval ---
echo "=== Test group 2: hook block chain/env/eval ==="
for cmd in \
    "echo go && gh pr merge 60" \
    "true; gh pr merge 60" \
    "FOO=1 gh pr merge 60" \
    'eval "gh pr merge 60"' \
    "echo a; git push origin main" \
    "true && git push origin main"; do
    actual=$(printf '%s' "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$cmd\"}}" | "$HOOK" >/dev/null 2>&1; echo $?)
    assert_exit "block chain/env '$cmd'" 2 "$actual"
done

# --- 3. pre-bash-gate.sh: 통과 case ---
echo "=== Test group 3: hook 통과 case ==="
for cmd in \
    "git status" \
    "gh pr view 60" \
    "git fetch origin main" \
    "ls -la" \
    "echo hello"; do
    actual=$(printf '%s' "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$cmd\"}}" | "$HOOK" >/dev/null 2>&1; echo $?)
    assert_exit "pass '$cmd'" 0 "$actual"
done

# --- 4. pre-bash-gate.sh: SAFE_MERGE_BYPASS 제거 확인 (bypass 미존재) ---
# 옛 SAFE_MERGE_BYPASS escape hatch 는 현 hook 에서 제거됨 — env var 로 차단 우회 불가.
# 본 case 는 bypass 가 더 이상 통하지 않음(차단 유지)을 회귀 고정.
echo "=== Test group 4: SAFE_MERGE_BYPASS 미존재 (no bypass) ==="
actual=$(SAFE_MERGE_BYPASS=1 bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"gh pr merge 60\"}}' | $HOOK" >/dev/null 2>&1; echo $?)
assert_exit "SAFE_MERGE_BYPASS=1 도 차단 (bypass 제거됨)" 2 "$actual"

# --- 5. pre-bash-gate.sh: malformed JSON fail-closed ---
echo "=== Test group 5: malformed JSON fail-closed ==="
actual=$(echo "NOT_JSON" | "$HOOK" >/dev/null 2>&1; echo $?)
assert_exit "malformed JSON → exit 2" 2 "$actual"

actual=$(echo "" | "$HOOK" >/dev/null 2>&1; echo $?)
assert_exit "empty input → exit 2 (parse fail)" 2 "$actual"

# --- 6. pre-push: protected branch block ---
echo "=== Test group 6: pre-push protected branch ==="
actual=$(printf '%s\n' "refs/heads/main abc refs/heads/main def" | "$PRE_PUSH" >/dev/null 2>&1; echo $?)
assert_exit "pre-push main block" 1 "$actual"

actual=$(printf '%s\n' "refs/heads/master abc refs/heads/master def" | "$PRE_PUSH" >/dev/null 2>&1; echo $?)
assert_exit "pre-push master block" 1 "$actual"

# feature/x 는 protected 아니라 pre-push 의 self-test 단계까지 도달 → 그 self-test 가 본 test 를
# 다시 부르는 무한 재귀를 막기 위해 PREPUSH_SELFTEST_GUARD=1 로 nested self-test 를 skip.
actual=$(printf '%s\n' "refs/heads/feature/x abc refs/heads/feature/x def" | PREPUSH_SELFTEST_GUARD=1 "$PRE_PUSH" >/dev/null 2>&1; echo $?)
assert_exit "pre-push feature/x pass" 0 "$actual"

# --- 7. (deprecated) safe-merge/check.sh argument validation ---
# safe-merge skill 제거 (PR 1, 2026-05-22) — Mergify rule 가 server-side takeover.
# 옛 group 7 (check.sh argument validation) 제거.

# --- 8. security v3 HIGH #2: tokenize bypass case ---
# Note: alias / shell variable expansion 의 catch 는 shell semantic 의 본질 한계 —
# alias 는 shell session state, variable 는 runtime expansion → static analysis 불가.
# 본 두 case 는 GitHub branch protection rule (server-side) 가 backstop.
# 본 group 8 은 static analysis 가능한 git -c / -C 만 검증.
echo "=== Test group 8: tokenize bypass (git -c / -C) ==="
for cmd in \
    'git -c foo=bar push origin main' \
    'git -C /tmp push origin main' \
    'git -c http.proxy=x push origin master'; do
    safe=$(printf '%s' "$cmd" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    actual=$(printf '{"tool_input":{"command":%s}}' "$safe" | "$HOOK" >/dev/null 2>&1; echo $?)
    assert_exit "tokenize bypass '$cmd'" 2 "$actual"
done

# --- 9. (deprecated) safe-merge/check.sh injection-safe ---
# safe-merge skill 제거. CRITICAL #1 fix verification 의 의미 사라짐.
# 본 verify 는 safe-push/check-ci.sh (heredoc env var pattern) 의 일부로 별 test (FOLLOWUP).

# helper: command + agent_type → hook 호출 exit code.
# agent_type 은 Claude Code stdin 메타 필드 — main 은 빈값, sub-agent 는 역할 문자열.
_gate_rc() {
    local _cmd="$1" _agent="$2"
    python3 -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]},"agent_type":sys.argv[2]}))' "$_cmd" "$_agent" \
        | "$HOOK" >/dev/null 2>&1; echo $?
}

# --- 10. issue #95: safe-push 호출자 검증 (push = main 전용) ---
# "review = sub-agent 전용 (post.sh)" 의 정반대 대칭 — push 는 main 전용.
echo "=== Test group 10: safe-push caller verification (#95) ==="
# main (agent_type 빈값) → run.sh 호출 허용 (상대경로/--force-with-lease/argv0 형식)
for cmd in \
    "bash .claude/skills/safe-push/run.sh feature/x" \
    "bash .claude/skills/safe-push/run.sh feature/x --force-with-lease" \
    "./.claude/skills/safe-push/run.sh feature/x"; do
    actual=$(_gate_rc "$cmd" "")
    assert_exit "safe-push main allow '$cmd'" 0 "$actual"
done
# sub-agent (agent_type 있음) → run.sh 호출 차단 (bash/sh/env wrapper + argv0 우회 형식 포함)
for cmd in \
    "bash .claude/skills/safe-push/run.sh feature/x" \
    "sh .claude/skills/safe-push/run.sh feature/x" \
    "env bash .claude/skills/safe-push/run.sh feature/x" \
    "./.claude/skills/safe-push/run.sh feature/x"; do
    actual=$(_gate_rc "$cmd" "oh-my-claudecode:executor")
    assert_exit "safe-push sub-agent block '$cmd'" 2 "$actual"
done
# file-path-as-argument false-positive 방어 — run.sh 가 push 호출이 아니라 인자
for cmd in \
    "git add .claude/skills/safe-push/run.sh" \
    "cat .claude/skills/safe-push/run.sh"; do
    actual=$(_gate_rc "$cmd" "oh-my-claudecode:executor")
    assert_exit "safe-push file-path-as-arg pass '$cmd'" 0 "$actual"
done

# --- 11. issue #95: post.sh 상대경로 탐지 (옛 hole 회귀 방지) ---
# 옛 "/.claude/..." 절대경로 suffix 는 문서 권장 상대경로 형식을 탐지 못해 main 의 직접
# post.sh 호출이 통과하던 hole. 본 group 은 상대경로 탐지 동작을 회귀 고정.
echo "=== Test group 11: post.sh 상대경로 탐지 (#95) ==="
# main(빈 agent_type) 의 상대경로 post.sh 직접 호출 → 차단 (self-impersonation)
actual=$(_gate_rc "bash .claude/skills/post-review/post.sh architect 5 APPROVE x" "")
assert_exit "post.sh relative main block" 2 "$actual"
# 일치하는 reviewer agent 의 상대경로 호출 → 허용
actual=$(_gate_rc "bash .claude/skills/post-review/post.sh architect 5 APPROVE x" "oh-my-claudecode:architect")
assert_exit "post.sh relative matching reviewer allow" 0 "$actual"
# role mismatch (다른 reviewer 명의) → 차단
actual=$(_gate_rc "bash .claude/skills/post-review/post.sh security-reviewer 5 APPROVE x" "oh-my-claudecode:architect")
assert_exit "post.sh relative role mismatch block" 2 "$actual"

# --- 12. issue #95 group A: 체인 명령 분해 검사 (우회 차단 + false-positive 방어) ---
# argv0-only 검사가 놓치던 `&&`/`||`/`;`/`|`/subshell 뒤 merge·push 를 segment 분해로 차단.
# 동시에 따옴표 내부 연산자 / 인자로 쓰인 push 문자열은 false-positive 없이 통과해야 함.
echo "=== Test group 12: 체인 분해 검사 (#95 group A) ==="
# 실재 체인 뒤 merge/push → 차단
for cmd in \
    "cd /tmp && git push origin main" \
    "gh pr view 60 || gh pr merge 60" \
    "(cd x; git push origin main)" \
    "echo a | gh pr merge 60" \
    "true && FOO=1 gh pr merge 60" \
    "git status; git push origin feature"; do
    actual=$(_gate_rc "$cmd" "")
    assert_exit "chain block '$cmd'" 2 "$actual"
done
# 따옴표 내부 연산자 / push·merge 가 인자·문자열인 경우 → 통과 (false-positive 방어)
for cmd in \
    'git commit -m "fix: a; b && c"' \
    'echo "x && gh pr merge 60"' \
    'git log --oneline | grep push' \
    'grep -r "gh pr merge" docs/'; do
    actual=$(_gate_rc "$cmd" "")
    assert_exit "chain false-positive pass '$cmd'" 0 "$actual"
done

# --- 13. issue #95 검증 라운드 fix: 개행 / source / 경로정규화 ---
echo "=== Test group 13: 개행·source·normpath (#95 verify-round) ==="
# HIGH-1: 여러 줄(개행) 명령의 각 line 이 독립 segment 로 검사돼 raw push/merge 차단
assert_exit "newline push block"  2 "$(_gate_rc "$(printf 'echo hi\ngit push origin main')" "")"
assert_exit "newline 3-line push block" 2 "$(_gate_rc "$(printf 'git add -A\ngit commit -m x\ngit push origin feature/x')" "")"
assert_exit "newline merge block" 2 "$(_gate_rc "$(printf 'gh pr view 60\ngh pr merge 60')" "")"
# 개행 false-positive 방어 — 따옴표 내부 개행 문자열은 통과
assert_exit "newline-in-string pass" 0 "$(_gate_rc 'echo "line1
line2 ok"' "")"
# MED-3: source / dot-source 로 run.sh·post.sh 호출 탐지
assert_exit "source run.sh sub-agent block"   2 "$(_gate_rc "source .claude/skills/safe-push/run.sh feature/x" "oh-my-claudecode:executor")"
assert_exit "dot-source run.sh sub-agent block" 2 "$(_gate_rc ". .claude/skills/safe-push/run.sh feature/x" "oh-my-claudecode:executor")"
assert_exit "source post.sh main block"       2 "$(_gate_rc "source .claude/skills/post-review/post.sh architect 5 APPROVE x" "")"
# dot 가 source 가 아니라 path 인자인 경우(argv0 아님) → false-positive 없이 통과
assert_exit "dot-as-pathfix pass" 0 "$(_gate_rc "ls . .claude/skills/safe-push/run.sh" "oh-my-claudecode:executor")"
# LOW-1: 경로 정규화(//, /./, ..) 변형도 탐지
assert_exit "normpath // block"   2 "$(_gate_rc "bash .claude/skills/safe-push//run.sh feature/x" "oh-my-claudecode:executor")"
assert_exit "normpath /./ block"  2 "$(_gate_rc "bash .claude/skills/safe-push/./run.sh feature/x" "oh-my-claudecode:executor")"
assert_exit "normpath .. block"   2 "$(_gate_rc "bash .claude/skills/../skills/safe-push/run.sh feature/x" "oh-my-claudecode:executor")"

# --- 14. issue #95 reviewer fix: glued subshell / env·체인 dot-source / 체인 role / agent_type 경계 ---
echo "=== Test group 14: glued subshell·env-dot·체인 role·agent_type 경계 (#95) ==="
SP="bash .claude/skills/safe-push/run.sh feat"
PR="bash .claude/skills/post-review/post.sh"
# glued subshell/paren·brace 우회 — sub-agent run.sh 차단 (caller-identity 도 segment 분해)
for cmd in "($SP)" "true &&($SP)" ";($SP)" "(($SP))" "{ $SP; }"; do
    assert_exit "glued subshell run.sh block '$cmd'" 2 "$(_gate_rc "$cmd" "oh-my-claudecode:executor")"
done
# env-prefix / 체인 dot-source — sub-agent run.sh 차단
assert_exit "env-prefix dot-source block" 2 "$(_gate_rc "FOO=1 . .claude/skills/safe-push/run.sh feat" "oh-my-claudecode:executor")"
assert_exit "chain dot-source block"      2 "$(_gate_rc "cd /tmp && . .claude/skills/safe-push/run.sh feat" "oh-my-claudecode:executor")"
# 체인된 post.sh role mismatch (full path, first-match 가 아니라 전체 segment 검사) → 차단
assert_exit "chained post.sh role mismatch block" 2 "$(_gate_rc "$PR architect 5 APPROVE x && $PR security-reviewer 5 APPROVE y" "oh-my-claudecode:architect")"
# main 이 glued subshell 로 post.sh self-impersonation → 차단
assert_exit "glued post.sh main self-impersonation block" 2 "$(_gate_rc "($PR security-reviewer 104 PASS x)" "")"
# glued subshell 로 raw push → 차단
assert_exit "glued subshell raw push block" 2 "$(_gate_rc "true &&(git push origin main)" "")"
# agent_type 경계: 부재/null = main(run.sh 허용), whitespace = sub-agent(차단)
_gate_json() { printf '%s' "$1" | "$HOOK" >/dev/null 2>&1; echo $?; }
assert_exit "agent_type 부재 = main run.sh 허용" 0 "$(_gate_json '{"tool_input":{"command":"bash .claude/skills/safe-push/run.sh feat"}}')"
assert_exit "agent_type null = main run.sh 허용"  0 "$(_gate_json '{"tool_input":{"command":"bash .claude/skills/safe-push/run.sh feat"},"agent_type":null}')"
assert_exit "agent_type whitespace = sub-agent run.sh 차단" 2 "$(_gate_json '{"tool_input":{"command":"bash .claude/skills/safe-push/run.sh feat"},"agent_type":"  "}')"

# --- 결과 ---
echo ""
echo "=== Summary ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "FAILED cases:"
    for c in "${FAIL_CASES[@]}"; do
        echo "  - $c"
    done
    exit 1
fi

exit 0
