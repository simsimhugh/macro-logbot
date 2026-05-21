#!/usr/bin/env bash
# task-PROCESS-002 (PR #62) — enforcement layer 1회 setup 자동화.
#
# 다른 프로젝트 적용 시 .claude/ + .githooks/ + .github/ copy 후 본 script 실행.
#
# Usage:
#   ./scripts/setup-enforcement.sh [<OWNER>/<REPO>]
#
# 의무:
#   - gh CLI 인증 (admin 권한 — branch protection rule 설정)
#   - git working tree 안 실행

set -euo pipefail

# --- repo 검출 ---
if [ $# -ge 1 ]; then
    REPO="$1"
else
    REPO="$(gh repo view --json owner,name --jq '.owner.login + "/" + .name' 2>/dev/null)"
fi

if [ -z "${REPO:-}" ]; then
    echo "ERROR: repo 검출 실패. 사용: $0 <OWNER>/<REPO>" >&2
    exit 1
fi

echo "=== Setup enforcement for $REPO ==="
echo ""

# --- 1. client-side git hook 활성 ---
echo "--- 1. client-side git hook (.githooks/) ---"
if [ ! -d .githooks ]; then
    echo "WARN: .githooks/ 디렉토리 없음 — 다른 프로젝트 copy 누락?" >&2
else
    git config core.hooksPath .githooks
    echo "    core.hooksPath = $(git config core.hooksPath)"
fi
echo ""

# --- 2. GitHub branch protection rule on main ---
echo "--- 2. branch protection rule on main ---"
if ! gh auth status >/dev/null 2>&1; then
    echo "ERROR: gh CLI 인증 안 됨. gh auth login 후 재시도" >&2
    exit 1
fi

# main branch 존재 확인
if ! gh api "repos/$REPO/branches/main" >/dev/null 2>&1; then
    echo "WARN: $REPO 의 main branch 없음 — branch 생성 후 재실행" >&2
    exit 1
fi

# branch protection rule 설정
# security v3 HIGH #3 fix: 옛 JSON 의 enforce_admins=false / dismiss_stale_reviews=false /
# required_conversation_resolution=false 가 enforce 약화 → strong default.
# 1-maintainer repo 의 admin lock-out 회피 = ALLOW_ADMIN_BYPASS=1 env override.
ENFORCE_ADMINS=true
DISMISS_STALE=true
REQUIRE_CONVO_RESOLUTION=true

if [ "${ALLOW_ADMIN_BYPASS:-}" = "1" ]; then
    echo "WARN: ALLOW_ADMIN_BYPASS=1 — enforce_admins=false (1-maintainer repo lock-out 회피)" >&2
    ENFORCE_ADMINS=false
fi

gh api "repos/$REPO/branches/main/protection" -X PUT --input - <<JSON
{
  "required_status_checks": null,
  "enforce_admins": $ENFORCE_ADMINS,
  "required_pull_request_reviews": {
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": $DISMISS_STALE
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": $REQUIRE_CONVO_RESOLUTION
}
JSON

echo "    branch protection on main: OK"
echo ""

# --- 3. .claude/ 안 file 검증 ---
echo "--- 3. .claude/ enforcement file 검증 ---"
required_files=(
    ".claude/settings.json"
    ".claude/hooks/pre-bash-gate.sh"
    ".claude/skills/safe-merge.md"
    ".claude/skills/safe-merge/check.sh"
    ".claude/skills/safe-push.md"
    ".githooks/pre-push"
    ".github/CODEOWNERS"
    ".github/pull_request_template.md"
)

missing=0
for f in "${required_files[@]}"; do
    if [ ! -f "$f" ]; then
        echo "    MISSING: $f" >&2
        missing=$((missing + 1))
    fi
done

if [ "$missing" -gt 0 ]; then
    echo "" >&2
    echo "ERROR: $missing enforcement file 누락. 다른 프로젝트 copy 절차 재확인" >&2
    exit 1
fi
echo "    all 8 enforcement files: OK"
echo ""

# --- 4. hook script 의 execute permission ---
echo "--- 4. hook script execute permission ---"
chmod 755 .claude/hooks/pre-bash-gate.sh .claude/skills/safe-merge/check.sh .githooks/pre-push 2>/dev/null || true
echo "    chmod 755: OK"
echo ""

echo "=== Setup done ==="
echo ""
echo "verify:"
echo "  gh api repos/$REPO/branches/main/protection --jq '.required_pull_request_reviews'"
echo ""
echo "test:"
echo "  echo '{\"tool_input\":{\"command\":\"gh pr merge 1\"}}' | .claude/hooks/pre-bash-gate.sh"
echo "  (expected exit 2 + stderr block message)"
