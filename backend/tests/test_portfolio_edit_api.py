"""PUT /api/portfolio/holding 与 DELETE 持仓精确维护离线 API 测试。

全部使用临时目录，不触碰真实用户 portfolio.json / account_profile.json。
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


def _acct_path(tmp_path) -> str:
    return str(tmp_path / "account_profile.json")


def _read_pf(tmp_path) -> dict:
    p = _pf_path(tmp_path)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"holdings": [], "last_refresh": None}


def _write_pf(tmp_path, d: dict) -> None:
    with open(_pf_path(tmp_path), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)


def _seed(tmp_path, holdings: list[dict], closed: list | None = None) -> None:
    d: dict = {"holdings": holdings, "last_refresh": None}
    if closed is not None:
        d["closed"] = closed
    _write_pf(tmp_path, d)


def _by_code(data: dict) -> dict:
    return {h["code"]: h for h in data.get("holdings", [])}


# ---------------------------------------------------------------------------
# PUT 成功：精确替换，不加权
# ---------------------------------------------------------------------------

def test_put_exact_replace(tmp_data):
    """PUT 精确替换数量与成本，不执行加权平均。"""
    _seed(tmp_data, [{"code": "001896", "shares": 1500, "cost": 13.55}])
    r = client.put("/api/portfolio/holding", json={
        "code": "001896", "shares": 1800, "cost": 14.20,
    })
    assert r.status_code == 200
    h = _by_code(r.json()["data"])["001896"]
    assert h["shares"] == 1800
    assert h["cost"] == 14.20

    r2 = client.get("/api/portfolio")
    assert r2.status_code == 200
    h2 = _by_code(r2.json()["data"])["001896"]
    assert h2["shares"] == 1800
    assert h2["cost"] == 14.20

    raw = _read_pf(tmp_data)
    assert raw["holdings"][0]["shares"] == 1800
    assert raw["holdings"][0]["cost"] == 14.20


def test_put_not_weighted_merge(tmp_data):
    """PUT 不是 POST 加权：从 1000@1600 改为 500@1700，结果即为 500/1700。"""
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 1600.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 500, "cost": 1700.0,
    })
    assert r.status_code == 200
    h = r.json()["data"]["holdings"][0]
    assert h["shares"] == 500
    assert h["cost"] == 1700.0
    # 若错误地按加权：(1000*1600+500*1700)/1500 ≈ 1633.33
    assert h["cost"] != pytest.approx((1000 * 1600 + 500 * 1700) / 1500, rel=1e-3)


def test_put_allows_odd_lot_shares(tmp_data):
    """shares 不要求 100 股整数倍（零股/送股兼容）。"""
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 137, "cost": 10.5,
    })
    assert r.status_code == 200
    assert _by_code(r.json()["data"])["600519"]["shares"] == 137


def test_put_allows_negative_cost(tmp_data):
    """成本价允许负值（既有业务语义）。"""
    _seed(tmp_data, [{"code": "600519", "shares": 100, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 100, "cost": -5.5,
    })
    assert r.status_code == 200
    assert _by_code(r.json()["data"])["600519"]["cost"] == -5.5


# ---------------------------------------------------------------------------
# PUT 失败路径
# ---------------------------------------------------------------------------

def test_put_nonexistent_404(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 1600.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "000001", "shares": 500, "cost": 10.0,
    })
    assert r.status_code == 404
    detail = r.json().get("detail", "")
    assert "000001" in detail or "不在" in detail


def test_put_shares_zero_400(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 0, "cost": 10.0,
    })
    assert r.status_code == 400


def test_put_shares_negative_400(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": -100, "cost": 10.0,
    })
    assert r.status_code == 400


def test_put_shares_float_400(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 100.5, "cost": 10.0,
    })
    assert r.status_code == 400


def test_put_shares_string_400(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": "100", "cost": 10.0,
    })
    assert r.status_code == 400


def test_put_shares_bool_400(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": True, "cost": 10.0,
    })
    assert r.status_code == 400


def test_put_cost_string_400(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 100, "cost": "10.0",
    })
    assert r.status_code == 400


def test_put_cost_bool_400(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 100, "cost": True,
    })
    assert r.status_code == 400


def test_put_cost_nan_400(tmp_data):
    """NaN 经 JSON 特殊序列化；Pydantic/handler 应 400。"""
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    # Python json 默认不允许 NaN 写出 unless allow_nan；用 content 发非标准 JSON
    r = client.put(
        "/api/portfolio/holding",
        content='{"code":"600519","shares":100,"cost":NaN}',
        headers={"Content-Type": "application/json"},
    )
    # 非法 JSON 或校验失败 → 4xx，不得 200
    assert r.status_code >= 400
    assert r.status_code < 500


def test_put_cost_infinity_400(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put(
        "/api/portfolio/holding",
        content='{"code":"600519","shares":100,"cost":Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code >= 400
    assert r.status_code < 500


def test_put_unknown_field_400(tmp_data):
    """extra=forbid → 未知字段 400。"""
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 10.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 100, "cost": 10.0, "extra": 1,
    })
    assert r.status_code == 400


def test_put_failure_portfolio_bytes_unchanged(tmp_data):
    """编辑失败（404）时 portfolio.json 字节不变。"""
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 1600.0}])
    with open(_pf_path(tmp_data), "rb") as f:
        before = f.read()
    r = client.put("/api/portfolio/holding", json={
        "code": "000001", "shares": 500, "cost": 10.0,
    })
    assert r.status_code == 404
    with open(_pf_path(tmp_data), "rb") as f:
        after = f.read()
    assert before == after


def test_put_failure_validation_bytes_unchanged(tmp_data):
    """校验失败时 portfolio.json 字节不变。"""
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 1600.0}])
    with open(_pf_path(tmp_data), "rb") as f:
        before = f.read()
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": -1, "cost": 10.0,
    })
    assert r.status_code == 400
    with open(_pf_path(tmp_data), "rb") as f:
        after = f.read()
    assert before == after


# ---------------------------------------------------------------------------
# POST 加权合并保持原行为
# ---------------------------------------------------------------------------

def test_post_same_code_still_merges(tmp_data):
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
# DELETE
# ---------------------------------------------------------------------------

def test_delete_does_not_affect_other_holdings(tmp_data):
    _seed(tmp_data, [
        {"code": "600519", "shares": 100, "cost": 10.0},
        {"code": "000001", "shares": 200, "cost": 11.0},
    ])
    r = client.request("DELETE", "/api/portfolio/holding", params={"code": "600519"})
    assert r.status_code == 200
    codes = {h["code"] for h in r.json()["data"]["holdings"]}
    assert "600519" not in codes
    assert "000001" in codes
    h = _by_code(r.json()["data"])["000001"]
    assert h["shares"] == 200
    assert h["cost"] == 11.0


def test_delete_does_not_create_closed_record(tmp_data):
    _seed(tmp_data, [{"code": "600519", "shares": 100, "cost": 10.0}], closed=[])
    r = client.request("DELETE", "/api/portfolio/holding", params={"code": "600519"})
    assert r.status_code == 200
    assert r.json()["data"].get("closed", []) == []
    raw = _read_pf(tmp_data)
    assert raw.get("closed", []) == []
    assert raw["holdings"] == []


# ---------------------------------------------------------------------------
# 账户资金隔离
# ---------------------------------------------------------------------------

def test_put_does_not_modify_account_profile(tmp_data):
    sentinel = {
        "total_assets": 100000.0,
        "available_cash": 20000.0,
        "updated_at": "2026-01-01 00:00:00",
    }
    with open(_acct_path(tmp_data), "w", encoding="utf-8") as f:
        json.dump(sentinel, f)
    _seed(tmp_data, [{"code": "600519", "shares": 1000, "cost": 1600.0}])
    r = client.put("/api/portfolio/holding", json={
        "code": "600519", "shares": 500, "cost": 1700.0,
    })
    assert r.status_code == 200
    with open(_acct_path(tmp_data), encoding="utf-8") as f:
        assert json.load(f) == sentinel


def test_delete_does_not_modify_account_profile(tmp_data):
    sentinel = {
        "total_assets": 100000.0,
        "available_cash": 20000.0,
        "updated_at": "2026-01-01 00:00:00",
    }
    with open(_acct_path(tmp_data), "w", encoding="utf-8") as f:
        json.dump(sentinel, f)
    _seed(tmp_data, [{"code": "600519", "shares": 100, "cost": 10.0}])
    r = client.request("DELETE", "/api/portfolio/holding", params={"code": "600519"})
    assert r.status_code == 200
    with open(_acct_path(tmp_data), encoding="utf-8") as f:
        assert json.load(f) == sentinel


# ---------------------------------------------------------------------------
# 非 portfolio 端点错误码不受影响
# ---------------------------------------------------------------------------

def test_other_api_validation_still_422(tmp_data):
    """未知字段在 advice 等端点仍可 422；holding 为 400。"""
    # portfolio/advice 带非法 llm 结构
    r = client.post("/api/portfolio/advice", json={"llm": "not-an-object"})
    assert r.status_code == 422

    # health 仍正常
    assert client.get("/api/health").status_code == 200



# ---------------------------------------------------------------------------
# CORS OPTIONS 预检测试 (PUT)
# ---------------------------------------------------------------------------

def test_cors_options_preflight_portfolio_holding():
    """OPTIONS /api/portfolio/holding 支持 PUT 预检。"""
    r = client.options(
        "/api/portfolio/holding",
        headers={
            "Origin": "http://localhost:5899",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    allow_methods = r.headers.get("access-control-allow-methods", "")
    assert "PUT" in [m.strip() for m in allow_methods.split(",")]
    allow_origin = r.headers.get("access-control-allow-origin", "")
    assert allow_origin == "http://localhost:5899"  # P0-SEC1：默认白名单，通配符不再是合法契约


def test_cors_options_preflight_account_profile():
    """OPTIONS /api/account-profile 支持 PUT 预检。"""
    r = client.options(
        "/api/account-profile",
        headers={
            "Origin": "http://localhost:5899",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    allow_methods = r.headers.get("access-control-allow-methods", "")
    assert "PUT" in [m.strip() for m in allow_methods.split(",")]
    allow_origin = r.headers.get("access-control-allow-origin", "")
    assert allow_origin == "http://localhost:5899"  # P0-SEC1：默认白名单，通配符不再是合法契约
