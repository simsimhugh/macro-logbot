# AI DLC (AI Development Life Cycle) 플로차트

**AI sub-agent가 SDLC 각 단계마다 reviewer/executor 역할을 수행해 코드 작성부터 자동 머지까지 처리하는 개발 사이클**

```mermaid
sequenceDiagram
    participant Main as main session (orchestrator)
    participant Exec as executor
    participant Arch as architect
    participant CR as code-reviewer
    participant Sec as security-reviewer
    participant Test as test-engineer
    participant Ver as verifier
    participant GH as GitHub

    Main->>Exec: task 부여 (spec § + AC)
    Exec->>GH: feature branch + commits + PR 생성

    Main->>Arch: 아키텍처 적합성 검토
    Arch->>GH: PASS / WARN / BLOCK comment

    alt BLOCK 발생
        Main->>Exec: 재작업 (최대 3회)
        Exec->>GH: 수정 commit
    end

    par 병렬 검토 (평가축 직교)
        Main->>CR: 코드 품질 검토
        CR->>GH: line comments + summary
    and
        Main->>Sec: 보안 검토 (OWASP + 사내 특화)
        Sec->>GH: comments
    and
        Main->>Test: 테스트 실행 (coverage ≥ 80%)
        Test->>GH: coverage + autonomy_rate
    end

    Main->>Ver: 종합 판정 (§5 기준)

    alt 모두 통과
        Ver->>GH: APPROVE comment (봇 PAT)
        Ver->>GH: gh pr review --approve (봇 PAT)
        Main->>GH: gh pr merge --squash (자동 머지)
    else 미달
        Ver->>GH: REQUEST_CHANGES
        Main->>Exec: 재작업 (재시도 횟수++)
    end
```

## sub-agent 역할

| sub-agent | 역할 | 통과 조건 |
|---|---|---|
| **executor** | spec 기반 코드 작성 · PR 생성 · 리뷰 반영 수정 | — (작성자) |
| **architect** | 컴포넌트 책임·NFR·메타 정의 위반 여부 | BLOCK 0, WARN 처리 완료 |
| **code-reviewer** | 정확성·가독성·버그·edge case | CRITICAL/HIGH/MEDIUM 0 |
| **security-reviewer** | OWASP Top 10 + 시크릿·외부 유출 차단 | CRITICAL/HIGH/MEDIUM 0 |
| **test-engineer** | 커버리지 ≥ 80% · 기존 테스트 회귀 없음 | 3개 조건 모두 충족 |
| **verifier** | 위 4개 결과 종합 + AC 일치 + 자동 머지 실행 | 전체 통과 시 봇 approve → 자동 머지 |
