<!-- finding format template — render_findings 가 본 block 의 형식 따라 generate -->
<!-- placeholders (per-finding):
  {{N}} — 1-based index
  {{EMOJI}} — severity emoji
  {{SEVERITY}} — 대문자 severity
  {{TITLE}} — 1-3 단어
  {{LANG}} — code language hint (optional, 빈 string 가능)
  {{LOCATION}} — relative path:line (optional)
  {{CODE}} — 문제 코드 발췌 (optional)
  {{DETAIL}} — 짧은 요약 (optional, ≤3 line, ≤200 char)
-->
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
