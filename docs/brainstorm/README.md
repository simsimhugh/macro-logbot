# docs/brainstorm — Living Document 정책

본 디렉토리의 doc 은 **living document** (의견 누적 + 결정 보류) 로 정식 spec (`docs/process/`) 와 다른 관리 정책.

## 본 정책의 적용 대상

- 결정 미확정 의견 / 외부 reference 정리 / architectural option 비교
- 사용자 의견 누적 (시간 순)
- sprint 진행 중 update 빈번

## 정식 spec 과의 차이

| 특성 | 정식 spec (`docs/process/`) | brainstorm (`docs/brainstorm/`) |
|---|---|---|
| mutability | immutable — PR + reviewer 5 명 cycle | **mutable — append 자유** |
| decision | 확정 | **보류 / 옵션 비교** |
| reviewer | 5 agent (architect/code/security/test/verifier) 의무 | **1 명 (architect 또는 사용자) 또는 author 직접 머지** |
| PR scope | 단일 spec change | doc 자체의 누적 update |
| 수명 | 영구 | **확정 시 `docs/design/` 으로 승격 또는 `_archive/` 로 이동** |

## PR cycle (light)

1. **사용자 의견 누적 update** (§ 8 같은 history append) — **author 직접 머지** 가능 (light), 또는 PR 안 만들고 worktree branch 만 push
2. **외부 reference 추가** (§ 2/§ 3) — author 직접 또는 architect 1명
3. **결정 사항 update** (§ 9 같은 action item) — architect 1명 review
4. **새 brainstorm doc 신규** — architect 1명 review

5 agent cycle (architect/code-reviewer/security/test-engineer/verifier) **의무 없음**. 본 doc 의 변경은 mutation 본질상 reviewer 5명 부담 정당화 어려움.

## Branch + Commit 규약

- branch: `docs/brainstorm-<topic>` (예: `docs/brainstorm-weak-llm-references`)
- commit message: `docs(brainstorm): <summary>` — 정식 spec 의 `docs:` 와 구별
- commit 빈도: 의견 누적 시 매번 새 commit OK (squash 후 머지 또는 직접 push)

## Update trigger

| trigger | 변경 위치 (예시: `01-약한-LLM-강화-references.md`) | 책임 |
|---|---|---|
| 사용자 의견 message | §8 (사용자 의견 누적) | 본인 (Claude main session) 즉시 append |
| 결정 사항 (path 채택) | §9 (다음 action) | 사용자 결정 후 본인 update |
| 측정 결과 update | §1 (현재 상황 baseline) | sprint 끝 / 측정 후 본인 update |
| 외부 reference 발견 | §2/§3 append + References | WebSearch / WebFetch 시 본인 즉시 append |

## 수명 정책

본 brainstorm doc 의 결정이 확정되면:
- **architectural decision** (예: Path B 채택) → `docs/design/` 의 정식 spec 으로 승격 (별도 PR + reviewer 5명)
- **historical archive** (옛 decision) → `docs/brainstorm/_archive/<원본-name>.md` 로 이동 (수명 종료 기록)

본 README 도 living — 정책 변경 시 update.

## 본 디렉토리의 현재 doc

- [`01-약한-LLM-강화-references.md`](01-약한-LLM-강화-references.md) — Claude Code 리버스 + open-source agent framework reference + Path A/B/C 비교 + 본 sprint architectural 결정

---

**본 정책의 결정 권한**: 사용자. 본인 (Claude) 은 정책 준수 + 정리 + 업데이트.
**관련 정책**: [[feedback-no-self-policy-changes]] (사용자 지시 없이 절차 변경 금지) 의 예외 = 본 doc 의 mutable update.
