"""POST /api/portfolio/holding 与 POST /api/portfolio/close 严格输入校验测试。

全部使用临时目录，不触碰真实用户 portfolio.json / account_profile.json。
NaN / Infinity 使用原始 content= 构造，避免测试客户端提前变更表示。
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

import account_profile
import app as app_module
import astock
import portfolio as pf

client = TestClient(app_module.app)


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    """隔离持仓与账户资金到临时目录；行情打桩。"""
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(account_profile, "ACCOUNT_FILE", str(tmp_path / "account_profile.json"))
    monkeypatch.setattr(
        astock,
        "tencent_quote",
        lambda codes: {c: {"name": f"股{c}", "price": 10.0} for c in codes},
    )
    return tmp_path


def _pf_path(tmp_path) -> str:
    return str(tmp_path / "portfolio.json")


def _read_pf(tmp_path) -> dict:
    p = _pf_path(tmp_path)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"holdings": [], "last_refresh": None}


def _seed(tmp_path, holdings: list[dict]) -> None:
    with open(_pf_path(tmp_path), "w", encoding="utf-8") as f:
        json.dump({"holdings": holdings, "last_refresh": None}, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# POST /api/portfolio/holding — 成功路径
# ---------------------------------------------------------------------------

def test_post_holding_normal(tmp_data):
    """正常新增：整数 shares + 有效 cost。"""
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 1500, "cost": 13.55,
    })
    assert r.status_code == 200
    h = r.json()["data"]["holdings"][0]
    assert h["code"] == "001896"
    assert h["shares"] == 1500
    assert h["cost"] == 13.55


def test_post_holding_odd_lot(tmp_data):
    """137 股合法（不要求 100 整数倍）。"""
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 137, "cost": 10.0,
    })
    assert r.status_code == 200
    assert r.json()["data"]["holdings"][0]["shares"] == 137


def test_post_holding_negative_cost(tmp_data):
    """负 cost 合法（既有业务语义）。"""
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 100, "cost": -5.5,
    })
    assert r.status_code == 200
    assert r.json()["data"]["holdings"][0]["cost"] == -5.5


def test_post_holding_zero_cost(tmp_data):
    """零 cost 合法。"""
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 100, "cost": 0,
    })
    assert r.status_code == 200
    assert r.json()["data"]["holdings"][0]["cost"] == 0


def test_post_holding_same_code_merges(tmp_data):
    """连续新增同代码仍按加权平均成本合并。"""
    r1 = client.post("/api/portfolio/holding", json={
        "code": "600519", "shares": 1000, "cost": 1600.0,
    })
    assert r1.status_code == 200
    r2 = client.post("/api/portfolio/holding", json={
        "code": "600519", "shares": 500, "cost": 1700.0,
    })
    assert r2.status_code == 200
    h = r2.json()["data"]["holdings"][0]
    assert h["shares"] == 1500
    assert h["cost"] == round((1000 * 1600 + 500 * 1700) / 1500, 4)


# ---------------------------------------------------------------------------
# POST /api/portfolio/holding — 失败路径
# ---------------------------------------------------------------------------

def test_post_holding_shares_string_400(tmp_data):
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": "100", "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_holding_shares_bool_400(tmp_data):
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": True, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_holding_shares_float_100_0_400(tmp_data):
    """float 100.0 应被拒绝（shares 必须是 int）。"""
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 100.0, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_holding_shares_float_100_5_400(tmp_data):
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 100.5, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_holding_cost_string_400(tmp_data):
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 100, "cost": "12.5",
    })
    assert r.status_code == 400


def test_post_holding_cost_bool_400(tmp_data):
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 100, "cost": True,
    })
    assert r.status_code == 400


def test_post_holding_cost_nan_400(tmp_data):
    r = client.post(
        "/api/portfolio/holding",
        content='{"code":"001896","shares":100,"cost":NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_holding_cost_infinity_400(tmp_data):
    r = client.post(
        "/api/portfolio/holding",
        content='{"code":"001896","shares":100,"cost":Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_holding_cost_neg_infinity_400(tmp_data):
    r = client.post(
        "/api/portfolio/holding",
        content='{"code":"001896","shares":100,"cost":-Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_holding_unknown_field_400(tmp_data):
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": 100, "cost": 10.0, "extra": 1,
    })
    assert r.status_code == 400


def test_post_holding_invalid_code_400(tmp_data):
    r = client.post("/api/portfolio/holding", json={
        "code": "abc", "shares": 100, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_holding_failure_bytes_unchanged(tmp_data):
    """校验失败时 portfolio.json 不被创建或字节不变。"""
    p = _pf_path(tmp_data)
    before = None
    if os.path.exists(p):
        with open(p, "rb") as f:
            before = f.read()
    r = client.post("/api/portfolio/holding", json={
        "code": "001896", "shares": "bad", "cost": 10.0,
    })
    assert r.status_code == 400
    if before is None:
        # 文件原本不存在，校验失败后仍不应存在
        assert not os.path.exists(p)
    else:
        with open(p, "rb") as f:
            assert f.read() == before


# ---------------------------------------------------------------------------
# POST /api/portfolio/close — 成功路径
# ---------------------------------------------------------------------------

def test_post_close_normal(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 1500, "cost": 13.55}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": 1500, "cost": 13.55,
    })
    assert r.status_code == 200
    closed = r.json()["data"]["closed"]
    assert len(closed) == 1
    assert closed[0]["code"] == "001896"
    assert closed[0]["shares"] == 1500
    assert closed[0]["price"] == 15.0


def test_post_close_odd_lot(tmp_data):
    """137 股合法。"""
    _seed(tmp_data, [{"code": "001896", "shares": 137, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": 137, "cost": 10.0,
    })
    assert r.status_code == 200
    assert r.json()["data"]["closed"][0]["shares"] == 137


def test_post_close_negative_cost(tmp_data):
    """负 cost 合法。"""
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": -5.5}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 10.0,
        "shares": 100, "cost": -5.5,
    })
    assert r.status_code == 200
    assert r.json()["data"]["closed"][0]["cost"] == -5.5


def test_post_close_zero_cost(tmp_data):
    """零 cost 合法。"""
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 10.0,
        "shares": 100, "cost": 0,
    })
    assert r.status_code == 200
    assert r.json()["data"]["closed"][0]["cost"] == 0


# ---------------------------------------------------------------------------
# POST /api/portfolio/close — 失败路径
# ---------------------------------------------------------------------------

def test_post_close_price_string_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": "15.0",
        "shares": 100, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_close_price_bool_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": True,
        "shares": 100, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_close_price_nan_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post(
        "/api/portfolio/close",
        content='{"code":"001896","date":"2026-07-22","price":NaN,"shares":100,"cost":10.0}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_close_price_infinity_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post(
        "/api/portfolio/close",
        content='{"code":"001896","date":"2026-07-22","price":Infinity,"shares":100,"cost":10.0}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_close_price_non_positive_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 0,
        "shares": 100, "cost": 10.0,
    })
    assert r.status_code == 400

    r2 = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": -1,
        "shares": 100, "cost": 10.0,
    })
    assert r2.status_code == 400


def test_post_close_shares_string_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": "100", "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_close_shares_bool_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": True, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_close_shares_float_100_0_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": 100.0, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_close_shares_float_100_5_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": 100.5, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_close_cost_string_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": 100, "cost": "10.0",
    })
    assert r.status_code == 400


def test_post_close_cost_bool_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": 100, "cost": True,
    })
    assert r.status_code == 400


def test_post_close_cost_nan_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post(
        "/api/portfolio/close",
        content='{"code":"001896","date":"2026-07-22","price":15.0,"shares":100,"cost":NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_close_cost_infinity_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post(
        "/api/portfolio/close",
        content='{"code":"001896","date":"2026-07-22","price":15.0,"shares":100,"cost":Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_post_close_unknown_field_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": 15.0,
        "shares": 100, "cost": 10.0, "extra": 1,
    })
    assert r.status_code == 400


def test_post_close_invalid_code_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "abc", "date": "2026-07-22", "price": 15.0,
        "shares": 100, "cost": 10.0,
    })
    assert r.status_code == 400

    r2 = client.post("/api/portfolio/close", json={
        "code": "12345", "date": "2026-07-22", "price": 15.0,
        "shares": 100, "cost": 10.0,
    })
    assert r2.status_code == 400


def test_post_close_invalid_date_400(tmp_data):
    _seed(tmp_data, [{"code": "001896", "shares": 100, "cost": 10.0}])
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "not-a-date", "price": 15.0,
        "shares": 100, "cost": 10.0,
    })
    assert r.status_code == 400


def test_post_close_failure_bytes_unchanged(tmp_data):
    """校验失败时已存在的 portfolio.json 字节不变。"""
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 1600.0}])
    with open(_pf_path(tmp_data), "rb") as f:
        before = f.read()
    r = client.post("/api/portfolio/close", json={
        "code": "001896", "date": "2026-07-22", "price": "bad",
        "shares": 100, "cost": 10.0,
    })
    assert r.status_code == 400
    with open(_pf_path(tmp_data), "rb") as f:
        assert f.read() == before
