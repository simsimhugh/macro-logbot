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

### task-SEC-005 — python-dotenv CVE-2026-28684 회피 (1.2.2+ 상향)
- **출처**: PR #11 security-reviewer (issuecomment-4480493181) MEDIUM
- **scope**: `pyproject.toml` 에 `python-dotenv>=1.2.2` explicit pin. 본 PR 안 시도 시 litellm 1.83.7 dependency resolution 충돌 — litellm 상향 (task-SEC-001) 과 함께 처리. 본 PoC 는 .env 직접 사용 없음, blast radius 낮음.
- **suggested branch**: task-SEC-001 와 묶음 (`chore/litellm-pin-upgrade`)
- **priority**: medium — task-SEC-001 와 함께

### task-MVP-010 — `read_file` 바이너리/크기 가드 확장
- **출처**: PR #11 security-reviewer (issuecomment-4480493181) MEDIUM
- **scope**: `read_file` 의 `_READ_FILE_MAX_BYTES = 2_000_000` (본 PR 안 도입) 외에 (a) 바이너리 파일 magic byte 거절, (b) 스트리밍 read (전체 메모리 로드 회피), (c) `list_directory` `recursive=True` entries max 가드. `task-MVP-006` (Tool 보안 강화) 의 scope 확장 또는 별도.
- **priority**: medium — 사내 운영 진입 전

### task-SEC-006 — Tool kwargs pydantic schema 강제
- **출처**: PR #11 security-reviewer (issuecomment-4480493181) INFO
- **scope**: `tools/registry.py` `execute_tool(**arguments)` 가 LLM 임의 kwarg 받음. tool 별 pydantic Input 모델 정의 + validate. 비현실적 인자 (e.g. `max_results=10**9`) 거절. `task-SEC-003` (LLMGateway kwargs allowlist) 와 별건.
- **priority**: low — Agent Core 안정화 시점

### task-SEC-007 — 운영 manifest 진입 시 `_auth_required()` default fail-closed
- **출처**: PR #12 security-reviewer (issuecomment-4482964138) HIGH
- **scope**: `src/macro_logbot/auth.py:29-32` `_auth_required()` 의 default 를 `true` 로 변경 (fail-closed). 현재 docker-compose.yml 의 `:-true` mitigation 으로 demo 안전하나, `.env` 명시 `false` 시 통과. 운영 manifest 진입 시 코드 default 자체를 fail-closed 로 뒤집고 dev 모드 진입을 startup ERROR 로 가시화.
- **suggested branch**: `chore/auth-fail-closed-default`
- **priority**: **high** — 사내 운영 진입 전 필수 (task-SEC-002 와 묶음)

### task-SEC-008 — `auth.py` token 비교 `hmac.compare_digest` 적용
- **출처**: PR #12 security-reviewer (issuecomment-4482964138) MEDIUM — **본 PR 안 처리 완료**, follow-up 등록 불요. 확인용 마커.

### task-OPS-001 — Dockerfile multi-stage build (이미지 크기 + 공격 표면 감소)
- **출처**: PR #12 architect (issuecomment-4480701169) COMMENT-1 + security-reviewer L-9
- **scope**: `Dockerfile` 를 builder + runtime 2-stage 로 분리, build-essential 을 runtime image 에서 제거. 이미지 100MB+ 감소 + gcc 등 공격 표면 축소.
- **suggested branch**: `chore/dockerfile-multistage`
- **priority**: medium — 운영 image 진입 전

### task-MVP-011 — gateway/client.py `_extract_tool_calls` dict 경로 테스트
- **출처**: PR #11 test-engineer (issuecomment-4480495225) WARN
- **scope**: `tests/test_gateway.py` 에 `_extract_tool_calls({"id":"x","function":{...}})` 단위 테스트 추가. provider edge case 방어 코드 커버.
- **priority**: low — gateway/client.py coverage 80%+ 회복

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

### task-MVP-001 — LangGraph state graph 마이그레이션
- **출처**: PR #11 MVP 의도된 단순화 (architect issuecomment-4480360602 PR description)
- **scope**: `src/macro_logbot/agent/core.py` 의 직접 `while` loop 을 LangGraph `StateGraph` 로 교체. `run_agent` 시그니처 유지하여 호출부 변경 폭 0. spec §5.2 명시.
- **suggested branch**: `feat/agent-langgraph`
- **size estimate**: 80~120 lines + dependencies (langgraph)
- **priority**: medium — Agent Core 안정화 시점

### task-MVP-002 — Session persistence (SQLite, spec §5.4)
- **출처**: PR #11 MVP 의도된 단순화
- **scope**: `src/macro_logbot/session/` 에 SQLite 백엔드 추가, `InMemorySessionStore` 를 `SQLiteSessionStore` 로 교체 가능한 protocol/interface 도입. spec §5.4 직접 인용.
- **suggested branch**: `feat/session-sqlite`
- **priority**: medium — Open WebUI 운영 진입 시점

### task-MVP-003 — MCP tools 나머지 4개 (spec §5.3)
- **출처**: PR #11 MVP 단순화 (9개 → 5개)
- **scope**: `git_log`, `find_test_history`, `get_environment_info`, `retrieve_similar_cases` 추가. KB 통합 PR 과 함께 또는 별도.
- **suggested branch**: `feat/tools-remaining-4`
- **priority**: medium — Agent Core 안정화 시점

### task-MVP-004 — /agent/analyze session 통합
- **출처**: PR #11 MVP 의도된 단순화
- **scope**: `/agent/analyze` 가 session_id 받아 session messages 누적, 다회차 분석 지원. task-MVP-002 (SessionStore) 후속.
- **priority**: low — multi-turn analysis 요구 시

### task-MVP-005 — intake parser 다국어 level 지원
- **출처**: PR #11 MVP 의도된 단순화
- **scope**: 한국어 등급 (`경고`/`오류`/`치명`) regex 추가. 사내 MACRO 로그 포맷 결정 후 정확한 패턴 매칭.
- **priority**: low — 사내 MACRO 로그 샘플 확보 후

### task-MVP-006 — Tool 보안 강화 (symlink 우회 등)
- **출처**: PR #11 MVP 의도된 단순화
- **scope**: `_safe_resolve` 가 symlink 추적 후 cwd 외부로 가는 경로 차단. `subprocess` argument injection 추가 검증. 사내 운영 진입 전 필수.
- **priority**: medium — `task-SEC-002` (인증) 와 함께 운영 진입 전

### task-MVP-009 — Tools in-process → MCP 서버 분리 (spec §5.3 표현 정합)
- **출처**: PR #11 architect (issuecomment-4480360602) COMMENT
- **scope**: 현재 `tools/builtin.py` 는 in-process Python 함수. spec §5.3 의 "MCP 서버" 표현과 정합 위해 별도 MCP server 프로세스 분리, `tools/registry.py` 가 MCP 클라이언트로 동작.
- **priority**: low — NFR-3 plugin 확장성 본격 활용 시점

### task-006 — Python 3.14 휠 가용성 CI matrix (chore)
- **출처**: PR #3 code-reviewer (issuecomment-4479212053) LOW (정보성이지만 가치 있어 등록)
- **scope**: `.github/workflows/`에 minimal CI matrix 추가 — `pip install -e ".[dev]"` + `pytest` 통과 검증. PR #4의 reviewer workflow와 별개 (단순 build/test CI만)
- **suggested branch**: `chore/ci-python-3.14-matrix`
- **reviewer scope**: §9 메타 변경
- **size estimate**: workflow yml 1개 (30~50 lines)
- **priority**: low (Stage 3 코드가 더 쌓인 후)

### task-POC-001 — 1-B/2-A/2-B Claude judge 채점 (PoC)
- **출처**: PR #14 (feat/poc-infrastructure) — 본 PR 은 1-A 결정론 채점만.
- **scope**: spec §10.1 의 1-B (root_cause 의미 매칭) · 2-A (follow-up tool 적절성) · 2-B (수정 방향 정합성) 를 Claude Code judge 로 채점하는 별도 스크립트 (`poc/scripts/judge.py`) 또는 main session 호출 가이드. follow-up Q1/Q2/Q3 자동 호출 흐름 포함.
- **suggested branch**: `feat/poc-judge`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **size estimate**: ~200 lines + tests + docs
- **priority**: high — PoC baseline 매트릭스 합산 점수 필수

### task-POC-002 — error catalog 5 → 10 확장
- **출처**: PR #14 — spec §10.4 / `docs/process/04-PoC-운영가이드.md` §4.2 의 Phase 1 카탈로그 10 개 명세 대비 본 PR 은 5 개만.
- **scope**: E006 (reversed if condition) · E007 (division by zero) · E008 (infinite loop / 타임아웃) · E009 (wrong variable assignment) · E010 (encoding error 한글 처리) — yaml 5 개 추가 + inject/trigger 검증.
- **suggested branch**: `feat/poc-catalog-expand`
- **reviewer scope**: 일반
- **size estimate**: yaml 5개 + tests
- **priority**: medium — task-POC-001 이후

### task-POC-003 — 4 모델 매트릭스 비교 (PoC)
- **출처**: PR #14 — 본 PR `evaluate.py` 는 단일 `--model` 만 지원.
- **scope**: `--models gemini/...,openai/...,anthropic/...,groq/...` 다중 swap + per-model 결과 분리 저장 + comparison.md 의 모델 매트릭스 (`docs/process/04-PoC-운영가이드.md` §6.4 표 형식). 약한 LLM 강화 사이클의 baseline 필수.
- **suggested branch**: `feat/poc-multi-model`
- **reviewer scope**: 일반
- **size estimate**: evaluate.py ~80 lines + tests + docs
- **priority**: medium — task-POC-001/002 이후

### task-POC-004 — `.env` 자동 로드로 pytest 401 발생 (chore)
- **출처**: PR #14 verifier — 본 PR 작업 중 pre-existing 발견 (main 에서도 재현). litellm/python-dotenv 가 import 시 `.env` 를 흡수 → `MACRO_LOGBOT_API_KEY` set + `AUTH_REQUIRED=true` 상태에서 `tests/test_endpoint_chat_completions.py` · `test_endpoint_agent_analyze.py` 가 401 반환 (TestClient 가 Bearer header 미부착).
- **scope**: `conftest.py` 에 `MACRO_LOGBOT_API_KEY` · `MACRO_LOGBOT_AUTH_REQUIRED` env clear fixture (autouse) 또는 dotenv 자동 로드 비활성화. 본 PR 은 무관 — `.env` 미제거 시 pre-existing 동일 실패.
- **suggested branch**: `chore/test-env-isolation`
- **reviewer scope**: 일반
- **size estimate**: conftest.py 수정 ~20 lines
- **priority**: medium — CI 통과 안정성에 직결

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

1. ~~task-LG-001~~ — Message tool_calls round-trip (PR #11 본 PR scope 안 처리 완료) ✅
2. **task-LG-002** + **task-SEC-003** — LLMGateway base_url/api_key + kwargs allowlist (사내 LLM 통합 PR 선결)
3. **task-SEC-002** + **task-MVP-006** — /v1/chat/completions 인증 + Tool 보안 강화 (사내 운영 진입 / Open WebUI 통합 PR 선결)
4. **task-LG-003** — /v1/chat/completions streaming (Open WebUI 통합 PR 시점)
5. **task-MVP-001** — LangGraph migration (Agent Core 안정화)
6. **task-MVP-002** — Session SQLite (Open WebUI 운영 진입)
7. **task-MVP-003** — MCP tools 나머지 4개 (KB 통합 또는 별도)
8. **task-PROCESS-001** — §10.4 §4.3 병렬 호출 검증 항목 (메타 PR)
9. **task-SEC-001** — LiteLLM pin 상향 (LiteLLM 3.14 지원 또는 Python downgrade 결정 후)
10. **task-MVP-004 / 005 / 009** — 운영·다국어·MCP 분리 (필요 시점)
11. **task-006** — Python 3.14 CI matrix (Stage 3 진척 후)
12. **task-POC-004** — `.env` 자동 로드 pytest 격리 (CI 통과 안정화)
13. **task-POC-001** — 1-B/2-A/2-B Claude judge 채점 (PoC baseline 합산 점수)
14. **task-POC-002** — error catalog 5 → 10 확장
15. **task-POC-003** — 4 모델 매트릭스 비교
16. **deferred 항목들** — 발견 시점에 처리

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
