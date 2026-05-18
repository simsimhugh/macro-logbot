"""In-memory Session store (MVP).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.4

NOTE: spec 은 SQLite 영속화를 명시하지만 MVP 는 단일 프로세스 in-memory.
영속화는 FOLLOWUP (session-store).
"""

from macro_logbot.session.store import InMemorySessionStore, Session

__all__ = ["InMemorySessionStore", "Session"]
