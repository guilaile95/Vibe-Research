"""GET /api/daily-review 离线 API 测试（Mock generate_daily_review，不联网）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import astock
import daily_review
import market

client = TestClient(app_module.app)


def _packet(status="normal", warnings=None, components=None):
    comps = components or {
        "indices": "normal",
        "global_indices": "normal",
        "breadth": "normal",
        "emotion": "normal",
        "turnover": "normal",
        "industry_boards": "normal",
        "concept_boards": "normal",
        "region_boards": "normal",
    }
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": status,
        "warnings": list(warnings if warnings is not None else []),
        "data_health": {"components": comps},
        "market_environment": {"indices": {"status": "normal", "data": []}},
        "sector_rotation": {"industry": {"status": "normal"}},
        "short_term_emotion": {"status": "normal", "data": {"zt_count": 80}},
        "capital_activity": {"total_amount": 1.2e12, "amount_top": []},
    }


# ── 1 normal ────────────────────────────────────────────────────────

def test_daily_review_api_normal_passthrough(monkeypatch):
    pkt = _packet("normal", warnings=["各数据源尚未提供统一的数据截止时间"])
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: pkt)
    r = client.get("/api/daily-review")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"data"}
    assert body["data"] == pkt
    assert body["data"]["status"] == "normal"
    assert body["data"]["schema_version"] == "daily-review-v0.1"
    assert body["data"]["warnings"] == ["各数据源尚未提供统一的数据截止时间"]
    assert body["data"]["capital_activity"]["total_amount"] == 1.2e12


# ── 2 partial ───────────────────────────────────────────────────────

def test_daily_review_api_partial(monkeypatch):
    comps = {
        "indices": "normal",
        "global_indices": "normal",
        "breadth": "normal",
        "emotion": "normal",
        "turnover": "normal",
        "industry_boards": "normal",
        "concept_boards": "unavailable",
        "region_boards": "normal",
    }
    pkt = _packet("partial", warnings=["[概念板块] timeout"], components=comps)
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: pkt)
    r = client.get("/api/daily-review")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "partial"
    assert data["warnings"] == ["[概念板块] timeout"]
    assert data["data_health"]["components"]["concept_boards"] == "unavailable"


# ── 3 unavailable ───────────────────────────────────────────────────

def test_daily_review_api_unavailable_still_200(monkeypatch):
    comps = {k: "unavailable" for k in (
        "indices", "global_indices", "breadth", "emotion", "turnover",
        "industry_boards", "concept_boards", "region_boards",
    )}
    pkt = _packet(
        "unavailable",
        warnings=["全部核心组件不可用"],
        components=comps,
    )
    pkt["market_environment"] = {"indices": {"status": "unavailable", "data": None}}
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: pkt)
    r = client.get("/api/daily-review")
    assert r.status_code == 200  # 业务状态，非 HTTP 故障
    data = r.json()["data"]
    assert data["status"] == "unavailable"
    assert "data_health" in data
    assert data["data_health"]["components"]["indices"] == "unavailable"
    assert data["market_environment"]["indices"]["status"] == "unavailable"


# ── 4 未预期异常 502 ────────────────────────────────────────────────

def test_daily_review_api_unexpected_error_502(monkeypatch):
    def boom():
        raise RuntimeError("unexpected")

    monkeypatch.setattr(daily_review, "generate_daily_review", boom)
    r = client.get("/api/daily-review")
    assert r.status_code == 502
    detail = r.json().get("detail", "")
    assert "每日复盘聚合异常" in detail
    assert "unexpected" in detail
    assert "data" not in r.json() or r.json().get("data") is None


# ── 5 单次调用 ──────────────────────────────────────────────────────

def test_daily_review_api_calls_once(monkeypatch):
    calls = {"n": 0}

    def once():
        calls["n"] += 1
        return _packet()

    monkeypatch.setattr(daily_review, "generate_daily_review", once)
    r = client.get("/api/daily-review")
    assert r.status_code == 200
    assert calls["n"] == 1


# ── 6 API 不直接调底层 ──────────────────────────────────────────────

def test_daily_review_api_does_not_call_underlying(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("underlying must not be called by API")

    monkeypatch.setattr(market, "get_market_breadth", fail)
    monkeypatch.setattr(market, "get_board_ranking", fail)
    monkeypatch.setattr(market, "get_short_term_emotion", fail)
    monkeypatch.setattr(astock, "index_quote", fail)
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: _packet())
    r = client.get("/api/daily-review")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "normal"


# ── 7 多余参数不进入聚合器 ──────────────────────────────────────────

def test_daily_review_api_ignores_date_query(monkeypatch):
    """当前接口不支持历史 date；多余查询参数不得传入 generate_daily_review()。"""
    calls = {"args": None, "kwargs": None}

    def capture(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return _packet()

    monkeypatch.setattr(daily_review, "generate_daily_review", capture)
    r = client.get("/api/daily-review?date=2026-07-20")
    assert r.status_code == 200
    # 无参调用
    assert calls["args"] == ()
    assert calls["kwargs"] == {}
