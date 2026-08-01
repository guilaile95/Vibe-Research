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

# ---------------------------------------------------------------------------
# Northbound turnover history (v0.1)
# ---------------------------------------------------------------------------

from datetime import date
from copy import deepcopy


def _history_js(trade_date: str, total: float, count: int | None = 1000, etf: float | None = 10.0) -> str:
    count_cell = "N/A" if count is None else f"{count}"
    etf_cell = "-" if etf is None else f"{etf}"
    half = total / 2
    return (
        "tabData = [\n"
        "  {\n"
        '    "market": "SSE Northbound",\n'
        f'    "date": "{trade_date}",\n'
        '    "content": [\n'
        "      {\n"
        '        "style": 1,\n'
        '        "table": {\n'
        '          "classname": "tradingTable",\n'
        '          "schema": ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"],\n'
        f'          "tr": [{{"td": [["{half}"], ["{count_cell}"], ["999,999,999"], ["{etf_cell}"]]}}]\n'
        "        }\n"
        "      }\n"
        "    ]\n"
        "  },\n"
        "  {\n"
        '    "market": "SZSE Northbound",\n'
        f'    "date": "{trade_date}",\n'
        '    "content": [\n'
        "      {\n"
        '        "style": 1,\n'
        '        "table": {\n'
        '          "classname": "tradingTable",\n'
        '          "schema": ["Total Turnover", "Total Trade Count", "DQB", "ETF Turnover"],\n'
        f'          "tr": [{{"td": [["{half}"], ["{count_cell}"], ["999,999,999"], ["{etf_cell}"]]}}]\n'
        "        }\n"
        "      }\n"
        "    ]\n"
        "  }\n"
        "];\n"
    )


def test_history_days_only_10_20_30():
    for d in (10, 20, 30):
        assert ncf.validate_history_days(d) == d
    for bad in (0, 1, 11, 31, 15, -1):
        with pytest.raises(ncf.NorthboundHistoryDaysError) as ei:
            ncf.validate_history_days(bad)
        assert str(ei.value) == ncf.HISTORY_DAYS_ERROR


def test_history_weekends_skip_fetch(monkeypatch):
    # Anchor on Sunday 2026-08-02 so first two calendar days are weekend.
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        return _history_js(dt, 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 8, 2))
    assert "2026-08-02" not in calls  # Sunday
    assert "2026-08-01" not in calls  # Saturday
    assert all(date.fromisoformat(c).weekday() < 5 for c in calls)
    assert env["returned_points"] == 10
    assert env["status"] == "normal"
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert "PARTIAL_SOURCE_FAILURE" not in codes


def test_history_normal_trading_day_points(monkeypatch):
    monkeypatch.setattr(
        ncf,
        "_fetch_daily_stat_js",
        lambda dt: _history_js(dt, 200.0, count=123, etf=4.5),
    )
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))  # Friday
    assert env["status"] == "normal"
    assert env["requested_days"] == 10
    assert env["returned_points"] == 10
    assert env["returned_points"] == len(env["series"])
    assert env["schema_version"] == "northbound-history-v0.1"
    assert env["source"] == ncf.SOURCE_NAME
    assert env["source_tier"] == ncf.SOURCE_TIER
    for p in env["series"]:
        assert p["total_turnover_mn"] == 200.0
        assert p["trade_count"] == 246  # both legs
        assert p["etf_turnover_mn"] == 9.0
        assert "net_buy_mn" not in p


def test_history_none_fetch_skips(monkeypatch):
    def mock_fetch(dt):
        if dt == "2026-07-30":
            return None
        return _history_js(dt, 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    dates = [p["trade_date"] for p in env["series"]]
    assert "2026-07-30" not in dates
    assert env["returned_points"] == 10
    # Ordinary missing file does not force partial once points are complete.
    assert env["status"] == "normal"
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert "PARTIAL_SOURCE_FAILURE" not in codes


def test_history_unavailable_envelope_skips(monkeypatch):
    def mock_fetch(dt):
        if dt == "2026-07-29":
            return "tabData = [];"
        return _history_js(dt, 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    dates = [p["trade_date"] for p in env["series"]]
    assert "2026-07-29" not in dates
    assert env["returned_points"] == 10
    # Non-empty payload that becomes unavailable is a real scan fault.
    assert env["status"] == "partial"
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert codes.count("PARTIAL_SOURCE_FAILURE") == 1


def test_history_parse_failure_skips(monkeypatch):
    def mock_fetch(dt):
        if dt == "2026-07-28":
            return "not-a-valid-tabData"
        return _history_js(dt, 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    dates = [p["trade_date"] for p in env["series"]]
    assert "2026-07-28" not in dates
    assert env["returned_points"] == 10
    assert env["status"] == "partial"
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert codes.count("PARTIAL_SOURCE_FAILURE") == 1


def test_history_one_failure_does_not_block(monkeypatch):
    def mock_fetch(dt):
        if dt.endswith("27"):
            raise RuntimeError("boom")
        return _history_js(dt, 50.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["returned_points"] == 10
    assert env["status"] == "partial"
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert codes.count("PARTIAL_SOURCE_FAILURE") == 1


def test_history_series_sorted_ascending(monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: _history_js(dt, 10.0))
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    dates = [p["trade_date"] for p in env["series"]]
    assert dates == sorted(dates)


def test_history_dedupe_same_trade_date(monkeypatch):
    # Force two calendar days to map to the same payload trade_date.
    def mock_fetch(dt):
        return _history_js("2026-07-20", 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    dates = [p["trade_date"] for p in env["series"]]
    assert dates.count("2026-07-20") == 1
    assert env["status"] in ("partial", "unavailable")


def test_history_full_points_normal(monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: _history_js(dt, 100.0, 10, 1.0))
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "normal"
    assert env["returned_points"] == 10


def test_history_partial_when_short(monkeypatch):
    # Only return files for 3 weekdays then None.
    good = {"2026-07-31", "2026-07-30", "2026-07-29"}

    def mock_fetch(dt):
        if dt in good:
            return _history_js(dt, 100.0)
        return None

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "partial"
    assert env["returned_points"] == 3
    codes = {lim["reason_code"] for lim in env["limitations"]}
    assert "INSUFFICIENT_HISTORY_POINTS" in codes


def test_history_no_points_unavailable(monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: None)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "unavailable"
    assert env["series"] == []
    assert env["returned_points"] == 0


def test_history_missing_trade_count_partial(monkeypatch):
    monkeypatch.setattr(
        ncf,
        "_fetch_daily_stat_js",
        lambda dt: _history_js(dt, 100.0, count=None, etf=2.0),
    )
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "partial"
    assert env["returned_points"] == 10
    assert all(p["trade_count"] is None for p in env["series"])
    fields = {lim["field"] for lim in env["limitations"]}
    assert "series[].trade_count" in fields
    assert sum(1 for lim in env["limitations"] if lim["field"] == "series[].trade_count") == 1


def test_history_missing_etf_partial(monkeypatch):
    monkeypatch.setattr(
        ncf,
        "_fetch_daily_stat_js",
        lambda dt: _history_js(dt, 100.0, count=5, etf=None),
    )
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "partial"
    assert all(p["etf_turnover_mn"] is None for p in env["series"])
    fields = {lim["field"] for lim in env["limitations"]}
    assert "series[].etf_turnover_mn" in fields


def test_history_missing_total_point_dropped(monkeypatch):
    def mock_fetch(dt):
        return (
            "tabData = [\n"
            f'  {{"market":"SSE Northbound","date":"{dt}","content":[{{"style":1,"table":{{"classname":"tradingTable","schema":["Total Turnover","Total Trade Count","DQB","ETF Turnover"],"tr":[{{"td":[["-"],["1"],["999,999,999"],["1"]}}]}}}}]}},\n'
            f'  {{"market":"SZSE Northbound","date":"{dt}","content":[{{"style":1,"table":{{"classname":"tradingTable","schema":["Total Turnover","Total Trade Count","DQB","ETF Turnover"],"tr":[{{"td":[["N/A"],["1"],["999,999,999"],["1"]}}]}}}}]}}\n'
            "];\n"
        )

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "unavailable"
    assert env["series"] == []


def test_history_trade_date_not_from_request_date(monkeypatch):
    # Payload dates fixed to 2026-07-01 regardless of request calendar day.
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: _history_js("2026-07-01", 100.0))
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["series"]
    assert all(p["trade_date"] == "2026-07-01" for p in env["series"])
    assert env["returned_points"] == 1  # deduped


def test_history_scan_hard_cap_days_times_two(monkeypatch):
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        return None

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    # Max calendar days = 20; weekends skipped so fetch calls <= weekdays in window.
    assert len(calls) <= 20
    # Ensure we did not scan beyond 20 calendar days from anchor.
    scanned = [date.fromisoformat(c) for c in calls]
    assert max((date(2026, 7, 31) - d).days for d in scanned) < 20
    assert env["status"] == "unavailable"


def test_history_insufficient_points_limitation(monkeypatch):
    good = {"2026-07-31", "2026-07-30"}

    def mock_fetch(dt):
        return _history_js(dt, 10.0) if dt in good else None

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "partial"
    codes = {lim["reason_code"] for lim in env["limitations"]}
    assert "INSUFFICIENT_HISTORY_POINTS" in codes
    detail = next(lim["detail"] for lim in env["limitations"] if lim["reason_code"] == "INSUFFICIENT_HISTORY_POINTS")
    assert "2/10" in detail


def test_history_no_net_buy_field(monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: _history_js(dt, 10.0))
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    for p in env["series"]:
        assert "net_buy_mn" not in p
        assert "daily_quota_balance_mn" not in p
        assert "active_stocks" not in p


def test_history_fixed_unverified_semantics_limitation(monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: _history_js(dt, 10.0))
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert "UNVERIFIED_SOURCE_SEMANTICS" in codes
    assert "NOT_PUBLISHED_BY_SOURCE" not in codes


def test_history_returned_points_equals_len(monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: _history_js(dt, 10.0))
    env = ncf.get_northbound_history(20, today=date(2026, 7, 31))
    assert env["returned_points"] == len(env["series"])


def test_history_point_does_not_mutate_envelope():
    tab = ncf.parse_daily_stat_js(SAMPLE_HKEX_JS)
    env = ncf.build_envelope(tab, fetched_at="2026-07-30T12:00:00+00:00")
    before = deepcopy(env)
    point = ncf._history_point_from_envelope(env)
    assert point is not None
    assert env == before


def test_history_unexpected_exception_safe(monkeypatch):
    def mock_fetch(dt):
        raise RuntimeError("secret-url-or-trace")

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "unavailable"
    assert env["series"] == []
    blob = str(env)
    assert "secret-url-or-trace" not in blob
    assert "RuntimeError" not in blob


def test_history_parse_failure_then_full_is_partial(monkeypatch):
    """First weekday parse fails; subsequent days still fill 10 complete points."""
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        if len(calls) == 1:
            return "not-a-valid-tabData"
        return _history_js(dt, 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "partial"
    assert env["returned_points"] == 10
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert codes.count("PARTIAL_SOURCE_FAILURE") == 1


def test_history_semantic_unavailable_then_full_is_partial(monkeypatch):
    """First weekday returns non-empty malformed payload -> unavailable; still fills 10 points."""
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        if len(calls) == 1:
            return "tabData = [];"
        return _history_js(dt, 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "partial"
    assert env["returned_points"] == 10
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert codes.count("PARTIAL_SOURCE_FAILURE") == 1


def test_history_fetch_exception_then_full_is_partial(monkeypatch):
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return _history_js(dt, 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "partial"
    assert env["returned_points"] == 10
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert codes.count("PARTIAL_SOURCE_FAILURE") == 1


def test_history_fetch_none_then_full_is_normal(monkeypatch):
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        if len(calls) == 1:
            return None
        return _history_js(dt, 100.0)

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)
    env = ncf.get_northbound_history(10, today=date(2026, 7, 31))
    assert env["status"] == "normal"
    assert env["returned_points"] == 10
    codes = [lim["reason_code"] for lim in env["limitations"]]
    assert "PARTIAL_SOURCE_FAILURE" not in codes
