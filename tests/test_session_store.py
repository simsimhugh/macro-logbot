"""InMemorySessionStore + SQLiteSessionStore 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from macro_logbot.gateway import Message
from macro_logbot.session import (
    InMemorySessionStore,
    SessionStore,
    SQLiteSessionStore,
)

# ---------------------------------------------------------------------------
# InMemorySessionStore — 기존 테스트 유지
# ---------------------------------------------------------------------------


def test_create_returns_unique_session() -> None:
    store = InMemorySessionStore()
    a = store.create()
    b = store.create()
    assert a.id != b.id
    assert a.messages == []
    assert a.created_at <= a.updated_at


def test_get_returns_none_for_missing() -> None:
    store = InMemorySessionStore()
    assert store.get("missing") is None


def test_update_refreshes_updated_at(monkeypatch: pytest.MonkeyPatch) -> None:
    """_now 를 monkeypatch 하여 update 가 실제로 시각을 갱신함을 엄밀 검증."""
    from macro_logbot.session import store as store_module

    # 시간을 단조 증가하도록 monkeypatch (create → update 사이 1초 진행).
    times = iter(
        [
            datetime(2026, 5, 19, 10, 0, 0, tzinfo=UTC),
            datetime(2026, 5, 19, 10, 0, 0, tzinfo=UTC),  # Session 생성 created_at + updated_at
            datetime(2026, 5, 19, 10, 0, 1, tzinfo=UTC),  # update 후 updated_at
        ]
    )
    monkeypatch.setattr(store_module, "_now", lambda: next(times))

    store = InMemorySessionStore()
    s = store.create()
    s.messages.append(Message(role="user", content="hi"))
    before = s.updated_at
    store.update(s)
    assert s.updated_at > before
    fetched = store.get(s.id)
    assert fetched is not None
    assert len(fetched.messages) == 1


def test_delete_returns_true_then_false() -> None:
    store = InMemorySessionStore()
    s = store.create()
    assert store.delete(s.id) is True
    assert store.delete(s.id) is False
    assert store.get(s.id) is None


# ---------------------------------------------------------------------------
# SQLiteSessionStore — 신규 테스트
# ---------------------------------------------------------------------------


def test_sqlite_store_create_and_get(tmp_path: Path) -> None:
    """create → get round-trip 검증."""
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    session = store.create()
    fetched = store.get(session.id)
    assert fetched is not None
    assert fetched.id == session.id
    assert fetched.messages == []
    assert fetched.created_at == session.created_at


def test_sqlite_store_persistence(tmp_path: Path) -> None:
    """같은 db_path 로 두 번 init — 첫 store 에 create 한 session 이 두 번째 store 에서 조회 가능.

    in-memory 와 달리 SQLiteSessionStore 는 프로세스 재시작 후에도 데이터 유지.
    """
    db_path = tmp_path / "sessions.db"
    store1 = SQLiteSessionStore(db_path)
    session = store1.create()

    # 두 번째 인스턴스 — 프로세스 재시작 시뮬레이션
    store2 = SQLiteSessionStore(db_path)
    fetched = store2.get(session.id)
    assert fetched is not None
    assert fetched.id == session.id


def test_sqlite_store_update_messages(tmp_path: Path) -> None:
    """메시지 추가 후 update → get — Pydantic Message rehydrate (role/content) 검증."""
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    session = store.create()

    session.messages.append(Message(role="user", content="안녕하세요"))
    session.messages.append(Message(role="assistant", content="무엇을 도와드릴까요?"))
    store.update(session)

    fetched = store.get(session.id)
    assert fetched is not None
    assert len(fetched.messages) == 2
    assert fetched.messages[0].role == "user"
    assert fetched.messages[0].content == "안녕하세요"
    assert fetched.messages[1].role == "assistant"
    assert fetched.updated_at >= session.updated_at


def test_sqlite_store_delete(tmp_path: Path) -> None:
    """delete 후 get → None, 두 번째 delete → False."""
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    session = store.create()
    assert store.delete(session.id) is True
    assert store.get(session.id) is None
    assert store.delete(session.id) is False


def test_sqlite_store_protocol(tmp_path: Path) -> None:
    """SQLiteSessionStore 와 InMemorySessionStore 모두 SessionStore Protocol 을 충족."""
    sqlite_store: SessionStore = SQLiteSessionStore(tmp_path / "sessions.db")
    mem_store: SessionStore = InMemorySessionStore()

    # isinstance 는 runtime_checkable Protocol 에서 structural check (method 존재 여부)
    assert isinstance(sqlite_store, SessionStore)
    assert isinstance(mem_store, SessionStore)

    # duck-typing: 실제 동작도 Protocol 메서드 시그니처대로 수행됨
    s = sqlite_store.create()
    assert sqlite_store.get(s.id) is not None
    sqlite_store.update(s)
    assert sqlite_store.delete(s.id) is True
