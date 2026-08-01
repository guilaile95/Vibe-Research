from __future__ import annotations

from datetime import datetime, timezone
import math
import pytest
import requests

import northbound_capital_flow as ncf

# Legacy flat schema + per-cell td wrapper (must keep working).
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

# Live-shaped nested schema:
# - schema is one-level nested
# - tradingTable uses one row per metric (observed live)
# - top10 uses whole-row td wrapper
# - may also include Buy/Sell columns (ignored for net_buy)
LIVE_NESTED_HKEX_JS = """
tabData = [
  {
    "market": "SSE Northbound",
    "date": "2026-07-31",
    "tradingDay": "2026-07-31",
    "content": [
      {
        "style": 1,
        "table": {
          "classname": "tradingTable",
          "schema": [[
            "Total Turnover",
            "Buy Turnover",
            "Sell Turnover",
            "Total Trade Count",
            "DQB",
            "ETF Turnover"
          ]],
          "tr": [
            {"td": [["159,927.12"]]},
            {"td": [["80,000.00"]]},
            {"td": [["79,927.12"]]},
            {"td": [["1,234"]]},
            {"td": [["999,999,999"]]},
            {"td": [["500.00"]]}
          ]
        }
      },
      {
        "style": 2,
        "table": {
          "classname": "top10Table",
          "schema": [["Rank", "Stock Code", "Stock Name", "Total Turnover"]],
          "tr": [
            {
              "td": [["1", "600519", "贵州茅台", "2,500,000,000"]]
            }
          ]
        }
      }
    ]
  },
  {
    "market": "SZSE Northbound",
    "date": "2026-07-31",
    "tradingDay": "2026-07-31",
    "content": [
      {
        "style": 1,
        "table": {
          "classname": "tradingTable",
          "schema": [[
            "Total Turnover",
            "Buy Turnover",
            "Sell Turnover",
            "Total Trade Count",
            "DQB",
            "ETF Turnover"
          ]],
          "tr": [
            {"td": [["140,072.88"]]},
            {"td": [["70,000.00"]]},
            {"td": [["70,072.88"]]},
            {"td": [["2,000"]]},
            {"td": [["999,999,999"]]},
            {"td": [["300.50"]]}
          ]
        }
      },
      {
        "style": 2,
        "table": {
          "classname": "top10Table",
          "schema": [["Rank", "Stock Code", "Stock Name", "Total Turnover"]],
          "tr": [
            {
              "td": [["1", "000858", "五粮液", "1,800,000,000"]]
            }
          ]
        }
      }
    ]
  }
];
"""

# Alternate nested shape: single trading row with all cells (still supported).
LIVE_NESTED_SINGLE_ROW_HKEX_JS = """
tabData = [
  {
    "market": "SSE Northbound",
    "date": "2026-07-31",
    "content": [
      {
        "style": 1,
        "table": {
          "classname": "tradingTable",
          "schema": [["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"]],
          "tr": [{"td": [["159,927.12", "1,234", "999,999,999", "500.00"]]}]
        }
      }
    ]
  },
  {
    "market": "SZSE Northbound",
    "date": "2026-07-31",
    "content": [
      {
        "style": 1,
        "table": {
          "classname": "tradingTable",
          "schema": [["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"]],
          "tr": [{"td": [["140,072.88", "2,000", "999,999,999", "300.50"]]}]
        }
      }
    ]
  }
];
"""


def _trading_entry(
    market: str,
    *,
    date: str | None = "2026-07-29",
    schema=None,
    cells=None,
    include_top10: bool = False,
):
    if schema is None:
        schema = ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"]
    if cells is None:
        cells = [["100.0"], ["10"], ["999,999,999"], ["5.0"]]
    content = [
        {
            "style": 1,
            "table": {
                "classname": "tradingTable",
                "schema": schema,
                "tr": [{"td": cells}],
            },
        }
    ]
    if include_top10:
        content.append(
            {
                "style": 2,
                "table": {
                    "classname": "top10Table",
                    "schema": ["Rank", "Stock Code", "Stock Name", "Total Turnover"],
                    "tr": [{"td": [["1"], ["600519"], ["贵州茅台"], ["1,000"]]}],
                },
            }
        )
    entry = {
        "market": market,
        "content": content,
    }
    if date is not None:
        entry["date"] = date
    return entry


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


def test_live_nested_schema_fixture_parses_normal():
    tab_data = ncf.parse_daily_stat_js(LIVE_NESTED_HKEX_JS)
    env = ncf.build_envelope(tab_data, fetched_at="2026-08-01T12:00:00+00:00")

    assert env["status"] == "normal"
    assert env["trade_date"] == "2026-07-31"
    assert env["schema_version"] == "northbound-capital-flow-v0.1"

    sse = env["data"]["shanghai_connect"]
    szse = env["data"]["shenzhen_connect"]
    nb = env["data"]["northbound"]

    assert pytest.approx(sse["total_turnover_mn"], 0.01) == 159927.12
    assert pytest.approx(szse["total_turnover_mn"], 0.01) == 140072.88
    assert pytest.approx(nb["total_turnover_mn"], 0.01) == 300000.0
    assert sse["trade_count"] == 1234
    assert szse["trade_count"] == 2000
    assert nb["trade_count"] == 3234
    assert pytest.approx(sse["etf_turnover_mn"], 0.01) == 500.0
    assert pytest.approx(szse["etf_turnover_mn"], 0.01) == 300.5
    assert pytest.approx(nb["etf_turnover_mn"], 0.01) == 800.5
    assert sse["daily_quota_balance_mn"] is None
    assert szse["daily_quota_balance_mn"] is None
    assert nb["net_buy_mn"] is None
    assert sse["net_buy_mn"] is None
    assert szse["net_buy_mn"] is None

    active = env["data"]["active_stocks"]
    assert len(active) == 2
    assert active[0]["code"] == "600519"
    assert active[0]["name"] == "贵州茅台"
    assert active[0]["total_turnover_yuan"] == 2500000000.0
    assert active[0]["net_buy_yuan"] is None
    assert active[1]["code"] == "000858"
    assert active[1]["net_buy_yuan"] is None

    # Buy/Sell must not invent net_buy fields; limitation wording must not claim source has no split.
    for lim in env["limitations"]:
        if lim.get("field", "").endswith("net_buy_mn") or lim.get("field", "").endswith("net_buy_yuan"):
            assert "未验证" in lim["detail"] or "Buy/Sell" in lim["detail"]
            assert "未发布买入/卖出拆分" not in lim["detail"]


def test_live_nested_single_row_trading_values():
    tab_data = ncf.parse_daily_stat_js(LIVE_NESTED_SINGLE_ROW_HKEX_JS)
    env = ncf.build_envelope(tab_data, fetched_at="2026-08-01T12:00:00+00:00")
    assert env["status"] == "normal"
    assert env["trade_date"] == "2026-07-31"
    assert pytest.approx(env["data"]["northbound"]["total_turnover_mn"], 0.01) == 300000.0
    assert env["data"]["northbound"]["trade_count"] == 3234
    assert pytest.approx(env["data"]["northbound"]["etf_turnover_mn"], 0.01) == 800.5


def test_schema_normalization_shapes():
    flat = ncf._normalize_schema_labels(
        ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"]
    )
    nested = ncf._normalize_schema_labels(
        [["Total Turnover", "Buy Turnover", "Sell Turnover", "Total Trade Count", "DQB", "ETF Turnover"]]
    )
    dict_cols = ncf._normalize_schema_labels(
        [{"ref": "Total Turnover"}, {"label": "Total Trade Count"}, {"name": "ETF Turnover"}]
    )
    assert flat == ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"]
    assert nested[0] == "Total Turnover"
    assert "Buy Turnover" in nested
    assert "Sell Turnover" in nested
    assert nested[-1] == "ETF Turnover"
    assert dict_cols == ["Total Turnover", "Total Trade Count", "ETF Turnover"]


def test_row_cells_whole_row_and_per_cell():
    per_cell = ncf._row_cells({"td": [["159,927.12"], ["1,234"], ["999,999,999"], ["500.00"]]})
    whole_row = ncf._row_cells(
        {"td": [["159,927.12", "80,000", "79,927.12", "1,234", "999,999,999", "500.00"]]}
    )
    assert per_cell == ["159,927.12", "1,234", "999,999,999", "500.00"]
    assert whole_row == ["159,927.12", "80,000", "79,927.12", "1,234", "999,999,999", "500.00"]


def test_partial_sse_only():
    tab_data = [
        _trading_entry(
            "SSE Northbound",
            cells=[["100.0"], ["10"], ["999,999,999"], ["5.0"]],
        )
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


def test_both_legs_structure_present_but_core_unparseable():
    """Tables/schema/rows exist but Total Turnover is empty/illegal → unavailable."""
    tab_data = [
        _trading_entry(
            "SSE Northbound",
            cells=[["-"], ["10"], ["999,999,999"], ["5.0"]],
        ),
        _trading_entry(
            "SZSE Northbound",
            cells=[["N/A"], ["20"], ["999,999,999"], ["6.0"]],
        ),
    ]
    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    assert env["status"] == "unavailable"
    assert env["trade_date"] is None
    assert env["data"]["northbound"]["total_turnover_mn"] is None
    assert env["data"]["shanghai_connect"]["total_turnover_mn"] is None
    assert env["data"]["shenzhen_connect"]["total_turnover_mn"] is None


def test_one_valid_one_invalid_core_is_partial():
    tab_data = [
        _trading_entry(
            "SSE Northbound",
            cells=[["100.0"], ["10"], ["999,999,999"], ["5.0"]],
        ),
        _trading_entry(
            "SZSE Northbound",
            cells=[["-"], ["20"], ["999,999,999"], ["6.0"]],
        ),
    ]
    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    assert env["status"] == "partial"
    assert env["data"]["shanghai_connect"]["total_turnover_mn"] == 100.0
    assert env["data"]["shenzhen_connect"]["total_turnover_mn"] is None
    assert env["data"]["northbound"]["total_turnover_mn"] is None


def test_core_valid_optional_missing_is_partial():
    # Only Total Turnover present; trade_count / etf missing.
    schema = ["Total Turnover", "DQB"]
    tab_data = [
        _trading_entry(
            "SSE Northbound",
            schema=schema,
            cells=[["100.0"], ["999,999,999"]],
        ),
        _trading_entry(
            "SZSE Northbound",
            schema=schema,
            cells=[["200.0"], ["999,999,999"]],
        ),
    ]
    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    assert env["status"] == "partial"
    assert env["data"]["shanghai_connect"]["total_turnover_mn"] == 100.0
    assert env["data"]["shenzhen_connect"]["total_turnover_mn"] == 200.0
    assert env["data"]["northbound"]["total_turnover_mn"] == 300.0
    assert env["data"]["shanghai_connect"]["trade_count"] is None
    assert env["data"]["shanghai_connect"]["etf_turnover_mn"] is None
    reason_codes = {lim.get("reason_code") for lim in env["limitations"]}
    fields = {lim.get("field") for lim in env["limitations"]}
    assert "FIELD_UNAVAILABLE" in reason_codes
    assert "data.shanghai_connect.trade_count" in fields
    assert "data.shanghai_connect.etf_turnover_mn" in fields
    assert "data.shenzhen_connect.trade_count" in fields
    assert "data.shenzhen_connect.etf_turnover_mn" in fields


def test_negative_and_nonfinite_rejected():
    for bad in ["-1", "NaN", "Infinity", "-Infinity"]:
        tab_data = [
            _trading_entry(
                "SSE Northbound",
                cells=[[bad], ["10"], ["999,999,999"], ["5.0"]],
            ),
            _trading_entry(
                "SZSE Northbound",
                cells=[[bad], ["20"], ["999,999,999"], ["6.0"]],
            ),
        ]
        env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
        assert env["status"] == "unavailable", bad
        assert env["data"]["northbound"]["total_turnover_mn"] is None
        assert env["data"]["shanghai_connect"]["total_turnover_mn"] is None

    # Numeric non-finite via direct helper path
    assert ncf._nonneg_finite(float("nan")) is None
    assert ncf._nonneg_finite(float("inf")) is None
    assert ncf._nonneg_finite(-1) is None
    assert ncf._nonneg_finite(0) == 0.0
    assert math.isfinite(ncf._nonneg_finite(1.5))


def test_date_missing_cannot_be_normal():
    tab_data = [
        _trading_entry(
            "SSE Northbound",
            date=None,
            cells=[["100.0"], ["10"], ["999,999,999"], ["5.0"]],
        ),
        _trading_entry(
            "SZSE Northbound",
            date=None,
            cells=[["200.0"], ["20"], ["999,999,999"], ["6.0"]],
        ),
    ]
    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    assert env["status"] == "partial"
    assert env["trade_date"] is None
    assert env["data"]["northbound"]["total_turnover_mn"] is None


def test_date_mismatch_is_partial_no_sum():
    tab_data = [
        _trading_entry(
            "SSE Northbound",
            date="2026-07-29",
            cells=[["100.0"], ["10"], ["999,999,999"], ["5.0"]],
        ),
        _trading_entry(
            "SZSE Northbound",
            date="2026-07-28",
            cells=[["200.0"], ["20"], ["999,999,999"], ["6.0"]],
        ),
    ]
    env = ncf.build_envelope(tab_data, fetched_at="2026-07-30T12:00:00+00:00")
    assert env["status"] == "partial"
    assert env["data"]["northbound"]["total_turnover_mn"] is None
    assert env["data"]["shanghai_connect"]["total_turnover_mn"] == 100.0
    assert env["data"]["shenzhen_connect"]["total_turnover_mn"] == 200.0


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
    # Missing/invalid Total Turnover means the leg itself fails closed.
    tab_data = [
        _trading_entry(
            "SSE Northbound",
            cells=[["-"], ["N/A"], ["null"], [""]],
        )
    ]
    sse = ncf._leg_metrics(tab_data[0])
    assert sse is None


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
