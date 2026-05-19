"""Knowledge Base 저장소 — ArchivedCase 모델 + KBStore Protocol + SQLiteKBStore.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.5

Phase 1: keyword substring 매칭 (LIKE). Phase 2 벡터 임베딩은 task-KB-001 후속.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class Location(BaseModel):
    """ArchivedCase.location — spec §5.5 line 220 의 file/function/line 3-키 강제."""

    file: str
    function: str
    # line 은 1-indexed (소스 파일 line 번호) — 0/음수 거절.
    line: int = Field(ge=1)


class ArchivedCase(BaseModel):
    """분석 완료된 에러 케이스 아카이브 — spec §5.5 line 216~225."""

    case_id: str
    timestamp: datetime = Field(default_factory=_now)
    error_signature: str
    category: str
    root_cause: str
    location: Location
    fix_hint: str
    # confidence 는 spec §5.5 정합 [0, 1] — Pydantic 차원에서 강제 (음수/2.5 거절).
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["poc", "production", "verified-master"]
    # mutable default 회피 — Pydantic v2 권장 (default_factory).
    tags: list[str] = Field(default_factory=list)
    related_code_refs: list[str] = Field(default_factory=list)


@runtime_checkable
class KBStore(Protocol):
    """Knowledge Base 저장소 Protocol — SQLiteKBStore 공통 인터페이스."""

    def add(self, case: ArchivedCase) -> None:
        """ArchivedCase 를 저장소에 추가."""
        ...

    def get(self, case_id: str) -> ArchivedCase | None:
        """case_id 로 ArchivedCase 조회. 없으면 None."""
        ...

    def search(self, query: str, top_k: int = 5) -> list[ArchivedCase]:
        """query 로 유사 케이스 검색.

        Phase 1: error_signature 또는 root_cause 에 query substring 이 포함된 케이스.
        결과는 confidence 내림차순 정렬, top_k 제한.
        Phase 2 (벡터 임베딩) 은 task-KB-001 후속.
        """
        ...


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS archived_cases (
    case_id             TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,
    error_signature     TEXT NOT NULL,
    category            TEXT NOT NULL,
    root_cause          TEXT NOT NULL,
    location_json       TEXT NOT NULL,
    fix_hint            TEXT NOT NULL,
    confidence          REAL NOT NULL,
    source              TEXT NOT NULL,
    tags_json           TEXT NOT NULL DEFAULT '[]',
    related_code_refs_json TEXT NOT NULL DEFAULT '[]'
)
"""


def _serialize_location(location: Location) -> str:
    return location.model_dump_json()


def _deserialize_location(raw: str) -> Location:
    return Location.model_validate_json(raw)


def _serialize_list(items: list[str]) -> str:
    return json.dumps(items)


def _deserialize_list(raw: str) -> list[str]:
    result: list[str] = json.loads(raw)
    return result


def _row_to_case(row: tuple[Any, ...]) -> ArchivedCase:
    (
        case_id,
        timestamp_str,
        error_signature,
        category,
        root_cause,
        location_json,
        fix_hint,
        confidence,
        source,
        tags_json,
        related_code_refs_json,
    ) = row
    return ArchivedCase(
        case_id=case_id,
        timestamp=datetime.fromisoformat(timestamp_str),
        error_signature=error_signature,
        category=category,
        root_cause=root_cause,
        location=_deserialize_location(location_json),
        fix_hint=fix_hint,
        confidence=confidence,
        source=source,
        tags=_deserialize_list(tags_json),
        related_code_refs=_deserialize_list(related_code_refs_json),
    )


class SQLiteKBStore:
    """SQLite 영속 Knowledge Base 저장소.

    - 표준 라이브러리 sqlite3 만 사용 (신규 dep 없음).
    - WAL 모드 + per-call connection: FastAPI async 환경에서 safe.
    - DB 파일 owner-only 권한 (0o600) 강제 — 사내 코드/로그 정보 보호.
    - search Phase 1: error_signature LIKE ? OR root_cause LIKE ? (keyword substring).
      Phase 2 벡터 임베딩은 task-KB-001 후속.
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
        # KB 본문(root_cause · fix_hint · related_code_refs)에 사내 코드/로그 정보가
        # 들어갈 수 있으므로 DB 파일은 owner-only 권한으로 강제 (spec §5.5 보안 주의).
        # WAL/SHM 부수 파일도 동일. 미생성 또는 Windows umask — silent skip.
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.chmod(self._db_path + suffix, 0o600)

    def add(self, case: ArchivedCase) -> None:
        """ArchivedCase 를 archived_cases 테이블에 INSERT."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO archived_cases (
                    case_id, timestamp, error_signature, category, root_cause,
                    location_json, fix_hint, confidence, source,
                    tags_json, related_code_refs_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    case.case_id,
                    case.timestamp.isoformat(),
                    case.error_signature,
                    case.category,
                    case.root_cause,
                    _serialize_location(case.location),
                    case.fix_hint,
                    case.confidence,
                    case.source,
                    _serialize_list(case.tags),
                    _serialize_list(case.related_code_refs),
                ),
            )
            conn.commit()

    def get(self, case_id: str) -> ArchivedCase | None:
        """case_id 로 ArchivedCase 조회. 없으면 None."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT case_id, timestamp, error_signature, category, root_cause,
                       location_json, fix_hint, confidence, source,
                       tags_json, related_code_refs_json
                FROM archived_cases WHERE case_id=?
                """,
                (case_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_case(row)

    def search(self, query: str, top_k: int = 5) -> list[ArchivedCase]:
        """Phase 1 keyword substring 매칭.

        error_signature LIKE '%query%' OR root_cause LIKE '%query%'.
        결과를 confidence 내림차순 정렬, top_k 제한.
        """
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT case_id, timestamp, error_signature, category, root_cause,
                       location_json, fix_hint, confidence, source,
                       tags_json, related_code_refs_json
                FROM archived_cases
                WHERE error_signature LIKE ? OR root_cause LIKE ?
                ORDER BY confidence DESC
                LIMIT ?
                """,
                (pattern, pattern, top_k),
            ).fetchall()
        return [_row_to_case(row) for row in rows]
