# macro-logbot

사내 에이전트 AI 플랫폼. 첫 번째 사용 사례는 사내 테스트 플랫폼 **MACRO**에서 발생하는 에러의 **자율 원인 분석**입니다. Claude Code와 유사하게 LLM이 도구(코드 검색·로그 조회 등)를 자율적으로 다중 호출하며 단서를 모아 결론을 도출합니다.

## 빠른 시작 (Ubuntu 22.04)

> **상세 가이드는 [배포 가이드 (DEPLOYMENT.md)](docs/operations/DEPLOYMENT.md)** 단일 출처. 본 README 는 요약만 — 사전 설치 명령 / 트러블슈팅 / 사외-사내 비교표는 DEPLOYMENT.md 참조 (변경 시 한 곳만 수정).

1. **사전 설치** — Docker Engine + Compose v2 plugin + git → DEPLOYMENT.md §1단계.
2. **clone + `.env` 작성**:
   ```bash
   git clone https://github.com/simsimhugh/macro-logbot.git
   cd macro-logbot && cp .env.example .env
   nano .env   # MACRO_LOGBOT_API_KEY + LLM key
   ```
3. **기동**:
   ```bash
   docker compose up -d --build       # 또는 ./scripts/deploy.sh
   ```

확인: `http://localhost:3000` (Open WebUI), `curl http://localhost:8000/health`.

사외/사내 차이는 `.env` 4개 변수 swap 뿐 (코드 변경 0).

## 현재 단계

```
[Stage 1] 요구사항 명세서   ← 현재 (v0.4)
[Stage 2] 설계 문서          예정
[Stage 3] 구현               예정
                             → 코드위키 운영 문서
```

## 문서

- [Stage 1 — 요구사항 명세서 (v0.4)](docs/requirements/01-요구사항명세서.md)

## 핵심 제약

- LLM endpoint는 **사내 전용** (외부 API 호출 금지)
- 분석 대상 코드·로그는 **사내 환경 외부로 유출 금지**
- macro-logbot **자체** 코드만 본 사외 GitHub repo에서 관리
- 사내 환경은 외부 인터넷 격리 → 사내 미러 레포 사용 (배포 환경별 의존성 소스 전환 가능)

자세한 내용은 요구사항 명세서를 참고하세요.

## Repository

- Source: https://github.com/simsimhugh/macro-logbot
- License: TBD (Stage 2에서 결정)

## Stage 3 진입

골격(skeleton) PR 머지 완료 — FastAPI app, 빈 패키지 구조, 기본 테스트 준비됨.

### 빠른 시작

```bash
pip install -e .[dev]   # 의존성 설치
make test               # 테스트 실행
make run                # 서버 실행 (localhost:8000)
```

## MVP Quick Start (사외 PoC)

Open WebUI 와 macro-logbot backend 를 docker-compose 로 한 번에 띄우는 사외 demo 흐름.
사내 운영 (사내 LLM endpoint + 사내 mirror image + reverse proxy) 은 별도 manifest.

### 사전 준비

- Docker + Docker Compose
- LLM provider API key 1개 이상
  - 권장: **Gemini Flash** — 무료 한도가 가장 넉넉. <https://aistudio.google.com> 에서 발급.
  - 대안: OpenAI / Anthropic / Groq (제공자별 비용 정책 확인).

### 실행

1. `.env` 파일 생성:
   ```bash
   cp .env.example .env
   ```
2. `.env` 편집:
   - `MACRO_LOGBOT_API_KEY` — 임의 문자열 (Open WebUI 와 backend 가 공유).
   - `MACRO_LOGBOT_DEFAULT_MODEL=gemini/gemini-1.5-flash` (Gemini 사용 시).
   - `GEMINI_API_KEY=<발급 키>` (또는 사용할 provider 의 key).
3. 기동:
   ```bash
   docker-compose up -d
   ```
4. <http://localhost:3000> 접속 (Open WebUI).
5. 모델 선택 → 채팅 시작. `read_file`, `grep_codebase`, `list_dir`, `git_blame`,
   `recent_commits` tool 이 자동 노출되며 agent 가 필요 시 호출.

### MACRO 에러 로그 분석 (직접 호출)

`/agent/analyze` endpoint 로 POST:

```bash
curl -X POST http://localhost:8000/agent/analyze \
  -H "Authorization: Bearer ${MACRO_LOGBOT_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "log_text": "2026-05-19 14:30:01 ERROR: DB connection failed\nTraceback (most recent call last):\nConnectionError: refused"
  }'
```

### 인증 동작 요약

- `Authorization: Bearer <key>` 또는 `X-API-Key: <key>` 헤더 필수.
- `/health` 는 인증 제외 (헬스 체크/로드 밸런서 호환).
- 서버 측 `MACRO_LOGBOT_API_KEY` 미설정 + `MACRO_LOGBOT_AUTH_REQUIRED=false` (기본) →
  WARN 로깅 후 인증 skip (dev 편의).
- `MACRO_LOGBOT_AUTH_REQUIRED=true` + key 미설정 → 503 (misconfigured).

상세 후속 작업은 `docs/process/FOLLOWUP-TASKS.md` (task-SEC-002 등) 참고.

> 사내 운영 시 `.env` 의 사내 mirror 3줄 (image/pip) uncomment 하면 같은 명령으로 동작 — LLM endpoint 1줄은 task-LG-002 후속 — `docs/design/02-설계문서.md` §8.4 참조.
