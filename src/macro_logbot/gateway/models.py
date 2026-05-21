"""OpenAI /v1/chat/completions 호환 Pydantic 모델.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1 · §5.2
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic import PrivateAttr


class FunctionCall(BaseModel):
    """OpenAI tool_calls 내 function 객체."""

    name: str
    # arguments 는 JSON 문자열 (OpenAI 스펙) — agent loop 에서 json.loads.
    arguments: str


class ToolCall(BaseModel):
    """OpenAI assistant message 의 tool_calls 항목."""

    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class Message(BaseModel):
    role: str
    # tool message 의 경우 content 는 tool 실행 결과 (string).
    content: str | None = None
    # assistant 가 tool 호출을 결정한 경우.
    tool_calls: list[ToolCall] | None = None
    # role="tool" 메시지가 어느 tool_call 에 대한 응답인지 식별.
    tool_call_id: str | None = None
    # 일부 provider 가 function/tool 메시지에 함께 요구.
    name: str | None = None
    # task-AGENT-024: gpt-oss / o1 류 reasoning model 의 chain-of-thought 분리 응답.
    # content 와 별개 필드 — request 시에는 항상 None (model_dump(exclude_none) 로 자동 제외),
    # response 시에만 LiteLLM 에서 capture. KB archive / observability 활용.
    reasoning: str | None = None


class ChatCompletionRequest(BaseModel):
    messages: list[Message]
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    # stream=True 은 본 PR 에서 미지원 — endpoint 가 명시적 400 으로 거절.
    # SSE 본기능 지원은 후속 PR (FOLLOWUP task-LG-003).
    stream: bool = False
    # tools/tool_choice 는 LiteLLM 으로 그대로 passthrough — body.tools 가
    # 명시되면 app.py 가 raw 경로로 (agent loop 우회) 전달.
    tools: list[dict[str, object]] | None = None
    tool_choice: str | dict[str, object] | None = None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = Field(default="chat.completion")
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
    # task-AGENT-009: fallback parser 사용 여부 — observability / SIEM 노출.
    # None = 정상 경로, "layer1_no_tools_retry" = BadRequestError retry,
    # "layer2_regex_inject" = content regex 패턴 검출.
    _fallback_used: str | None = PrivateAttr(default=None)
    # Layer 2 의 경우 매칭된 패턴 이름: "function_xml" / "tool_call_xml" /
    # "json_codeblock" / "python_tag". Layer 1 또는 정상 경로에서는 None.
    _fallback_pattern: str | None = PrivateAttr(default=None)
