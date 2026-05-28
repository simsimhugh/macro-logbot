# AI DLC (AI Development Life Cycle) — 발표용

**AI 서브에이전트가 SDLC 각 단계의 reviewer / executor 역할을 수행해 코드 작성부터 자동 머지까지 처리하는 개발 사이클**

## 한 장 정리

![AI DLC 플로차트](03-ai-dlc-flowchart.png)

## 4 단계 요약

1. **작성** — Orchestrator → executor → PR
2. **병렬 리뷰** — 아키텍처 / 코드 / 보안 / 테스트 (4 AI 동시)
3. **종합 판정** — verifier 가 모든 리뷰 결과 합의
4. **자동 머지** — 통과 시 봇 PAT 로 self-approve + squash

---

> 다이어그램 원본은 `03-ai-dlc-flowchart.mmd` (mermaid). 수정 시 PNG 재생성 필요.
