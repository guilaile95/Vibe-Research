"""Offline fund-flow completeness and model-facing evidence contracts."""
from datetime import date, timedelta
import json
from types import SimpleNamespace

import pytest

import ai_tools
import astock
import chat


FIELDS = ("main_net", "small_net", "mid_net", "large_net", "super_net")


def _rows(count, amount=1e8):
    return [{"date": (date(2026, 1, 1) + timedelta(days=i)).isoformat(),
             **{field: amount for field in FIELDS}} for i in range(count)]


def _run(monkeypatch, rows):
    monkeypatch.setattr(astock, "stock_fund_flow_120d", lambda code: rows)
    result = ai_tools.exec_tool("query_fund_flow", {"code": "000001"})
    serialized, status, _ = chat._serialize_tool_result(result)
    return result, json.loads(serialized), status


@pytest.mark.parametrize("reader", [astock.stock_fund_flow_120d, ai_tools._fund_flow_today])
@pytest.mark.parametrize("bad", ["-", "--", "", "oops", "nan", "inf", "-inf", "1e999"])
def test_both_sources_preserve_unknown_amounts_and_real_zero(monkeypatch, reader, bad):
    payload = {"data": {"klines": [f"2026-09-29,{bad},0,-2,3.5,0"]}}
    monkeypatch.setattr(astock, "em_get", lambda *a, **kw: SimpleNamespace(json=lambda: payload))
    row = reader("000001")[0]
    assert row["main_net"] is None
    assert row["small_net"] == row["super_net"] == 0
    assert row["mid_net"] == -2
    assert row["large_net"] == 3.5
    json.dumps(row, allow_nan=False)


@pytest.mark.parametrize("reader", [astock.stock_fund_flow_120d, ai_tools._fund_flow_today])
def test_null_data_and_malformed_rows_are_empty(monkeypatch, reader):
    for payload in ({"data": None}, {"data": {"klines": None}},
                    {"data": {"klines": [None, "short"]}}):
        monkeypatch.setattr(astock, "em_get", lambda *a, **kw: SimpleNamespace(json=lambda: payload))
        assert reader("000001") == []


def test_short_history_does_not_claim_any_full_window(monkeypatch):
    result, envelope, status = _run(monkeypatch, _rows(2))
    assert status == "partial" and envelope["limitations"]
    for n in (5, 20, 60):
        assert result[f"main_net_{n}d_yi"] is None
        assert result["windows"][f"{n}d"] == {
            "expected_count": n, "observed_count": 2, "valid_count": 2, "status": "partial"}
    assert len(envelope["data"]["recent"]) == 2


@pytest.mark.parametrize("bad", [None, "-", float("nan"), float("inf")])
def test_missing_amount_inside_full_window_is_not_zero_or_skipped(monkeypatch, bad):
    rows = _rows(61)
    rows[-1]["main_net"] = bad
    result, envelope, status = _run(monkeypatch, rows)
    assert status == "partial"
    for n in (5, 20, 60):
        assert result[f"main_net_{n}d_yi"] is None
        assert result["windows"][f"{n}d"]["observed_count"] == n
        assert result["windows"][f"{n}d"]["valid_count"] == n - 1
    assert envelope["data"]["recent"][-1]["main_net"] is None


def test_each_window_has_independent_completeness(monkeypatch):
    rows = _rows(60)
    rows[-6]["main_net"] = None
    result, _, status = _run(monkeypatch, rows)
    assert result["main_net_5d_yi"] == 5
    assert result["main_net_20d_yi"] is None
    assert result["main_net_60d_yi"] is None
    assert status == "partial"


@pytest.mark.parametrize("amount", [0, 1e8, -1e8])
def test_complete_windows_preserve_real_zero_and_signed_totals(monkeypatch, amount):
    result, envelope, status = _run(monkeypatch, _rows(60, amount))
    assert status == "success" and not envelope["limitations"]
    assert "不证明连续交易日覆盖" in result["note"]
    for n in (5, 20, 60):
        assert result[f"main_net_{n}d_yi"] == n * amount / 1e8
        assert result["windows"][f"{n}d"]["valid_count"] == n


@pytest.mark.parametrize("dates", [["2026-01-01"] * 60, ["invalid"] * 60,
                                  [None] * 60, [r["date"] for r in reversed(_rows(60))]])
def test_duplicate_invalid_or_unordered_dates_cannot_establish_complete_window(monkeypatch, dates):
    rows = _rows(60)
    for row, d in zip(rows, dates):
        row["date"] = d
    result, _, status = _run(monkeypatch, rows)
    assert status == "partial"
    assert all(result[f"main_net_{n}d_yi"] is None for n in (5, 20, 60))


def test_delayed_fallback_explicitly_partial_even_for_real_zero(monkeypatch):
    monkeypatch.setattr(ai_tools, "_fund_flow_today", lambda code: _rows(1, 0))
    result, envelope, status = _run(monkeypatch, [])
    assert status == "partial" and envelope["limitations"]
    assert result["source"] == "eastmoney_push2delay"
    assert result["recent"][0]["main_net"] == 0
    assert result["main_net_5d_yi"] is None


def test_unavailable_fallback_stays_error(monkeypatch):
    monkeypatch.setattr(ai_tools, "_fund_flow_today", lambda code: [])
    _, envelope, status = _run(monkeypatch, [])
    assert status == "error" and envelope["limitations"]


def test_missing_secondary_amount_is_preserved_and_disclosed(monkeypatch):
    rows = _rows(60)
    rows[-1]["small_net"] = None
    result, _, status = _run(monkeypatch, rows)
    assert result["main_net_60d_yi"] == 60
    assert status == "partial"


def test_dated_truncated_row_is_not_dropped_or_backfilled(monkeypatch):
    payload = {"data": {"klines": ["2026-09-29", "2026-09-30,0"]}}
    monkeypatch.setattr(astock, "em_get", lambda *a, **kw: SimpleNamespace(json=lambda: payload))
    rows = astock.stock_fund_flow_120d("000001")
    assert len(rows) == 2
    assert rows[0]["main_net"] is None
    assert rows[1]["main_net"] == 0
    assert rows[1]["super_net"] is None
    result, _, status = _run(monkeypatch, rows)
    assert status == "partial"
    assert result["windows"]["5d"]["observed_count"] == 2
    assert result["windows"]["5d"]["valid_count"] == 1
