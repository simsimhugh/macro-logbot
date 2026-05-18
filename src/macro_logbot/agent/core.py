"""Agent loop — tool-calling round-trip.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.2

흐름:
  1. tools schema 첨부하여 gateway.complete 호출.
  2. assistant_msg.tool_calls 가 없으면 final answer 로 반환.
  3. 있으면 각 tool_call 을 실행 (asyncio.to_thread), 결과를 tool role
     message 로 messages 에 추가.
  4. 다음 iter 로.
  5. max_iters 도달 시 마지막 response 그대로 반환.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

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


async def run_agent(
    messages: list[Message],
    gateway: LLMGateway,
    max_iters: int = MAX_ITERS_DEFAULT,
    model: str | None = None,
    **generation_kwargs: object,
) -> AgentRunResult:
    """Tool-calling agent loop 실행.

    messages 는 in-place 로 확장되지 않고 새 리스트로 작업한다 — 호출 측이
    원본 보존을 보장받도록.

    generation_kwargs 는 LLM 호출 시 forward (temperature, max_tokens,
    tool_choice 등 OpenAI 호환 파라미터).
    """
    working: list[Message] = list(messages)
    tools = get_openai_tools_schema()
    last_response: ChatCompletionResponse | None = None

    for iteration in range(1, max_iters + 1):
        response = await gateway.complete(
            working, model=model, tools=tools, **generation_kwargs
        )
        last_response = response
        if not response.choices:
            return AgentRunResult(
                response=response, iterations=iteration, messages=working
            )
        assistant_msg = response.choices[0].message
        working.append(assistant_msg)
        if not assistant_msg.tool_calls:
            return AgentRunResult(
                response=response, iterations=iteration, messages=working
            )

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
            working.append(
                Message(
                    role="tool",
                    tool_call_id=tool_call.id,
                    name=tool_call.function.name,
                    content=json.dumps(result, ensure_ascii=False),
                )
            )

    # max_iters 도달 — 마지막 response 그대로 반환 (final answer 미수신 가능성).
    assert last_response is not None  # loop 최소 1회 실행 보장
    return AgentRunResult(
        response=last_response, iterations=max_iters, messages=working
    )
