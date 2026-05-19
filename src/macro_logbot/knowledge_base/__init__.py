"""Knowledge Base 패키지 — ArchivedCase 모델 + KBStore Protocol + SQLiteKBStore.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.5
"""

from macro_logbot.knowledge_base.store import (
    ArchivedCase,
    KBStore,
    SQLiteKBStore,
)

__all__ = ["ArchivedCase", "KBStore", "SQLiteKBStore"]
