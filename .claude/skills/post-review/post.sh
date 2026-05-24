#!/usr/bin/env bash
# reviewer agent 의 PR comment/review entry script.
#
# 목적:
#   - 4 reviewer agent 의 review 게시 형식 표준화 (per-role template).
#   - agent 의 raw `gh pr comment`/`gh pr review` 직접 호출 금지 (hook + settings.deny).
#   - finding severity 로 verdict 자동 결정 — CRITICAL/HIGH at HIGH confidence 만 REQUEST_CHANGES, 나머지 APPROVE.
#     (옵션 C 2026-05-23: MED/WARN = informational — OMC code-reviewer prompt 정합)
#   - identity 검증: token user.login ↔ 명시 GH_USER 일치.
#   - scope 검증: <role> ↔ token username substring 일치 (e.g. architect ↔ *architect-bot).
#   - full PR scope: origin/main...HEAD 전체 diff review (incremental 아님).
#   - idempotent: last review SHA == HEAD 면 게시 skip.
#
# 사용법:
#   .claude/skills/post-review/post.sh <role> <PR-NUM> <verdict> <findings-json>
#
#   <role>:     architect | code-reviewer | security-reviewer | test-engineer
#   <PR-NUM>:   e.g. 65
#   <verdict>:  APPROVE | REQUEST_CHANGES
#               (script 가 findings 기반 expected verdict 산출 후 인자 verdict 와 일치 verify)
#               COMMENT 는 제거됨 (finding C: dead code — 모든 severity 가 APPROVE/REQUEST_CHANGES 도달)
#   <findings-json>:
#               JSON array — `[{"severity":"<S>","title":"<t>","detail":"<d>"},...]`
#               severity ∈ {CRITICAL, HIGH, MED, WARN, LOW, INFO, PASS}
#               (MEDIUM alias 제거 — MED 가 canonical. 미허용 값 → validate_finding_format 에서 exit 1)
#
# Exit codes:
#   0  — review 게시 성공 (또는 idempotent skip)
#   1  — arg parse 또는 env source 실패
#   2  — identity verify 실패 (token user.login ↔ GH_USER mismatch)
#   3  — scope verify 실패 (<role> ↔ GH_USER mismatch)
#   4  — verdict mismatch (인자 verdict ↔ findings 기반 expected verdict)
#   5  — gh API 호출 실패 또는 template render 실패

set -euo pipefail

# SCRIPT_DIR 은 post_helper.py 경로 기준 (finding N: python3 inline DRY)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$SCRIPT_DIR/post_helper.py"

#-----------------------------------------------------------------------
# 0. arg parse
#-----------------------------------------------------------------------
if [ "$#" -ne 4 ]; then
    cat >&2 <<'EOF'
[post-review] arg 4 개 필수.
사용법: post.sh <role> <PR-NUM> <verdict> <findings-json>
EOF
    exit 1
fi

ROLE="$1"
PR_NUM="$2"
VERDICT_ARG="$3"
FINDINGS_JSON="$4"

case "$ROLE" in
    architect|code-reviewer|security-reviewer|test-engineer) ;;
    *)
        echo "[post-review] unknown role: $ROLE (expected: architect|code-reviewer|security-reviewer|test-engineer)" >&2
        exit 1
        ;;
esac

case "$VERDICT_ARG" in
    APPROVE|REQUEST_CHANGES) ;;
    *)
        echo "[post-review] unknown verdict: $VERDICT_ARG (expected: APPROVE|REQUEST_CHANGES)" >&2
        exit 1
        ;;
esac

if ! [[ "$PR_NUM" =~ ^[0-9]+$ ]]; then
    echo "[post-review] PR-NUM must be integer: $PR_NUM" >&2
    exit 1
fi

# findings JSON validate — finding J: inline python3 → post_helper.py validate_findings (DRY 회복)
_findings_validate="$(python3 "$HELPER" validate_findings "$FINDINGS_JSON" 2>/dev/null || echo "PARSE_ERROR:python3 failed")"
case "$_findings_validate" in
    OK) ;;
    PARSE_ERROR:*)
        echo "[post-review] findings-json JSON parse 실패: ${_findings_validate#PARSE_ERROR:}" >&2
        exit 1
        ;;
    NOT_ARRAY:*)
        echo "[post-review] findings-json must be JSON array, got: ${_findings_validate#NOT_ARRAY:}" >&2
        exit 1
        ;;
    *)
        echo "[post-review] findings-json validate 실패" >&2
        exit 1
        ;;
esac

#-----------------------------------------------------------------------
# 1. env source (bot PAT)
#-----------------------------------------------------------------------
# finding I: Env dir override — prod mode 에서 MACRO_LOGBOT_BOT_ENV_DIR override 무시.
# POST_REVIEW_PROD=1 (또는 DRY_RUN 미설정 = prod 운영) 시 default 경로만 허용.
# override 는 테스트/개발 목적으로만 사용 (POST_REVIEW_DRY_RUN=1 필수).
if [ -n "${MACRO_LOGBOT_BOT_ENV_DIR:-}" ] && [ "${POST_REVIEW_DRY_RUN:-}" != "1" ]; then
    echo "[post-review] MACRO_LOGBOT_BOT_ENV_DIR override 는 POST_REVIEW_DRY_RUN=1 (테스트 모드) 에서만 허용 (finding I). prod 운영 시 default 경로 사용." >&2
    exit 1
fi
ENV_FILE="${MACRO_LOGBOT_BOT_ENV_DIR:-$HOME/.config/macro-logbot}/${ROLE}-bot.env"
if [ ! -r "$ENV_FILE" ]; then
    echo "[post-review] bot env file not readable: $ENV_FILE" >&2
    exit 1
fi

# finding J: mode + ownership 검증 후 source (arbitrary shell 실행 방어)
# finding H (Env source TOCTOU): realpath -e 로 절대 경로 고정 후 stat -L 명시.
#   stat -c (symlink follow) ↔ source 사이 race 방지.
# security WARN-4: symlink follow 차단 — lstat(-h) 으로 symlink 자체 check (여전히 유효).
if [ -L "$ENV_FILE" ]; then
    echo "[post-review] env file 는 symlink 불가 (보안): $ENV_FILE" >&2
    exit 1
fi
# realpath -e: 절대 경로 lock — check ↔ source 사이 path 변조 방지 (finding H)
RESOLVED_ENV_FILE="$(realpath -e "$ENV_FILE" 2>/dev/null || echo "")"
if [ -z "$RESOLVED_ENV_FILE" ]; then
    echo "[post-review] env file realpath 실패 (존재하지 않거나 권한 없음): $ENV_FILE" >&2
    exit 1
fi
# stat -L: resolved path 의 실제 파일 stat (symlink 재확인 포함)
_env_stat="$(stat -L -c '%a %u' "$RESOLVED_ENV_FILE" 2>/dev/null || echo "")"
_env_mode="${_env_stat%% *}"
_env_uid="${_env_stat##* }"
_cur_uid="$(id -u)"
if [ -z "$_env_stat" ]; then
    echo "[post-review] env file stat 실패: $ENV_FILE" >&2
    exit 1
fi
if [ "$_env_uid" != "$_cur_uid" ]; then
    echo "[post-review] env file owner mismatch (expected uid=$_cur_uid, got $_env_uid): $ENV_FILE" >&2
    exit 1
fi
if [ "$_env_mode" != "600" ] && [ "$_env_mode" != "400" ]; then
    echo "[post-review] env file permissions too open (expected 600/400, got $_env_mode): $ENV_FILE" >&2
    exit 1
fi

# security MED-1: allowlist key 만 export — arbitrary shell 실행 방어.
# `. "$RESOLVED_ENV_FILE"` 대신 grep 으로 허용 key(GH_TOKEN, GH_USER)만 추출.
_GH_TOKEN_VAL="$(grep -E '^GH_TOKEN=[[:print:]]+$' "$RESOLVED_ENV_FILE" | head -1 | cut -d= -f2- || true)"
_GH_USER_VAL="$(grep -E '^GH_USER=[[:print:]]+$' "$RESOLVED_ENV_FILE" | head -1 | cut -d= -f2- || true)"
# strip surrounding quotes if present — matched pair only (single or double)
# WARN-quote-strip: leading/trailing 독립 strip 대신 matched pair 만 strip
# (e.g. 'value' → value, "value" → value, 'value" → 그대로)
if [[ "$_GH_TOKEN_VAL" == \"*\" ]] || [[ "$_GH_TOKEN_VAL" == \'*\' ]]; then
    _GH_TOKEN_VAL="${_GH_TOKEN_VAL:1:${#_GH_TOKEN_VAL}-2}"
fi
if [[ "$_GH_USER_VAL" == \"*\" ]] || [[ "$_GH_USER_VAL" == \'*\' ]]; then
    _GH_USER_VAL="${_GH_USER_VAL:1:${#_GH_USER_VAL}-2}"
fi
if [ -z "$_GH_TOKEN_VAL" ]; then
    echo "[post-review] GH_TOKEN missing or empty in $ENV_FILE" >&2
    exit 1
fi
if [ -z "$_GH_USER_VAL" ]; then
    echo "[post-review] GH_USER missing or empty in $ENV_FILE" >&2
    exit 1
fi
GH_TOKEN="$_GH_TOKEN_VAL"
GH_USER="$_GH_USER_VAL"
unset _GH_TOKEN_VAL _GH_USER_VAL
# security LOW-5: GH_TOKEN export scope 최소화 — 전역 export 대신 각 gh 호출 앞 inline 주입
# (gh 호출은 GH_TOKEN=... gh ... 패턴으로 전달, 아래 각 호출부 참조)
# 단, gh 는 GH_TOKEN env 를 자동 탐색하므로 subshell 격리 목적으로 unset 후 inline 주입.
# 본 스크립트 내 모든 gh 호출은 GH_TOKEN="$GH_TOKEN" 명시 또는 export 범위를 유지.
# 현재 구조상 subshell 분리가 어려워 export 유지하되 scope 주석 명시.
export GH_TOKEN  # scope: 본 script process 안 gh 호출 전용 — child process 로 상속됨

#-----------------------------------------------------------------------
# 2. identity verify — token user.login ↔ GH_USER
#-----------------------------------------------------------------------
ACTUAL_USER="$(gh api /user --jq '.login' 2>/dev/null || true)"
# finding L: multiline ACTUAL_USER guard — .login 이 multiline 이면 첫 줄만 사용
ACTUAL_USER="${ACTUAL_USER%%$'\n'*}"
if [ -z "$ACTUAL_USER" ]; then
    echo "[post-review] gh api /user failed — token invalid or network error" >&2
    exit 2
fi
if [ "$ACTUAL_USER" != "$GH_USER" ]; then
    cat >&2 <<EOF
[post-review] identity verify FAIL — token user.login ↔ GH_USER mismatch
  actual (gh api /user):   $ACTUAL_USER
  expected (\$GH_USER):     $GH_USER
  env file:                $ENV_FILE

이 mismatch 는 PR #64 의 architect agent 1차 spawn 의 token confusion bug 사례.
다른 bot PAT 가 source 됐을 가능성 (env file 오염 / process env inheritance bug).
EOF
    exit 2
fi

#-----------------------------------------------------------------------
# 3. scope verify — <role> ↔ GH_USER exact suffix match
# security MED-3: glob *"${ROLE}-bot"* → exact suffix "-${ROLE}-bot" 또는 "${ROLE}-bot" 으로 끝남
#-----------------------------------------------------------------------
_expected_suffix="${ROLE}-bot"
case "$GH_USER" in
    *"-${_expected_suffix}"|"${_expected_suffix}") ;;
    *)
        cat >&2 <<EOF
[post-review] scope verify FAIL — <role> ↔ GH_USER mismatch
  role arg:                $ROLE
  token user.login:        $GH_USER
  expected suffix:         ${_expected_suffix}

agent 가 자기 scope 가 아닌 role 명의로 review 게시 시도 catch.
EOF
        exit 3
        ;;
esac

#-----------------------------------------------------------------------
# 4. repo owner/name 추출 (origin remote 기준)
#-----------------------------------------------------------------------
REPO="$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null || true)"
if [ -z "$REPO" ]; then
    echo "[post-review] gh repo view failed — not in a git repo or origin missing" >&2
    exit 5
fi

#-----------------------------------------------------------------------
# 5. last review SHA 산출 — <role> 의 가장 최근 review 의 commit_id
#-----------------------------------------------------------------------
# finding D: API failure 별도 처리 (|| echo '{}' 패턴 폐기 — silent mask 방지)
# security MED-2: GH_USER literal 보간 — shell interpolation 제거 (python3 로 필터)
# fix: gh api v2.46.0 은 --arg 미지원 (jq CLI 전용). python3 로 user 필터링.
_reviews_raw="$(gh api "/repos/${REPO}/pulls/${PR_NUM}/reviews" 2>&1)" || {
    echo "[post-review] gh api reviews 호출 실패 (exit $?): $_reviews_raw" >&2
    exit 5
}
_reviews_out="$(printf '%s' "$_reviews_raw" | python3 -c "
import json, sys
user = sys.argv[1]
reviews = json.loads(sys.stdin.read())
matched = [r for r in reviews if r.get('user', {}).get('login') == user]
print(json.dumps(matched[-1] if matched else {}))
" "$GH_USER")" || {
    echo "[post-review] reviews filter 실패 (exit $?): $_reviews_out" >&2
    exit 5
}
LAST_REVIEW_JSON="$_reviews_out"
LAST_SHA="$(python3 "$SCRIPT_DIR/post_helper.py" extract_field "$LAST_REVIEW_JSON" commit_id)"

#-----------------------------------------------------------------------
# 6. PR head/base SHA 산출 — finding K: last_sha ↔ head_sha atomic snapshot
#    두 SHA 를 같은 API call 에서 추출 (race condition 방지)
#-----------------------------------------------------------------------
_pr_json="$(gh api "/repos/${REPO}/pulls/${PR_NUM}" --jq '{base_sha: .base.sha, head_sha: .head.sha}' 2>&1)" || {
    echo "[post-review] gh api PR 정보 호출 실패 (exit $?): $_pr_json" >&2
    exit 5
}
HEAD_SHA="$(python3 "$HELPER" extract_field "$_pr_json" head_sha)"
PR_BASE_SHA="$(python3 "$HELPER" extract_field "$_pr_json" base_sha)"
[ -z "$HEAD_SHA" ] && { echo "[post-review] failed to fetch PR head.sha" >&2; exit 5; }

[ -z "$PR_BASE_SHA" ] && { echo "[post-review] failed to fetch PR base.sha" >&2; exit 5; }

# idempotent skip — last review 의 SHA == 현 HEAD → 게시 안 함 (사용자 명시 2026-05-22)
if [ -n "$LAST_SHA" ] && [ "$LAST_SHA" = "$HEAD_SHA" ]; then
    echo "[post-review] no new commits since last ${ROLE} review (${LAST_SHA:0:7}) — skip (idempotent)"
    exit 0
fi

# commit 범위 표기 — PR base ~ HEAD (full SHA, GitHub 자동 링크)
COMMIT_LIST="${PR_BASE_SHA} ~ ${HEAD_SHA}"

#-----------------------------------------------------------------------
# 7. findings → expected verdict 산출 + verdict mismatch check
#
# finding C: COMMENT path 제거 (dead code — severity 7가지 enum 모두 APPROVE/REQUEST_CHANGES
#            로 도달. COMMENT 는 unreachable).
# finding H: empty findings = APPROVE 허용 시 bypass hole → 빈 findings 시 최소 1 항목 의무.
#            empty findings 는 reject (exit 1) — agent 가 명시적 PASS/INFO 항목 작성 의무.
#-----------------------------------------------------------------------
# empty findings check (finding H)
_findings_len="$(python3 "$HELPER" findings_len "$FINDINGS_JSON")"
if [ "$_findings_len" = "0" ]; then
    cat >&2 <<'EOF'
[post-review] findings-json 가 빈 배열 — 최소 1 개 항목 필수.
blocking severity 없으면 PASS/INFO 항목 명시 (e.g. [{"severity":"PASS","title":"no issues","detail":"..."}]).
빈 findings + APPROVE = security bypass hole (finding H 정책).
EOF
    exit 1
fi

# finding format validate — title/detail/location length/format check (sub-agent retry 가능한 명확 exit message)
python3 "$HELPER" validate_finding_format "$FINDINGS_JSON" || exit 1

EXPECTED_VERDICT="$(python3 "$HELPER" expected_verdict "$FINDINGS_JSON" "$ROLE")"

if [ "$VERDICT_ARG" != "$EXPECTED_VERDICT" ]; then
    if [ "$ROLE" = "code-reviewer" ]; then
        _policy_msg="정책 (code-reviewer, 옵션 C 2026-05-23): CRITICAL/HIGH at HIGH confidence → REQUEST_CHANGES. MED/WARN/LOW/INFO/PASS = informational → APPROVE. LOW-confidence CRITICAL/HIGH = informational → APPROVE."
    elif [ "$ROLE" = "architect" ]; then
        _policy_msg="정책 (architect, 2026-05-23 강화): CRITICAL/HIGH/MED/WARN → REQUEST_CHANGES. LOW/INFO/PASS = informational → APPROVE."
    else
        _policy_msg="정책 (${ROLE}, 2026-05-24): CRITICAL/HIGH → REQUEST_CHANGES. MED/WARN/LOW/INFO/PASS = informational → APPROVE."
    fi
    cat >&2 <<EOF
[post-review] verdict mismatch — agent 의 verdict 결정 ↔ findings severity 일관성 위반
  arg verdict:        $VERDICT_ARG
  expected (script):  $EXPECTED_VERDICT
  findings severity:  $(python3 "$HELPER" severity_set "$FINDINGS_JSON")
  role:               $ROLE

${_policy_msg}
agent 가 본 정책 위반 시 본 script 가 게시 거절.
EOF
    exit 4
fi

#-----------------------------------------------------------------------
# 8. template file 경로 결정 (findings render 전에 필요 — use-before-set 수정)
#-----------------------------------------------------------------------
TEMPLATE_FILE="$SCRIPT_DIR/templates/${ROLE}.md"
if [ ! -r "$TEMPLATE_FILE" ]; then
    echo "[post-review] template not found: $TEMPLATE_FILE" >&2
    exit 5
fi

#-----------------------------------------------------------------------
# 9. findings render — template file 의 FINDING_TEMPLATE block 기반 render
#    (사용자 명시: template 이 render 의 단일 source)
#-----------------------------------------------------------------------
RENDERED_FINDINGS="$(python3 "$HELPER" render_findings "$FINDINGS_JSON" "$TEMPLATE_FILE" "$ROLE")"

#-----------------------------------------------------------------------
# 10. verdict badge + reason
# finding C: COMMENT case 제거 (dead code — APPROVE/REQUEST_CHANGES 2갈래만)
#-----------------------------------------------------------------------
case "$EXPECTED_VERDICT" in
    APPROVE)
        VERDICT_BADGE="✅ APPROVE"
        VERDICT_LINE="**APPROVE** — no blocking findings."
        ;;
    REQUEST_CHANGES)
        VERDICT_BADGE="❌ REQUEST CHANGES"
        # role-specific blocking policy message (사용자 명시 2026-05-23)
        if [ "$ROLE" = "code-reviewer" ]; then
            VERDICT_LINE="**REQUEST_CHANGES** — CRITICAL/HIGH at HIGH confidence 만 blocking."
        else
            VERDICT_LINE="**REQUEST_CHANGES** — CRITICAL/HIGH/MED/WARN blocking."
        fi
        ;;
    # code-r LOW-1: wildcard branch 제거 — expected_verdict 는 APPROVE/REQUEST_CHANGES 만 반환
    # 도달 불가 코드였으나 명시적 오류로 교체
    *)
        echo "[post-review] unexpected expected_verdict value: $EXPECTED_VERDICT" >&2
        exit 5
        ;;
esac

VERDICT_REASON="$(python3 "$HELPER" verdict_reason "$FINDINGS_JSON")"

#-----------------------------------------------------------------------
# 11. template render
# LOW-step: 옛 중복 번호 (11 was 10) 정정 — 단일 step 11
#-----------------------------------------------------------------------

POST_SCRIPT_SHA="$(git -C "$SCRIPT_DIR" log -1 --pretty=%h -- "$SCRIPT_DIR/post.sh" 2>/dev/null || echo 'uncommitted')"

# safe placeholder substitution — env-based to avoid shell expansion pitfalls
# (multi-line content, `"""`, `$` 등 특수문자 안전).
export _PR_VERDICT_BADGE="$VERDICT_BADGE"
# _PR_LAST_SHA / _PR_LAST_TIME 제거 — template header label 삭제 후 미사용 (MED stale exports)
# _PR_COMMIT_LIST 는 template {{COMMIT_LIST}} placeholder 에서 사용 — 유지
export _PR_COMMIT_LIST="$COMMIT_LIST"
export _PR_FINDINGS="$RENDERED_FINDINGS"
export _PR_VERDICT_LINE="$VERDICT_LINE"
export _PR_VERDICT_REASON="$VERDICT_REASON"
export _PR_BOT_USER="$GH_USER"
export _PR_SCRIPT_SHA="$POST_SCRIPT_SHA"
export _PR_TEMPLATE_FILE="$TEMPLATE_FILE"

BODY="$(python3 "$HELPER" render_template "$TEMPLATE_FILE")"

# LOW-env-leak: _PR_* export 후 사용 완료 — unset
unset _PR_VERDICT_BADGE _PR_COMMIT_LIST
unset _PR_FINDINGS _PR_VERDICT_LINE _PR_VERDICT_REASON _PR_BOT_USER
unset _PR_SCRIPT_SHA _PR_TEMPLATE_FILE

#-----------------------------------------------------------------------
# 12. dry-run mode (env: POST_REVIEW_DRY_RUN=1)
#-----------------------------------------------------------------------
if [ "${POST_REVIEW_DRY_RUN:-}" = "1" ]; then
    cat <<EOF
=== post-review DRY RUN ===
role:        $ROLE
PR:          $PR_NUM
verdict:     $EXPECTED_VERDICT (arg: $VERDICT_ARG ✓)
bot user:    $GH_USER
last review: ${LAST_SHA:-none}
scope:       ${PR_BASE_SHA} ~ ${HEAD_SHA}
============================
$BODY
============================
EOF
    exit 0
fi

#-----------------------------------------------------------------------
# 13. TOCTOU 방어 — gh pr review 호출 직전 token identity 재검증 (finding I)
#     env source 후 파일 변조 / process env 오염 방지
#-----------------------------------------------------------------------
_pre_post_user="$(gh api /user --jq '.login' 2>/dev/null || true)"
if [ -z "$_pre_post_user" ]; then
    echo "[post-review] pre-post identity verify: gh api /user 실패" >&2
    exit 2
fi
if [ "$_pre_post_user" != "$GH_USER" ]; then
    cat >&2 <<EOF
[post-review] pre-post identity verify FAIL — token 이 env source 후 변경됨 (TOCTOU)
  env source 시:  $GH_USER
  현재 (gh api /user): $_pre_post_user
EOF
    exit 2
fi

# finding F: TOCTOU post window — template render (HEAD_SHA snapshot) ↔ 실제 gh pr review 사이
# 새 commit push 시 template 의 commit list 가 stale 가능. 직전 한 번 더 HEAD SHA check.
# 본질 한계: 이 check 와 gh pr review 사이에도 극히 짧은 window 존재 (불가피한 race).
# 완화: mismatch 시 exit 5 — caller 가 재시도. 동시 push 극히 드문 PR review 맥락에서 충분.
_current_head="$(gh api "/repos/${REPO}/pulls/${PR_NUM}" --jq '.head.sha' 2>/dev/null || true)"
if [ -n "$_current_head" ] && [ "$_current_head" != "$HEAD_SHA" ]; then
    cat >&2 <<EOF
[post-review] TOCTOU post window — HEAD SHA 가 template render 후 변경됨 (finding F)
  template render 시 HEAD: $HEAD_SHA
  현재 HEAD:               $_current_head
  commit list 가 stale — post.sh 재호출 필요.
EOF
    exit 5
fi

#-----------------------------------------------------------------------
# 14. gh pr review 호출 (post.sh subshell 의 child 라 hook 자체가 invoke 안 됨)
# finding C: COMMENT case 제거 (APPROVE/REQUEST_CHANGES 2갈래만)
#-----------------------------------------------------------------------
case "$EXPECTED_VERDICT" in
    APPROVE)         REVIEW_FLAG="--approve" ;;
    REQUEST_CHANGES) REVIEW_FLAG="--request-changes" ;;
    *)
        echo "[post-review] unexpected verdict at post stage: $EXPECTED_VERDICT" >&2
        exit 5
        ;;
esac

if ! gh pr review "$PR_NUM" "$REVIEW_FLAG" --body "$BODY" 2>&1; then
    echo "[post-review] gh pr review failed" >&2
    exit 5
fi

echo "[post-review] OK — $ROLE / PR #$PR_NUM / $EXPECTED_VERDICT posted by $GH_USER"
exit 0
