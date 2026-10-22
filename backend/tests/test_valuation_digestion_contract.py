"""Offline execution of embedded valuation examples and production boundaries.

Only function definitions are extracted: live demonstration calls never execute.
HTTP and forecast inputs are synthetic; production source/unit contracts remain
covered by their existing dedicated suites.
"""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

import astock


SKILL = Path(__file__).resolve().parents[2] / "a-stock-data" / "SKILL.md"


def example_blocks():
    return [part.split("```", 1)[0] for part in SKILL.read_text(encoding="utf-8").split("```python\n")[1:]]


def example_namespace():
    namespace = {"math": math, "pd": pd}
    for name in ("pe_digestion", "full_valuation"):
        block = next(block for block in example_blocks() if f"def {name}(" in block)
        function = next(node for node in ast.parse(block).body if isinstance(node, ast.FunctionDef) and node.name == name)
        exec(compile(ast.Module(body=[function], type_ignores=[]), f"embedded-{name}", "exec"), namespace)
    return namespace


def example_valuation(price, eps_cur, eps_next):
    namespace = example_namespace()
    values = [""] * 47
    values[1], values[3], values[39], values[45], values[46] = "synthetic", str(price), "40", "10", "2"
    response = Mock()
    response.read.return_value = ('v="' + "~".join(values) + '";').encode("gbk")
    namespace["urllib"] = SimpleNamespace(request=SimpleNamespace(Request=Mock(), urlopen=Mock(return_value=response)))
    namespace["ths_eps_forecast"] = lambda _: pd.DataFrame([
        {"年度": "2026", "均值": eps_cur, "预测机构数": 3},
        {"年度": "2027", "均值": eps_next, "预测机构数": 3},
    ])
    return namespace["full_valuation"]("000001")


def production_valuation(price, eps_cur, eps_next):
    rows = [{"年度": "2026", "均值": eps_cur}, {"年度": "2027", "均值": eps_next}]
    with patch.object(astock, "tencent_quote", return_value={"000001": {"name": "synthetic", "price": price}}), \
         patch.object(astock, "profit_forecast", return_value=rows):
        return astock.full_valuation("000001", valuation_reader=lambda _: {})


class ValuationDigestionContract(unittest.TestCase):
    def test_boundaries_match_example_and_production(self):
        for price, current, following, expected in [
            (60, 1, 1, None), (60, 1, 0.8, None),
            (30, 1, 1, 0.0), (20, 1, 0.8, 0.0), (60, 1, 2, 1.0),
            (60, None, None, None), (20, 1, None, None),
            (60, -1, -2, None), (60, 0, 1, None), (60, 1, 0, None),
            (60, 1, -1, None), (60, None, 2, None),
            (20, 1, -1, None), (30, 1, -1, None),
            (20, 1, 0, None), (30, 1, 0, None), (30, 1, 0.8, 0.0),
        ]:
            with self.subTest(price=price, current=current, following=following):
                for compute in (example_valuation, production_valuation):
                    actual = compute(price, current, following)
                    self.assertEqual(actual["digest_years"], expected)
                    json.dumps(actual, allow_nan=False)

    def test_loss_and_zero_next_eps_preserve_observation_not_estimates(self):
        for following in (-1, 0):
            for price in (20, 30, 60):
                for compute, key in ((example_valuation, "eps_next"), (production_valuation, "eps_27e")):
                    with self.subTest(compute=compute.__name__, following=following, price=price):
                        result = compute(price, 1, following)
                        self.assertEqual(result[key], following)
                        self.assertEqual(result["cagr_pct"], (following - 1) * 100)
                        self.assertIsNone(result["peg"])
                        self.assertIsNone(result["digest_years"])

    def test_nonfinite_forecasts_are_missing_not_zero_years(self):
        for invalid in (float("nan"), float("inf"), float("-inf")):
            for current, following in ((invalid, 1), (1, invalid), (invalid, invalid)):
                for compute, keys in ((example_valuation, ("eps_cur", "eps_next")),
                                      (production_valuation, ("eps_26e", "eps_27e"))):
                    with self.subTest(compute=compute.__name__, current=current, following=following):
                        result = compute(60, current, following)
                        self.assertIsNone(result["digest_years"])
                        for value, key in zip((current, following), keys):
                            self.assertEqual(result[key], value if math.isfinite(value) else None)
                        json.dumps(result, allow_nan=False)

    def test_extreme_finite_forecasts_do_not_overflow_json_or_raise(self):
        for current, following in ((1e-308, 1), (1, 1e308), (1e-308, 1e308), (1e308, 1e-308)):
            for compute in (example_valuation, production_valuation):
                with self.subTest(compute=compute.__name__, current=current, following=following):
                    json.dumps(compute(60, current, following), allow_nan=False)

    def test_helper_invalid_pe_and_growth_are_not_zero_years(self):
        for helper in (example_namespace()["pe_digestion"], astock.pe_digestion):
            for pe, growth, target in ((-30, 1, 30), (0, 1, 30), (float("nan"), 1, 30),
                                       (float("inf"), 1, 30), (20, float("nan"), 30),
                                       (20, float("inf"), 30), (60, 1, 0)):
                with self.subTest(pe=pe, growth=growth, target=target):
                    self.assertTrue(math.isinf(helper(pe, growth, target)))
            self.assertTrue(math.isfinite(helper(60, 1e-16)))
            self.assertTrue(math.isfinite(helper(1e308, 1, 1e-308)))

    def test_batch_display_distinguishes_zero_missing_and_unestimable(self):
        block = next(block for block in example_blocks() if 'stocks = ["688017"' in block)
        for result, expected in ((example_valuation(30, 1, 1), "消化=0.0年"),
                                 (example_valuation(60, 1, 1), "消化=无法估算"),
                                 (example_valuation(60, None, None), "消化=缺少输入")):
            with self.subTest(expected=expected):
                output = io.StringIO()
                with redirect_stdout(output):
                    exec(compile(block, "embedded-batch-valuation", "exec"), {"full_valuation": lambda _: result})
                self.assertIn(expected, output.getvalue())
                self.assertNotIn("None年", output.getvalue())
                self.assertNotIn("nan年", output.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
