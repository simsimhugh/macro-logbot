"""OpenAI /v1/chat/completions 호환 Pydantic 모델.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.1
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    messages: list[Message]
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    # stream=True is out of scope for this PR; field accepted but ignored
    stream: bool = False


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
