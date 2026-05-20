# macro-logbot 배포 가이드 (Ubuntu 22.04 LTS)

사내 VM 에 macro-logbot 을 배포하는 절차. 사외/사내 차이는 `.env` 4개 변수 swap 뿐 — **코드 변경 없음**.

> "도커 이미지, pip 모듈을 어디서 받을지는 코드가 아니라 환경에서 설정만 되어 있으면 되는 거지?" — 정확합니다. `BASE_IMAGE` / `PIP_INDEX_URL` / `OPEN_WEBUI_IMAGE` / `MACRO_LOGBOT_LLM_*` 4 변수만 사내 mirror 값으로 바꾸면 동일 한 줄 명령으로 배포됩니다.

---

## 개요

```
사외 PoC                  사내 운영
────────────────────────────────────────────
docker compose up -d --build   (동일)
  BASE_IMAGE=python:3.14-slim         → <사내-registry>/python:3.14-slim
  PIP_INDEX_URL=https://pypi.org/...  → https://<사내-pypi>/simple
  OPEN_WEBUI_IMAGE=ghcr.io/...        → <사내-registry>/open-webui:main
  (LLM keys)                          → MACRO_LOGBOT_LLM_BASE_URL + API_KEY
```

Python 3.14 는 **호스트 설치 불필요** — `Dockerfile` 의 `FROM python:3.14-slim` 이 container 안에서 처리합니다.

---

## 호스트 사전 요구사항 (Ubuntu 22.04 LTS)

| 패키지 | 최소 버전 | 비고 |
|---|---|---|
| Docker Engine | 20.10+ | apt `docker.io` 24.0+ OK |
| Docker Compose v2 | 2.0+ | apt `docker-compose-v2` 또는 plugin |
| git | 2.x+ | clone 용 |

Python, pip, Node.js 등 **호스트에 별도 설치 불필요**.

---

## 1단계 — 사전 설치 (호스트에 한 번만)

Ubuntu 22.04 LTS (jammy) 의 archive 에는 `docker-compose-v2` / `docker-compose-plugin` 패키지가 없으므로 **Docker 공식 repo** 를 추가한다.

```bash
# (a) Docker 공식 GPG key + apt repo 등록
sudo apt update && sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update

# (b) Docker Engine + Compose v2 plugin 설치
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER
# 반드시 logout 후 재로그인 (또는 newgrp docker) — 이후 sudo 없이 docker 사용 가능
```

> **사내 망 변형**: `download.docker.com` 차단 시 사내 mirror 의 docker repo 또는 사내 IT 가 제공하는 사전 설치 절차 사용. 아래 명령 모두 사내 mirror 경로로 치환 가능.

설치 확인:

```bash
docker --version          # Docker version 24.x ...
docker compose version    # Docker Compose version v2.x ...
git --version             # git version 2.x ...
```

---

## 2단계 — 배포 (한 줄)

```bash
git clone https://github.com/simsimhugh/macro-logbot.git && cd macro-logbot \
  && cp .env.example .env && nano .env \
  && docker compose up -d --build
```

또는 원샷 스크립트 사용:

```bash
git clone https://github.com/simsimhugh/macro-logbot.git
cd macro-logbot
cp .env.example .env
nano .env          # 아래 .env 작성 가이드 참고
./scripts/deploy.sh
```

---

## `.env` 작성 가이드

### 사외 PoC vs 사내 운영 비교표

| Env | 사외 default (PoC) | 사내 운영 | 용도 |
|---|---|---|---|
| `MACRO_LOGBOT_API_KEY` | 임의 문자열 (필수) | 동일 (SSO 통합 전 임시) | backend ↔ Open WebUI 공유 key |
| `MACRO_LOGBOT_AUTH_REQUIRED` | `true` | `true` | 인증 강제 여부 |
| `BASE_IMAGE` | `python:3.14-slim` (기본값) | `<사내-registry>/python:3.14-slim` | Dockerfile base image |
| `PIP_INDEX_URL` | `https://pypi.org/simple` (기본값) | `https://<사내-pypi>/simple` | pip 패키지 mirror |
| `OPEN_WEBUI_IMAGE` | `ghcr.io/open-webui/open-webui:main` (기본값) | `<사내-registry>/open-webui:main` | Open WebUI 컨테이너 image |
| `APT_MIRROR` | (미설정 — Debian 공식) | `http://<사내-apt-mirror>` | Dockerfile 의 `apt sources.list` 교체 — `build-essential` 등 OS 패키지 사내 mirror |
| `PIP_TRUSTED_HOST` | (미설정) | `<사내-pypi-host>` | pip `--trusted-host` — 사내 HTTP mirror / self-signed CA 환경 인증서 검증 우회 |
| `MACRO_LOGBOT_LLM_BASE_URL` | (미설정 — 각 provider SDK 직접) | `https://<사내-llm-endpoint>` | 사내 LLM endpoint |
| `MACRO_LOGBOT_LLM_API_KEY` | (미설정) | `<사내 API key>` | 사내 LLM 인증 key |
| `MACRO_LOGBOT_LLM_PROVIDER` | (미설정) | `openai` / `anthropic` / custom | LiteLLM custom_provider |
| `MACRO_LOGBOT_DEFAULT_MODEL` | `gemini/gemini-2.5-flash-lite` | `<사내-모델-이름>` | 기본 LLM 모델 |
| `MACRO_LOGBOT_ENV` | `poc` | `production` | 실행 환경 게이트. `poc` 시 workspace 확장 허용; 미설정·`production` 시 fail-closed |
| `MACRO_LOGBOT_POC_WORKSPACE_ALLOWED` | `/tmp/poc-cases` | (미설정 — 사내 운영 시 제거) | `MACRO_LOGBOT_ENV=poc` 활성화 시만 유효한 workdir 루트 |
| `MACRO_LOGBOT_MODEL_CONTEXT_LIMIT` | `16384` | `8192` (Gemma 3 12B 등 소형 모델) 또는 `16384` | agent loop 컨텍스트 토큰 상한. 80% watermark 초과 시 오래된 메시지 pop |
| `GEMINI_API_KEY` | `<발급 key>` (사외 PoC 용) | (미설정 — 사내 endpoint 사용) | Gemini API key |
| `OPENAI_API_KEY` | (사외 PoC, 사용 시) | (미설정) | OpenAI API key — `MACRO_LOGBOT_DEFAULT_MODEL=openai/gpt-4o` 등 사용 시 |
| `ANTHROPIC_API_KEY` | (사외 PoC, 사용 시) | (미설정) | Anthropic API key — Claude 모델 사용 시 |
| `GROQ_API_KEY` | (사외 PoC, 사용 시) | (미설정) | Groq API key — Llama 3.3 등 사용 시 (14,400 RPD free) |

### 사외 PoC 최소 설정 예시

```bash
MACRO_LOGBOT_API_KEY=my-secret-key-change-me
MACRO_LOGBOT_AUTH_REQUIRED=true
MACRO_LOGBOT_DEFAULT_MODEL=gemini/gemini-2.5-flash-lite
GEMINI_API_KEY=AIza...
# PoC 측정 환경 — workspace 확장 허용 게이트
MACRO_LOGBOT_ENV=poc
MACRO_LOGBOT_POC_WORKSPACE_ALLOWED=/tmp/poc-cases
MACRO_LOGBOT_MODEL_CONTEXT_LIMIT=16384
```

### 사내 운영 최소 설정 예시

```bash
MACRO_LOGBOT_API_KEY=my-secret-key-change-me
MACRO_LOGBOT_AUTH_REQUIRED=true
BASE_IMAGE=registry.internal.corp/python:3.14-slim
PIP_INDEX_URL=https://pypi.internal.corp/simple
OPEN_WEBUI_IMAGE=registry.internal.corp/open-webui:main
APT_MIRROR=http://apt.internal.corp/debian
PIP_TRUSTED_HOST=pypi.internal.corp
MACRO_LOGBOT_LLM_BASE_URL=https://llm.internal.corp/v1
MACRO_LOGBOT_LLM_API_KEY=<사내 LLM key>
MACRO_LOGBOT_LLM_PROVIDER=openai
MACRO_LOGBOT_DEFAULT_MODEL=internal/llm-model
# 사내 production — fail-closed workspace 게이트 강제
MACRO_LOGBOT_ENV=production
# MACRO_LOGBOT_POC_WORKSPACE_ALLOWED 미설정 (사내 운영 시 제거)
# docker-compose 에서 /tmp/poc-cases:ro 마운트도 제거 (production manifest 분리)
```

> **production manifest 분리 원칙**: `docker-compose.yml` 에서 `/tmp/poc-cases:ro` 볼륨 마운트는 PoC 전용. 사내 운영용 `docker-compose.production.yml` 에는 해당 마운트를 포함하지 않는다. `MACRO_LOGBOT_ENV=production` 설정으로 코드 레벨 이중 차단.

---

## 3단계 — 검증

### 헬스 체크

```bash
curl http://localhost:8000/health
# 정상: {"status":"ok","version":"0.0.1"}
```

### LLM 응답 확인

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer ${MACRO_LOGBOT_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini/gemini-2.5-flash-lite","messages":[{"role":"user","content":"안녕"}]}'
# 정상: {"choices":[{"message":{"content":"안녕하세요..."}}],...}
```

### Open WebUI 접속

1. 브라우저에서 `http://localhost:3000` 접속.
2. Settings → Connections → OpenAI API → URL: `http://macro-logbot-backend:8000/v1`, Key: `MACRO_LOGBOT_API_KEY` 값.
3. 모델 선택 → 채팅 시작.

### multi-turn 데모 CLI (task-MVP-004 session_id 활용)

`scripts/demo_session.py` 가 첫 분석 → 같은 session_id 로 follow-up 대화를 ENABLE.

```bash
# 1. PoC case 자동 inject + trigger + 분석
.venv/bin/python scripts/demo_session.py --case E001

# 2. 직접 로그 분석
.venv/bin/python scripts/demo_session.py --log "$(cat /tmp/error.log)"

# 3. 단순 prompt
.venv/bin/python scripts/demo_session.py --prompt "안녕"
```

흐름: 첫 호출에서 `session_id` 발급 → REPL (`You>` 프롬프트) → 같은 session_id 로 follow-up. Ctrl+C 또는 빈 입력으로 종료.

`MACRO_LOGBOT_API_KEY` 환경변수 또는 `--api-key` 명시 필요.

---

## 트러블슈팅

### "permission denied while trying to connect to the Docker daemon socket"

```bash
sudo usermod -aG docker $USER
# logout 후 재로그인
newgrp docker   # 재로그인 없이 즉시 적용 (현재 세션만)
```

### Gemini RateLimitError 429 (quota exceeded)

무료 한도 초과. 해결 방법:

- `MACRO_LOGBOT_DEFAULT_MODEL=gemini/gemini-2.5-flash-lite` 로 변경 (Flash 대비 50배 높은 무료 한도 1000 RPD).
- 사내 LLM endpoint 로 전환 (`MACRO_LOGBOT_LLM_BASE_URL` + `MACRO_LOGBOT_LLM_API_KEY` 설정).

### 사내 mirror 에 패키지 없음

```
ERROR: Could not find a version that satisfies the requirement ...
```

- `.env` 의 `PIP_INDEX_URL` 이 올바른 사내 PyPI mirror URL 인지 확인.
- `BASE_IMAGE` 가 사내 registry 에 존재하는지 확인 (`docker pull <BASE_IMAGE>` 테스트).

### WSL2 환경 메모리 부족

`C:\Users\<계정>\.wslconfig` (Windows 호스트):

```ini
[wsl2]
memory=8GB
processors=4
```

변경 후 `wsl --shutdown` + WSL2 재시작.

### 컨테이너 로그 확인

```bash
docker compose logs -f macro-logbot-backend
docker compose logs -f open-webui
```

### 서비스 재시작 / 중지

```bash
docker compose restart macro-logbot-backend
docker compose down
docker compose down -v   # 볼륨(Open WebUI 데이터) 포함 삭제
```

---

## 운영 진입 전 체크리스트

현재 MVP/PoC 단계. **사내 운영 투입 전** 아래 task 완료 필수 (`docs/process/FOLLOWUP-TASKS.md` 참조):

| Task ID | 항목 | 우선순위 |
|---|---|---|
| task-SEC-002 | 운영 진입 인증 (SSO/OAuth 통합) | 필수 |
| task-MVP-006 | Tool 보안 강화 (symlink / control char 차단) | 필수 |
| task-SEC-012 | KB env path containment | 필수 |
| task-OPS-001 | Dockerfile multi-stage (image 경량화) | 권장 |
| task-SEC-009 | Supply chain — image digest pinning + pip hash | 권장 |
| task-MVP-002-y | Session retention 30일 cleanup | 권장 |

---

## 사내 배포 진행 상황 (2026-05-20 기준)

| 항목 | 상태 | 비고 |
|---|---|---|
| 사내 build 정상 | ✅ 완료 | 사내 미러 + `APT_MIRROR` / `PIP_TRUSTED_HOST` 설정으로 외부 인터넷 없이 빌드 성공 |
| 사내 runtime 기동 | ✅ 완료 | backend container + Open WebUI 정상 기동 확인 |
| 사내 LLM tool 지원 확인 | ✅ 완료 | multi-turn tool calling 지원 확인 (A-2 가정 검증 완료). 운영 가능 단계 진입 |
| 사내 LLM 허가 | ⚠️ 대기 중 | 허가 미보유 → 사내 측정은 사용자 직접만 가능. main Claude 의 사내 측정 실행 불가 |
| 사내 측정 + 평가 | 🔜 예정 | 사내 LLM 허가 획득 후 사용자 직접 `evaluate.py` 실행 |

> **Note**: 사내 배포 환경에서 `docker compose up -d --build` 성공 = NFR-6 (Deployment Portability) 1차 검증 완료. AC-6 (사내 미러만으로 빌드·런타임 성공) 달성.

---

## 관련 문서

- [`.env.example`](../../.env.example) — 전체 환경변수 목록 + 주석
- [`docker-compose.yml`](../../docker-compose.yml) — 서비스 정의
- [`docs/process/FOLLOWUP-TASKS.md`](../process/FOLLOWUP-TASKS.md) — 후속 task 큐
- [`docs/design/02-설계문서.md`](../design/02-설계문서.md) — §8.4 사내 LLM 통합 상세
