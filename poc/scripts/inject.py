"""Inject an error from poc/error_catalog/<case>.yaml into a workdir copy of snake.py.

Spec ref: docs/process/04-PoC-운영가이드.md §5.1, docs/design/02-설계문서.md §10.4.

Usage:
    python poc/scripts/inject.py --case E001 --workdir /tmp/snake-E001

Side effects:
    1. Copies poc/targets/snake-game/original/snake.py to <workdir>/snake.py.
    2. Applies the yaml's injection_diff (unified diff) via `git apply --directory=<workdir>`.
    3. Writes <workdir>/case.yaml — a copy of the catalog entry for downstream reference.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any, cast

import yaml

# poc/scripts/inject.py → repo root 는 두 단계 위.
# MACRO_LOGBOT_POC_ROOT env 로 override 가능 (CI / 격리 테스트 환경 지원).
_ENV_ROOT = os.environ.get("MACRO_LOGBOT_POC_ROOT")
REPO_ROOT = Path(_ENV_ROOT).resolve() if _ENV_ROOT else Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "poc" / "error_catalog"
SNAKE_ORIGINAL = REPO_ROOT / "poc" / "targets" / "snake-game" / "original" / "snake.py"


def load_case(case_id: str) -> dict[str, Any]:
    """case_id (예: 'E001') 로 yaml 메타 로드. 실패 시 FileNotFoundError.

    case_id 는 alphanumeric + '_'/'-' 만 허용 — path traversal (`../`) 차단.
    """
    if not case_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"invalid case_id: {case_id!r}")
    path = CATALOG_DIR / f"{case_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"unknown case: {case_id} (expected {path})")
    with path.open(encoding="utf-8") as fp:
        return cast(dict[str, Any], yaml.safe_load(fp))


def _parse_hunks(diff_text: str) -> list[tuple[str, str]]:
    """unified diff 의 각 hunk 에서 (before_block, after_block) 추출.

    before_block 은 ' ' (context) + '-' (제거) 라인의 본문을, after_block 은
    ' ' + '+' (추가) 라인의 본문을 join 한 것. hunk header (@@) 의 라인 수
    카운트는 검사하지 않는다 (yaml 작성 편의 — context 로 매칭).
    """
    hunks: list[tuple[str, str]] = []
    cur_before: list[str] = []
    cur_after: list[str] = []
    in_hunk = False

    def flush() -> None:
        if cur_before or cur_after:
            hunks.append(("\n".join(cur_before), "\n".join(cur_after)))

    for raw_line in diff_text.splitlines():
        if raw_line.startswith(("---", "+++")):
            continue
        if raw_line.startswith("@@"):
            if in_hunk:
                flush()
                cur_before.clear()
                cur_after.clear()
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw_line.startswith("-"):
            cur_before.append(raw_line[1:])
        elif raw_line.startswith("+"):
            cur_after.append(raw_line[1:])
        elif raw_line.startswith(" "):
            cur_before.append(raw_line[1:])
            cur_after.append(raw_line[1:])
        # 다른 라인 (빈 줄, \ No newline 등) 무시.
    if in_hunk:
        flush()
    return hunks


def apply_diff(workdir: Path, diff_text: str) -> None:
    """unified diff 의 hunk 들을 workdir 안 snake.py 에 context-매칭으로 적용.

    구현: 각 hunk 의 before_block (context+제거 라인) 을 파일에서 찾아
    after_block (context+추가 라인) 으로 교체. 라인 번호는 무시 — yaml
    작성 시 카운트 오류 회피 + 결정론적 매칭.

    실패 (before_block 미발견 / 중복 매칭) 시 RuntimeError.
    """
    target = workdir / "snake.py"
    text = target.read_text(encoding="utf-8")
    for before, after in _parse_hunks(diff_text):
        if before == after:
            continue
        count = text.count(before)
        if count == 0:
            raise RuntimeError(
                f"hunk context not found in {target}:\n---\n{before}\n---"
            )
        if count > 1:
            raise RuntimeError(
                f"hunk context matches multiple times ({count}) — diff too ambiguous"
            )
        text = text.replace(before, after, 1)
    target.write_text(text, encoding="utf-8")


def inject(case_id: str, workdir: Path) -> dict[str, Any]:
    """case_id 의 injection_diff 를 workdir 의 snake.py 사본에 적용.

    Returns: case yaml dict (호출자가 ground_truth 등에 추가 접근).
    """
    case = load_case(case_id)
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SNAKE_ORIGINAL, workdir / "snake.py")
    diff = cast(str, case["injection_diff"])
    apply_diff(workdir, diff)
    # case meta 사본 — trigger/evaluate 가 yaml 을 다시 로드 안 해도 되게.
    case_meta_path = workdir / "case.yaml"
    with case_meta_path.open("w", encoding="utf-8") as fp:
        yaml.safe_dump(case, fp, allow_unicode=True, sort_keys=False)
    return case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inject error case into a workdir.")
    parser.add_argument("--case", required=True, help="case id (예: E001)")
    parser.add_argument("--workdir", required=True, help="대상 디렉토리")
    args = parser.parse_args(argv)
    workdir = Path(args.workdir).resolve()
    try:
        inject(args.case, workdir)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"patch apply failed: {exc}", file=sys.stderr)
        return 3
    print(f"injected {args.case} into {workdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
