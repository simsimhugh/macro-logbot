"""PoC inject.py 단위 테스트.

inject.apply_diff 가 unified diff 를 context-매칭으로 잘 적용하는지 +
모든 catalog yaml 이 snake.py 에 깨끗하게 적용되는지 검증.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "poc" / "scripts" / "inject.py"
CATALOG_DIR = REPO_ROOT / "poc" / "error_catalog"
SNAKE_ORIGINAL = REPO_ROOT / "poc" / "targets" / "snake-game" / "original" / "snake.py"

# poc/scripts 는 package 가 아니라 script — 동적 import.
_spec = importlib.util.spec_from_file_location("poc_inject", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
inject_mod = importlib.util.module_from_spec(_spec)
sys.modules["poc_inject"] = inject_mod
_spec.loader.exec_module(inject_mod)


def test_parse_hunks_extracts_before_after() -> None:
    diff = (
        "--- a/snake.py\n"
        "+++ b/snake.py\n"
        "@@ -1,3 +1,3 @@\n"
        " context_a\n"
        "-old_line\n"
        "+new_line\n"
        " context_b\n"
    )
    hunks = inject_mod._parse_hunks(diff)
    assert len(hunks) == 1
    before, after = hunks[0]
    assert before == "context_a\nold_line\ncontext_b"
    assert after == "context_a\nnew_line\ncontext_b"


def test_inject_E001_changes_init_game(tmp_path: Path) -> None:
    inject_mod.inject("E001", tmp_path)
    text = (tmp_path / "snake.py").read_text(encoding="utf-8")
    # E001 은 init_game 의 self.head 를 None 으로 바꾼다.
    assert "self.head = None" in text
    # 본래의 Segment(GRID_WIDTH // 2, GRID_HEIGHT // 2) 라인은 제거되어야 한다.
    assert "Segment(GRID_WIDTH // 2, GRID_HEIGHT // 2)" not in text
    # case.yaml 사본 생성 확인.
    assert (tmp_path / "case.yaml").is_file()


def test_inject_unknown_case_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        inject_mod.inject("E999", tmp_path)


def test_repo_root_env_override(tmp_path: Path) -> None:
    """MACRO_LOGBOT_POC_ROOT env 로 REPO_ROOT 를 override 할 수 있음."""
    import importlib
    import importlib.util
    import os
    import sys

    env_before = os.environ.get("MACRO_LOGBOT_POC_ROOT")
    try:
        os.environ["MACRO_LOGBOT_POC_ROOT"] = str(tmp_path)
        # 모듈을 새로 로드해서 REPO_ROOT 재계산 확인.
        spec = importlib.util.spec_from_file_location("poc_inject_env", SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.REPO_ROOT == tmp_path.resolve()
    finally:
        if env_before is None:
            os.environ.pop("MACRO_LOGBOT_POC_ROOT", None)
        else:
            os.environ["MACRO_LOGBOT_POC_ROOT"] = env_before


def test_all_catalog_cases_apply_cleanly(tmp_path: Path) -> None:
    """모든 catalog yaml 이 snake.py original 에 깨끗하게 patch 되는지."""
    cases = sorted(p.stem for p in CATALOG_DIR.glob("E*.yaml"))
    assert len(cases) >= 5, f"expected >=5 cases, got {cases}"
    for case_id in cases:
        sub = tmp_path / case_id
        sub.mkdir()
        # 실패 시 RuntimeError 가 위로 — pytest 가 자동으로 fail 표시.
        inject_mod.inject(case_id, sub)
        # 결과가 원본과 다른지 (실제로 뭔가 바뀌었는지) 확인.
        injected = (sub / "snake.py").read_text(encoding="utf-8")
        original = SNAKE_ORIGINAL.read_text(encoding="utf-8")
        assert injected != original, f"{case_id}: patch applied but no diff"


def test_inject_files_are_world_readable(tmp_path: Path) -> None:
    """PR #52 regression — inject 후 snake.py / case.yaml 의 mode == 0o644.

    backend container 의 uid (예: macrologbot uid=10001) 가 host 의 evaluator uid
    (예: hugh uid=1000) 가 만든 파일을 read 할 수 있어야 함.
    """
    inject_mod.inject("E001", tmp_path)
    snake_mode = (tmp_path / "snake.py").stat().st_mode & 0o777
    yaml_mode = (tmp_path / "case.yaml").stat().st_mode & 0o777
    assert snake_mode == 0o644, f"snake.py mode {oct(snake_mode)} != 0o644"
    assert yaml_mode == 0o644, f"case.yaml mode {oct(yaml_mode)} != 0o644"
