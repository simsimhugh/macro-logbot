#!/usr/bin/env bash
# macro-logbot 원샷 배포 스크립트
# 사용법: ./scripts/deploy.sh
# Ubuntu 22.04 LTS 기준. 사전 요구사항: docker, docker compose v2, git

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== macro-logbot 배포 시작 ==="
echo "경로: ${REPO_ROOT}"

# ────────────────────────────────────────────
# 1. Pre-flight: 필수 도구 확인
# ────────────────────────────────────────────

check_command() {
  local cmd="$1"
  local install_hint="$2"
  if ! command -v "${cmd}" > /dev/null 2>&1; then
    echo ""
    echo "[오류] '${cmd}' 를 찾을 수 없습니다."
    echo "설치 방법: ${install_hint}"
    exit 1
  fi
}

echo ""
echo "--- 사전 요구사항 확인 ---"

check_command docker \
  "sudo apt update && sudo apt install -y docker.io && sudo usermod -aG docker \$USER"

# docker compose v2 (plugin) 확인
if ! docker compose version > /dev/null 2>&1; then
  echo ""
  echo "[오류] 'docker compose' (v2) 를 찾을 수 없습니다."
  echo "설치 방법: sudo apt update && sudo apt install -y docker-compose-v2"
  echo "           (또는 Docker Desktop v2.4+ 사용)"
  exit 1
fi

check_command git \
  "sudo apt update && sudo apt install -y git"

DOCKER_VERSION="$(docker --version)"
COMPOSE_VERSION="$(docker compose version)"
GIT_VERSION="$(git --version)"

echo "  docker  : ${DOCKER_VERSION}"
echo "  compose : ${COMPOSE_VERSION}"
echo "  git     : ${GIT_VERSION}"
echo ""

# ────────────────────────────────────────────
# 2. .env 파일 확인
# ────────────────────────────────────────────

echo "--- .env 파일 확인 ---"

ENV_FILE="${REPO_ROOT}/.env"
ENV_EXAMPLE="${REPO_ROOT}/.env.example"

if [ ! -f "${ENV_FILE}" ]; then
  if [ -f "${ENV_EXAMPLE}" ]; then
    echo ""
    echo "[오류] .env 파일이 없습니다."
    echo "아래 명령으로 생성 후 편집해 주세요:"
    echo ""
    echo "  cp .env.example .env"
    echo "  nano .env  # 또는 vi .env"
    echo ""
    echo "  필수 항목:"
    echo "    MACRO_LOGBOT_API_KEY=<임의 문자열>"
    echo "    GEMINI_API_KEY=<Gemini API key>  # 사외 PoC 의 경우"
    echo ""
    echo "  사내 운영의 경우 추가:"
    echo "    BASE_IMAGE=<사내-registry>/python:3.14-slim"
    echo "    PIP_INDEX_URL=https://<사내-pypi>/simple"
    echo "    OPEN_WEBUI_IMAGE=<사내-registry>/open-webui:main"
    echo "    MACRO_LOGBOT_LLM_BASE_URL=https://<사내-llm-endpoint>"
    echo "    MACRO_LOGBOT_LLM_API_KEY=<사내 LLM key>"
  else
    echo ""
    echo "[오류] .env.example 도 없습니다. 저장소가 올바르게 clone 되었는지 확인하세요."
  fi
  exit 1
fi

echo "  .env 파일 확인됨."

# ────────────────────────────────────────────
# 3. 필수 환경변수 확인
# ────────────────────────────────────────────

echo ""
echo "--- 필수 환경변수 확인 ---"

# .env 에서 값 추출 (주석·공백 제거)
get_env_val() {
  local key="$1"
  # shellcheck disable=SC2155
  local val
  val="$(grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs 2>/dev/null || true)"
  echo "${val}"
}

API_KEY="$(get_env_val MACRO_LOGBOT_API_KEY)"

if [ -z "${API_KEY}" ] || [ "${API_KEY}" = "__SET_A_REAL_KEY__" ]; then
  echo ""
  echo "[오류] MACRO_LOGBOT_API_KEY 가 설정되지 않았습니다."
  echo ".env 에서 아래 줄을 실제 값으로 변경하세요:"
  echo ""
  echo "  MACRO_LOGBOT_API_KEY=<임의 문자열>"
  echo ""
  exit 1
fi

echo "  MACRO_LOGBOT_API_KEY 확인됨."
echo ""

# ────────────────────────────────────────────
# 4. docker compose up
# ────────────────────────────────────────────

echo "--- 서비스 기동 ---"
echo "  docker compose up -d --build"
echo ""

cd "${REPO_ROOT}"
docker compose up -d --build

echo ""
echo "--- 서비스 기동 완료. 헬스 체크 대기 중 (최대 60초) ---"

# ────────────────────────────────────────────
# 5. 헬스 체크 (최대 60초)
# ────────────────────────────────────────────

HEALTH_URL="http://localhost:8000/health"
MAX_WAIT=60
INTERVAL=5
elapsed=0
healthy=false

while [ "${elapsed}" -lt "${MAX_WAIT}" ]; do
  if curl -sf "${HEALTH_URL}" > /dev/null 2>&1; then
    healthy=true
    break
  fi
  echo "  대기 중... (${elapsed}s / ${MAX_WAIT}s)"
  sleep "${INTERVAL}"
  elapsed=$((elapsed + INTERVAL))
done

echo ""

if [ "${healthy}" = "true" ]; then
  HEALTH_RESP="$(curl -sf "${HEALTH_URL}")"
  echo "=== 배포 성공 ==="
  echo ""
  echo "  헬스 체크: ${HEALTH_RESP}"
  echo ""
  echo "  백엔드  : http://localhost:8000"
  echo "  Open WebUI: http://localhost:3000"
  echo ""
  echo "  다음 단계:"
  echo "  1. http://localhost:3000 브라우저 접속"
  echo "  2. 모델 선택 → 채팅 시작"
  echo "  3. MACRO 에러 로그는 http://localhost:8000/agent/analyze 로 POST"
  echo ""
  echo "  상세 가이드: docs/operations/DEPLOYMENT.md"
else
  echo "=== 경고: 헬스 체크 타임아웃 (${MAX_WAIT}s) ==="
  echo ""
  echo "백엔드가 아직 준비되지 않았을 수 있습니다. 로그를 확인하세요:"
  echo ""
  docker compose logs --tail=30 macro-logbot-backend
  echo ""
  echo "수동 확인: curl http://localhost:8000/health"
  exit 1
fi
