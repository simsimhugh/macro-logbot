"""MACRO 에러 로그 간단 regex 파서 (PoC 수준).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1

지원 패턴 (첫 줄):
  YYYY-MM-DD HH:MM:SS LEVEL: message

LEVEL 은 영문 (DEBUG/INFO/WARN/WARNING/ERROR/CRITICAL/FATAL). 한국어 level
은 본 PoC scope 밖 — raw 만 채워서 반환.

Traceback 은 'Traceback (most recent call last):' 라인부터 끝까지 추출.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel

_HEADER_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    # 긴 alternative 먼저 — 'WARN' 이 'WARNING' 보다 먼저 매치되면
    # 'ING' 가 message 로 누수됨.
    r"\s+(?P<level>WARNING|CRITICAL|DEBUG|INFO|WARN|ERROR|FATAL)\b"
    r"\s*[:\-]?\s*(?P<msg>.*)$"
)

_TRACEBACK_MARKER = "Traceback (most recent call last):"


class IntakeRecord(BaseModel):
    timestamp: datetime | None = None
    level: str | None = None
    message: str
    traceback: str | None = None
    raw: str


def parse_macro_log(text: str) -> IntakeRecord:
    """raw log 텍스트를 IntakeRecord 로 파싱.

    실패 시 message=text(첫 줄), raw=원본, 나머지 None.
    """
    raw = text
    lines = text.splitlines()
    first = lines[0] if lines else ""

    match = _HEADER_RE.match(first)
    ts: datetime | None = None
    level: str | None = None
    msg: str = first.strip()

    if match:
        ts_str = match.group("ts").replace("T", " ")
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            ts = None
        level = match.group("level").upper()
        # WARNING → WARN 정규화 (spec 일관성).
        if level == "WARNING":
            level = "WARN"
        msg = match.group("msg").strip()

    traceback: str | None = None
    if _TRACEBACK_MARKER in text:
        idx = text.index(_TRACEBACK_MARKER)
        traceback = text[idx:].rstrip()

    return IntakeRecord(
        timestamp=ts,
        level=level,
        message=msg,
        traceback=traceback,
        raw=raw,
    )
