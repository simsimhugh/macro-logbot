"""Tool registry — OpenAI tools schema 생성 + 이름 → 실행 라우팅.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.3
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from macro_logbot.tools.builtin import (
    git_blame,
    grep_codebase,
    list_directory,
    read_file,
    search_logs,
)

ToolExecutor = Callable[..., dict[str, Any]]


class ToolSpec(BaseModel):
    """단일 tool 의 schema + 실행 함수 묶음."""

    # Callable 은 pydantic core schema 에 직접 등록 안 됨 — arbitrary 허용.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    parameters_schema: dict[str, Any]
    executor: ToolExecutor


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "grep_codebase": ToolSpec(
        name="grep_codebase",
        description=(
            "Python 소스 코드 안에서 패턴을 정규/문자열로 검색합니다. "
            "결과는 파일 경로 + 라인 번호 + 매칭 텍스트 목록."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "grep 정규식 또는 문자열 패턴",
                },
                "path": {
                    "type": "string",
                    "description": "검색 시작 디렉토리 (기본: 현재 작업 디렉토리)",
                    "default": ".",
                },
                "max_results": {
                    "type": "integer",
                    "description": "반환할 최대 매칭 수",
                    "default": 50,
                },
            },
            "required": ["pattern"],
        },
        executor=grep_codebase,
    ),
    "read_file": ToolSpec(
        name="read_file",
        description="파일을 읽어 텍스트로 반환합니다. 라인 범위 옵션 가능.",
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "파일 경로"},
                "start_line": {
                    "type": "integer",
                    "description": "시작 라인 (1-indexed, inclusive)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "끝 라인 (1-indexed, inclusive)",
                },
            },
            "required": ["path"],
        },
        executor=read_file,
    ),
    "list_directory": ToolSpec(
        name="list_directory",
        description="디렉토리 항목을 나열합니다. 숨김 항목 제외.",
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "디렉토리 경로 (기본: 현재 작업 디렉토리)",
                    "default": ".",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "재귀 나열 여부",
                    "default": False,
                },
            },
            "required": [],
        },
        executor=list_directory,
    ),
    "git_blame": ToolSpec(
        name="git_blame",
        description="git blame -L 으로 특정 라인 범위의 작성자/커밋 정보를 반환합니다.",
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "파일 경로"},
                "start_line": {"type": "integer", "description": "시작 라인 (1-indexed)"},
                "end_line": {"type": "integer", "description": "끝 라인 (1-indexed)"},
            },
            "required": ["path", "start_line", "end_line"],
        },
        executor=git_blame,
    ),
    "search_logs": ToolSpec(
        name="search_logs",
        description="로그 디렉토리 안 .log/.txt 파일에서 패턴을 검색합니다.",
        parameters_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "검색 패턴"},
                "log_dir": {"type": "string", "description": "로그 디렉토리 경로"},
            },
            "required": ["pattern", "log_dir"],
        },
        executor=search_logs,
    ),
}


def get_openai_tools_schema() -> list[dict[str, Any]]:
    """OpenAI tools 형식 (function calling) 으로 등록된 모든 tool 을 변환."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters_schema,
            },
        }
        for spec in TOOL_REGISTRY.values()
    ]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """name 으로 tool 을 찾아 arguments 와 함께 실행."""
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return spec.executor(**arguments)
    except TypeError as exc:
        # 잘못된 인자 — LLM 이 다시 시도하도록 message 로 전달.
        return {"error": f"invalid arguments for {name}: {exc}"}
