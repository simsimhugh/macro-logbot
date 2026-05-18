"""Session 저장소 — 단일 프로세스 dict 기반.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.4
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from macro_logbot.gateway import Message


def _now() -> datetime:
    return datetime.now(UTC)


class Session(BaseModel):
    id: str
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class InMemorySessionStore:
    """단순 dict 백엔드. FastAPI single-process 가정 (thread-safety 불요)."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = str(uuid.uuid4())
        session = Session(id=sid)
        self._sessions[sid] = session
        return session

    def get(self, id: str) -> Session | None:
        return self._sessions.get(id)

    def update(self, session: Session) -> None:
        session.updated_at = _now()
        self._sessions[session.id] = session

    def delete(self, id: str) -> bool:
        return self._sessions.pop(id, None) is not None
