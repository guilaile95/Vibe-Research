"""GET /api/daily-review 离线 API 测试（Mock generate_daily_review，不联网）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import astock
import daily_review
import market

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _clear_review_state():
    import daily_review_cache

    daily_review._clear_review_cache()
    with daily_review._bg_refresh_lock:
        daily_review._bg_refreshing = False
        daily_review._refresh_failed = False
        daily_review._refresh_error = None
    daily_review_cache.clear_latest_review_file()
    yield
    daily_review._clear_review_cache()
    with daily_review._bg_refresh_lock:
        daily_review._bg_refreshing = False
        daily_review._refresh_failed = False
        daily_review._refresh_error = None
    daily_review_cache.clear_latest_review_file()


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
    assert "data" in body
    assert body["data"] == pkt
    assert body["data"]["status"] == "normal"
    assert body["data"]["schema_version"] == "daily-review-v0.1"
    assert body["data"]["warnings"] == ["各数据源尚未提供统一的数据截止时间"]
    assert body["data"]["capital_activity"]["total_amount"] == 1.2e12
    # 展示路径可附带 cache_meta；不破坏 data 契约
    if "cache_meta" in body:
        assert isinstance(body["cache_meta"], dict)
        assert "stale" in body["cache_meta"]


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

    # 展示路径走 get_daily_review_for_display；mock 其同步 live 分支
    monkeypatch.setattr(daily_review, "get_daily_review_for_display", boom)
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
        return {
            "data": _packet(),
            "cache_meta": {
                "source": "live",
                "stale": False,
                "refreshing": False,
                "saved_at": None,
                "age_seconds": 0.0,
            },
        }

    monkeypatch.setattr(daily_review, "get_daily_review_for_display", once)
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
    """当前接口不支持历史 date；多余查询参数不得传入展示聚合。"""
    calls = {"args": None, "kwargs": None}

    def capture(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {
            "data": _packet(),
            "cache_meta": {
                "source": "live",
                "stale": False,
                "refreshing": False,
                "saved_at": None,
                "age_seconds": 0.0,
            },
        }

    monkeypatch.setattr(daily_review, "get_daily_review_for_display", capture)
    r = client.get("/api/daily-review?date=2026-07-20")
    assert r.status_code == 200
    # 无参调用
    assert calls["args"] == ()
    assert calls["kwargs"] == {}


def test_daily_review_api_exposes_cache_meta(monkeypatch):
    monkeypatch.setattr(
        daily_review,
        "get_daily_review_for_display",
        lambda: {
            "data": _packet(),
            "cache_meta": {
                "source": "persisted",
                "stale": True,
                "refreshing": True,
                "saved_at": "2026-07-20 15:00:00",
                "age_seconds": 3600.0,
            },
        },
    )
    r = client.get("/api/daily-review")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "normal"
    assert body["cache_meta"]["stale"] is True
    assert body["cache_meta"]["source"] == "persisted"
