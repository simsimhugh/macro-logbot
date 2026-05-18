"""Built-in tool 함수 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from macro_logbot.tools.builtin import (
    git_blame,
    grep_codebase,
    list_directory,
    read_file,
    search_logs,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp_path 를 cwd 로 사용. tool 들은 cwd 기준 path 검증."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_grep_codebase_finds_match(workspace: Path) -> None:
    pkg = workspace / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (pkg / "other.py").write_text("# nothing here\n", encoding="utf-8")

    result = grep_codebase("alpha", path=".")
    assert "matches" in result
    matches = result["matches"]
    assert any("mod.py" in m["file"] and m["line"] == 1 for m in matches)


def test_grep_codebase_path_traversal_rejected(workspace: Path) -> None:
    result = grep_codebase("anything", path="../../../etc")
    assert result.get("error") == "path outside working directory"


def test_grep_codebase_respects_max_results(workspace: Path) -> None:
    big = workspace / "big.py"
    big.write_text("\n".join(f"x = {i}  # token" for i in range(100)), encoding="utf-8")
    result = grep_codebase("token", path=".", max_results=5)
    assert len(result["matches"]) == 5


def test_read_file_full(workspace: Path) -> None:
    p = workspace / "a.txt"
    p.write_text("hello\nworld\n", encoding="utf-8")
    result = read_file(str(p))
    # splitlines 후 "\n".join — trailing newline 제거됨 (의도된 정규화).
    assert result["content"] == "hello\nworld"
    assert result["total_lines"] == 2
    assert result["truncated"] is False


def test_read_file_max_lines_truncate(workspace: Path) -> None:
    """max_lines 가드 — 슬라이스 결과가 max 초과 시 truncate + flag=True."""
    p = workspace / "big.txt"
    p.write_text("\n".join(f"line{i}" for i in range(1, 501)), encoding="utf-8")
    result = read_file(str(p), max_lines=50)
    assert result["truncated"] is True
    assert result["content"].count("\n") == 49  # 50 lines
    assert result["end_line"] == 50
    assert result["total_lines"] == 500


def test_read_file_range(workspace: Path) -> None:
    p = workspace / "lines.txt"
    p.write_text("\n".join(f"line{i}" for i in range(1, 11)), encoding="utf-8")
    result = read_file(str(p), start_line=3, end_line=5)
    assert result["content"] == "line3\nline4\nline5"
    assert result["start_line"] == 3
    assert result["end_line"] == 5


def test_read_file_not_a_file(workspace: Path) -> None:
    result = read_file(str(workspace))
    assert "error" in result


def test_read_file_path_traversal(workspace: Path) -> None:
    result = read_file("../../etc/passwd")
    assert result.get("error") == "path outside working directory"


def test_list_directory_excludes_hidden(workspace: Path) -> None:
    (workspace / "visible.txt").write_text("x", encoding="utf-8")
    (workspace / ".hidden.txt").write_text("x", encoding="utf-8")
    sub = workspace / "sub"
    sub.mkdir()
    (sub / "inner.txt").write_text("x", encoding="utf-8")

    result = list_directory(".")
    names = {e["name"] for e in result["entries"]}
    assert "visible.txt" in names
    assert ".hidden.txt" not in names
    assert "sub" in names


def test_list_directory_recursive(workspace: Path) -> None:
    (workspace / "a.txt").write_text("x", encoding="utf-8")
    sub = workspace / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("x", encoding="utf-8")

    result = list_directory(".", recursive=True)
    names = {e["name"] for e in result["entries"]}
    assert "a.txt" in names
    assert "sub" in names
    assert "sub/b.txt" in names


def test_list_directory_not_a_dir(workspace: Path) -> None:
    f = workspace / "x.txt"
    f.write_text("x", encoding="utf-8")
    result = list_directory(str(f))
    assert "error" in result


def test_list_directory_path_traversal(workspace: Path) -> None:
    result = list_directory("../../")
    assert result.get("error") == "path outside working directory"


def test_git_blame_path_traversal(workspace: Path) -> None:
    result = git_blame("../../etc/passwd", 1, 1)
    assert result.get("error") == "path outside working directory"


def test_git_blame_not_a_file(workspace: Path) -> None:
    result = git_blame(".", 1, 1)
    assert "error" in result


def test_git_blame_non_git_dir(workspace: Path) -> None:
    # workspace 는 tmp 라 git repo 아님 — blame 은 error 반환.
    f = workspace / "x.txt"
    f.write_text("hi\n", encoding="utf-8")
    result = git_blame(str(f), 1, 1)
    assert "error" in result


def test_read_file_too_large_rejected(workspace: Path) -> None:
    """파일이 _READ_FILE_MAX_BYTES (2MB) 초과 시 명시적 error 반환."""
    big = workspace / "huge.txt"
    # 2MB + 1 byte
    big.write_bytes(b"x" * (2_000_000 + 1))
    result = read_file(str(big))
    assert "error" in result
    assert "file too large" in result["error"]


def test_search_logs_respects_max_results(workspace: Path) -> None:
    """search_logs max_results 가드 — 초과 시 truncate + flag."""
    logs = workspace / "logs"
    logs.mkdir()
    (logs / "app.log").write_text(
        "\n".join(f"line{i} pattern" for i in range(100)), encoding="utf-8"
    )
    result = search_logs("pattern", log_dir=str(logs), max_results=5)
    assert len(result["matches"]) == 5
    assert result["truncated"] is True


def test_search_logs_finds_pattern(workspace: Path) -> None:
    logs = workspace / "logs"
    logs.mkdir()
    (logs / "app.log").write_text("INFO ok\nERROR boom\n", encoding="utf-8")
    (logs / "notes.txt").write_text("nothing\nboom appears\n", encoding="utf-8")
    (logs / "binary.bin").write_text("boom\n", encoding="utf-8")

    result = search_logs("boom", log_dir=str(logs))
    files = {m["file"] for m in result["matches"]}
    assert any("app.log" in f for f in files)
    assert any("notes.txt" in f for f in files)
    assert not any("binary.bin" in f for f in files)


def test_search_logs_path_traversal(workspace: Path) -> None:
    result = search_logs("x", log_dir="../../etc")
    assert result.get("error") == "path outside working directory"


def test_search_logs_not_a_dir(workspace: Path) -> None:
    f = workspace / "x.log"
    f.write_text("x", encoding="utf-8")
    result = search_logs("x", log_dir=str(f))
    assert "error" in result
