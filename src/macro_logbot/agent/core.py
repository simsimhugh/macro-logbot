"""Agent loop — LangGraph state graph (tool-calling round-trip).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.2

흐름 (LangGraph state graph):
  - entry: `llm_call` 노드 — tools schema 첨부하여 gateway.complete 호출,
    응답 assistant message 를 state.messages 에 추가.
  - conditional edge `_route_after_llm`:
      - assistant_msg.tool_calls 가 있고 iter ≤ max_iters → `execute_tools`
      - 아니면 (final answer 또는 max_iters 도달) → END
  - `execute_tools` 노드 — tool_calls 를 실행 (asyncio.to_thread), 결과를
    tool role message 로 state.messages 에 추가 → 다시 `llm_call` 로 (loop).

본 PR 은 spec §5.2 6 노드 중 핵심 3 (`llm_call` / `route` / `execute_tools`)
만 구현 — 현재 동작 그대로 LangGraph 로 표현. intake / crystallize_report /
followup 은 호출 측 책임 또는 후속 task-MVP-001-x.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TypedDict, cast

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from macro_logbot.gateway import (
    ChatCompletionResponse,
    LLMGateway,
    Message,
)
from macro_logbot.tools.registry import execute_tool, get_openai_tools_schema

MAX_ITERS_DEFAULT = 20  # spec §5.2 default


@dataclass
class AgentRunResult:
    """Agent loop 결과 — 마지막 응답 + 사용된 iter 수."""

    response: ChatCompletionResponse
    iterations: int
    messages: list[Message]


class AgentState(TypedDict):
    """LangGraph state — messages 누적 + iteration 카운터 + 호출 시점 lock-in.

    `_gateway` / `_model` / `_generation_kwargs` 는 노드 함수에서 closure 대신
    state 를 통해 전달 (LangGraph 표준). MVP 상 in-memory 만 가정 — checkpoint
    serialization 은 follow-up task-MVP-001-x.
    """

    messages: list[Message]
    iteration: int
    max_iters: int
    last_response: ChatCompletionResponse | None
    _model: str | None
    _generation_kwargs: dict[str, object]
    _gateway: LLMGateway


async def _llm_call_node(state: AgentState) -> AgentState:
    """gateway.complete 호출 → assistant message 를 state.messages 에 추가."""
    tools = get_openai_tools_schema()
    response = await state["_gateway"].complete(
        state["messages"],
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
            result: dict[str, object] = {
                "error": f"invalid JSON arguments: {exc}"
            }
        else:
            result = await asyncio.to_thread(
                execute_tool, tool_call.function.name, args
            )
        tool_messages.append(
            Message(
                role="tool",
                tool_call_id=tool_call.id,
                name=tool_call.function.name,
                content=json.dumps(result, ensure_ascii=False),
            )
        )
    return {**state, "messages": [*state["messages"], *tool_messages]}


def _route_after_llm(state: AgentState) -> str:
    """tool_calls 가 있고 iter ≤ max_iters 이면 execute_tools, 아니면 END."""
    if state["iteration"] >= state["max_iters"]:
        return "end"
    if not state["messages"]:
        return "end"
    last = state["messages"][-1]
    if last.role == "assistant" and last.tool_calls:
        return "execute_tools"
    return "end"


def _build_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """LangGraph StateGraph 컴파일 — module-level 1회만 호출 (비용 절약)."""
    g = StateGraph(AgentState)
    g.add_node("llm_call", _llm_call_node)
    g.add_node("execute_tools", _execute_tools_node)
    g.set_entry_point("llm_call")
    g.add_conditional_edges(
        "llm_call",
        _route_after_llm,
        {"execute_tools": "execute_tools", "end": END},
    )
    g.add_edge("execute_tools", "llm_call")
    return g.compile()


_GRAPH = _build_graph()


async def run_agent(
    messages: list[Message],
    gateway: LLMGateway,
    max_iters: int = MAX_ITERS_DEFAULT,
    model: str | None = None,
    **generation_kwargs: object,
) -> AgentRunResult:
    """Tool-calling agent loop 실행 (LangGraph state graph).

    입력 `messages` 는 in-place 변경되지 않는다 — 호출 측이 원본 보존을
    보장받도록 새 리스트로 시작한다.

    generation_kwargs 는 LLM 호출 시 forward (temperature, max_tokens,
    tool_choice 등 OpenAI 호환 파라미터).
    """
    initial_state: AgentState = {
        "messages": list(messages),
        "iteration": 0,
        "max_iters": max_iters,
        "last_response": None,
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
    )
