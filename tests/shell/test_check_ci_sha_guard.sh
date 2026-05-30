#!/usr/bin/env bash
# issue #105 — safe-push/check-ci.sh 의 push 직후 stale-green 회귀 방지 test.
#
# 시나리오: push 직후 GitHub 이 직전 commit 의 green rollup 을 잠깐 반환 →
# check-ci.sh 가 EXPECTED_HEAD_SHA 와 headRefOid 를 비교해 STALE 로 보고 계속 poll,
# 새 commit 의 rollup 이 등록되어 일치할 때만 PASS 해야 함.
#
# 사용:
#   bash tests/shell/test_check_ci_sha_guard.sh
#
# Exit:
#   0 — all tests PASS
#   1 — N tests FAIL

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CHECK_CI="$REPO_ROOT/.claude/skills/safe-push/check-ci.sh"

PASS=0
FAIL=0
FAIL_CASES=()

assert() {
    local desc="$1" cond="$2"
    if [ "$cond" = "ok" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        FAIL_CASES+=("$desc")
    fi
}

# --- gh mock 준비 ---
# 호출마다 FIXTURE_DIR/resp_<n>.json 을 순차 반환 (counter 파일로 추적, max 에서 clamp).
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/bin"
mkdir -p "$BIN"
cat > "$BIN/gh" <<'SHIM'
#!/usr/bin/env bash
d="$FIXTURE_DIR"
n="$(cat "$d/counter" 2>/dev/null || echo 1)"
[ "$n" -gt "$FIXTURE_MAX" ] && n="$FIXTURE_MAX"
cat "$d/resp_$n.json"
echo "$(( $(cat "$d/counter" 2>/dev/null || echo 1) + 1 ))" > "$d/counter"
SHIM
chmod +x "$BIN/gh"

run_check_ci() {
    # run_check_ci <fixture_subdir> <max> <expected_sha> <timeout>
    local fdir="$TMP/$1" max="$2" sha="$3" timeout="$4"
    rm -f "$fdir/counter"
    PATH="$BIN:$PATH" \
        FIXTURE_DIR="$fdir" FIXTURE_MAX="$max" \
        EXPECTED_HEAD_SHA="$sha" CHECK_CI_POLL_INTERVAL=0 \
        bash "$CHECK_CI" 999 "$timeout" 2>&1
}

run_check_ci_no_sha() {
    # run_check_ci_no_sha <fixture_subdir> <max> <timeout>
    # T5 전용: EXPECTED_HEAD_SHA 를 env 에서 빼고 호출(standalone 가드-off 경로).
    local fdir="$TMP/$1" max="$2" timeout="$3"
    rm -f "$fdir/counter"
    env -u EXPECTED_HEAD_SHA \
        PATH="$BIN:$PATH" \
        FIXTURE_DIR="$fdir" FIXTURE_MAX="$max" \
        CHECK_CI_POLL_INTERVAL=0 \
        bash "$CHECK_CI" 999 "$timeout" 2>&1
}

SUCCESS_ROLLUP='[{"name":"test","status":"COMPLETED","conclusion":"SUCCESS"}]'

# === Test 1: stale-green 가드 — 직전 SHA green 을 PASS 하지 않고 새 SHA 까지 poll ===
echo "=== Test 1: push 직후 stale-green → STALE 후 새 SHA 에서 PASS ==="
mkdir -p "$TMP/t1"
printf '{"headRefOid":"OLDSHA","statusCheckRollup":%s}\n' "$SUCCESS_ROLLUP" > "$TMP/t1/resp_1.json"
printf '{"headRefOid":"NEWSHA","statusCheckRollup":[]}\n'                   > "$TMP/t1/resp_2.json"
printf '{"headRefOid":"NEWSHA","statusCheckRollup":[{"name":"test","status":"IN_PROGRESS","conclusion":null}]}\n' > "$TMP/t1/resp_3.json"
printf '{"headRefOid":"NEWSHA","statusCheckRollup":%s}\n' "$SUCCESS_ROLLUP" > "$TMP/t1/resp_4.json"
out="$(run_check_ci t1 4 NEWSHA 60)"; rc=$?
[ "$rc" -eq 0 ] && assert "T1 최종 exit 0 (green)" ok || assert "T1 최종 exit 0 (green) — got rc=$rc" fail
echo "$out" | grep -q "WAIT: rollup 이 push 한 SHA 미반영" \
    && assert "T1 stale 단계에서 STALE wait 발생 (false-green 차단)" ok \
    || assert "T1 STALE wait 미발생 — stale rollup 을 그대로 신뢰했을 위험" fail
echo "$out" | grep -q "PASS: 모든 1 CI checks success" \
    && assert "T1 새 SHA green 에서만 PASS" ok \
    || assert "T1 PASS 메시지 누락" fail

# === Test 2: 새 SHA 가 끝내 안 나타나면 false-green 없이 timeout(exit 2) ===
echo "=== Test 2: headRefOid 가 계속 직전 SHA → timeout, green 아님 ==="
mkdir -p "$TMP/t2"
printf '{"headRefOid":"OLDSHA","statusCheckRollup":%s}\n' "$SUCCESS_ROLLUP" > "$TMP/t2/resp_1.json"
out="$(run_check_ci t2 1 NEWSHA 1)"; rc=$?
[ "$rc" -eq 2 ] && assert "T2 timeout exit 2 (green 으로 오판 안 함)" ok || assert "T2 expected exit 2, got $rc" fail

# === Test 3: SHA 일치 + all-success → 즉시 PASS (정상 흐름 회귀 없음) ===
echo "=== Test 3: headRefOid == EXPECTED 이고 all green → 즉시 PASS ==="
mkdir -p "$TMP/t3"
printf '{"headRefOid":"NEWSHA","statusCheckRollup":%s}\n' "$SUCCESS_ROLLUP" > "$TMP/t3/resp_1.json"
out="$(run_check_ci t3 1 NEWSHA 60)"; rc=$?
[ "$rc" -eq 0 ] && assert "T3 exit 0" ok || assert "T3 expected exit 0, got $rc" fail
echo "$out" | grep -q "WAIT: rollup 이 push 한 SHA 미반영" \
    && assert "T3 일치 시 STALE 오발생" fail \
    || assert "T3 일치 시 STALE 미발생 (정상)" ok

# === Test 4: SHA 일치 + FAILURE conclusion → exit 1 (FAILED 분기 회귀 방지) ===
echo "=== Test 4: headRefOid == EXPECTED 이고 lint FAILURE → exit 1 ==="
mkdir -p "$TMP/t4"
printf '{"headRefOid":"NEWSHA","statusCheckRollup":[{"name":"lint","status":"COMPLETED","conclusion":"FAILURE"}]}\n' > "$TMP/t4/resp_1.json"
out="$(run_check_ci t4 1 NEWSHA 60)"; rc=$?
[ "$rc" -eq 1 ] && assert "T4 FAILURE conclusion 시 exit 1" ok || assert "T4 expected exit 1, got $rc" fail
echo "$out" | grep -q "FAIL: CI 1+ check failed" \
    && assert "T4 FAILED 메시지 출력" ok \
    || assert "T4 FAILED 메시지 누락" fail

# === Test 5: EXPECTED_HEAD_SHA 미지정(standalone) → 가드 off + 즉시 PASS + WARN ===
echo "=== Test 5: EXPECTED_HEAD_SHA unset → 가드 비활성, all-green 즉시 PASS + WARN ==="
mkdir -p "$TMP/t5"
printf '{"headRefOid":"ANYSHA","statusCheckRollup":%s}\n' "$SUCCESS_ROLLUP" > "$TMP/t5/resp_1.json"
out="$(run_check_ci_no_sha t5 1 60)"; rc=$?
[ "$rc" -eq 0 ] && assert "T5 가드-off 즉시 exit 0" ok || assert "T5 expected exit 0, got $rc" fail
echo "$out" | grep -q "가드 비활성" \
    && assert "T5 가드 비활성 WARN 출력 (silent off 아님)" ok \
    || assert "T5 가드 비활성 WARN 누락" fail
echo "$out" | grep -q "WAIT: rollup 이 push 한 SHA 미반영" \
    && assert "T5 가드-off 인데 STALE 발생 (가드 미우회)" fail \
    || assert "T5 가드-off 로 STALE 미발생 (정상)" ok

# --- 결과 ---
echo ""
echo "=================================="
echo "PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
    printf '  - %s\n' "${FAIL_CASES[@]}"
    exit 1
fi
echo "all green"
exit 0
