# macro-logbot baseline 측정 N=3 (PR #50/52/53 적용 후, 2026-05-20)

> **TL;DR**: PR #52 (workdir mode fix — F2 진짜 해소) + PR #53 (평가 인프라 invariant + fail-fast guard) + PR #50 (system prompt 강화) 모두 적용된 환경에서 진행한 **첫 진짜 baseline 측정**. tool result success rate **91.8%** (이전 N=10 측정의 0% false positive 대비 진짜 측정), avg total **73.27/100**, **자율해결률 90% (full + partial)**, **full 30%**. 본 N=3 가 본 sprint 의 최종 baseline.
>
> **이전 N=10 (`baseline-2026-05-20-N10.md`) 결과는 false positive — measurement 인프라 미작동 상태에서 traceback echo 만으로 1-A heuristic 통과**. PR #52 이후 진짜 측정 가능. 본 보고서가 본 sprint 의 single source of truth.

## 1. 측정 환경

| 항목 | 값 |
|---|---|
| Repo HEAD | `ad0dda2` (PR #53 머지본) |
| Backend HEAD | `b61ce18` (PR #50 system prompt 강화 적용) |
| 분석 모델 | `openai/gemma-3-12b-it` (LM Studio Local, Tailscale) |
| Backend env | `MACRO_LOGBOT_ENV=poc` + `POC_WORKSPACE_ALLOWED=/tmp/poc-cases` + `MODEL_CONTEXT_LIMIT=8192` |
| Case 수 | 10 (E001~E010) |
| 반복 수 | N=3 |
| 채점 기준 | 자동 30 + Claude judge 70 (§7.1, PR #49 확정) |
| 측정 시점 | 2026-05-20 17:48~18:10 KST (22분) |
| Raw output | `/tmp/baseline-n3-after-pr53/reports/N{1..3}/2026-05-20/E*.json` (30 파일) |

## 2. §7.5 invariant 검증 (PR #53 의무)

| invariant | 결과 | 신뢰도 |
|---|---|---|
| **#1 Tool result success rate ≥ 80%** | ✅ **91.8%** (101 ok / 9 err / 110 total) | PASS |
| **#1 (자동) infra_error flag case** | ✅ **0/30** — fail-fast guard 통과 | PASS |
| **#2 traceback echo vs 코드 read 구별** | ✅ tool success 91.8% + session DB 의 read_file content 검증 | PASS |
| **#3 structured Report 채움 경로** | ✅ 30/30 모두 location ≠ None + 대부분 코드 read 후 도출 | PASS |
| **#4 deterministic 검증** | ⚠️ **E006 std=0.427, E010 std=0.361 — variance 큼** | PARTIAL |

§7.6.2 disclaim 적용:
- **E006/E010 의 median run 채점은 대표성 약함** — N≥5 재측정 후 변동 가능. 본 sprint 의 N=3 한계.
- **median run 1 개만 채점** — 1-B/2-A/2-B 의 run-to-run variance 미측정.

## 3. 1-A heuristic (자동 30 점, 0~1 정규화)

| case | N1 | N2 | N3 | mean | std | median run |
|---|---|---|---|---|---|---|
| E001 | 0.925 | 1.000 | 1.000 | **0.975** | 0.043 | N2 |
| E002 | 0.850 | 0.925 | 0.925 | 0.900 | 0.043 | N2 |
| E003 | 0.925 | 0.925 | 0.625 | 0.825 | 0.173 | N1 |
| E004 | 0.880 | 0.880 | 0.940 | 0.900 | 0.035 | N2 |
| E005 | 1.000 | 1.000 | 1.000 | **1.000** | 0.000 | N2 |
| E006 | 0.925 | 0.225 | 1.000 | 0.717 | **0.427** ⚠️ | N1 |
| E007 | 0.700 | 1.000 | 1.000 | 0.900 | 0.173 | N2 |
| E008 | 0.475 | 0.475 | 0.475 | 0.475 | 0.000 | N2 |
| E009 | 0.625 | 0.925 | 0.925 | 0.825 | 0.173 | N2 |
| E010 | 0.075 | 0.700 | 0.700 | 0.492 | **0.361** ⚠️ | N2 |
| **avg** | | | | **0.801** | | |

- 자율해결률 (1-A mean ≥ 0.5): **8/10 (80%)**
- full (≥ 0.85): **5/10 (50%)**

## 4. 4-channel total (§7.1, 100 점 만점)

case 별 median run 의 4-channel 채점:

| case | 자동 30 (1-A×30) | root_cause (40) | fix_hint (30) | total | 판정 |
|---|---|---|---|---|---|
| E001 | 30.0 | 중 20 (init_game 위치 미명시) | 중 15 (모호) | **65.0** | ⚠️ partial |
| E002 | 27.75 | 중 20 (off-by-one 추측만) | **상 30** (GT 일치) | **77.75** | ⚠️ partial |
| E003 | 27.75 | **상 40** (off-by-one + range) | **상 30** (`range(len(self.body))`) | **97.75** | ✅ full |
| E004 | 26.4 | **상 40** | **상 30** (`"score: " + str(...)` 정확) | **96.4** | ✅ full |
| E005 | 30.0 | 중 20 (KeyError 정확, 메커니즘 부분) | 중 15 (잘못된 방향) | **65.0** | ⚠️ partial |
| E006 | 27.75 | **상 40** (`snake.py:126` 정확) | 중 15 (잘못된 방향) | **82.75** | ⚠️ partial |
| E007 | 30.0 | **상 40** | 중 15 (가드 추가 일반적) | **85.0** | ✅ full (경계) |
| E008 | 14.25 | 하 5 (`TimeoutError` echo만) | 하 5 (모호) | **24.25** | ❌ fail |
| E009 | 27.75 | 중 20 (`IndexError` echo만) | 중 15 (잘못된 방향) | **62.75** | ⚠️ partial |
| E010 | 21.0 | **상 40** | 중 15 (`encode/decode` 무의미) | **76.0** | ⚠️ partial |
| **avg** | **26.27** | **28.5** | **17.5** | **73.27** | |

### 종합 분류 (§7.1 의 100 점 만점)
- **full (≥ 85)**: 3/10 — E003, E004, E007 = **30%**
- **partial (45~84)**: 6/10 — E001, E002, E005, E006, E009, E010 = **60%**
- **fail (≤ 44)**: 1/10 — E008 = **10%**
- **자율해결률 (full + partial)**: **9/10 (90%)**

자동 30 점은 task-EVAL-002 (binary 정합) 미구현으로 `1-A naive_score × 30` 근사. 다음 sprint 에 binary 정합 후 재산출.

## 5. 본 sprint (PR #36~#53) 효과 분류

| PR | 분류 | 효과 |
|---|---|---|
| **PR #50** (system prompt 강화) | **성능 개선** (분석 모델 능력) | task-AGENT-015/016/017 — fix_hint 구체화 + semantic 분석 + noise filter |
| **PR #52** (workdir mode fix) | **인프라 fix** (성능 X) | F2 (workspace) 진짜 해소 — 코드 read 가능 |
| **PR #53** (평가 방법론 + fail-fast) | **채점 방식 개선** (measurement protocol) | §7.5 invariant + §7.6 본인 평가 워크플로우 |

## 6. N=10 (옛, false positive) vs N=3 (본 sprint 최종)

| metric | N=10 (`baseline-2026-05-20-N10.md`) | N=3 (본 보고서) | 의미 |
|---|---|---|---|
| 측정 시점 | 11:35~12:25 KST | 17:48~18:10 KST | |
| Backend HEAD | `5cffa59` (PR #48) — workdir mode 미적용 | `b61ce18` (PR #50) + workdir fix | |
| 채점 방식 | 옛 4-channel 25%×4 | **새 30+70** (§7.1) | 변환 불가 |
| tool result success | **0% (false positive)** | **91.8%** (진짜) | F2 진짜 해소 |
| 1-A avg | 0.635 (echo) | **0.801** (read) | +0.166 |
| full (옛/새 기준) | 30% (옛) / N/A | **30%** (새) | 명목 동일, 의미 다름 |
| 자율해결률 (옛/새) | 80% (false) / N/A | **90%** (진짜) | |
| 측정 의미 | "traceback echo 능력" | **"진짜 자율 분석 능력"** | 패러다임 차이 |

**N=10 보고서 결론 정정** (task-EVAL-006):
- N=10 의 "F2 해소 ✅" → **false positive**. PR #52 머지 후 진짜 해소.
- N=10 의 "tool 호출 시도 100%" → 시도 vs 성공 conflate. 실제 success 는 0%.
- N=10 의 "structured Report 90%" → traceback fallback 의 결과. 코드 read 의 결과가 아님.
- N=10 의 "자율분석 80%" → "traceback echo 능력 80%" 로 재해석.

## 7. 본 sprint 핵심 약점 (E008 fail)

E008 (spawn_food 무한 루프) 만 fail. 원인:
- TimeoutError 가 stderr 마지막 줄 → agent 가 본 신호만 echo
- 무한 루프 root cause (`return` 누락) 식별은 코드 read 후 control flow 분석 필요
- **PR #50 의 system prompt 강화 (semantic 오류 분석) 가 본 case 에는 부족**

→ **task-AGENT-021 신규 follow-up**: control-flow / infinite-loop 패턴 특화 prompt.

## 8. 사내 배포 진행 상황 (2026-05-20)

| 단계 | 상태 |
|---|---|
| 사외 PoC 측정 (E001~E010) | ✅ 완료 (본 보고서) |
| 사내 build (사내 미러 + APT/PIP_TRUSTED_HOST) | ✅ 정상 |
| 사내 runtime (backend + Open WebUI) | ✅ 기동 |
| 사내 LLM tool 지원 확인 | ✅ |
| 사내 LLM 사용 허가 | ⚠️ 대기 |
| 사내 측정 (사용자 직접) | ⏸️ 허가 후 |

본 Claude 는 사내 측정 실행 불가. 사용자 LLM 허가 후 N=3 측정 + 결과 공유 시 후속 분석 가능.

## 9. 본 sprint 종합 (PR #36~#53 누적, 18 PR)

| 분류 | PR | 효과 |
|---|---|---|
| Sprint 1 (Night) | #36~#41 | DEFAULT_MODEL / fallback metadata / SSO plan / cosmetic / header / baseline (false positive) |
| Sprint 2 (측정 fix) | #42~#47 | spec 정합 / workspace policy / inject workdir / context truncate / crystallize / docker env |
| Sprint 3 (docs + 개선) | #48~#51 | sprint #42-46 docs / 채점 기준 30+70 / system prompt 강화 / N=10 보고서 (false positive) |
| Sprint 4 (인프라 fix + 채점 명문화) | **#52/#53/#54** | **workdir mode fix → 채점 invariant 명문화 → 본 baseline 보고서** |

18 PR × 5 reviewer = **90+ reviewer comment**. WARN-MED follow-up [[feedback-warn-policy]] 정합.

## 10. 다음 step

1. **사내 LLM 측정** — 사용자 LLM 허가 후 N≥3 측정 + 본 보고서와 비교.
2. **task-EVAL-007** (high, architect 발견) — `AgentAnalyzeResponse` 에 `tool_call_summary` 필드 추가 (§7.5 invariant #2 자동화 완성).
3. **task-JUDGE-001** (high) — `claude_judge.judge_tool_appropriateness` 의 tool result error 채점 점검 (옛 N=10 의 2-A full 1.0 × 10 의 root cause 추정).
4. **task-AGENT-019** (high) — "Unknown: <사유>" escape 강제 mechanism (hallucinate 차단).
5. **task-AGENT-021** (신규) — control-flow / infinite-loop 패턴 prompt 강화 (E008 fail 대응).
6. **N≥5 재측정** — E006/E010 의 variance disclaim 해소.
7. **task-EVAL-002** — evaluate.py 의 30 점 binary 정합 (현 1-A × 30 근사 → 4 항목 binary 합산).

---

**raw data**: `/tmp/baseline-n3-after-pr53/reports/N{1..3}/2026-05-20/E*.json` (gitignored, 30 파일).
**비교 보고서**: `comparison.md` (각 run 의 `reports/N{N}/2026-05-20/comparison.md`).
