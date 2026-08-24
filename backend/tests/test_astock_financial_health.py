from __future__ import annotations

import math

import astock


class _Frame:
    def __init__(self, rows):
        self.rows = rows
        self.empty = not rows

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


def _summary(period: str, **overrides):
    row = {
        "报告期": period,
        "营业总收入": "100亿",
        "营业总收入同比增长率": "8%",
        "净利润": "20亿",
        "净利润同比增长率": "10%",
        "扣非净利润": "19亿",
        "扣非净利润同比增长率": "9%",
        "基本每股收益": "2.0",
        "每股净资产": "12.0",
        "净资产收益率": "15%",
        "销售毛利率": "40%",
        "销售净利率": "20%",
        "每股经营现金流": "2.5",
        "流动比率": "1.8",
        "速动比率": "1.4",
        "产权比率": "0.5",
        "资产负债率": "33%",
    }
    row.update(overrides)
    return row


def _metrics(period: str, values: dict[str, object]):
    return [
        {"report_date": period, "metric_name": key, "value": value}
        for key, value in values.items()
    ]


class _Ak:
    def __init__(self, *, cash_period="2025-12-31", cash_error=False):
        self.cash_period = cash_period
        self.cash_error = cash_error

    def stock_financial_abstract_ths(self, **_kwargs):
        return _Frame([
            _summary("2025-09-30"),
            _summary("2025-12-31", **{"每股经营现金流": None}),
        ])

    def stock_financial_benefit_new_ths(self, **_kwargs):
        return _Frame(_metrics("2025-12-31", {
            "operating_income_total": "1000",
            "net_profit": "200",
            "parent_holder_net_profit": "190",
        }))

    def stock_financial_cash_new_ths(self, **_kwargs):
        if self.cash_error:
            raise RuntimeError("cash source down")
        return _Frame(_metrics(self.cash_period, {
            "act_cash_flow_net": "300",
            "pay_fixed_assets_etc_cash": "40",
        }))

    def stock_financial_debt_new_ths(self, **_kwargs):
        return _Frame(_metrics("2025-12-31", {
            "assets_total": "2000",
            "cash": "500",
            "accounts_receivable": "100",
            "total_debt": "800",
            "holder_equity_total": "1200",
        }))


def test_legacy_financial_consumers_do_not_pay_for_statement_enrichment(monkeypatch):
    source = _Ak()
    def fail(**_kwargs):
        raise AssertionError("statement enrichment should not run")
    source.stock_financial_benefit_new_ths = fail
    monkeypatch.setattr(astock, "_akshare", lambda: source)

    result = astock.financials("600519")

    assert result["period"] == "2025-12-31"
    assert "history" not in result


def test_financial_health_projects_exact_period_facts_and_preserves_time_semantics(monkeypatch):
    monkeypatch.setattr(astock, "_akshare", lambda: _Ak())

    result = astock.financials("600519", include_health=True)

    assert result["period"] == result["period_end"] == "2025-12-31"
    assert result["report_date"] is None
    assert result["op_cf_ps"] is None
    assert result["operating_cash_flow"] == 300.0
    assert result["free_cash_flow"] == 260.0
    assert result["cash_conversion_ratio"] == 1.5
    assert result["free_cash_flow_margin"] == 0.26
    assert result["accrual_ratio"] == -0.05
    assert result["receivables_pressure"] == 0.1
    assert result["net_cash_ratio"] == -0.15
    assert result["data_quality"]["point_in_time_supported"] is False
    assert result["data_quality"]["publication_date_known"] is False
    assert result["data_quality"]["status"] == "normal"
    assert result["history"][0]["period_end"] == "2025-12-31"


def test_financial_health_never_joins_neighboring_period_or_converts_missing_to_zero(monkeypatch):
    monkeypatch.setattr(astock, "_akshare", lambda: _Ak(cash_period="2025-09-30"))

    result = astock.financials("600519", include_health=True)

    assert result["operating_cash_flow"] is None
    assert result["capital_expenditure"] is None
    assert result["free_cash_flow"] is None
    assert result["cash_conversion_ratio"] is None
    assert result["data_quality"]["status"] == "partial"
    older = next(row for row in result["history"] if row["period_end"] == "2025-09-30")
    assert older["operating_cash_flow"] == 300.0
    assert older["net_profit_amount"] is None
    assert older["cash_conversion_ratio"] is None


def test_financial_health_keeps_core_snapshot_when_optional_cashflow_fails(monkeypatch):
    monkeypatch.setattr(astock, "_akshare", lambda: _Ak(cash_error=True))

    result = astock.financials("600519", include_health=True)

    assert result["revenue"] == "100亿"
    assert result["operating_cash_flow"] is None
    assert "cashflow_unavailable" in result["data_quality"]["warnings"]
    assert result["data_quality"]["status"] == "partial"
    assert not any(
        isinstance(value, float) and not math.isfinite(value)
        for value in result.values()
    )
