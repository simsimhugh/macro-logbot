"""Built-in MCP tools — agent 가 호출할 수 있는 9개 tool (spec §5.3).

Spec reference: docs/design/02-설계문서.md (v1.1) §5.3

9 tools:
  - grep_codebase
  - read_file
  - list_directory
  - git_blame
  - search_logs
  - git_log
  - find_test_history (사외 PoC mock — task-MVP-003-x 사내 DB 연동)
  - get_environment_info
  - retrieve_similar_cases (KB §5.5 미구현 placeholder — task-MVP-003-x)
"""

from macro_logbot.tools.builtin import (
    find_test_history,
    get_environment_info,
    git_blame,
    git_log,
    grep_codebase,
    list_directory,
    read_file,
    retrieve_similar_cases,
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
    "find_test_history",
    "get_environment_info",
    "get_openai_tools_schema",
    "git_blame",
    "git_log",
    "grep_codebase",
    "list_directory",
    "read_file",
    "retrieve_similar_cases",
    "search_logs",
]
