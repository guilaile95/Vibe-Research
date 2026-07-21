"""GET /api/account-profile 与 PUT /api/account-profile 离线 API 测试。"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


def _account_file() -> str:
    # 与 account_profile 模块路径一致
    import account_profile
    return account_profile.ACCOUNT_FILE


def _delete() -> None:
    try:
        os.remove(_account_file())
    except FileNotFoundError:
        pass


def test_get_unconfigured():
    """未配置 → configured=false, data=null。"""
    _delete()
    resp = client.get("/api/account-profile")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False, "data": None}


def test_put_and_get_round_trip():
    """正常保存 → 读取一致。"""
    _delete()
    resp = client.put("/api/account-profile", json={
        "total_assets": 100000, "available_cash": 20000,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["data"]["total_assets"] == 100000.0
    assert body["data"]["available_cash"] == 20000.0
    assert isinstance(body["data"]["updated_at"], str)

    # GET 返回一致
    resp2 = client.get("/api/account-profile")
    assert resp2.status_code == 200
    assert resp2.json() == body


def test_put_rejects_invalid():
    """各类非法输入 → 400，不写文件。"""
    _delete()
    cases = [
        {"total_assets": 0, "available_cash": 0},
        {"total_assets": -100, "available_cash": 0},
        {"total_assets": 100000, "available_cash": -1},
        {"total_assets": 100000, "available_cash": 100001},
        {"total_assets": "100000", "available_cash": 20000},
        {"total_assets": True, "available_cash": 20000},
        {"total_assets": 100000, "available_cash": float("nan")},
        {"total_assets": 100000, "available_cash": 20000, "extra": 1},
        {"total_assets": 100000, "available_cash": 20000,
         "updated_at": "2026-01-01 00:00:00"},
    ]
    for c in cases:
        resp = client.put("/api/account-profile", json=c)
        assert resp.status_code == 400, f"期望 400，得到 {resp.status_code}: {c}"

    # 未写入
    assert client.get("/api/account-profile").json()["configured"] is False


def test_put_extra_fields_forbidden():
    """Pydantic extra=forbid 拒绝未知字段（覆盖 unknown 路径）。"""
    _delete()
    resp = client.put("/api/account-profile", json={
        "total_assets": 100000, "available_cash": 20000, "foo": "bar",
    })
    assert resp.status_code == 400


def test_put_does_not_modify_portfolio():
    """保存账户资金不改 portfolio.json。"""
    _delete()
    import account_profile
    portfolio_file = os.path.join(account_profile.CACHE_DIR, "portfolio.json")
    os.makedirs(account_profile.CACHE_DIR, exist_ok=True)
    sentinel = {"holdings": [], "last_refresh": "sentinel"}
    import json
    with open(portfolio_file, "w", encoding="utf-8") as f:
        json.dump(sentinel, f)

    client.put("/api/account-profile", json={
        "total_assets": 100000, "available_cash": 20000,
    })

    with open(portfolio_file, encoding="utf-8") as f:
        after = json.load(f)
    assert after == sentinel
