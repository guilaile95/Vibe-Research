"""Offline route, adjustment, unit and whole-batch validation contracts."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
import requests
import ai_tools
import astock
import hithink_finance_client as hithink
import tencent_kline as tencent

BAR = ["2026-08-20", "10", "11", "12", "9", "23", "999999"]


def install(monkeypatch, series, *, code="sh600519", error=None):
    state = {"calls": [], "closed": False}
    def get(url, **kwargs):
        state["calls"].append((url, kwargs))
        def close(): state["closed"] = True
        def status():
            if error: raise error
        return SimpleNamespace(raise_for_status=status, close=close,
                               json=lambda: {"data": {code: series}})
    monkeypatch.setattr(requests, "get", get)
    return state


@pytest.mark.parametrize("period", ["day", "week", "month"])
def test_unadjusted_contract_and_lot_conversion(monkeypatch, period):
    state = install(monkeypatch, {period: [deepcopy(BAR)], "qfq" + period: [["bad"]]})
    result = tencent.unadjusted_bars("600519", period, 20)
    assert state["calls"][0][1]["params"]["param"] == f"sh600519,{period},,,20,"
    assert state["closed"]
    assert result[0]["volume"] == result[0]["vol"] == 2300
    assert result[0]["amount"] is None  # seventh value is not amount
    assert result[0]["price_adjustment"] == "none"


def test_ai_retains_qfq_lots_and_reuses_validation(monkeypatch):
    state = install(monkeypatch, {"qfqday": [deepcopy(BAR)]})
    assert ai_tools._kline_tencent("600519", "day", 5)[0]["volume"] == 23
    assert state["calls"][0][1]["params"]["param"].endswith(",qfq")
    install(monkeypatch, {"qfqday": [], "day": [BAR]})
    with pytest.raises(ValueError):
        ai_tools._kline_tencent("600519", "day", 5)


@pytest.mark.parametrize("series", [
    {"qfqday": [], "day": [BAR]},
    {"qfqday": [BAR, ["broken"]]},
])
def test_ai_summary_uses_only_fallback_after_adjusted_series_failure(monkeypatch, series):
    state = install(monkeypatch, series)
    fallback_rows = [
        {"date": "2026-08-20", "close": 20.0},
        {"date": "2026-08-21", "close": 22.0},
    ]

    def fallback(code, category, offset):
        assert (code, category, offset) == ("600519", 4, 5)
        return fallback_rows

    monkeypatch.setattr(astock, "kline", fallback)
    result = ai_tools._kline({"code": "600519", "count": 5})
    assert result["summary"]["bars"] == 2
    assert result["summary"]["first_close"] == 20
    assert result["summary"]["last_close"] == 22
    assert result["summary"]["change_pct"] == 10
    assert [(row["date"], row["close"]) for row in result["recent"]] == [
        (row["date"], row["close"]) for row in fallback_rows
    ]
    assert state["closed"]


@pytest.mark.parametrize("fallback_failure", ["empty", "error"])
def test_ai_summary_is_unavailable_when_all_sources_fail(monkeypatch, fallback_failure):
    state = install(monkeypatch, {"qfqday": [BAR, ["broken"]]})

    def fallback(*args, **kwargs):
        if fallback_failure == "error":
            raise RuntimeError("No qualified fallback")
        return []

    monkeypatch.setattr(astock, "kline", fallback)
    result = ai_tools._kline({"code": "600519"})
    assert "error" in result
    assert "summary" not in result
    assert "recent" not in result
    assert state["closed"]


@pytest.mark.parametrize("raw", [[], [["bad"]], [BAR, BAR], [BAR, ["2026-08-19", 10, 11, 12, 9, 23]],
                                 [["2999-01-01", 10, 11, 12, 9, 23]],
                                 [["2026-08-20", 10, 11, 12, 9, "nan"]],
                                 [["2026-08-20", 10, 11, 12, 9, True]],
                                 [["2026-08-20", 10, 13, 12, 9, 23]],
                                 [["2026-08-20", 0, 11, 12, 0, 23]]])
def test_invalid_batch_never_partially_consumed(monkeypatch, raw):
    install(monkeypatch, {"day": raw})
    with pytest.raises((ValueError, TypeError)):
        tencent.unadjusted_bars("600519", "day", 5)


@pytest.mark.parametrize("series,code", [({"qfqday": [BAR]}, "sh600519"),
                                         ({"day": [BAR]}, "sz000001"),
                                         ({"day": [BAR, BAR]}, "sh600519")])
def test_identity_adjustment_and_count_bounds(monkeypatch, series, code):
    install(monkeypatch, series, code=code)
    with pytest.raises(ValueError):
        tencent.unadjusted_bars("600519", "day", 1)


@pytest.mark.parametrize("code,period,count", [("920001", "day", 5), ("830001", "day", 5),
    ("600519", "m60", 5), ("600519", "day", 321), ("600519", "day", 0),
    ("600519", "day", True), ("600519", "day", 1.5), ("bad", "day", 5)])
def test_unsupported_request_never_calls_transport(monkeypatch, code, period, count):
    state = install(monkeypatch, {"day": [BAR]})
    with pytest.raises(ValueError):
        tencent.unadjusted_bars(code, period, count)
    assert not state["calls"]


def test_http_failure_closes_response(monkeypatch):
    state = install(monkeypatch, {"day": [BAR]}, error=requests.HTTPError("503"))
    with pytest.raises(requests.HTTPError):
        tencent.unadjusted_bars("600519", "day", 5)
    assert state["closed"]


@pytest.mark.parametrize("category,period", [(4, "day"), (5, "week"), (6, "month")])
@pytest.mark.parametrize("mode", ["empty", "error"])
def test_mootdx_uncovered_routes_get_bounded_fallback(monkeypatch, category, period, mode):
    monkeypatch.setattr(hithink, "is_configured", lambda: False)
    def client():
        if mode == "error": raise astock.DependencyMissing("missing")
        return SimpleNamespace(bars=lambda **_: None)
    monkeypatch.setattr(astock, "_mootdx_client", client)
    state = install(monkeypatch, {period: [BAR]})
    assert astock.kline("600519", category, 5)[0]["amount"] is None
    assert len(state["calls"]) == 1


@pytest.mark.parametrize("code,category", [("600519", 11), ("920001", 5), ("830001", 6)])
def test_unqualified_routes_never_fake_empty_success(monkeypatch, code, category):
    monkeypatch.setattr(astock, "_mootdx_client", lambda: SimpleNamespace(bars=lambda **_: None))
    state = install(monkeypatch, {"day": [BAR]})
    with pytest.raises(RuntimeError, match="qualified"):
        astock.kline(code, category, 5)
    assert not state["calls"]
