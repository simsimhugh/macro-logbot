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

# --- 15. PR #104 architect MED: redirect decapitation ---
# leading/inline redirect 의 TARGET 이 다음 명령의 argv0 자리에 glue 돼 차단을 우회하던 hole.
# `_seg_split` 가 redirect 연산자(`>`/`<`/`>&`) 뒤 target 1개를 drop → argv0 복원 → 차단 유지.
echo "=== Test group 15: redirect decapitation (PR #104) ==="
# leading/inline redirect 뒤 raw push → 차단 (target drop 후 argv0=git)
for cmd in \
    ">/tmp/x git push origin main" \
    "1>/dev/null git push origin main" \
    "foo 2>&1 git push origin main" \
    "2>/dev/null git push origin feature" \
    ">out gh pr merge 60"; do
    actual=$(_gate_rc "$cmd" "")
    assert_exit "redirect-decap block '$cmd'" 2 "$actual"
done
# 정상 redirect false-positive 방어 → 통과 (push/merge 가 아니면 허용)
for cmd in \
    "echo a > b" \
    'git commit -m "msg" > /tmp/log' \
    "ls -la 2>/dev/null" \
    "cat file > out.txt"; do
    actual=$(_gate_rc "$cmd" "")
    assert_exit "redirect false-positive pass '$cmd'" 0 "$actual"
done
# redirect 가 붙어도 명령 자체가 push 면 여전히 차단 (redirect 가 면죄부 아님)
assert_exit "push with trailing redirect still block" 2 "$(_gate_rc "git push origin main >/dev/null" "")"

# --- 16. PR #104 code-reviewer HIGH+MED: literal env prefix bypass ---
# `env A=1 run.sh` / `env A=1 git push` 는 env-drop 미적용으로 rc=0 우회 가능했던 결함.
# env-drop 에 리터럴 env 토큰 추가 후 수정.
echo "=== Test group 16: literal env prefix bypass (PR #104) ==="
# HIGH: sub-agent 가 env A=1 run.sh 로 push gate 우회 시도 → 차단
assert_exit "env-prefix run.sh sub-agent block" 2 "$(_gate_rc "env A=1 .claude/skills/safe-push/run.sh feat" "oh-my-claudecode:executor")"
# HIGH: main 이 env A=1 post.sh 로 self-impersonation 우회 시도 → 차단
assert_exit "env-prefix post.sh main self-impersonate block" 2 "$(_gate_rc "env A=1 .claude/skills/post-review/post.sh architect 5 APPROVE x" "")"
# MED: env A=1 git push → canonical_check 가 env drop 후 git 인식 → 차단
assert_exit "env-prefix git push main block" 2 "$(_gate_rc "env A=1 git push origin main" "")"
# Regression: env 단독 명령 → 허용 (env 자체는 정상 명령)
assert_exit "env standalone pass" 0 "$(_gate_rc "env" "")"
# Regression: env FOO=1 git status → git push 아니므로 허용
assert_exit "env-prefix git status pass" 0 "$(_gate_rc "env FOO=1 git status" "")"
# Regression: bash .../run.sh (env 없음) main → 허용
assert_exit "bash run.sh main pass" 0 "$(_gate_rc "bash .claude/skills/safe-push/run.sh feat" "")"
# Regression: env A=1 bash .../run.sh main → run.sh는 main이 bash 경유 호출, agent_type 없음 → 허용
assert_exit "env-prefix bash run.sh main pass" 0 "$(_gate_rc "env A=1 bash .claude/skills/safe-push/run.sh feat" "")"

# --- 17. PR #104 test-engineer HIGH: bash -c caller-id bypass ---
# bash/sh/env -c '<inner>' 의 inner segment 도 _caller_check 를 통과해야 함.
# 수정 전: inner loop 가 while-read + 미종결 NUL 로 body skip → rc=0 (bypass).
# 수정 후: mapfile + _caller_check → inner segment 도 caller-identity 검사.
echo "=== Test group 17: bash-c caller-id bypass (PR #104 test-engineer HIGH) ==="
SP="bash .claude/skills/safe-push/run.sh feat"
PR_POST="bash .claude/skills/post-review/post.sh"
# sub-agent 가 bash/sh/env -c 로 run.sh 감싸면 차단 (expect 2)
assert_exit "bash -c run.sh sub-agent block"       2 "$(_gate_rc "bash -c \"$SP\""     "oh-my-claudecode:executor")"
assert_exit "sh -c run.sh sub-agent block"         2 "$(_gate_rc "sh -c \"$SP\""       "oh-my-claudecode:executor")"
assert_exit "env bash -c run.sh sub-agent block"   2 "$(_gate_rc "env bash -c \"$SP\"" "oh-my-claudecode:executor")"
# main 이 bash -c 로 post.sh self-impersonation → 차단 (expect 2)
assert_exit "bash -c post.sh main self-impersonate block" 2 \
    "$(_gate_rc "bash -c \"$PR_POST architect 5 APPROVE x\"" "")"
# sub-agent role-mismatch via bash -c → 차단 (expect 2)
assert_exit "bash -c post.sh role-mismatch block"  2 \
    "$(_gate_rc "bash -c \"$PR_POST security-reviewer 5 APPROVE x\"" "oh-my-claudecode:architect")"
# Regression: main 이 bash -c 로 run.sh → 허용 (expect 0)
assert_exit "bash -c run.sh main allow"            0 "$(_gate_rc "bash -c \"$SP\"" "")"
# Regression: bash -c echo hi → 허용 (expect 0)
assert_exit "bash -c echo hi allow"                0 "$(_gate_rc 'bash -c "echo hi"' "oh-my-claudecode:executor")"
# Regression: bash -c git status → 허용 (expect 0)
assert_exit "bash -c git status allow"             0 "$(_gate_rc 'bash -c "git status"' "")"

# --- 18. PR #104 test-engineer LOW: role-mismatch matrix 확장 ---
# architect 행만 있던 role-mismatch 검사를 모든 reviewer 행으로 확장.
echo "=== Test group 18: role-mismatch matrix 확장 (PR #104 test-engineer LOW) ==="
PR_POST="bash .claude/skills/post-review/post.sh"
# test-engineer 가 다른 role 명의 post.sh 호출 → 차단
assert_exit "test-engineer calls architect post.sh block"         2 \
    "$(_gate_rc "$PR_POST architect 5 APPROVE x"          "oh-my-claudecode:test-engineer")"
assert_exit "test-engineer calls code-reviewer post.sh block"     2 \
    "$(_gate_rc "$PR_POST code-reviewer 5 APPROVE x"      "oh-my-claudecode:test-engineer")"
assert_exit "test-engineer calls security-reviewer post.sh block" 2 \
    "$(_gate_rc "$PR_POST security-reviewer 5 APPROVE x"  "oh-my-claudecode:test-engineer")"
# code-reviewer 가 다른 role 명의 post.sh 호출 → 차단
assert_exit "code-reviewer calls architect post.sh block"         2 \
    "$(_gate_rc "$PR_POST architect 5 APPROVE x"          "oh-my-claudecode:code-reviewer")"
assert_exit "code-reviewer calls test-engineer post.sh block"     2 \
    "$(_gate_rc "$PR_POST test-engineer 5 APPROVE x"      "oh-my-claudecode:code-reviewer")"
# unknown role → 차단
assert_exit "unknown-role post.sh block"                          2 \
    "$(_gate_rc "$PR_POST architect 5 APPROVE x"          "oh-my-claudecode:unknown-role")"
# 각 reviewer 가 자신의 role 로 호출 → 허용
assert_exit "test-engineer own post.sh allow"                     0 \
    "$(_gate_rc "$PR_POST test-engineer 5 APPROVE x"      "oh-my-claudecode:test-engineer")"
assert_exit "code-reviewer own post.sh allow"                     0 \
    "$(_gate_rc "$PR_POST code-reviewer 5 APPROVE x"      "oh-my-claudecode:code-reviewer")"
assert_exit "security-reviewer own post.sh allow"                 0 \
    "$(_gate_rc "$PR_POST security-reviewer 5 APPROVE x"  "oh-my-claudecode:security-reviewer")"

# --- 19. PR #104 cycle-4: env option-flag bypass ---
# `env -i`, `env -u FOO`, `env --` 등 env 의 option flag 가 VAR=val drop 이후 남아
# real argv0 자리를 차지하던 hole. env-drop 후 option flag 도 소비하도록 수정.
echo "=== Test group 19: env option-flag bypass (PR #104 cycle-4) ==="
# 차단: env flag form 으로 git push 우회 시도 (main)
assert_exit "env -i git push block"            2 "$(_gate_rc "env -i git push origin main" "")"
assert_exit "env -u FOO git push block"        2 "$(_gate_rc "env -u FOO git push origin main" "")"
assert_exit "env -- git push block"            2 "$(_gate_rc "env -- git push origin main" "")"
# 차단: sub-agent 가 env -i run.sh 로 caller-id 우회 시도
assert_exit "env -i run.sh sub-agent block"    2 "$(_gate_rc "env -i .claude/skills/safe-push/run.sh feat" "oh-my-claudecode:executor")"
# 허용: main 이 env -i bash run.sh 호출 (run.sh 는 main 전용 → 허용)
assert_exit "env -i bash run.sh main allow"    0 "$(_gate_rc "env -i bash .claude/skills/safe-push/run.sh feat" "")"
# 허용: env -i git status (push 가 아님)
assert_exit "env -i git status allow"          0 "$(_gate_rc "env -i git status" "")"
# cycle-2 regression: env A=1 git push → 차단 유지
assert_exit "env A=1 git push still block"     2 "$(_gate_rc "env A=1 git push origin main" "")"
# cycle-2 regression: env FOO=1 git status → 허용 유지
assert_exit "env FOO=1 git status still allow" 0 "$(_gate_rc "env FOO=1 git status" "")"

# --- 20. PR #104 cycle-5: env -S / --split-string bypass ---
# env -S '<cmd>' / env --split-string='<cmd>' 는 payload 를 split 후 execvp — push/merge/review
# 우회 벡터. 3 가지 형태(glued / spaced / --split-string=) 모두 차단.
echo "=== Test group 20: env -S / --split-string bypass (PR #104 cycle-5) ==="
# 차단: glued form — env -S'git push origin main'
assert_exit "env -S glued git push block"                    2 "$(_gate_rc "env -S'git push origin main'" "")"
# 차단: spaced form — env -S 'git push origin main'
assert_exit "env -S spaced git push block"                   2 "$(_gate_rc "env -S 'git push origin main'" "")"
# 차단: long-opt form — env --split-string='git push origin main'
assert_exit "env --split-string= git push block"             2 "$(_gate_rc "env --split-string='git push origin main'" "")"
# 차단: gh pr merge payload
assert_exit "env -S gh pr merge block"                       2 "$(_gate_rc "env -S'gh pr merge 104'" "")"
# 차단: gh pr review payload
assert_exit "env -S gh pr review block"                      2 "$(_gate_rc "env -S'gh pr review 104 --approve'" "")"
# 차단: git update-ref payload
assert_exit "env -S git update-ref block"                    2 "$(_gate_rc "env -S'git update-ref refs/heads/main HEAD'" "")"
# 차단: sub-agent 가 env -S'bash run.sh' 로 safe-push 우회 시도
assert_exit "env -S run.sh sub-agent block"                  2 "$(_gate_rc "env -S'bash .claude/skills/safe-push/run.sh br'" "oh-my-claudecode:executor")"
# 차단: main 이 env -S'bash post.sh' 로 self-impersonate 시도
assert_exit "env -S post.sh main self-impersonate block"     2 "$(_gate_rc "env -S'bash .claude/skills/post-review/post.sh architect 5 APPROVE x'" "")"
# cycle-4 regression: env -i / -u / -- 여전히 차단
assert_exit "env -i git push still block (c4 reg)"           2 "$(_gate_rc "env -i git push origin main" "")"
assert_exit "env -u FOO git push still block (c4 reg)"       2 "$(_gate_rc "env -u FOO git push origin main" "")"
assert_exit "env -- git push still block (c4 reg)"           2 "$(_gate_rc "env -- git push origin main" "")"
# cycle-4 regression: env -i git status → 여전히 허용
assert_exit "env -i git status still allow (c4 reg)"         0 "$(_gate_rc "env -i git status" "")"

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
