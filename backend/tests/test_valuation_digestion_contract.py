"""Offline boundary parity for the embedded example and production valuation.

The vendored a-stock-data example keeps its upstream attribution; this test
executes its actual digestion expression, without HTTP, pandas or providers.
"""
from __future__ import annotations

import ast
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import astock


def example_digest(price, eps_cur, eps_next):
    skill = (Path(__file__).resolve().parents[2] / "a-stock-data" / "SKILL.md").read_text()
    blocks = [part.split("```", 1)[0] for part in skill.split("```python\n")[1:]]
    helper = next(ast.parse(block) for block in blocks if "def pe_digestion(" in block)
    example = next(ast.parse(block) for block in blocks if "def full_valuation(" in block)
    function = next(node for node in example.body if isinstance(node, ast.FunctionDef) and node.name == "full_valuation")
    selected = [node for node in function.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id in {"pe_fwd", "cagr", "digest"} for target in node.targets)]
    result = next(node.value for node in function.body if isinstance(node, ast.Return))
    expression = next(value for key, value in zip(result.keys, result.values) if isinstance(key, ast.Constant) and key.value == "digest_years")
    namespace = {"math": math, "price": price, "eps_cur": eps_cur, "eps_next": eps_next}
    exec(compile(helper, "embedded-pe-digestion", "exec"), namespace)
    exec(compile(ast.Module(body=selected, type_ignores=[]), "embedded-full-valuation", "exec"), namespace)
    return eval(compile(ast.Expression(expression), "embedded-digest-json", "eval"), namespace)


class ValuationDigestionContract(unittest.TestCase):
    def test_boundaries_match_example_and_production(self):
        for price, current, following, expected in [
            (60, 1, 1, None),        # Above target, zero growth is not zero years.
            (60, 1, 0.8, None),      # Above target, declining earnings cannot digest PE.
            (30, 1, 1, 0.0),        # At target, no wait required even without growth.
            (20, 1, 0.8, 0.0),      # Below target, declining earnings still starts below target.
            (60, 1, 2, 1.0),        # Positive growth has a finite horizon.
            (60, None, None, None), # Missing forecasts must not invent zero years.
        ]:
            with self.subTest(price=price, current=current, following=following):
                rows = [] if current is None else [
                    {"年度": "2026", "均值": current}, {"年度": "2027", "均值": following},
                ]
                with patch.object(astock, "tencent_quote", return_value={"000001": {"name": "测试", "price": price}}), \
                     patch.object(astock, "profit_forecast", return_value=rows):
                    actual = astock.full_valuation("000001", valuation_reader=lambda _: {})["digest_years"]
                self.assertEqual(actual, expected)
                self.assertEqual(example_digest(price, current, following), expected)
                self.assertEqual(json.loads(json.dumps({"digest_years": actual}, allow_nan=False))["digest_years"], expected)


if __name__ == "__main__":
    unittest.main()
