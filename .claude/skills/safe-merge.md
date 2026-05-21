---
name: safe-merge
description: PR 머지 entry — reviewer 5 + verifier APPROVE 검증 후 raw merge. raw `gh pr merge` 직접 호출 금지 (settings.deny + hook 차단). task-PROCESS-002 enforcement.
allowed-tools: Bash, Read
---

# /safe-merge <PR-NUM>

PR 머지 의 **유일한 entry skill**. 본 skill 외 raw `gh pr merge` / `gh api ... merge` / `git update-ref refs/heads/main` 등 모두 `.claude/settings.json` 의 `permissions.deny` + `.claude/hooks/pre-bash-gate.sh` 가 차단.

## 의무 검증 sequence

### 1. 인자 확인

PR-NUM 이 정수인지 확인. 없으면:
```
ERROR: usage — /safe-merge <PR-NUM>
```

### 2. PR comment 확보 (5 이상)

```bash
gh pr view <PR-NUM> --json comments,reviewDecision | jq '.comments | length'
```

5 미만이면 block — reviewer 미완료. comment 갯수 + 누락 reviewer 명시 후 보고.

### 3. 4 reviewer + 1 verifier 의 verdict 검증

각 reviewer agent 의 가장 최근 comment 의 verdict 검증:

| Reviewer | 허용 verdict |
|---|---|
| code-reviewer | APPROVE |
| architect | APPROVE / APPROVE with follow-up |
| security-reviewer | APPROVE / APPROVE with follow-up |
| test-engineer | APPROVE / HEALTHY / APPROVE with concerns |
| verifier | PASS |

검출 방법:
```bash
gh api repos/<OWNER>/<REPO>/issues/<PR-NUM>/comments \
    --jq '.[] | select(.body | contains("Review") or contains("Verifier") or contains("verifier") or contains("architect") or contains("code-reviewer") or contains("security-reviewer") or contains("test-engineer")) | {id, body: .body[0:200]}'
```

5 reviewer 중 1 명이라도 verdict 누락 또는 REJECT/BLOCK 이면 block + 누락 reviewer 보고.

### 4. REQUEST CHANGES 후 fix 시 재approve 검증

만약 어떤 reviewer 의 verdict 가 REQUEST CHANGES 였다면:

```bash
# fix commit 시각 (REQUEST CHANGES 이후 commit) 확보
gh pr view <PR-NUM> --json commits --jq '.commits[-1].committedDate'

# 해당 reviewer 의 그 시각 이후 새 comment 존재 + 새 comment 의 verdict 가 APPROVE 인지
gh api repos/<OWNER>/<REPO>/issues/<PR-NUM>/comments \
    --jq '.[] | select(.created_at > "<fix-commit-date>") | .body[0:200]'
```

재approve 없으면 block — "X reviewer 의 REQUEST CHANGES 후 fix 했지만 재approve 미확인" 보고.

### 5. PR mergeable 상태 확인

```bash
gh pr view <PR-NUM> --json mergeable,mergeStateStatus
```

`mergeable=MERGEABLE` 또는 `mergeStateStatus=CLEAN`/`UNSTABLE` 아니면 block.

### 6. 통과 시 머지

모든 검증 통과 시:

```bash
SAFE_MERGE_BYPASS=1 gh pr merge <PR-NUM> --squash
```

`SAFE_MERGE_BYPASS=1` env 가 `.claude/hooks/pre-bash-gate.sh` 의 차단 우회. 본 env 는 본 skill 의 일부 — 사용자 manual 호출 금지 (settings.deny 가 보조 차단).

### 7. 결과 보고

머지 성공:
```
PR #<NUM> merged at <UTC>
follow-up task 의무: <FOLLOWUP-TASKS.md 의 본 PR 관련 entry 목록>
```

실패:
```
PR #<NUM> merge BLOCKED — <원인>
복구 방법: <reviewer 재spawn / fix push / verifier 재spawn 등>
```

## 본 skill 의 정책 본체

- `docs/process/03-개발-프로세스.md §<task-PROCESS-002>` — process enforcement layer
- `.claude/settings.json` — permissions.deny rule
- `.claude/hooks/pre-bash-gate.sh` — Bash PreToolUse hook (보조 safety net)

## 다른 프로젝트 적용

본 skill + hook + settings.json + .gitignore policy 를 그대로 copy:
```
cp -r .claude/{settings.json,hooks,skills} <other-project>/.claude/
# .gitignore 의 .claude/worktrees/ + .claude/settings.local.json 만 ignore 정책
```
