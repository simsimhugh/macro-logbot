"""PoC workspace path 정책 regression 테스트 (task-TOOL-001).

4 security layer 검증:
  Layer 1: literal prefix match only
  Layer 2: symlink 거부
  Layer 3: secret blocklist (.env, .ssh 등)
  Layer 4: env=poc gate (fail-closed default)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import macro_logbot.tools.builtin as builtin_mod
from macro_logbot.tools.builtin import _safe_resolve


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_no_poc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """각 테스트 전: PoC env 변수 제거 + cwd = tmp_path."""
    monkeypatch.delenv("MACRO_LOGBOT_ENV", raising=False)
    monkeypatch.delenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", raising=False)
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# Layer 4: fail-closed default (production mode)
# ---------------------------------------------------------------------------


class TestProductionFailClosed:
    """MACRO_LOGBOT_ENV 미설정 → 모든 /tmp/poc-* 경로 거부."""

    def test_tmp_poc_path_denied_no_env(self, tmp_path: Path) -> None:
        # env 미설정 — cwd 밖 /tmp/poc-xxx 는 거부.
        result = _safe_resolve("/tmp/poc-E001-xxx/snake.py")
        assert result is None

    def test_tmp_poc_traversal_denied_no_env(self, tmp_path: Path) -> None:
        result = _safe_resolve("/tmp/poc-../etc/passwd")
        assert result is None

    def test_tmp_poc_secret_denied_no_env(self, tmp_path: Path) -> None:
        result = _safe_resolve("/tmp/poc-test/.env")
        assert result is None

    def test_poc_env_only_no_allowlist_denied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MACRO_LOGBOT_ENV=poc 이지만 ALLOWED 미설정 → cwd-only fallback."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        result = _safe_resolve("/tmp/poc-E001-xxx/snake.py")
        assert result is None

    def test_cwd_relative_path_still_allowed_no_env(self, tmp_path: Path) -> None:
        """env 미설정이어도 cwd 안 상대경로는 허용."""
        (tmp_path / "file.py").write_text("x", encoding="utf-8")
        result = _safe_resolve("file.py")
        assert result is not None
        assert result == (tmp_path / "file.py").resolve()


# ---------------------------------------------------------------------------
# Layer 1: literal prefix match
# ---------------------------------------------------------------------------


class TestLiteralPrefixMatch:
    """허용 prefix 와 일치하면 접근 가능, 미일치는 거부."""

    def test_matching_prefix_allowed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-")
        # 실제 파일 필요 없음 — resolve 결과만 검증.
        result = _safe_resolve("/tmp/poc-E001-xxx/snake.py")
        assert result is not None
        assert str(result).startswith("/tmp/poc-")

    def test_non_matching_prefix_denied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-")
        result = _safe_resolve("/tmp/other-dir/file.py")
        assert result is None

    def test_csv_multiple_prefixes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv(
            "MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-, /tmp/bench-"
        )
        assert _safe_resolve("/tmp/poc-E001/snake.py") is not None
        assert _safe_resolve("/tmp/bench-run/data.py") is not None
        assert _safe_resolve("/tmp/other/file.py") is None

    def test_path_traversal_rejected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """/tmp/poc-/../../etc/passwd — normpath 후 /etc/passwd — prefix 미일치 → 거부."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-")
        result = _safe_resolve("/tmp/poc-/../../etc/passwd")
        assert result is None


# ---------------------------------------------------------------------------
# Layer 3: secret blocklist
# ---------------------------------------------------------------------------


class TestSecretBlocklist:
    """secret blocklist 항목 포함 경로는 PoC 모드에서도 거부."""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "/tmp/poc-test/.env",
            "/tmp/poc-test/.ssh/id_rsa",
            "/tmp/poc-test/.aws/credentials",
            "/tmp/poc-test/id_ed25519",
            "/tmp/poc-test/config.json",
            "/tmp/poc-test/cert.pem",
        ],
    )
    def test_secret_paths_denied(
        self,
        bad_path: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-")
        result = _safe_resolve(bad_path)
        assert result is None, f"expected denial for {bad_path}"


# ---------------------------------------------------------------------------
# Layer 2: symlink 거부
# ---------------------------------------------------------------------------


class TestSymlinkRejection:
    """symlink 는 PoC 모드에서도 거부 (O_NOFOLLOW 동등)."""

    def test_symlink_file_denied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        # /tmp/poc-test-<random> 디렉토리 생성 후 symlink 생성.
        poc_dir = tmp_path / "poc-symlink-test"
        poc_dir.mkdir(parents=True, exist_ok=True)
        target = tmp_path / "real_file.py"
        target.write_text("real", encoding="utf-8")
        link = poc_dir / "link_to_real.py"
        link.symlink_to(target)

        monkeypatch.setenv(
            "MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", str(poc_dir)
        )
        result = _safe_resolve(str(link))
        assert result is None

    def test_symlink_dir_denied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.py").write_text("x", encoding="utf-8")
        link_dir = tmp_path / "poc-link-dir"
        link_dir.symlink_to(real_dir)

        monkeypatch.setenv(
            "MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", str(tmp_path)
        )
        result = _safe_resolve(str(link_dir / "file.py"))
        assert result is None


# ---------------------------------------------------------------------------
# cwd 안 경로 — poc 모드에서도 항상 허용
# ---------------------------------------------------------------------------


class TestCwdAlwaysAllowed:
    """cwd 안 경로는 PoC/production 모두 허용."""

    def test_cwd_path_allowed_in_poc_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-")
        (tmp_path / "local.py").write_text("x", encoding="utf-8")
        result = _safe_resolve("local.py")
        assert result is not None
        assert result.is_relative_to(tmp_path)
