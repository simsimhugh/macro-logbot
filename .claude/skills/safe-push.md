---
name: safe-push
description: branch push entry — commit 검증 + 자동 sub-agent review trigger. raw `git push` 직접 호출 금지 (main/master branch 한정 차단). task-PROCESS-002 enforcement.
allowed-tools: Bash, Read, Agent
---

# /safe-push [BRANCH]

branch push 의 entry skill. **main/master 직접 push 는 차단** (`.claude/settings.json` + hook). feature branch push 는 본 skill 에서 검증 후 진행.

## 의무 검증 sequence

### 1. branch 확인

현재 branch 또는 명시 BRANCH 의 이름이 `main` / `master` 이면:
```
ERROR: main/master 직접 push 금지. PR 경로 사용 — gh pr create + /safe-merge.
```

### 2. local commit 검증

```bash
# unstaged / untracked 확인
git status -s
# 새 commit 의 message 형식 확인 (Conventional Commits + task ID + Co-Authored-By)
git log @{u}..HEAD --format="%s%n%b" 2>/dev/null
```

새 commit 의 message 가 prefix (feat/fix/docs/chore/test/refactor) + task ID + `Co-Authored-By: Claude` 포함 안 하면 warn (block 아님 — soft 검증).

### 3. push

main/master 아닌 branch 의 push 는 raw `git push` 사용 가능 (settings.deny + hook 는 main/master 만 차단):

```bash
git push -u origin <BRANCH>
```

### 4. push 후 자동 review trigger

push 성공 시 본 skill 가 reviewer agent spawn (Agent tool):

```
4 reviewer parallel spawn:
- oh-my-claudecode:code-reviewer
- oh-my-claudecode:architect
- oh-my-claudecode:security-reviewer
- oh-my-claudecode:test-engineer
```

각 reviewer 의 prompt template = `.claude/skills/safe-push-review-template.md` (별 file 또는 본 skill 의 inline). 대상 commit = `@{u}..HEAD` 의 range.

### 5. reviewer 완료 후

4 reviewer 의 보고서 (`/tmp/pr<PR-NUM>-<reviewer>.md`) 작성 → PR comment 게시 (bot PAT) → verifier spawn → verifier PASS 시 머지 진행 (`/safe-merge <PR-NUM>`).

## reviewer prompt format (강제)

각 reviewer agent 의 prompt 의 의무 항목:
- 대상 PR URL + branch + worktree path
- 변경 file 목록 (diff stat)
- 검토 spec (sev 별)
- 출력 형식: verdict (APPROVE / APPROVE with follow-up / REQUEST CHANGES / BLOCK) + findings + 본 PR scope 안/밖 분류 + comment 게시용 본문

본 format 의 template = `.claude/skills/reviewer-prompt-template.md` (별 file, follow-up).

## 본 skill 의 정책 본체

- `docs/process/03-개발-프로세스.md §<task-PROCESS-002>`
- `.claude/settings.json` — main/master push 차단
- `.claude/hooks/pre-bash-gate.sh` — Bash PreToolUse hook
