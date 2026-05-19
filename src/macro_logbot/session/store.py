"""Session 저장소 — InMemorySessionStore (단위 테스트/fallback) + SQLiteSessionStore (영속화).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.4
"""

from __future__ import annotations

import contextlib
import json
import os
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

    def create(self) -> Session:
        """새 Session 을 생성하고 저장한 뒤 반환."""
        ...

    def get(self, id: str) -> Session | None:
        """id 로 Session 조회. 없으면 None."""
        ...

    def update(self, session: Session) -> None:
        """기존 Session 의 messages/updated_at 을 영속화.

        존재하지 않는 id 에 대한 동작은 backend 마다 다르다 — InMemory 는 upsert,
        SQLite 는 silent no-op. 두 의미를 통일하는 작업은 task-MVP-004 (endpoint
        session 통합) 시점.
        """
        ...

    def delete(self, id: str) -> bool:
        """id 의 Session 을 삭제. 실제 삭제됐으면 True, 없었으면 False."""
        ...


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
    # exclude_none — None default 필드 (tool_calls / tool_call_id / name / content)
    # 가 row 당 직렬화되지 않도록 storage bloat 회피. Pydantic v2 의 model_validate
    # 가 missing optional → None 으로 복원하므로 round-trip 안전.
    return json.dumps([m.model_dump(exclude_none=True) for m in messages])


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
        # 시크릿이 우연히 LLM message 에 echo 될 수 있어 (task-SEC-008) DB 파일은
        # owner-only 권한으로 강제. WAL/SHM 부수 파일도 동일 처리.
        # 부수 파일 미생성 (WAL mode 진입 전) 또는 Windows umask — silent skip.
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.chmod(self._db_path + suffix, 0o600)

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
