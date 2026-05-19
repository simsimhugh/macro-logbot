"""Session 저장소 — InMemorySessionStore (단위 테스트/fallback) + SQLiteSessionStore (영속화).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.4
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from macro_logbot.gateway import Message


def _now() -> datetime:
    return datetime.now(UTC)


class Session(BaseModel):
    id: str
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


@runtime_checkable
class SessionStore(Protocol):
    """Session 저장소 Protocol — InMemorySessionStore / SQLiteSessionStore 공통 인터페이스."""

    def create(self) -> Session: ...

    def get(self, id: str) -> Session | None: ...

    def update(self, session: Session) -> None: ...

    def delete(self, id: str) -> bool: ...


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


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    messages_json TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""


def _serialize_messages(messages: list[Message]) -> str:
    return json.dumps([m.model_dump() for m in messages])


def _deserialize_messages(raw: str) -> list[Message]:
    return [Message.model_validate(obj) for obj in json.loads(raw)]


class SQLiteSessionStore:
    """SQLite 영속 저장소.

    - 표준 라이브러리 sqlite3 만 사용 (신규 dep 없음).
    - WAL 모드 + per-call connection: FastAPI async 환경에서 safe.
    - MVP 단순화: messages 만 직렬화. tool_history / follow_up_messages / report 컬럼 확장은
      task-MVP-002-x 후속.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.commit()

    def create(self) -> Session:
        session = Session(id=str(uuid.uuid4()))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, messages_json, created_at, updated_at) VALUES (?,?,?,?)",
                (
                    session.id,
                    _serialize_messages(session.messages),
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            conn.commit()
        return session

    def get(self, id: str) -> Session | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, messages_json, created_at, updated_at FROM sessions WHERE id=?",
                (id,),
            ).fetchone()
        if row is None:
            return None
        sid, messages_json, created_at_str, updated_at_str = row
        return Session(
            id=sid,
            messages=_deserialize_messages(messages_json),
            created_at=datetime.fromisoformat(created_at_str),
            updated_at=datetime.fromisoformat(updated_at_str),
        )

    def update(self, session: Session) -> None:
        session.updated_at = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET messages_json=?, updated_at=? WHERE id=?",
                (
                    _serialize_messages(session.messages),
                    session.updated_at.isoformat(),
                    session.id,
                ),
            )
            conn.commit()

    def delete(self, id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE id=?", (id,))
            conn.commit()
        return cursor.rowcount > 0
