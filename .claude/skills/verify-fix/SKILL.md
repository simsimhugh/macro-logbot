---
name: verify-fix
description: 검증 sub-agent 가 fix 의 정확성 verify 의무 spec. main session 이 verifier sub-agent prompt 작성 시 본 skill 의 verifier-template.md 의무 항목을 명시해야 함.
---

# verify-fix skill

## 목적

fix sub-agent 의 작업 완료 후 main session 이 verifier sub-agent 를 spawn 해 fix 의 정확성을 검증.
`verifier-template.md` 를 main session 의 verifier sub-agent prompt 에 포함시켜 regression 및 누락 fix 를 catch.

## verifier 구성 (단일 · 전체 통합 · 보고 전용)

- **단일 verifier**: fix 가 여러 reviewer 도메인에 걸쳐도 **verifier sub-agent 는 1 개** (agent type `oh-my-claudecode:verifier`, sonnet). reviewer 별로 쪼개지 않는다 — verify 의 핵심은 **도메인 간 regression 검출**(한 도메인의 fix 가 다른 도메인의 fix 를 깨뜨림, 예: security fix 가 architect fix 를 깼나)이라, 변경 전체를 한 agent 가 한 번에 봐야 사각지대가 없다. **reviewer 4 개(다양한 전문성 렌즈) → verifier 1 개(전체 통합 조망)** 의 비대칭이 의도된 설계.
- **검증 대상**: fix 산출물의 **전체 변경** (단일 worktree 산출물, commit 수 무관).
- **FAIL 임계값**: 의무 검증 항목 중 **1 개라도 FAIL 이면 전체 verdict = FAIL** (부분 통과 없음). → 완료 보고 항목 9.
- **보고 전용 · push 금지**: verifier 는 결과를 **`PASS` / `FAIL` 로 main session 에 보고만** 한다. push / merge / commit 권한 없음 (settings.deny 가 raw push 물리 차단). 후속 행동(push · reviewer spawn 등)은 main session 이 수행.
  - `FAIL` → main session 이 재-fix 지시 (fix→verify 재실행). **inner loop 재시도 한도 = 최대 3회** — verifier 3회 연속 FAIL 시 `needs-human-review` label + 사용자 개입 (non-converging fix 무한 루프 방지).
  - `PASS` → main session 에 PASS 보고 → 이후 push·reviewer cycle 재진입은 main session 의 의무 (→ [`safe-push/SKILL.md`](../safe-push/SKILL.md)).

## 사용법

main session 이 verifier sub-agent prompt 작성 시 `verifier-template.md` 의 모든 의무 항목을 포함시켜야 함.

```
.claude/skills/verify-fix/verifier-template.md 참조 — 아래 의무 항목 모두 포함:
1. 옛 fix evidence preserved 검증 (evidence 파일 기반)
2. 새 finding fix evidence 매핑
3. regression catch (evidence 기반)
4. end-to-end test (post.sh dry-run)
5. block 사유 별 specific verify
6. cycle history regression tracking (evidence 기반)
7. end-to-end dry-run (post.sh sample 호출)
8. evidence 파일 존재 + 무결성 검증
```

## verifier-template.md 의무 항목 요약

| 항목 | 의무 내용 |
|---|---|
| 옛 fix evidence preserved 검증 | evidence 파일에 기록된 모든 cycle 의 fix 가 현 HEAD 에 그대로 있는지 확인 |
| 새 finding fix evidence 매핑 | 새 cycle 의 finding 별 fix 의 actual file:line + diff 매핑 |
| regression catch | evidence 파일 기반 옛 fix 가 새 작업으로 overwrite 됐는지 검출. 발견 시 FAIL + 재 fix 의무 |
| end-to-end test | fix 후 actual post.sh dry-run 호출 — PAT 없으면 render_findings/expected_verdict 단위 테스트 |
| block 사유 별 specific verify | 각 block 사유 finding 의 location 의 actual content 가 fix 됐는지 구체적 확인 |
| cycle history regression tracking | evidence 파일의 모든 cycle 의 block 사유 fix 가 현 HEAD 에 보존됐는지 추적 |
| end-to-end dry-run | post.sh helper 6 개 sample 호출 + 기대 결과 일치 여부 확인 |
| evidence 파일 무결성 검증 | evidence 파일 존재 + JSON 파싱 + 필수 필드 확인 |

## 완료 보고 의무 항목 요약

| # | 보고 항목 |
|---|---|
| 1 | 옛 fix preserved 표 — evidence 파일의 각 cycle fix code → 현 HEAD 존재 여부 (PASS/FAIL) |
| 2 | 새 finding fix evidence 표 — finding 별 fix file:line + diff 요약 |
| 3 | regression 없음 확인 — evidence 기반 code grep 결과 |
| 4 | end-to-end test 결과 — render_findings / expected_verdict 단위 테스트 출력 |
| 5 | block 사유 별 specific verify — 각 finding location 의 actual content fix 확인 |
| 6 | cycle history regression tracking — evidence 파일 기반 전체 cycle fix 보존 여부 |
| 7 | end-to-end dry-run 결과 — post.sh helper 6 개 sample 호출 + 기대 결과 일치 여부 |
| 8 | evidence 파일 무결성 — 파일 존재 + JSON 파싱 + 필수 필드 확인 |
| 9 | 전체 verdict — PASS (모두 확인) 또는 FAIL (재 fix 필요 항목 명시) |

## 본 skill 이 catch 하는 사례

| 사례 | catch 방법 |
|---|---|
| 옛 cycle fix 가 새 작업으로 overwrite (regression) | evidence 파일 기반 옛 fix code 현 HEAD 존재 여부 확인 |
| fix sub-agent 가 finding 일부 누락 | finding 별 fix evidence 매핑 — 매핑 없으면 FAIL |
| post.sh dry-run 자체 버그 (cycle 6 의 gh --arg broken 사례) | actual dry-run 호출 + stdout/exit code 확인 |
| body template render 깨짐 | dry-run body sample 에서 placeholder 미치환 여부 확인 |
| fix sub-agent 가 evidence 파일 미작성 | evidence 파일 존재 + 무결성 검증으로 catch |
| cycle history regression | evidence 파일의 전체 cycle fix code 보존 추적 |
