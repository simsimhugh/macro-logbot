---
name: safe-merge
description: PR 머지 entry — `.claude/skills/safe-merge/check.sh` 로 검증 위임 (5 reviewer + verifier verdict + 재approve) + FAIL 시 N=3 재spawn cycle. raw `gh pr merge` 직접 호출 금지.
allowed-tools: Bash, Agent
---

# /safe-merge <PR-NUM>

PR 머지 의 **유일한 entry skill**. 본 skill 외 raw `gh pr merge` / `gh api ... merge` / `git update-ref refs/heads/main` 등 모두 `.claude/settings.json` 의 `permissions.deny` + `.claude/hooks/pre-bash-gate.sh` 가 차단.

## flow (code-level enforce)

### 1. check.sh 호출 (logic 위임)

```bash
.claude/skills/safe-merge/check.sh <PR-NUM>
```

본 script 가 다음 의무 검증을 code-level 강제 (본인 markdown 의지 의존 X):
1. PR comment ≥ 5
2. 4 reviewer (code-reviewer/architect/security-reviewer/test-engineer) latest verdict = APPROVE
3. verifier latest verdict = PASS
4. REQUEST CHANGES 후 fix commit 시 같은 reviewer 의 재approve
5. PR mergeable=MERGEABLE / mergeStateStatus=CLEAN|UNSTABLE

### 2. exit code 분기

| exit | 의미 | 다음 step |
|---|---|---|
| **0** | 모든 check PASS | step 3 — raw merge |
| **1** | reviewer 일부 verdict 누락/REJECT/REQUEST CHANGES | step 4 — 자동 재spawn cycle |
| **2** | argument error 또는 fatal | step 5 — 사용자 manual |

### 3. PASS — raw merge

```bash
SAFE_MERGE_BYPASS=1 gh pr merge <PR-NUM> --squash
```

`SAFE_MERGE_BYPASS=1` env 가 `.claude/hooks/pre-bash-gate.sh` 의 차단 우회. 본 env 는 skill 의 일부.

### 4. FAIL — 자동 재spawn cycle (N=3 retry)

1. check.sh stderr 의 `FAIL #N: reviewer '<name>' verdict = <V>` 메시지 분석 — 어떤 reviewer 의 verdict 누락/REJECT
2. 그 reviewer 만 Agent tool 로 재spawn (재검증 prompt + 이전 review file 참조)
3. 재spawn 완료 후 reviewer comment PR 게시 (bot PAT)
4. check.sh 재호출 → step 2 분기
5. **N=3 retry 초과** → step 5 (사용자 manual)

### 5. 사용자 manual

본인이 사용자에게 보고:
```
PR #<N> 머지 fail — <원인>.
재spawn cycle N=3 소진. 사용자 manual 결정 필요.
```

## 본 skill 의 본질 한계 (정직 명시 — security v3 발견)

1. **markdown instruction 의 의지 의존**: 본 skill 본문은 instruction — 본인 (Claude main session) 이 step 4 재spawn cycle skip 가능. **완전한 enforcement = check.sh (code-level) + 본 markdown + 사용자 manual review backstop (3 layer)**.

2. **shell semantic 의 본질 한계** (security v3 HIGH #2 — regex/tokenize 로 catch 불가):
   - `alias g=gh; g pr merge 60` — alias 는 shell session state, static analysis 불가
   - `GH=gh; $GH pr merge 60` — variable expansion 은 runtime, static analysis 불가
   - 본 우회는 **GitHub branch protection rule (server-side, `enforce_admins=true`)** 가 backstop

3. **`.claude/settings.local.json` override** (security v3 LOW #6): user-local override 가 `permissions.ask`/`deny` widen 가능 — `.gitignore` 의 본 file ignore 정책으로 secret 보존, 다만 정책 widen 위험 → settings.local.json 의 정책 widening 금지 (사회적 계약).

## 보완 layer (defense-in-depth)

| Layer | 역할 |
|---|---|
| Layer 1 — `.claude/` (settings + hook + skill) | client-side, 본인 명령 시점 차단 + skill entry 강제 |
| Layer 2 — `.githooks/pre-push` | client-side, main/master push 차단 |
| Layer 3 — GitHub branch protection rule | server-side, force-push 금지 + required PR review + `enforce_admins=true` (Layer 1 우회 시도 backstop) |

## 옛 의무 검증 sequence (참조 — check.sh 에 통합)

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
