"""Agent loop — LangGraph state graph (tool-calling round-trip).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.2

흐름 (LangGraph state graph — 6 노드 완성, PR #23):
  - entry: `intake` 노드 — raw log 텍스트 파싱, system 컨텍스트 prepend.
  - `llm_call` 노드 — tools schema 첨부하여 gateway.complete 호출,
    응답 assistant message 를 state.messages 에 추가.
  - conditional edge `_route_after_llm`:
      - assistant_msg.tool_calls 가 있고 iter ≤ max_iters → `execute_tools`
      - 아니면 (final answer 또는 max_iters 도달) → `crystallize_report`
  - `execute_tools` 노드 — tool_calls 를 실행 (asyncio.to_thread), 결과를
    tool role message 로 state.messages 에 추가 → 다시 `llm_call` 로 (loop).
  - `crystallize_report` 노드 — last assistant message 를 구조화 Report 로 변환.
  - `finalize` 노드 — cleanup/metric/log 발행 후 END. MVP no-op.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict, cast

import litellm
import litellm.exceptions
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ValidationError

from macro_logbot.gateway import (
    ChatCompletionResponse,
    LLMGateway,
    Message,
)
from macro_logbot.intake.parser import parse_macro_log
from macro_logbot.knowledge_base.store import Location
from macro_logbot.tools.registry import execute_tool, get_openai_tools_schema

logger = logging.getLogger(__name__)

MAX_ITERS_DEFAULT = 20  # spec §5.2 default

# context 한계 — env override 가능 (default 16384, Gemma 3 12B 기준).
_CONTEXT_LIMIT_ENV = "MACRO_LOGBOT_MODEL_CONTEXT_LIMIT"
_CONTEXT_LIMIT_DEFAULT = 16384
_CONTEXT_HIGH_WATERMARK = 0.80  # 80% 초과 시 truncate 시작
_CONTEXT_TARGET = 0.70  # truncate 후 목표 — limit 의 70% 이하


def _get_context_limit() -> int:
    """env 에서 context limit 읽기 (int 변환 실패 또는 ≤ 0 이면 default 반환)."""
    raw = os.environ.get(_CONTEXT_LIMIT_ENV, "")
    try:
        value = int(raw)
    except ValueError:
        return _CONTEXT_LIMIT_DEFAULT
    if value <= 0:
        logger.warning(
            "%s env value %r is not positive; using default %d",
            _CONTEXT_LIMIT_ENV,
            raw,
            _CONTEXT_LIMIT_DEFAULT,
        )
        return _CONTEXT_LIMIT_DEFAULT
    return value


def _build_tool_call_groups(messages: list[Message]) -> list[list[int]]:
    """messages 에서 tool-call group 을 추출한다.

    각 group = [assistant(tool_calls) 인덱스, *대응하는 tool 메시지 인덱스들].
    assistant message 의 tool_calls 리스트에 있는 모든 tool_call_id 에 매칭되는
    tool role 메시지들을 같은 group 으로 묶는다.

    orphan tool 메시지 (대응 assistant 없음) 는 포함하지 않는다 — 이미 깨진
    상태이므로 건드리지 않고 안전하게 보존한다.
    """
    groups: list[list[int]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.role == "assistant" and m.tool_calls:
            # 이 assistant message 의 모든 tool_call_id 수집.
            expected_ids: set[str] = {tc.id for tc in m.tool_calls if tc.id is not None}
            group: list[int] = [i]
            j = i + 1
            # 바로 뒤에 오는 tool 메시지들 중 matching ID 를 group 에 추가.
            while j < len(messages) and messages[j].role == "tool":
                if messages[j].tool_call_id in expected_ids:
                    group.append(j)
                j += 1
            groups.append(group)
            i = j  # group 끝 이후부터 재개
        else:
            i += 1
    return groups


def _truncate_messages(
    messages: list[Message],
    model: str | None,
    limit: int,
) -> list[Message]:
    """누적 messages 가 limit × 80% 초과 시 가장 오래된 tool-call group 부터 제거.

    보존 우선순위:
      1. role=system  (모든 system 메시지)
      2. role=user    (최신 user message 포함 전체)
      3. 최근 N=2 group (assistant(tool_calls) + 대응 tool 메시지 묶음)
    나머지 tool-call group 을 오래된 순서로 group 단위로 제거해
    token count ≤ limit × 70% 가 될 때까지 반복.

    group 단위 제거로 assistant(tool_calls) ↔ tool(tool_call_id) 1:1 짝을
    유지하여 LiteLLM/OpenAI provider 400 (orphan tool_call_id) 를 방지한다.

    WARN-2 (token_counter O(n²)): group 제거 전 token 을 1회 계산 후 dict 캐시.
    group 제거 후에만 재계산하여 호출 횟수를 O(group_count) 로 줄인다.

    litellm.token_counter 가 실패하면 truncate 를 생략하고 원본을 반환한다.
    """
    # BLOCK-2: limit ≤ 0 이면 truncate 불가 — 원본 그대로 반환.
    if limit <= 0:
        return messages

    high = int(limit * _CONTEXT_HIGH_WATERMARK)
    target = int(limit * _CONTEXT_TARGET)
    _model = model or "gpt-4o"

    # WARN-2: 초기 token count 1회 계산.
    try:
        token_count_fn = litellm.token_counter
        before = token_count_fn(model=_model, messages=messages)
    except Exception:
        return messages

    if before <= high:
        return messages

    # tool-call group 수집 — group 단위로 oldest-first pop.
    groups = _build_tool_call_groups(messages)

    # 최근 2 group 보존 (인덱스 단위가 아닌 group 단위).
    removable_groups = groups[:-2] if len(groups) > 2 else []

    if not removable_groups:
        return messages

    working = list(messages)
    current_tokens = before
    total_removed = 0
    # offset: 이미 제거된 메시지 수 — 원본 인덱스를 working 인덱스로 변환할 때 사용.
    offset = 0

    for group in removable_groups:
        # group 내 인덱스를 오름차순 정렬 후 앞에서부터 제거.
        # 제거할 때마다 offset 을 1씩 늘려 이후 인덱스를 보정한다.
        for orig_idx in sorted(group):
            real_idx = orig_idx - offset
            if 0 <= real_idx < len(working):
                working.pop(real_idx)
                offset += 1
                total_removed += 1
        # WARN-2: group 제거 후 token 재계산 (per-message 아닌 per-group).
        try:
            current_tokens = token_count_fn(model=_model, messages=working)
        except Exception:
            break
        if current_tokens <= target:
            break

    try:
        after_final = token_count_fn(model=_model, messages=working)
    except Exception:
        after_final = -1

    logger.info(
        "context truncate: removed %d messages (%d groups), "
        "before=%d tokens, after=%d tokens, limit=%d",
        total_removed,
        len(removable_groups),
        before,
        after_final,
        limit,
    )
    return working


# spec §5.5 Location — KB store 정의 (file/function/line) 재사용 (architect WARN-1 충돌 회피).
_LOCATION_RE = re.compile(r"([\w./-]+\.py):(\d+)")

# traceback fallback — stderr 에서 마지막 프레임 추출.
_TRACEBACK_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')

# structured output 추출 prompt — JSON only, 다른 텍스트 없이.
_CRYSTALLIZE_SYSTEM_PROMPT = """\
당신은 에러 분석 결과를 JSON 으로 정확히 구조화하는 어시스턴트입니다.
다음 JSON 형식으로만 출력하세요. 다른 텍스트 없이 JSON 만.

{
  "root_cause": "<error class + 원인 함수/변수 — 한 문장>",
  "location": {"file": "<basename.py>", "function": "<func_name>", "line": <int or null>},
  "fix_hint": "<구체적 코드 수정>",
  "confidence": <0.0~1.0>,
  "reasoning_summary": "<핵심 추론 요약>"
}

location 이 불명확하면 null 을 사용하세요: "location": null
"""


class Report(BaseModel):
    """crystallize_report 노드 출력 — 구조화 분석 결과.

    MVP 단순화 (task-MVP-001-y 로 개선 예정):
      - root_cause / reasoning_summary: last assistant message 본문 그대로 복사.
      - location: 첫 *.py:N 매칭, 없으면 None.
      - confidence: 0.5 고정 placeholder.
      - fix_hint: last assistant message 본문 그대로 (LLM 추가 호출 생략).
    LLM 추가 호출로 정확 JSON 추출은 task-MVP-001-y.
    """

    root_cause: str
    location: Location | None = None
    fix_hint: str
    confidence: float = 0.5
    reasoning_summary: str


@dataclass
class AgentRunResult:
    """Agent loop 결과 — 마지막 응답 + 사용된 iter 수 + 구조화 리포트."""

    response: ChatCompletionResponse
    iterations: int
    messages: list[Message]
    report: Report | None = field(default=None)


class AgentState(TypedDict):
    """LangGraph state — messages 누적 + iteration 카운터 + 호출 시점 lock-in.

    `_gateway` / `_model` / `_generation_kwargs` 는 노드 함수에서 closure 대신
    state 를 통해 전달 (LangGraph 표준). MVP 상 in-memory 만 가정 — checkpoint
    serialization 은 follow-up task-MVP-001-x.

    `report` 는 crystallize_report 노드가 채움 (None → Report).

    `session_id` — endpoint 가 채워서 전달 (spec §5.2 line 134). agent loop /
    followup 노드가 향후 활용. None 이면 단독 호출 (비-session 컨텍스트).

    `event_id` — Log Event 와의 1:N 관계 키 (spec §5.2 line 135, `event` 필드의
    MVP 단순화 표기). None 이면 미연결 (task-MVP-005 intake 한국어 후 통합 예정).
    """

    messages: list[Message]
    iteration: int
    max_iters: int
    last_response: ChatCompletionResponse | None
    report: Report | None
    session_id: str | None
    event_id: str | None
    _model: str | None
    _generation_kwargs: dict[str, object]
    _gateway: LLMGateway


async def _intake_node(state: AgentState) -> AgentState:
    """마지막 user message 를 파싱해 system 컨텍스트 prepend (entry point).

    - `state.messages[-1]` 이 user role 이면 `parse_macro_log` 로 파싱.
    - 파싱 결과를 system message 로 messages 앞에 추가.
    - 빈 로그(빈 문자열 / user message 없음) 이면 no-op.
    """
    msgs = state["messages"]
    # last user message 추출.
    last_user = next(
        (m for m in reversed(msgs) if m.role == "user" and m.content),
        None,
    )
    if last_user is None or not last_user.content:
        return state

    record = parse_macro_log(last_user.content)
    # 파싱 성공 여부와 무관하게 system 힌트 생성 (실패 시 level/ts=None).
    ts_str = record.timestamp.isoformat() if record.timestamp else "unknown"
    level_str = record.level or "unknown"
    hint = f"[INTAKE] level={level_str}, time={ts_str}, hint={record.message[:120]}"
    system_msg = Message(role="system", content=hint)

    # 재진입 방어 — 어느 위치든 [INTAKE] system 메시지가 있으면 중복 추가 X
    # (app.py 가 ANALYZE_SYSTEM_PROMPT 를 0번째에 두면 startswith 가 False 가 되어
    # 가드 우회되던 버그 fix — PR #23 code-r WARN-2).
    already_has_intake = any(
        m.role == "system" and m.content and m.content.startswith("[INTAKE]") for m in msgs
    )
    if already_has_intake:
        return state

    # 기존 system 메시지 뒤에 intake 힌트 삽입 (ANALYZE_PROMPT 같은 페르소나 system 보존).
    insert_idx = 0
    for i, m in enumerate(msgs):
        if m.role == "system":
            insert_idx = i + 1
        else:
            break
    new_msgs = [*msgs[:insert_idx], system_msg, *msgs[insert_idx:]]
    return {**state, "messages": new_msgs}


async def _llm_call_node(state: AgentState) -> AgentState:
    """gateway.complete 호출 → assistant message 를 state.messages 에 추가."""
    tools = get_openai_tools_schema()
    msgs = _truncate_messages(
        state["messages"],
        model=state["_model"],
        limit=_get_context_limit(),
    )
    response = await state["_gateway"].complete(
        msgs,
        model=state["_model"],
        tools=tools,
        **state["_generation_kwargs"],
    )
    if not response.choices:
        # provider edge case — choices 가 비어도 마지막 응답으로 기록하고 종료.
        return {
            **state,
            "last_response": response,
            "iteration": state["iteration"] + 1,
        }
    assistant_msg = response.choices[0].message
    return {
        **state,
        "messages": [*state["messages"], assistant_msg],
        "last_response": response,
        "iteration": state["iteration"] + 1,
    }


async def _execute_tools_node(state: AgentState) -> AgentState:
    """마지막 assistant message 의 tool_calls 실행 → tool messages 추가."""
    assistant_msg = state["messages"][-1]
    if not assistant_msg.tool_calls:
        return state
    tool_messages: list[Message] = []
    for tool_call in assistant_msg.tool_calls:
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError as exc:
            result: dict[str, object] = {"error": f"invalid JSON arguments: {exc}"}
        else:
            result = await asyncio.to_thread(execute_tool, tool_call.function.name, args)
        tool_messages.append(
            Message(
                role="tool",
                tool_call_id=tool_call.id,
                name=tool_call.function.name,
                content=json.dumps(result, ensure_ascii=False),
            )
        )
    return {**state, "messages": [*state["messages"], *tool_messages]}


def _location_from_traceback(stderr: str) -> Location | None:
    """stderr traceback 의 마지막 프레임에서 Location 추출.

    LLM 답변에 location 이 없을 때 user message (stderr) 에서 fallback.
    """
    matches = list(_TRACEBACK_FRAME_RE.finditer(stderr))
    if not matches:
        return None
    m = matches[-1]
    try:
        return Location(
            file=Path(m.group(1)).name,
            function=m.group(3),
            line=int(m.group(2)),
        )
    except ValidationError:
        return None


def _parse_structured_json(raw: str) -> dict[str, object] | None:
    """LLM raw 응답에서 JSON 블록을 추출하고 파싱. 실패 시 None."""
    # 마크다운 코드펜스 벗기기 (```json ... ```)
    stripped = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
        return None
    except json.JSONDecodeError:
        return None


async def _crystallize_report_node(state: AgentState) -> AgentState:
    """last assistant message → 구조화 Report 추출 (graph 종료 직전).

    추가 LLM 호출로 structured JSON 추출 (task-AGENT-011):
      1. system prompt (JSON schema 강제) + last assistant content 로 LLM 호출.
      2. 파싱 실패 시 1회 재시도.
      3. location 이 None 이면 user message (stderr) traceback fallback.
      4. 최종 실패 시 last assistant content 를 root_cause 에 그대로 복사 (MVP fallback).
    """
    # last assistant message 본문 추출.
    last_assistant_content = ""
    for m in reversed(state["messages"]):
        if m.role == "assistant" and m.content:
            last_assistant_content = m.content
            break

    # user message (stderr) 추출 — traceback fallback 용.
    user_content = ""
    for m in state["messages"]:
        if m.role == "user" and m.content:
            user_content = m.content
            break

    # structured JSON 추출 LLM 호출 (최대 2회).
    parsed: dict[str, object] | None = None
    _response_format_supported = True  # OSS 모델 미지원 시 False 로 전환.
    crystallize_messages = [
        Message(role="system", content=_CRYSTALLIZE_SYSTEM_PROMPT),
        Message(role="user", content=last_assistant_content or "(분석 결과 없음)"),
    ]
    for _attempt in range(2):
        msgs = list(crystallize_messages)
        if _attempt > 0:
            # corrective prompt — 이전 시도가 JSON 형식 아닌 경우.
            msgs.append(
                Message(
                    role="user",
                    content="이전 답안이 JSON 형식 아닙니다. JSON 만 답하세요. 추가 설명 금지.",
                )
            )
        extra_kwargs: dict[str, object] = dict(state["_generation_kwargs"])
        if _response_format_supported:
            extra_kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await state["_gateway"].complete(
                msgs,
                model=state["_model"],
                **extra_kwargs,
            )
        except (
            litellm.exceptions.UnsupportedParamsError,
            litellm.exceptions.BadRequestError,
        ) as exc:
            if "response_format" in str(exc).lower():
                # OSS 모델 미지원 — prompt-only fallback.
                logger.info(
                    "response_format unsupported for crystallize, "
                    "using prompt-only JSON instruction"
                )
                _response_format_supported = False
                extra_kwargs.pop("response_format", None)
                try:
                    resp = await state["_gateway"].complete(
                        msgs,
                        model=state["_model"],
                        **extra_kwargs,
                    )
                except Exception as inner_exc:  # noqa: BLE001
                    # crystallize 는 best-effort — LLM 호출 실패 시 MVP fallback.
                    logger.warning("crystallize LLM call failed (inner): %s", inner_exc)
                    break
            else:
                raise
        except Exception as exc:  # noqa: BLE001
            # crystallize 는 best-effort — rate limit / timeout / attr 오류 시 MVP fallback.
            logger.warning("crystallize LLM call failed: %s", exc)
            break
        else:
            if resp.choices:
                raw = resp.choices[0].message.content or ""
                parsed = _parse_structured_json(raw)
                if parsed is not None:
                    break

    # parsed 결과에서 필드 추출, 실패 시 MVP fallback.
    if parsed is not None:

        def _extract_str(val: object) -> str:
            """None 또는 공백 전용이면 last_assistant_content 로 fallback."""
            s = str(val) if val is not None else ""
            return s if s.strip() else last_assistant_content

        root_cause = _extract_str(parsed.get("root_cause"))
        fix_hint = _extract_str(parsed.get("fix_hint"))
        reasoning_summary = _extract_str(parsed.get("reasoning_summary"))
        raw_confidence = parsed.get("confidence")
        try:
            confidence = float(raw_confidence) if raw_confidence is not None else 0.5  # type: ignore[arg-type]
            confidence = max(0.0, min(1.0, confidence))
        except TypeError, ValueError:
            confidence = 0.5

        # location 추출.
        location: Location | None = None
        loc_data = parsed.get("location")
        if isinstance(loc_data, dict):
            try:
                raw_line = loc_data.get("line")
                if raw_line is not None:
                    location = Location(
                        file=str(loc_data.get("file") or ""),
                        function=str(loc_data.get("function") or ""),
                        line=int(raw_line),
                    )
            except ValidationError, TypeError, ValueError:
                location = None
    else:
        # LLM 호출/파싱 완전 실패 → MVP fallback.
        root_cause = last_assistant_content
        fix_hint = last_assistant_content
        reasoning_summary = last_assistant_content
        confidence = 0.5
        location = None
        # regex fallback (이전 MVP 동작 보존).
        loc_match = _LOCATION_RE.search(last_assistant_content)
        if loc_match:
            try:
                location = Location(file=loc_match.group(1), line=int(loc_match.group(2)))
            except ValidationError:
                location = None

    # traceback fallback — location 여전히 None 이고 user message 에 stderr 있으면.
    if location is None and user_content:
        location = _location_from_traceback(user_content)

    report = Report(
        root_cause=root_cause,
        location=location,
        fix_hint=fix_hint,
        confidence=confidence,
        reasoning_summary=reasoning_summary,
    )
    return {**state, "report": report}


async def _finalize_node(state: AgentState) -> AgentState:
    """cleanup / metric / log 발행 후 END. MVP no-op — state 그대로 반환."""
    return state


def _route_after_llm(state: AgentState) -> str:
    """tool_calls 가 있고 iter ≤ max_iters 이면 execute_tools, 아니면 crystallize_report."""
    if state["iteration"] >= state["max_iters"]:
        return "crystallize_report"
    if not state["messages"]:
        return "crystallize_report"
    last = state["messages"][-1]
    if last.role == "assistant" and last.tool_calls:
        return "execute_tools"
    return "crystallize_report"


def _build_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """LangGraph StateGraph 컴파일 — module-level 1회만 호출 (비용 절약).

    흐름:
      intake → llm_call → conditional:
        - tool_calls? → execute_tools → llm_call (loop)
        - no  → crystallize_report → finalize → END
    """
    g = StateGraph(AgentState)
    g.add_node("intake", _intake_node)
    g.add_node("llm_call", _llm_call_node)
    g.add_node("execute_tools", _execute_tools_node)
    g.add_node("crystallize_report", _crystallize_report_node)
    g.add_node("finalize", _finalize_node)
    g.set_entry_point("intake")
    g.add_edge("intake", "llm_call")
    g.add_conditional_edges(
        "llm_call",
        _route_after_llm,
        {"execute_tools": "execute_tools", "crystallize_report": "crystallize_report"},
    )
    g.add_edge("execute_tools", "llm_call")
    g.add_edge("crystallize_report", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


_GRAPH = _build_graph()


async def run_agent(
    messages: list[Message],
    gateway: LLMGateway,
    max_iters: int = MAX_ITERS_DEFAULT,
    model: str | None = None,
    session_id: str | None = None,
    event_id: str | None = None,
    **generation_kwargs: object,
) -> AgentRunResult:
    """Tool-calling agent loop 실행 (LangGraph state graph).

    입력 `messages` 는 in-place 변경되지 않는다 — 호출 측이 원본 보존을
    보장받도록 새 리스트로 시작한다.

    generation_kwargs 는 LLM 호출 시 forward (temperature, max_tokens,
    tool_choice 등 OpenAI 호환 파라미터).

    session_id — endpoint 가 채워서 전달 (spec §5.2). None 이면 단독 호출.
    event_id   — Log Event 와의 1:N 관계 키 (MVP 미사용, task-MVP-005 후 통합).
    """
    initial_state: AgentState = {
        "messages": list(messages),
        "iteration": 0,
        "max_iters": max_iters,
        "last_response": None,
        "report": None,
        "session_id": session_id,
        "event_id": event_id,
        "_model": model,
        "_generation_kwargs": dict(generation_kwargs),
        "_gateway": gateway,
    }
    final_state = cast(AgentState, await _GRAPH.ainvoke(initial_state))
    last_response = final_state["last_response"]
    assert last_response is not None  # llm_call 노드가 최소 1회 실행됨
    return AgentRunResult(
        response=last_response,
        iterations=min(final_state["iteration"], max_iters),
        messages=final_state["messages"],
        report=final_state.get("report"),
    )
