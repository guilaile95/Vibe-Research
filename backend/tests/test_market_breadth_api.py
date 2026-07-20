"""GET /api/market/breadth 离线 API 测试（Mock market.get_market_breadth，不联网）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import market

client = TestClient(app_module.app)

_BREADTH_CORE = {
    "stock_count": 5,
    "valid_count": 4,
    "up_count": 2,
    "down_count": 1,
    "flat_count": 1,
    "up_ratio": 0.5,
    "up_3pct_count": 1,
    "down_3pct_count": 0,
    "total_amount": 1.5e9,
    "amount_valid_count": 3,
    "amount_top": [
        {
            "code": "600519",
            "name": "贵州茅台",
            "price": 1700.0,
            "change_pct": 1.2,
            "amount": 1e9,
            "turnover_pct": 0.5,
            "market_cap": 2e12,
        }
    ],
    "high_turnover": [],
}


def test_breadth_api_normal_from_raw_stats(monkeypatch):
    """市场层返回纯统计字段时，API 包装为 status=normal。"""
    monkeypatch.setattr(market, "get_market_breadth", lambda: dict(_BREADTH_CORE))
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    payload = body["data"]
    assert payload["status"] == "normal"
    assert payload["source"] == "eastmoney_push2"
    assert payload["trade_date"] is None
    assert payload["data_time"] is None
    assert payload["is_stale"] is False
    assert isinstance(payload["fetched_at"], str) and len(payload["fetched_at"]) >= 10
    assert isinstance(payload["warnings"], list) and payload["warnings"]
    assert payload["data"]["stock_count"] == 5
    assert payload["data"]["up_count"] == 2
    assert payload["data"]["up_ratio"] == pytest.approx(0.5)
    assert payload["data"]["amount_top"][0]["code"] == "600519"


def test_breadth_api_partial_passthrough(monkeypatch):
    """市场层已返回 partial 信封时透传，仍 HTTP 200。"""
    env = {
        "status": "partial",
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:30:00",
        "is_stale": False,
        "warnings": ["部分字段缺失"],
        "data": {**_BREADTH_CORE, "total_amount": None, "amount_valid_count": 0},
    }
    monkeypatch.setattr(market, "get_market_breadth", lambda: env)
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    payload = r.json()["data"]
    assert payload["status"] == "partial"
    assert payload["warnings"] == ["部分字段缺失"]
    assert payload["data"]["total_amount"] is None


def test_breadth_api_unavailable_still_200(monkeypatch):
    """unavailable 状态仍 HTTP 200，由 body.status 表达数据源不可用。"""
    env = {
        "status": "unavailable",
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:30:00",
        "is_stale": True,
        "warnings": ["数据源不可用"],
        "data": None,
    }
    monkeypatch.setattr(market, "get_market_breadth", lambda: env)
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    payload = r.json()["data"]
    assert payload["status"] == "unavailable"
    assert payload["data"] is None
    assert payload["is_stale"] is True


def test_breadth_api_unexpected_error_502(monkeypatch):
    """未预期异常 → 502，不伪造 unavailable。"""
    def boom():
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(market, "get_market_breadth", boom)
    r = client.get("/api/market/breadth")
    assert r.status_code == 502
    detail = r.json().get("detail", "")
    assert "市场广度异常" in detail
    assert "upstream exploded" in detail
    # 不得伪装成 200 + unavailable
    assert r.json().get("data", {}).get("status") != "unavailable"
