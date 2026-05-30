#!/usr/bin/env bash
# safe-push entry script — branch 검증 + git push + CI all-green wait.
# step 5 (4 reviewer parallel spawn) 은 본 script 종료 후 main session 의 의무.

set -euo pipefail

# 0. arg parse
BRANCH="${1:-$(git branch --show-current)}"
[ -z "$BRANCH" ] && { echo "[safe-push] branch 명시 필수 (인자 또는 현재 branch)" >&2; exit 1; }

# 1. branch 확인 — main/master 차단
case "$BRANCH" in
    main|master)
        echo "[safe-push] main/master 직접 push 금지. PR 경로 사용 (gh pr create + Mergify auto-merge / 사용자 admin bypass)." >&2
        exit 1
        ;;
esac

# 2. local commit 검증 (soft warn)
echo "[safe-push] step 2: local commit 검증 (soft)"
git status -s
# 새 commit 의 message 형식 warn (Conventional Commits + Co-Authored-By)
NEW_COMMITS="$(git log @{u}..HEAD --format='%s' 2>/dev/null || true)"
if [ -n "$NEW_COMMITS" ]; then
    # finding U: trailing newline → empty iteration 방지 ([ -n "$msg" ] 조건 추가)
    while IFS= read -r msg && [ -n "$msg" ]; do
        if ! [[ "$msg" =~ ^(feat|fix|docs|chore|test|refactor)(\(.*\))?:.* ]]; then
            echo "[safe-push] warn: commit message 가 Conventional Commits 형식 아님: '$msg'" >&2
        fi
    done <<< "$NEW_COMMITS"
fi


# 3. push (subshell child 라 raw git push 차단 hook 우회)
# --force-with-lease 지원: --force-with-lease 인자 명시 (SAFE_PUSH_FORCE env var 미구현 — 인자 전용)
FORCE_FLAG=""
for _arg in "$@"; do
    [ "$_arg" = "--force-with-lease" ] && FORCE_FLAG="--force-with-lease"
done
echo "[safe-push] step 3: git push $FORCE_FLAG -u origin $BRANCH"
# shellcheck disable=SC2086
git push $FORCE_FLAG -u origin "$BRANCH"
# issue #105: 방금 push 한 HEAD SHA 를 check-ci.sh 로 전달 → rollup stale-green 가드.
PUSHED_SHA="$(git rev-parse HEAD)"

# 4. CI all-green wait
echo "[safe-push] step 4: CI all-green 대기"
PR_NUM="$(gh pr view "$BRANCH" --json number --jq '.number' 2>/dev/null || true)"
if [ -z "$PR_NUM" ]; then
    echo "[safe-push] PR 없음 — push 완료. PR 생성 후 step 4 수동 재실행." >&2
    exit 0
fi

CHECK_CI="$(dirname "$0")/check-ci.sh"
if [ -x "$CHECK_CI" ]; then
    # || CI_EXIT=$? — set -e 환경에서 non-zero exit 시 script 즉시 종료 방지.
    # check-ci.sh exit 1 (CI fail) / exit 2 (timeout) 을 case block 까지 전달.
    CI_EXIT=0
    EXPECTED_HEAD_SHA="$PUSHED_SHA" "$CHECK_CI" "$PR_NUM" || CI_EXIT=$?
else
    echo "[safe-push] warn: check-ci.sh 없음 또는 실행 권한 없음, CI 대기 skip" >&2
    CI_EXIT=0
fi

case "$CI_EXIT" in
    0)
        cat <<EOF
[safe-push] step 1-4 완료 — CI all-green.

다음 step (main session 의 자율 의무):
  4 reviewer parallel spawn (Agent tool):
    - oh-my-claudecode:architect
    - oh-my-claudecode:code-reviewer
    - oh-my-claudecode:security-reviewer
    - oh-my-claudecode:test-engineer
  각 agent 가 review 진행 후 post.sh 통해 게시.
EOF
        exit 0
        ;;
    1)
        cat >&2 <<EOF
[safe-push] step 4 fail — CI fail.

다음 step (main session 의 자율 의무):
  1. CI log 분석 (gh run view <run-id> --log-failed)
  2. fix
  3. new commit (Conventional Commits 형식)
  4. safe-push 재호출 (자기 cycle)
EOF
        exit 1
        ;;
    2)
        cat >&2 <<EOF
[safe-push] step 4 timeout — CI poll timeout (30분 default).

다음 step (main session 의 자율 의무):
  사용자에게 보고 + 자율 진행 중단.
  (CI stuck 또는 PR 의 workflow 미시작 가능성)
EOF
        exit 2
        ;;
    *)
        echo "[safe-push] warn: check-ci.sh 예외 exit code $CI_EXIT — 자율 진행 중단, 사용자 보고 필요" >&2
        exit "$CI_EXIT"
        ;;
esac
