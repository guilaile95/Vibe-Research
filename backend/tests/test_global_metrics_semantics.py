"""Fixture-only financial currency, scale and zero-value contracts."""
import pytest
import gstock
from reporting_currency import reporting_currency


@pytest.mark.parametrize("raw,expected", [("人民币", "CNY"), ("港元", "HKD"), ("美元", "USD"), (" USD ", "USD"), (None, None), ("unknown", None), ({}, None)])
def test_reporting_currency(raw, expected):
    assert reporting_currency(raw) == expected


@pytest.mark.parametrize("primary,alternate,expected", [(0, 77, 0), (-4, 77, -4), (None, 77, 77), (False, 77, None), (float('nan'), 77, None), (float('inf'), None, None), ("0", 77, 0)])
def test_us_profit_preserves_valid_zero(monkeypatch, primary, alternate, expected):
    monkeypatch.setattr(gstock.astock, "eastmoney_datacenter", lambda *a, **k: [{"PARENT_HOLDER_NETPROFIT": primary, "HOLDER_PROFIT": alternate}])
    assert gstock._key_metrics("TEST.O")["net_profit"] == expected


def test_hk_report_currency_is_not_listing_currency(monkeypatch):
    monkeypatch.setattr(gstock.astock, "eastmoney_datacenter", lambda *a, **k: [{"CURRENCY": "人民币", "OPERATE_INCOME": 100, "HOLDER_PROFIT": 0, "PARENT_HOLDER_NETPROFIT": 9, "BASIC_EPS": 2}])
    metrics = gstock._key_metrics("00001.HK")
    assert metrics["reporting_currency"] == "CNY"
    assert metrics["net_profit"] == 0
    assert metrics["revenue"] == 100
    assert metrics["amount_unit"] == "PROVIDER_RAW_SCALE_UNVERIFIED"
    assert metrics["amount_scale_to_currency_units"] is None
    assert metrics["eps_unit"] == "REPORTING_CURRENCY_PER_SHARE"


@pytest.mark.parametrize("symbol,currency,expected", [("TEST.O", "人民币", "CNY"), ("TEST.O", "CHF", None), ("00001.HK", "港元", "HKD"), ("00001.HK", None, None)])
def test_currency_never_falls_back_to_market(monkeypatch, symbol, currency, expected):
    monkeypatch.setattr(gstock.astock, "eastmoney_datacenter", lambda *a, **k: [{"CURRENCY": currency}])
    metrics = gstock._key_metrics(symbol)
    assert metrics["reporting_currency"] == expected
    assert metrics["source_reporting_currency"] == currency


def test_nonfinite_or_boolean_metrics_are_missing(monkeypatch):
    monkeypatch.setattr(gstock.astock, "eastmoney_datacenter", lambda *a, **k: [{"OPERATE_INCOME": float("nan"), "BASIC_EPS": True, "NET_PROFIT_RATIO": float("inf")}])
    metrics = gstock._key_metrics("TEST.O")
    assert metrics["revenue"] is None
    assert metrics["eps"] is None
    assert metrics["net_margin"] is None
