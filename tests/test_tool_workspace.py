"""PoC workspace path 정책 regression 테스트 (task-TOOL-001).

4 security layer 검증:
  Layer 1: literal prefix match only
  Layer 2: symlink 거부
  Layer 3: secret blocklist (.env, .ssh 등)
  Layer 4: env=poc gate (fail-closed default)
"""

from __future__ import annotations

from pathlib import Path

import pytest

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

    def test_poc_env_only_no_allowlist_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
    """허용 prefix 와 일치하면 접근 가능, 미일치는 거부.

    prefix 는 directory 경계 단위로 지정해야 한다 (e.g. /tmp/poc-cases, /tmp/bench-run).
    partial-name prefix (e.g. /tmp/poc-) 는 sibling-dir escape 가능하므로 사용하지 않는다.
    """

    def test_matching_prefix_allowed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        # 실제 파일 필요 없음 — resolve 결과만 검증.
        result = _safe_resolve("/tmp/poc-cases/E001-xxx/snake.py")
        assert result is not None
        assert str(result).startswith("/tmp/poc-cases/")

    def test_non_matching_prefix_denied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/other-dir/file.py")
        assert result is None

    def test_csv_multiple_prefixes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases, /tmp/bench-run")
        assert _safe_resolve("/tmp/poc-cases/E001/snake.py") is not None
        assert _safe_resolve("/tmp/bench-run/data.py") is not None
        assert _safe_resolve("/tmp/other/file.py") is None

    def test_path_traversal_rejected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """/tmp/poc-cases/../../etc/passwd — normpath 후 /etc/passwd — prefix 미일치 → 거부."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-cases/../../etc/passwd")
        assert result is None


# ---------------------------------------------------------------------------
# Layer 3: secret blocklist
# ---------------------------------------------------------------------------


class TestSecretBlocklist:
    """secret blocklist 항목 포함 경로는 PoC 모드에서도 거부."""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "/tmp/poc-cases/.env",
            "/tmp/poc-cases/.ssh/id_rsa",
            "/tmp/poc-cases/.aws/credentials",
            "/tmp/poc-cases/id_ed25519",
            "/tmp/poc-cases/config.json",
            "/tmp/poc-cases/cert.pem",
        ],
    )
    def test_secret_paths_denied(
        self,
        bad_path: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve(bad_path)
        assert result is None, f"expected denial for {bad_path}"


# ---------------------------------------------------------------------------
# Layer 2: symlink 거부
# ---------------------------------------------------------------------------


class TestSymlinkRejection:
    """symlink 는 PoC 모드에서도 거부 (O_NOFOLLOW 동등)."""

    def test_symlink_file_denied(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        # /tmp/poc-test-<random> 디렉토리 생성 후 symlink 생성.
        poc_dir = tmp_path / "poc-symlink-test"
        poc_dir.mkdir(parents=True, exist_ok=True)
        target = tmp_path / "real_file.py"
        target.write_text("real", encoding="utf-8")
        link = poc_dir / "link_to_real.py"
        link.symlink_to(target)

        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", str(poc_dir))
        result = _safe_resolve(str(link))
        assert result is None

    def test_symlink_dir_denied(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.py").write_text("x", encoding="utf-8")
        link_dir = tmp_path / "poc-link-dir"
        link_dir.symlink_to(real_dir)

        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", str(tmp_path))
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


# ---------------------------------------------------------------------------
# BLOCK-1: sibling-dir escape 거부
# ---------------------------------------------------------------------------


class TestSiblingDirEscape:
    """sibling-dir escape — directory-boundary prefix 밖 경로는 거부."""

    def test_sibling_dir_escape_denied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """/tmp/poc-casesX/etc/shadow 는 prefix /tmp/poc-cases 에 매칭되면 안 된다.

        이전 단순 startswith('/tmp/poc-cases') 는 True 를 반환했음 (sibling-dir escape).
        _matches_prefix 는 '/tmp/poc-cases/' prefix 를 강제하므로 거부한다.
        """
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-casesX/etc/shadow")
        assert result is None, "sibling-dir escape must be denied"

    def test_exact_prefix_dir_allowed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """prefix 가 정확히 directory 경계인 경우만 허용."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-cases/E001/snake.py")
        assert result is not None
        assert str(result).startswith("/tmp/poc-cases/")

    def test_sibling_same_prefix_string_denied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """/tmp/poc-casesEXTRA/file.py 는 prefix /tmp/poc-cases 에 매칭되면 안 된다."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-casesEXTRA/file.py")
        assert result is None, "sibling dir with same prefix string must be denied"


# ---------------------------------------------------------------------------
# BLOCK-3 확장: path component 단위 blocklist + case-insensitive
# ---------------------------------------------------------------------------


class TestBlocklistPathComponent:
    """_is_secret: path component 단위 매칭 + case-insensitive."""

    def test_etc_passwd_denied(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """/tmp/poc-cases/etc/passwd — passwd 는 SECRET_NAMES 에 포함."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-cases/etc/passwd")
        assert result is None, "/tmp/poc-cases/etc/passwd must be denied"

    def test_dotenv_uppercase_denied(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """/tmp/poc-cases/.ENV — case-insensitive blocklist 적용."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-cases/.ENV")
        assert result is None, ".ENV must be denied (case-insensitive)"

    def test_ssh_dir_uppercase_denied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """/tmp/poc-cases/.SSH/config — .SSH 디렉토리 component 거부."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-cases/.SSH/config")
        assert result is None, ".SSH/ dir component must be denied (case-insensitive)"

    def test_credentialsmgr_dir_allowed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """credentialsmgr — substring false positive 방지. 허용돼야 한다.

        이전 substring 매칭: 'credentials' in '/tmp/poc-cases/credentialsmgr/app.py' → True (bug).
        path component 단위 매칭: 'credentialsmgr' not in _SECRET_NAMES → 허용 (correct).
        """
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-cases/credentialsmgr/app.py")
        assert result is not None, "credentialsmgr should not be blocked (no false positive)"

    def test_shadow_file_denied(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """/tmp/poc-cases/etc/shadow — shadow 는 SECRET_NAMES 에 포함."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-cases/etc/shadow")
        assert result is None, "shadow must be denied"

    def test_key_suffix_denied(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """/tmp/poc-cases/server.key — .key suffix 거부."""
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "poc")
        monkeypatch.setenv("MACRO_LOGBOT_POC_WORKSPACE_ALLOWED", "/tmp/poc-cases")
        result = _safe_resolve("/tmp/poc-cases/server.key")
        assert result is None, ".key suffix must be denied"


# ---------------------------------------------------------------------------
# WARN-MED: invalid MACRO_LOGBOT_ENV → RuntimeError
# ---------------------------------------------------------------------------


class TestEnvEnum:
    """MACRO_LOGBOT_ENV 유효값 외 입력 시 RuntimeError."""

    def test_invalid_env_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MACRO_LOGBOT_ENV", "INVALID_VALUE")
        with pytest.raises(RuntimeError, match="invalid MACRO_LOGBOT_ENV"):
            _safe_resolve("/tmp/poc-test/file.py")

    def test_valid_envs_do_not_raise(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        for valid_env in ("production", "staging", "poc", "dev"):
            monkeypatch.setenv("MACRO_LOGBOT_ENV", valid_env)
            # RuntimeError 가 발생하지 않으면 됨 (결과값은 무관).
            try:
                _safe_resolve("/tmp/some-path/file.py")
            except RuntimeError:
                pytest.fail(f"RuntimeError raised for valid env={valid_env!r}")
