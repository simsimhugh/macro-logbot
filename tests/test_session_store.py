"""InMemorySessionStore 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from macro_logbot.gateway import Message
from macro_logbot.session import InMemorySessionStore


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
