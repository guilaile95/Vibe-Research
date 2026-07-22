"""portfolio_advice_contracts 公共契约层专项测试。

验证：
- 所有常量定义正确
- 类型正确（frozenset / tuple / dict / str / int / float）
- 常量不被意外修改（immutable 验证）
"""
from __future__ import annotations

import pytest

import portfolio_advice_contracts as contracts
import portfolio_advice_policy as policy


class TestSchemaVersion:
    def test_schema_version_value(self):
        assert contracts.SCHEMA_VERSION == "portfolio-advice-v0.1"

    def test_schema_version_is_str(self):
        assert isinstance(contracts.SCHEMA_VERSION, str)


class TestActions:
    def test_actions_count(self):
        assert len(contracts.ACTIONS) == 6

    def test_actions_contains_all_six(self):
        expected = {"add", "hold", "reduce", "sell", "watch", "avoid"}
        assert set(contracts.ACTIONS) == expected

    def test_actions_is_tuple(self):
        assert isinstance(contracts.ACTIONS, tuple)

    def test_actions_order(self):
        # 顺序稳定（为 prompt 输出契约所依赖）
        assert contracts.ACTIONS[0] == "add"
        assert contracts.ACTIONS[3] == "sell"


class TestAccountActions:
    def test_account_actions_count(self):
        assert len(contracts.ACCOUNT_ACTIONS) == 4

    def test_account_actions_contains_all_four(self):
        expected = {"hold", "reduce_risk", "selective_add", "defensive"}
        assert set(contracts.ACCOUNT_ACTIONS) == expected

    def test_account_actions_is_tuple(self):
        assert isinstance(contracts.ACCOUNT_ACTIONS, tuple)


class TestConfidenceLevels:
    def test_confidence_levels_count(self):
        assert len(contracts.CONFIDENCE_LEVELS) == 3

    def test_confidence_levels_values(self):
        assert contracts.CONFIDENCE_LEVELS == frozenset({"high", "medium", "low"})

    def test_confidence_levels_is_frozenset(self):
        assert isinstance(contracts.CONFIDENCE_LEVELS, frozenset)


class TestAddTiers:
    def test_add_tiers_values(self):
        assert policy.ADD_TIERS == frozenset({10.0, 20.0})

    def test_add_tiers_is_frozenset(self):
        assert isinstance(policy.ADD_TIERS, frozenset)

    def test_add_tiers_are_floats(self):
        for t in policy.ADD_TIERS:
            assert isinstance(t, float)


class TestReduceTiers:
    def test_reduce_tiers_values(self):
        assert policy.REDUCE_TIERS == frozenset({10.0, 20.0, 30.0})

    def test_reduce_tiers_is_frozenset(self):
        assert isinstance(policy.REDUCE_TIERS, frozenset)


class TestSellTier:
    def test_sell_tier_value(self):
        assert policy.SELL_TIER == 100.0

    def test_sell_tier_is_float(self):
        assert isinstance(policy.SELL_TIER, float)


class TestConfidenceCap:
    def test_confidence_cap_keys(self):
        assert set(policy.CONFIDENCE_CAP.keys()) == {"low", "medium", "high"}

    def test_confidence_cap_low(self):
        assert policy.CONFIDENCE_CAP["low"] == 10.0

    def test_confidence_cap_medium(self):
        assert policy.CONFIDENCE_CAP["medium"] == 20.0

    def test_confidence_cap_high(self):
        assert policy.CONFIDENCE_CAP["high"] == 30.0

    def test_confidence_cap_values_ascending(self):
        cap = policy.CONFIDENCE_CAP
        assert cap["low"] < cap["medium"] < cap["high"]


class TestPartialMarketLimits:
    def test_partial_add_max(self):
        assert policy.PARTIAL_MARKET_ADD_MAX == 10.0

    def test_partial_reduce_max(self):
        assert policy.PARTIAL_MARKET_REDUCE_MAX == 20.0

    def test_partial_add_max_within_add_tiers(self):
        assert policy.PARTIAL_MARKET_ADD_MAX in policy.ADD_TIERS

    def test_partial_reduce_max_within_reduce_tiers(self):
        assert policy.PARTIAL_MARKET_REDUCE_MAX in policy.REDUCE_TIERS


class TestLotSize:
    def test_lot_size_value(self):
        assert contracts.LOT_SIZE == 100

    def test_lot_size_is_int(self):
        assert isinstance(contracts.LOT_SIZE, int)


class TestReExportCompat:
    """验证 prompt.py 仍然 re-export 同样的值（向后兼容性）。"""

    def test_prompt_re_exports_schema_version(self):
        from portfolio_advice_prompt import SCHEMA_VERSION
        assert SCHEMA_VERSION == contracts.SCHEMA_VERSION

    def test_prompt_re_exports_actions(self):
        from portfolio_advice_prompt import ACTIONS
        assert set(ACTIONS) == set(contracts.ACTIONS)

    def test_prompt_re_exports_account_actions(self):
        from portfolio_advice_prompt import ACCOUNT_ACTIONS
        assert set(ACCOUNT_ACTIONS) == set(contracts.ACCOUNT_ACTIONS)

    def test_validator_imports_from_contracts_not_prompt(self):
        """验证 validator 不再直接导入 prompt（通过检查 validator 源码）。"""
        import pathlib
        validator_src = (
            pathlib.Path(__file__).parent.parent / "portfolio_advice_validator.py"
        ).read_text(encoding="utf-8")
        assert "from portfolio_advice_prompt import" not in validator_src, (
            "portfolio_advice_validator should not import from portfolio_advice_prompt"
        )

    def test_policy_imports_contracts(self):
        """验证 policy 只向下依赖中立 contracts。"""
        import pathlib
        policy_src = (
            pathlib.Path(__file__).parent.parent / "portfolio_advice_policy.py"
        ).read_text(encoding="utf-8")
        assert "from portfolio_advice_contracts import" in policy_src

    def test_contracts_do_not_import_policy(self):
        import pathlib
        contracts_src = (
            pathlib.Path(__file__).parent.parent / "portfolio_advice_contracts.py"
        ).read_text(encoding="utf-8")
        assert "from portfolio_advice_policy import" not in contracts_src
