"""Intake parser 단위 테스트."""

from __future__ import annotations

from datetime import datetime

from macro_logbot.intake import parse_macro_log


def test_parse_full_log_with_traceback() -> None:
    text = (
        "2026-05-19 14:30:01 ERROR: DB connection failed\n"
        "Traceback (most recent call last):\n"
        '  File "app.py", line 10, in <module>\n'
        "    db.connect()\n"
        "ConnectionError: refused\n"
    )
    record = parse_macro_log(text)
    assert record.level == "ERROR"
    assert record.message == "DB connection failed"
    assert isinstance(record.timestamp, datetime)
    assert record.traceback is not None
    assert "ConnectionError" in record.traceback


def test_parse_warning_normalized_to_warn() -> None:
    text = "2026-05-19 14:30:01 WARNING: slow query 1.2s"
    record = parse_macro_log(text)
    assert record.level == "WARN"
    assert record.message == "slow query 1.2s"


def test_parse_unrecognized_format() -> None:
    text = "이건 한글 포맷의 알 수 없는 로그입니다"
    record = parse_macro_log(text)
    assert record.level is None
    assert record.timestamp is None
    assert record.raw == text
    assert record.message == text.strip()


def test_parse_empty() -> None:
    record = parse_macro_log("")
    assert record.raw == ""
    assert record.level is None


def test_parse_iso_timestamp_with_T() -> None:
    text = "2026-05-19T14:30:01 INFO: started"
    record = parse_macro_log(text)
    assert record.level == "INFO"
    assert isinstance(record.timestamp, datetime)
