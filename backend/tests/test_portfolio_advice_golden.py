"""portfolio_advice Golden Tests——行为锁定套件。

每个场景由 gen_fixtures.py 预先录制（input.json + expected.json），
本文件只做回放比对：输入 → validate_portfolio_advice → 与快照完全相等。

重构时，只要 validator 行为不变，这 27 个用例永远通过。
若某个用例失败，说明重构改变了产品行为——必须先修正再提交。

运行：
    cd backend
    .venv/Scripts/python -m pytest tests/test_portfolio_advice_golden.py -vv
"""
from __future__ import annotations

import json
import pathlib

import pytest

from portfolio_advice_validator import validate_portfolio_advice

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures" / "portfolio_advice"

# 自动发现所有场景（按前缀 s01_ … s27_ 排序）
_SCENARIOS = sorted(
    p.stem.replace("_input", "")
    for p in FIXTURE_DIR.glob("*_input.json")
)

assert len(_SCENARIOS) == 27, f"Expected 27 scenarios, found {len(_SCENARIOS)}: {_SCENARIOS}"


def _load(scenario_id: str) -> tuple[dict, dict, dict]:
    """返回 (ai_result, context, expected_output)。"""
    inp_path = FIXTURE_DIR / f"{scenario_id}_input.json"
    exp_path = FIXTURE_DIR / f"{scenario_id}_expected.json"
    data = json.loads(inp_path.read_text(encoding="utf-8"))
    expected = json.loads(exp_path.read_text(encoding="utf-8"))
    return data["ai_result"], data["context"], expected


@pytest.mark.parametrize("scenario_id", _SCENARIOS)
def test_golden(scenario_id: str) -> None:
    """回放 validate_portfolio_advice 并与快照精确比对。"""
    ai_result, context, expected = _load(scenario_id)
    actual = validate_portfolio_advice(ai_result, context)
    assert actual == expected, (
        f"Golden test failed for scenario: {scenario_id}\n"
        f"ACTUAL keys: {list(actual.keys())}\n"
        f"EXPECTED keys: {list(expected.keys())}"
    )
