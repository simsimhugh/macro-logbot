# macro-logbot — 아키텍처 다이어그램

**사외 GitHub에서 개발하고 사내 환경에 단방향 clone·deploy하는 에이전트 AI 플랫폼**

```mermaid
flowchart LR
    subgraph 사외환경
        GH["사외 GitHub\nsimsimhugh/macro-logbot"]
        FREE["무료 LLM 4종\n(사외 PoC용)"]
    end

    subgraph 사내환경
        MACRO["MACRO\n(테스트 플랫폼)"]
        LLM["사내 LLM Endpoint"]
        CB[("사내 코드베이스")]
        MIR[("사내 패키지·이미지 미러")]
        USER["사내 사용자"]

        subgraph deploy["macro-logbot 인스턴스 (사내 deploy)"]
            LI["Log Intake\n프리로드 래퍼"]
            UI["Open WebUI\n(Docker 컨테이너)"]
            AC["Agent Core\n(LangGraph)"]
            LG["LLM Gateway\n(LiteLLM)"]
            TS["Tool System\n(MCP, 9개 도구)"]
            SC["Session & Context\n(SQLite)"]
            KB[("Knowledge Base\narchived_cases")]
        end

        deploy -.->|"build · runtime 의존성"| MIR
    end

    MACRO -->|"에러 이벤트"| LI
    LI --> AC
    USER <-->|"대화 · follow-up"| UI
    UI -->|"OpenAI 호환 API"| AC
    AC <-->|"messages · tools"| LG
    LG <-->|"모델 라우팅"| LLM
    LG -.->|"env swap (사외 PoC)"| FREE
    AC <-->|"tool call · result"| TS
    TS <-->|"검색 / 읽기"| CB
    AC <--> SC
    AC <-->|"prefetch · write"| KB
    GH -.->|"clone and deploy (단방향)"| deploy
```

| 컴포넌트 | 핵심 책임 |
|---|---|
| Log Intake | MACRO 에러 이벤트 수신 (HTTP webhook) · 세션 초기화 |
| Agent Core | iterative tool calling 루프 · LangGraph state graph |
| LLM Gateway | LiteLLM 어댑터 · 100+ 모델 단일 인터페이스 · 모델 독립성 |
| Tool System | 사내 코드베이스 검색·읽기 9개 MCP 도구 (read-only) |
| Session & Context | 메시지 히스토리 · follow-up 컨텍스트 유지 |
| Knowledge Base | 분석 결과 자동 아카이빙 · 유사 사례 retrieval (RAG) |
| Open WebUI | 사용자 채팅 UI (Docker 격리 · Python 3.14 호환 회피) |
