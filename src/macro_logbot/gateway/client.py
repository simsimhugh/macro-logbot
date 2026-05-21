"""LiteLLM 래퍼 — 멀티 프로바이더 LLM 클라이언트.

Spec reference: docs/design/02-설계문서.md (v1.1) §4 LG · §7

Supported model prefixes:
  openai/     — e.g. "openai/gpt-4o"
  anthropic/  — e.g. "anthropic/claude-haiku-3-5"
  gemini/     — e.g. "gemini/gemini-2.5-flash-lite"
  groq/       — e.g. "groq/llama3-8b-8192"

Provider API keys are read by LiteLLM directly from the environment:
  OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import types
import uuid
from typing import Any

import litellm

from macro_logbot.gateway.models import (
    ChatCompletionResponse,
    Choice,
    FunctionCall,
    Message,
    ToolCall,
    Usage,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_ENV = "MACRO_LOGBOT_DEFAULT_MODEL"
_FALLBACK_MODEL = "gemini/gemini-2.5-flash-lite"

# 사내 LLM endpoint env (task-LG-002 / spec §7.3).
# arg > env > None 우선순위로 LLMGateway.__init__ 에서 흡수.
_LLM_BASE_URL_ENV = "MACRO_LOGBOT_LLM_BASE_URL"
_LLM_API_KEY_ENV = "MACRO_LOGBOT_LLM_API_KEY"
_LLM_PROVIDER_ENV = "MACRO_LOGBOT_LLM_PROVIDER"

# 사내 API gateway 커스텀 헤더 env (DS API HUB x-dep-ticket 인증 방식).
# extra_headers forward 는 LiteLLM 의 OpenAI-compat provider 한정 — 사내 endpoint 가
# OpenAI 호환 (/v1/chat/completions) 인 한 정상 동작. Anthropic/Gemini native 경로는
# 일부 header drop 가능 (각 provider 의 transformer 동작 의존).
_LLM_X_DEP_TICKET_ENV = "MACRO_LOGBOT_LLM_X_DEP_TICKET"
_LLM_SEND_SYSTEM_NAME_ENV = "MACRO_LOGBOT_LLM_SEND_SYSTEM_NAME"
_LLM_USER_ID_ENV = "MACRO_LOGBOT_LLM_USER_ID"
_LLM_USER_TYPE_ENV = "MACRO_LOGBOT_LLM_USER_TYPE"

# task-AGENT-024: gpt-oss / o1 류 reasoning model 의 reasoning_effort + 장기 호출 timeout.
# 사용자 요구: latency 무제한 (10분 OK) — high effort 측정 시 default timeout 부족 방지.
# reasoning_effort 는 low/medium/high 만 허용 — LiteLLM 이 그대로 OpenAI compat 으로 forward.
_LLM_REASONING_EFFORT_ENV = "MACRO_LOGBOT_LLM_REASONING_EFFORT"
_LLM_TIMEOUT_SEC_ENV = "MACRO_LOGBOT_LLM_TIMEOUT_SEC"
_REASONING_EFFORT_ALLOWED: frozenset[str] = frozenset({"low", "medium", "high"})

# task-SEC-003: complete(**kwargs) 자유 패스스루 차단 → allowlist 외 ValueError.
# OpenAI / LiteLLM 호환 generation 파라미터 + tool calling 만 허용.
# agent loop (run_agent) 가 보내는 generation_kwargs (temperature/max_tokens 등) +
# /v1/chat/completions raw passthrough 가 보내는 body 필드 (tools/tool_choice) 모두 포함.
# task-AGENT-024: reasoning_effort / timeout 추가 — gpt-oss 류 reasoning model 지원.
_ALLOWED_FORWARD_KWARGS: frozenset[str] = frozenset(
    {
        "temperature",
        "max_tokens",
        "top_p",
        "top_k",
        "frequency_penalty",
        "presence_penalty",
        "stop",
        "stream",
        "n",
        "seed",
        "response_format",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "reasoning_effort",
        "timeout",
    }
)


# task-AGENT-008: OSS 모델 native tool-call 패턴 fallback parser.
# 각 provider 가 tools 파라미터 없이 free-form text 로 tool call 을 출력할 때 검출.
# 현재 cover: Llama 3.1/3.3, Qwen, markdown JSON. Mistral [TOOL_CALLS] 등 추가는 follow-up.
# args body 는 lazy `.*?` 로 잡고 json.loads 로 사후 검증 — Pattern 1/4 의 `[^<]/[^|]` 한계 (
# special char 있는 args 매칭 실패) 해소 (CR WARN-1).
# task-AGENT-009: 각 패턴에 이름 부여 — _fallback_pattern metadata 노출용.
_FALLBACK_TOOL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Llama 3.3 native: <function=name>{json_args}</function>
    (
        "function_xml",
        re.compile(
            r"<function=(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>\s*(?P<args>\{.*?\})\s*</function>",
            re.DOTALL,
        ),
    ),
    # Qwen tool_call tag: <tool_call>{"name":"...", "arguments":{...}}</tool_call>
    (
        "tool_call_xml",
        re.compile(r"<tool_call>\s*(?P<json>\{.*?\})\s*</tool_call>", re.DOTALL),
    ),
    # Markdown JSON code block: ```json\n{...}\n```
    # name/arguments 키 존재는 json.loads 후 검증 (CR WARN-2: 키 순서/누락 false negative 해소).
    (
        "json_codeblock",
        re.compile(r"```json\s*\n(?P<json>\{.*?\})\s*```", re.DOTALL),
    ),
    # Llama 3.1 python_tag: <|python_tag|>name.call({...})
    (
        "python_tag",
        re.compile(
            r"<\|python_tag\|>(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\.call\(\s*(?P<args>\{.*?\})\s*\)",
            re.DOTALL,
        ),
    ),
]

# security WARN-M2: content length cap — regex DoS 가드 + 메모리/지연 보호.
# 64KB 초과 시 fallback parser skip (보통 LLM 응답 < 16KB, MACRO log 도 < 32KB).
_MAX_FALLBACK_CONTENT_LEN = 64 * 1024


def _parse_fallback_tool_calls(
    content: str,
) -> tuple[list[dict[str, Any]], str] | None:
    """LLM content 에서 native tool-call 패턴을 검출해 OpenAI tool_calls 형식으로 변환.

    매칭 패턴이 없으면 None. 검출 1개 이상이면 (calls, pattern_name) 튜플 반환.
    pattern_name 은 첫 매칭 패턴의 이름 ("function_xml" / "tool_call_xml" /
    "json_codeblock" / "python_tag") — task-AGENT-009 metadata 노출용.

    Returns:
      ([{"id": "fallback_0", "type": "function", "function": {"name": ..., "arguments": "..."}}],
       "pattern_name")
      arguments 는 JSON string (OpenAI tool_calls schema 준수).
    """
    # security WARN-M2: regex DoS 가드 — content 가 너무 크면 fallback skip.
    if len(content) > _MAX_FALLBACK_CONTENT_LEN:
        logger.warning(
            "fallback parser skipped — content length %d > %d (security cap)",
            len(content),
            _MAX_FALLBACK_CONTENT_LEN,
        )
        return None
    calls: list[dict[str, Any]] = []
    matched_pattern_name: str | None = None
    for pattern_name, pattern in _FALLBACK_TOOL_PATTERNS:
        for m in pattern.finditer(content):
            d = m.groupdict()
            if "name" in d and "args" in d:
                # Pattern 1, 4 (Llama): name + args 분리
                name = d["name"]
                args_json = d["args"]
                try:
                    json.loads(args_json)
                except json.JSONDecodeError:
                    continue
                if matched_pattern_name is None:
                    matched_pattern_name = pattern_name
                calls.append(
                    {
                        "id": f"fallback_{len(calls)}",
                        "type": "function",
                        "function": {"name": name, "arguments": args_json},
                    }
                )
            elif "json" in d:
                # Pattern 2, 3 (Qwen/markdown): json 객체 안 name+arguments 분리
                try:
                    obj = json.loads(d["json"])
                    name = obj.get("name") or (obj.get("function") or {}).get("name")
                    args = (
                        obj.get("arguments")
                        or (obj.get("function") or {}).get("arguments")
                        or {}
                    )
                    if not name:
                        continue
                    args_str = args if isinstance(args, str) else json.dumps(args)
                    if matched_pattern_name is None:
                        matched_pattern_name = pattern_name
                    calls.append(
                        {
                            "id": f"fallback_{len(calls)}",
                            "type": "function",
                            "function": {"name": name, "arguments": args_str},
                        }
                    )
                except (json.JSONDecodeError, AttributeError):
                    continue
    if calls and matched_pattern_name is not None:
        return calls, matched_pattern_name
    return None


def _construct_tool_call_obj(call: dict[str, Any]) -> object:
    """fallback dict 를 LiteLLM tool_call 객체 형태로 래핑.

    _extract_tool_calls 가 getattr/dict.get 둘 다 처리하므로
    SimpleNamespace 로 충분하다.
    """
    fn = call["function"]
    return types.SimpleNamespace(
        id=call["id"],
        type=call["type"],
        function=types.SimpleNamespace(
            name=fn["name"],
            arguments=fn["arguments"],
        ),
    )


def _extract_tool_calls(raw_tool_calls: object) -> list[ToolCall] | None:
    """LiteLLM tool_calls 응답을 ToolCall 리스트로 정규화.

    LiteLLM 은 provider 에 따라 list[obj] 또는 list[dict] 로 반환할 수 있어
    양쪽 모두 처리한다.
    """
    if not raw_tool_calls:
        return None
    result: list[ToolCall] = []
    for tc in raw_tool_calls:  # type: ignore[attr-defined]
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            result.append(
                ToolCall(
                    id=tc.get("id", ""),
                    type="function",
                    function=FunctionCall(
                        name=fn.get("name", ""),
                        arguments=fn.get("arguments", "") or "",
                    ),
                )
            )
        else:
            fn = getattr(tc, "function", None)
            result.append(
                ToolCall(
                    id=getattr(tc, "id", "") or "",
                    type="function",
                    function=FunctionCall(
                        name=getattr(fn, "name", "") or "",
                        arguments=getattr(fn, "arguments", "") or "",
                    ),
                )
            )
    return result or None


class LLMGateway:
    """LiteLLM 을 통한 멀티 프로바이더 LLM 게이트웨이."""

    def __init__(
        self,
        default_model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        custom_llm_provider: str | None = None,
    ) -> None:
        # Priority: explicit arg → env var → hardcoded fallback / None.
        # 사내 LLM endpoint (spec §7.3 · task-LG-002) — base_url/api_key/provider
        # 는 미설정 시 None (LiteLLM 이 provider prefix 와 표준 env 키로 fallback).
        self.default_model: str = (
            default_model
            or os.environ.get(_DEFAULT_MODEL_ENV)
            or _FALLBACK_MODEL
        )
        self.base_url: str | None = base_url or os.environ.get(_LLM_BASE_URL_ENV)
        self.api_key: str | None = api_key or os.environ.get(_LLM_API_KEY_ENV)
        self.custom_llm_provider: str | None = custom_llm_provider or os.environ.get(
            _LLM_PROVIDER_ENV
        )
        # 사내 DS API HUB 커스텀 헤더 — x-dep-ticket 설정 시 extra_headers 로 주입.
        # static 부분만 __init__ 에 보관 — Prompt-Msg-Id / Completion-Msg-Id 는
        # complete() 안에서 매 호출마다 새 UUID 로 생성 (traceability).
        # strip() — env 가 공백만 있는 경우 (운영자 실수) 망가진 헤더 forward 회피.
        self._extra_headers: dict[str, str] | None = None
        x_dep_ticket = (os.environ.get(_LLM_X_DEP_TICKET_ENV) or "").strip()
        if x_dep_ticket:
            self._extra_headers = {
                "x-dep-ticket": x_dep_ticket,
                "Send-System-Name": os.environ.get(_LLM_SEND_SYSTEM_NAME_ENV, "macro-logbot"),
                "User-Id": os.environ.get(_LLM_USER_ID_ENV, "macro-logbot"),
                "User-Type": os.environ.get(_LLM_USER_TYPE_ENV, "AD_ID"),
            }

        # task-AGENT-024: reasoning_effort + timeout — env-driven default 만 보관.
        # complete(**kwargs) 의 explicit 값이 우선 (None 일 때만 default 적용).
        # 잘못된 값은 fail-fast — 운영자가 실수해도 silent corruption 없도록 __init__ 시점에 raise.
        self.reasoning_effort: str | None = None
        re_env = (os.environ.get(_LLM_REASONING_EFFORT_ENV) or "").strip().lower()
        if re_env:
            if re_env not in _REASONING_EFFORT_ALLOWED:
                raise ValueError(
                    f"invalid {_LLM_REASONING_EFFORT_ENV}={re_env!r} — "
                    f"expected one of: {sorted(_REASONING_EFFORT_ALLOWED)}"
                )
            self.reasoning_effort = re_env

        self.timeout: float | None = None
        to_env = (os.environ.get(_LLM_TIMEOUT_SEC_ENV) or "").strip()
        if to_env:
            try:
                to_val = float(to_env)
            except ValueError as e:
                raise ValueError(
                    f"invalid {_LLM_TIMEOUT_SEC_ENV}={to_env!r} — expected float seconds"
                ) from e
            if to_val <= 0:
                raise ValueError(
                    f"invalid {_LLM_TIMEOUT_SEC_ENV}={to_env!r} — must be > 0"
                )
            self.timeout = to_val

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs: object,
    ) -> ChatCompletionResponse:
        """LiteLLM acompletion 을 호출하고 결과를 우리 응답 모델로 변환한다.

        kwargs 는 `_ALLOWED_FORWARD_KWARGS` allowlist 외 인자 시 `ValueError`
        (task-SEC-003). base_url/api_key/custom_llm_provider 는 None 제외 후
        forward (task-LG-002).
        """
        # task-SEC-003: allowlist 검증 — 자유 패스스루 차단.
        bad = set(kwargs) - _ALLOWED_FORWARD_KWARGS
        if bad:
            raise ValueError(
                f"disallowed kwargs forwarded to acompletion: {sorted(bad)}"
            )

        # task-AGENT-024: env-driven default 주입 — caller 명시 kwarg 가 우선.
        # gpt-oss / o1 류 reasoning model 의 effort + 장기 호출 timeout 을
        # agent loop 변경 없이 측정 환경에서 토글 가능하게.
        if self.reasoning_effort is not None and "reasoning_effort" not in kwargs:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.timeout is not None and "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        target_model = model or self.default_model
        # tool_calls / tool_call_id / name 등 None 이 아닌 모든 필드를 보존.
        # 사내 DS API Gateway 규칙: tool_calls 있는 assistant 메시지에 content 필드 필수
        # (null / missing 시 422 Unprocessable Entity). model_dump(exclude_none=True) 가
        # content=None 일 때 key 자체를 제외하므로 명시적 content="" 보강.
        raw_messages: list[dict[str, Any]] = []
        for m in messages:
            d = m.model_dump(exclude_none=True)
            if d.get("role") == "assistant" and "tool_calls" in d and "content" not in d:
                d["content"] = ""
            raw_messages.append(d)

        # task-LG-002: 사내 LLM endpoint forward — None 제외해 LiteLLM 기본 동작 보존.
        extra: dict[str, Any] = {}
        if self.base_url is not None:
            extra["base_url"] = self.base_url
        if self.api_key is not None:
            extra["api_key"] = self.api_key
        if self.custom_llm_provider is not None:
            extra["custom_llm_provider"] = self.custom_llm_provider
        if self._extra_headers is not None:
            extra["extra_headers"] = {
                **self._extra_headers,
                "Prompt-Msg-Id": str(uuid.uuid4()),
                "Completion-Msg-Id": str(uuid.uuid4()),
            }

        # task-AGENT-024: reasoning_effort / timeout 등 model-specific param 의 안전 drop.
        # 비-reasoning model (gemini, claude, gemma 등) 에 reasoning_effort 가 forward 되면
        # LiteLLM 이 `openai does not support parameters: ['reasoning_effort']` UnsupportedParamsError.
        # drop_params=True 로 LiteLLM 이 model 별 미지원 param 을 silent drop — 단일 코드베이스로
        # 멀티 provider (reasoning + 비-reasoning) 동시 지원.
        extra.setdefault("drop_params", True)

        # Layer 1: BadRequestError(tool_use_failed) 자동 retry (1회).
        # Groq 의 native tool parser 가 LLM 출력 변환 실패 시 tools 없이 재호출
        # → content 를 받아 Layer 2 fallback parser 로 흘린다.
        # 재호출 안에서 또 BadRequestError 가 나면 그대로 raise (무한루프 방지).
        layer1_retry_used = False
        try:
            response = await litellm.acompletion(
                model=target_model,
                messages=raw_messages,
                **extra,
                **kwargs,
            )
        except litellm.exceptions.BadRequestError as exc:
            if "tool_use_failed" in str(exc) and "tools" in kwargs:
                retry_kwargs = {
                    k: v
                    for k, v in kwargs.items()
                    if k != "tools" and k != "tool_choice"
                }
                logger.warning(
                    "tool_use_failed for %s — retrying without tools (fallback parser)",
                    target_model,
                )
                layer1_retry_used = True
                response = await litellm.acompletion(
                    model=target_model,
                    messages=raw_messages,
                    **extra,
                    **retry_kwargs,
                )
            else:
                raise

        # Layer 2: content → tool_calls fallback extraction.
        # tool_calls 가 비어 있고 content 가 있으면 regex 로 native 패턴 검출.
        raw_msg = response.choices[0].message
        layer2_pattern_name: str | None = None
        layer2_inject_used = False
        if not getattr(raw_msg, "tool_calls", None) and getattr(raw_msg, "content", None):
            fallback_result = _parse_fallback_tool_calls(raw_msg.content)
            if fallback_result:
                fallback_calls, layer2_pattern_name = fallback_result
                layer2_inject_used = True
                logger.info(
                    "fallback parser extracted %d tool_calls from content "
                    "pattern=%s model=%s",
                    len(fallback_calls),
                    layer2_pattern_name,
                    target_model,
                )
                raw_msg.tool_calls = [_construct_tool_call_obj(c) for c in fallback_calls]
            elif layer1_retry_used:
                # CR WARN-3: Layer 1 retry 후 Layer 2 도 0-match — silent recovery 위험.
                # tool 호출 의도가 있었으나 fallback parser 가 패턴 인식 못함 → agent loop 가
                # tool 없이 final answer 박제. 운영자 진단 위해 warning 명시.
                logger.warning(
                    "fallback parser 0-match after tool_use_failed retry (model=%s, content_len=%d) — "
                    "agent may terminate without tool call",
                    target_model,
                    len(raw_msg.content),
                )

        # task-AGENT-024: gpt-oss / o1 류 reasoning model 의 reasoning (chain-of-thought).
        # LiteLLM 이 OpenAI compat response 의 .reasoning 필드를 그대로 노출.
        # 비-reasoning model 은 attribute 부재 → getattr default None. 빈 string 도 None 정규화.
        choices = [
            Choice(
                index=c.index,
                message=Message(
                    role=c.message.role,
                    content=c.message.content or None,
                    tool_calls=_extract_tool_calls(
                        getattr(c.message, "tool_calls", None)
                    ),
                    reasoning=getattr(c.message, "reasoning", None) or None,
                ),
                finish_reason=c.finish_reason,
            )
            for c in response.choices
        ]
        # LiteLLM provider 일부(예: Anthropic prompt caching, Groq stream 종결)에서
        # response.usage 또는 그 하위 필드가 None 인 케이스 방어.
        usage_data = response.usage
        usage = Usage(
            prompt_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage_data, "total_tokens", 0) or 0,
        )

        # response.id / .object / .model 도 provider edge case 에서 None 가능 —
        # usage 와 동일 defensive 패턴 적용 (일관성).
        result = ChatCompletionResponse(
            id=response.id or f"chatcmpl-litellm-{int(time.time())}",
            object=response.object or "chat.completion",
            created=response.created or int(time.time()),
            model=response.model or target_model,
            choices=choices,
            usage=usage,
        )

        # task-AGENT-009: fallback metadata 노출 — observability / SIEM.
        # PrivateAttr 는 생성자 파라미터로 전달 불가 → 생성 후 setattr.
        if layer1_retry_used:
            result._fallback_used = "layer1_no_tools_retry"
            logger.warning(
                "fallback=layer1_no_tools_retry model=%s",
                target_model,
            )
        if layer2_inject_used:
            result._fallback_used = "layer2_regex_inject"
            result._fallback_pattern = layer2_pattern_name
        # 정상 경로: _fallback_used 는 PrivateAttr default=None 유지.

        return result
