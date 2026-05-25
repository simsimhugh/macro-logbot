# Contributing to macro-logbot

이 repo는 **AI DLC 실증 사례**입니다. 일반적 OSS와 달리 코드 작성·리뷰·머지의 대부분을 **AI 서브에이전트가 자동으로 수행**하며, 사람은 (1) 요구사항·설계 의사결정 (2) 자동 머지 기준을 정의하는 역할만 합니다.

## 빠른 시작

```bash
git clone https://github.com/simsimhugh/macro-logbot.git
cd macro-logbot

# 사외 PoC 환경 setup (별도 가이드)
./poc/scripts/ops/setup.sh
```

## 본 repo를 읽는 법 (PR history)

PR 페이지가 "AI 에이전트들의 협업 기록"으로 구성되어 있습니다:
- PR description: `executor agent` 작성 (🤖 표식)
- Comments: `architect` · `code-reviewer` · `security-reviewer` · `test-engineer` · `verifier` 각각이 자동 post
- Commit messages 끝: `Co-Authored-By` 트레일러로 에이전트 식별
- 자동 머지: 모든 reviewer 통과 시 사람 승인 없이 진행

자세한 워크플로우는 [`docs/process/03-개발-프로세스.md`](docs/process/03-개발-프로세스.md) 참조.

## 브랜치 전략

| 브랜치 패턴 | 용도 |
|---|---|
| `main` | 안정 (force-push/deletion 보호) |
| `feat/<short-name>` | 새 기능 (예: `feat/mcp-grep-tool`) |
| `fix/<short-name>` | 버그 수정 |
| `docs/<short-name>` | 문서 변경 |
| `chore/<short-name>` | 빌드·환경·메타 변경 |
| `tmp/<purpose>` | 임시 (예: `tmp/pre-design-checklist` — 담당자 답변 회수용) |
| `experiment/<short-name>` | PoC 실험 |

## Commit 메시지

Conventional Commits 스타일:

```
<type>(<scope>?): <subject 50자 이내>

<body — what / why, 줄당 72자 권장>

Co-Authored-By: <agent-name or "Claude Opus 4.7 (1M context)"> <noreply@anthropic.com>
```

`type`: `feat` · `fix` · `docs` · `chore` · `refactor` · `test` · `perf` · `style` · `ci`

**Co-Authored-By 의무**: 에이전트가 작성한 commit이면 어떤 에이전트인지 명시.

예시:
```
feat(mcp): implement grep_codebase tool

- regex search with re.MULTILINE
- file_glob filter support
- output max 50 matches per call (truncation note)

Address code-reviewer comment on PR #12 line 42.

Co-Authored-By: executor-agent (Sonnet) <noreply@anthropic.com>
Co-Authored-By: code-reviewer-agent <noreply@anthropic.com>
```

## PR 절차 (요약)

자세한 자동화 규칙은 [`docs/process/03-개발-프로세스.md`](docs/process/03-개발-프로세스.md).

1. `executor` agent가 feature branch에 코드 작성 + commit
2. PR 생성 (`gh pr create`) — description은 `executor`가 자동 작성
3. `architect` → `code-reviewer` → `security-reviewer` → `test-engineer` → `verifier` 순차 호출
4. 각 reviewer가 PR comment 자동 post (🤖 표식 + severity)
5. blocker가 있으면 → `executor`가 재작업 (최대 3회 시도)
6. 모든 reviewer pass → `verifier`가 auto-merge 승인 → squash merge

## 코드 스타일

Python:
- PEP 8 + Black formatter (line length 100)
- Type hints 의무 (mypy strict)
- Ruff lint (config는 `pyproject.toml`)
- async/await 우선

Markdown:
- 행당 100자 권장 (한국어는 자유)
- Mermaid 다이어그램은 큰따옴표 라벨 + 특수문자 회피 (`&` → `and`)

## 이슈

기능 요청·버그 보고는 GitHub Issues로. 라벨:
- `requirements` — Stage 1 영향
- `design` — Stage 2 영향
- `implementation` — Stage 3 코드
- `poc` — PoC 환경/평가
- `agent-instruction` — 서브에이전트 매뉴얼 개선
- `meta` — process 문서 자체 변경

## 보안

시크릿(.env, API key, 사내 URL 등)은 commit 금지. `.gitignore` 등록 패턴 참조. 사고 발견 시 즉시 메인테이너 통보.
