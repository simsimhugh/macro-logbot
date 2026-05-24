---
name: post-review
description: 4 reviewer agent (architect / code-reviewer / security-reviewer / test-engineer) 의 PR review 게시 표준 entry. raw `gh pr review` / `gh pr comment` 호출 금지 — 본 skill 의 post.sh 만 정직한 entry.
---

# post-review skill

## 목적

4 reviewer agent 의 PR review 게시:
1. **per-role template** — `templates/{architect,code-reviewer,security-reviewer,test-engineer}.md` 의 일관 형식.
2. **verdict 자동 결정** — finding severity + confidence 기반 (role-specific, 2026-05-24 갱신). agent 의 verdict 자율 결정 금지.
   - `code-reviewer`: CRITICAL / HIGH at HIGH confidence → REQUEST_CHANGES, 나머지 APPROVE
   - `architect`: CRITICAL + HIGH + MED + WARN → REQUEST_CHANGES, LOW / INFO / PASS → APPROVE
   - `security-reviewer` / `test-engineer`: CRITICAL + HIGH → REQUEST_CHANGES, MED / WARN / LOW / INFO / PASS → APPROVE
3. **identity verify** — token user.login ↔ `$GH_USER` 일치 (token 오염 / 다른 bot 명의 게시 catch).
4. **scope verify** — `<role>` ↔ `$GH_USER` substring 일치 (architect agent 가 code-reviewer-bot 명의로 게시 catch).
5. **full PR review** — 매 cycle 전체 PR diff (`origin/main...HEAD`) 를 review scope 로 사용. main session 이 reviewer agent prompt 작성 시 scope 를 incremental 로 좁히는 것 금지 — 기존 finding 이 scope 밖으로 사라지는 사각지대 방지. last review SHA == 현 HEAD 면 게시 skip (idempotent). commit 범위는 template 에 `PR_BASE_SHA ~ HEAD_SHA` (full SHA) 로 표기 — GitHub 이 자동 링크 + 앞 7자리 표시.
6. **lockdown** — raw `gh pr comment` / `gh pr review` 는 hook + settings.deny 가 차단. 본 skill 의 post.sh 만 정직한 entry.

## 사용법 (agent 의 출력 의무)

각 reviewer agent 는 **본 script 호출 만** 출력. raw `gh pr ...` 직접 금지.

```bash
.claude/skills/post-review/post.sh <role> <PR-NUM> <verdict> <findings-json>
```

### 인자

| 인자 | 값 |
|---|---|
| `<role>` | `architect` / `code-reviewer` / `security-reviewer` / `test-engineer` 중 하나 |
| `<PR-NUM>` | 정수, e.g. `65` |
| `<verdict>` | `APPROVE` / `REQUEST_CHANGES` (script 가 findings 로 산출 후 일치 verify) |
| `<findings-json>` | JSON array — 아래 schema 참조 |

severity ∈ {`CRITICAL`, `HIGH`, `MED`, `WARN`, `LOW`, `INFO`, `PASS`}

> **body 표기 정책 (role-specific, 2026-05-23 사용자 명시)**:
> - `code-reviewer`: `CRITICAL` / `HIGH` 만 body render. `MED` / `WARN` / `LOW` / `INFO` / `PASS` 모두 skip.
> - `architect` / `security-reviewer` / `test-engineer`: `CRITICAL` / `HIGH` / `MED` / `WARN` 만 body render. `LOW` / `INFO` / `PASS` 모두 skip.
> verdict 산출 에는 영향 X (원본 findings 기반).

### findings JSON schema

```json
{
  "severity": "MED",
  "title": "Dead code",
  "location": "path/to/file.sh:42",
  "language": "bash",
  "code": "if foo == bar:\n    pass",
  "detail": "optional 짧은 요약",
  "confidence": "HIGH"
}
```

- `severity` — 필수
- `title` — 필수, **1-3 단어 유형** (e.g. `"Race condition"`, `"Dead code"`, `"Doc drift"`)
- `location` — optional, `"relative/path/to/file:line"` 형식. **명시 시 `code` 필수** (발췌 없는 location 만 → exit 1)
- `language` — optional, code block fence 의 lang hint (e.g. `"bash"`, `"python"`, `"typescript"`, `""`)
- `code` — optional (단, `location` 명시 시 **필수**), 문제 코드 발췌 (여러 줄 시 `\n` 구분)
- `detail` — optional, 짧은 요약
- `confidence` — optional, `HIGH` / `MEDIUM` / `LOW` (생략 시 `HIGH`). 옵션 C (2026-05-23): CRITICAL/HIGH at HIGH confidence 만 blocking. LOW-confidence CRITICAL/HIGH = informational → APPROVE.

> **verdict 정책 (role-specific, 2026-05-24 갱신)**:
> - `code-reviewer`: CRITICAL/HIGH + confidence=HIGH (또는 생략) → `REQUEST_CHANGES`. MED/WARN/LOW/INFO/PASS = informational → `APPROVE`. OMC code-reviewer prompt 의 `"REQUEST_CHANGES: CRITICAL or HIGH issues present at HIGH confidence"` 와 정합.
> - `architect`: CRITICAL/HIGH/MED/WARN → `REQUEST_CHANGES`. LOW/INFO/PASS = informational → `APPROVE`.
> - `security-reviewer` / `test-engineer`: CRITICAL/HIGH → `REQUEST_CHANGES`. MED/WARN/LOW/INFO/PASS = informational → `APPROVE`.

### 예시

```bash
.claude/skills/post-review/post.sh code-reviewer 65 APPROVE '[
  {"severity":"MED","title":"Unbounded loop","location":"src/x.py:42","code":"while True:\n    count += 1","detail":"무한 증가."},
  {"severity":"LOW","title":"Typo","location":"src/x.py:7","code":"\"Returs the count\"","detail":"Returs → Returns"}
]'
```

## 동작 흐름

```
agent 의 호출
  ↓
post.sh entry
  ↓
arg parse (role/PR/verdict/findings JSON validate)
  ↓
env source — ~/.config/macro-logbot/<role>-bot.env (GH_TOKEN, GH_USER)
  ↓
identity verify — gh api /user --jq '.login' ↔ $GH_USER (mismatch → exit 2)
  ↓
scope verify — <role> ↔ $GH_USER substring (mismatch → exit 3)
  ↓
last review SHA 산출 — gh api /pulls/<PR>/reviews | select(.user.login == "$GH_USER") | last
  ↓
last SHA == HEAD → idempotent skip (exit 0, 게시 안 함)
  ↓
minimize old reviews — 같은 bot user ($GH_USER) 의 기존 review 를 "Hidden as outdated" 처리
  다른 role/bot 의 review 미터치. minimize 실패는 non-fatal (WARN). dry-run 시 skip.
  ↓
commit 범위 표기 — PR_BASE_SHA ~ HEAD_SHA (full SHA, GitHub 자동 링크)
  ↓
verdict 산출 — findings severity 기반 expected verdict
  ↓
인자 verdict ↔ expected verdict mismatch check (mismatch → exit 4)
  ↓
template render — templates/<role>.md 의 placeholder 치환
  (FINDING_*_TEMPLATE block + spec comment block → review body 에서 strip)
  ↓
gh pr review <PR> --approve|--request-changes --body "$rendered"
```

## Exit codes

| code | 의미 |
|---|---|
| 0 | review 게시 성공 (또는 idempotent skip) |
| 1 | arg parse / env source / JSON validate 실패 |
| 2 | identity verify 실패 (token user.login ↔ GH_USER mismatch) |
| 3 | scope verify 실패 (`<role>` ↔ GH_USER mismatch) |
| 4 | verdict mismatch (인자 verdict ↔ findings 기반 expected) |
| 5 | gh API 호출 / template render 실패 |

## verdict 자동 결정 (role-specific, 2026-05-24 갱신)

| role | blocking severity |
|---|---|
| `code-reviewer` | CRITICAL / HIGH at HIGH confidence (OMC code-reviewer prompt 정의) |
| `architect` | CRITICAL + HIGH + MED + WARN (강화) |
| `security-reviewer` / `test-engineer` | CRITICAL + HIGH 만. MED / WARN = informational |

LOW / INFO / PASS 는 informational — verdict 영향 X, body render 안 함.
security-reviewer / test-engineer 의 MED / WARN 는 body render 하되 verdict 영향 X.

## env 의 위치

`~/.config/macro-logbot/<role>-bot.env` (`chmod 600`):

```bash
GH_TOKEN='github_pat_...'
GH_USER='simsim-<role>-bot'
```

→ 4 file 분리 (architect-bot / code-reviewer-bot / security-reviewer-bot / test-engineer-bot). PAT 권한 = Pull requests RW + Metadata R only.

`MACRO_LOGBOT_BOT_ENV_DIR` env 로 디렉터리 override 가능 (test 용).

## Dry-run mode

```bash
POST_REVIEW_DRY_RUN=1 .claude/skills/post-review/post.sh <args>
```

→ gh pr review 호출 안 함, render 된 body 만 stdout 출력.

**주의 (finding T)**: dry-run mode 도 env source + identity verify 단계를 실행함.
실제 `~/.config/macro-logbot/<role>-bot.env` (또는 `MACRO_LOGBOT_BOT_ENV_DIR` override) 에 유효한 PAT 가 있어야 dry-run 이 성공함. stub 테스트 시 `MACRO_LOGBOT_BOT_ENV_DIR=/path/to/stub-env-dir` 로 mock env file 을 가리켜야 함.

## 본 skill 이 catch 하는 사례

| 사례 | catch step |
|---|---|
| code-reviewer agent 가 CRITICAL/HIGH finding + APPROVE 게시 | verdict mismatch → exit 4 |
| architect agent 가 code-reviewer-bot 명의로 게시 (token confusion) | identity (exit 2) + scope (exit 3) verify |
| reviewer 가 scope 를 incremental 로 좁혀 기존 finding 사각지대 | 본 SKILL.md 의 full PR review 정책 명시 — main 의 scope 축소 prompt 금지 |
| 같은 reviewer 가 같은 HEAD commit 에 대해 2번 review 호출 | idempotent skip (last SHA == HEAD → exit 0, 게시 안 함) |
| reviewer 가 raw `gh pr comment` 직접 호출 (skill bypass) | settings.deny + pre-bash-gate.sh 차단 |
| main session 이 직접 post.sh 호출 (self-impersonation 시도) | hook 의 agent_type 검사 — agent_type field 없음 → 차단 |
| agent 가 다른 role 명의로 post.sh 호출 (e.g. code-reviewer agent 가 role=architect) | hook 의 agent_type ↔ role mismatch 검사 → 차단 |

## 본질 한계

본 skill 은 **agent identity + 형식 표준화** layer. agent 의 실제 review 정직성 은 OMC agent prompt safety 에 의존.

### Claude Code stdin 메타 필드 의존성 (finding G/L)

`pre-bash-gate.sh` 의 `agent_type` 검사는 Claude Code 가 PreToolUse hook 의 stdin JSON 에 주입하는 `agent_type` 필드를 사용.

**이 필드는 Claude Code 의 내부 미문서 API** — 버전 업그레이드 시 field 명 / 값 형식 이 silent 변경될 수 있음.

- 현재 알려진 형식 (2026-05): `"agent_type": "oh-my-claudecode:architect"` (sub-agent invocation 시)
- main session 에서는 field 자체 부재 (empty string 취급)
- 미래 Claude Code 버전 에서 field 제거 / 명칭 변경 시 `agent_type` 검사 가 silent fail-open (모든 agent 통과) 또는 silent fail-closed (모든 agent 차단) 될 수 있음
- **완화**: 본 hook 는 defense-in-depth layer (post.sh 의 scope verify 도 동일 보호 제공). hook fail 단독으로 전체 bypass 가 아님.

### OMC agent prompt 의 정직성 안전망 비대칭

OMC code-reviewer prompt 만 강한 안전망 갖고 있음:
- `Discovery_Filtering_Separation` — main 의 dishonest filter prompt ("only important issues", "don't nitpick") 거부
- `Never approve ... HIGH at HIGH confidence` — 자동 approve 거부

architect / security-reviewer / test-engineer prompt 는 약함 — main 의 dishonest review 지시 거부 vector 명시 X. 매우 정교한 main prompt 의 agent behavior override 시도 시 무력화 가능성.

### 차단 못 하는 vector

- agent 가 정직 review 한 후, agent invocation 안에서 자기 role 의 post.sh 추가 호출 — review cycle 외 자율 호출 차단 불가
- post.sh 의 child gh 호출 — Claude tool 호출 아니라 hook 가 감시 안 함 (의도된 정직한 entry)
- safe-push run.sh 종료 후 reviewer cycle 미진행 — script 가 종료 후 main session 의 행동을 강제할 수단 없음 (finding O). **main session 의 자율 의무**: safe-push 완료 후 반드시 4 reviewer parallel spawn 진행.

### 현실적 보강

- 인간 manual review gate — PR 머지 전 사용자가 한 번 check (현 단계 backstop)
- architect / security-reviewer / test-engineer prompt 의 정직성 안전망 보강 — OMC upstream 작업
