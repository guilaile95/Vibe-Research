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


def test_breadth_api_normal_envelope_passthrough_no_rewrite(monkeypatch):
    """normal 信封透传：HTTP 200，结构正确，数值不被 API 层改写。"""
    env = {
        "status": "normal",
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:30:00",
        "is_stale": False,
        "warnings": [],
        "data": dict(_BREADTH_CORE),
    }
    monkeypatch.setattr(market, "get_market_breadth", lambda: env)
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    payload = r.json()["data"]
    assert payload["status"] == "normal"
    assert payload["source"] == "eastmoney_push2"
    assert payload["trade_date"] is None
    assert payload["data_time"] is None
    assert payload["fetched_at"] == "2026-07-21 15:30:00"
    assert payload["is_stale"] is False
    assert payload["warnings"] == []
    # 数值原样，API 层不得改写
    assert payload["data"] == _BREADTH_CORE
    assert payload["data"]["stock_count"] == 5000
    assert payload["data"]["valid_count"] == 4900
    assert payload["data"]["up_count"] == 3000
    assert payload["data"]["down_count"] == 1800
    assert payload["data"]["flat_count"] == 100


def test_breadth_api_normal_from_raw_stats_wraps(monkeypatch):
    """市场层返回纯统计字段时，API 包装为 status=normal（当前实现兼容）。"""
    monkeypatch.setattr(market, "get_market_breadth", lambda: dict(_BREADTH_CORE))
    r = client.get("/api/market/breadth")
    assert r.status_code == 200
    payload = r.json()["data"]
    assert payload["status"] == "normal"
    assert payload["source"] == "eastmoney_push2"
    assert payload["data"]["stock_count"] == 5000
    assert payload["data"]["up_count"] == 3000
    # 内层数值未被改写
    assert payload["data"]["up_ratio"] == pytest.approx(0.6122)
    assert payload["data"]["total_amount"] == 1250000000000


def test_breadth_api_partial_status(monkeypatch):
    """partial：HTTP 200，warnings 完整保留。"""
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
    assert payload["status"] == "partial"
    assert payload["warnings"] == ["部分字段缺失", "成交额汇总不可用"]
    assert payload["data"]["total_amount"] is None


def test_breadth_api_unavailable_status(monkeypatch):
    """unavailable：HTTP 200，data.data is None，错误原因保留。"""
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
    assert payload["status"] == "unavailable"
    assert payload["data"] is None
    assert payload["warnings"] == ["全市场快照获取失败：timeout"]
    assert "timeout" in payload["warnings"][0]


def test_breadth_api_unexpected_error_502(monkeypatch):
    """未预期异常 → HTTP 502；detail 含市场广度异常；不伪造市场数据。"""
    def boom():
        raise RuntimeError("unexpected")

    monkeypatch.setattr(market, "get_market_breadth", boom)
    r = client.get("/api/market/breadth")
    assert r.status_code == 502
    body = r.json()
    detail = body.get("detail", "")
    assert "市场广度异常" in detail
    assert "unexpected" in detail
    # 不返回伪造的 unavailable 市场数据
    assert "data" not in body or body.get("data") is None
    assert body.get("data", {}).get("status") != "unavailable" if isinstance(body.get("data"), dict) else True


def test_breadth_api_calls_get_market_breadth_once(monkeypatch):
    """一次 API 请求只调用一次 get_market_breadth，不重复快照/广度计算。"""
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
