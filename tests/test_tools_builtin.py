"""Built-in tool 함수 단위 테스트."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from macro_logbot.knowledge_base import ArchivedCase, SQLiteKBStore
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


def test_grep_codebase_literal_special_regex_no_error(workspace: Path) -> None:
    """LLM 이 escape 안된 regex special char 보내도 fail 안 함 (사내 평가 2026-05-21).

    이전: `grep -rn --include=*.py 'def step\\(self' ...` → BRE 가 `Unmatched (` error
    → silent 0-match → agent panic. Fix: `-F` (fixed string).
    """
    pkg = workspace / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        "class SnakeGame:\n"
        "    def step(self, action):\n"
        "        self.head.x += 1\n",
        encoding="utf-8",
    )

    # LLM 의 실제 호출 패턴 — escape 시도한 `\(` (사내 평가 발견)
    result = grep_codebase(r"def step\(self", path=".")
    # 핵심 검증: error 안 남 (이전엔 `Unmatched (` error)
    assert "error" not in result, f"unexpected error: {result.get('error')}"
    # literal 매칭이라 `def step\(self` 가 file 의 `def step(self` 와 매칭 안 됨 — 의도된 동작
    assert result["matches"] == []


def test_grep_codebase_literal_paren_match(workspace: Path) -> None:
    """LLM 이 보낸 literal `(` 도 escape 없이 매칭 — `-F` mode 의 핵심 효과."""
    pkg = workspace / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        "def init_game(self):\n"
        "    self.head = None\n",
        encoding="utf-8",
    )

    result = grep_codebase("def init_game(self)", path=".")
    assert "error" not in result, f"unexpected error: {result.get('error')}"
    matches = result["matches"]
    assert any(m["line"] == 1 and "init_game" in m["text"] for m in matches), (
        f"literal `(` match should succeed, got: {matches}"
    )


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


def _init_git_repo(path: Path) -> None:
    """tmp dir 에 최소 git repo 초기화 — author/email + 단일 commit."""
    env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=path, check=True, env=env
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"], cwd=path, check=True
    )


def test_git_log_returns_commits(workspace: Path) -> None:
    _init_git_repo(workspace)
    (workspace / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "first commit"], cwd=workspace, check=True
    )
    (workspace / "b.txt").write_text("world\n", encoding="utf-8")
    subprocess.run(["git", "add", "b.txt"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "second commit"],
        cwd=workspace,
        check=True,
    )
    result = git_log()
    assert "commits" in result
    messages = [c["message"] for c in result["commits"]]
    assert "second commit" in messages
    assert "first commit" in messages
    # 각 entry 는 hash + message 키.
    for commit in result["commits"]:
        assert commit["hash"]
        assert isinstance(commit["hash"], str)


def test_git_log_path_filter(workspace: Path) -> None:
    _init_git_repo(workspace)
    (workspace / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "touch a"], cwd=workspace, check=True
    )
    (workspace / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "add", "b.txt"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "touch b"], cwd=workspace, check=True
    )
    result = git_log(path="a.txt")
    messages = [c["message"] for c in result["commits"]]
    assert "touch a" in messages
    assert "touch b" not in messages


def test_git_log_not_git_dir(workspace: Path) -> None:
    # workspace 는 git init 안 된 상태 — git log 가 error 반환.
    result = git_log()
    assert "error" in result


def test_git_log_path_traversal(workspace: Path) -> None:
    result = git_log(path="../../etc/passwd")
    assert result.get("error") == "path outside working directory"


def test_find_test_history_mock(workspace: Path) -> None:
    result = find_test_history("TC-001")
    assert result["test_id"] == "TC-001"
    assert result["test_runs"] == []
    assert "note" in result
    assert "mock" in result["note"]


def test_find_test_history_missing_test_id(workspace: Path) -> None:
    result = find_test_history("")
    assert "error" in result
    assert "test_id" in result["error"]


def test_get_environment_info_has_python(workspace: Path) -> None:
    result = get_environment_info()
    assert "python" in result
    assert "os" in result
    assert "platform" in result
    assert "packages" in result
    # 핵심 패키지 키 확인 — 본 환경에 설치된 항목.
    packages = result["packages"]
    for name in ("litellm", "fastapi", "langgraph", "pydantic", "pyyaml"):
        assert name in packages
    # 시크릿 노출 X — env vars 키는 응답 어디에도 없어야.
    for key in ("api_key", "MACRO_LOGBOT_API_KEY", "env", "secrets"):
        assert key not in result


def test_retrieve_similar_cases_missing_signature(workspace: Path) -> None:
    result = retrieve_similar_cases("")
    assert "error" in result
    assert "error_signature" in result["error"]


def test_retrieve_similar_cases_kb_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KB SQLiteKBStore fixture — add 후 retrieve_similar_cases 로 케이스 반환 검증."""
    import macro_logbot.tools.builtin as builtin_mod

    db_path = tmp_path / "kb.db"
    store = SQLiteKBStore(db_path)
    case = ArchivedCase(
        case_id="test-case-001",
        error_signature="AttributeError:NoneType",
        category="runtime/none-access",
        root_cause="None 값에 접근",
        location={"file": "src/app.py", "function": "run", "line": 10},
        fix_hint="None 체크 추가",
        confidence=0.85,
        source="poc",
    )
    store.add(case)

    # module-level singleton 리셋 + env 패치
    monkeypatch.setattr(builtin_mod, "_kb_store", None)
    monkeypatch.setenv("MACRO_LOGBOT_KB_PATH", str(db_path))

    result = retrieve_similar_cases("AttributeError:NoneType")
    assert result["error_signature"] == "AttributeError:NoneType"
    assert len(result["similar_cases"]) == 1
    assert result["similar_cases"][0]["case_id"] == "test-case-001"


def test_retrieve_similar_cases_signature_length_cap(workspace: Path) -> None:
    """error_signature 가 _MAX_SIGNATURE_LEN (4096) 초과 시 error 반환."""
    long_sig = "A" * 4097
    result = retrieve_similar_cases(long_sig)
    assert "error" in result
    assert "too long" in result["error"]


def test_retrieve_similar_cases_top_k_range(workspace: Path) -> None:
    """top_k 가 1..50 범위를 벗어나면 error 반환."""
    result_zero = retrieve_similar_cases("AttributeError:NoneType", top_k=0)
    assert "error" in result_zero

    result_over = retrieve_similar_cases("AttributeError:NoneType", top_k=51)
    assert "error" in result_over


def test_retrieve_similar_cases_kb_oserror_fallback(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KB init 시 OSError → _get_kb_store None → note 포함 빈 결과 반환.

    PoC 환경에서 .macro-logbot/ 디렉토리 생성이 실패하는 케이스 (read-only fs 등)
    의 fallback 분기 검증. retrieve_similar_cases 가 error 가 아닌 note 로 처리.
    """
    import macro_logbot.tools.builtin as builtin_mod

    monkeypatch.setattr(builtin_mod, "_kb_store", None)
    # /proc/nonexistent/ 는 mkdir 시 OSError (procfs read-only).
    monkeypatch.setenv("MACRO_LOGBOT_KB_PATH", "/proc/nonexistent/kb.db")

    result = retrieve_similar_cases("AttributeError:NoneType")
    assert result.get("error") is None
    assert result["similar_cases"] == []
    assert "note" in result
