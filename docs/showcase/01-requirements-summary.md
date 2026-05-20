# macro-logbot — 요구사항 요약 (발표용)

**사내 테스트 플랫폼 MACRO 의 에러 로그를 받아 LLM 이 자율적으로 원인을 분석·리포트하는 사내 에이전트 AI 플랫폼**

## 한 장 정리

![요구사항 요약](01-requirements-summary.png)

## 핵심 기능

- **자율 원인 분석** — LLM 이 도구를 반복 호출하며 원인 추적
- **코드 + 로그 결합** — 사내 코드베이스 검색·읽기로 정확도 향상
- **구조화 리포트** — structured JSON (원인 / 위치 / 신뢰도) 출력, OSS fallback + retry
- **모델 독립성** — env swap 만으로 다른 LLM 으로 전환
- **workspace 격리 보안** — `MACRO_LOGBOT_ENV` 게이트로 PoC/production 접근 범위 분리, symlink escape 차단

---

## 현재 진행 단계 (2026-05-20)

```
사외 PoC 측정 검증  →  사내 배포 검증  →  사내 LLM 허가 대기  →  사내 측정 + 평가
       ✅ 완료              ✅ 완료              ⚠️ 진행 중               🔜 예정
```

| 단계 | 상태 | 내용 |
|---|---|---|
| 사외 PoC 측정 | ✅ | 10 case 카탈로그 기준 측정 완료 |
| 사내 배포 첫 검증 | ✅ | build + runtime 정상. 사내 LLM tool 지원 확인 |
| 사내 LLM 허가 | ⚠️ | 허가 대기 중. 사내 측정은 사용자 직접만 가능 |
| 사내 측정 + 평가 | 🔜 | 허가 획득 후 진행 |

---

> 다이어그램 원본은 `01-requirements-summary.mmd` (mermaid). 수정 시 PNG 재생성 필요.
