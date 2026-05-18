"""API key 인증 미들웨어.

Open WebUI 와 macro-logbot 간 공유 단일 API key 인증.

- `MACRO_LOGBOT_API_KEY` env var 에서 key 로드 (다중 사용자/role 은 후속).
- `Authorization: Bearer <key>` 또는 `X-API-Key: <key>` 헤더 검사.
- key 미설정 시 동작은 `MACRO_LOGBOT_AUTH_REQUIRED` 에 따라 분기:
  * "true"/"1"/"yes" → 503 (서비스 misconfigured)
  * 그 외/미설정 → 인증 skip + WARN 로깅 (dev/PoC 모드 기본)

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1 External Interfaces
FOLLOWUP task-SEC-002 (본 PR 안 처리).
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

_API_KEY_ENV = "MACRO_LOGBOT_API_KEY"
_AUTH_REQUIRED_ENV = "MACRO_LOGBOT_AUTH_REQUIRED"
_WWW_AUTH_HEADER = {"WWW-Authenticate": "Bearer"}


def _auth_required() -> bool:
    """`MACRO_LOGBOT_AUTH_REQUIRED` env var 가 truthy 면 True."""
    raw = os.environ.get(_AUTH_REQUIRED_ENV, "").strip().lower()
    return raw in {"true", "1", "yes", "on"}


def _extract_token(request: Request) -> str | None:
    """Authorization Bearer 또는 X-API-Key 헤더에서 토큰 추출."""
    auth = request.headers.get("Authorization")
    if auth:
        # 대소문자 무시 — RFC 7235 는 scheme 을 case-insensitive 로 규정.
        parts = auth.split(maxsplit=1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            if token:
                return token
    x_api_key = request.headers.get("X-API-Key")
    if x_api_key:
        token = x_api_key.strip()
        if token:
            return token
    return None


async def verify_api_key(request: Request) -> None:
    """FastAPI dependency — API key 검증.

    동작:
      - server key 미설정 + AUTH_REQUIRED=true → 503.
      - server key 미설정 + AUTH_REQUIRED=false → WARN 로깅 후 통과 (dev 모드).
      - client token 누락 → 401 "missing API key".
      - client token 불일치 → 401 "invalid API key".
      - 일치 → 통과.
    """
    server_key = os.environ.get(_API_KEY_ENV, "").strip()
    if not server_key:
        if _auth_required():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="server API key not configured",
            )
        # dev/PoC 모드 — 인증 skip.
        logger.warning(
            "%s not set and %s is not true — authentication is DISABLED (dev mode)",
            _API_KEY_ENV,
            _AUTH_REQUIRED_ENV,
        )
        return

    token = _extract_token(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing API key",
            headers=_WWW_AUTH_HEADER,
        )
    if token != server_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
            headers=_WWW_AUTH_HEADER,
        )


__all__ = ["verify_api_key"]
