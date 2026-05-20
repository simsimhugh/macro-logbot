# 약한 LLM 강화 — 외부 reference 브레인스토밍 (2026-05-21)

> **목적**: 본 sprint 의 점수 천장 (Gemma 3 12B Q4 = 73.27/100, fail case E008 의 control-flow 분석 실패 + E001 N2 의 tool calling 무한 loop) 을 외부 OSS 자료 차용으로 돌파.
>
> **본 doc 의 위치**: docs/process/ 의 정식 spec 이 아닌 **브레인스토밍 노트**. 정식 적용 시 별도 PR + reviewer cycle.
>
> 사용자 명시: "약한 모델 강화는 본 PoC 의 핵심 미션 — 사내 LLM 라인업 (GPT-OSS / Gemma 4.1 / Gauss 4.1) 으로 측정 전 사외 baseline 도 더 강한 prompt + agent loop 로 끌어올리기".

## 1. 현재 상황 (PR #54 baseline 기준)

| metric | 값 | 약점 |
|---|---|---|
| 1-A avg | 0.801 | 일부 case 의 file:line 정확도 부족 |
| 4-channel total | **73.27 / 100** | fix_hint 모호 6/10 |
| 자율해결률 (≥45) | 90% | E008 (spawn_food 무한 루프) fail |
| full (≥85) | 30% | reasoning 능력 한계 |
| tool calling 안정성 | 91.8% success | E001 N2 의 40-message 무한 loop |

본 sprint 의 시도:
- **PR #50** (task-AGENT-015/016/017) — system prompt 강화 (분석 절차 6 step + noise filter 6 패턴) ✅
- **PR #55** (task-AGENT-021) — control-flow prompt 추가. **regression 으로 close** (0.801 → 0.453)
- **PR #55 v2** (task-AGENT-022) — agent termination guard (same-tool-args repeat detection). **regression 으로 close** (effect 부재)

→ **prompt 강화의 자체 한계 진단**. 본 PoC 의 agent loop / tool design 자체를 더 robust 한 패턴으로 재설계 필요.

## 2. 외부 reference 후보 — Claude Code 리버스 엔지니어링 (5 repo)

| repo | 내용 | 본 PoC 차용 가치 |
|---|---|---|
| **[zep-us/claude-system-prompt](https://github.com/zep-us/claude-system-prompt)** | Claude 공식 prompt 와 validate 된 리버스 prompt | ★★★ Gemma 의 system prompt → Claude 패턴 차용 |
| **[hitmux/HitCC](https://github.com/hitmux/HitCC)** | v2.1.84 의 agent loop + tool use + prompt assembly 전체 문서화 | ★★★ task-AGENT-022 가 close 한 termination 의 진짜 정답 패턴 |
| **[shareAI-lab/analysis_claude_code](https://github.com/shareAI-lab/analysis_claude_code)** | v1.0.33 의 real-time steering, multi-agent, context management, tool execution pipeline (4.7k★) | ★★ context overflow + multi-agent reasoning |
| **[ruvnet/open-claude-code](https://github.com/ruvnet/open-claude-code)** | AI-powered decompilation 의 full OSS 재구현 | ★ 참고 구현 |
| **[Yuyz0112/claude-code-reverse](https://github.com/Yuyz0112/claude-code-reverse)** | LLM 대화 시각화 + common prompt 자동 식별 | ★ 분석 도구 (본 PoC 의 N=3 측정 결과 분석에 활용 가능) |

## 3. 외부 reference 후보 — Open-source agent AI framework (4 후보)

| framework | SWE-bench (참고) | 본 PoC 차용 가치 |
|---|---|---|
| **[OpenHands](https://www.openhands.dev/)** (구 OpenDevin) | **72% Verified** (Claude 4), 40k+★ | ★★★ **multi-agent subtask delegation** — 200 줄 코드 분석 실패 직접 해소. **control-flow sub-agent + root_cause sub-agent 분리** |
| **[SWE-agent](https://github.com/SWE-agent/SWE-agent)** (Princeton) | NeurIPS 2024 학술 | ★★★ **Agent-Computer Interface (ACI)** — tool 의 LLM-friendly 추상화 (Gemma 의 tool calling 약함 직접 fix) |
| **[Aider](https://aider.chat/)** | git-native | ★ 본 PoC 와 결 다름 (editing 중심) |
| **MetaGPT / CrewAI / AutoGen** | multi-agent | ★ 본 PoC scope 외 (multi-agent simulation 위주) |

## 4. 본 PoC 약점 ↔ 차용 매핑

| 본 PoC 약점 | 외부 패턴 | 차용 방식 |
|---|---|---|
| **fix_hint 모호** (E001/E002/E003/E005/E006/E009/E010 6/10) | OpenHands 의 **plan → decompose → execute** + Claude Code 의 plan-first prompt | system prompt 에 "plan 단계 → 구체적 변경 제안" 강제 |
| **E001 N2 tool calling 무한 loop** | Claude Code 의 **same-tool-args repeat detection** (task-AGENT-022 는 실패 — 다른 구현 필요) + SWE-agent ACI 의 tool error retry pattern | termination guard 재설계 + tool result 의 LLM-friendly summary |
| **E008 control-flow 분석 실패** | OpenHands 의 **multi-agent subtask delegation** | control-flow 전문 sub-agent 추가 (task-AGENT-024 후보) |
| **context overflow** (PR #45 truncate) | shareAI-lab/analysis_claude_code 의 **intelligent context management** (sliding window + summary) | 본 sprint 의 group truncate → summary-based |
| **tool 의 LLM-friendly 형식** | SWE-agent 의 **Agent-Computer Interface** | read_file/grep_codebase 의 description + output 형식을 Claude Code/OpenHands 패턴으로 |

## 5. 다음 action 권고 (try sequence)

### 5.1 단기 (1 sprint)
1. **[zep-us/claude-system-prompt](https://github.com/zep-us/claude-system-prompt)** WebFetch → 핵심 system prompt 패턴 추출
2. 본 PoC 의 `_ANALYZE_SYSTEM_PROMPT` (현 PR #50 적용본) 을 Claude Code 패턴으로 재작성 → **task-AGENT-025** (신규)
3. **gpt-oss-20b** 다운로드 + load (사용자 PC RX 9070 XT 16GB 충분) + N=3 측정 — **모델 효과** 분리
4. 두 측정 (prompt 변경 only + 모델 변경 only) 비교 → 효과 분해

### 5.2 중기 (2-3 sprint)
1. **[hitmux/HitCC](https://github.com/hitmux/HitCC)** WebFetch → agent loop + tool use 패턴
2. 본 PoC 의 LangGraph state graph 재설계 — Claude Code 의 termination + retry 패턴 차용
3. **OpenHands 의 multi-agent subtask** — control-flow 전문 sub-agent 추가 (E008 fail case 해소)
4. **SWE-agent ACI** — read_file/grep_codebase 의 output 형식을 LLM-friendly 로 (PR #43 의 4-layer 위에 추가 wrapper)

### 5.3 장기 (사내 운영 진입 후)
1. **Claude Code 의 plugin / MCP server 패턴** 차용 — 사내 도구 (Linear, Jira 등) 와의 통합
2. **OpenHands 의 production deployment** — Docker sandboxing + remote execution

## 6. 본 doc 의 follow-up

- **task-RESEARCH-001** (이 doc 의 follow-up) — 5.1 단기 action item 실측 (Claude Code system prompt 차용 + gpt-oss-20b 측정)
- **task-RESEARCH-002** — 5.2 중기 action item (OpenHands multi-agent 차용)
- 본 brainstorm doc 은 **living document** — 측정 결과 + 사용자 의견 누적되면 update

## References (검색 일자: 2026-05-21)

### Claude Code 리버스 엔지니어링
- [Yuyz0112/claude-code-reverse](https://github.com/Yuyz0112/claude-code-reverse) — LLM 대화 시각화
- [ruvnet/open-claude-code](https://github.com/ruvnet/open-claude-code) — AI-powered decompilation
- [hitmux/HitCC](https://github.com/hitmux/HitCC) — v2.1.84 전체 문서화
- [zep-us/claude-system-prompt](https://github.com/zep-us/claude-system-prompt) — 리버스 prompt + 공식 validate
- [shareAI-lab/analysis_claude_code](https://github.com/shareAI-lab/analysis_claude_code) — v1.0.33 분석

### Open-source agent framework
- [OpenHands](https://www.openhands.dev/) — 72% SWE-bench Verified, multi-agent
- [SWE-agent](https://github.com/SWE-agent/SWE-agent) — Princeton, ACI 추상화
- [Aider](https://aider.chat/) — git-native pair programmer
- [Awesome AI Agents 2026 (Zijian-Ni)](https://github.com/Zijian-Ni/awesome-ai-agents-2026) — 300+ 큐레이션

### 분석 보고
- [Open-Source Coding Agents Survey](https://airesponsibly.substack.com/p/open-source-ai-coding-agents-a-survey)
- [Best Open-Source AI Coding Agents 2026](https://www.opensourceaireview.com/blog/best-open-source-ai-coding-agents-in-2026-ranked-by-developers)
- [OpenHands vs SWE-agent](https://www.codesota.com/agentic/openhands-vs-swe-agent)

---

**본 doc 의 결정 권한**: 사용자. 본인 (Claude) 은 정리 + 측정 + 보고 담당.
