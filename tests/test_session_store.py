"""InMemorySessionStore 단위 테스트."""

from __future__ import annotations

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


def test_update_refreshes_updated_at() -> None:
    store = InMemorySessionStore()
    s = store.create()
    s.messages.append(Message(role="user", content="hi"))
    before = s.updated_at
    store.update(s)
    assert s.updated_at >= before
    fetched = store.get(s.id)
    assert fetched is not None
    assert len(fetched.messages) == 1


def test_delete_returns_true_then_false() -> None:
    store = InMemorySessionStore()
    s = store.create()
    assert store.delete(s.id) is True
    assert store.delete(s.id) is False
    assert store.get(s.id) is None
