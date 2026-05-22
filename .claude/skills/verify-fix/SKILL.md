---
name: verify-fix
description: 검증 sub-agent 가 fix 의 정확성 verify 의무 spec. main session 이 verifier sub-agent prompt 작성 시 본 skill 의 verifier-template.md 의무 항목을 명시해야 함.
---

# verify-fix skill

## 목적

fix sub-agent 의 작업 완료 후 main session 이 verifier sub-agent 를 spawn 해 fix 의 정확성을 검증.
`verifier-template.md` 를 main session 의 verifier sub-agent prompt 에 포함시켜 regression 및 누락 fix 를 catch.

## 사용법

main session 이 verifier sub-agent prompt 작성 시 `verifier-template.md` 의 모든 의무 항목을 포함시켜야 함.

```
.claude/skills/verify-fix/verifier-template.md 참조 — 아래 의무 항목 모두 포함:
1. 옛 fix evidence preserved 검증
2. 새 finding fix evidence 매핑
3. regression catch
4. end-to-end test
```

## verifier-template.md 의무 항목 요약

| 항목 | 의무 내용 |
|---|---|
| 옛 fix evidence preserved 검증 | 옛 cycle 의 fix 의 file:line + diff content 가 현 HEAD 에 그대로 있는지 확인 |
| 새 finding fix evidence 매핑 | 새 cycle 의 finding 별 fix 의 actual file:line + diff 매핑 |
| regression catch | 옛 fix 가 다른 sub-agent 의 작업으로 overwrite 됐는지 검출. 발견 시 FAIL + 재 fix 의무 |
| end-to-end test | fix 후 actual post.sh dry-run 호출 + body sample 검증 |

## 본 skill 이 catch 하는 사례

| 사례 | catch 방법 |
|---|---|
| 옛 cycle fix 가 새 작업으로 overwrite (regression) | 옛 fix file:line 현 HEAD 존재 여부 확인 |
| fix sub-agent 가 finding 일부 누락 | finding 별 fix evidence 매핑 — 매핑 없으면 FAIL |
| post.sh dry-run 자체 버그 (cycle 6 의 gh --arg broken 사례) | actual dry-run 호출 + stdout/exit code 확인 |
| body template render 깨짐 | dry-run body sample 에서 placeholder 미치환 여부 확인 |
