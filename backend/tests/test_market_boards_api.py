"""GET /api/market/boards 离线 API 测试（Mock market.get_board_ranking，不联网）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import market

client = TestClient(app_module.app)

_BOARD_DATA = {
    "type": "industry",
    "total": 90,
    "ranked_count": 90,
    "unknown_count": 0,
    "top": [{"code": "BK001", "name": "半导体", "change_pct": 3.5}],
    "bottom": [{"code": "BK002", "name": "银行", "change_pct": -1.2}],
}


_SENTINEL = object()


def _env(status="normal", data=_SENTINEL, warnings=None):
    return {
        "status": status,
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:30:00",
        "is_stale": False,
        "warnings": list(warnings if warnings is not None else ["源数据未提供明确交易日期和行情时间"]),
        "data": dict(_BOARD_DATA) if data is _SENTINEL else data,
    }


# ── 1 默认参数 ──────────────────────────────────────────────────────

def test_boards_api_default_params(monkeypatch):
    calls = []

    def fake(board_type="industry", top_n=20):
        calls.append((board_type, top_n))
        return _env()

    monkeypatch.setattr(market, "get_board_ranking", fake)
    r = client.get("/api/market/boards")
    assert r.status_code == 200
    assert calls == [("industry", 20)]


# ── 2 自定义参数 ────────────────────────────────────────────────────

def test_boards_api_custom_params(monkeypatch):
    calls = []

    def fake(board_type="industry", top_n=20):
        calls.append((board_type, top_n))
        return _env(data={**_BOARD_DATA, "type": "concept"})

    monkeypatch.setattr(market, "get_board_ranking", fake)
    r = client.get("/api/market/boards?type=concept&top_n=10")
    assert r.status_code == 200
    assert calls == [("concept", 10)]


# ── 3 region ────────────────────────────────────────────────────────

def test_boards_api_region(monkeypatch):
    calls = []

    def fake(board_type="industry", top_n=20):
        calls.append((board_type, top_n))
        return _env(data={**_BOARD_DATA, "type": "region"})

    monkeypatch.setattr(market, "get_board_ranking", fake)
    r = client.get("/api/market/boards?type=region")
    assert r.status_code == 200
    assert calls[0][0] == "region"
    assert r.json()["data"]["data"]["type"] == "region"


# ── 4 normal 透传 ───────────────────────────────────────────────────

def test_boards_api_normal_passthrough(monkeypatch):
    env = _env("normal")
    monkeypatch.setattr(market, "get_board_ranking", lambda *a, **k: env)
    r = client.get("/api/market/boards")
    assert r.status_code == 200
    assert r.json()["data"] == env
    assert r.json()["data"]["status"] == "normal"
    assert r.json()["data"]["data"]["top"][0]["code"] == "BK001"


# ── 5 partial ───────────────────────────────────────────────────────

def test_boards_api_partial(monkeypatch):
    env = _env(
        "partial",
        data={**_BOARD_DATA, "ranked_count": 85, "unknown_count": 5},
        warnings=["源数据未提供明确交易日期和行情时间", "有 5 个板块缺少有效涨跌幅"],
    )
    monkeypatch.setattr(market, "get_board_ranking", lambda *a, **k: env)
    r = client.get("/api/market/boards?type=industry&top_n=20")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "partial"
    assert r.json()["data"] == env


# ── 6 unavailable ───────────────────────────────────────────────────

def test_boards_api_unavailable(monkeypatch):
    env = _env("unavailable", data=None, warnings=["板块排名数据不可用：timeout"])
    monkeypatch.setattr(market, "get_board_ranking", lambda *a, **k: env)
    r = client.get("/api/market/boards")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "unavailable"
    assert r.json()["data"]["data"] is None


# ── 7 非法 type ─────────────────────────────────────────────────────

def test_boards_api_invalid_type(monkeypatch):
    def boom(board_type="industry", top_n=20):
        raise ValueError(f"不支持的板块类型：{board_type}")

    monkeypatch.setattr(market, "get_board_ranking", boom)
    r = client.get("/api/market/boards?type=test")
    assert r.status_code == 400
    assert "不支持的板块类型：test" in r.json().get("detail", "")


# ── 8 非法 top_n ────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [0, 101])
def test_boards_api_invalid_top_n(monkeypatch, n):
    def boom(board_type="industry", top_n=20):
        raise ValueError(f"top_n 必须在 1..100 之间，收到：{top_n!r}")

    monkeypatch.setattr(market, "get_board_ranking", boom)
    r = client.get(f"/api/market/boards?top_n={n}")
    assert r.status_code == 400
    assert "top_n" in r.json().get("detail", "")


# ── 9 未预期异常 502 ────────────────────────────────────────────────

def test_boards_api_unexpected_error_502(monkeypatch):
    def boom(board_type="industry", top_n=20):
        raise RuntimeError("timeout")

    monkeypatch.setattr(market, "get_board_ranking", boom)
    r = client.get("/api/market/boards")
    assert r.status_code == 502
    detail = r.json().get("detail", "")
    assert "板块排名异常" in detail
    assert "timeout" in detail


# ── 10 只调用一次 ───────────────────────────────────────────────────

def test_boards_api_calls_once(monkeypatch):
    calls = {"n": 0}

    def once(board_type="industry", top_n=20):
        calls["n"] += 1
        return _env()

    monkeypatch.setattr(market, "get_board_ranking", once)
    r = client.get("/api/market/boards?type=industry&top_n=20")
    assert r.status_code == 200
    assert calls["n"] == 1
