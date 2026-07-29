"""Unit tests for portfolio_advice_trace_adapter normalization."""

from __future__ import annotations

import math

import portfolio_advice_trace_adapter as adapter


def test_execution_size_to_target_ratio_matrix():
    assert adapter.execution_size_to_target_ratio(30) == 0.30
    assert adapter.execution_size_to_target_ratio(0) == 0.0
    assert adapter.execution_size_to_target_ratio(100) == 1.0
    assert adapter.execution_size_to_target_ratio(10) == 0.10
    assert adapter.execution_size_to_target_ratio(None) is None
    assert adapter.execution_size_to_target_ratio(True) is None
    assert adapter.execution_size_to_target_ratio(False) is None
    assert adapter.execution_size_to_target_ratio(float("nan")) is None
    assert adapter.execution_size_to_target_ratio(float("inf")) is None
    assert adapter.execution_size_to_target_ratio(-10) is None
    assert adapter.execution_size_to_target_ratio(101) is None
    assert adapter.execution_size_to_target_ratio("30") == 0.30
    assert adapter.execution_size_to_target_ratio("x") is None
    assert adapter.execution_size_to_target_ratio({"a": 1}) is None
    assert adapter.execution_size_to_target_ratio([30]) is None


def test_summarize_holding_reason_strings_only():
    holding = {
        "execution_plan": ["分批减仓", {"x": 1}, "分批减仓"],
        "trigger_conditions": [0, False, "估值偏高"],
        "risk_conditions": ["回撤扩大则停止", "第三"],
        "invalidation_conditions": ["不会被取到"],
        "data_limitations": ["也不会"],
    }
    reason = adapter.summarize_holding_reason(holding)
    assert "分批减仓" in reason
    assert "估值偏高" in reason
    assert "回撤扩大则停止" in reason
    assert "{'x': 1}" not in reason
    assert "False" not in reason
    assert reason.count("；") == 2  # three parts


def test_summarize_holding_reason_fallback():
    assert adapter.summarize_holding_reason({}) == adapter.REASON_FALLBACK
    assert adapter.summarize_holding_reason({"execution_plan": [{"a": 1}]}) == adapter.REASON_FALLBACK


def test_constraint_state_evaluated_not_applied():
    advice = {
        "account_funding": {"configured": True, "quote_coverage": {"complete": True}},
        "holdings": [
            {
                "code": "000001",
                "action": "add",
                "execution_size_pct_of_holding": 20,
                "execution_quantity": None,
            },
            {
                "code": "600519",
                "action": "reduce",
                "execution_size_pct_of_holding": 30,
                "execution_quantity": 100,
                "sellable_quantity_advisory": 100,
            },
        ],
    }
    state = adapter.extract_constraint_state(advice)
    assert state["account_funding_available"] is True
    assert state["account_funding_configured"] is True
    assert state["cash_constraint_evaluated"] is True
    assert state["sellable_quantity_evaluated"] is True
    assert state["constrained_add_count"] == 1
    assert state["sellable_advisory_count"] == 1
    assert adapter.holding_is_cash_constrained(advice["holdings"][0]) is True
    assert adapter.holding_is_cash_constrained(advice["holdings"][1]) is False


def test_resolve_advice_schema_version():
    assert adapter.resolve_advice_schema_version({}) == "portfolio-advice-v0.1"
    assert (
        adapter.resolve_advice_schema_version({"schema_version": "portfolio-advice-v0.1"})
        == "portfolio-advice-v0.1"
    )
