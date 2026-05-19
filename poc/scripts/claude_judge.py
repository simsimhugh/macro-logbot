"""Claude judge — 1-B/2-A/2-B 채점 함수.

spec ref: docs/design/02-설계문서.md §10.1 / docs/process/04-PoC-운영가이드.md §6.1
rubric: spec §10.5~§10.7 (설계문서 §10.1 채점 방식)

각 함수:
  - judge_root_cause      → 1-B 의미 매칭
  - judge_tool_appropriateness → 2-A 도구 적절성
  - judge_fix_direction   → 2-B 수정 방향

응답 schema: {"score": float, "reasoning": str}
  score 0.0 / 0.5 / 1.0 (연속 스케일 아님 — rubric 기준)
"""

from __future__ import annotations

import json
from typing import Any

import litellm

# JSON 강제 system prompt 공통 접두어.
_JSON_SYSTEM_PREFIX = (
    "You are a strict evaluator. "
    "Respond ONLY with a valid JSON object — no markdown fences, no extra text. "
    'Schema: {"score": <float>, "reasoning": <string>}'
)

# LiteLLM 호출 공통 kwargs.
_COMPLETION_KWARGS: dict[str, Any] = {
    "temperature": 0,
    "max_tokens": 256,
}


def _call_judge(system: str, user: str, model: str) -> dict[str, Any]:
    """LiteLLM 으로 judge 호출. JSON parse 실패 시 score=0.0 + error reasoning 반환."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        resp = litellm.completion(model=model, messages=messages, **_COMPLETION_KWARGS)
        raw: str = resp.choices[0].message.content or ""
        parsed: dict[str, Any] = json.loads(raw.strip())
        score = float(parsed.get("score", 0.0))
        reasoning = str(parsed.get("reasoning", ""))
        return {"score": score, "reasoning": reasoning}
    except json.JSONDecodeError as exc:
        return {"score": 0.0, "reasoning": f"JSON parse error: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "reasoning": f"judge call error: {type(exc).__name__}: {exc}"}


def judge_root_cause(ground_truth: str, response: str, model: str) -> dict[str, Any]:
    """1-B 의미 매칭 — root_cause 의미 비교.

    Rubric (spec §10.1 / 04-PoC-운영가이드 §6.1):
      score 1.0 — 원인 분석이 ground truth 와 같은 개념·위치·메커니즘을 정확히 지적
      score 0.5 — 부분 일치 (핵심 keyword/concept 일부 언급, 다른 부분 누락 또는 부정확)
      score 0.0 — 전혀 다른 원인 또는 분석 없음

    Args:
        ground_truth: error_catalog 의 ground_truth.root_cause 문자열.
        response:     에이전트가 반환한 분석 텍스트 (analysis 필드 또는 report.root_cause).
        model:        LiteLLM 모델 식별자 (예: "claude-haiku-4-5").

    Returns:
        {"score": float, "reasoning": str}
    """
    system = (
        f"{_JSON_SYSTEM_PREFIX}\n\n"
        "Task: Evaluate if the agent's root cause analysis semantically matches the ground truth.\n"
        "Scoring rubric:\n"
        "  score 1.0 — Correct: same concept, mechanism, and location as ground truth\n"
        "  score 0.5 — Partial: key concept partially mentioned but incomplete or slightly off\n"
        "  score 0.0 — Wrong: different cause entirely, or no analysis provided\n"
        "Note: exact wording is NOT required — semantic equivalence is what matters."
    )
    user = (
        f"Ground truth root cause:\n{ground_truth}\n\n"
        f"Agent analysis:\n{response}\n\n"
        "Rate the semantic match. Respond with JSON only."
    )
    return _call_judge(system, user, model)


def judge_tool_appropriateness(
    expected_tools: list[str],
    actual_tool_calls: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    """2-A 도구 적절성 — 예상 도구 호출과 실제 도구 호출의 의미적 일치.

    Rubric (spec §10.1 / 04-PoC-운영가이드 §6.1):
      score 1.0 — 모든 expected_tools 에 해당하는 도구가 호출됨
                  (예: read_file 대신 grep_codebase 사용도 합리적이면 인정)
      score 0.5 — 일부만 호출 (partial credit)
      score 0.0 — 관련 도구 미호출 또는 전혀 다른 도구만 사용

    Args:
        expected_tools:   error_catalog 의 ground_truth.expected_tool_calls 리스트.
        actual_tool_calls: 에이전트 실제 tool_calls (각 dict 에 "tool" 또는 "name" 키 포함).
        model:            LiteLLM 모델 식별자.

    Returns:
        {"score": float, "reasoning": str}
    """
    actual_names = [
        str(tc.get("tool") or tc.get("name") or tc.get("function", {}).get("name", ""))
        for tc in actual_tool_calls
    ]
    system = (
        f"{_JSON_SYSTEM_PREFIX}\n\n"
        "Task: Evaluate if the agent called appropriate tools to diagnose the error.\n"
        "Scoring rubric:\n"
        "  score 1.0 — All expected tools (or semantically equivalent alternatives) were called\n"
        "  score 0.5 — Some expected tools called but others missing\n"
        "  score 0.0 — No relevant tools called or only irrelevant tools used\n"
        "Note: semantic equivalence counts "
        "(e.g. grep_codebase instead of read_file is reasonable if it finds the same info)."
    )
    user = (
        f"Expected tool calls: {json.dumps(expected_tools)}\n"
        f"Actual tool calls made: {json.dumps(actual_names)}\n\n"
        "Rate the tool appropriateness. Respond with JSON only."
    )
    return _call_judge(system, user, model)


def judge_fix_direction(
    ground_truth_fix: str,
    response_fix: str,
    model: str,
) -> dict[str, Any]:
    """2-B 수정 방향 — fix_hint 가 ground_truth fix 와 같은 위치/방법을 가리키는지.

    Rubric (spec §10.1 / 04-PoC-운영가이드 §6.1):
      score 1.0 — 같은 위치(함수/라인)와 방법(guard/init/type cast 등)을 정확히 제안
      score 0.5 — 부분 일치 (위치 또는 방법 중 하나만 맞음)
      score 0.0 — 다른 위치나 방법 제안 또는 수정 방향 없음

    Args:
        ground_truth_fix: error_catalog 의 ground_truth.fix_hint 문자열.
        response_fix:     에이전트가 제시한 수정 방향 텍스트.
        model:            LiteLLM 모델 식별자.

    Returns:
        {"score": float, "reasoning": str}
    """
    system = (
        f"{_JSON_SYSTEM_PREFIX}\n\n"
        "Task: Evaluate if the agent's fix suggestion matches the ground truth fix direction.\n"
        "Scoring rubric:\n"
        "  score 1.0 — Correct location (function/line) AND correct fix method\n"
        "  score 0.5 — Partial: correct location but wrong method,"
        " or right idea but wrong location\n"
        "  score 0.0 — Wrong location and wrong method, or no fix suggested\n"
        "Note: exact wording is NOT required — semantic equivalence is what matters."
    )
    user = (
        f"Ground truth fix hint:\n{ground_truth_fix}\n\n"
        f"Agent fix suggestion:\n{response_fix}\n\n"
        "Rate the fix direction match. Respond with JSON only."
    )
    return _call_judge(system, user, model)
