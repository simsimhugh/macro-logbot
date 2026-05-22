<!-- task-PROCESS-002 (2026-05-21) — PR template. format 강제 보조. -->

## Summary

<!-- 1-2 문장. 본 PR 의 의도 + 변경의 핵심. -->

## 변경 (file 수 + 주요 file)

<!-- diff stat 또는 file list. -->

## Refs

- task-<ID>
- 사용자 요구 / 사내 평가 발견 / 옛 PR 의 follow-up

## Test plan

- [ ] `pytest tests/<관련>` — 신규 / 기존 test PASS
- [ ] bash syntax (`bash -n` scripts/) — 변경 script 있으면
- [ ] 실측 (있으면) — 사내 / 사외 environment 검증

## Reviewer cycle (task-PROCESS-002 enforcement)

본 PR 머지 전 의무:
- [ ] 4 reviewer (code-reviewer / architect / security-reviewer / test-engineer) PR comment 게시
- [ ] verifier PR comment 게시 (PASS)
- [ ] REQUEST CHANGES 후 fix 시 같은 reviewer 의 재approve

머지 = Mergify auto-merge (PR 2 후, conditions 만족 시) 또는 사용자 admin bypass (PR 2 전). raw `gh pr merge` 는 차단.

## Follow-up (별 PR)

<!-- 본 PR scope 밖 finding 의 follow-up task ID 목록. -->

🤖 Generated with [Claude Code](https://claude.com/claude-code)
