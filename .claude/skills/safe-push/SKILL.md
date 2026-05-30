---
name: safe-push
description: branch push entry — commit 검증 + git push + CI all-green wait + reviewer spawn 의무. raw `git push` 직접 호출 금지 (모든 branch). task-PROCESS-002 enforcement.
allowed-tools: Bash, Read, Agent
---

# safe-push skill

## 목적

branch push 의 정직한 entry:
1. **main/master 차단** — 직접 push 금지, PR 경로 강제.
2. **commit 형식 검증** — Conventional Commits prefix soft warn.
3. **git push** — subshell child 로 실행 (hook 우회 의도된 정직한 entry).
4. **CI all-green wait** — `check-ci.sh` 로 code-level 강제.
5. **reviewer spawn 의무** — step 5 는 main session 의 Agent tool 호출 의무 (본 script 종료 후).

> **caller = main 전용 (issue #95)**: `run.sh` 호출은 **main session 전용**입니다. sub-agent
> (verifier · fix executor 등)의 `bash run.sh` 호출은 `pre-bash-gate.sh` hook 이 차단합니다
> (stdin `agent_type` 가 비어있지 않으면 = sub-agent → 차단). 이는 review 게시(`post.sh`)가
> **sub-agent 전용**인 것의 정반대 대칭 — **"push = main, review = sub-agent"**. 상대경로 카논형식·
> 경로 정규화 변형·`bash`/`sh`/`env`/`source`/dot-source wrapper·`&&`·`;`·subshell·개행(여러 줄) 체인·
> 선행 redirect(`>`/`<`/`>&` target decapitation) 우회를 hook 이 탐지합니다. 단, 이 강제는 `agent_type`(Claude Code 내부 미문서 필드)에 의존하는
> defense-in-depth layer 이며 — command substitution·백틱·here-string·`bash -c` 내부 identity·bare-basename
> 호출(`cd <skill-dir> && bash run.sh`) 등은 미탐지(residual) — 본질 경계는 server-side(branch protection + Mergify)입니다.
> → [`docs/process/03-개발-프로세스.md`](../../../docs/process/03-개발-프로세스.md) §7

## 사용법

```bash
bash .claude/skills/safe-push/run.sh <BRANCH> [--force-with-lease]
```

`<BRANCH>` 생략 시 현재 branch 자동 사용.

`--force-with-lease` — 안전한 force push (remote 에 다른 변경이 있으면 거절). 필요한 경우에만 쓰는 opt-in.

## 동작 흐름

```
run.sh 호출
  ↓
step 1: branch 확인 — main/master 이면 exit 1 (차단)
  ↓
step 2: local commit 검증 (soft) — git status -s + Conventional Commits prefix warn
  ↓
step 3: git push -u origin <BRANCH>   ← subshell child → hook invoke 안 됨 (정직한 우회)
  ↓
step 4: CI all-green 대기 — check-ci.sh <PR-NUM>
         (PR 없음 → push 완료 메시지 후 exit 0)
  ↓
run.sh 종료 (exit code 반환)
  ↓
[main session 의 자율 의무]
  ↓
case exit code in
    0 (all-green) → 4 reviewer parallel spawn (Agent tool):
                    - oh-my-claudecode:architect
                    - oh-my-claudecode:code-reviewer
                    - oh-my-claudecode:security-reviewer
                    - oh-my-claudecode:test-engineer
                    각 agent 가 review 진행 후 post.sh 통해 게시
    1 (CI fail)   → log 분석 + fix + new commit + safe-push 재호출 (cycle)
    2 (timeout)   → 사용자에게 보고 (자율 진행 중단)
esac
```

step 6: Mergify auto-merge (PR 2 후) 또는 사용자 admin bypass (PR 2 전).

## main session 의 의무

### 단일 safe-push cycle 의무

`bash run.sh <BRANCH>` 호출 후 main session 은 **반드시** exit code 확인하고 자율 진행:

| exit code | 의미 | main session 의 자율 행동 |
|---|---|---|
| 0 | push + CI all-green | 4 reviewer parallel spawn (Agent tool 4 회, 아래 참조) |
| 1 | CI fail 또는 push 오류 | CI log 분석 → fix → new commit → safe-push 재호출 (cycle) |
| 2 | CI poll timeout | 사용자에게 보고 + 자율 진행 중단 |

**exit 0 시 4 reviewer parallel spawn 방법** (Agent tool, run_in_background=false):

```
Agent(subagent_type="oh-my-claudecode:architect",       prompt="PR #N review ...")
Agent(subagent_type="oh-my-claudecode:code-reviewer",   prompt="PR #N review ...")
Agent(subagent_type="oh-my-claudecode:security-reviewer", prompt="PR #N review ...")
Agent(subagent_type="oh-my-claudecode:test-engineer",   prompt="PR #N review ...")
```

각 agent prompt 에 명시:
- 대상 PR 번호
- **reviewer 의 review·게시 계약은 [`post-review/SKILL.md`](../post-review/SKILL.md) 따름** (safe-push 는 spawn 만 담당 — reviewer 동작은 정의하지 않음)

**본 의무를 따르지 않으면**: review 0 상태 유지 + 머지 불가. run.sh exit 후 침묵은 spec 위반.

2026-05-22 PR #71 cycle 에서 main session 이 raw `git push` 만 호출 + reviewer cycle skip = review 0 상태 + 사용자 catch. 본 spec 은 해당 패턴의 재발 방지 — 자율 진행 = main session 의 책임.

### 4 reviewer cycle 의무

4 reviewer parallel spawn 후 **모든 review 게시 완료 wait**. push 후 침묵 금지 — 결과 처리부터 머지까지 cycle 을 완수할 의무 (#71 재발 방지). 결과별 처리:

- **모두 APPROVE** → 머지 진행 (Mergify auto / 사용자 admin bypass)
- **1+ REQUEST_CHANGES** → fix → verify → re-push 후 새 reviewer cycle 재진입 (모두 APPROVE 까지 반복)
- **COMMENT 만** → main session 판단 (finding 정합성 검토 후 필요 시 fix)

**reviewer cycle (outer loop) 재시도 한도**: 같은 finding 으로 reviewer 가 **3 cycle 연속 REQUEST_CHANGES** 면 본 PR 에 `needs-human-review` label + 사용자 개입 (orchestrator 자율 진행 중단). fix→verify inner loop 한도는 [`verify-fix/SKILL.md`](../verify-fix/SKILL.md) 소유.

**re-push commit 규칙**: fix 수렴 후 main session 이 commit 한 뒤 `run.sh` 로 push. cycle 당 새 commit 1 개로 통합은 **권장**(작성 위생)이지 **강제 아님** — 이미 push 된 commit 에 추가 fix 면 amend/force 말고 **별도 commit 으로 push** (머지 시 Mergify 가 squash).

## Exit codes

| code | 의미 |
|---|---|
| 0 | push + CI 완료 (또는 PR 없음 — push 만 완료) |
| 1 | main/master push 시도 차단 또는 branch 인자 누락 |
| (check-ci.sh exit 1) | CI 1+ check failed — fix + 재 push + 재 실행 필요 |
| (check-ci.sh exit 2) | CI poll timeout 또는 argument error |

## 본 skill 의 정책 본체

- `.claude/settings.json` — 모든 raw git push 차단
- `.claude/hooks/pre-bash-gate.sh` — Bash PreToolUse hook

## 본질 한계

script 의 `git push` 는 subshell child 로 실행 — Claude tool 호출이 아니라 hook 가 감시 안 함 (의도된 정직한 entry). 단, main session 이 본 script 를 경유하지 않고 raw `git push` 를 직접 시도하면 hook 가 차단. 본 skill 의 enforceability 는 main session 의 정직한 entry 준수에 의존.
