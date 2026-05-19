"""PoC trigger.py 단위 테스트.

original snake.py 의 정상 동작 + 각 catalog case injection 후 실제 에러 발생 검증.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INJECT_PATH = REPO_ROOT / "poc" / "scripts" / "inject.py"
TRIGGER_PATH = REPO_ROOT / "poc" / "scripts" / "trigger.py"
SNAKE_ORIGINAL = REPO_ROOT / "poc" / "targets" / "snake-game" / "original" / "snake.py"
CATALOG_DIR = REPO_ROOT / "poc" / "error_catalog"


def _load(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


inject_mod = _load("poc_inject_for_trigger", INJECT_PATH)
trigger_mod = _load("poc_trigger", TRIGGER_PATH)


def test_original_snake_runs_clean(tmp_path: Path) -> None:
    """주입 없는 원본은 --auto-play 2 에서 정상 종료 (rc=1: clean exit)."""
    shutil.copy2(SNAKE_ORIGINAL, tmp_path / "snake.py")
    exit_code, _stderr = trigger_mod.trigger(tmp_path, timeout=30)
    # trigger 의 exit_code 1 = "process exited cleanly (no injection error)".
    assert exit_code == 1


def test_all_injected_cases_raise(tmp_path: Path) -> None:
    """모든 catalog case 가 injection 후 traceback 발생 (trigger rc=0)."""
    cases = sorted(p.stem for p in CATALOG_DIR.glob("E*.yaml"))
    failures: list[str] = []
    for case_id in cases:
        sub = tmp_path / case_id
        sub.mkdir()
        inject_mod.inject(case_id, sub)
        exit_code, stderr = trigger_mod.trigger(sub, timeout=30)
        # trigger rc=0 = "process raised exception (good)".
        if exit_code != 0:
            failures.append(f"{case_id}: trigger rc={exit_code}, stderr={stderr[:200]}")
        elif "Traceback" not in stderr and "Error" not in stderr:
            failures.append(f"{case_id}: no traceback marker in stderr={stderr[:200]}")
    assert not failures, "\n".join(failures)
