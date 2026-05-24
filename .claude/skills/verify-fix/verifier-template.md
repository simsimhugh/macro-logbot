# verify-fix sub-agent brief template

본 template 은 main session 이 verifier sub-agent 에게 전달하는 brief 의 의무 항목 spec.
main session 은 verifier spawn 시 아래 항목을 모두 포함한 brief 를 작성해야 함.

---

## 의무 항목 1 — 옛 fix evidence preserved 검증

verifier sub-agent 는 이전 모든 cycle 의 fix 가 현 HEAD 에 그대로 있는지 확인해야 함.

```bash
# 전체 commit history (main 이후)
git log --oneline origin/main..HEAD

# 특정 이전 cycle commit 의 변경 내용
git show <옛-cycle-sha> --stat
git show <옛-cycle-sha> -- <fix-file>

# 옛 fix 의 핵심 코드가 현 HEAD 에 있는지 grep
grep -n "<옛-fix-핵심-코드>" <fix-file>
```

- 옛 cycle 의 fix 가 현 HEAD 에 없으면 → **FAIL** + 재 fix 의무 보고
- 각 이전 cycle 의 핵심 fix file:line 을 표로 정리해 존재 여부 명시

## 의무 항목 2 — 새 finding fix evidence 매핑

verifier sub-agent 는 새 cycle 의 각 finding 에 대해 fix 의 actual file:line + diff 를 매핑해야 함.

```bash
# 새 cycle fix commit 의 변경 내용
git show HEAD --stat
git show HEAD -- <fix-file>

# finding 이 지정한 location 의 현재 내용 확인
# (finding location: "path/to/file.py:42" → 해당 줄 Read)
```

- finding 별 fix 표:

| finding | severity | location | fix file:line | 확인 방법 |
|---|---|---|---|---|
| finding 1 | CRITICAL | file.py:42 | file.py:42 | git show HEAD -- file.py |
| ... | ... | ... | ... | ... |

- fix evidence 가 없는 finding → **FAIL** + 재 fix 의무 보고

## 의무 항목 3 — regression catch

verifier sub-agent 는 옛 fix 가 새 작업으로 overwrite 됐는지 검출해야 함.

```bash
# 옛 cycle SHA 와 현 HEAD 의 fix file diff
git diff <옛-cycle-sha>..HEAD -- <fix-file>

# 옛 fix 의 핵심 line 이 삭제됐는지 확인 (- 라인으로 표기되면 regression)
git diff <옛-cycle-sha>..HEAD -- <fix-file> | grep "^-"
```

- 옛 fix line 이 `-` 로 표기 (삭제) 됐으면 → **FAIL** 즉시 보고
- regression 발견 시 어떤 commit 이 overwrite 했는지 특정:

```bash
git log --oneline <옛-cycle-sha>..HEAD -- <fix-file>
```

## 의무 항목 4 — end-to-end test (post.sh dry-run)

verifier sub-agent 는 반드시 actual `post.sh` dry-run 을 호출해 self-test bug 를 catch 해야 함.
(cycle 6 의 `gh --arg broken` bug — dry-run 안 하면 발견 불가 사례의 직접 차단)

```bash
# stub env dir 준비 (실제 PAT 불필요 — dry-run 은 identity verify 까지만 실행)
# MACRO_LOGBOT_BOT_ENV_DIR 로 mock env 지정
STUB_DIR=$(mktemp -d)
cat > "$STUB_DIR/code-reviewer-bot.env" <<'ENVEOF'
GH_TOKEN=fake-token-for-dry-run
GH_USER=simsim-code-reviewer-bot
ENVEOF
chmod 600 "$STUB_DIR/code-reviewer-bot.env"

# dry-run 호출 (실제 gh API 없이 body render 까지 확인)
# 주의: dry-run 은 env source + identity verify 실행 — 실제 PAT 없으면 exit 2 발생
# → verifier 는 아래 중 하나 선택:
#   a) 실제 PAT 가 있으면 DRY_RUN=1 직접 호출
#   b) post_helper.py render_findings / render_template 만 단위 테스트
```

**최소 검증 항목 (PAT 없는 환경):**

```bash
# render_findings — PASS/LOW 제외 + severity 정렬 확인
python3 .claude/skills/post-review/post_helper.py render_findings \
  '[{"severity":"MED","title":"Dead code","detail":"unused var"}]' \
  .claude/skills/post-review/templates/code-reviewer.md

# expected_verdict — 옵션 C: MED only → APPROVE (CRITICAL/HIGH only blocking)
python3 .claude/skills/post-review/post_helper.py expected_verdict \
  '[{"severity":"MED","title":"Dead code"}]'
# 기대 출력: APPROVE

# expected_verdict — CRITICAL at HIGH confidence → REQUEST_CHANGES
python3 .claude/skills/post-review/post_helper.py expected_verdict \
  '[{"severity":"CRITICAL","title":"SQL injection","confidence":"HIGH"}]'
# 기대 출력: REQUEST_CHANGES

# expected_verdict — CRITICAL at LOW confidence → APPROVE
python3 .claude/skills/post-review/post_helper.py expected_verdict \
  '[{"severity":"CRITICAL","title":"SQL injection","confidence":"LOW"}]'
# 기대 출력: APPROVE
```

## 의무 항목 5 — block 사유 별 specific verify

verifier sub-agent 는 각 block 사유 finding 의 location 의 actual content 가 fix 됐는지 구체적으로 확인해야 함.

```bash
# finding location: "post_helper.py:60" → 해당 줄의 현재 내용 직접 Read
Read /path/to/post_helper.py  (offset: 58, limit: 5)

# 또는 grep 으로 fix 된 패턴 확인
grep -n "<fix-됐어야-할-패턴>" <fix-file>

# e.g. "hook 의 false-positive" finding → hook 의 regex pattern 정밀화 됐는지
grep -n "<정밀화된-regex>" .claude/hooks/pre-bash-gate.sh
```

- 각 finding 의 `location` field 의 실제 file:line content 를 직접 확인 (추정 금지)
- finding 의 `code` field 와 현재 파일 내용 비교 — `code` 가 더 이상 존재하지 않아야 정상
- e.g. "hook 의 false-positive" finding → hook 의 regex pattern 이 정밀화 됐는지 grep + diff verify

## 의무 항목 6 — cycle history regression tracking

verifier sub-agent 는 옛 cycle (cycle 1~N) 의 block 사유 list 가 새 cycle 에서 재 surface 됐는지 추적해야 함.

```bash
# PR review history 에서 옛 cycle 의 block 사유 finding 목록 추출
gh pr view <PR-NUM> --json reviews --jq '.reviews[].body' | grep -E "(CRITICAL|HIGH|MED|WARN)"

# 옛 cycle SHA 에서 fix 된 코드가 현 HEAD 에도 fix 돼 있는지 확인
git show <옛-cycle-sha> -- <fix-file> | grep "^+"  # 옛 cycle 이 추가한 fix 코드
grep -n "<옛-fix-코드>" <fix-file>                 # 현 HEAD 에도 존재해야 함
```

- 옛 cycle 의 block 사유 finding title 목록을 PR review history 에서 추출해라
- 해당 finding 이 새 cycle 에서 다시 나타나면 → **FAIL** (regression — fix 가 덮어쓰여졌거나 revert 됨)
- cycle history regression 발견 시 어떤 commit 이 재 도입했는지 특정:

```bash
git log --oneline <옛-cycle-sha>..HEAD -- <fix-file>
```

## 의무 항목 7 — end-to-end dry-run (post.sh sample 호출)

verifier sub-agent 는 반드시 `post.sh` 의 helper function 을 직접 호출해 role-specific verdict 와 body render 를 검증해야 함.

```bash
HELPER=".claude/skills/post-review/post_helper.py"

# 1. code-reviewer + MED only → APPROVE (code-reviewer 는 MED blocking 안 함)
python3 "$HELPER" expected_verdict '[{"severity":"MED","title":"Dead code"}]' "code-reviewer"
# 기대: APPROVE

# 2. architect + MED only → REQUEST_CHANGES (architect 는 MED blocking)
python3 "$HELPER" expected_verdict '[{"severity":"MED","title":"Dead code"}]' "architect"
# 기대: REQUEST_CHANGES

# 3. security-reviewer + WARN only → APPROVE (MED/WARN = informational, 2026-05-24)
python3 "$HELPER" expected_verdict '[{"severity":"WARN","title":"Weak cipher"}]' "security-reviewer"
# 기대: APPROVE

# 4. code-reviewer body render: MED finding → body 에 없음
python3 "$HELPER" render_findings '[{"severity":"MED","title":"Dead code","detail":"unused"}]' \
  ".claude/skills/post-review/templates/code-reviewer.md" "code-reviewer"
# 기대: "_(no blocking findings)_"

# 5. architect body render: MED finding → body 에 render 됨
python3 "$HELPER" render_findings '[{"severity":"MED","title":"Dead code","detail":"unused"}]' \
  ".claude/skills/post-review/templates/architect.md" "architect"
# 기대: "Dead code" 포함

# 6. code-reviewer + CRITICAL at LOW confidence → APPROVE
python3 "$HELPER" expected_verdict '[{"severity":"CRITICAL","title":"SQL injection","confidence":"LOW"}]' "code-reviewer"
# 기대: APPROVE
```

- 위 6 개 dry-run 모두 기대 결과와 일치해야 함 → 하나라도 다르면 **FAIL**
- 옛 block 사유 finding 을 sample 로 사용해 실제 blocking 여부 confirm

---

## 완료 보고 의무 항목

verifier sub-agent 의 완료 보고에는 반드시 다음을 포함해야 함:

1. **옛 fix preserved 표** — 옛 cycle 핵심 fix 의 file:line → 현 HEAD 존재 여부 (PASS/FAIL)
2. **새 finding fix evidence 표** — finding 별 fix file:line + diff 요약
3. **regression 없음 확인** — "옛 fix overwrite 없음" 또는 발견된 regression 상세
4. **end-to-end test 결과** — render_findings / expected_verdict 단위 테스트 출력
5. **block 사유 별 specific verify** — 각 finding location 의 actual content fix 확인
6. **cycle history regression tracking** — 옛 cycle block 사유 재 surface 여부 (PASS/FAIL)
7. **end-to-end dry-run 결과** — post.sh helper 6 개 sample 호출 + 기대 결과 일치 여부
8. **전체 verdict** — PASS (모두 확인) 또는 FAIL (재 fix 필요 항목 명시)
