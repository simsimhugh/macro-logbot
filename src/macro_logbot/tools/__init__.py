"""Built-in MCP tools — agent 가 호출할 수 있는 5개 핵심 tool.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.3

핵심 5개 (MVP scope):
  - grep_codebase
  - read_file
  - list_directory
  - git_blame
  - search_logs

나머지 4개 (FOLLOWUP): git_log, find_test_history, get_environment_info,
retrieve_similar_cases.
"""

from macro_logbot.tools.builtin import (
    git_blame,
    grep_codebase,
    list_directory,
    read_file,
    search_logs,
)
from macro_logbot.tools.registry import (
    TOOL_REGISTRY,
    ToolSpec,
    execute_tool,
    get_openai_tools_schema,
)

__all__ = [
    "TOOL_REGISTRY",
    "ToolSpec",
    "execute_tool",
    "get_openai_tools_schema",
    "git_blame",
    "grep_codebase",
    "list_directory",
    "read_file",
    "search_logs",
]
