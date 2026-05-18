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

### task-LG-001 — Message 모델 tool_calls round-trip 지원 (Agent Core 선결)
- **출처**: PR #8 architect (issuecomment-4479740071) WARN
- **scope**: `src/macro_logbot/gateway/models.py` `Message` 에 `tool_calls: list[ToolCall] | None`, `tool_call_id: str | None`, `name: str | None` 추가 + `client.py` 직렬화에서 None 제외해 LiteLLM 으로 전달. spec §5.2 AgentState.messages · §5.4 Session.messages · §7.4 AS-1 multi-turn tool calling 검증 (E000 case) 선결 요건.
- **suggested branch**: `feat/gateway-tool-calls`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **size estimate**: models.py ~20 lines + client.py ~10 lines + tests ~50 lines
- **priority**: **high** — Agent Core PR (feat/agent-core) 시작 전 선결

### task-LG-002 — LLMGateway base_url/api_key override (사내 LLM 통합 선결)
- **출처**: PR #8 architect (issuecomment-4479740071) WARN
- **scope**: `LLMGateway.__init__` 에 `base_url: str | None = None`, `api_key: str | None = None`, `custom_llm_provider: str | None = None` 인자 추가 + 대응 env `MACRO_LOGBOT_LLM_BASE_URL` · `MACRO_LOGBOT_LLM_API_KEY` 흡수 + `acompletion` 호출 시 forward. spec §7.3 직접 인용.
- **suggested branch**: `feat/gateway-internal-llm-hooks`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **size estimate**: client.py ~30 lines + tests ~40 lines
- **priority**: **high** — 사내 LLM endpoint 통합 PR 시작 전 선결

### task-LG-003 — /v1/chat/completions streaming (SSE) 지원
- **출처**: PR #8 architect (issuecomment-4479740071) WARN — 본 PR 에서는 400 으로 임시 거절
- **scope**: `/v1/chat/completions` 에 `stream=true` 시 `StreamingResponse(media_type="text/event-stream")` 반환 — LiteLLM `acompletion(stream=True)` async generator forward. Open WebUI 호환 운영 진입 전 필요.
- **suggested branch**: `feat/gateway-streaming`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **size estimate**: app.py + client.py ~60 lines + tests ~80 lines
- **priority**: medium — Open WebUI 통합 PR (feat/openwebui-integ) 시점에 함께

### task-SEC-001 — LiteLLM 3.14 지원 복구 시 1.83.10+ 으로 상향
- **출처**: PR #8 security-reviewer (issuecomment-4479896415) MEDIUM, 본 PR 안 임시 fix (`>=1.83.7,<2.0`) 후 등록
- **scope**: `pyproject.toml` 의 `litellm` pin 을 `>=1.83.10,<2.0` 으로 상향. 현재 LiteLLM 1.83.8+ 은 Python <3.14 만 지원해 본 환경에 미가용. LiteLLM 측에서 3.14 지원 복구하거나 사내 Python 정책이 3.13 으로 정해질 때 진행.
- **현 영향**: 1.83.7 에서 미패치된 유일한 CVE 는 guardrails sandbox escape (GHSA-wxxx-gvqv-xp7p, 1.83.10 fix) — 본 PoC 가 guardrails 미사용이라 무영향.
- **suggested branch**: `chore/litellm-pin-upgrade`
- **reviewer scope**: 일반 (의존성 변경은 §9 메타 아님 — 런타임 영향)
- **priority**: medium — LiteLLM 3.14 지원 또는 Python downgrade 결정 후 즉시

### task-SEC-002 — /v1/chat/completions 인증 미들웨어
- **출처**: PR #8 security-reviewer (issuecomment-4479896415) LOW — 사내 운영 진입 차단 사유
- **scope**: `/v1/chat/completions` 에 API key 또는 JWT 인증 미들웨어 추가. spec §5.1 직접 인용. Open WebUI 통합 PR 또는 직전 선결.
- **suggested branch**: `feat/gateway-auth`
- **reviewer scope**: 일반 (전체 reviewer cycle — security 중요)
- **size estimate**: app.py + middleware ~50 lines + tests ~80 lines
- **priority**: **high** — 사내 운영 진입 / Open WebUI 통합 PR 선결

### task-SEC-003 — LLMGateway.complete kwargs allowlist
- **출처**: PR #8 security-reviewer (issuecomment-4479896415) LOW
- **scope**: `LLMGateway.complete(**kwargs)` 자유 패스스루 → allowlist (`temperature`, `max_tokens`, `top_p`, `stop`, `tools`, `tool_choice` 등) 외 kwargs `ValueError`. `task-LG-002` (base_url/api_key override) 작업 시 동일 시그니처를 건드리므로 함께 도입 권고.
- **suggested branch**: task-LG-002 와 묶음 (`feat/gateway-internal-llm-hooks`)
- **priority**: medium — task-LG-002 시점에 함께

### task-PROCESS-001 — §10.4 검증 항목에 §4.3 병렬 호출 준수 추가
- **출처**: PR #9 architect (issuecomment-4479796124) COMMENT + verifier (issuecomment-4479834661) follow-up 권고
- **scope**: `docs/process/03-개발-프로세스.md` §10.4 검증 방법에 (1) "비-meta PR 의 CR/Sec/Test comment timestamp 가 거의 동일 시각 (병렬 호출 흔적)" (2) "§3.6 verifier 호출 트리거 표현 일관성 (CR/Sec/Test 병렬 통과 후)" 두 항목 추가.
- **suggested branch**: `docs/process-parallel-verification`
- **reviewer scope**: §9 메타 변경 (architect+verifier 단독)
- **size estimate**: docs 5~10 lines
- **priority**: medium — Stage 3 다음 PR 들이 본 정책 따라 진행되는지 검증 가능해야 함

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

### task-LG-004 — LG spec §7.1 잔여 책임 (rate limit · retry · timeout 일관 처리)
- **출처**: PR #8 architect (issuecomment-4479740071) COMMENT — follow-up 등록 권고
- **scope**: `LLMGateway.complete` 에 retry/timeout/rate-limit 일관 처리 — Tenacity 또는 LiteLLM `Router` 활용. 사용자 코드가 매 호출마다 새 LLMGateway 인스턴스 생성하는 현 패턴 (`app.py` `get_gateway`) 도 함께 모듈 레벨 싱글톤/`lru_cache` 로 정리.
- **priority**: deferred — Agent Core 통합 시점에 함께 (지금은 stateless 라 위험 낮음)

### task-SEC-004 — 보안 이벤트 로깅 (OWASP A09)
- **출처**: PR #8 security-reviewer (issuecomment-4479896415) LOW/INFO
- **scope**: 인증 시도/실패, 비정상 요청, LLM 호출 오류 등을 표준 로깅 framework 으로 기록. 키/시크릿/PII 마스킹. spec §7.1 LG 책임에 포함될 가능성.
- **priority**: deferred — `feat/agent-core` 또는 운영 진입 PR 시점

---

## Priority Order (실행 순서)

1. **task-LG-001** — Message tool_calls round-trip (Agent Core PR 선결)
2. **task-LG-002** + **task-SEC-003** — LLMGateway base_url/api_key + kwargs allowlist (사내 LLM 통합 PR 선결, 같은 시그니처 건드림)
3. **task-SEC-002** — /v1/chat/completions 인증 (Open WebUI 통합 PR 선결)
4. **task-LG-003** — /v1/chat/completions streaming (Open WebUI 통합 PR 시점)
5. **task-PROCESS-001** — §10.4 §4.3 병렬 호출 검증 항목 (메타 PR)
6. **task-SEC-001** — LiteLLM pin 상향 (LiteLLM 3.14 지원 또는 Python downgrade 결정 후)
7. **task-006** — Python 3.14 CI matrix (Stage 3 진척 후)
8. **deferred 항목들** — 발견 시점에 처리

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
