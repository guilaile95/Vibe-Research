"""backend/portfolio.py get_portfolio 与 GET /api/portfolio 的行情 Null Safety 直接契约测试。

测试覆盖：
1. 全部行情有效 (complete == True, totals 有值, row data_status == normal)
2. 部分行情缺失 (complete == False, totals.market_value/pnl/pnl_pct == None, data_status == partial)
3. 全部行情缺失 (complete == False, totals.market_value/pnl/pnl_pct == None, data_status == unavailable)
4. 无效价格类型参数化 (None, 0, 负数, NaN, Infinity, bool, string)
5. 空持仓 (valid_holdings == 0, total_holdings == 0, complete == False, totals == 0.0)
6. 清仓数据 (closed 原样保留, realized_pnl 不受影响)
7. /api/portfolio HTTP 接口 JSON 序列化
"""
from __future__ import annotations

import json
import os
import pytest
from fastapi.testclient import TestClient

import app as app_module
import astock
import portfolio as pf

client = TestClient(app_module.app)


@pytest.fixture()
def tmp_pf_dir(tmp_path, monkeypatch):
    """隔离 portfolio 数据到临时目录，避免误动真实用户文件。"""
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    return tmp_path


def _seed_portfolio(tmp_path, holdings: list[dict], closed: list | None = None) -> None:
    p = str(tmp_path / "portfolio.json")
    data = {"holdings": holdings, "last_refresh": None}
    if closed is not None:
        data["closed"] = closed
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. 全部行情有效
# ---------------------------------------------------------------------------

def test_get_portfolio_all_quotes_valid(tmp_pf_dir, monkeypatch):
    _seed_portfolio(tmp_pf_dir, [
        {"code": "600519", "shares": 100, "cost": 1600.0},
        {"code": "000001", "shares": 200, "cost": 10.0},
    ])
    monkeypatch.setattr(
        astock,
        "tencent_quote",
        lambda codes: {
            "600519": {"name": "贵州茅台", "price": 1800.0},
            "000001": {"name": "平安银行", "price": 12.0},
        },
    )
    res = pf.get_portfolio()
    assert res["data_status"] == "normal"
    cov = res["quote_coverage"]
    assert cov["valid_holdings"] == 2
    assert cov["total_holdings"] == 2
    assert cov["complete"] is True

    h1, h2 = res["holdings"]
    assert h1["price"] == 1800.0
    assert h1["market_value"] == 180000.0
    assert h1["pnl"] == 20000.0
    assert h1["pnl_pct"] == 12.5
    assert h1["data_status"] == "normal"

    assert h2["price"] == 12.0
    assert h2["market_value"] == 2400.0
    assert h2["pnl"] == 400.0
    assert h2["pnl_pct"] == 20.0
    assert h2["data_status"] == "normal"

    assert res["totals"]["market_value"] == 182400.0
    assert res["totals"]["cost"] == 162000.0
    assert res["totals"]["pnl"] == 20400.0
    assert res["totals"]["pnl_pct"] == 12.59


# ---------------------------------------------------------------------------
# 2. 部分行情缺失
# ---------------------------------------------------------------------------

def test_get_portfolio_partial_quotes_missing(tmp_pf_dir, monkeypatch):
    _seed_portfolio(tmp_pf_dir, [
        {"code": "600519", "shares": 100, "cost": 1600.0},
        {"code": "BAD_CODE", "shares": 500, "cost": 20.0},
    ])
    monkeypatch.setattr(
        astock,
        "tencent_quote",
        lambda codes: {
            "600519": {"name": "贵州茅台", "price": 1800.0},
            # BAD_CODE 不在返回的 quotes 中
        },
    )
    res = pf.get_portfolio()
    assert res["data_status"] == "partial"
    cov = res["quote_coverage"]
    assert cov["valid_holdings"] == 1
    assert cov["total_holdings"] == 2
    assert cov["complete"] is False

    by_code = {h["code"]: h for h in res["holdings"]}
    ok_h = by_code["600519"]
    bad_h = by_code["BAD_CODE"]

    assert ok_h["price"] == 1800.0
    assert ok_h["market_value"] == 180000.0
    assert ok_h["data_status"] == "normal"

    assert bad_h["price"] is None
    assert bad_h["market_value"] is None
    assert bad_h["pnl"] is None
    assert bad_h["pnl_pct"] is None
    assert bad_h["data_status"] == "unavailable"

    # totals：只保留 cost，行情依赖字段为 None
    assert res["totals"]["cost"] == 170000.0
    assert res["totals"]["market_value"] is None
    assert res["totals"]["pnl"] is None
    assert res["totals"]["pnl_pct"] is None


# ---------------------------------------------------------------------------
# 3. 全部行情缺失
# ---------------------------------------------------------------------------

def test_get_portfolio_all_quotes_missing(tmp_pf_dir, monkeypatch):
    _seed_portfolio(tmp_pf_dir, [
        {"code": "600519", "shares": 100, "cost": 1600.0},
        {"code": "000001", "shares": 200, "cost": 10.0},
    ])
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {})
    res = pf.get_portfolio()
    assert res["data_status"] == "unavailable"
    cov = res["quote_coverage"]
    assert cov["valid_holdings"] == 0
    assert cov["total_holdings"] == 2
    assert cov["complete"] is False

    for h in res["holdings"]:
        assert h["price"] is None
        assert h["market_value"] is None
        assert h["pnl"] is None
        assert h["pnl_pct"] is None
        assert h["data_status"] == "unavailable"

    assert res["totals"]["cost"] == 162000.0
    assert res["totals"]["market_value"] is None
    assert res["totals"]["pnl"] is None
    assert res["totals"]["pnl_pct"] is None


# ---------------------------------------------------------------------------
# 4. 无效价格类型参数化测试
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("invalid_price", [
    {}, None, 0, 0.0, -1, -10.5, float("nan"), float("inf"), float("-inf"),
    True, False, "10.0", "abc"
])
def test_get_portfolio_invalid_price_types_parameterized(tmp_pf_dir, monkeypatch, invalid_price):
    _seed_portfolio(tmp_pf_dir, [{"code": "600519", "shares": 100, "cost": 1000.0}])
    if invalid_price == {}:
        monkeypatch.setattr(astock, "tencent_quote", lambda codes: {"600519": {}})
    else:
        monkeypatch.setattr(astock, "tencent_quote", lambda codes: {"600519": {"price": invalid_price}})

    res = pf.get_portfolio()
    assert res["data_status"] == "unavailable"
    assert res["quote_coverage"]["complete"] is False
    h = res["holdings"][0]
    assert h["price"] is None
    assert h["market_value"] is None
    assert h["pnl"] is None
    assert h["pnl_pct"] is None
    assert h["data_status"] == "unavailable"
    assert res["totals"]["cost"] == 100000.0
    assert res["totals"]["market_value"] is None


# ---------------------------------------------------------------------------
# 5. 空持仓契约
# ---------------------------------------------------------------------------

def test_get_portfolio_empty_holdings(tmp_pf_dir, monkeypatch):
    _seed_portfolio(tmp_pf_dir, [])
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {})
    res = pf.get_portfolio()
    assert res["data_status"] == "normal"
    assert res["quote_coverage"] == {
        "valid_holdings": 0,
        "total_holdings": 0,
        "complete": False,
    }
    assert res["holdings"] == []
    assert res["totals"] == {
        "market_value": 0.0,
        "cost": 0.0,
        "pnl": 0.0,
        "pnl_pct": 0.0,
    }


# ---------------------------------------------------------------------------
# 6. 清仓数据不受行情影响
# ---------------------------------------------------------------------------

def test_get_portfolio_closed_positions_unaffected(tmp_pf_dir, monkeypatch):
    closed = [{
        "code": "600519", "name": "贵州茅台", "date": "2026-01-01",
        "price": 1800.0, "shares": 100, "cost": 1600.0, "pnl": 20000.0, "pnl_pct": 12.5
    }]
    _seed_portfolio(tmp_pf_dir, [{"code": "000001", "shares": 100, "cost": 10.0}], closed=closed)
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {})  # 行情失败
    res = pf.get_portfolio()
    assert res["closed"] == closed
    assert res["realized_pnl"] == 20000.0


# ---------------------------------------------------------------------------
# 7. /api/portfolio HTTP 接口 JSON 序列化测试
# ---------------------------------------------------------------------------

def test_api_portfolio_returns_nullable_json(tmp_pf_dir, monkeypatch):
    _seed_portfolio(tmp_pf_dir, [
        {"code": "600519", "shares": 100, "cost": 1600.0},
        {"code": "000001", "shares": 200, "cost": 10.0},
    ])
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {"600519": {"price": 1800.0}})
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["data_status"] == "partial"
    assert data["quote_coverage"]["complete"] is False
    assert data["totals"]["market_value"] is None
    assert data["totals"]["cost"] == 162000.0
    by_code = {h["code"]: h for h in data["holdings"]}
    assert by_code["600519"]["price"] == 1800.0
    assert by_code["000001"]["price"] is None
