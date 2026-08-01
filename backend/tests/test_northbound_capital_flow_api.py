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
