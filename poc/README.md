# macro-logbot PoC 환경

spec §10.4 PoC 자동 측정 환경. 사외 환경에서 macro-logbot 의 자율 해결률을 재현 가능하게 측정한다.

## 구성

```
poc/
├── targets/snake-game/original/    # MIT 자체 작성 snake (~200 LOC)
├── error_catalog/                  # E001~E005 yaml (injection_diff + ground_truth)
├── scripts/                        # setup/inject/trigger/evaluate
│   ├── setup.sh
│   ├── inject.py
│   ├── trigger.py
│   └── evaluate.py
└── reports/                        # 평가 산출물 (gitignore — milestone 만 commit)
```

## 사용법

1. **setup**: `bash poc/scripts/setup.sh` — pygame-ce + pyyaml 설치 + snake 정상 동작 검증.
2. **backend 기동**: docker-compose 또는 `uvicorn macro_logbot.app:app` 으로 `localhost:8000` 가동.
3. **API key** 환경변수: `export MACRO_LOGBOT_API_KEY=...` (`/agent/analyze` Bearer auth).
4. **측정**:

```bash
python poc/scripts/evaluate.py --cases E001,E002,E003,E004,E005
```

옵션:
- `--model gemini/gemini-2.5-flash` (기본) — 다른 모델 swap.
- `--api-url http://localhost:8000` — backend URL.
- `--rate-limit-cooldown 60` — case 간 sleep (Gemini free tier 5 RPM 보호).

5. **결과**: `poc/reports/<YYYY-MM-DD>/{<case>.json,comparison.md}`.

## 채점 범위

| 단계 | 평가 항목 | 비중 | 채점자 | 상태 |
|---|---|---|---|---|
| 1-A | file:line substring 매칭 | 25% | 결정론 스크립트 | ✅ `evaluate.py` |
| 1-B | root_cause 의미 매칭 | 25% | LLM judge | ✅ `claude_judge.py` (PR #27) |
| 2-A | 도구 호출 적절성 | 25% | LLM judge | ⚠️ interim — 1차 분석 기반 (PR #27) |
| 2-B | 수정 방향 정합성 | 25% | LLM judge | ⚠️ interim — 1차 분석 기반 (PR #27) |

`evaluate.py --judge claude-haiku-4-5` 옵션으로 1-A ~ 2-B 4단계 전체 채점 가능. judge 없이 실행 시 1-A 만 (기존 동작 유지).

> **⚠️ interim 의미** (architect WARN-1 PR #27): spec §6.2 (`docs/process/04-PoC-운영가이드.md`) 의 2-A/2-B 는 본래 **follow-up 대화 (Q1/Q2/Q3) 답변** 을 채점 대상으로 정의. 본 PR 은 1차 `/agent/analyze` 응답만으로 모든 4 항목을 채점한다 — 즉 2-A/2-B 는 "1차 분석에서 도구 호출이 적절했는가" + "1차 분석 안의 fix_hint 가 정합한가" 의 interim 의미. follow-up Q1/Q2/Q3 자동 호출 + 진짜 채점은 **`task-POC-001-x`** (endpoint multi-turn 통합 후) 로 분리. 본격 baseline 측정 시점에 2-A/2-B 의미 재확인 필요.

### 측정 실패 처리 (architect WARN-2 PR #27)

`claude_judge` 호출이 JSON parse 실패 또는 LiteLLM call 실패 시 해당 항목은 `score=None` + `error` 필드. `naive_score_total` 평균은 유효 항목만 사용 (denominator 조정). `scored_axes` 필드에 유효 항목 수 표기 (4 가 정상, <4 이면 일부 측정 실패).

### 결정성 (architect WARN-3 PR #27)

judge 호출은 `temperature=0 + seed=42` — best-effort 결정성. LiteLLM provider 별 batch hashing 영향으로 같은 입력에 score variance 가능 (특히 0.5 ↔ 1.0). 본격 baseline 측정 시 동일 case **N=3 run 후 median** 권고.

### 측정 명령 예시

```bash
# 1-A 만 (judge 없음 — 기본)
python poc/scripts/evaluate.py --cases E001 --api-key $MACRO_LOGBOT_API_KEY

# 4단계 전체 채점 (Claude Haiku judge)
python poc/scripts/evaluate.py --cases E001 --judge claude-haiku-4-5 \
    --anthropic-api-key sk-ant-...

# Gemini judge 사용 시
python poc/scripts/evaluate.py --cases E001,E002,E003 \
    --judge gemini/gemini-2.5-flash-lite
```

## case 추가

1. `poc/error_catalog/E00N.yaml` 추가 — `injection_diff` 와 `ground_truth` 작성.
2. `injection_diff` 는 unified diff 형식 — hunk header 의 line count 가 어긋나도 OK (`inject.py` 는 context 본문 기반 매칭).
3. `python poc/scripts/inject.py --case E00N --workdir /tmp/test` → patch 적용 검증.
4. `python poc/scripts/trigger.py --case E00N --workdir /tmp/test` → 에러 발생 검증.

## 호환성 메모

- **pygame 가 아니라 pygame-ce**: pygame (mainline) 은 Python 3.14 휠 없음 → sdl2-config 필요한 source build 만 가능. pygame-ce (community edition, drop-in `import pygame`) 는 cp314 manylinux 휠 제공.
- **traceback 캡처**: `subprocess.run(..., stderr=PIPE)` 로 capture, exit code 비-0 일 때 traceback 본문이 stderr 에 있다고 가정.
- **case 간 cooldown**: Gemini free tier 5 RPM 제한 — 기본 60s. 모델 변경 시 `--rate-limit-cooldown 0`.

## 한계 (architect WARN, task-POC-002/005 후속)

- **1-A file 매칭 false-positive**: 5 case 의 `ground_truth.file` 이 모두 `snake.py` → LLM 이 "snake.py 어딘가" 라고만 답해도 0.4 자동 통과. task-POC-002 (5→10 확장, 다른 file path 포함) 전까지 baseline 변별력 한계.
- **endpoint vs spec §9.4**: `evaluate.py` 가 `POST /agent/analyze` 단일 호출. spec §9.4 의 `POST /events` + polling 흐름은 task-MVP-004 (session 통합) 후 task-POC-005 에서 마이그레이션.
- **1-A 만으론 spec §10.2 baseline 판정 불가**: 본 PR 은 4단계 채점 중 1-A 만 자동. full/partial 자율해결률 정량 측정은 task-POC-001 (Claude judge) 후.

## demo runbook (사용자)

- Gemini free tier **5 RPM** → 5 case 측정 시 `--rate-limit-cooldown 60` × 4 = 약 4분 sleep. demo 직전 dry-run 필수.
- 모델 변경 (Groq Llama / Claude Haiku 등 RPM 더 큰) 시 `--rate-limit-cooldown 0` 명시.

## 후속

- task-POC-001: 1-B/2-A/2-B Claude judge 채점.
- task-POC-002: 카탈로그 5 → 10 확장 (E006~E010).
- task-POC-003: 4 모델 매트릭스 (`--model` 다중 swap + 비교 리포트).
- task-POC-005: `evaluate.py` 를 spec §9.4 endpoint 흐름으로 마이그레이션 (task-MVP-004 후).
