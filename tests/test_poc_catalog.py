"""PoC error catalog 스키마 검증 — 10 case yaml 로드 + ground_truth 필드 확인.

task-POC-002: E006~E010 추가 후 전체 10 케이스가 올바른 schema 를 갖추는지.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "poc" / "error_catalog"

REQUIRED_GROUND_TRUTH_FIELDS = {"root_cause", "location", "fix_hint", "expected_tool_calls"}
REQUIRED_LOCATION_FIELDS = {"file", "function", "line"}
REQUIRED_TOP_FIELDS = {
    "id",
    "title",
    "category",
    "target_file",
    "target_function",
    "injection_diff",
    "trigger",
    "ground_truth",
}


def _all_case_ids() -> list[str]:
    return sorted(p.stem for p in CATALOG_DIR.glob("E*.yaml"))


@pytest.mark.parametrize("case_id", _all_case_ids())
def test_catalog_yaml_loads(case_id: str) -> None:
    """각 yaml 이 safe_load 로 파싱 가능한지."""
    path = CATALOG_DIR / f"{case_id}.yaml"
    with path.open(encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    assert isinstance(data, dict), f"{case_id}: yaml root must be a dict"


@pytest.mark.parametrize("case_id", _all_case_ids())
def test_catalog_top_level_fields(case_id: str) -> None:
    """각 case 의 최상위 필드가 schema 를 만족하는지."""
    path = CATALOG_DIR / f"{case_id}.yaml"
    with path.open(encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    missing = REQUIRED_TOP_FIELDS - set(data.keys())
    assert not missing, f"{case_id}: missing top-level fields: {missing}"


@pytest.mark.parametrize("case_id", _all_case_ids())
def test_catalog_ground_truth_fields(case_id: str) -> None:
    """ground_truth 블록에 root_cause / location / fix_hint / expected_tool_calls 존재."""
    path = CATALOG_DIR / f"{case_id}.yaml"
    with path.open(encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    gt = data.get("ground_truth", {})
    assert isinstance(gt, dict), f"{case_id}: ground_truth must be a dict"
    missing = REQUIRED_GROUND_TRUTH_FIELDS - set(gt.keys())
    assert not missing, f"{case_id}: missing ground_truth fields: {missing}"


@pytest.mark.parametrize("case_id", _all_case_ids())
def test_catalog_location_fields(case_id: str) -> None:
    """ground_truth.location 에 file / function / line 존재."""
    path = CATALOG_DIR / f"{case_id}.yaml"
    with path.open(encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    loc = data["ground_truth"].get("location", {})
    assert isinstance(loc, dict), f"{case_id}: location must be a dict"
    missing = REQUIRED_LOCATION_FIELDS - set(loc.keys())
    assert not missing, f"{case_id}: missing location fields: {missing}"


@pytest.mark.parametrize("case_id", _all_case_ids())
def test_catalog_expected_tool_calls_nonempty(case_id: str) -> None:
    """expected_tool_calls 가 비어있지 않은 list 인지."""
    path = CATALOG_DIR / f"{case_id}.yaml"
    with path.open(encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    tool_calls = data["ground_truth"].get("expected_tool_calls", [])
    assert isinstance(tool_calls, list), f"{case_id}: expected_tool_calls must be a list"
    assert len(tool_calls) >= 1, f"{case_id}: expected_tool_calls must not be empty"


def test_total_case_count() -> None:
    """카탈로그에 정확히 10 개 케이스 (E001~E010) 있는지."""
    cases = _all_case_ids()
    assert len(cases) == 10, f"expected 10 cases, got {len(cases)}: {cases}"


def test_case_ids_sequential() -> None:
    """E001 ~ E010 순서가 연속적인지 (누락 없음)."""
    cases = _all_case_ids()
    expected = [f"E{i:03d}" for i in range(1, 11)]
    assert cases == expected, f"expected {expected}, got {cases}"
