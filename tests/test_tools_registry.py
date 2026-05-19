"""Tool registry 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from macro_logbot.tools.registry import (
    TOOL_REGISTRY,
    execute_tool,
    get_openai_tools_schema,
)


def test_registry_has_nine_tools() -> None:
    expected = {
        "grep_codebase",
        "read_file",
        "list_directory",
        "git_blame",
        "search_logs",
        "git_log",
        "find_test_history",
        "get_environment_info",
        "retrieve_similar_cases",
    }
    assert set(TOOL_REGISTRY.keys()) == expected


def test_openai_tools_schema_shape() -> None:
    schema = get_openai_tools_schema()
    assert len(schema) == 9
    for entry in schema:
        assert entry["type"] == "function"
        fn = entry["function"]
        assert "name" in fn
        assert "description" in fn
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params


def test_execute_tool_unknown() -> None:
    result = execute_tool("does_not_exist", {})
    assert "error" in result
    assert "unknown tool" in result["error"]


def test_execute_tool_invalid_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    # read_file 은 path 가 필수 — 미제공 시 TypeError → "invalid arguments".
    result = execute_tool("read_file", {})
    assert "error" in result
    assert "invalid arguments" in result["error"]


def test_execute_tool_happy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.txt").write_text("hello\n", encoding="utf-8")
    result = execute_tool("read_file", {"path": "x.txt"})
    # splitlines/join 정규화 — trailing newline 제거.
    assert result.get("content") == "hello"
