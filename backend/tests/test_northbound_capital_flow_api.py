from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app, _DC_CACHE
import northbound_capital_flow as ncf
from tests.test_northbound_capital_flow import LIVE_NESTED_HKEX_JS, SAMPLE_HKEX_JS


@pytest.fixture
def client():
    _DC_CACHE._data.clear()
    return TestClient(app)


def test_api_200_envelope(client, monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: SAMPLE_HKEX_JS)
    resp = client.get("/api/market/northbound")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    env = body["data"]
    assert env["status"] == "normal"
    assert env["trade_date"] == "2026-07-29"
    assert env["schema_version"] == "northbound-capital-flow-v0.1"


def test_api_unavailable_returns_200(client, monkeypatch):
    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", lambda dt: None)
    resp = client.get("/api/market/northbound")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    env = body["data"]
    assert env["status"] == "unavailable"
    assert env["trade_date"] is None


def test_api_cache_hit_prevents_refetch(client, monkeypatch):
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        return SAMPLE_HKEX_JS

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)

    resp1 = client.get("/api/market/northbound")
    assert resp1.status_code == 200
    count1 = len(calls)
    assert count1 >= 1

    resp2 = client.get("/api/market/northbound")
    assert resp2.status_code == 200
    assert len(calls) == count1  # cached, no new fetch calls


def test_api_unavailable_not_cached(client, monkeypatch):
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        return None

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)

    resp1 = client.get("/api/market/northbound")
    assert resp1.status_code == 200
    assert resp1.json()["data"]["status"] == "unavailable"
    count1 = len(calls)

    resp2 = client.get("/api/market/northbound")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "unavailable"
    assert len(calls) > count1  # unavailable not cached, fetched again


def test_api_empty_core_structure_not_cached(client, monkeypatch):
    """Structure parses to entry/table but core values are empty → unavailable, no cache."""
    empty_core_js = """
tabData = [
  {
    "market": "SSE Northbound",
    "date": "2026-07-31",
    "content": [
      {
        "style": 1,
        "table": {
          "classname": "tradingTable",
          "schema": [["Total Turnover", "Buy Turnover", "Sell Turnover", "Total Trade Count", "DQB", "ETF Turnover"]],
          "tr": [
            {"td": [["-"]]},
            {"td": [["-"]]},
            {"td": [["-"]]},
            {"td": [["-"]]},
            {"td": [["999,999,999"]]},
            {"td": [["-"]]}
          ]
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
          "schema": [["Total Turnover", "Buy Turnover", "Sell Turnover", "Total Trade Count", "DQB", "ETF Turnover"]],
          "tr": [
            {"td": [["N/A"]]},
            {"td": [["0"]]},
            {"td": [["0"]]},
            {"td": [["0"]]},
            {"td": [["999,999,999"]]},
            {"td": [["null"]]}
          ]
        }
      }
    ]
  }
];
"""
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        return empty_core_js

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)

    resp1 = client.get("/api/market/northbound")
    assert resp1.status_code == 200
    assert resp1.json()["data"]["status"] == "unavailable"
    count1 = len(calls)
    assert count1 >= 1

    resp2 = client.get("/api/market/northbound")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "unavailable"
    assert len(calls) > count1


def test_api_live_nested_fixture_cached(client, monkeypatch):
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        return LIVE_NESTED_HKEX_JS

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)

    resp1 = client.get("/api/market/northbound")
    assert resp1.status_code == 200
    env1 = resp1.json()["data"]
    assert env1["status"] == "normal"
    assert env1["trade_date"] == "2026-07-31"
    count1 = len(calls)
    assert count1 >= 1

    resp2 = client.get("/api/market/northbound")
    assert resp2.status_code == 200
    env2 = resp2.json()["data"]
    assert env2["status"] == "normal"
    assert len(calls) == count1


def test_api_partial_is_cached(client, monkeypatch):
    partial_js = """
tabData = [
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
];
"""
    calls = []

    def mock_fetch(dt):
        calls.append(dt)
        return partial_js

    monkeypatch.setattr(ncf, "_fetch_daily_stat_js", mock_fetch)

    resp1 = client.get("/api/market/northbound")
    assert resp1.status_code == 200
    assert resp1.json()["data"]["status"] == "partial"
    count1 = len(calls)
    assert count1 >= 1

    resp2 = client.get("/api/market/northbound")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "partial"
    assert len(calls) == count1

def _history_ok_env(days=20, points=None, status="normal"):
    if points is None:
        points = [
            {
                "trade_date": f"2026-07-{i:02d}",
                "total_turnover_mn": 100.0 + i,
                "trade_count": 1000 + i,
                "etf_turnover_mn": 1.0 + i,
            }
            for i in range(1, days + 1)
        ]
    return {
        "schema_version": ncf.HISTORY_SCHEMA_VERSION,
        "source": ncf.SOURCE_NAME,
        "source_tier": ncf.SOURCE_TIER,
        "status": status,
        "fetched_at": "2026-08-01T00:00:00+00:00",
        "requested_days": days,
        "returned_points": len(points),
        "limitations": [dict(ncf.LIMITATION_HISTORY_NET_BUY)],
        "series": points,
    }


def test_history_api_default_days_20(client, monkeypatch):
    calls = []

    def mock_hist(days, **kwargs):
        calls.append(days)
        return _history_ok_env(days)

    monkeypatch.setattr(ncf, "get_northbound_history", mock_hist)
    resp = client.get("/api/market/northbound/history")
    assert resp.status_code == 200
    env = resp.json()["data"]
    assert calls == [20]
    assert env["requested_days"] == 20
    assert env["schema_version"] == "northbound-history-v0.1"
    assert env["source"] == ncf.SOURCE_NAME
    assert env["source_tier"] == ncf.SOURCE_TIER
    assert env["status"] == "normal"
    assert env["returned_points"] == 20
    assert isinstance(env["limitations"], list)
    assert isinstance(env["series"], list)
    for p in env["series"]:
        assert "net_buy_mn" not in p
        assert "daily_quota_balance_mn" not in p
        assert "active_stocks" not in p


@pytest.mark.parametrize("days", [10, 20, 30])
def test_history_api_allowed_days(client, monkeypatch, days):
    monkeypatch.setattr(ncf, "get_northbound_history", lambda d, **k: _history_ok_env(d))
    resp = client.get(f"/api/market/northbound/history?days={days}")
    assert resp.status_code == 200
    assert resp.json()["data"]["requested_days"] == days


@pytest.mark.parametrize("days", ["0", "1", "11", "31"])
def test_history_api_invalid_days_400(client, days):
    resp = client.get(f"/api/market/northbound/history?days={days}")
    assert resp.status_code == 400
    assert "days 仅支持 10、20、30" in resp.text


def test_history_api_non_int_days_422(client):
    resp = client.get("/api/market/northbound/history?days=abc")
    assert resp.status_code == 422


def test_history_api_normal_cached(client, monkeypatch):
    calls = []

    def mock_hist(days, **kwargs):
        calls.append(days)
        return _history_ok_env(days)

    monkeypatch.setattr(ncf, "get_northbound_history", mock_hist)
    r1 = client.get("/api/market/northbound/history?days=10")
    r2 = client.get("/api/market/northbound/history?days=10")
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls == [10]


def test_history_api_days_isolation(client, monkeypatch):
    calls = []

    def mock_hist(days, **kwargs):
        calls.append(days)
        return _history_ok_env(days)

    monkeypatch.setattr(ncf, "get_northbound_history", mock_hist)
    assert client.get("/api/market/northbound/history?days=10").status_code == 200
    assert client.get("/api/market/northbound/history?days=20").status_code == 200
    assert calls == [10, 20]


def test_history_api_partial_cached(client, monkeypatch):
    calls = []

    def mock_hist(days, **kwargs):
        calls.append(days)
        return _history_ok_env(
            days,
            points=[{
                "trade_date": "2026-07-01",
                "total_turnover_mn": 1.0,
                "trade_count": 1,
                "etf_turnover_mn": 0.1,
            }],
            status="partial",
        )

    monkeypatch.setattr(ncf, "get_northbound_history", mock_hist)
    r1 = client.get("/api/market/northbound/history?days=20")
    r2 = client.get("/api/market/northbound/history?days=20")
    assert r1.json()["data"]["status"] == "partial"
    assert r2.json()["data"]["status"] == "partial"
    assert calls == [20]


def test_history_api_unavailable_not_cached(client, monkeypatch):
    calls = []

    def mock_hist(days, **kwargs):
        calls.append(days)
        return {
            "schema_version": ncf.HISTORY_SCHEMA_VERSION,
            "source": ncf.SOURCE_NAME,
            "source_tier": ncf.SOURCE_TIER,
            "status": "unavailable",
            "fetched_at": "2026-08-01T00:00:00+00:00",
            "requested_days": days,
            "returned_points": 0,
            "limitations": [dict(ncf.LIMITATION_HISTORY_NET_BUY)],
            "series": [],
        }

    monkeypatch.setattr(ncf, "get_northbound_history", mock_hist)
    r1 = client.get("/api/market/northbound/history?days=30")
    r2 = client.get("/api/market/northbound/history?days=30")
    assert r1.json()["data"]["status"] == "unavailable"
    assert r2.json()["data"]["status"] == "unavailable"
    assert calls == [30, 30]


def test_history_api_exception_safe(client, monkeypatch):
    def boom(days, **kwargs):
        raise RuntimeError("internal-trace-or-url")

    monkeypatch.setattr(ncf, "get_northbound_history", boom)
    resp = client.get("/api/market/northbound/history?days=10")
    assert resp.status_code == 200
    env = resp.json()["data"]
    assert env["status"] == "unavailable"
    assert env["series"] == []
    assert "internal-trace-or-url" not in resp.text
