"""SQLiteKBStore + KBStore Protocol 단위 테스트."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from macro_logbot.knowledge_base import ArchivedCase, KBStore, SQLiteKBStore


def _make_case(
    case_id: str = "case-001",
    error_signature: str = "AttributeError:NoneType.x_access",
    category: str = "runtime/none-access",
    root_cause: str = "x 가 None 인 상태에서 x_access 호출",
    confidence: float = 0.9,
    source: str = "poc",
) -> ArchivedCase:
    return ArchivedCase(
        case_id=case_id,
        error_signature=error_signature,
        category=category,
        root_cause=root_cause,
        location={"file": "src/app.py", "function": "main", "line": 42},
        fix_hint="None 체크 추가 또는 Optional 타입 명시",
        confidence=confidence,
        source=source,  # type: ignore[arg-type]
        tags=["none-access", "runtime"],
        related_code_refs=["src/app.py:42"],
    )


# ---------------------------------------------------------------------------
# add / get round-trip
# ---------------------------------------------------------------------------


def test_add_and_get(tmp_path: Path) -> None:
    """add → get round-trip — 모든 필드 보존 검증."""
    store = SQLiteKBStore(tmp_path / "kb.db")
    case = _make_case()
    store.add(case)

    fetched = store.get("case-001")
    assert fetched is not None
    assert fetched.case_id == "case-001"
    assert fetched.error_signature == "AttributeError:NoneType.x_access"
    assert fetched.category == "runtime/none-access"
    assert fetched.root_cause == "x 가 None 인 상태에서 x_access 호출"
    # location 은 Location BaseModel — dict 비교 시 model_dump 사용.
    assert fetched.location.model_dump() == {
        "file": "src/app.py",
        "function": "main",
        "line": 42,
    }
    assert fetched.fix_hint == "None 체크 추가 또는 Optional 타입 명시"
    assert fetched.confidence == pytest.approx(0.9)
    assert fetched.source == "poc"
    assert fetched.tags == ["none-access", "runtime"]
    assert fetched.related_code_refs == ["src/app.py:42"]


def test_get_missing_returns_none(tmp_path: Path) -> None:
    """존재하지 않는 case_id — None 반환."""
    store = SQLiteKBStore(tmp_path / "kb.db")
    assert store.get("nonexistent") is None


# ---------------------------------------------------------------------------
# search — keyword matching
# ---------------------------------------------------------------------------


def test_search_keyword_match(tmp_path: Path) -> None:
    """error_signature substring 매칭 — 포함된 케이스만 반환."""
    store = SQLiteKBStore(tmp_path / "kb.db")
    store.add(_make_case(case_id="c1", error_signature="AttributeError:NoneType.x_access"))
    store.add(_make_case(case_id="c2", error_signature="KeyError:missing_key"))

    results = store.search("AttributeError")
    assert len(results) == 1
    assert results[0].case_id == "c1"


def test_search_root_cause_match(tmp_path: Path) -> None:
    """root_cause substring 매칭 — error_signature 불일치라도 root_cause 포함이면 반환."""
    store = SQLiteKBStore(tmp_path / "kb.db")
    store.add(
        _make_case(
            case_id="c1",
            error_signature="KeyError:missing_key",
            root_cause="딕셔너리에 키가 없는 상태에서 접근",
        )
    )
    store.add(
        _make_case(
            case_id="c2",
            error_signature="IndexError:list_out_of_range",
            root_cause="리스트 인덱스 초과",
        )
    )

    results = store.search("딕셔너리")
    assert len(results) == 1
    assert results[0].case_id == "c1"


def test_search_returns_top_k_sorted_by_confidence(tmp_path: Path) -> None:
    """confidence 내림차순 정렬 + top_k 제한."""
    store = SQLiteKBStore(tmp_path / "kb.db")
    store.add(_make_case(case_id="low", error_signature="AttributeError:foo", confidence=0.3))
    store.add(_make_case(case_id="high", error_signature="AttributeError:bar", confidence=0.95))
    store.add(_make_case(case_id="mid", error_signature="AttributeError:baz", confidence=0.7))

    results = store.search("AttributeError", top_k=2)
    assert len(results) == 2
    assert results[0].case_id == "high"
    assert results[1].case_id == "mid"


def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    """매칭 없는 query — 빈 리스트 반환."""
    store = SQLiteKBStore(tmp_path / "kb.db")
    store.add(_make_case())

    results = store.search("ZeroDivisionError:totally_different")
    assert results == []


# ---------------------------------------------------------------------------
# security / permissions
# ---------------------------------------------------------------------------


def test_kb_store_db_file_permission(tmp_path: Path) -> None:
    """DB 파일이 owner-only 권한 (0o600) 으로 강제 — 사내 코드/로그 정보 보호."""
    db_path = tmp_path / "kb.db"
    SQLiteKBStore(db_path)
    if os.name == "posix":
        mode = db_path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


# ---------------------------------------------------------------------------
# Protocol isinstance check
# ---------------------------------------------------------------------------


def test_kb_store_protocol_isinstance(tmp_path: Path) -> None:
    """SQLiteKBStore 가 runtime_checkable KBStore Protocol 을 충족."""
    store = SQLiteKBStore(tmp_path / "kb.db")
    assert isinstance(store, KBStore)


# ---------------------------------------------------------------------------
# ArchivedCase Pydantic validation (architect WARN-3)
# ---------------------------------------------------------------------------


def test_archived_case_confidence_range_validation() -> None:
    """confidence 가 [0, 1] 범위 밖이면 ValidationError — spec §5.5 정합."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _make_case(confidence=1.5)
    with pytest.raises(ValidationError):
        _make_case(confidence=-0.1)


def test_archived_case_location_keys_enforced() -> None:
    """location 은 Location BaseModel (file/function/line 3 키 강제)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ArchivedCase(
            case_id="invalid-loc",
            error_signature="X",
            category="c",
            root_cause="r",
            location={"foo": "bar"},  # type: ignore[arg-type]
            fix_hint="h",
            confidence=0.5,
            source="poc",
        )


def test_archived_case_location_extra_keys_ignored() -> None:
    """Location 의 extra key 는 Pydantic v2 default (extra='ignore') 로 허용.

    이 동작이 의도 (현재 spec §5.5 line 220 의 3-키 외 확장 자유) — 명시 검증.
    """
    case = ArchivedCase(
        case_id="extra-loc",
        error_signature="X",
        category="c",
        root_cause="r",
        location={  # type: ignore[arg-type]
            "file": "f.py",
            "function": "fn",
            "line": 42,
            "extra_metadata": "ignored",
        },
        fix_hint="h",
        confidence=0.5,
        source="poc",
    )
    # extra key 는 dropped — Pydantic v2 default.
    assert case.location.model_dump() == {"file": "f.py", "function": "fn", "line": 42}


def test_location_line_zero_rejected() -> None:
    """Location.line = 0 — 1-indexed 소스 line 번호이므로 ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ArchivedCase(
            case_id="invalid-line",
            error_signature="X",
            category="c",
            root_cause="r",
            location={"file": "f.py", "function": "fn", "line": 0},  # type: ignore[arg-type]
            fix_hint="h",
            confidence=0.5,
            source="poc",
        )


def test_confidence_boundary_values_round_trip(tmp_path: Path) -> None:
    """confidence 경계 0.0 / 1.0 — Pydantic 허용 + SQLite REAL round-trip 보존."""
    store = SQLiteKBStore(tmp_path / "kb.db")
    for cid, conf in [("zero", 0.0), ("one", 1.0)]:
        store.add(_make_case(case_id=cid, confidence=conf))
        fetched = store.get(cid)
        assert fetched is not None
        assert fetched.confidence == pytest.approx(conf)


def test_add_duplicate_case_id_raises(tmp_path: Path) -> None:
    """동일 case_id 두 번 add — sqlite3.IntegrityError 전파 (PRIMARY KEY UNIQUE).

    현재 정책 (계약 명문화). task-KB-002 시점에 INSERT OR REPLACE vs 명시 update
    분리 등 정책 결정 예정.
    """
    import sqlite3

    store = SQLiteKBStore(tmp_path / "kb.db")
    store.add(_make_case(case_id="dup-001"))
    with pytest.raises(sqlite3.IntegrityError):
        store.add(_make_case(case_id="dup-001"))
