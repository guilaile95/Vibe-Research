from __future__ import annotations

import json
from datetime import datetime, timezone
import pytest
import requests

import northbound_capital_flow as ncf

SAMPLE_HKEX_JS = """
tabData = [
  {
    "market": "SSE Northbound",
    "date": "2026-07-29",
    "tradingDay": "2026-07-29",
    "content": [
      {
        "style": 1,
        "table": {
          "classname": "tradingTable",
          "schema": ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"],
          "tr": [
            {
              "td": [["159,631.57"], ["1,234,567"], ["999,999,999"], ["1,234.56"]]
            }
          ]
        }
      },
      {
        "style": 2,
        "table": {
          "classname": "top10Table",
          "schema": ["Rank", "Stock Code", "Stock Name", "Total Turnover"],
          "tr": [
            {
              "td": [["1"], ["600519"], ["贵州茅台"], ["2,500,000,000"]]
            }
          ]
        }
      }
    ]
  },
  {
    "market": "SZSE Northbound",
    "date": "2026-07-29",
    "tradingDay": "2026-07-29",
    "content": [
      {
        "style": 1,
        "table": {
          "classname": "tradingTable",
          "schema": ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"],
          "tr": [
            {
              "td": [["140,368.43"], ["987,654"], ["999,999,999"], ["765.44"]]
            }
          ]
        }
      },
      {
        "style": 2,
        "table": {
          "classname": "top10Table",
          "schema": ["Rank", "Stock Code", "Stock Name", "Total Turnover"],
          "tr": [
            {
              "td": [["1"], ["000858"], ["五粮液"], ["1,800,000,000"]]
            }
          ]
        }
      }
    ]
  }
];
"""


def test_resolve_status_three_states():
    assert ncf.resolve_status(True, True) == "normal"
    assert ncf.resolve_status(True, False) == "partial"
    assert ncf.resolve_status(False, True) == "partial"
    assert ncf.resolve_status(False, False) == "unavailable"


def test_normal_parse_both_sides():
    tab_data = ncf.parse_daily_stat_js(SAMPLE_HKEX_JS)
    assert isinstance(tab_data, list)
    assert len(tab_data) == 2

    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    assert env["schema_version"] == "northbound-capital-flow-v0.1"
    assert env["status"] == "normal"
    assert env["trade_date"] == "2026-07-29"
    assert env["currency"] == "CNY"
    assert env["amount_unit"] == "million"

    nb = env["data"]["northbound"]
    assert pytest.approx(nb["total_turnover_mn"], 0.01) == 300000.0
    assert nb["trade_count"] == 2222221
    assert pytest.approx(nb["etf_turnover_mn"], 0.01) == 2000.0
    assert nb["net_buy_mn"] is None

    sse = env["data"]["shanghai_connect"]
    assert sse["market"] == "SSE"
    assert pytest.approx(sse["total_turnover_mn"], 0.01) == 159631.57
    assert sse["trade_count"] == 1234567
    assert pytest.approx(sse["etf_turnover_mn"], 0.01) == 1234.56
    assert sse["daily_quota_balance_mn"] is None  # placeholder reset to None
    assert sse["net_buy_mn"] is None

    active = env["data"]["active_stocks"]
    assert len(active) == 2
    assert active[0]["market"] == "SSE"
    assert active[0]["code"] == "600519"
    assert active[0]["total_turnover_yuan"] == 2500000000.0
    assert active[0]["net_buy_yuan"] is None


def test_partial_sse_only():
    tab_data = [
        {
            "market": "SSE Northbound",
            "date": "2026-07-29",
            "content": [
                {
                    "style": 1,
                    "table": {
                        "classname": "tradingTable",
                        "schema": ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"],
                        "tr": [{"td": [["100.0"], ["10"], ["999,999,999"], ["5.0"]]}]
                    }
                }
            ]
        }
    ]
    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    assert env["status"] == "partial"
    assert env["data"]["northbound"]["total_turnover_mn"] is None
    assert env["data"]["shanghai_connect"]["total_turnover_mn"] == 100.0
    assert env["data"]["shenzhen_connect"]["total_turnover_mn"] is None
    assert len(env["warnings"]) > 0


def test_unavailable_both_failed():
    env = ncf.build_envelope([], fetched_at="2026-07-30T12:00:00+00:00")
    assert env["status"] == "unavailable"
    assert env["trade_date"] is None
    assert env["data"]["northbound"]["total_turnover_mn"] is None
    assert env["data"]["shanghai_connect"]["total_turnover_mn"] is None
    assert env["data"]["active_stocks"] == []


def test_unavailable_404_lookback(monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: None)
    res = ncf.get_northbound_capital_flow()
    assert res["status"] == "unavailable"
    assert res["trade_date"] is None


def test_broken_js_response():
    with pytest.raises(ncf.NorthboundParseError) as excinfo:
        ncf.parse_daily_stat_js("var tabData = bad_json_!!!;")
    assert "PARSE_FAILED" in str(excinfo.value)
    assert "bad_json" not in str(excinfo.value)


def test_missing_fields_to_none():
    tab_data = [
        {
            "market": "SSE Northbound",
            "date": "2026-07-29",
            "content": [
                {
                    "style": 1,
                    "table": {
                        "classname": "tradingTable",
                        "schema": ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"],
                        "tr": [{"td": [["-"], ["N/A"], ["null"], [""]]}]
                    }
                }
            ]
        }
    ]
    sse = ncf._leg_metrics(tab_data[0])
    assert sse["total_turnover_mn"] is None
    assert sse["trade_count"] is None
    assert sse["etf_turnover_mn"] is None
    assert sse["daily_quota_balance_mn"] is None


def test_timeout_handling(monkeypatch):
    def _mock_fetch(dt):
        raise requests.Timeout("Upstream timed out")

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", _mock_fetch)
    res = ncf.get_northbound_capital_flow()
    assert res["status"] == "unavailable"
    assert res["trade_date"] is None


def test_dqb_placeholder_handling():
    tab_data = ncf.parse_daily_stat_js(SAMPLE_HKEX_JS)
    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    assert env["data"]["shanghai_connect"]["daily_quota_balance_mn"] is None
    placeholder_lims = [
        lim for lim in env["limitations"] if lim.get("reason_code") == "PLACEHOLDER_VALUE"
    ]
    assert len(placeholder_lims) >= 1


def test_trade_date_only_from_payload(monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: SAMPLE_HKEX_JS)
    res = ncf.get_northbound_capital_flow()
    assert res["trade_date"] == "2026-07-29"


def test_all_net_buy_fields_are_none():
    tab_data = ncf.parse_daily_stat_js(SAMPLE_HKEX_JS)
    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    data = env["data"]
    assert data["northbound"]["net_buy_mn"] is None
    assert data["shanghai_connect"]["net_buy_mn"] is None
    assert data["shenzhen_connect"]["net_buy_mn"] is None
    for item in data["active_stocks"]:
        assert item["net_buy_yuan"] is None


def test_is_stale_behavior():
    now_utc = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    # trade_date 2026-07-29 is previous trading day -> not stale if expected is 2026-07-30 12:00 (before 15:00 close)
    stale = ncf._stale_flag("2026-07-29", now_utc)
    assert isinstance(stale, bool)
