"""Log Intake — MACRO 에러 로그 파싱 (PoC).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1
"""

from macro_logbot.intake.parser import IntakeRecord, parse_macro_log

__all__ = ["IntakeRecord", "parse_macro_log"]
