# Follow-up Task Queue

본 파일은 reviewer agent가 발견했지만 **본 PR scope 밖**이라 별도 PR로 분리해야 하는 task의 외부 가시 queue.

## 정책

[`docs/process/03-개발-프로세스.md`](03-개발-프로세스.md) §6.8 참조:

- **WARN** (architect) / **MEDIUM** (code-reviewer · security-reviewer) 무시 금지
- 본 PR scope 안 수정 가능 → 본 PR에서 수정 commit (§6.5 시간 순서 적용)
- 본 PR scope 밖 → 본 파일 "Pending Tasks"에 등록 + 본 PR description "Follow-up" 섹션에 task ID 명시
- 본 PR 머지 직후 main session orchestrator가 본 queue 점검 → pending task별 follow-up PR 생성 → 정상 reviewer cycle
- 완료된 task는 "Completed Tasks" 섹션으로 이동

**LOW / INFO** finding은 정보성만 — 본 queue 등록 불필요.

---

## Pending Tasks

### task-006 — Python 3.14 휠 가용성 CI matrix (chore)
- **출처**: PR #3 code-reviewer (issuecomment-4479212053) LOW (정보성이지만 가치 있어 등록)
- **scope**: `.github/workflows/`에 minimal CI matrix 추가 — `pip install -e ".[dev]"` + `pytest` 통과 검증. PR #4의 reviewer workflow와 별개 (단순 build/test CI만)
- **suggested branch**: `chore/ci-python-3.14-matrix`
- **reviewer scope**: §9 메타 변경
- **size estimate**: workflow yml 1개 (30~50 lines)
- **priority**: low (Stage 3 코드가 더 쌓인 후)

---

## Deferred (INFO/COMMENT 등급 — 즉시 처리 불필요, 발견 시점에 처리)

### task-004 — §10.4 검증 항목에 reviewer comment 별개 invocation 검증 추가
- **출처**: PR #5 architect (issuecomment-4479041673) COMMENT
- **scope**: §10.4에 "각 reviewer comment의 작성 주체가 별개 agent invocation 결과인지 확인" 한 줄
- **priority**: deferred

### task-005 — §9 pyproject.toml dependencies 경계 명시
- **출처**: PR #5 architect (issuecomment-4479041673) COMMENT
- **scope**: §9에 "dependencies 추가는 런타임 코드 영향 → 비-메타 (전체 reviewer cycle)" 한 줄
- **priority**: deferred

### task-007 — 무료 LLM default model 변경 검토
- **출처**: PR #3 code-reviewer (issuecomment-4479212053) INFO
- **scope**: `.env.example`의 `MACRO_LOGBOT_DEFAULT_MODEL=openai/gpt-4o-mini` → `gemini/gemini-2.0-flash` 또는 `groq/llama-3.3-70b-versatile`로 PoC 기본값 변경 (무료 한도 더 넉넉)
- **priority**: deferred (사용자 결정 사항)

### task-008 — TestClient lifespan-safe fixture 패턴
- **출처**: PR #3 code-reviewer (issuecomment-4479212053) LOW
- **scope**: `tests/conftest.py` — `with TestClient(app) as client: yield client` 패턴 적용
- **priority**: deferred (현재 lifespan 미사용이라 무해)

---

## Priority Order (실행 순서)

1. **task-006** — Python 3.14 CI matrix (Stage 3 진척 후)
2. **deferred 항목들** — 발견 시점에 처리

---

## Completed Tasks

### task-001 — Spec 도구 8/9 불일치 정정 ✅
- **출처**: PR #3 architect (issuecomment-4478591552) WARN
- **처리 PR**: docs/followup-batch-1 (PR #7)
- **변경**: docs/design/02-설계문서.md §6.3 line 286, §9.1 line 396, §10.5 line 630 — "8개"/"8 tools" → "9개"/"9 tools"

### task-002 — §6.2 reviewer comment template과 §6.7 callout 정합 ✅
- **출처**: PR #5 architect (issuecomment-4479041673) WARN
- **처리 PR**: docs/followup-batch-1 (PR #7)
- **변경**: docs/process/03-개발-프로세스.md §6.2 General comment template + Line-level comment template 모두 callout 포함 형태 + 대상 commit 필드 명시

### task-003 — §6.7 severity 매핑에 LOW 추가 ✅
- **출처**: PR #5 architect (issuecomment-4479041673) WARN
- **처리 PR**: docs/followup-batch-1 (PR #7)
- **변경**: docs/process/03-개발-프로세스.md §6.7 표에 LOW · COMMENT/INFO 분리 매핑 추가 (둘 다 `[!NOTE]` 사용)
