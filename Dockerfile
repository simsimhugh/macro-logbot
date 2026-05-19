# macro-logbot backend — Open WebUI MVP demo image.
#
# NOTE: pyproject.toml 의 requires-python = ">=3.14" 제약 때문에 base 도
# Python 3.14 가 필요하다. python:3.14-slim 이 가용하지 않으면 빌드 단계에서
# 명시적으로 실패시켜 호환성을 보고하도록 한다 (silent downgrade 금지).
#
# 사외 PoC default. 사내 운영은 build args 로 사내 mirror swap.
#   docker compose build --build-arg BASE_IMAGE=<사내-registry>/python:3.14-slim \
#                        --build-arg PIP_INDEX_URL=https://<사내-pypi>/simple
ARG BASE_IMAGE=python:3.14-slim
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG APT_MIRROR=""
ARG PIP_TRUSTED_HOST=""

FROM ${BASE_IMAGE} AS runtime

# Docker ARG scope: FROM 이전 ARG (global) 는 FROM line 안에서만 유효 —
# stage 안에서 ENV/RUN 에 참조하려면 stage 안에서 재선언 필수.
# APT_MIRROR / PIP_TRUSTED_HOST 는 사용 직전 (line 26, 47) 재선언돼서 동작 중.
# PIP_INDEX_URL 만 누락되어 있어 ENV 가 빈 값으로 expand 되던 문제 (PR #29 잔존).
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 사내 apt mirror swap (APT_MIRROR 비어 있으면 skip — 사외 PoC 기본 동작 유지).
ARG APT_MIRROR
RUN [ -z "${APT_MIRROR}" ] || { \
        printf "deb %s trixie main\ndeb %s trixie-updates main\n" \
            "${APT_MIRROR}" "${APT_MIRROR}" > /etc/apt/sources.list \
        && rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; \
    }

# 시스템 빌드 의존성 (litellm/pydantic transitive 휠 빌드 대비 — slim 이므로 최소).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# 의존성 캐시 — 메타데이터 먼저 복사.
COPY pyproject.toml README.md ./
COPY src ./src

# production install — dev tools (pytest/ruff/mypy) 제외.
# PIP_TRUSTED_HOST 있으면 사내 mirror 인증서 검증 skip (self-signed CA 환경 우회).
# 보안 trade-off: MITM 방어 약화 + supply-chain 무결성 검증 우회. 정공법은 사내 CA bundle
# 을 image 에 COPY 또는 컨테이너에 마운트. `--trusted-host` 는 HTTP / self-signed 환경
# 임시 우회용으로만 사용 (architect WARN-1 PR #29).
ARG PIP_TRUSTED_HOST
RUN pip install --upgrade pip \
    && pip install . ${PIP_TRUSTED_HOST:+--trusted-host ${PIP_TRUSTED_HOST}}

# build-time import smoke — 의존성 누락/3.14 휠 부재 등을 런타임 전에 즉시 검출.
RUN python -c "import macro_logbot, macro_logbot.app, macro_logbot.auth"

# non-root user — MVP 보안 baseline.
RUN useradd --create-home --uid 10001 macrologbot \
    && chown -R macrologbot:macrologbot /app
USER macrologbot

EXPOSE 8000

CMD ["uvicorn", "macro_logbot.app:app", "--host", "0.0.0.0", "--port", "8000"]
