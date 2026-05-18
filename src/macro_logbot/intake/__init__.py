"""프리로드 래퍼 (Log Intake) 자리 — 후속 PR feat/preload-wrapper.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1 External Interfaces
수신 방식: HTTP webhook (POST JSON). 응답: 202 Accepted + session_id.

NOTE: Open WebUI는 외부 Docker 컨테이너로 분리(§8.2). 본 패키지는 프리로드 래퍼/Log Intake만 담당.
"""
