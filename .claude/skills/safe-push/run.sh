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

# 2.5. last review SHA 이후 commit 수 check (한 cycle = 한 commit 의무)
# 사용자 명시 (2026-05-23): review fix + lint/typecheck/format fix 도 한 commit 으로 통합 (분리 금지).
# last review SHA 이후 HEAD 까지 commit 2+ 이면 reject — main session 이 squash 후 재호출.
#
# finding D (architect MED-3): step 2.5 의 "any reviewer" 의 last SHA 사용 의도 명문화.
# 한 cycle 내 4 reviewer 는 모두 같은 HEAD commit 에 대해 review 하므로 any reviewer 의
# last SHA = cycle 의 last commit SHA = 모든 reviewer 공통 baseline. 의도 OK.
#
# orphan last SHA case (사용자 catch 2026-05-23): squash 의 결과 last review SHA 가 HEAD 의
# ancestor 아닌 orphan 인 경우 git rev-list LAST..HEAD 가 잘못된 commit 수 반환 → false reject.
# 본 case 는 의도된 force-push (squash base 변경) — force flag 명시 시 step 2.5 skip + warn.
_force_flag_present=0
for _arg in "$@"; do
    [ "$_arg" = "--force-with-lease" ] && _force_flag_present=1
done
if [ "$_force_flag_present" = "1" ]; then
    echo "[safe-push] step 2.5 skip — force-with-lease 명시 (의도된 base 변경)" >&2
else
    PR_NUM_EARLY="$(gh pr view "$BRANCH" --json number --jq '.number' 2>/dev/null || true)"
    if [ -n "$PR_NUM_EARLY" ]; then
        REPO_OWNER_NAME="$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null || true)"
        if [ -n "$REPO_OWNER_NAME" ]; then
            LAST_REVIEW_SHA="$(gh api "/repos/${REPO_OWNER_NAME}/pulls/${PR_NUM_EARLY}/reviews" --jq '[.[] | .commit_id] | last // empty' 2>/dev/null || true)"
            if [ -n "$LAST_REVIEW_SHA" ]; then
                NEW_COMMIT_COUNT="$(git rev-list "${LAST_REVIEW_SHA}..HEAD" --count 2>/dev/null || echo "")"
                # test-eng LOW-1: shallow clone / unknown SHA 시 git rev-list 가 empty 반환 가능
                # → 검증 불가 warn 로깅 후 skip (false reject 방지)
                if [ -z "$NEW_COMMIT_COUNT" ]; then
                    echo "[safe-push] step 2.5 warn: git rev-list ${LAST_REVIEW_SHA}..HEAD 가 empty (shallow clone 또는 SHA 미보유) — commit count 검증 skip" >&2
                elif [ "$NEW_COMMIT_COUNT" -gt 1 ]; then
                    LAST_SHORT="$(echo "$LAST_REVIEW_SHA" | cut -c1-7)"
                    cat >&2 <<EOF
[safe-push] step 2.5 fail — last review SHA (${LAST_SHORT}) 이후 ${NEW_COMMIT_COUNT} commit.

한 리뷰 사이클 = 한 commit 의무 위반. main session 의 자율 의무:
  git reset --soft ${LAST_SHORT} && git commit -F <message-file>
  또는 git commit --amend (단일 commit 인 경우)

squash 후 bash run.sh $BRANCH --force-with-lease 재호출.
EOF
                    exit 1
                fi
            fi
        fi
    fi
fi  # end: _force_flag_present != 1

# 3. push (subshell child 라 raw git push 차단 hook 우회)
# --force-with-lease 지원: --force-with-lease 인자 명시 (SAFE_PUSH_FORCE env var 미구현 — 인자 전용)
FORCE_FLAG=""
for _arg in "$@"; do
    [ "$_arg" = "--force-with-lease" ] && FORCE_FLAG="--force-with-lease"
done
echo "[safe-push] step 3: git push $FORCE_FLAG -u origin $BRANCH"
# shellcheck disable=SC2086
git push $FORCE_FLAG -u origin "$BRANCH"

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
    "$CHECK_CI" "$PR_NUM" || CI_EXIT=$?
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
