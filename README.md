# macro-logbot

사내 에이전트 AI 플랫폼. 첫 번째 사용 사례는 사내 테스트 플랫폼 **MACRO**에서 발생하는 에러의 **자율 원인 분석**입니다. Claude Code와 유사하게 LLM이 도구(코드 검색·로그 조회 등)를 자율적으로 다중 호출하며 단서를 모아 결론을 도출합니다.

## 현재 단계

```
[Stage 1] 요구사항 확인서   ← 현재 (v0.4)
[Stage 2] 설계 문서          예정
[Stage 3] 구현               예정
                             → 코드위키 운영 문서
```

## 문서

- [Stage 1 — 요구사항 확인서 (v0.4)](docs/requirements/01-요구사항확인서.md)

## 핵심 제약

- LLM endpoint는 **사내 전용** (외부 API 호출 금지)
- 분석 대상 코드·로그는 **사내 환경 외부로 유출 금지**
- macro-logbot **자체** 코드만 본 사외 GitHub repo에서 관리
- 사내 환경은 외부 인터넷 격리 → 사내 미러 레포 사용 (배포 환경별 의존성 소스 전환 가능)

자세한 내용은 요구사항 확인서를 참고하세요.

## Repository

- Source: https://github.com/simsimhugh/macro-logbot
- License: TBD (Stage 2에서 결정)
