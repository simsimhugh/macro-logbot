# macro-logbot SSO 로그인 설계 plan (task-SEC-002 상세화)

> 출처: architect agent (read-only) 2026-05-19, PR #38 docs 정착

본 문서는 architect agent 의 분석 결과로, task-SEC-002 ([GitHub Issues `follow-up`](https://github.com/simsim-lab/macro-logbot/issues?q=is%3Aopen+label%3Afollow-up)) 의 sub-task 분해 근거 및 구현 지침으로 사용한다.

---

## 1. 요구사항 정리

### 1.1 사내 환경 가정
- 사용자 사내는 Samsung 계열 사내 LLM (`gpt-oss / GaussO4 / GaussO3 / Gemma4-260430`) 을 운영 — Samsung 사내 SSO 의 통합 가능성이 높음(미확인). 정확한 protocol(SAMLv2 / OIDC / 자체 토큰)은 사용자 확인 필요 — §7 risk 로 격상.
- 사내 네트워크는 외부 인터넷 차단 (spec `docs/design/02-설계문서.md:730-748` §12.1). 따라서 외부 IdP(Google/Microsoft) 사용 불가, **사내 IdP only**.
- 사내 미러 가용 (`docs/operations/DEPLOYMENT.md:107-118` 의 BASE_IMAGE/PIP_INDEX_URL 패턴). `Authlib` / `python-jose` / `oauth2-proxy` image 미러 필요.

### 1.2 사외 PoC vs 사내 production 분리
| 환경 | 인증 |
|---|---|
| 사외 PoC (현재) | 공유 API key (`MACRO_LOGBOT_API_KEY`) Bearer + X-API-Key 동치. `src/macro_logbot/auth.py:57-101`. WEBUI_AUTH=false (`docker-compose.yml:61`) |
| 사내 production | SSO 필수 — task-SEC-002. 운영 진입 차단 사유 (`docs/operations/DEPLOYMENT.md:241-247`) |

핵심 원칙: **API key 인증은 deprecate 가 아닌 fallback 으로 유지** — 서비스 계정(evaluate.py, intake webhook, MACRO platform → backend)이 SSO 미지원이라서 영구 공존 필요.

### 1.3 단일 사용자 vs 다중 사용자 — 영향 평가 (critical)
현재 시스템은 사실상 단일 사용자 가정:
- `verify_api_key` 가 단일 server_key 와 timing-safe 비교만 수행 — principal 개념 없음 (`src/macro_logbot/auth.py:57-101`).
- `SQLiteSessionStore.get(session_id)` 는 owner 검증 없음 + `app.py:242-249` 가 미존재 session_id 받으면 **새 session 발급으로 fallback** — IDOR 회피 + DoS/저장소 오염 vector. principal scoping → task-SEC-002 묶음 (§6 sub-task 참조).
- `AgentState` 에 `user_id` / `principal` 필드 없음 — `session_id` / `event_id` 만 존재 (`docs/design/02-설계문서.md:136-148`).

**영향**: SSO 도입 시 단순 인증만 추가하면 부족. 다음 4개 모델 변경이 동반되어야 함:
1. `sessions` 테이블에 `owner_principal TEXT NOT NULL` 컬럼 추가 (task-MVP-002-x 와 묶음 권장).
2. `AgentState` 에 `principal: Principal | None` 필드 추가.
3. `KBStore` 의 `verified-master` 승격 권한 분리 (모든 사용자 vs admin role).
4. `archived_cases.source="poc"` 외 `created_by` 컬럼 추가.

### 1.4 audit log 요구
- 운영 회수 채널 §11 + 보안 §12 (`docs/design/02-설계문서.md:719-749`) 에서 명시 부재 — 운영 진입 시 보안팀 요청 예상. 본 plan 에서 audit 표준화.
- 최소 로깅 이벤트: `auth.login.success/failure`, `auth.token.refresh`, `auth.token.revoke`, `session.access`(IDOR 감시), `kb.write.verified-master` (권한 승격 행위).
- 형식: 구조화 JSON (Python `logging` + JSON formatter), PII 마스킹 (email 도메인까지만, employee_id 해시).

---

## 2. Provider 옵션 비교

| Option | 적합도(사내) | 구현 난이도 | Pros | Cons |
|---|---|---|---|---|
| **A. SAML 2.0** | 높음 (Samsung 사내 표준 가능성 ↑) | 높음 — `python-saml3` 또는 `Authlib` SAML support. XML metadata 교환 필요 | (1) Enterprise 사실상 표준 (2) IdP-initiated SSO 가능 (3) 인증서 기반 무전이 신뢰 | (1) XML 복잡 (2) FastAPI 직접 통합 라이브러리 빈약 (3) IdP metadata URL 사내 발급 절차 필요 |
| **B. OAuth 2.0 / OIDC** | 중-높음 (사내 IdP 가 OIDC 지원 시) | 중 — `Authlib` 가 first-class. Open WebUI 자체 OIDC 지원 (검증 필요) | (1) `Authlib` 성숙 (2) JWT 토큰 자체 검증 가능 — DB lookup 회피 (3) Open WebUI native 통합 (4) 사외 PoC 도 무료 IdP(Google) 로 테스트 가능 | (1) IdP 가 OIDC 미지원이면 무용 (2) JWT 키 rotation 운영 (3) refresh token 저장 |
| **C. 사내 자체 SSO API** | 가능 (사내 wrapper 가 있을 경우) | 가변 — 사내 SDK 의존 | (1) 사내 IT 의 1차 권고 (2) 사내 보안 정책 자동 준수 | (1) 외부 PoC 에서 검증 불가 (2) library lock-in (3) protocol opaque |

**권고**: **B(OIDC) 우선 + A(SAML) fallback**. Samsung 사내 IdP 가 OIDC endpoint 를 노출하면 (대부분의 enterprise IdP — Ping/Okta/Azure AD/사내 KMS — 가 노출함) B 채택. 미지원이면 A. C 는 사내 IT 의 명시적 요청 시에만 (vendor lock-in 위험).

---

## 3. 아키텍처 옵션

### Option A: Backend 자체 SSO middleware (FastAPI + Authlib)
```
[Open WebUI] --(OPENAI_API_KEYS 공유 키)--> [backend: Authlib OIDC] <-- redirect --> [사내 IdP]
                                                                                    |
                                                                            backend 가 JWT 검증
```
- 구현: `verify_api_key` → `AuthBackend.authenticate(request) -> Principal` interface. `OIDCAuthBackend` + `APIKeyAuthBackend` + `ChainedAuthBackend`(fallback 순서).
- **Pros**: backend 가 principal 의 single source of truth. evaluate.py / webhook 도 동일 backend.
- **Cons**: Open WebUI ↔ backend 간 redirect flow 가 OpenAI 호환 API 와 맞지 않음 — Open WebUI 는 단순 API key 만 송신. 브라우저 redirect 가 불가.
- **적합성**: webhook(MACRO platform → `/agent/analyze`) + 직접 curl 시나리오에는 적합. 브라우저 UI 시나리오에는 부적합.

### Option B: 사내 reverse proxy(oauth2-proxy / nginx auth_request) 에서 SSO 처리, backend 는 헤더 신뢰
```
                       [oauth2-proxy: SSO]
                              |
[브라우저] -> [oauth2-proxy] --+--> [Open WebUI] --(OPENAI key + forward header)--> [backend]
                              \--> [backend (직접 호출 path)]
                       \-- X-Forwarded-User, X-Forwarded-Email 헤더 --/
                              ↑
                       [사내 IdP] 와 통신
```
- 구현: backend 는 reverse proxy 에서 forward 된 `X-Forwarded-User`(employee_id) + `X-Forwarded-Email` 헤더를 신뢰 + IP allowlist(proxy 만 forward 허용)로 spoofing 방지.
- **Header propagation 메커니즘 (Hardening R3 — architect WARN-MED)**: Open WebUI 가 자체 brower session 에서 backend 호출 시 oauth2-proxy header 가 자동 propagate 되지 않는다. 두 가지 해소책:
  - (a) **권장**: oauth2-proxy 가 backend 도 직접 proxy — 사용자 → oauth2-proxy → {Open WebUI, backend} 토폴로지. Open WebUI 는 사용자 인증 정보 없이 service-account API key 만 사용.
  - (b) 대안: Open WebUI 가 backend 호출 시 oauth2-proxy 의 `--set-xauthrequest=true` + Open WebUI 의 request forwarding config 로 header chain 구성. (Open WebUI 의 OpenAI API client 가 header pass-through 지원해야 — 검증 필요)
- **Pros**: (1) 사내 표준 패턴 — oauth2-proxy 는 SAML/OIDC 둘 다 지원 (2) backend 코드 변경 최소 (3) Open WebUI + backend 둘 다 동일 proxy 뒤 (4) 사내 보안팀이 oauth2-proxy 자체 검증 인계 가능
- **Cons**: (1) Open WebUI 가 자체 user 관리 — proxy 헤더 ↔ Open WebUI user 매핑(`WEBUI_AUTH_TRUSTED_EMAIL_HEADER` 설정 필요) (2) backend 헤더 spoofing 방어 critical (3) `tcpdump` 검증 시 추가 hop
- **적합성**: 사내 production 표준. evaluate.py / webhook 은 별도 service-account API key path.

### Option C: Open WebUI 자체 SSO + backend 는 service account
```
[브라우저] -> [Open WebUI: OIDC 자체] -> [backend: service account API key (Open WebUI 가 보유)]
```
- 구현: Open WebUI 의 `ENABLE_OAUTH_SIGNUP=true` + `OAUTH_CLIENT_ID/SECRET/PROVIDER_URL` 환경변수 활용. backend 는 그대로 API key 검증.
- **Pros**: (1) backend 코드 변경 0 (2) Open WebUI 의 OAuth 지원 활용 (3) 가장 빠른 진입 경로
- **Cons**: (1) backend 가 직접 호출되는 path(webhook, evaluate.py, curl) 는 SSO 불가 — API key 만 (2) audit log 가 Open WebUI 와 backend 둘로 갈라짐 (3) Open WebUI 가 사용자 principal 을 backend 에 전달할 인터페이스 없음 — OpenAI API 는 user 필드만 (선택) (4) 사내 보안팀 입장에서 "Open WebUI 자체 신뢰 가능 인증?" 추가 검토 필요

### 권고 — Hybrid: B(reverse proxy) + Option C 의 일부
| Trust boundary | 인증 방식 |
|---|---|
| 사용자 브라우저 → Open WebUI | oauth2-proxy 가 처리 (Option B) |
| Open WebUI → backend `/v1/*` | proxy 가 backend 호출 시 `X-Forwarded-User` 헤더 + service-account API key (cross check) |
| 외부 webhook → backend `/agent/analyze` | API key 인증 (service account, scope 제한) |
| 직접 curl / evaluate.py → backend | API key 인증 (admin scope) |

**Trade-off**: 단순 Option C 보다 인프라 1단계 추가, 대신 단일 audit log + principal 일관성 확보.

---

## 4. 구현 단계 (sprint plan)

### Sprint 1 — 인증 추상화 layer (PR 1개) → task-SEC-002-a
- `src/macro_logbot/auth.py:57-101` 의 `verify_api_key` 를 다음 구조로 리팩토링:
  ```
  AuthBackend (Protocol):
    async authenticate(request) -> Principal | None
  ────
  APIKeyAuthBackend(AuthBackend)
  HeaderForwardAuthBackend(AuthBackend)  # X-Forwarded-User
  OIDCAuthBackend(AuthBackend)           # Authlib JWT 검증
  ChainedAuthBackend(AuthBackend)        # 순서대로 시도, 첫 success
  ```
- `Principal` Pydantic 모델: `{id: str, email: str | None, name: str | None, scopes: list[str], source: Literal["api_key","sso","header_forward"]}`
- `verify_api_key` 는 `Depends(get_principal)` 로 교체. backward-compat: `MACRO_LOGBOT_AUTH_REQUIRED=true` + API key 만 설정한 환경은 그대로 동작.
- 테스트: 기존 `tests/test_auth*.py` 호환 + Principal 반환 검증.
- **사이즈 추정**: src ~150 lines + tests ~120 lines.

### Sprint 2 — API key fallback 유지 + 기본 SSO 추가 (PR 1개) → task-SEC-002-b
- `HeaderForwardAuthBackend` 구현 — `MACRO_LOGBOT_AUTH_TRUSTED_PROXY_IPS` env (CIDR 리스트) 로 spoofing 방어. proxy IP 가 아닌 곳에서 들어온 `X-Forwarded-User` 헤더는 무시 + WARN 로깅.
- `Principal.scopes` 에 `["chat","analyze"]` (사용자) vs `["webhook"]` (service account) vs `["admin","kb.verify"]` (관리자) 분리.
- 엔드포인트별 scope 가드: `chat_completions` → `chat`, `agent_analyze` → `analyze` 또는 `webhook`, KB verified-master 승격 → `kb.verify` (미래).
- **사이즈 추정**: src ~80 lines + tests ~100 lines.

### Sprint 2b — OIDC 백엔드 (PR 1개, 사내 IdP 확정 후) → task-SEC-002-c
- `OIDCAuthBackend` 구현 — `Authlib` JWKS 검증. `MACRO_LOGBOT_OIDC_ISSUER` + `MACRO_LOGBOT_OIDC_JWKS_URL` env.
- JWKS 캐시: `Authlib` 기본 600s 캐시 유지.

### Sprint 3 — session/token 관리 → task-SEC-002-d
- **결정**: stateless JWT(OIDC access token 자체) + session DB(분석 session)는 **분리 유지**.
  - 인증 토큰 = JWT in `Authorization: Bearer`. backend 는 JWKS 로 검증 only — Redis 불필요.
  - 분석 session = 기존 SQLite `sessions` (`SQLiteSessionStore`).
  - cookie 는 oauth2-proxy 영역만, backend 는 cookie 무시.
- `sessions` 테이블 schema 변경(task-MVP-002-x 와 묶음):
  - `owner_principal TEXT NOT NULL DEFAULT 'anonymous'` (NOT NULL with default — 기존 row 마이그레이션 안전).
- `SQLiteSessionStore.get(session_id, principal)` 시그니처 확장 — owner mismatch 시 `None` 반환 (404 와 동일 처리, IDOR 회피 — `src/macro_logbot/app.py:242-249` 의 기존 fallback 패턴 유지). **주의 (architect WARN-MED)**: 현재 `app.py:242-249` 가 미존재 session_id 받으면 새 session 발급으로 fallback — multi-user 환경에서 owner mismatch 와 미존재 구분 안 하면 DoS/저장소 오염 vector. task-SEC-002-d 구현 시 owner mismatch → 명시적 403 (또는 audit log 후 새 session 발급 거부) 결정 필요.
- **사이즈 추정**: src ~60 lines + tests ~80 lines + 마이그레이션 SQL 1개.

### Sprint 4 — audit log + 보안 로깅 → task-SEC-002-e
- 새 모듈 `src/macro_logbot/audit.py`. JSON logger + `audit.log_event(event_type, principal, details)` API.
- 이벤트: `auth.success`, `auth.failure`, `session.access`, `session.access_denied`(IDOR), `kb.write`(향후 `kb.verified-master.promote`).
- PII 마스킹: `email_domain_only()`, `principal_hash()` 헬퍼.
- 로그 sink: stdout JSON line (사내 SIEM 이 docker logs 수집), optional `MACRO_LOGBOT_AUDIT_LOG_PATH` env 로 파일.
- **사이즈 추정**: src ~120 lines + tests ~80 lines.

### Sprint 5 — 사내 환경 통합 + production gate → task-SEC-002-f
- `docker-compose.internal.yml` 추가 — oauth2-proxy 컨테이너 + Open WebUI `WEBUI_AUTH_TRUSTED_EMAIL_HEADER` 설정.
- Open WebUI OIDC 자체 통합(Option C) 도 옵션으로 — `ENABLE_OAUTH_SIGNUP=true` env.
- `DEPLOYMENT.md` 사내 운영 절차 갱신.
- production gate: `MACRO_LOGBOT_AUTH_BACKEND={api_key|header_forward|oidc|chained}` env 의 기본값을 사내 production manifest 에서 `chained`(header_forward → api_key) 로.
- **사이즈 추정**: compose ~50 lines + docs ~100 lines.

---

## 5. spec 변경 사항

### 5.1 `docs/design/02-설계문서.md` §5.1 (line 99-124, 인증)
- "shared secret (Authorization 헤더) — placeholder, OQ B-4 답변 시 확정" 행(line 103)을 다음으로 갱신:
  - 사외 PoC: 공유 API key.
  - 사내 production: oauth2-proxy SSO + backend `HeaderForwardAuthBackend`.
  - service account: scoped API key(`webhook` scope 전용).
- `AuthBackend` Protocol 정의 + `Principal` schema 도입 명시.

### 5.2 `docs/design/02-설계문서.md` §12 보안 검증 (line 730-748)
- §12.1 외부 유출 방지: 화이트리스트에 "사내 IdP endpoint" 추가.
- §12.2 시크릿 관리: JWT 검증용 JWKS URL + OIDC client_secret 항목 추가.
- 신규 §12.4 SSO 통합 추가 — Trust boundary 표 + spoofing 방어 (proxy IP allowlist) 명시.
- 신규 §12.5 Audit Log — 이벤트 카탈로그 + PII 마스킹 정책.

### 5.3 `docs/operations/DEPLOYMENT.md` (line 93-132)
- 사외 PoC vs 사내 운영 비교표(line 95-109) 에 4개 행 추가:
  - `MACRO_LOGBOT_AUTH_BACKEND` (사외: api_key, 사내: chained)
  - `MACRO_LOGBOT_AUTH_TRUSTED_PROXY_IPS` (사외: 빈칸, 사내: oauth2-proxy CIDR)
  - `MACRO_LOGBOT_OIDC_ISSUER` / `MACRO_LOGBOT_OIDC_JWKS_URL` (사내: 사내 IdP)
  - `MACRO_LOGBOT_AUDIT_LOG_PATH` (사내: `/var/log/macro-logbot/audit.jsonl`)
- 사내 운영 최소 설정 예시(line 120-132) 갱신.
- 신규 섹션 "사내 운영 — SSO 통합 절차" 추가.

---

## 6. task-SEC-002 sub-task 분해

task-SEC-002 를 6 sub-task 로 분해 (GitHub Issues `follow-up` 으로 등록):

| sub-task | Sprint | 내용 | priority |
|---|---|---|---|
| task-SEC-002-a | Sprint 1 | `AuthBackend` Protocol + `Principal` 모델 + `verify_api_key` 호환 리팩토링 | high |
| task-SEC-002-b | Sprint 2 | `HeaderForwardAuthBackend` + scope 분리 | high |
| task-SEC-002-c | Sprint 2b | `OIDCAuthBackend`(Authlib) + JWKS 검증 | high (IdP 확정 후) |
| task-SEC-002-d | Sprint 3 | `sessions.owner_principal` 컬럼 + IDOR 회피 + session principal scoping | high |
| task-SEC-002-e | Sprint 4 | `audit.py` 모듈 + 이벤트 로깅 | medium |
| task-SEC-002-f | Sprint 5 | `docker-compose.internal.yml` + oauth2-proxy + spec/DEPLOYMENT 문서 갱신 | high |

---

## 7. Risk / Open Questions

| ID | 항목 | 영향 | 차단 여부 |
|---|---|---|---|
| RISK-SSO-1 | Samsung 사내 SSO 의 정확한 protocol(SAML vs OIDC vs 자체) 미확인 | Option B vs A vs C 결정 불가 | task-SEC-002-c 차단. 사용자에게 1차 인터뷰 필요 |
| RISK-SSO-2 | 다중 사용자 모델 부재 — `sessions` 테이블 + `AgentState` 모두 principal 필드 없음 | 운영 진입 전 schema migration 필수 | task-SEC-002-d ↔ task-MVP-002-x 묶음으로 해소 |
| RISK-SSO-3 | Open WebUI ↔ backend 의 SSO context propagation — Open WebUI 의 OpenAI API 호출은 user 필드만 (선택) 제공 | Option B(reverse proxy 헤더) 의존 필연 | oauth2-proxy 채택 시 해소 |
| RISK-SSO-4 | evaluate.py 의 인증 정책 미정 — SSO 우회? service account? | PoC 자동화 회귀 위험 | `webhook` scope 의 service-account API key 영구 유지로 해소 |
| RISK-SSO-5 | JWT 키 rotation — JWKS URL 캐시 만료 정책 결정 필요 | 사내 IdP 의 키 rotation 주기 ≥ 캐시 만료 보장 | OIDCAuthBackend 구현 시 `Authlib` 기본 600s 캐시 유지 |
| RISK-SSO-6 | oauth2-proxy 와 backend 사이 spoofing 방어 — backend 가 무신뢰 환경에서 헤더 받으면 우회 가능 | high severity | `MACRO_LOGBOT_AUTH_TRUSTED_PROXY_IPS` CIDR allowlist + 미설정 시 fail-closed |
| RISK-SSO-7 | 사내 미러에 `Authlib` / `oauth2-proxy` image 미보유 가능성 | Sprint 차단 | task-SEC-001 / task-OPS-001 패턴으로 dep 등록 절차 사전 진행 |
| RISK-SSO-8 | KB `verified-master` 승격 권한 — 누가 어떤 role 로? | KB 신뢰성 손상 | `Principal.scopes` 에 `kb.verify` 추가, 별도 admin role |
| RISK-SSO-9 | OAuth state/PKCE CSRF — login-back redirect 가로채기 | high — 세션 탈취 | OIDCAuthBackend 가 state cookie + PKCE 강제, oauth2-proxy 의 `--cookie-csrf-per-request=true` 활성 |
| RISK-SSO-10 | Refresh token theft — 장기 사용자 세션 탈취 | medium — 토큰 노출 시 영속 접근 | refresh token 저장 회피 (JWT access token + 짧은 만료 + IdP 재인증) 또는 oauth2-proxy 의 server-side session store (`--session-store-type=redis`) 사용 |
| RISK-SSO-11 | Audit log tampering — IDOR/우회 사후 추적 불가 | high — 사고 회수 불가 | audit log sink 를 backend 외부 (host syslog + 사내 SIEM) 로 forward, integrity hash chain (또는 append-only log) 검토 |
| RISK-SSO-12 | SSO bypass via 영구 API key — service account 의 admin scope 가 사용자 path 도 접근 시 SSO 회피 | high — 권한 상승 | service account API key 는 `webhook` scope 만 발급, `chat/analyze` scope 발급 절대 금지. audit log 에서 `principal.source="api_key"` + 사용자 endpoint 호출 = 즉시 alert |

### 측정 시스템(evaluate.py)의 인증 우회 정책 — 명문화
- evaluate.py / poc 채점 스크립트는 **service-account API key** 로 backend 호출. 해당 key 는 `webhook` scope 만 보유 — 일반 사용자 endpoint 접근 불가.
- 사내 production 에서도 동일 — evaluate 는 SSO 흐름 통과하지 않음. audit log 에서 `principal.source="api_key"` + `principal.id="evaluate-service"` 로 식별 가능.

---

## Trade-off 요약

| Option | Pros | Cons | 권고 |
|---|---|---|---|
| A. Backend 자체 SSO | principal SSoT, 모든 path 통합 | 브라우저 redirect 불가 — Open WebUI 와 부조화 | webhook/CLI path 만 |
| B. Reverse proxy (oauth2-proxy) | 사내 표준 패턴, backend 변경 최소, IdP 종속 격리 | spoofing 방어 critical, hop 1개 추가 | **사내 production 기본** |
| C. Open WebUI 자체 OIDC | 가장 빠른 진입, backend 변경 0 | 직접 호출 path 통합 불가, audit 분리 | Option B 의 Open WebUI 측 옵션으로 병행 |

**최종 권고**: Hybrid = **B(주력) + 일부 C(Open WebUI 측면 추가 detection) + 영구 API key fallback(service account)** + `AuthBackend` 추상화로 dev/PoC ↔ 사내 production swap.

### Hardening rules (사내 production manifest 강제)

| 규칙 | 근거 | 강제 위치 |
|---|---|---|
| **R1** `MACRO_LOGBOT_AUTH_REQUIRED=true` 강제 (fail-closed) | security M3 (PR #38 review) — dev default `false` 가 production 으로 흘러오면 인증 무력화 | `docker-compose.internal.yml` (task-SEC-002-f) + backend startup 시 manifest 에 `AUTH_REQUIRED=false` 발견 시 fatal exit |
| **R2** IdP downgrade 방어 — B(OIDC) + A(SAML) 동시 enable 금지 | security M2 — attacker 가 약한 IdP path 선택 가능 | `MACRO_LOGBOT_AUTH_BACKEND` env 가 단일 backend (`oidc` 또는 `header_forward` 또는 `chained`) 만 허용. `oidc,saml` 같은 조합 reject |
| **R3** oauth2-proxy `X-Forwarded-User` propagation 메커니즘 명시 | architect WARN-MED (PR #38 review) — Open WebUI → backend hop 에서 자동 propagate 안 됨 | task-SEC-002-f 의 `docker-compose.internal.yml` 에 oauth2-proxy 가 backend 도 직접 proxy 하는 topology (사용자 → oauth2-proxy → {Open WebUI, backend}) 채택. Open WebUI 가 backend 호출 시 oauth2-proxy 의 forward header 를 그대로 전달하도록 Open WebUI 의 `WEBUI_AUTH_TRUSTED_EMAIL_HEADER` + backend reverse proxy 추가 hop 구성 |
| **R4** Service account scope 격리 | RISK-SSO-12 — admin scope 가 사용자 endpoint 호출 시 SSO 회피 | `Principal.scopes` 에 `webhook` 와 `chat/analyze` 분리, 동일 key 에 둘 다 부여 금지. audit log alert |

---

## References

핵심 코드:
- `src/macro_logbot/auth.py:57-101` — 현재 인증 구현 (`verify_api_key`)
- `src/macro_logbot/app.py:104,125,229` — `verify_api_key` 의존성 적용 endpoint 3개 (`/v1/models`, `/v1/chat/completions`, `/agent/analyze`)
- `src/macro_logbot/app.py:242-249` — 세션 owner 검증 부재(IDOR risk source) + 미존재 session_id 시 새 session 발급 fallback
- `docker-compose.yml:14-46, 48-67` — backend service + Open WebUI service. `WEBUI_AUTH=false` (line 61)

스펙/프로세스:
- `docs/design/02-설계문서.md:99-124` — §5.1 External Interfaces
- `docs/design/02-설계문서.md:136-147` — `AgentState` (principal 필드 부재)
- `docs/design/02-설계문서.md:730-748` — §12 보안 검증
- `docs/operations/DEPLOYMENT.md:241-247` — 운영 진입 전 체크리스트 (task-SEC-002 의 운영 진입 차단 사유)
- task-SEC-002 — 본 PR 에서 a~f 로 분해 (§6 참조). GitHub Issue 로 등록.
- task-MVP-006 — Tool 보안 강화 (task-SEC-002 와 묶음 후보). GitHub Issue 로 등록.
