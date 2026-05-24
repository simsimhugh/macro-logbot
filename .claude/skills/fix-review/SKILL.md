---
name: fix-review
description: fix sub-agent 위임 시 따라야 할 brief 의무 spec. main session 이 fix sub-agent prompt 작성 시 본 skill 의 brief-template.md 의무 항목을 명시해야 함.
---

# fix-review skill

## 목적

main session 이 fix sub-agent 를 spawn 할 때 sub-agent 가 반드시 따라야 할 의무 항목을 spec 화.
`brief-template.md` 를 main session 의 fix sub-agent prompt 에 포함시켜 regression 및 찾기 누락을 차단.

## 사용법

main session 이 fix sub-agent prompt 작성 시 `brief-template.md` 의 모든 의무 항목을 포함시켜야 함.

```
.claude/skills/fix-review/brief-template.md 참조 — 아래 의무 항목 모두 포함:
1. review comment 직접 read
2. 옛 fix evidence 읽기 (persist 기반)
3. regression verify (evidence 기반)
4. 모든 finding 의 location + code field 읽기
5. fix evidence 쓰기 (persist)
```

## brief-template.md 의무 항목 요약

| 항목 | 의무 내용 |
|---|---|
| review comment 직접 read | `gh pr view <PR> --json reviews --jq '.reviews[].body'` 로 actual finding 본문 fetch 필수 |
| 옛 fix evidence 읽기 | `.omc/state/fix-evidence/pr-<PR-NUM>.json` 에서 이전 cycle fix 매핑 읽기 (역추론 금지) |
| regression verify | evidence 파일의 `fix_lines[].code` 를 grep 으로 현재 파일에 존재하는지 verify |
| location + code 읽기 | finding 이 명시한 actual file:line 의 content (e.g. post_helper.py:344 가 실제 어떤 line 인지) read 의무 |
| fix evidence 쓰기 | fix 완료 후 evidence 파일에 현 cycle entry append (다음 cycle 이 역추론 없이 사용) |

## 본 skill 이 차단하는 사례

| 사례 | 차단 방법 |
|---|---|
| sub-agent 가 review comment 안 읽고 기억에 의존해 fix | `gh pr view --json reviews` 필수 의무 |
| 옛 cycle fix 가 새 작업으로 overwrite (regression) | evidence 파일 읽기 + code grep verify 의무 |
| finding 의 location 만 보고 actual code 미확인 | location + code field 읽기 의무 |
| 매 cycle 마다 git log/show 로 역추론 반복 (비용 + 오류) | evidence persist 로 사실 기반 매핑 (추론 제거) |
