#!/usr/bin/env python3
"""post_helper.py — post.sh 의 python3 inline DRY 분리 (finding N).

사용법: python3 post_helper.py <command> [args...]

commands:
  extract_field <json> <field>      — JSON object 에서 단일 field 추출 (str, default "")
  findings_len <json>               — findings array 길이 출력
  expected_verdict <json>           — findings severity 기반 verdict 출력
                                      severity ∈ {CRITICAL,HIGH,MED,WARN,LOW,INFO,PASS}
                                      unknown severity → conservative REQUEST_CHANGES
  render_findings <json> <tpl>      — template file 의 FINDING_TEMPLATE block 기반 findings 출력
                                      (사용자 명시: template 이 render 의 단일 source)
  verdict_reason <json>             — severity count 요약 출력
  severity_set <json>               — severity set 출력 (sorted, bracket)
  policy_summary <role>             — verdict mismatch 에러용 정책 산문 (role-specific)
  verdict_line <role> <verdict>     — PR body verdict 한 줄 (role-specific)
  extract_review_node_ids          — stdin: reviews JSON, argv: user → node IDs (GraphQL)
  validate_findings <json>          — OK / PARSE_ERROR:<msg> / NOT_ARRAY:<type>
  validate_finding_format <json>    — finding severity/length/format validate
                                      (finding A: severity allow-list, finding E: location range)
  render_template <template_file>   — env var 기반 template placeholder 치환 후 stdout 출력
"""

import collections
import json
import re
import sys

SEV_EMOJI = {
    "CRITICAL": "🚨",
    "HIGH": "❗",
    "MED": "⚠️",
    "WARN": "⚠️",
    "LOW": "🔹",
    "INFO": "ℹ️",
    "PASS": "✅",
}
SEV_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MED": 2,
    "WARN": 3,
    "LOW": 4,
    "INFO": 5,
    "PASS": 6,
}
# canonical severity allow-list (finding A: unknown severity → conservative block)
SEV_ALLOWLIST = frozenset(SEV_EMOJI.keys())

# severity order used to generate policy prose (CRITICAL → PASS).
_PROSE_ORDER = ["CRITICAL", "HIGH", "MED", "WARN", "LOW", "INFO", "PASS"]

# role-specific blocking policy — 단일 source (issue #100).
# expected_verdict() 의 verdict 로직 + policy_summary()/verdict_line() 의 산문이
# 모두 본 테이블에서 파생. 정책 변경 시 여기 한 곳만 수정.
#   blocking_sev           — REQUEST_CHANGES 를 유발하는 severity set
#   require_high_confidence — True 면 CRITICAL/HIGH 는 confidence=HIGH(또는 생략) 일 때만 blocking
#   date                   — 정책 명시일 (산문 출력용 label)
_ROLE_POLICY = {
    "code-reviewer": {
        "blocking_sev": frozenset({"CRITICAL", "HIGH"}),
        "require_high_confidence": True,
        "date": "옵션 C 2026-05-23",
    },
    "architect": {
        "blocking_sev": frozenset({"CRITICAL", "HIGH", "MED", "WARN"}),
        "require_high_confidence": False,
        "date": "2026-05-23 강화",
    },
    # default: security-reviewer / test-engineer
    "_default": {
        "blocking_sev": frozenset({"CRITICAL", "HIGH"}),
        "require_high_confidence": False,
        "date": "2026-05-24",
    },
}


def _policy_for(role: str) -> dict:
    """role 의 blocking policy 반환 (미지정 role → _default)."""
    return _ROLE_POLICY.get(role, _ROLE_POLICY["_default"])


def _blocking_label(policy: dict) -> str:
    """blocking severity 를 'CRITICAL/HIGH[ at HIGH confidence]' 산문으로."""
    sev = "/".join(s for s in _PROSE_ORDER if s in policy["blocking_sev"])
    if policy["require_high_confidence"]:
        sev += " at HIGH confidence"
    return sev


def policy_summary(role: str) -> str:
    """verdict mismatch 에러 메시지용 정책 산문 (role-specific)."""
    p = _policy_for(role)
    nonblocking = "/".join(s for s in _PROSE_ORDER if s not in p["blocking_sev"])
    msg = (
        f"정책 ({role}, {p['date']}): {_blocking_label(p)} → REQUEST_CHANGES."
        f" {nonblocking} = informational → APPROVE."
    )
    if p["require_high_confidence"]:
        blocking = "/".join(s for s in _PROSE_ORDER if s in p["blocking_sev"])
        msg += f" LOW-confidence {blocking} = informational → APPROVE."
    return msg


def verdict_line(role: str, verdict: str) -> str:
    """PR body 의 verdict 한 줄 (role-specific blocking 정책 요약)."""
    if verdict == "APPROVE":
        return "**APPROVE** — no blocking findings."
    p = _policy_for(role)
    suffix = "만 blocking." if p["require_high_confidence"] else "blocking."
    return f"**REQUEST_CHANGES** — {_blocking_label(p)} {suffix}"


def extract_field(json_str: str, field: str) -> str:
    d = json.loads(json_str)
    return str(d.get(field, "") or "")


def extract_review_node_ids(reviews_json: str, user: str) -> str:
    """reviews JSON array 에서 user.login == user 인 review 의 node_id 목록 반환.

    stdin 으로 raw reviews JSON 수신, user 는 CLI arg.
    반환: newline-separated node_id (GraphQL minimizeComment 용). 매칭 없으면 빈 문자열.
    """
    reviews = json.loads(reviews_json)
    node_ids = [
        str(r["node_id"])
        for r in reviews
        if isinstance(r, dict) and (r.get("user") or {}).get("login") == user and r.get("node_id")
    ]
    return "\n".join(node_ids)


def findings_len(json_str: str) -> str:
    d = json.loads(json_str)
    return str(len(d))


def expected_verdict(json_str: str, role: str = "") -> str:
    """findings severity 기반 verdict 산출 (role-specific, 사용자 명시 2026-05-23).

    role-specific blocking severity set:
      code-reviewer: CRITICAL / HIGH at HIGH confidence 만 blocking
                     (OMC code-reviewer prompt 정의)
      architect (강화): CRITICAL + HIGH + MED + WARN blocking, confidence 무관
      security-reviewer / test-engineer: CRITICAL + HIGH 만 blocking
                     MED / WARN = informational (verdict 영향 X)
    """
    findings = json.loads(json_str)

    # role-specific blocking severity set — 단일 source (_ROLE_POLICY, issue #100)
    _policy = _policy_for(role)
    blocking_sev = _policy["blocking_sev"]
    require_high_confidence = _policy["require_high_confidence"]

    all_sev = {f.get("severity", "").upper() for f in findings if isinstance(f, dict)}
    # unknown severity → conservative REQUEST_CHANGES
    # (finding A: typo like "CRIT" must not silent-APPROVE)
    unknown = all_sev - SEV_ALLOWLIST
    if unknown:
        return "REQUEST_CHANGES"

    has_blocking = False
    for f in findings:
        if not isinstance(f, dict):
            continue
        sev = (f.get("severity") or "").upper()
        conf = (f.get("confidence") or "HIGH").upper()
        if sev not in blocking_sev:
            continue
        if require_high_confidence and conf not in {"HIGH", ""}:
            # code-reviewer: LOW/MEDIUM confidence 는 informational
            continue
        has_blocking = True

    return "REQUEST_CHANGES" if has_blocking else "APPROVE"


_IMPERSONATION_PATTERNS = re.compile(
    r"(🤖\s*posted by\b|<role>-bot\b)",
    re.IGNORECASE,
)


def _safe_bot_user(s: str) -> str:
    """BOT_USER footer 필드 검증 — impersonation 방어 (finding C scope 수정).

    finding C fix: _safe_text 의 적용 범위를 footer 의 BOT_USER 로 한정.
    finding title/detail 에는 적용하지 않음 — "simsim-" 같은 흔한 표현이
    finding 본문에 포함 가능해 false-redaction 야기하기 때문.
    impersonation pattern 은 footer 전용 정밀 regex 로 좁힘.
    """
    if not s:
        return s
    if _IMPERSONATION_PATTERNS.search(s):
        return "(redacted: impersonation pattern detected)"
    return s


def _extract_block(content: str, start_marker: str, end_marker: str) -> str:
    """template file 에서 START/END marker 사이 block 추출.

    LOW-_extract_block: sys.exit 대신 ValueError raise — 호출자가 적절히 처리 가능.
    """
    m = re.search(
        rf"{re.escape(start_marker)}\n(.*?)\n{re.escape(end_marker)}",
        content,
        re.DOTALL,
    )
    if not m:
        raise ValueError(f"template 의 {start_marker} block 없음")
    return m.group(1)


def _subst_finding(
    tpl: str,
    n: int,
    emoji: str,
    sev: str,
    title: str,
    lang: str,
    location: str,
    code: str,
    detail: str,
) -> str:
    """per-finding placeholder 치환 (B023: loop variable binding 방어 — module-level)."""
    b = tpl
    b = b.replace("{{N}}", str(n))
    b = b.replace("{{EMOJI}}", emoji)
    b = b.replace("{{SEVERITY}}", sev)
    b = b.replace("{{TITLE}}", title)
    b = b.replace("{{LANG}}", lang)
    b = b.replace("{{LOCATION}}", location)
    # WARN-code-fence: findings.code 내 ``` escape — GitHub markdown code fence 깨짐 방지
    safe_code = code.replace("```", "\\`\\`\\`")
    b = b.replace("{{CODE}}", "\n   ".join(safe_code.split("\n")))
    b = b.replace("{{DETAIL}}", detail)
    # detail 빈 경우 blank-only 줄 제거
    if not detail:
        b = "\n".join(ln for ln in b.split("\n") if ln.strip() != "")
    # LOW-trailing-newline: detail 마지막 줄 뒤 trailing newline 정규화
    b = b.rstrip("\n")
    return b


def render_findings(json_str: str, template_file: str, role: str = "") -> str:
    """findings JSON 을 template file 의 FINDING_TEMPLATE block 기반으로 render.

    사용자 명시: template file 이 render 의 단일 source.
    3 branch 모두 template-driven (finding E):
      - FINDING_PLAIN_TEMPLATE block         — code + location 둘 다 없음
      - FINDING_LOCATION_ONLY_TEMPLATE block — location 만 있음
      - FINDING_TEMPLATE block               — code (+ location 선택)

    finding C: title/detail 에 _safe_text 미적용 — finding 본문은 plain pass-through.
               impersonation 방어는 render_template 의 BOT_USER (footer) 만 대상.

    role-specific body render 정책 (사용자 명시 2026-05-23):
      code-reviewer: CRITICAL / HIGH 만 body render. MED/WARN/LOW/INFO 모두 skip.
      architect / security-reviewer / test-engineer: CRITICAL/HIGH/MED/WARN 만 render.
                     LOW / INFO / PASS 모두 skip.
    verdict 산출 (expected_verdict) 에는 영향 X — 원본 findings 로 산출.
    """
    # role-specific body render severity set
    if role == "code-reviewer":
        body_sev = {"CRITICAL", "HIGH"}
    else:
        body_sev = {"CRITICAL", "HIGH", "MED", "WARN"}

    findings = json.loads(json_str)
    render_findings_list = [
        f for f in findings if (f.get("severity", "") or "").upper() in body_sev
    ]
    if not render_findings_list:
        return "_(no blocking findings)_"
    render_findings_list = sorted(
        render_findings_list,
        key=lambda f: SEV_ORDER.get((f.get("severity", "") or "").upper(), 9),
    )

    # template file 에서 3 branch block 추출 (finding E: 모두 template-driven)
    with open(template_file, encoding="utf-8") as fh:
        content = fh.read()
    finding_tpl = _extract_block(
        content, "<!-- FINDING_TEMPLATE_START -->", "<!-- FINDING_TEMPLATE_END -->"
    )
    plain_tpl = _extract_block(
        content,
        "<!-- FINDING_PLAIN_TEMPLATE_START -->",
        "<!-- FINDING_PLAIN_TEMPLATE_END -->",
    )
    location_only_tpl = _extract_block(
        content,
        "<!-- FINDING_LOCATION_ONLY_TEMPLATE_START -->",
        "<!-- FINDING_LOCATION_ONLY_TEMPLATE_END -->",
    )

    rendered = []
    for i, f in enumerate(render_findings_list, 1):
        sev = (f.get("severity", "") or "").upper()
        emoji = SEV_EMOJI.get(sev, "•")
        # finding C: title/detail 은 plain pass-through (impersonation 검사 제거)
        title = (f.get("title", "") or "(no title)").replace("\n", " ").strip()
        location = (f.get("location", "") or "").strip()
        code = (f.get("code", "") or "").strip()
        lang = (f.get("language", "") or "").strip()
        detail = (f.get("detail", "") or "").strip()

        if not code and not location:
            block = _subst_finding(plain_tpl, i, emoji, sev, title, lang, location, code, detail)
        elif not code:
            block = _subst_finding(
                location_only_tpl, i, emoji, sev, title, lang, location, code, detail
            )
        else:
            block = _subst_finding(finding_tpl, i, emoji, sev, title, lang, location, code, detail)
        rendered.append(block)
    return "\n\n".join(rendered)


def verdict_reason(json_str: str) -> str:
    findings = json.loads(json_str)
    c = collections.Counter(
        (f.get("severity", "") or "").upper() for f in findings if isinstance(f, dict)
    )
    # MED is canonical (architect INFO: MEDIUM alias removed)
    order = ["CRITICAL", "HIGH", "MED", "WARN", "LOW", "INFO", "PASS"]
    parts = [f"{s}={c[s]}" for s in order if c[s]]
    # report unknown severities so caller can see them
    unknown = {s for s in c if s not in SEV_ALLOWLIST}
    if unknown:
        parts.append(f"UNKNOWN={sum(c[s] for s in unknown)}({','.join(sorted(unknown))})")
    return "findings: " + (", ".join(parts) if parts else "none")


def severity_set(json_str: str) -> str:
    findings = json.loads(json_str)
    sev = sorted({(f.get("severity", "") or "").upper() for f in findings if isinstance(f, dict)})
    return str(sev)


def validate_findings(json_str: str) -> str:
    try:
        d = json.loads(json_str)
    except Exception as exc:
        return f"PARSE_ERROR:{exc}"
    if not isinstance(d, list):
        return f"NOT_ARRAY:{type(d).__name__}"
    return "OK"


_LANG_ALLOWLIST = frozenset(
    {
        "python",
        "bash",
        "javascript",
        "typescript",
        "go",
        "rust",
        "java",
        "yaml",
        "json",
        "markdown",
        "dockerfile",
        "make",
        "text",
        "",
    }
)


def validate_finding_format(json_str: str) -> None:
    """finding 의 length / format validate.

    위반 시 stderr 메시지 + sys.exit(1).
    exit message 는 sub-agent 가 읽고 retry 가능하도록 명확.

    규칙:
      severity   — 필수, SEV_ALLOWLIST 내 값만 허용 (finding A: unknown severity → reject)
      title      — 필수, ≤30 char, 공백 ≤2 (1-3 단어)
      detail     — optional, ≤200 char, ≤3 line
      location   — optional, "path:line" 또는 "path:line-line" 형식 (finding E: range 허용)
      code       — optional, multi-line OK
      language   — optional, code block fence lang hint (사용자 명시: _LANG_ALLOWLIST)
      confidence — optional, HIGH/MEDIUM/LOW (옵션 C 2026-05-23: CRITICAL/HIGH at HIGH
                   confidence 만 blocking). 생략 시 HIGH 로 간주. 미허용 값 → reject.
    """
    findings = json.loads(json_str)
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            print(f"finding {i}: dict 타입 필수 (got {type(f).__name__})", file=sys.stderr)
            sys.exit(1)

        severity = (f.get("severity", "") or "").upper()
        title = f.get("title", "") or ""
        detail = f.get("detail", "") or ""
        location = f.get("location", "") or ""

        # severity validate (finding A: allow-list check)
        if not severity:
            print(
                f"finding {i}: severity 필수 — 허용값: {sorted(SEV_ALLOWLIST)}",
                file=sys.stderr,
            )
            sys.exit(1)
        if severity not in SEV_ALLOWLIST:
            print(
                f"finding {i}: severity 오타/미허용값 {severity!r}"
                f" — 허용값: {sorted(SEV_ALLOWLIST)}",
                file=sys.stderr,
            )
            sys.exit(1)

        # title validate
        if not title:
            print(f"finding {i}: title 필수", file=sys.stderr)
            sys.exit(1)
        if len(title) > 30:
            print(
                f"finding {i}: title 30 char 초과 ({len(title)})"
                f" — 1-3 단어로 줄여라. 현재: {title!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        if title.count(" ") > 2:
            print(
                f"finding {i}: title 공백 ≤2 (1-3 단어) — 현재: {title!r}",
                file=sys.stderr,
            )
            sys.exit(1)

        # detail validate (optional)
        if detail:
            if len(detail) > 200:
                print(
                    f"finding {i}: detail 200 char 초과 ({len(detail)})"
                    f" — 요약 (한 줄 권고). 현재 head: {detail[:50]!r}",
                    file=sys.stderr,
                )
                sys.exit(1)
            if detail.count("\n") > 2:
                print(
                    f"finding {i}: detail 3 line 초과 — 요약. 현재: {detail!r}",
                    file=sys.stderr,
                )
                sys.exit(1)

        # location validate (optional) — "path:line" 또는 "path:line-line" 허용 (finding E)
        # finding O: Linux/Unix path 만 지원. Windows path (C:\path:42) 는 미지원 —
        #   colon 을 path 구분자로 사용하는 Windows drive letter 패턴은 `^[^:]+:\d+` 에서
        #   drive letter 의 첫 colon 이 line number 구분자로 오인됨.
        #   본 스크립트는 Linux/Unix 환경 전용이므로 Windows path 지원 불필요.
        if location and not re.match(r"^[^:]+:\d+(-\d+)?$", location):
            print(
                f'finding {i}: location 형식 "path:line" 또는 "path:line-line"'
                f" (Linux/Unix path 만 지원) — 현재: {location!r}",
                file=sys.stderr,
            )
            sys.exit(1)

        # location 명시 시 code 필수 (사용자 명시: 가독성 + agent 정직성 강제)
        code = (f.get("code", "") or "").strip()
        if location and not code:
            print(
                f"finding {i}: location 명시 시 code 필수 — actual 코드 발췌 (≥1 line) 의무. "
                f"현재 location={location!r}, code 비어있음.",
                file=sys.stderr,
            )
            sys.exit(1)

        # language validate (optional) — code block fence lang hint (사용자 명시)
        language = (f.get("language", "") or "").strip().lower()
        if language not in _LANG_ALLOWLIST:
            print(
                f"finding {i}: language 미허용값 {language!r} — 허용값: {sorted(_LANG_ALLOWLIST)}",
                file=sys.stderr,
            )
            sys.exit(1)

        # confidence validate (optional) — 옵션 C (2026-05-23):
        # CRITICAL/HIGH at HIGH confidence 만 blocking. 생략 시 HIGH 로 간주.
        # LOW-confidence CRITICAL/HIGH = informational.
        _CONFIDENCE_ALLOWLIST = frozenset({"HIGH", "MEDIUM", "LOW", ""})
        confidence = (f.get("confidence", "") or "").strip().upper()
        if confidence not in _CONFIDENCE_ALLOWLIST:
            print(
                f"finding {i}: confidence 미허용값 {confidence!r}"
                f" — 허용값: HIGH / MEDIUM / LOW (생략 시 HIGH)",
                file=sys.stderr,
            )
            sys.exit(1)


def render_template(template_file: str) -> str:
    """env var 기반 template placeholder 치환.

    strip: spec comment block (<!-- finding format template ... --> 부터
    <!-- FINDING_TEMPLATE_END --> 까지) 을 review body 에서 제거.
    template 파일 내 single source 로 유지하되 출력에는 노출 안 함.
    """
    import os

    with open(template_file, encoding="utf-8") as f:
        tpl = f.read()

    # spec comment block + 모든 FINDING_*_TEMPLATE block 제거
    # (사용자 명시: block 은 spec single source 유지 but review body 에 안 보이게)
    # WARN-strip-coupling: 3 개 별도 strip regex → 단일 helper 로 통합
    def _strip_block(text: str, start: str, end: str) -> str:
        return re.sub(
            rf"{re.escape(start)}[\s\S]*?{re.escape(end)}\n?",
            "",
            text,
        )

    # finding format template spec comment (open-ended start marker) 포함 FINDING_TEMPLATE block 제거  # noqa: E501
    tpl = re.sub(
        r"<!-- finding format template[\s\S]*?<!-- FINDING_TEMPLATE_END -->\n?",
        "",
        tpl,
    )
    # finding E: plain / location-only template block 도 review body 에서 제거
    tpl = _strip_block(
        tpl, "<!-- FINDING_PLAIN_TEMPLATE_START -->", "<!-- FINDING_PLAIN_TEMPLATE_END -->"
    )
    tpl = _strip_block(
        tpl,
        "<!-- FINDING_LOCATION_ONLY_TEMPLATE_START -->",
        "<!-- FINDING_LOCATION_ONLY_TEMPLATE_END -->",
    )

    subs = {
        "{{VERDICT_BADGE}}": os.environ.get("_PR_VERDICT_BADGE", ""),
        # {{LAST_REVIEW_SHA}} / {{LAST_REVIEW_TIME}} 제거 — template header label 삭제 후 미사용
        "{{COMMIT_LIST}}": os.environ.get("_PR_COMMIT_LIST", ""),
        "{{FINDINGS}}": os.environ.get("_PR_FINDINGS", ""),
        "{{VERDICT_LINE}}": os.environ.get("_PR_VERDICT_LINE", ""),
        "{{VERDICT_REASON}}": os.environ.get("_PR_VERDICT_REASON", ""),
        # finding C: BOT_USER 는 footer impersonation 방어 대상 (_safe_bot_user 적용)
        "{{BOT_USER}}": _safe_bot_user(os.environ.get("_PR_BOT_USER", "")),
        "{{POST_SCRIPT_SHA}}": os.environ.get("_PR_SCRIPT_SHA", ""),
    }
    for k, v in subs.items():
        tpl = tpl.replace(k, v)
    return tpl


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    try:
        if cmd == "extract_field":
            print(extract_field(sys.argv[2], sys.argv[3]))
        elif cmd == "findings_len":
            print(findings_len(sys.argv[2]))
        elif cmd == "expected_verdict":
            # optional 3rd arg: role (e.g. "code-reviewer")
            _role = sys.argv[3] if len(sys.argv) > 3 else ""
            print(expected_verdict(sys.argv[2], _role))
        elif cmd == "render_findings":
            if len(sys.argv) < 4:
                print("render_findings requires <json> <template_file> [role]", file=sys.stderr)
                sys.exit(1)
            # optional 4th arg: role (e.g. "code-reviewer")
            _role = sys.argv[4] if len(sys.argv) > 4 else ""
            sys.stdout.write(render_findings(sys.argv[2], sys.argv[3], _role))
        elif cmd == "verdict_reason":
            print(verdict_reason(sys.argv[2]))
        elif cmd == "severity_set":
            print(severity_set(sys.argv[2]))
        elif cmd == "policy_summary":
            print(policy_summary(sys.argv[2]))
        elif cmd == "verdict_line":
            print(verdict_line(sys.argv[2], sys.argv[3]))
        elif cmd == "validate_findings":
            print(validate_findings(sys.argv[2]))
        elif cmd == "extract_review_node_ids":
            # stdin 으로 reviews JSON 수신, argv[2] = user
            reviews_input = sys.stdin.read()
            print(extract_review_node_ids(reviews_input, sys.argv[2]))
        elif cmd == "validate_finding_format":
            validate_finding_format(sys.argv[2])
        elif cmd == "render_template":
            sys.stdout.write(render_template(sys.argv[2]))
        else:
            print(f"unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
