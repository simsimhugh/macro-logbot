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

## 의무 항목 2 — 옛 fix evidence 매핑

fix sub-agent 는 이전 cycle 의 fix commit 들을 반드시 확인하고 보존해야 함.

```bash
# 옛 cycle commit list
git log --oneline origin/main..HEAD

# 특정 commit 의 변경 내용 확인
git show <commit-sha> --stat
git show <commit-sha> -- <file-path>
```

- 각 이전 commit 이 어떤 finding 을 fix 했는지 file:line 수준으로 매핑해라
- 새 fix 작업 전 옛 fix 의 위치를 파악해라 (overwrite 방지)
- 보존 의무: 옛 cycle 의 모든 fix 는 새 commit 에 그대로 있어야 함

## 의무 항목 3 — regression verify

fix 후 반드시 옛 fix 가 보존됐는지 self-verify 해야 함.

```bash
# 옛 cycle 기준 SHA 와 현 HEAD diff
git diff <옛-cycle-sha>..HEAD -- <fix-file>

# 또는 특정 줄 존재 여부 확인
grep -n "<옛-fix-코드>" <fix-file>
```

- 옛 fix 의 핵심 line 이 새 commit 에 그대로 있는지 확인해라
- 다른 sub-agent 의 작업으로 overwrite 된 경우 → 즉시 재 fix 의무
- verify 결과를 완료 보고에 명시 (file:line → 존재 여부)

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
git diff <옛-SHA>..HEAD -- <fix-file>
```

- `git diff` 의 `+` 라인이 finding 의 location:line 영역에 있는지 확인해라
- fix 가 finding 이 지적한 실제 코드를 변경했는지 (location drift 방지)
- verify 결과를 완료 보고에 명시 (finding location → diff line 일치 여부)

## 의무 항목 7 — cycle history 의 block 사유 fix evidence 보존

옛 cycle (cycle 1~N) 의 block 사유 fix 가 새 commit 에 그대로 있는지 확인해야 함.

```bash
# 옛 cycle 의 block 사유 finding 이 fix 된 file:line 을 grep 으로 확인
grep -n "<옛-fix-핵심-코드>" <fix-file>

# 또는 옛 cycle commit 의 변경과 현 HEAD 비교
git diff <옛-cycle-sha>..HEAD -- <fix-file> | grep "^-"
```

- 옛 cycle 의 block 사유 fix 가 `-` 라인 (삭제) 으로 나타나면 regression → 즉시 재 fix
- 보존 의무: cycle 1 부터 현재 cycle 까지 모든 block 사유 fix 가 HEAD 에 존재해야 함

---

## 완료 보고 의무 항목

fix sub-agent 의 완료 보고에는 반드시 다음을 포함해야 함:

1. **각 finding 의 fix 위치** — `file:line` + 변경 내용 요약
2. **옛 fix 보존 verify 결과** — 옛 cycle 핵심 fix 의 `file:line` → 현 HEAD 존재 여부
3. **regression 없음 확인** — `git diff <옛-sha>..HEAD` 결과 요약
4. **review comment 직접 read 여부** — "gh pr view --json reviews 로 직접 확인" 명시
5. **block 사유 우선 fix 확인** — block 사유 finding 목록 + fix 순서 명시
6. **self-verify 결과** — `git diff` 의 변경 라인 ↔ finding location 일치 여부
7. **cycle history block 사유 보존** — 옛 cycle block 사유 fix 의 현 HEAD 존재 여부 (file:line)
