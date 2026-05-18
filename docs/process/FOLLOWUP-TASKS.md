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

### task-001 — Spec 도구 8/9 불일치 정정
- **출처**: PR #3 architect (issuecomment-4478135929) WARN
- **scope**: `docs/design/02-설계문서.md` §6.3, §9.1, §10.5 — "MCP 도구 8개" → "9개"로 통일 (§5.3 헤더는 이미 v1.1에서 9개로 갱신됨)
- **suggested branch**: `docs/spec-tool-count-fix`
- **reviewer scope**: §9 메타 변경 (architect + verifier만)
- **size estimate**: 3 줄 정도 Edit
- **priority**: high (다음 머지 후 즉시)

### task-002 — §6.2 reviewer comment template과 §6.7 callout 정합
- **출처**: PR #5 architect (issuecomment-4479041673) WARN
- **scope**: `docs/process/03-개발-프로세스.md` §6.2 — 현재 plain `Severity: <PASS|WARN|BLOCK|INFO>` 형식을 §6.7 callout 포함 형태로 갱신
- **suggested branch**: `docs/process-template-callout-fix`
- **reviewer scope**: §9 메타 변경
- **size estimate**: §6.2 template 5~10줄 갱신
- **priority**: high

### task-003 — §6.7 severity 매핑에 LOW 추가
- **출처**: PR #5 architect (issuecomment-4479041673) WARN
- **scope**: `docs/process/03-개발-프로세스.md` §6.7 — code-reviewer/security-reviewer는 LOW까지 5단계인데 callout 표는 4단계. LOW를 NOTE에 매핑 + 한 줄 설명 추가
- **suggested branch**: `docs/process-severity-low-mapping`
- **reviewer scope**: §9 메타 변경
- **size estimate**: 표 1줄 추가
- **priority**: medium

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

1. **task-001** — spec 일관성 (PR #3 머지 후 즉시)
2. **task-002** — process 문서 template 정합성
3. **task-003** — process 문서 severity 매핑 보강
4. **task-006** — CI matrix (Stage 3 진척 후)
5. **deferred 항목들** — 발견 시점에 처리

---

## Completed Tasks

(없음 — PR #3 머지 후 task-001부터 진행)
