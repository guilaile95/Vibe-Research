from __future__ import annotations

import pytest

import portfolio_risk_context as context


FIXED_TIME = "2026-09-09T00:00:00Z"


def _portfolio(*market_values: float | None, authority: str = "CANONICAL") -> dict:
    return {
        "authority_state": authority,
        "holdings": [
            {
                "code": f"60000{index}",
                "name": f"股票{index}",
                "shares": 100,
                "market_value": value,
            }
            for index, value in enumerate(market_values, start=1)
        ],
    }


def _fact(value, *, state: str = "CANONICAL", confirmation_id: str | None = "c1", status: str = "AVAILABLE") -> dict:
    return {
        "value": value,
        "authority_state": state,
        "confirmation_id": confirmation_id,
        "status": status,
    }


def _account(*, total=1000, cash=200, total_state="CANONICAL", cash_state="CANONICAL", total_confirmation="c1", cash_confirmation="c1") -> dict:
    return {
        "canonical": False,
        "account_total_assets": {"current_fact": _fact(total, state=total_state, confirmation_id=total_confirmation)},
        "cash": {"current_fact": _fact(cash, state=cash_state, confirmation_id=cash_confirmation)},
        "settled_nav": 1200,
        "nav_authority": "SETTLED_NAV_CANDIDATE",
        "nav_canonical": False,
    }


def _build(portfolio, account=None, industries=None, industry_reader=None):
    return context.build_portfolio_risk_context(
        portfolio_reader=lambda: portfolio,
        account_reader=lambda: _account() if account is None else account,
        industry_reader=industry_reader or (lambda: {} if industries is None else industries),
        fetched_at=FIXED_TIME,
    )


def test_complete_quote_coverage_and_deterministic_top_concentration():
    result = _build(_portfolio(500, 300, 200), industries={"600001": "电子", "600002": "医药", "600003": "银行"})
    concentration = result["security_concentration"]
    assert result["quote_coverage"] == {
        "status": "COMPLETE",
        "usable_holdings": 3,
        "total_holdings": 3,
        "complete": True,
        "usable_market_value": 1000.0,
        "source": "CURRENT_PORTFOLIO_QUOTE_COVERAGE",
    }
    assert concentration["status"] == "COMPLETE"
    assert concentration["top1_pct"] == 50.0
    assert concentration["top3_pct"] == 100.0
    assert concentration["top5_pct"] == 100.0
    assert [item["code"] for item in concentration["holdings_ranked"]] == ["600001", "600002", "600003"]


def test_partial_quote_never_renormalizes_known_holdings():
    result = _build(_portfolio(600, None, 400), industries={"600001": "电子", "600003": "医药"})
    assert result["quote_coverage"]["status"] == "PARTIAL"
    assert result["security_concentration"]["status"] == "PARTIAL"
    assert result["security_concentration"]["reason_code"] == "NOT_FULLY_EVALUABLE"
    assert result["security_concentration"]["top1_pct"] is None
    assert all(item["weight_in_tracked_stock_pct"] is None for item in result["securities"])
    assert result["industry_exposure"]["status"] == "PARTIAL"
    assert sum(item["weight_in_tracked_stock_pct"] or 0 for item in result["industry_exposure"]["items"]) == 100.0


def test_no_holdings_is_empty_capability_state_not_unavailable():
    result = _build(_portfolio(), industries={})
    assert result["status"] == "NORMAL"
    assert result["holding_count"] == 0
    assert result["position_context"]["status"] == "NORMAL"
    assert result["quote_coverage"]["status"] == "EMPTY"
    assert result["security_concentration"]["reason_code"] == "NO_ACTIVE_HOLDINGS"
    assert result["industry_exposure"]["status"] == "EMPTY"


def test_one_holding_uses_actual_quantity_for_top3_and_top5():
    result = _build(_portfolio(250), industries={"600001": "电子"})
    assert result["security_concentration"]["top1_pct"] == 100.0
    assert result["security_concentration"]["top3_pct"] == 100.0
    assert result["security_concentration"]["top5_pct"] == 100.0


def test_zero_market_value_is_a_valid_zero_not_null():
    result = _build(_portfolio(0), industries={"600001": "电子"})
    security = result["securities"][0]
    assert security["market_value"] == 0.0
    assert security["quote_status"] == "AVAILABLE"
    assert result["quote_coverage"]["status"] == "COMPLETE"
    assert result["security_concentration"]["reason_code"] == "ZERO_TRACKED_MARKET_VALUE"
    assert result["industry_exposure"]["items"][0]["market_value"] == 0.0


def test_null_market_value_is_unavailable_and_distinct_from_zero():
    result = _build(_portfolio(None), industries={})
    assert result["securities"][0]["market_value"] is None
    assert result["securities"][0]["quote_status"] == "UNAVAILABLE"
    assert result["quote_coverage"]["status"] == "UNAVAILABLE"


def test_canonical_total_assets_exposes_account_denominator():
    result = _build(_portfolio(250), account=_account(total=1000, cash=200))
    assert result["account_fact_status"]["total_assets"]["status"] == "CANONICAL"
    assert result["account_exposure"]["status"] == "AVAILABLE"
    assert result["account_exposure"]["tracked_stock_account_pct"] == 25.0
    assert result["securities"][0]["account_exposure_pct"] == 25.0
    assert result["account_exposure"]["denominator"]["semantics"] == "CURRENT_MIXED_TIME_NOT_OFFICIAL_SETTLED_NAV"


def test_noncanonical_total_assets_blocks_account_denominator_but_keeps_concentration():
    result = _build(_portfolio(250), account=_account(total=1000, total_state="UNPROVEN"), industries={"600001": "电子"})
    assert result["security_concentration"]["status"] == "COMPLETE"
    assert result["account_exposure"]["status"] == "UNAVAILABLE"
    assert result["account_exposure"]["tracked_stock_account_pct"] is None
    assert result["cash_buffer"]["status"] == "UNAVAILABLE"


def test_cash_buffer_requires_same_confirmation_current_facts():
    result = _build(_portfolio(), account=_account(total_confirmation="same", cash_confirmation="same"))
    assert result["cash_buffer"]["status"] == "AVAILABLE"
    assert result["cash_buffer"]["ratio_pct"] == 20.0


def test_cash_confirmation_mismatch_is_unavailable():
    result = _build(_portfolio(), account=_account(cash_confirmation="other"))
    assert result["cash_buffer"]["status"] == "UNAVAILABLE"
    assert result["cash_buffer"]["ratio_pct"] is None
    assert result["status"] == "PARTIAL"


def test_cash_zero_is_available_zero_ratio():
    result = _build(_portfolio(), account=_account(cash=0))
    assert result["cash_buffer"]["status"] == "AVAILABLE"
    assert result["cash_buffer"]["value"] == 0.0
    assert result["cash_buffer"]["ratio_pct"] == 0.0


def test_current_industry_exposure_has_provider_and_membership_semantics():
    result = _build(_portfolio(600, 400), industries={"600001": "电子", "600002": "医药"})
    assert result["industry_exposure"]["status"] == "AVAILABLE"
    assert result["industry_exposure"]["provider"] == "EASTMONEY_INDUSTRY_CURRENT"
    assert result["industry_exposure"]["membership_semantics"] == "CURRENT_MEMBERSHIP_SNAPSHOT"
    assert {item["industry"] for item in result["industry_exposure"]["items"]} == {"电子", "医药"}


def test_industry_partial_quote_keeps_tracked_denominator():
    result = _build(_portfolio(600, None, 400), industries={"600001": "电子", "600003": "医药"})
    assert result["industry_coverage"]["quote_usable_holdings"] == 2
    assert result["industry_coverage"]["coverage_ratio"] == 1.0
    assert sum(item["weight_in_tracked_stock_pct"] for item in result["industry_exposure"]["items"]) == 100.0
    assert result["industry_exposure"]["denominator_market_value"] == 1000.0


def test_missing_industry_uses_unknown_bucket_without_renormalization():
    result = _build(_portfolio(600, 400), industries={"600001": "电子"})
    assert result["industry_coverage"]["industry_classified_holdings"] == 1
    assert result["industry_coverage"]["unknown_industry_holdings"] == 1
    assert result["industry_coverage"]["coverage_ratio"] == 0.5
    unknown = next(item for item in result["industry_exposure"]["items"] if item["industry"] == "UNKNOWN_INDUSTRY")
    assert unknown["weight_in_tracked_stock_pct"] == 40.0


def test_industry_provider_failure_does_not_erase_other_sections():
    def broken():
        raise RuntimeError("provider fixture")

    result = _build(_portfolio(600, 400), industry_reader=broken)
    assert result["status"] == "PARTIAL"
    assert result["industry_exposure"]["status"] == "UNAVAILABLE"
    assert result["security_concentration"]["top1_pct"] == 60.0
    assert result["cash_buffer"]["ratio_pct"] == 20.0


def test_account_failure_does_not_erase_concentration_or_industry():
    result = _build(
        _portfolio(600, 400),
        account={"account_total_assets": None, "cash": None},
        industries={"600001": "电子", "600002": "医药"},
    )
    assert result["account_exposure"]["status"] == "UNAVAILABLE"
    assert result["security_concentration"]["top1_pct"] == 60.0
    assert result["industry_exposure"]["status"] == "AVAILABLE"


def test_account_reader_exception_is_isolated():
    def broken():
        raise RuntimeError("account fixture")

    result = context.build_portfolio_risk_context(
        portfolio_reader=lambda: _portfolio(600, 400),
        account_reader=broken,
        industry_reader=lambda: {"600001": "电子", "600002": "医药"},
        fetched_at=FIXED_TIME,
    )
    assert result["account_fact_status"]["status"] == "UNAVAILABLE"
    assert result["security_concentration"]["top1_pct"] == 60.0


def test_position_failure_is_fail_closed_without_partial_fake_holdings():
    def broken():
        raise RuntimeError("position fixture")

    result = context.build_portfolio_risk_context(
        portfolio_reader=broken,
        account_reader=lambda: _account(),
        industry_reader=lambda: {"600001": "电子"},
        fetched_at=FIXED_TIME,
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["holding_count"] == 0
    assert result["writes"] == {"formal_state": 0, "account": 0, "position": 0, "trade": 0, "portfolio": 0}


def test_pre_entry_risk_policy_is_reused_without_portfolio_aggregation():
    result = _build(_portfolio(100))
    capability = result["single_trade_risk_budget_capability"]
    assert capability["status"] == "IMPLEMENTED_IN_PRE_ENTRY_CANDIDATE_FLOW"
    assert capability["rates_pct"] == {"SHORT": 0.75, "SWING": 1.0, "MEDIUM": 1.25}
    assert result["portfolio_aggregated_risk_budget"]["status"] == "NOT_EVALUATED"


def test_drawdown_is_always_blocked_without_official_nav_history():
    result = _build(_portfolio(100))
    assert result["drawdown"]["status"] == "UNAVAILABLE_NO_OFFICIAL_NAV_HISTORY"
    assert result["drawdown"]["nav_canonical"] is False
    assert "正式 NAV 历史" in result["drawdown"]["message"]


def test_stress_test_is_deferred_without_scenario_contract():
    result = _build(_portfolio(100))
    assert result["stress_test"]["status"] == "DEFERRED_NO_ACCEPTED_SCENARIO_CONTRACT"
    assert "压力情景" in result["stress_test"]["message"]


def test_no_score_or_recommendation_is_created():
    result = _build(_portfolio(100))
    assert "risk_score" not in result
    assert "recommendation" not in result
    assert result["portfolio_aggregated_risk_budget"]["status"] == "NOT_EVALUATED"


def test_legacy_position_authority_is_reported_without_new_authority():
    result = _build(_portfolio(100, authority="LEGACY"))
    assert result["position_context"]["authority_state"] == "LEGACY"
    assert result["position_context"]["source"] == "POSITION_REALITY_AND_CURRENT_PORTFOLIO"


@pytest.mark.parametrize("field", ["formal_state", "account", "position", "trade", "portfolio"])
def test_writes_are_zero_for_every_mutation_boundary(field: str):
    result = _build(_portfolio(100))
    assert result["writes"][field] == 0
