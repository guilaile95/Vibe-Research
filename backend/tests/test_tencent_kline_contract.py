"""Offline route, adjustment, unit and whole-batch validation contracts."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest
import requests
import ai_tools
import astock
import chat
import debate
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
    {"day": [BAR]},
    {"qfqday": [], "day": [BAR]},
    {"qfqday": [BAR, ["broken"]]},
])
def test_ai_summary_never_substitutes_unadjusted_fallback(monkeypatch, series):
    state = install(monkeypatch, series)

    def fallback(*args, **kwargs):
        pytest.fail("AI qfq requests must not call the unadjusted contract")

    monkeypatch.setattr(astock, "kline", fallback)
    result = ai_tools._kline({"code": "600519", "count": 5})
    assert result["status"] == "unavailable"
    assert result["adjustment"] == "qfq"
    assert result["source"] is result["latest_bar_date"] is None
    assert result["fallback"] == {"used": False, "status": "disabled", "reason": "unsupported_adjustment"}
    assert "summary" not in result and "recent" not in result
    assert state["closed"]


@pytest.mark.parametrize("available", [False, True])
def test_ai_kline_tool_envelope_does_not_count_metadata_as_observations(monkeypatch, available):
    install(monkeypatch, {"qfqday": [BAR]} if available else {"day": [BAR]})
    monkeypatch.setattr(astock, "kline", lambda *_a, **_kw: pytest.fail("Raw fallback invoked"))
    result = ai_tools.exec_tool("query_kline", {"code": "600519", "count": 5})
    serialized, status, truncated = chat._serialize_tool_result(result)
    envelope = json.loads(serialized)
    assert status == ("success" if available else "error")
    assert envelope["data"]["status"] == ("success" if available else "unavailable")
    assert envelope["data"]["adjustment"] == "qfq"
    assert not truncated
    section = debate._fetch_section(("query_kline", {"count": 5}, "K线", True, False), "600519")
    assert section["status"] == ("success" if available else "error")
    assert section["ok"] is available
    assert section["data"]["adjustment"] == "qfq"


def test_ai_adjusted_summary_discloses_source_and_distinct_timestamps(monkeypatch):
    install(monkeypatch, {"qfqday": [BAR, ["2026-08-21", "11", "12.1", "13", "10", "24"]],
                          "day": [["2026-08-20", "20", "22", "24", "18", "23"]]})
    result = ai_tools._kline({"code": "600519", "count": 5})
    assert result["summary"]["change_pct"] == 10
    assert result["source"] == "tencent_fqkline"
    assert result["adjustment"] == "qfq"
    assert result["latest_bar_date"] == "2026-08-21"
    assert result["fetched_at"] != result["latest_bar_date"]
    assert result["fallback"] == {"used": False, "status": "not_needed"}


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
