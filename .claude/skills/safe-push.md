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

### 4. push 후 — CI all-green 까지 wait (code-level enforce)

사용자 정책 (2026-05-22) — reviewer cycle 시작 = GitHub Actions 의 CI workflow 모두 pass 후. CI fail 시 본인 fix → 재 push → CI re-run → all-green 후 reviewer spawn.

```bash
.claude/skills/safe-push/check-ci.sh <PR-NUM>
```

본 script 가 logic 강제:
- exit 0 — all CI conclusion=success → step 5 (reviewer spawn) 진행
- exit 1 — 1+ check fail → 본인 fix + 재 push + step 4 로 복귀 cycle
- exit 2 — timeout (default 30분) 또는 argument error

### 5. CI all-green 후 — 4 reviewer parallel spawn

```
4 reviewer parallel spawn:
- oh-my-claudecode:code-reviewer
- oh-my-claudecode:architect
- oh-my-claudecode:security-reviewer
- oh-my-claudecode:test-engineer
```

각 reviewer 의 prompt template = inline (본 skill 안) 또는 별 file (`.claude/skills/safe-push-review-template.md` — follow-up). 대상 commit = `@{u}..HEAD` 의 range.

reviewer 의 출력 = PR comment + APPROVE review (각 bot PAT).

### 6. reviewer 완료 후 — Mergify 가 자동 머지 (PR 2 후)

memory `project_ai-dlc-design` §3 결정 (2026-05-21):
- **verifier agent 제거** — Mergify rule + GitHub branch protection 가 server-side 의무.
- **safe-merge skill deprecated** — Mergify 가 자동 squash merge takeover.

PR 2 (Mergify rule 활성) 후:
- 4 reviewer APPROVE + CI all-green 만족 시 Mergify 가 자동 squash merge.
- 본인 (Claude main session) 가 머지 trigger 안 함.

PR 2 전 (현재 시점):
- 본인 + 사용자 admin bypass (사용자 web UI 머지). raw `gh pr merge` = client-side hook + server-side branch protection 으로 차단.

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
