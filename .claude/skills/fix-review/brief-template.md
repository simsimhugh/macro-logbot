# fix sub-agent brief template

본 template 은 main session 이 fix sub-agent 에게 전달하는 brief 의 의무 항목 spec.
main session 은 sub-agent spawn 시 아래 항목을 모두 포함한 brief 를 작성해야 함.

---

## 의무 항목 1 — review comment 직접 read

fix sub-agent 는 반드시 실제 PR review body 를 직접 fetch 해야 함.
기억 또는 상위 brief 의 요약에 의존 금지.

```bash
# PR review body 전체 fetch (finding 본문 포함)
gh pr view <PR-NUM> --json reviews --jq '.reviews[].body'
```

- 각 reviewer (architect / code-reviewer / security-reviewer / test-engineer) 의 finding 본문을 직접 읽어라
- finding 의 `location`, `code`, `detail` field 를 원문 그대로 확인해라
- 요약/압축된 finding 설명이 아닌 actual review body 에서 fix 대상 특정

## 의무 항목 2 — 옛 fix evidence 읽기 (persist 기반)

fix sub-agent 는 이전 cycle 의 fix 매핑을 persist 파일에서 읽어야 함.
git log + git show 로 어떤 commit 이 어떤 finding 을 fix 했는지 역추론하는 것을 금지.

```bash
# evidence 파일 읽기
EVIDENCE_FILE=".omc/state/fix-evidence/pr-<PR-NUM>.json"
cat "$EVIDENCE_FILE" 2>/dev/null || echo "no evidence file (cycle 1)"
```

- evidence 파일이 있으면 → 파일 내용을 보존 대상으로 사용. 역추론 불필요.
- evidence 파일이 없으면 → cycle 1 (첫 fix). 보존 대상 없음 — 신규 fix 만 수행. 단, 의무 항목 8 에서 fix 완료 후 evidence 파일 생성 의무 — verifier 호출 시점에는 evidence 파일이 존재해야 함.
- 각 cycle entry 의 `fix_lines[].code` 를 `grep` 으로 현재 파일에서 위치 확인 (라인 drift 대응)
- 보존 의무: evidence 에 기록된 모든 fix 는 새 commit 에 그대로 있어야 함

evidence 파일 스키마:

```json
{
  "pr": 71,
  "cycles": [
    {
      "cycle": 1,
      "findings": [
        {
          "reviewer": "security-reviewer",
          "location": "post_helper.py:60",
          "severity": "CRITICAL",
          "title": "SQL injection"
        }
      ],
      "fix_commit": "abc1234",
      "fix_lines": [
        {"file": "post_helper.py", "line": 60, "code": "sanitize(input)"}
      ]
    }
  ]
}
```

## 의무 항목 3 — regression verify (evidence 기반)

fix 후 반드시 evidence 파일에 기록된 옛 fix 가 보존됐는지 self-verify 해야 함.

```bash
# evidence 파일의 각 cycle 의 fix_lines[].code 가 현재 파일에 있는지 grep
grep -n "<evidence 의 fix code>" <fix-file>
```

- evidence 파일의 모든 `fix_lines[].code` 가 현재 파일에 존재하는지 확인해라
- 라인 번호가 달라도 code 내용이 있으면 OK (drift 허용)
- code 가 없으면 regression → 즉시 재 fix 의무
- verify 결과를 완료 보고에 명시 (evidence cycle → code 존재 여부)

## 의무 항목 4 — finding 의 location + code field 읽기

finding 이 명시한 actual file:line 의 content 를 반드시 직접 읽어야 함.
location 만 보고 코드를 추정하거나 기억에 의존 금지.

```bash
# finding 이 location: "path/to/file.py:42" 명시 시
# → 반드시 해당 파일의 해당 줄을 Read tool 로 직접 확인
Read /home/.../path/to/file.py  (offset: 40, limit: 10)
```

- finding 의 `code` field 가 있으면 실제 파일의 해당 줄과 대조해라
- `code` field 와 실제 파일 내용이 다르면 → reviewer 의 location 이 stale 일 가능성. 실제 내용 기준으로 fix.
- `location: "post_helper.py:344"` 라면 실제 344번째 줄이 무엇인지 확인 후 fix

---

## 의무 항목 5 — block 사유 우선 fix

fix sub-agent 는 block 사유 finding (verdict = REQUEST_CHANGES 에 기여한 finding) 을 먼저 fix 해야 함.

- block 사유 = role-specific blocking severity:
  - `code-reviewer`: CRITICAL / HIGH at HIGH confidence
  - `architect` / `security-reviewer` / `test-engineer`: CRITICAL / HIGH / MED / WARN
- informational finding (LOW / INFO / PASS, 또는 code-reviewer 의 MED/WARN) 은 후순위 (또는 별 issue)
- block 사유 finding 을 먼저 모두 fix 한 후 informational 처리

## 의무 항목 6 — fix 후 self-verify

fix 후 반드시 변경 라인이 finding location 과 일치하는지 self-verify 해야 함.

```bash
# finding 의 location: "post_helper.py:60" → 해당 줄이 실제 fix 됐는지 diff 확인
# 여기서 SHA 는 현재 cycle 의 fix commit 직전 SHA (역추론 아님 — 자기 작업 범위)
git diff HEAD~1..HEAD -- <fix-file>
```

- `git diff` 의 `+` 라인이 finding 의 location:line 영역에 있는지 확인해라
- fix 가 finding 이 지적한 실제 코드를 변경했는지 (location drift 방지)
- verify 결과를 완료 보고에 명시 (finding location → diff line 일치 여부)

## 의무 항목 7 — cycle history 의 block 사유 fix evidence 보존

evidence 파일의 모든 cycle 의 block 사유 fix 가 현재 코드에 그대로 있는지 확인해야 함.

```bash
# evidence 파일에서 각 cycle 의 blocking finding + fix code + file 추출 후 해당 파일에서 grep
# (evidence 파일이 없으면 cycle 1 — 이 항목 skip)
cat ".omc/state/fix-evidence/pr-<PR-NUM>.json" | \
  python3 -c "
import json, sys
d = json.load(sys.stdin)
for c in d.get('cycles', []):
    for fl in c.get('fix_lines', []):
        print(fl['file'] + '\t' + fl['code'])
" | while IFS=$'\t' read -r file code; do
    grep -qF "$code" "$file" || echo "MISSING in $file: $code"
done
```

- fix_lines[].file 별로 iterate 하므로 multi-file fix 에서도 각 파일에서 개별 grep 수행
- evidence 에 기록된 fix code 가 해당 파일에 없으면 regression → 즉시 재 fix
- 보존 의무: evidence 의 cycle 1 부터 현재까지 모든 block 사유 fix code 가 현재 코드에 존재해야 함

## 의무 항목 8 — fix evidence 쓰기 (persist)

fix 완료 후 반드시 `.omc/state/fix-evidence/pr-<PR-NUM>.json` 에 현재 cycle 의 evidence 를 추가해야 함.

```bash
# 디렉토리 생성 (최초 1회)
mkdir -p .omc/state/fix-evidence

# evidence 파일 쓰기 (기존 파일이 있으면 cycles 배열에 append, 없으면 신규 생성)
# cycle 번호는 기존 배열의 마지막 entry 의 cycle + 1 (배열 비어있거나 파일 없으면 1)
```

evidence entry 필수 필드:

| 필드 | 설명 |
|---|---|
| `findings[]` | fix 한 finding 목록 — `reviewer`, `location`, `severity`, `title` |
| `fix_commit` | fix commit SHA (short hash) |
| `fix_lines[]` | fix 한 코드 위치 — `file`, `line`, `code` (실제 코드 내용) |

규칙:
- `fix_lines[].code` 에는 fix 후의 **실제 코드 내용**을 기록 (다음 cycle 이 grep 으로 보존 확인에 사용)
- `fix_lines[].line` 은 fix 시점의 라인 번호 (drift 가능 — code 가 primary key)
- 기존 cycle entry 는 절대 수정 금지 — append only
- evidence 파일은 `.omc/` 하위이므로 `.gitignore` 적용 → PR diff 오염 없음

---

## 완료 보고 의무 항목

fix sub-agent 의 완료 보고에는 반드시 다음을 포함해야 함:

1. **각 finding 의 fix 위치** — `file:line` + 변경 내용 요약
2. **옛 fix 보존 verify 결과** — evidence 파일의 각 cycle fix code → 현재 파일 grep 존재 여부
3. **regression 없음 확인** — evidence 기반 code grep 결과 요약
4. **review comment 직접 read 여부** — "gh pr view --json reviews 로 직접 확인" 명시
5. **block 사유 우선 fix 확인** — block 사유 finding 목록 + fix 순서 명시
6. **self-verify 결과** — `git diff` 의 변경 라인 ↔ finding location 일치 여부
7. **cycle history block 사유 보존** — evidence 파일의 모든 cycle fix code 현재 코드 존재 여부
8. **evidence 파일 갱신** — `.omc/state/fix-evidence/pr-<PR-NUM>.json` 에 현 cycle entry 추가 완료
