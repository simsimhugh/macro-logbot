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
cd "$REPO_ROOT"

HOOK="$REPO_ROOT/.claude/hooks/pre-bash-gate.sh"
PRE_PUSH="$REPO_ROOT/.githooks/pre-push"
CHECK_SH="$REPO_ROOT/.claude/skills/safe-merge/check.sh"

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
    "git merge --ff-only origin/main"; do
    actual=$(printf '%s' "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$cmd\"}}" | "$HOOK" >/dev/null 2>&1; echo $?)
    assert_exit "block '$cmd'" 2 "$actual"
done

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
    "git push origin feature-branch" \
    "ls -la" \
    "echo hello"; do
    actual=$(printf '%s' "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$cmd\"}}" | "$HOOK" >/dev/null 2>&1; echo $?)
    assert_exit "pass '$cmd'" 0 "$actual"
done

# --- 4. pre-bash-gate.sh: bypass env ---
echo "=== Test group 4: SAFE_MERGE_BYPASS ==="
actual=$(SAFE_MERGE_BYPASS=1 bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"gh pr merge 60\"}}' | $HOOK" >/dev/null 2>&1; echo $?)
assert_exit "SAFE_MERGE_BYPASS=1 통과" 0 "$actual"

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

actual=$(printf '%s\n' "refs/heads/feature/x abc refs/heads/feature/x def" | "$PRE_PUSH" >/dev/null 2>&1; echo $?)
assert_exit "pre-push feature/x pass" 0 "$actual"

# --- 7. check.sh argument validation ---
echo "=== Test group 7: check.sh argument validation ==="
actual=$("$CHECK_SH" >/dev/null 2>&1; echo $?)
assert_exit "check.sh no arg → exit 2" 2 "$actual"

actual=$("$CHECK_SH" not-a-number >/dev/null 2>&1; echo $?)
assert_exit "check.sh invalid arg → exit 2" 2 "$actual"

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
