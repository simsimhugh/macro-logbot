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

### ~~task-LG-002 — LLMGateway base_url/api_key override (사내 LLM 통합 선결)~~
- **출처**: PR #8 architect (issuecomment-4479740071) WARN
- **scope**: `LLMGateway.__init__` 에 `base_url: str | None = None`, `api_key: str | None = None`, `custom_llm_provider: str | None = None` 인자 추가 + 대응 env `MACRO_LOGBOT_LLM_BASE_URL` · `MACRO_LOGBOT_LLM_API_KEY` 흡수 + `acompletion` 호출 시 forward. spec §7.3 직접 인용.
- **suggested branch**: `feat/gateway-internal-llm-hooks`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **size estimate**: client.py ~30 lines + tests ~40 lines
- **priority**: **high** — 사내 LLM endpoint 통합 PR 시작 전 선결
- **처리 완료**: 본 PR 안 처리 완료 (`feat/gateway-internal-llm-hooks`). 확인용 마커.

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

### task-SEC-009 — Supply chain hardening (mirror 신뢰 검증 + image digest pinning)
- **출처**: PR #15 security-reviewer (issuecomment-4484123961) MEDIUM (A08) + LOW (A09)
- **scope**: (a) `.env.example` 또는 spec §8.4 에 사내 registry/mirror **허용 도메인 명시** + runbook 검증 가이드. (b) pip hash pinning (`pip install --require-hashes` 또는 `--trusted-host` 명시) 또는 lockfile 도입. (c) `open-webui:main` floating tag → `@sha256:<digest>` digest pinning. (d) Dockerfile `ENV PIP_INDEX_URL` 의 runtime leak — task-OPS-001 multi-stage 시 runtime stage 에서 제거.
- **suggested branch**: `chore/supply-chain-hardening`
- **reviewer scope**: 일반 (보안 중요)
- **priority**: medium — 사내 운영 진입 전 (task-LG-002 / task-SEC-007 와 묶음)

### task-SEC-010 — Message content length cap + endpoint body size cap (DoS 가드)
- **출처**: PR #20 security-reviewer WARN-MED-1 (A03) + WARN-LOW-2 (A04) + PR #23 security WARN-2 (A04)
- **scope**:
  - `src/macro_logbot/gateway/models.py` `Message.content` 에 `Field(max_length=1_000_000)` 추가. 거대 LLM 응답 (악성 / 오작동) 또는 user-controlled tool output blob 이 row 에 들어가 SQLite query latency / disk fill 유발하는 표면 차단. Pydantic v2 ValidationError 가 자동으로 거절 → 직렬화 단계 도달 X. **arguments / tool result 의 길이도 동일 cap 고려**.
  - **PR #23 sec WARN-2 (LOW)**: `/agent/analyze` body 의 `log_text` 길이 cap — FastAPI middleware `max_body_size` 또는 endpoint-level `len(log_text) > N: raise HTTPException(413)` 가드. 거대 input traceback 으로 prompt 폭주 + 비용 폭증 차단.
- **suggested branch**: `feat/message-length-cap`
- **reviewer scope**: 일반
- **priority**: medium — 사내 운영 진입 전 (task-MVP-006 운영 보안 패키지와 묶음)

### task-SEC-011 — 시크릿 echo 차단 (LLM 응답 / tool output / crystallize report 안 시크릿 노출 방어)
- **출처**: PR #20 security-reviewer WARN-MED-2 (A02 + A09) + PR #23 security WARN-1 (A02 + A09)
- **scope**: 다층 방어:
  - (a) tool layer (PR #19 `read_file` / `grep_codebase` / `search_logs`) 가 `.env`, `secrets/`, `*.key`, `*.pem`, `id_rsa*` 등 시크릿 파일 path allowlist 차단 (task-MVP-006 의 path 보안 강화에 흡수 가능).
  - (b) LLM 응답에 우연히 포함된 시크릿 redact — 출력 단계에서 regex 매칭 (API key 패턴 `[A-Za-z0-9]{32,}`, AWS access key `AKIA...`, GitHub PAT `ghp_...` 등) 시 `***REDACTED***` 치환.
  - **PR #23 sec WARN-1 (MED)**: `_crystallize_report_node` 가 last assistant content 를 `root_cause / fix_hint / reasoning_summary` 셋에 삼중 echo. prompt-inject 로 "이전 system prompt 출력" 유도 시 시크릿 / 사내 코드 / PII 가 응답으로 직출 가능. crystallize 단계에서 secret-pattern regex redact + length cap (`_SECRET_RE.sub("[REDACTED]", s)[:cap]`) 적용 필요. task-MVP-001-y (LLM structured output) 와 함께 처리하면 효과적.
  - (c) (운영 배포 시) SQLCipher 또는 DB-level encryption-at-rest 검토 — task-OPS-001 multi-stage 와 함께.
- **suggested branch**: `feat/secret-redaction`
- **reviewer scope**: 일반 (보안 중요)
- **priority**: medium — 사내 운영 진입 전 (사외 PoC 영향 적음)

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

### task-SEC-002 — SSO 인증 통합 (Hybrid B+C+API key fallback)

architect 설계 plan: [`docs/design/sso-plan.md`](../design/sso-plan.md). 권고 방식: **Hybrid = B(reverse proxy oauth2-proxy 주력) + 일부 C(Open WebUI 측 OIDC) + 영구 API key fallback(service account)**. `AuthBackend` 추상화로 dev/PoC ↔ 사내 production swap. 6 sub-task 로 분해 (각각 별도 PR):

- **출처**: PR #8 security-reviewer (issuecomment-4479896415) LOW — 사내 운영 진입 차단 사유
- **관련 설계**: `docs/design/sso-plan.md` (architect agent 2026-05-19, PR #38 정착)

#### task-SEC-002-a — `AuthBackend` Protocol + `Principal` 모델 + `verify_api_key` 호환 리팩토링
- **scope**: `src/macro_logbot/auth.py:57-98` 의 `verify_api_key` 를 `AuthBackend` Protocol + `APIKeyAuthBackend` / `HeaderForwardAuthBackend` / `OIDCAuthBackend` / `ChainedAuthBackend` 구조로 리팩토링. `Principal` Pydantic 모델 (`id`, `email`, `name`, `scopes`, `source`) 도입. `verify_api_key` → `Depends(get_principal)` 교체 (backward-compat 유지). 기존 `tests/test_auth*.py` 호환 + Principal 반환 검증.
- **suggested branch**: `feat/auth-backend-abstraction`
- **reviewer scope**: 일반 (전체 reviewer cycle — security 중요)
- **size estimate**: src ~150 lines + tests ~120 lines
- **priority**: **high** — 사내 운영 진입 / Open WebUI 통합 PR 선결

#### task-SEC-002-b — `HeaderForwardAuthBackend` + scope 분리
- **scope**: `HeaderForwardAuthBackend` 구현 — `MACRO_LOGBOT_AUTH_TRUSTED_PROXY_IPS` env (CIDR 리스트) 로 spoofing 방어. proxy IP 외 `X-Forwarded-User` 헤더 무시 + WARN 로깅. `Principal.scopes` 에 `["chat","analyze"]` (사용자) / `["webhook"]` (service account) / `["admin","kb.verify"]` (관리자) 분리. 엔드포인트별 scope 가드 적용.
- **suggested branch**: `feat/auth-header-forward-backend`
- **reviewer scope**: 일반 (전체 reviewer cycle — security 중요)
- **size estimate**: src ~80 lines + tests ~100 lines
- **priority**: **high** — task-SEC-002-a 완료 후

#### task-SEC-002-c — `OIDCAuthBackend` (Authlib) + JWKS 검증
- **scope**: `OIDCAuthBackend` 구현 — `Authlib` JWKS 검증. `MACRO_LOGBOT_OIDC_ISSUER` + `MACRO_LOGBOT_OIDC_JWKS_URL` env. JWKS 캐시 600s (Authlib 기본). Samsung 사내 IdP protocol (SAML vs OIDC vs 자체) 확정 후 진행 — RISK-SSO-1.
- **suggested branch**: `feat/auth-oidc-backend`
- **reviewer scope**: 일반 (전체 reviewer cycle — security 중요)
- **size estimate**: src ~100 lines + tests ~100 lines
- **priority**: **high** — 사내 IdP protocol 확정 후 즉시 (현재 차단: RISK-SSO-1)

#### task-SEC-002-d — `sessions.owner_principal` 컬럼 + IDOR 회피 + session principal scoping
- **scope**: `sessions` 테이블에 `owner_principal TEXT NOT NULL DEFAULT 'anonymous'` 컬럼 추가 (기존 row 마이그레이션 안전). `SQLiteSessionStore.get(session_id, principal)` 시그니처 확장 — owner mismatch 시 `None` 반환 (404 동일 처리, IDOR 회피). `AgentState` 에 `principal: Principal | None` 필드 추가. task-MVP-002-x 와 묶음 권장.
- **suggested branch**: `feat/session-principal-scoping`
- **reviewer scope**: 일반 (전체 reviewer cycle — security 중요)
- **size estimate**: src ~60 lines + tests ~80 lines + 마이그레이션 SQL 1개
- **priority**: **high** — 다중 사용자 운영 진입 전 (task-SEC-002-a 완료 후)

#### task-SEC-002-e — `audit.py` 모듈 + 이벤트 로깅
- **scope**: 신규 `src/macro_logbot/audit.py` — JSON logger + `audit.log_event(event_type, principal, details)` API. 이벤트: `auth.success`, `auth.failure`, `session.access`, `session.access_denied`(IDOR), `kb.write`. PII 마스킹: `email_domain_only()`, `principal_hash()` 헬퍼. 로그 sink: stdout JSON line + optional `MACRO_LOGBOT_AUDIT_LOG_PATH` env 파일.
- **suggested branch**: `feat/audit-logging`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **size estimate**: src ~120 lines + tests ~80 lines
- **priority**: medium — task-SEC-002-b 완료 후

#### task-SEC-002-f — `docker-compose.internal.yml` + oauth2-proxy + spec/DEPLOYMENT 문서 갱신
- **scope**: `docker-compose.internal.yml` 추가 — oauth2-proxy 컨테이너 + Open WebUI `WEBUI_AUTH_TRUSTED_EMAIL_HEADER`. `DEPLOYMENT.md` 사내 운영 절차 갱신 (env 비교표 4개 행 추가, SSO 통합 절차 섹션). `docs/design/02-설계문서.md` §5.1 / §12 보안 검증 갱신 (Trust boundary 표 + spoofing 방어 명시). production gate env `MACRO_LOGBOT_AUTH_BACKEND` 기본값 `chained` 설정.
- **suggested branch**: `feat/internal-compose-sso`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **size estimate**: compose ~50 lines + docs ~100 lines
- **priority**: **high** — 사내 운영 manifest 투입 직전 (task-SEC-002-b/d 완료 후)

### ~~task-SEC-003 — LLMGateway.complete kwargs allowlist~~
- **출처**: PR #8 security-reviewer (issuecomment-4479896415) LOW
- **scope**: `LLMGateway.complete(**kwargs)` 자유 패스스루 → allowlist (`temperature`, `max_tokens`, `top_p`, `stop`, `tools`, `tool_choice` 등) 외 kwargs `ValueError`. `task-LG-002` (base_url/api_key override) 작업 시 동일 시그니처를 건드리므로 함께 도입 권고.
- **suggested branch**: task-LG-002 와 묶음 (`feat/gateway-internal-llm-hooks`)
- **priority**: medium — task-LG-002 시점에 함께
- **처리 완료**: 본 PR 안 처리 완료 (`feat/gateway-internal-llm-hooks`). 확인용 마커.

### task-PROCESS-001 — §10.4 검증 항목에 §4.3 병렬 호출 준수 추가
- **출처**: PR #9 architect (issuecomment-4479796124) COMMENT + verifier (issuecomment-4479834661) follow-up 권고
- **scope**: `docs/process/03-개발-프로세스.md` §10.4 검증 방법에 (1) "비-meta PR 의 CR/Sec/Test comment timestamp 가 거의 동일 시각 (병렬 호출 흔적)" (2) "§3.6 verifier 호출 트리거 표현 일관성 (CR/Sec/Test 병렬 통과 후)" 두 항목 추가.
- **suggested branch**: `docs/process-parallel-verification`
- **reviewer scope**: §9 메타 변경 (architect+verifier 단독)
- **size estimate**: docs 5~10 lines
- **priority**: medium — Stage 3 다음 PR 들이 본 정책 따라 진행되는지 검증 가능해야 함

### ~~task-MVP-001~~ — LangGraph state graph 마이그레이션 ✅ **PR #18 머지**
- **처리 PR**: PR #18 (`feat/agent-langgraph`) — `src/macro_logbot/agent/core.py` 가 LangGraph `StateGraph` + 3 노드 (llm_call / route / execute_tools). `run_agent` 시그니처 100% 유지, 호출부 변경 0.
- **잔여**: spec §5.2 의 `intake` / `crystallize_report` / `followup` 3 노드는 task-MVP-001-x 후속.

### ~~task-MVP-001-x~~ — spec §5.2 잔여 3 노드 (intake / crystallize_report / finalize) ✅ **PR #23 머지**
- **처리 PR**: PR #23 (`feat/agent-graph-full`) — `intake` / `crystallize_report` / `finalize` 3 노드 추가, spec §5.2 6 노드 완성 (single-turn). `Report` / `Location` Pydantic 모델 도입. `AgentRunResult.report` 필드 추가. `/agent/analyze` 응답에 `report` / `session_id` 필드 포함.
- **잔여**: `crystallize_report` 의 LLM 추가 호출 정확 추출 → task-MVP-001-y. multi-turn follow-up (`followup` 노드) → task-MVP-004.

### task-MVP-001-y — `crystallize_report` LLM 추가 호출로 정확 JSON 추출 + Report 스키마 spec §5.4 정합 + design.md mermaid sync + regex robustness
- **출처**: PR #23 의도된 단순화 + PR #23 architect WARN-2/3 (MED) + code-reviewer WARN-3/4/5/6/7 (MED/LOW) + test-engineer WARN-3 (MED)
- **scope**:
  - `_crystallize_report_node` 에서 LLM 추가 호출 (structured output 또는 prompt engineering) 으로 `root_cause` / `fix_hint` / `location` 를 본문에서 정확하게 JSON 추출. 또는 LiteLLM structured output (`response_format=Report`) 강제. `confidence` 도 LLM 평가 기반으로 산출.
  - **arch WARN-2 (MED)**: `Report` 스키마에 spec §5.4 line 205 의 `related_code_refs: list[str]` 추가 — 현재 `location` (단일) + `fix_hint` 만으로는 spec §5.4 와 비대칭. `fix_hint` 는 §5.5 KB ArchivedCase 필드라 §5.4 와 mix 됨 — task-MVP-002-x (Session report_json 컬럼 확장) 와 함께 모델 분리 결정 (Report vs ArchivedCase 의도 명문화).
  - **arch WARN-3 (MED)**: `docs/design/02-설계문서.md` §5.2 mermaid (line 155-165) 에 `finalize` 노드 명시 추가. 현재 mermaid `crystallize → END` 와 구현 `crystallize → finalize → END` 불일치 — design.md mermaid 보강 (§9 메타 PR 가능).
  - **code-r WARN-3 + test WARN-3 (MED/LOW)**: `_LOCATION_RE` regex robustness — (a) URL false-positive (`http://...a.py:80` → `Location(file='//.../a.py', ...)` 매칭) 차단 (`(?<![:/])` lookbehind), (b) 첫 매칭만 반환 정책 명시 또는 `findall` 후 가장 가까운 path 선택, (c) `../` 상대 경로 변형 sanitize.
  - **code-r WARN-4 (MED)**: `Location.function: str = ""` default 가 KB write 경로에서 `function=""` ArchivedCase 누수 표면 — model_validator 또는 KB-context 강제 검증.
  - **code-r WARN-5 (MED)**: `Report` 의 3 필드 (root_cause / fix_hint / reasoning_summary) 가 동일 텍스트 복사 → 응답 payload 부풀림. LLM structured output 으로 분리 추출 시 자동 해소. `AgentAnalyzeResponse.report` Field description 에 "MVP placeholder" 가시화 권장.
  - **code-r WARN-6 (LOW)**: `_intake_node` SRP 분해 — `_build_intake_hint(record)` + `_already_has_intake(msgs)` 헬퍼 분리.
  - **code-r WARN-7 (LOW)**: `Location` layer separation — `agent` → `knowledge_base` import 역전 (DIP 시각). `macro_logbot/models/location.py` 상위 모듈 또는 별도 shared 패키지 검토. 현재는 architect WARN-1 의 KB canonical 결정 유지 OK.
- **suggested branch**: `feat/crystallize-llm-extract`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **priority**: medium — PoC 채점 품질 향상 시점 (task-POC-001 이후)

### ~~task-MVP-002~~ — Session persistence (SQLite, spec §5.4) ✅ **PR #20 머지**
- **처리 PR**: PR #20 (`feat/session-sqlite`) — `SQLiteSessionStore` + `SessionStore` Protocol 도입. `src/macro_logbot/session/store.py`. messages 직렬화 (단일 table). `InMemorySessionStore` 유지 (fallback/test).
- **잔여**: `tool_history` / `follow_up_messages` / `report` 컬럼 확장 → task-MVP-002-x. endpoint 통합 → task-MVP-004.

### task-MVP-002-x — Session 확장 컬럼 (event_id / status / tool_history / follow_up_messages / report) + 코드/테스트 잔여
- **출처**: PR #20 의도된 단순화 + architect WARN-2/4 (LOW) + code-reviewer WARN-3 (LOW) + test-engineer WARN-2/3/4 (MED/LOW)
- **scope**: `sessions` 테이블에 spec §5.4 line 199~205 의 잔여 5개 필드 추가:
  - `event_id TEXT` — Log Event 와의 1:N 관계 키 (spec §5.4 line 201).
  - `status TEXT` — 분석 진행 상태 (`intake/analyzing/reported/followup` — §5.2 노드 상태와 연동).
  - `tool_history_json TEXT` — `{ tool_name, args, result, ts }` 리스트.
  - `follow_up_messages_json TEXT` — 1차 리포트 이후 대화.
  - `report_json TEXT` — `{ root_cause, related_code_refs[], confidence, reasoning_summary }`.
  - **arch WARN-4 (LOW)**: WAL mode 설정 (`PRAGMA journal_mode=WAL`) 을 매 connection 마다가 아닌 첫 init 1회로 최적화 (idempotent 라 안전, 단순한 마이크로 최적화).
  - **code-r WARN-3 (LOW)**: Protocol/구현 메서드의 `id: str` 인자가 built-in `id()` 를 가림. `session_id: str` 으로 통일 (외부 caller 0 이라 무위험, 본 task 컬럼 추가와 함께 묶음).
  - **test WARN-2 (MED)**: plain Message (`role/content` 만, tool_calls=None) round-trip 단위 테스트 추가 — fetched 후 `tool_calls is None`, `tool_call_id is None`, `name is None` 명시 assert. Pydantic 모델 변경 시 회귀 방어.
  - **test WARN-3 (LOW)**: `test_sqlite_store_persistence` 의 "프로세스 재시작 시뮬레이션" 주석을 "같은 프로세스 내 두 인스턴스 간 데이터 가시성 검증 (프로세스 격리는 별도 통합 테스트)" 로 정정.
  - **test WARN-4 (LOW)**: `test_sqlite_store_protocol` 에서 `mem_store` 도 실제 create/get/delete 호출 추가 (현재 isinstance 만).
- **suggested branch**: `feat/session-columns`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **priority**: medium — multi-turn 분석 리포트 저장 필요 시점

### task-MVP-002-y — Session retention 30일 cleanup
- **출처**: PR #20 architect WARN-4 (LOW) — spec §5.4 line 209 `Retention: 분석 완료 후 30일 보관` 정책 미구현
- **scope**: `SQLiteSessionStore` 에 `cleanup_expired(before: datetime)` 또는 `cleanup_older_than(days: int)` 메서드 추가. FastAPI startup hook 또는 별도 cron 으로 일 1회 호출. 검증셋 export 흐름은 별도 정의 필요.
- **suggested branch**: `feat/session-retention`
- **reviewer scope**: 일반
- **priority**: low — 사외 PoC 단계 무영향, 사내 운영 진입 전

### ~~task-MVP-003~~ — MCP tools 나머지 4개 (spec §5.3) ✅ **PR #19 머지**
- **처리 PR**: PR #19 (`feat/tools-remaining-4`) — `git_log`, `find_test_history`, `get_environment_info`, `retrieve_similar_cases` 4 함수 + 4 ToolSpec 추가, spec §5.3 9 tools 인터페이스 완성. 출력 키도 spec §5.3 표 (`test_runs[]`, `similar_cases[]`) 와 정합.
- **잔여**: `find_test_history` 는 사외 PoC mock (`{"test_runs": []}`), `retrieve_similar_cases` 는 KB §5.5 미구현 placeholder (`{"similar_cases": []}`) — 실제 연동은 task-MVP-003-x.

### task-MVP-003-x — `find_test_history` 사내 DB 연동 + scope 인자 처리
- **출처**: PR #19 의도된 단순화 (mock + placeholder) + architect WARN-3 + security WARN-3 + code-reviewer WARN-5
- **scope**:
  - `find_test_history` — 사내 MACRO test DB 접속 client 도입 + 실제 test_id 별 run history 반환. 사내 운영 진입 시점. `limit` 인자 실제 적용.
  - ~~`retrieve_similar_cases` — spec §5.5 Knowledge Base (`archived_cases` 테이블) 구현 후 keyword/signature 매칭 (Phase 1) 또는 벡터 임베딩 (Phase 2) 검색 로직 통합. **WARN-3 (sec MED)**: `error_signature` 길이 cap (`_MAX_SIGNATURE_LEN`), `top_k` 범위 (1..50) 검증.~~ **PR #21 처리 완료** — `SQLiteKBStore` Phase 1 + 보안 가드 도입.
  - **WARN-3 (arch LOW + code-r WARN-5)**: `get_environment_info` 의 `scope` 인자가 현재 silent 무시. ToolSpec description 에 "현재 무시됨 — 향후 필터링용 인터페이스 호환" 으로 명시하거나 실제 필터 (e.g. `scope="packages"` 만 반환) 구현.
- **suggested branch**: `feat/tools-real-integration`
- **reviewer scope**: 일반 (전체 reviewer cycle)
- **priority**: medium — `find_test_history` 는 사내 운영 진입 시점

### task-KB-001 — KB Phase 2 벡터 임베딩 (RAG / case-based reasoning) + WARN-1/2 보강 + 검색 robustness
- **출처**: PR #21 의도된 단순화 (Phase 1 keyword LIKE 만) — spec §5.5 Phase 2 선택 항목 + architect WARN-1/2 (MED) + code-reviewer WARN-4 (LOW) + security LOW-1 (LIKE wildcard) + test-engineer WARN-3 (정책 결정)
- **scope**:
  - `SQLiteKBStore.search` 를 벡터 임베딩으로 업그레이드. sentence-transformers 또는 sqlite-vec / pgvector 평가 후 retrieval scoring 개선. Phase 1 LIKE fallback 유지.
  - **architect WARN-1 (MED)**: spec §5.5 의 `verified-master` 우선 부여 — `ORDER BY CASE source WHEN 'verified-master' THEN 0 WHEN 'production' THEN 1 ELSE 2 END, confidence DESC` 적용. 동일 confidence 케이스의 source tie-break 결정.
  - **architect WARN-2 (MED)**: Phase 1 LIKE 검색의 정규화 layer 추가 — signature token split + OR 매칭 (예: `AttributeError:NoneType.x_access` → `AttributeError` + `NoneType` + `x_access` 각각 substring), 또는 별도 `category` + `error_type` 컬럼 분리. 운영 단계에서 정확한 동일 정규화 표식 매칭이 거의 무력화되는 문제 해소.
  - **code-r WARN-4 / sec LOW-1 / test WARN-3 (LOW)**: 검색 robustness — (a) 빈 query 시 `[]` 반환 (현재 LIKE '%%' 전체 매칭) 정책 결정 + 테스트, (b) `%` / `_` 메타문자 ESCAPE 처리 (literal 매칭), (c) test-only `test_search_empty_query` / `test_search_sql_wildcard_not_expanded` 동작 고정.
- **suggested branch**: `feat/kb-vector-search`
- **reviewer scope**: 일반 (전체 reviewer cycle — 신규 외부 dep 포함)
- **priority**: low — PoC validation 후 (KB 누적 케이스 충분해진 시점)

### ~~task-KB-002~~ — `archived_cases` populating 흐름 (분석 완료 후 자동 add) ✅ **PR #24 머지**
- **처리 PR**: PR #24 (`feat/session-endpoint-kb-archive`) — `env MACRO_LOGBOT_KB_AUTO_ARCHIVE=true` 활성화 시 `/agent/analyze` 가 분석 완료 후 `_kb_auto_archive()` 호출 → `SQLiteKBStore.add(ArchivedCase)`. `source="poc"`, `case_id=uuid4()`, `error_signature=root_cause[:80]`, `location` None 이면 placeholder `Location(file="unknown", line=1)` 사용.
- **잔여**: 중복 case_id upsert/ignore 정책 → task-KB-001 또는 task-KB-002-x. verifier 승격 (`verified-master`) hook → 별도.

### task-KB-002-x — KB write 품질 (error_signature 정규화 + Location placeholder 처리)
- **출처**: PR #24 architect WARN-3 (LOW) + WARN-4 (LOW)
- **scope**:
  - **WARN-3 (LOW)**: `error_signature = root_cause[:80]` 단순 truncate → 자연어 본문 prefix 가 들어가 spec §5.5 line 220 `정규화 표식` (예: `"AttributeError:NoneType.x_access"`) 의도와 다름. KB retrieval 매칭 효과 약화. task-MVP-001-y 의 LLM structured output 으로 정규화 signature 추출 후 흡수, 또는 별도 lightweight 정규화 함수 (traceback 마지막 줄 추출 + `<ExceptionType>:<attr/op>` 정규식).
  - **WARN-4 (LOW)**: `report.location is None` 일 때 placeholder `Location(file="unknown", function="", line=1)` 으로 archive — KB retrieval 시 의미 없는 row noise. 옵션: (A) location None 이면 archive skip (가장 안전, 권고), (B) `Location.line: int | None = None` 허용 + KB schema NULLABLE (spec §5.5 line 220 정합 손상 가능).
  - 중복 case_id upsert/ignore 정책 — `INSERT OR REPLACE` (덮어쓰기) vs `INSERT OR IGNORE` (skip) + `KBStoreDuplicateError` raise 결정 후 docstring 명문화.
- **suggested branch**: `feat/kb-write-quality`
- **reviewer scope**: 일반
- **priority**: medium — task-MVP-001-y (정확 JSON 추출) 후 또는 묶음

### task-KB-003 — SQLite store 공통 base 추출 (DRY)
- **출처**: PR #21 code-reviewer WARN-1 (MED) — KB + SessionStore 의 `_connect`/`_init_db`/chmod 패턴 거의 동일
- **scope**: `src/macro_logbot/persistence/sqlite_base.py` (또는 `_SQLiteStoreBase`) 추출 — `__init__(db_path)` + `_connect()` + `_apply_owner_only_perms()` 공유. WAL pragma + chmod 0o600 + `-wal`/`-shm` suffix loop + `contextlib.suppress(OSError)` 패턴 중복 제거. 각 store 는 `_CREATE_TABLE_SQL` + CRUD 메서드만 정의. KBStore/SessionStore Protocol 의미 보존 (Protocol = 인터페이스, base class = 구현). 향후 3번째 store 추가 시 보안 가드 누락 방지.
- **suggested branch**: `refactor/sqlite-store-base`
- **reviewer scope**: 일반
- **priority**: low — 3번째 store 추가 시점에 의미 ↑

### task-SEC-012 — `MACRO_LOGBOT_KB_PATH` env path containment + symlink guard
- **출처**: PR #21 security WARN-MED-1 (A01 Broken Access Control / A05 Misconfiguration)
- **scope**: `MACRO_LOGBOT_KB_PATH` env 가 절대 path 그대로 수용 — `_safe_resolve` 의 cwd containment 미적용. `MACRO_LOGBOT_DATA_ROOT` (또는 default `.macro-logbot`) 도입 후 KB path 가 root 밖이면 fail-closed. symlink 추적 후 root 외부 가는 경로 차단. 운영 진입 패키지 (task-SEC-007/009/011) 와 묶음.
- **suggested branch**: `feat/kb-env-containment`
- **reviewer scope**: 일반 (보안 중요)
- **priority**: medium — 사내 운영 진입 전 (task-SEC-007 / task-SEC-011 와 묶음)

### task-TEST-001 — MCP tools 테스트 보강 (branch coverage + schema 내용 검증)
- **출처**: PR #19 test-engineer (WARN-5/6/7/8/9) + architect WARN-4 (LOW) + code-reviewer WARN-6 (LOW)
- **scope**:
  - **WARN-5 (MED)**: `subprocess.run` `OSError`/`TimeoutExpired` 분기 미테스트 — `grep_codebase` / `git_blame` / `search_logs` / `git_log` 4건. `unittest.mock.patch` 로 raise 시뮬레이션.
  - **WARN-6 (MED)**: `git_blame` success path (`{"blame": ...}` 반환) 미테스트. `_init_git_repo` + commit 후 호출.
  - **WARN-7 (MED)**: `get_environment_info` `metadata.PackageNotFoundError` 분기 (`"not installed"` 반환) 미테스트.
  - **WARN-8 (MED) — 이미 PR #19 fix**: ✅ `search_logs` ToolSpec `max_results` property 누락 fix. **잔여**: `test_tools_registry.py` 가 각 entry 의 `name` ↔ `TOOL_REGISTRY.keys()` 매칭 + `required` 필드 컨텐츠 검증 (현재 shape 만).
  - **WARN-9 (LOW)**: `grep_codebase` / `search_logs` 파싱 예외 경로 (`parts < 3`, `ValueError on line_no`) 미커버.
  - **arch WARN-4 (LOW)**: edge-case — `git_log limit=0`, `find_test_history.limit` / `retrieve_similar_cases.top_k` 인자 실제 적용 후 컨트랙트 검증.
  - **code-r WARN-6 (LOW)**: `_ENV_INFO_PACKAGES` 하드코딩 — `metadata.distributions()` 로 dynamic 조회 + denylist, 또는 docstring 에 "pyproject.toml sync 필요" 명시.
  - **PR #21 test WARN-6 (LOW)**: `_kb_store` singleton 격리 — 각 KB tool 테스트가 `monkeypatch.setattr(builtin_mod, "_kb_store", None)` 패턴 반복. `autouse=True` fixture 로 추출하여 일관 적용 + stale singleton 회피.
  - **PR #23 test WARN-4 (MED)**: `test_full_graph_runs_all_6_nodes` 가 실제 노드 호출 증명 X — 결과만 검증. 테스트 이름 수정 (`test_full_graph_happy_path_with_tool_call`) + `_finalize_node` non-no-op 진입 시 실 호출 검증.
  - **PR #23 test WARN-5 (MED)**: endpoint `/agent/analyze` ↔ real graph 통합 케이스 추가 — `run_agent` patch 제거하고 `gateway.complete` 만 mock 한 케이스 1건으로 endpoint 직렬화 + 실 graph flow 동시 검증.
- **suggested branch**: `test/tools-branch-coverage`
- **reviewer scope**: test-engineer 단독 가능 (test-only PR, src 변경 없음 — code-r WARN-6 fix 가 src 포함시 일반 cycle)
- **priority**: medium — 사내 운영 진입 전 운영 분기 검증 필요

### ~~task-MVP-004~~ — /agent/analyze session 통합 + SessionStore.update semantic 통일 ✅ **PR #24 머지**
- **처리 PR**: PR #24 (`feat/session-endpoint-kb-archive`) — `/agent/analyze` 가 optional `session_id` 받아 `SQLiteSessionStore` 에서 messages 로드 → graph 실행 → messages 저장 → 응답에 `session_id` 반환. `SQLiteSessionStore.update` 가 upsert (INSERT OR REPLACE) 로 변경 — `InMemorySessionStore` 와 동일 의미. `test_sqlite_store_update_nonexistent_is_upsert` 테스트로 계약 명문화.
- **잔여**: singleton thread-safety (`_get_session_store` / `_get_kb_store` lock 보호 + `reset_*` helper) → task-MVP-004-x. `AgentState` 에 `session_id` / `event` / `pending_tool_calls` / `tool_results` 4 필드 추가 → task-MVP-004-x.

### ~~task-MVP-004-x~~ — singleton thread-safety + AgentState session_id/event_id 필드 추가 ✅ **PR #26 머지**
- **처리 PR**: PR #26 (`feat/singleton-thread-safety-and-agentstate`) — `_get_session_store` / `_get_kb_store` double-checked locking (`threading.Lock`) 적용. `_reset_singletons_for_test()` helper 추가 (테스트 격리). `AgentState` 에 `session_id: str | None` + `event_id: str | None` 추가. `run_agent` 시그니처 확장 (backward-compat). `/agent/analyze` 가 `session_id=session.id` 를 graph state 로 전달.
- **잔여**:
  - principal scoping (session IDOR owner 확인) → task-SEC-002 묶음.
  - `pending_tool_calls: list[ToolCall]` / `tool_results: list[ToolResult]` → spec §5.2 잠정 필드, LangGraph node 함수 시그니처와 중복 — 구현 미정.
  - `event: LogEvent` → `event_id: str | None` MVP 단순화, LogEvent.id 통합은 task-MVP-005 (intake 한국어) 후.

### task-MVP-004-y — singleton thread-safety LOW 보강 + session_id covenant + pre-existing flaky test fix
- **출처**: PR #26 architect WARN-2/3 (LOW) + code-reviewer WARN-1/2/4 (MED/LOW) + security WARN-3/4/5 (MED/LOW) + test-engineer WARN-2 (LOW) + PR #20 머지 후 pre-existing flaky
- **scope**:
  - **arch WARN-2 + code-r WARN-1 (MED)**: `_get_kb_store` env read 가 lock 밖 — thread A stale path race. lock 안 재확인 또는 docstring 에 "env 는 process lifetime 불변" 명문화.
  - **arch WARN-3 (LOW)**: `_reset_singletons_for_test()` 가 lock 없이 None 대입. docstring 에 "main thread / 테스트 셋업 전용" 명문화.
  - **code-r WARN-2 (MED)**: `run_agent()` 의 initial_state 채움 라인 (`"session_id": session_id`, `"event_id": event_id`) 누락 회귀 방어 unit test. mock `_llm_call_node` 가 받은 state 캡쳐 → session_id 확인.
  - **code-r WARN-4 / test WARN-2 (LOW)**: `threading.Barrier(10)` 추가됐지만 lock 제거 시 fail 보장 (mutant test) 까진 검증 X. PEP 703 free-threaded 환경 대비.
  - **sec WARN-3 (MED)**: agent 노드 함수가 `state["session_id"]` 를 LLM prompt 로 echo 하지 않게 명시 covenant — 주석 + sanitizer (crystallize_report 에서 root_cause 에 session_id 매칭 시 redact). 또는 RunContext 별도 분리.
  - **sec WARN-4 (LOW)**: `session_id[:8]` 부분 로깅 충돌 (uuid4 first 32 bit birthday ~65k) — 12자 또는 HMAC-truncated.
  - **sec WARN-5 (LOW)**: `event_id` covenant 문서화 (LogEvent.id 통합 시점에 sanitizer 동시 적용).
  - **pre-existing flaky** (`tests/test_session_store.py::test_update_refreshes_updated_at`): Pydantic v2 `Field(default_factory=_now)` 가 callable reference 캐시 — `monkeypatch.setattr(store_module, "_now", ...)` 우회. 해결: `time.sleep(0.01)` + monkeypatch 제거, 또는 `Session.__init__` 에서 `_now()` 명시 호출, 또는 `freezegun` 도입.
- **suggested branch**: `chore/singleton-and-flaky-test-fix`
- **reviewer scope**: 일반
- **priority**: low — pytest deselect 1건 잔존 + 보안 covenant 는 노드 함수가 session_id read 안 하면 0 위험.

### task-MVP-005 — intake parser 다국어 level 지원
- **출처**: PR #11 MVP 의도된 단순화
- **scope**: 한국어 등급 (`경고`/`오류`/`치명`) regex 추가. 사내 MACRO 로그 포맷 결정 후 정확한 패턴 매칭.
- **priority**: low — 사내 MACRO 로그 샘플 확보 후

### task-MVP-006 — Tool 보안 강화 (symlink 우회 + control-char strip + int input cap)
- **출처**: PR #11 MVP 의도된 단순화 + PR #19 security-reviewer (WARN-1/2/5)
- **scope**:
  - `_safe_resolve` 가 symlink 추적 후 cwd 외부로 가는 경로 차단. `Path.cwd()` 자체가 symlink 인 환경의 edge case 처리.
  - `subprocess` argument injection 추가 검증.
  - **WARN-2 (MED)**: `git_log`/`grep_codebase`/`search_logs` raw output 의 control char (`\x00-\x08\x0b-\x1f\x7f`) / ANSI escape strip — LLM prompt injection 표면 제거. `splitlines()` → `split("\n")` + ctrl char regex strip.
  - **WARN-5 (LOW)**: integer 인자 입력 cap 통일 — `git_log.limit` (≤200), `read_file.max_lines`, `grep_codebase.max_results`, `search_logs.max_results`, `find_test_history.limit`, `retrieve_similar_cases.top_k`. OOM/cost 가드.
- **priority**: medium — `task-SEC-002` (인증) 와 함께 운영 진입 전

### task-MVP-006b — `platform.platform()` 사내 hostname/kernel-build 누출 제거
- **출처**: PR #19 security-reviewer (WARN-4 LOW)
- **scope**: `get_environment_info` 의 `platform.platform()` 출력 (커널 빌드 / 일부 환경 hostname 포함) 을 LLM/외부 모델 provider 로 보내지 않도록 제거. `platform.release()` 의 build suffix drop 만 유지.
- **suggested branch**: `feat/env-info-redact`
- **priority**: low — 사외 PoC 영향 없음, 사내 운영 진입 직전

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

### ~~task-POC-001~~ — 1-B/2-A/2-B Claude judge 채점 (PoC) ✅ **PR #27 머지 (interim)**
- **출처**: PR #14 (feat/poc-infrastructure) — 본 PR 은 1-A 결정론 채점만.
- **처리 PR**: PR #27 (`feat/poc-claude-judge`) — `poc/scripts/claude_judge.py` 신규 (LiteLLM 사용, 신규 dep 없음). `judge_root_cause` (1-B) · `judge_tool_appropriateness` (2-A) · `judge_fix_direction` (2-B) 3 함수. `evaluate.py` 에 `--judge` / `--judge-api-key` 플래그 추가 (PR #31 에서 `--anthropic-api-key` → `--judge-api-key` 로 generic 화 + provider prefix 기반 env auto-detect). `naive_score_total` 4항목 평균 (측정 실패 None 항목 제외). `comparison.md` 컬럼 확장. 단위 테스트 6건. `seed=42` 결정성 baseline.
- **잔여**:
  - **task-POC-001-x (신규)**: 2-A/2-B 의 진짜 follow-up Q1/Q2/Q3 자동 호출 구현 (architect WARN-1 HIGH).
  - ~~**task-POC-002**~~ (5→10 case 확장) — PR #30 에서 처리 완료.

### task-POC-001-x — Follow-up 대화 (Q1/Q2/Q3) 자동 호출 + 2-A/2-B 진짜 채점
- **출처**: PR #27 architect WARN-1 (HIGH) — 현 PR 은 1차 `/agent/analyze` 응답만으로 모든 4 항목 채점. spec §6.2 (`docs/process/04-PoC-운영가이드.md:236-258`) 의 2-A/2-B 는 본래 follow-up 대화 답변 채점 의도.
- **scope**:
  - `evaluate.py` 가 1차 분석 후 같은 session_id 로 Q1/Q2/Q3 자동 follow-up 호출 (task-MVP-004 의 session 통합 PR #25 활용).
    - Q1: "어떤 추가 도구를 호출해보면 좋겠습니까?"
    - Q2: "분석 결과를 어떻게 수정하시겠습니까?"
    - Q3: "다른 가능성 있는 원인은?"
  - 2-A judge — 1차 tool_calls + Q1 답변의 추가 tool_call 합쳐 채점.
  - 2-B judge — Q2 답변의 fix 방향 + 1차 fix_hint 합쳐 채점.
  - `comparison.md` 에 follow-up 채점 vs interim 채점 분리 컬럼.
- **suggested branch**: `feat/poc-followup-questions`
- **reviewer scope**: 일반
- **priority**: medium — 본격 baseline 측정 (task-POC-002 후) 직전 처리

### ~~task-POC-002~~ — error catalog 5 → 10 확장 ✅ **PR #30 머지**
- **출처**: PR #14 — spec §10.4 / `docs/process/04-PoC-운영가이드.md` §4.2 의 Phase 1 카탈로그 10 개 명세 대비 본 PR 은 5 개만.
- **처리 PR**: PR #30 (`feat/poc-catalog-expand-10`) — E006 (AttributeError is_dead in step) · E007 (ZeroDivisionError ticks=0) · E008 (infinite loop spawn_food) · E009 (wrong assignment body insert) · E010 (UnicodeEncodeError ascii encode) yaml 5개 추가. inject/trigger 검증 완료. `tests/test_poc_catalog.py` 신규 (52 tests). `tests/test_poc_trigger.py` E008 timeout rc=2 허용 수정.
- **잔여**:
  - **task-POC-002b 신규** (architect WARN-MED): `ground_truth.location.line` 정확도 — E006 (claim 126→real 125), E007 (claim 90→real 89), E008 (claim 73→real 78) off-by-1~5. 1-A `line_match` 측정 왜곡 회피.
  - **task-POC-002c 신규** (architect WARN-LOW): file-path 단조성 (10 case 모두 snake.py) — multi-file target (예: utils.py 추출 후 inject) 으로 1-A `file_match` free 25% 제거. PR #14 이미 지적.
  - **task-POC-002d 신규** (architect WARN-LOW): E006 title "NameError" → "AttributeError" 정정. E009 traceback 발생 검증.
  - task-POC-003 (4 모델 매트릭스).

### task-POC-002b — ground_truth.location.line 정확도 (PR #30 architect WARN-MED)
- **scope**: E006/E007/E008 yaml 의 `ground_truth.location.line` 을 inject 후 실제 snake.py 라인과 일치하게 정정.
- **priority**: medium — baseline 측정 honest 평가 위해 task-POC-003 이전 권고

### task-POC-002c — multi-file target (1-A file_match free 회피)
- **scope**: PoC target 에 `utils.py` 또는 별도 module 추출 + 1~2 case 에 그쪽 inject. 모든 case file=snake.py 면 LLM 이 "snake.py" 라고만 답해도 file_match=True (free 25%). PR #14 architect 가 지적했고 PR #30 도 미해결.
- **priority**: low — baseline 측정 변별력

### task-POC-002d — E006 title 정정 + E009 traceback 검증
- **scope**: E006 title "NameError" → "AttributeError" (Python raise type 정합). E009 self.body[0] 덮어쓰기가 실제 IndexError raise 하는지 검증, 아니면 다른 traceback 패턴 명시.
- **priority**: low — cosmetic

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

### task-POC-005 — evaluate.py 를 spec §9.4 endpoint 흐름 (POST /events + polling) 으로 마이그레이션
- **출처**: PR #14 architect (issuecomment-4484079642) WARN-1
- **scope**: `poc/scripts/evaluate.py` 가 현재 `POST /agent/analyze` 단일 호출. spec `docs/design/02-설계문서.md` §9.4 + `docs/process/04-PoC-운영가이드.md` §5.3 는 `POST /events` → session_id polling → `GET /sessions/<id>/report` 흐름. **task-MVP-004 (session 통합) 완료 후** evaluate.py 마이그레이션, 또는 단기적으로 04-PoC-운영가이드 §5.3 endpoint 명세를 현행 MVP 와 일치하게 annotation.
- **suggested branch**: `feat/poc-events-endpoint` (task-MVP-004 후) 또는 `docs/poc-guide-endpoint-annotation` (단기)
- **priority**: medium — task-MVP-004 와 묶음

### task-POC-006 — judge calibration + provider env mapping dict refactor
- **출처**: PR #31 architect WARN-LOW-1 + code-reviewer LOW-1.
- **scope (calibration)**: `temperature=0 + seed=42` 결정성 best-effort 지만 Groq Llama 3.3 70B 가 0.5↔1.0 boundary 일관성 사전 검증 없음. baseline 첫 case (E001) N≥3~5 dry-run → score variance 측정 → 0.5/1.0 swing 발견 시 `evaluate.py` 에 `--judge-runs N` 옵션 + median 자동 산출.
- **scope (refactor)**: `evaluate.py:358-366` provider→env if/elif chain 을 `claude_judge._PROVIDER_ENV: dict[str, str]` 로 데이터 driven 화. 4번째 provider 추가 시점에 처리.
- **suggested branch**: `feat/poc-judge-calibration`
- **priority**: low — baseline 측정 결과 보고 0.5↔1.0 swing 빈도 확인 후 결정.

### task-SEC-013 — `.env` perms + 외부 LLM judge 송신 한계 문서
- **출처**: PR #31 security WARN-LOW-1/LOW-2.
- **scope**:
  - `.env.example` 에 `# 권장: chmod 600 .env (다른 user 읽기 차단)` 1줄 추가.
  - `poc/README.md §한계` 에 "외부 LLM judge (Groq/Anthropic/Gemini) 송신 — traceback 본문 포함. 사내 운영 데이터 송신 금지" 1줄 추가.
  - 사내 진입 시 secret store 이전 (`task-SEC-002` SSO/OAuth 묶기).
- **suggested branch**: `docs/sec-env-and-judge-boundary`
- **priority**: low — 사외 PoC 영향 0, 사내 진입 시점에 묶음 처리.

### task-INFRA-002 — Default model identifier source-of-truth 정합
- **출처**: PR #33 architect WARN-MED (issuecomment-4489144902).
- **scope**: `MACRO_LOGBOT_DEFAULT_MODEL` default 값이 3 곳에서 stale (PR #20 잔존):
  - `docker-compose.yml:30` — `${MACRO_LOGBOT_DEFAULT_MODEL:-gemini/gemini-1.5-flash}` → `gemini-2.5-flash-lite`
  - `README.md:87` — `.env` 가이드 `gemini/gemini-1.5-flash` → `gemini-2.5-flash-lite`
  - `src/macro_logbot/app.py:108` — `/v1/models` endpoint fallback `openai/gpt-4o-mini` → `gemini-2.5-flash-lite`
  - 영향: user 가 `.env` 미설정 시 docker-compose 가 존재하지 않는 1.5-flash 로 부팅, Open WebUI 모델 picker 도 `gpt-4o-mini` 표시 (실제 호출 모델과 불일치).
- **장기 (LOW)**: `DEFAULT_MODEL` 상수를 `src/macro_logbot/config.py` 단일 모듈로 추출 → evaluate.py/app.py/compose default 가 import.
- **suggested branch**: `fix/default-model-source-of-truth`
- **priority**: medium — 본 PR #33 의 짝꿍, 같은 sprint 안 처리 권고.

### task-AGENT-001 — system prompt ALSA noise filter 패턴 확장
- **출처**: PR #34 architect / code-reviewer 권고 (system prompt 강화 후속).
- **scope**: `src/macro_logbot/app.py` 의 `_ANALYZE_SYSTEM_PROMPT` 노이즈 필터 항목 (현재 ALSA / pygame init / GPU driver / locale warning) 에 사내 환경 추가 noise 패턴 보강 — 사내 stderr 에 자주 나타나는 pattern (예: glibc warnings, KDE/GNOME desktop noise, Samsung-specific tooling output) 카탈로그화. 우선 외부 PoC 회귀 없음 확인 후 사내 데이터 수집 시점에 갱신.
- **suggested branch**: `feat/system-prompt-noise-filter-expansion`
- **reviewer scope**: 일반
- **size estimate**: prompt diff ~20 lines + 회귀 테스트 1개
- **priority**: low — 측정 결과(self-judging) 정상 동작 중, 사내 데이터 확보 후 처리

### task-AGENT-002 — system prompt tool 호출 의무 wording 정량화
- **출처**: PR #34 code-reviewer 권고 (현재 "반드시 순서대로" 는 정성 표현).
- **scope**: tool 호출 실패 시 retry / escalate 정책 명문화 — "tool 호출이 N회 실패하면 사용자에게 보고하고 중단", "tool 호출 없이 응답 시도 시 자체 검증" 등. system prompt 또는 별도 agent 정책 문서로 분리. 영향 측정 필요 (variance 증가 가능).
- **suggested branch**: `feat/system-prompt-tool-policy-quantified`
- **reviewer scope**: 일반
- **size estimate**: prompt + agent 코드 ~40 lines + 측정 보고
- **priority**: medium — fallback parser metadata (task-AGENT-009) 머지 후 측정 가능

### task-AGENT-003 — fallback parser regex DoS guard 실측 효과 측정
- **출처**: PR #35 architect WARN-LOW (fallback parser regex guard).
- **scope**: `_MAX_FALLBACK_CONTENT_LEN = 64 * 1024` 가 실측 효과 (regex catastrophic backtracking 회피) 가 적절한지 재조정. 적대적 input (긴 `<function=>` 중첩, unterminated `<tool_call>`) 으로 timeout 측정 + 적정값 산정.
- **suggested branch**: `perf/fallback-parser-guard-measurement`
- **reviewer scope**: 일반 + test-engineer 중점
- **size estimate**: bench script + tests ~80 lines
- **priority**: medium — task-TEST-002 와 묶음 가능

### task-SEC-014 — fallback parser prompt injection vector 검토
- **출처**: PR #35 security-reviewer WARN-MED (4 패턴 inject regex).
- **scope**: fallback parser 가 사용하는 4 패턴 (`<function=>`, `<tool_call>`, ` ```json `, `<|python_tag|>`) 이 사용자 input 에 포함될 경우 prompt injection vector 가 될 수 있는지 분석. 가능하다면 input sanitization (escape / reject) 또는 trust boundary 명문화. 위험도 high — 사용자 stderr 가 LLM context 에 그대로 들어가므로 공격자가 stderr 에 fake tool call 주입 시 tool 임의 호출 가능.
- **suggested branch**: `feat/fallback-parser-injection-guard`
- **reviewer scope**: 일반 + security-reviewer 중점
- **size estimate**: input sanitizer ~80 lines + injection 테스트 케이스 ~120 lines
- **priority**: **high** — 보안 critical, fallback parser 도입 직후 우선 처리

### task-TEST-002 — fallback parser regex catastrophic backtracking 테스트
- **출처**: PR #35 test-engineer WARN-LOW.
- **scope**: fallback parser 의 4 regex 패턴 (`re.DOTALL` 사용) 이 적대적 input 에서 catastrophic backtracking 발생 안 하는지 테스트 추가. greedy `.*?` 사용 + `_MAX_FALLBACK_CONTENT_LEN` 가드 의 효과 측정. timeout 기반 회귀 테스트.
- **suggested branch**: `test/fallback-parser-backtracking`
- **reviewer scope**: 일반 + test-engineer 중점
- **size estimate**: tests ~100 lines (adversarial fixtures + timeout)
- **priority**: medium — task-AGENT-003 과 묶음 가능

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

### task-DOC-001 — Open WebUI 첫 사용 가이드 / API key rotation / backup-restore
- **출처**: PR #22 docs(deployment) — 배포 가이드 scope 외 항목
- **scope**: `docs/operations/` 추가 문서:
  - Open WebUI 첫 접속 → 모델 선택 → MACRO 에러 로그 붙여넣기 walk-through
  - `MACRO_LOGBOT_API_KEY` rotation 절차 (서비스 재시작 없는 rolling update 포함)
  - `.open-webui-data/` 볼륨 backup / restore 절차
- **suggested branch**: `docs/ops-user-guide`
- **reviewer scope**: 메타 (architect + verifier)
- **size estimate**: docs ~100 lines
- **priority**: low — 운영 투입 직전

### task-DEMO-001 — demo_session.py 개선 (cleanup + semantic + error paths)
- **출처**: PR #29 architect WARN-3/4 (LOW) + code-r WARN-2/3 (MED) + LOW 4 + test HIGH/MED 분기 미커버
- **scope**:
  - **arch WARN-3 + code-r WARN-2 (MED)**: `--log` 와 `--prompt` 동작 동일 — docstring/help 에 "현재 동작 동일, semantic hint" 명시 또는 통합.
  - **arch WARN-4 (LOW)**: `--case` 모드의 `tempfile.mkdtemp` cleanup — `tempfile.TemporaryDirectory` context manager.
  - **code-r WARN-1 (MED)**: mypy `no-any-return` 3건 (`scripts/demo_session.py:88,90,92`) cast 명시.
  - **code-r WARN-3 (MED)**: `--case` 분기 `inject/trigger` ImportError 친절 처리 (사외 배포 환경).
  - **code-r LOW**: root_cause 300자 truncation `...` 표기, `--timeout` 문서화, Dockerfile Debian codename ARG, apt sources backup.
  - **test HIGH-1**: `post_analyze` 에러 path 3종 (HTTPError/URLError/Timeout) + `main()` `sid` 없는 분기 테스트.
  - **test MED**: `EOFError` / `KeyboardInterrupt` input 분기.
  - **test LOW**: `_print_response` 출력 분기 + `--case` mock 테스트.
- **suggested branch**: `chore/demo-session-improvements`
- **reviewer scope**: 일반
- **priority**: low — 데모 안정성

### task-DEMO-002 — `--api-key` argv 평문 노출 회피 (env 또는 getpass)
- **출처**: PR #29 security WARN-MED-2
- **scope**: `scripts/demo_session.py` `--api-key` flag 가 `ps auxe` / `/proc/<pid>/cmdline` / shell history 에 평문 노출. env `MACRO_LOGBOT_API_KEY` 만 허용 (flag deprecate) 또는 `getpass.getpass("API key: ")` fallback. 최소 help 문구에 argv 노출 경고.
- **suggested branch**: `chore/demo-api-key-getpass`
- **reviewer scope**: 일반 (보안)
- **priority**: low — demo CLI, env 사용 권장

### task-INFRA-CA-001 — 사내 CA bundle + --trusted-host 제거 + apt signed-by
- **출처**: PR #29 security WARN-MED-1 + LOW-3
- **scope**:
  - Dockerfile 에 `ARG INTERNAL_CA_BUNDLE` + `COPY ${INTERNAL_CA_BUNDLE:-/dev/null} /usr/local/share/ca-certificates/internal.crt` + `update-ca-certificates` 표준 패턴.
  - `pip install --trusted-host` 완전 제거 (system CA 로 충분).
  - `pip install --require-hashes` 또는 lockfile 도입 검토.
  - apt sources.list 에 `signed-by=/etc/apt/keyrings/internal.gpg` 명시.
- **suggested branch**: `chore/infra-ca-bundle`
- **reviewer scope**: 일반 (보안 중요)
- **priority**: medium — 사내 production rollout release gate

---

## Priority Order (실행 순서)

1. ~~task-LG-001~~ — Message tool_calls round-trip (PR #11 본 PR scope 안 처리 완료) ✅
2. ~~**task-LG-002** + **task-SEC-003**~~ — LLMGateway base_url/api_key + kwargs allowlist ✅ `feat/gateway-internal-llm-hooks` 본 PR 완료
3. **task-SEC-002** + **task-MVP-006** — /v1/chat/completions 인증 + Tool 보안 강화 (사내 운영 진입 / Open WebUI 통합 PR 선결)
4. **task-LG-003** — /v1/chat/completions streaming (Open WebUI 통합 PR 시점)
5. ~~task-MVP-001~~ — LangGraph migration (PR #18 머지 완료) ✅
6. **task-MVP-002** — Session SQLite (Open WebUI 운영 진입)
7. ~~task-MVP-003~~ — MCP tools 나머지 4개 (PR #19 머지 완료) ✅ — 잔여 mock/placeholder 실연동은 **task-MVP-003-x**
8. **task-PROCESS-001** — §10.4 §4.3 병렬 호출 검증 항목 (메타 PR)
9. **task-SEC-001** — LiteLLM pin 상향 (LiteLLM 3.14 지원 또는 Python downgrade 결정 후)
10. **task-MVP-004 / 005 / 009** — 운영·다국어·MCP 분리 (필요 시점)
11. **task-006** — Python 3.14 CI matrix (Stage 3 진척 후)
12. **task-POC-004** — `.env` 자동 로드 pytest 격리 (CI 통과 안정화)
13. ~~**task-POC-001**~~ — 1-B/2-A/2-B Claude judge 채점 ✅ PR #27
14. ~~**task-POC-002**~~ — error catalog 5 → 10 확장 ✅ PR #30
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
