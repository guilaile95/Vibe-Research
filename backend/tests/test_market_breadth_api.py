"""GET /api/market/breadth 离线 API 测试（Mock market.get_market_breadth，不联网）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import market

client = TestClient(app_module.app)

_BREADTH_CORE = {
    "stock_count": 5000,
    "valid_count": 4900,
    "up_count": 3000,
    "down_count": 1800,
    "flat_count": 100,
    "up_ratio": 0.6122,
    "up_3pct_count": 500,
    "down_3pct_count": 260,
    "total_amount": 1250000000000,
    "amount_valid_count": 4900,
    "amount_top": [],
    "high_turnover": [],
}


def test_breadth_api_normal_passthrough_no_rewrite(monkeypatch):
    """normal 信封原样透传；API 不改写数值/warnings/status。"""
    env = {
        "status": "normal",
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:30:00",
        "is_stale": False,
        "warnings": ["源数据未提供明确交易日期和行情时间"],
        "data": dict(_BREADTH_CORE),
    }
    monkeypatch.setattr(market, "get_market_breadth", lambda: env)
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    payload = r.json()["data"]
    assert payload == env
    assert payload["status"] == "normal"
    assert payload["data"]["stock_count"] == 5000
    assert payload["data"]["up_count"] == 3000
    assert payload["warnings"] == ["源数据未提供明确交易日期和行情时间"]


def test_breadth_api_partial_passthrough(monkeypatch):
    env = {
        "status": "partial",
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:30:00",
        "is_stale": False,
        "warnings": ["部分字段缺失", "成交额汇总不可用"],
        "data": {**_BREADTH_CORE, "total_amount": None, "amount_valid_count": 0},
    }
    monkeypatch.setattr(market, "get_market_breadth", lambda: env)
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    payload = r.json()["data"]
    assert payload == env
    assert payload["status"] == "partial"
    assert payload["warnings"] == ["部分字段缺失", "成交额汇总不可用"]


def test_breadth_api_unavailable_passthrough(monkeypatch):
    env = {
        "status": "unavailable",
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:30:00",
        "is_stale": False,
        "warnings": ["全市场快照获取失败：timeout"],
        "data": None,
    }
    monkeypatch.setattr(market, "get_market_breadth", lambda: env)
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    payload = r.json()["data"]
    assert payload == env
    assert payload["status"] == "unavailable"
    assert payload["data"] is None
    assert "timeout" in payload["warnings"][0]


def test_breadth_api_unexpected_error_502(monkeypatch):
    def boom():
        raise RuntimeError("unexpected")

    monkeypatch.setattr(market, "get_market_breadth", boom)
    r = client.get("/api/market/breadth")
    assert r.status_code == 502
    body = r.json()
    detail = body.get("detail", "")
    assert "市场广度异常" in detail
    assert "unexpected" in detail
    assert "data" not in body or body.get("data") is None


def test_breadth_api_calls_get_market_breadth_once(monkeypatch):
    calls = {"n": 0}

    def once():
        calls["n"] += 1
        return {
            "status": "normal",
            "source": "eastmoney_push2",
            "trade_date": None,
            "data_time": None,
            "fetched_at": "2026-07-21 15:30:00",
            "is_stale": False,
            "warnings": [],
            "data": dict(_BREADTH_CORE),
        }

    monkeypatch.setattr(market, "get_market_breadth", once)
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    assert calls["n"] == 1
