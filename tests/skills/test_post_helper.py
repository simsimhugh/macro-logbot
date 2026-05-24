"""post_helper.py 단위 테스트 (finding N).

post_helper.py 는 sys.path 에 없으므로 importlib 로 직접 load.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# post_helper.py 경로 — .claude/skills/post-review/post_helper.py
_HELPER_PATH = (
    Path(__file__).parent.parent.parent / ".claude" / "skills" / "post-review" / "post_helper.py"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location("post_helper", _HELPER_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


ph = _load_helper()

# ---------------------------------------------------------------------------
# extract_field
# ---------------------------------------------------------------------------


def test_extract_field_present():
    assert ph.extract_field('{"login": "bot-user"}', "login") == "bot-user"


def test_extract_field_missing():
    assert ph.extract_field('{"login": "bot-user"}', "missing") == ""


def test_extract_field_null():
    assert ph.extract_field('{"commit_id": null}', "commit_id") == ""


# ---------------------------------------------------------------------------
# findings_len
# ---------------------------------------------------------------------------


def test_findings_len_empty():
    assert ph.findings_len("[]") == "0"


def test_findings_len_two():
    assert ph.findings_len('[{"severity":"PASS"},{"severity":"INFO"}]') == "2"


# ---------------------------------------------------------------------------
# expected_verdict
# ---------------------------------------------------------------------------


def test_expected_verdict_pass_only():
    assert ph.expected_verdict('[{"severity":"PASS","title":"ok","detail":""}]') == "APPROVE"


def test_expected_verdict_info_only():
    assert ph.expected_verdict('[{"severity":"INFO","title":"note","detail":""}]') == "APPROVE"


def test_expected_verdict_low_only():
    assert ph.expected_verdict('[{"severity":"LOW","title":"style","detail":""}]') == "APPROVE"


def test_expected_verdict_warn_blocks():
    # WARN blocks for non-code-reviewer roles (default role = "")
    assert (
        ph.expected_verdict('[{"severity":"WARN","title":"issue","detail":""}]', "architect")
        == "REQUEST_CHANGES"
    )


def test_expected_verdict_med_blocks():
    # MED blocks for non-code-reviewer roles (default role = "")
    assert (
        ph.expected_verdict('[{"severity":"MED","title":"issue","detail":""}]', "architect")
        == "REQUEST_CHANGES"
    )


def test_expected_verdict_high_blocks():
    assert (
        ph.expected_verdict('[{"severity":"HIGH","title":"issue","detail":""}]')
        == "REQUEST_CHANGES"
    )


def test_expected_verdict_critical_blocks():
    assert (
        ph.expected_verdict('[{"severity":"CRITICAL","title":"issue","detail":""}]')
        == "REQUEST_CHANGES"
    )


def test_expected_verdict_unknown_severity_blocks():
    # finding A: unknown severity → conservative REQUEST_CHANGES
    assert (
        ph.expected_verdict('[{"severity":"CRIT","title":"typo","detail":""}]') == "REQUEST_CHANGES"
    )


# ---------------------------------------------------------------------------
# validate_findings
# ---------------------------------------------------------------------------


def test_validate_findings_ok():
    assert ph.validate_findings('[{"severity":"PASS"}]') == "OK"


def test_validate_findings_parse_error():
    result = ph.validate_findings("{not valid json")
    assert result.startswith("PARSE_ERROR:")


def test_validate_findings_not_array():
    result = ph.validate_findings('{"severity":"PASS"}')
    assert result.startswith("NOT_ARRAY:")


# ---------------------------------------------------------------------------
# validate_finding_format
# ---------------------------------------------------------------------------


def test_validate_finding_format_valid():
    ph.validate_finding_format('[{"severity":"PASS","title":"no issues","detail":"all good"}]')


def test_validate_finding_format_missing_severity(capsys):
    with pytest.raises(SystemExit):
        ph.validate_finding_format('[{"title":"ok"}]')


def test_validate_finding_format_unknown_severity(capsys):
    with pytest.raises(SystemExit):
        ph.validate_finding_format('[{"severity":"CRIT","title":"ok"}]')


def test_validate_finding_format_title_too_long(capsys):
    with pytest.raises(SystemExit):
        ph.validate_finding_format(
            '[{"severity":"PASS","title":"this title is way too long to be accepted here"}]'
        )


def test_validate_finding_format_title_too_many_words(capsys):
    with pytest.raises(SystemExit):
        ph.validate_finding_format('[{"severity":"PASS","title":"one two three four"}]')


def test_validate_finding_format_detail_too_long(capsys):
    with pytest.raises(SystemExit):
        ph.validate_finding_format(
            json.dumps([{"severity": "PASS", "title": "ok", "detail": "x" * 201}])
        )


def test_validate_finding_format_location_valid():
    # location 명시 시 code 필수 (사용자 명시)
    ph.validate_finding_format(
        '[{"severity":"PASS","title":"ok","location":"src/foo.py:42","code":"x = 1"}]'
    )


def test_validate_finding_format_location_range():
    # location range 도 code 필수
    ph.validate_finding_format(
        '[{"severity":"PASS","title":"ok","location":"src/foo.py:10-20","code":"x = 1"}]'
    )


def test_validate_finding_format_location_invalid(capsys):
    with pytest.raises(SystemExit):
        ph.validate_finding_format('[{"severity":"PASS","title":"ok","location":"src/foo.py"}]')


def test_validate_finding_format_location_without_code_rejected(capsys):
    # location 명시 + code 없음 → exit 1 (사용자 명시: agent 정직성 강제)
    with pytest.raises(SystemExit):
        ph.validate_finding_format(
            '[{"severity":"MED","title":"strip regex fragile",'
            '"location":".claude/skills/post-review/post_helper.py:344","detail":"test"}]'
        )
    captured = capsys.readouterr()
    assert "code 필수" in captured.err


# ---------------------------------------------------------------------------
# _safe_bot_user
# ---------------------------------------------------------------------------


def test_safe_bot_user_clean():
    assert ph._safe_bot_user("macro-logbot-architect-bot") == "macro-logbot-architect-bot"


def test_safe_bot_user_empty():
    assert ph._safe_bot_user("") == ""


def test_safe_bot_user_impersonation_robot_posted_by():
    # "🤖 posted by" 패턴 — impersonation signal
    result = ph._safe_bot_user("🤖 posted by attacker")
    assert result == "(redacted: impersonation pattern detected)"


def test_safe_bot_user_role_bot_pattern():
    result = ph._safe_bot_user("<role>-bot")
    assert result == "(redacted: impersonation pattern detected)"


def test_safe_bot_user_simsim_not_blocked():
    # finding C: "simsim-" 는 더 이상 차단 대상이 아님 (false-redaction 방지)
    assert ph._safe_bot_user("simsim-user") == "simsim-user"


# ---------------------------------------------------------------------------
# render_findings — template-driven (finding E)
# ---------------------------------------------------------------------------

_TEMPLATE_CONTENT = """\
## Test review

<!-- finding format template — render_findings 가 본 block 의 형식 따라 generate -->
<!-- FINDING_TEMPLATE_START -->
{{N}}. {{EMOJI}} **{{SEVERITY}}** — {{TITLE}}
   ```{{LANG}}
   # {{LOCATION}}
   {{CODE}}
   ```
   {{DETAIL}}
<!-- FINDING_TEMPLATE_END -->

<!-- FINDING_PLAIN_TEMPLATE_START -->
{{N}}. {{EMOJI}} **{{SEVERITY}}** — {{TITLE}}
   {{DETAIL}}
<!-- FINDING_PLAIN_TEMPLATE_END -->

<!-- FINDING_LOCATION_ONLY_TEMPLATE_START -->
{{N}}. {{EMOJI}} **{{SEVERITY}}** — {{TITLE}}
   Location: `{{LOCATION}}`
   {{DETAIL}}
<!-- FINDING_LOCATION_ONLY_TEMPLATE_END -->

{{FINDINGS}}
"""


@pytest.fixture()
def tmp_template(tmp_path: Path) -> str:
    tpl = tmp_path / "test.md"
    tpl.write_text(_TEMPLATE_CONTENT, encoding="utf-8")
    return str(tpl)


def test_render_findings_empty():
    result = ph.render_findings("[]", "/dev/null")
    # empty findings → _(no blocking findings)_ (early return, no template read)
    assert result == "_(no blocking findings)_"


def test_render_findings_plain_branch(tmp_template: str):
    # no code, no location → FINDING_PLAIN_TEMPLATE 사용
    # WARN severity: renders for all roles (architect default)
    findings = json.dumps([{"severity": "WARN", "title": "no issues", "detail": "all ok"}])
    result = ph.render_findings(findings, tmp_template)
    assert "no issues" in result
    assert "all ok" in result
    assert "```" not in result  # code block 없음


def test_render_findings_location_only_branch(tmp_template: str):
    # location 만 있음 → FINDING_LOCATION_ONLY_TEMPLATE 사용
    # WARN severity: renders for all roles
    findings = json.dumps(
        [{"severity": "WARN", "title": "see here", "detail": "check it", "location": "foo.py:10"}]
    )
    result = ph.render_findings(findings, tmp_template)
    assert "Location: `foo.py:10`" in result
    assert "```" not in result


def test_render_findings_full_code_branch(tmp_template: str):
    # code 있음 → FINDING_TEMPLATE 사용
    findings = json.dumps(
        [
            {
                "severity": "HIGH",
                "title": "bad code",
                "detail": "fix it",
                "location": "bar.py:5",
                "code": "x = 1",
                "language": "python",
            }
        ]
    )
    result = ph.render_findings(findings, tmp_template)
    assert "```python" in result
    assert "x = 1" in result
    assert "bar.py:5" in result


def test_render_findings_sorted_by_severity(tmp_template: str):
    # CRITICAL 먼저, WARN 나중 (PASS/LOW 는 body render 에서 제외 — INFO/WARN/MED/HIGH/CRITICAL 만)
    findings = json.dumps(
        [
            {"severity": "WARN", "title": "warn item", "detail": ""},
            {"severity": "CRITICAL", "title": "bad crit", "detail": ""},
        ]
    )
    result = ph.render_findings(findings, tmp_template)
    assert result.index("bad crit") < result.index("warn item")


def test_render_findings_no_false_redaction(tmp_template: str):
    # finding C: "simsim-" 가 finding title 에 있어도 redact 안 됨
    # WARN severity: renders for all roles
    findings = json.dumps([{"severity": "WARN", "title": "simsim-fix", "detail": "some detail"}])
    result = ph.render_findings(findings, tmp_template)
    assert "simsim-fix" in result
    assert "redacted" not in result


# ---------------------------------------------------------------------------
# render_template — BOT_USER _safe_bot_user 적용 (finding C)
# ---------------------------------------------------------------------------

_FULL_TEMPLATE = """\
## review

<!-- finding format template — spec comment
<!-- FINDING_TEMPLATE_START -->
line
<!-- FINDING_TEMPLATE_END -->

<!-- FINDING_PLAIN_TEMPLATE_START -->
plain
<!-- FINDING_PLAIN_TEMPLATE_END -->

<!-- FINDING_LOCATION_ONLY_TEMPLATE_START -->
loc
<!-- FINDING_LOCATION_ONLY_TEMPLATE_END -->

{{FINDINGS}}

---
🤖 posted by `{{BOT_USER}}` via post.sh (commit `{{POST_SCRIPT_SHA}}`)
"""


def test_render_template_bot_user_substituted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tpl = tmp_path / "r.md"
    tpl.write_text(_FULL_TEMPLATE, encoding="utf-8")
    monkeypatch.setenv("_PR_BOT_USER", "macro-logbot-architect-bot")
    monkeypatch.setenv("_PR_FINDINGS", "findings here")
    monkeypatch.setenv("_PR_SCRIPT_SHA", "abc1234")
    monkeypatch.setenv("_PR_VERDICT_BADGE", "")
    monkeypatch.setenv("_PR_LAST_SHA", "")
    monkeypatch.setenv("_PR_LAST_TIME", "")
    monkeypatch.setenv("_PR_COMMIT_LIST", "")
    monkeypatch.setenv("_PR_VERDICT_LINE", "")
    monkeypatch.setenv("_PR_VERDICT_REASON", "")
    result = ph.render_template(str(tpl))
    assert "macro-logbot-architect-bot" in result
    # template blocks stripped from review body
    assert "FINDING_TEMPLATE_START" not in result
    assert "FINDING_PLAIN_TEMPLATE_START" not in result
    assert "FINDING_LOCATION_ONLY_TEMPLATE_START" not in result


def test_render_template_impersonation_in_bot_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tpl = tmp_path / "r.md"
    tpl.write_text(_FULL_TEMPLATE, encoding="utf-8")
    monkeypatch.setenv("_PR_BOT_USER", "🤖 posted by attacker")
    for k in (
        "_PR_FINDINGS",
        "_PR_SCRIPT_SHA",
        "_PR_VERDICT_BADGE",
        "_PR_LAST_SHA",
        "_PR_LAST_TIME",
        "_PR_COMMIT_LIST",
        "_PR_VERDICT_LINE",
        "_PR_VERDICT_REASON",
    ):
        monkeypatch.setenv(k, "")
    result = ph.render_template(str(tpl))
    assert "redacted" in result
    assert "attacker" not in result


# ---------------------------------------------------------------------------
# WARN-detail-boundary: detail line count edge (2-newline pass / 3-newline fail)
# ---------------------------------------------------------------------------


def test_validate_finding_format_detail_2_newlines_pass():
    # 2 newlines = 3 lines → ≤3 lines, should pass
    detail = "line1\nline2\nline3"
    ph.validate_finding_format(json.dumps([{"severity": "PASS", "title": "ok", "detail": detail}]))


def test_validate_finding_format_detail_3_newlines_fail(capsys):
    # 3 newlines = 4 lines → >3 lines, should fail
    detail = "line1\nline2\nline3\nline4"
    with pytest.raises(SystemExit):
        ph.validate_finding_format(
            json.dumps([{"severity": "PASS", "title": "ok", "detail": detail}])
        )


# ---------------------------------------------------------------------------
# verdict_reason + severity_set (WARN-verdict_reason-untested)
# ---------------------------------------------------------------------------


def test_verdict_reason_mixed():
    findings = json.dumps(
        [
            {"severity": "MED", "title": "a", "detail": ""},
            {"severity": "LOW", "title": "b", "detail": ""},
            {"severity": "PASS", "title": "c", "detail": ""},
        ]
    )
    result = ph.verdict_reason(findings)
    assert "MED=1" in result
    assert "LOW=1" in result
    assert "PASS=1" in result


def test_verdict_reason_unknown_severity():
    findings = json.dumps([{"severity": "TYPO", "title": "x", "detail": ""}])
    result = ph.verdict_reason(findings)
    assert "UNKNOWN=" in result
    assert "TYPO" in result


def test_severity_set_sorted():
    findings = json.dumps(
        [
            {"severity": "LOW", "title": "a", "detail": ""},
            {"severity": "HIGH", "title": "b", "detail": ""},
        ]
    )
    result = ph.severity_set(findings)
    # should be sorted list string
    assert "HIGH" in result
    assert "LOW" in result


# ---------------------------------------------------------------------------
# language allowlist gap (LOW-language-allowlist-gap)
# ---------------------------------------------------------------------------


def test_validate_finding_format_invalid_language(capsys):
    with pytest.raises(SystemExit):
        ph.validate_finding_format(
            json.dumps(
                [
                    {
                        "severity": "PASS",
                        "title": "ok",
                        "language": "cobol",
                        "code": "x = 1",
                    }
                ]
            )
        )


def test_validate_finding_format_empty_language_pass():
    # empty language is allowed
    ph.validate_finding_format(
        json.dumps([{"severity": "PASS", "title": "ok", "language": "", "code": "x = 1"}])
    )


# ---------------------------------------------------------------------------
# _extract_block error path (LOW-_extract_block-error)
# ---------------------------------------------------------------------------


def test_extract_block_missing_raises():
    content = "no markers here"
    with pytest.raises(ValueError, match="block 없음"):
        ph._extract_block(content, "<!-- START -->", "<!-- END -->")


# ---------------------------------------------------------------------------
# non-dict finding item (LOW-non-dict-finding)
# ---------------------------------------------------------------------------


def test_validate_finding_format_non_dict(capsys):
    with pytest.raises(SystemExit):
        ph.validate_finding_format('["not a dict"]')


# ---------------------------------------------------------------------------
# empty verdict edge (LOW-empty-verdict)
# ---------------------------------------------------------------------------


def test_verdict_reason_empty():
    result = ph.verdict_reason("[]")
    assert result == "findings: none"


def test_expected_verdict_empty_array():
    # empty array → no blocking severities → APPROVE
    assert ph.expected_verdict("[]") == "APPROVE"


# ---------------------------------------------------------------------------
# LOW-code-fence-escape: ``` in code field must be escaped
# ---------------------------------------------------------------------------


def test_render_findings_code_fence_escaped(tmp_template: str):
    # code 내 ``` 는 \`\`\` 로 escape — GitHub markdown code fence 깨짐 방지
    findings = json.dumps(
        [
            {
                "severity": "WARN",
                "title": "fence break",
                "detail": "code has backticks",
                "location": "foo.py:1",
                "code": "x = ```value```",
                "language": "python",
            }
        ]
    )
    result = ph.render_findings(findings, tmp_template)
    assert "\\`\\`\\`" in result
    # raw ``` sequence must not appear inside a code block as literal fence
    # (the opening/closing ``` of the block itself are in the template, not in code)
    lines = result.split("\n")
    code_lines = [ln for ln in lines if "value" in ln]
    assert code_lines, "code content must appear in output"
    for ln in code_lines:
        assert "```" not in ln, f"unescaped ``` found in code line: {ln!r}"


# ---------------------------------------------------------------------------
# LOW-severity-integration: validate_finding_format rejects unknown severity
# expected_verdict treats unknown as conservative REQUEST_CHANGES
# ---------------------------------------------------------------------------


def test_validate_finding_format_unknown_severity_rejected(capsys):
    # unknown severity (not in SEV_ALLOWLIST) → exit 1
    with pytest.raises(SystemExit):
        ph.validate_finding_format('[{"severity":"BLOCKER","title":"x"}]')
    captured = capsys.readouterr()
    assert "미허용값" in captured.err or "허용값" in captured.err


def test_expected_verdict_unknown_severity_conservative():
    # unknown severity → conservative REQUEST_CHANGES (not silent APPROVE)
    result = ph.expected_verdict('[{"severity":"BLOCKER","title":"x","detail":""}]')
    assert result == "REQUEST_CHANGES"


def test_expected_verdict_mixed_unknown_and_pass():
    # unknown + PASS → REQUEST_CHANGES (unknown blocks)
    findings = json.dumps(
        [
            {"severity": "PASS", "title": "ok", "detail": ""},
            {"severity": "TYPO_SEV", "title": "typo sev", "detail": ""},
        ]
    )
    assert ph.expected_verdict(findings) == "REQUEST_CHANGES"


# ---------------------------------------------------------------------------
# role-specific verdict logic (사용자 명시 2026-05-23)
# ---------------------------------------------------------------------------


def test_expected_verdict_code_reviewer_med_approve():
    # code-reviewer + MED only → APPROVE (MED 는 code-reviewer 에게 informational)
    assert (
        ph.expected_verdict('[{"severity":"MED","title":"Dead code"}]', "code-reviewer")
        == "APPROVE"
    )


def test_expected_verdict_architect_med_request_changes():
    # architect + MED only → REQUEST_CHANGES (architect 는 MED blocking)
    assert (
        ph.expected_verdict('[{"severity":"MED","title":"Dead code"}]', "architect")
        == "REQUEST_CHANGES"
    )


def test_expected_verdict_security_warn_approve():
    # security-reviewer + WARN only → APPROVE (MED/WARN = informational, 2026-05-24)
    assert (
        ph.expected_verdict('[{"severity":"WARN","title":"Weak cipher"}]', "security-reviewer")
        == "APPROVE"
    )


def test_expected_verdict_code_reviewer_critical_low_confidence_approve():
    # code-reviewer + CRITICAL with LOW confidence → APPROVE (LOW confidence = informational)
    assert (
        ph.expected_verdict(
            '[{"severity":"CRITICAL","title":"SQL injection","confidence":"LOW"}]',
            "code-reviewer",
        )
        == "APPROVE"
    )


# ---------------------------------------------------------------------------
# role-specific render_findings body policy (사용자 명시 2026-05-23)
# ---------------------------------------------------------------------------


def test_render_findings_code_reviewer_med_skip(tmp_template: str):
    # code-reviewer + MED finding → body 에 없음 (_(no blocking findings)_)
    findings = json.dumps([{"severity": "MED", "title": "Dead code", "detail": "unused var"}])
    result = ph.render_findings(findings, tmp_template, "code-reviewer")
    assert result == "_(no blocking findings)_"


def test_render_findings_architect_med_render(tmp_template: str):
    # architect + MED finding → body 에 render 됨
    findings = json.dumps([{"severity": "MED", "title": "Dead code", "detail": "unused var"}])
    result = ph.render_findings(findings, tmp_template, "architect")
    assert "Dead code" in result


def test_render_findings_low_info_skip_all_roles(tmp_template: str):
    # LOW / INFO 는 모든 role 에서 body render skip
    low_findings = json.dumps([{"severity": "LOW", "title": "Minor style", "detail": "nit"}])
    info_findings = json.dumps([{"severity": "INFO", "title": "FYI note", "detail": "note"}])
    for role in ("code-reviewer", "architect", "security-reviewer", "test-engineer", ""):
        assert ph.render_findings(low_findings, tmp_template, role) == "_(no blocking findings)_"
        assert ph.render_findings(info_findings, tmp_template, role) == "_(no blocking findings)_"


# ---------------------------------------------------------------------------
# extract_review_ids (PR #75: dismiss old reviews from same role)
# ---------------------------------------------------------------------------


def test_extract_review_ids_returns_matching_user_id():
    reviews = json.dumps([{"id": 111, "user": {"login": "my-bot"}}])
    result = ph.extract_review_ids(reviews, "my-bot")
    assert result == "111"


def test_extract_review_ids_returns_multiple_ids_newline_separated():
    reviews = json.dumps(
        [
            {"id": 10, "user": {"login": "my-bot"}},
            {"id": 20, "user": {"login": "my-bot"}},
        ]
    )
    result = ph.extract_review_ids(reviews, "my-bot")
    assert result == "10\n20"


def test_extract_review_ids_ignores_other_users():
    reviews = json.dumps(
        [
            {"id": 10, "user": {"login": "my-bot"}},
            {"id": 99, "user": {"login": "other-bot"}},
        ]
    )
    result = ph.extract_review_ids(reviews, "my-bot")
    assert result == "10"
    assert "99" not in result


def test_extract_review_ids_returns_empty_string_when_no_match():
    reviews = json.dumps([{"id": 55, "user": {"login": "other-bot"}}])
    result = ph.extract_review_ids(reviews, "my-bot")
    assert result == ""


def test_extract_review_ids_empty_array_returns_empty_string():
    result = ph.extract_review_ids("[]", "my-bot")
    assert result == ""


def test_extract_review_ids_skips_non_dict_items():
    # non-dict entries (e.g. null, string) must be skipped without crashing
    reviews = json.dumps([None, "bad", {"id": 42, "user": {"login": "my-bot"}}])
    result = ph.extract_review_ids(reviews, "my-bot")
    assert result == "42"


def test_extract_review_ids_skips_entry_with_missing_user_key():
    reviews = json.dumps([{"id": 7}, {"id": 8, "user": {"login": "my-bot"}}])
    result = ph.extract_review_ids(reviews, "my-bot")
    assert result == "8"


def test_extract_review_ids_skips_entry_with_null_user():
    reviews = json.dumps([{"id": 3, "user": None}, {"id": 4, "user": {"login": "my-bot"}}])
    result = ph.extract_review_ids(reviews, "my-bot")
    assert result == "4"


def test_extract_review_ids_id_returned_as_string():
    # IDs must be strings (used in shell loop as gh api path segment)
    reviews = json.dumps([{"id": 9999, "user": {"login": "bot"}}])
    ids = ph.extract_review_ids(reviews, "bot").split("\n")
    assert all(isinstance(i, str) for i in ids)
    assert ids == ["9999"]


def test_extract_review_ids_skips_dismissed():
    reviews = json.dumps(
        [
            {"id": 100, "user": {"login": "bot"}, "state": "APPROVED"},
            {"id": 200, "user": {"login": "bot"}, "state": "DISMISSED"},
            {"id": 300, "user": {"login": "bot"}, "state": "CHANGES_REQUESTED"},
        ]
    )
    result = ph.extract_review_ids(reviews, "bot")
    assert result == "100\n300"


def test_extract_review_ids_int_cast():
    # non-integer id raises ValueError (defense-in-depth)
    reviews = json.dumps([{"id": "not-a-number", "user": {"login": "bot"}}])
    with pytest.raises(ValueError):
        ph.extract_review_ids(reviews, "bot")
