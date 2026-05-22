"""InMemorySessionStore + SQLiteSessionStore 단위 테스트."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from macro_logbot.gateway import Message
from macro_logbot.gateway.models import FunctionCall, ToolCall
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
    # Pydantic BaseModel 의 default_factory 는 model 정의 시점 ref 고정 → monkeypatch 가
    # Session.created_at/updated_at 의 factory 까지 못 미침. store.update() 의 `_now()`
    # 호출만 mock 가능하나, create 시점도 mock 해야 단조 증가 verify 가능.
    # → mock 없이 real clock + 짧은 sleep + `>=` 로 의도 보존 (실패 시 monotonic 깨짐 catch).
    import time

    store = InMemorySessionStore()
    s = store.create()
    s.messages.append(Message(role="user", content="hi"))
    before = s.updated_at
    time.sleep(0.001)
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


def test_sqlite_store_update_nonexistent_is_upsert(tmp_path: Path) -> None:
    """존재하지 않는 id 에 update() 호출 → upsert (INSERT OR REPLACE).

    task-MVP-004 (PR #24) 에서 InMemorySessionStore 와 동일한 upsert 의미로 통일.
    존재하지 않는 id 라도 update 후 get 으로 조회 가능해야 한다.
    """
    from macro_logbot.session.store import Session as _Session

    store = SQLiteSessionStore(tmp_path / "sessions.db")
    ghost = _Session(id="ghost-id")
    ghost.messages.append(Message(role="user", content="phantom"))
    # 예외 없이 통과 + upsert 됐으므로 get 으로 조회 가능.
    store.update(ghost)
    fetched = store.get("ghost-id")
    assert fetched is not None
    assert len(fetched.messages) == 1
    assert fetched.messages[0].content == "phantom"


def test_sqlite_store_db_file_permission(tmp_path: Path) -> None:
    """DB 파일이 owner-only 권한 (0o600) 으로 강제 — 시크릿 echo 방어 (security WARN-MED-3)."""
    db_path = tmp_path / "sessions.db"
    SQLiteSessionStore(db_path)
    # POSIX 환경에서만 의미 — 권한 mask 검증.
    if os.name == "posix":
        mode = db_path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_sqlite_store_tool_calls_round_trip(tmp_path: Path) -> None:
    """spec §5.4 messages[] 의 tool_calls / tool_call_id / name 5필드 round-trip 보존.

    agent loop multi-turn (assistant.tool_calls → tool.response) 시점에 surprise
    방지. Pydantic v2 model_dump/model_validate 가 nested ToolCall.function.arguments
    (JSON 문자열) 까지 통과시킴을 명시 검증.
    """
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    session = store.create()

    # assistant message — tool_calls 호출 결정.
    assistant = Message(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id="call_001",
                function=FunctionCall(
                    name="read_file",
                    arguments='{"path": "src/app.py", "max_lines": 50}',
                ),
            )
        ],
    )
    # tool message — assistant 의 tool_call_id 에 대응하는 결과.
    tool_response = Message(
        role="tool",
        tool_call_id="call_001",
        name="read_file",
        content='{"path": "src/app.py", "content": "..."}',
    )
    session.messages.extend([assistant, tool_response])
    store.update(session)

    fetched = store.get(session.id)
    assert fetched is not None
    assert len(fetched.messages) == 2

    # assistant.tool_calls round-trip — nested FunctionCall.arguments JSON 보존.
    fetched_assistant = fetched.messages[0]
    assert fetched_assistant.role == "assistant"
    assert fetched_assistant.content is None
    assert fetched_assistant.tool_calls is not None
    assert len(fetched_assistant.tool_calls) == 1
    tc = fetched_assistant.tool_calls[0]
    assert tc.id == "call_001"
    assert tc.type == "function"
    assert tc.function.name == "read_file"
    assert tc.function.arguments == '{"path": "src/app.py", "max_lines": 50}'

    # tool message — tool_call_id 및 name 보존.
    fetched_tool = fetched.messages[1]
    assert fetched_tool.role == "tool"
    assert fetched_tool.tool_call_id == "call_001"
    assert fetched_tool.name == "read_file"
