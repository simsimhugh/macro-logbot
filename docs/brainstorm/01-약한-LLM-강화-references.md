# 약한 LLM 강화 + 본 PoC architecture 재검토 (브레인스토밍, 2026-05-21)

> **목적**: 본 sprint 의 점수 천장 (Gemma 3 12B Q4 = 73.27/100, fail case E008 의 control-flow 분석 실패 + E001 N2 의 tool calling 무한 loop) 돌파.
>
> **본 doc 의 위치**: docs/process/ 의 정식 spec 이 아닌 **브레인스토밍 노트** + **본 PoC 의 architectural 의사결정 reference**. 정식 적용 시 별도 PR + reviewer cycle.
>
> 사용자 명시 (2026-05-21):
> - "약한 모델 강화 = 본 PoC 핵심 미션"
> - 사내 라인업: GPT-OSS / Gemma 4.1 / Gauss 4.1
> - "패턴 차용만 할거면 안 하고 말지" — **본 PoC 통째 대체 (Path B) 진지 검토 의사**
> - "Claude Code (Anthropic 공식) 도 reference 가능"

## 1. 현재 상황 (PR #54 baseline 기준)

| metric | 값 | 약점 |
|---|---|---|
| 1-A avg | 0.801 | 일부 case 의 file:line 정확도 부족 |
| 4-channel total | **73.27 / 100** | fix_hint 모호 6/10 |
| 자율해결률 (≥45) | 90% | E008 (spawn_food 무한 루프) fail |
| full (≥85) | 30% | reasoning 능력 한계 |
| tool calling 안정성 | 91.8% success | E001 N2 의 40-message 무한 loop |

본 sprint 의 prompt-level 시도:
- **PR #50** (task-AGENT-015/016/017) — system prompt 강화 ✅ baseline 달성
- **PR #55** (task-AGENT-021, prompt) — control-flow 가이드. ❌ **close (regression 0.801 → 0.453)**
- **PR #55 v2** (task-AGENT-022, agent loop) — termination guard. ❌ **close (effect 부재)**

→ **prompt 강화의 자체 한계 evidence 확인됨**. 본 PoC 의 agent loop / tool design 자체 한계.

## 2. 외부 reference — Claude Code 리버스 엔지니어링 (5 repo)

| repo | 내용 | 본 PoC 차용 가치 |
|---|---|---|
| **[zep-us/claude-system-prompt](https://github.com/zep-us/claude-system-prompt)** | 리버스 system prompt + Anthropic 공식 validate | ★★★ Gemma 의 prompt → Claude 패턴 |
| **[hitmux/HitCC](https://github.com/hitmux/HitCC)** | v2.1.84 agent loop + tool use + prompt assembly 전체 문서화 | ★★★ task-AGENT-022 실패의 진짜 termination 패턴 |
| **[shareAI-lab/analysis_claude_code](https://github.com/shareAI-lab/analysis_claude_code)** | v1.0.33 real-time steering / multi-agent / context management (4.7k★) | ★★ |
| **[ruvnet/open-claude-code](https://github.com/ruvnet/open-claude-code)** | AI-powered decompilation full OSS 재구현 | ★ |
| **[Yuyz0112/claude-code-reverse](https://github.com/Yuyz0112/claude-code-reverse)** | LLM 대화 시각화 + common prompt 자동 식별 | ★ 분석 도구 |

**Claude Code 자체 (Anthropic 공식)** 도 reference 가능:
- 사용자 본인 PC 의 `claude --debug` 또는 `--verbose` 로 system prompt + tool description dump
- 본인 (Claude Opus 4.7) 의 knowledge 기반 안내 (knowledge cutoff 2026.1, 정확도 부분적)

## 3. 외부 reference — Open-source agent framework

### 3.1 본 PoC 와 결 가까운 (automated backend)

| framework | ★ | License | 본 PoC 차용 가치 |
|---|---|---|---|
| **[OpenHands](https://github.com/All-Hands-AI/OpenHands)** (구 OpenDevin) | 68k | MIT | ★★★ **72% SWE-bench Verified** (Claude 4). frontend (Web UI) + backend (Python FastAPI) + Docker sandbox + microagents + MCP. **본 PoC 통째 대체 가능** |
| **[SWE-agent](https://github.com/SWE-agent/SWE-agent)** | — | MIT | ★★ Princeton, NeurIPS 2024. **Agent-Computer Interface (ACI)** 의 학술 reference |
| **[Goose](https://github.com/block/goose)** | 32k | Apache 2.0 | ★★ Block (Square) 의 local agent framework. **MCP-native** |

### 3.2 IDE extension 류 (본 PoC 의 backend 와 결 다름)

| framework | ★ | License | 본 PoC 차용 가치 |
|---|---|---|---|
| **[Cline](https://github.com/cline/cline)** | 58k | Apache 2.0 | ★ pattern only (mode-based prompt 등) |
| **[Aider](https://github.com/Aider-AI/aider)** | 41k | Apache 2.0 | ★ git-native pair programmer |
| **[Continue](https://github.com/continuedev/continue)** | 31k | Apache 2.0 | ★ VS Code + JetBrains |
| **[Roo Code](https://github.com/RooCodeInc/Roo-Code)** | 22k | Apache 2.0 | ⚠️ Cline fork, **2026-05-15 shutdown 예정** — Cline 으로 migrate |
| **[Kilo Code](https://github.com/Kilo-Org/kilocode)** | — | OSS | Cline-derived, 1.5M users, 500+ models |
| **Tabby** | 33k | Apache 2.0 | self-hosted code completion |

→ IDE extension 류는 본 PoC 의 **사내 alerting → 자동 분석 → Report** 시나리오와 결 다름. **패턴만 차용 가치**.

## 4. 본 PoC 약점 ↔ 외부 패턴 매핑

| 본 PoC 약점 | 외부 reference 패턴 | 본 PoC 차용 |
|---|---|---|
| **fix_hint 모호** (E001/E002/E003/E005/E006/E009/E010 6/10) | OpenHands **plan → decompose → execute** + Claude Code plan-first | system prompt 에 plan 단계 강제 |
| **E001 N2 tool calling 무한 loop** | Claude Code **same-tool-args repeat detection** + SWE-agent **ACI 의 tool result LLM-friendly summary** | termination guard 재설계 |
| **E008 control-flow 분석 실패** | OpenHands **multi-agent subtask delegation** + Roo Code **mode-based (Debugger mode)** | control-flow 전문 sub-agent / mode |
| **context overflow** | shareAI-lab/analysis_claude_code 의 **intelligent context management** (sliding window + summary) | PR #45 truncate → summary-based |
| **tool LLM-friendly 형식** | SWE-agent **Agent-Computer Interface** | read_file/grep 의 output 재설계 |

## 5. Path 비교 — 본 sprint 의 architectural 결정

| Path | 의미 | sprint 비용 | 예상 점수 | 본 sprint evidence |
|---|---|---|---|---|
| **A (현재 — 자체 구현 + 패턴 차용)** | 본 PoC src 위에 Claude Code/OpenHands 패턴 차용 | 1-2 sprint | 80~88 | ❌ **PR #55 의 task-AGENT-021/022 실패 — 패턴 차용 효과 작음** |
| **B (OpenHands fork + 사내 customize) — 사용자 제안** | OpenHands base 위에 본 PoC 의 사내 spec wrapper | 2-3 sprint | **85~92** | OpenHands 72% SWE-bench Verified 의 base 위에서 시작 |
| C (하이브리드) | OpenHands agent core + 본 PoC measurement | 3-4 sprint | 80~88 | 가장 어려움 |

### 5.1 Path A 의 한계 (PR #55 evidence)

PR #55 의 두 시도 모두 **regression 으로 close**:
- task-AGENT-021 (prompt 강화) — avg 0.801 → 0.453 (-0.348)
- task-AGENT-022 (termination guard) — avg 0.801 → 0.703 (-0.098), JSON normalize 후도 regression

본 evidence 가 시사:
- 패턴 차용은 **Gemma 12B 의 모델 자체 한계** 를 못 넘음
- 본 PoC 의 agent loop / tool design 도 production-grade 패턴 부족
- → **architectural 재검토 필요** (사용자 의견)

### 5.2 Path B 의 진지 검토 (사용자 의견)

**사용자 명시**: "패턴 차용만 할 거면 안 하고 말지" — Path A 의 한계 수용 + Path B 진지 검토.

**OpenHands 가 frontend + backend full stack** — 본 PoC 의 src/macro_logbot/ + Open WebUI 통째 대체 가능.

본인이 1차 답에서 trade-off 강조 (사내 spec, 측정 인프라) 한 부분도 **OpenHands microagent + MCP plugin + Custom evaluation harness 로 customize 가능**.

**진짜 trade-off** (정직):
- 재구축 sprint 비용 (1-2 sprint)
- 사내 dependency audit (Apache 2.0 OK)
- 본 PoC 의 학습 (workspace permission, session DB, KB, system prompt, §7.5 invariant) 은 **OpenHands customize 시점에 모두 차용** — 버려지지 않음

## 6. Path B 의 단계별 plan (사용자 결정 시)

| Phase | 작업 | 기간 |
|---|---|---|
| **Phase 1** | OpenHands clone + 로컬 동작 + 사내 LLM endpoint 연결 (x-dep-ticket + content="") | 1 주 |
| **Phase 2** | case fixture (E001-E010) 통합 + 측정 harness (evaluate.py 핵심 로직) | 1 주 |
| **Phase 3** | 본 PoC spec (4-channel scoring + Report schema + KB archive) microagent + MCP plugin | 1-2 주 |
| **Phase 4** | 사내 측정 + 본 PoC 자체 구현 vs OpenHands base 비교 (Gemma 3 12B 동일 환경) | 1 주 |

**총 4-5 주** (2-3 sprint).

## 7. 본 sprint 의 진행 방향 — 결정 옵션

| 결정 | 의미 | sprint 영향 |
|---|---|---|
| **B 즉시 시작** | 본 sprint 의 src 변경 보류 + Phase 1 진입 | 현재 baseline 측정 일시 정지. Path B 의 산출물 다음 sprint 끝까지 |
| **현재 sprint 끝낸 후 B** | gpt-oss-20b N=3 측정 (현재 plan) → 결과 만족 안 됨 → Phase 1 | 현재 sprint 의 baseline 확정 후 Path B. 점진적 |
| **두 path 병행** | 본인 (Claude) Phase 1 (OpenHands clone + 사내 LLM 연결) + 사용자 gpt-oss-20b 측정 | 1-2 주 후 양쪽 evidence 비교 |
| **A 유지 + 작은 시도만** | gpt-oss-20b + Claude Code system prompt 차용 — A path 의 마지막 시도 | 1 sprint 후 결정 |

**본인 의견**: 두 path 병행 (#3) — sprint 비용 분산 + evidence 양쪽 확보. 1-2 주 후 비교 데이터로 Stage 2 (운영) 의 방향 확정.

## 8. 사용자 의견 누적 (본 doc 의 living history)

| 일자 | 사용자 의견 | 본인 반영 |
|---|---|---|
| 2026-05-21 | "점수 개선 전혀 안 되고 있다" | 본 doc §1 baseline 의 한계 인정 |
| 2026-05-21 | 사내 라인업 = GPT-OSS / Gemma 4.1 / Gauss 4.1 | §1 의 baseline 목표 = 사내 라인업 대응 |
| 2026-05-21 | "2만 줄 로그 보내면 overflow 아니야?" | log preprocessing = caller 측 (사내 alerting) 책임 = 본 PoC scope 외 |
| 2026-05-21 | "기존에 쓰던 LLM 컨텍스트 늘리면?" | Gemma context 32K 가능. 효과 작음. gpt-oss-20b 권고 |
| 2026-05-21 | **"agent AI 오픈소스 차용하면 무조건 좋지 않냐"** | OpenHands 정직 평가 — 거의 확실히 더 좋음 |
| 2026-05-21 | **"프론트+백엔드 다 가져올 수 있는거잖아"** | 본인 trade-off 과장 정정 — OpenHands full stack 가능 |
| 2026-05-21 | **"패턴 차용만 할거면 안 하고 말지"** | Path A 한계 인정 + Path B 진지 검토 |
| 2026-05-21 | "Claude Code 볼 수도 있는데" | Claude Code (Anthropic 공식) 도 reference 활용 옵션 |

## 9. 다음 action (사용자 결정 후 본인 진행)

본 doc 머지 후 사용자가 §7 의 결정 → 본인이 다음 action:

### 9.1 만약 Path B 채택
- **task-RESEARCH-002** 신규 — Phase 1 (OpenHands clone + 사내 LLM 연결)
- 본 PoC src 의 PR (현재 진행 중) 보류
- `macro-logbot-openhands` 신규 worktree 또는 별도 repo

### 9.2 만약 Path A 유지 + 작은 시도
- **task-RESEARCH-001** — gpt-oss-20b 다운로드 + N=3 측정
- Claude Code system prompt (zep-us repo) WebFetch → 본 PoC 의 _ANALYZE_SYSTEM_PROMPT 차용
- 측정 후 만족 안 되면 → Path B escalate

### 9.3 두 path 병행 (본인 권고)
- 본인 (Claude main session) — Path B Phase 1 진행 (사용자 PC 의 OpenHands clone + 사내 LLM 연결 가이드)
- 사용자 — gpt-oss-20b 다운로드 + LM Studio + 본 PoC src 위에서 N=3 측정
- 1-2 주 후 비교: gpt-oss-20b on 본 PoC vs OpenHands on Gemma

## References

### Claude Code 리버스 (검색 일자 2026-05-21)
- [zep-us/claude-system-prompt](https://github.com/zep-us/claude-system-prompt)
- [hitmux/HitCC](https://github.com/hitmux/HitCC)
- [shareAI-lab/analysis_claude_code](https://github.com/shareAI-lab/analysis_claude_code)
- [ruvnet/open-claude-code](https://github.com/ruvnet/open-claude-code)
- [Yuyz0112/claude-code-reverse](https://github.com/Yuyz0112/claude-code-reverse)

### Open-source agent framework (검색 일자 2026-05-21)
- [OpenHands](https://github.com/All-Hands-AI/OpenHands) — 본 doc 의 Path B 핵심 후보
- [SWE-agent](https://github.com/SWE-agent/SWE-agent)
- [Goose (Block)](https://github.com/block/goose)
- [Cline](https://github.com/cline/cline)
- [Aider](https://github.com/Aider-AI/aider)
- [Continue](https://github.com/continuedev/continue)
- [Roo Code](https://github.com/RooCodeInc/Roo-Code) — shutdown 예정
- [Kilo Code](https://github.com/Kilo-Org/kilocode)

### 분석 보고
- [Open-Source Coding Agents Survey](https://airesponsibly.substack.com/p/open-source-ai-coding-agents-a-survey)
- [Best Open-Source AI Coding Agents 2026](https://www.opensourceaireview.com/blog/best-open-source-ai-coding-agents-in-2026-ranked-by-developers)
- [OpenHands vs SWE-agent](https://www.codesota.com/agentic/openhands-vs-swe-agent)
- [Roo Code vs Cline (qodo.ai)](https://www.qodo.ai/blog/roo-code-vs-cline/)
- [Best Open-Source AI Coding Tools 2026 (Frontman)](https://frontman.sh/blog/best-open-source-ai-coding-tools-2026/)

### 모델 reference
- gpt-oss-20b — OpenAI Apache 2.0, 21B (MoE 3.6B active), 131K context, native function calling
- Gemma 3 27B-it — Google, 27B Q4 ~15GB VRAM
- Qwen2.5-32B-Instruct — Alibaba, Gauss 4.1 대체 후보

---

**본 doc 의 결정 권한**: 사용자. 본인 (Claude) 은 정리 + 측정 + 가이드.
**본 doc 의 정책**: living document. 사용자 의견 / 측정 결과 / 사내 의사결정 누적되면 §8 / §9 update.
