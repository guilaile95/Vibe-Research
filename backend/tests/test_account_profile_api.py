"""GET /api/account-profile 与 PUT /api/account-profile 离线 API 测试（不接触真实用户目录）。"""
from __future__ import annotations

import os
import json

import pytest
from fastapi.testclient import TestClient

import app as app_module
import account_profile

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated_account_dir(tmp_path, monkeypatch):
    """每个测试在临时 CACHE_DIR 内操作，不影响真实 ~/.vibe-research。"""
    monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path / "data"))


def _account_file() -> str:
    return account_profile._account_path()


def test_get_unconfigured():
    """未配置 → configured=false, data=null。"""
    assert not os.path.exists(_account_file())
    resp = client.get("/api/account-profile")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False, "data": None}


def test_put_and_get_round_trip():
    """正常保存 → 读取一致。"""
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
    """Pydantic extra=forbid 拒绝未知字段。"""
    resp = client.put("/api/account-profile", json={
        "total_assets": 100000, "available_cash": 20000, "foo": "bar",
    })
    assert resp.status_code == 400


def test_put_does_not_modify_portfolio():
    """保存账户资金不改临时 CACHE_DIR 内的 portfolio.json sentinel。"""
    portfolio_file = os.path.join(account_profile.CACHE_DIR, "portfolio.json")
    os.makedirs(account_profile.CACHE_DIR, exist_ok=True)
    sentinel = {"holdings": [], "last_refresh": "sentinel"}
    with open(portfolio_file, "w", encoding="utf-8") as f:
        json.dump(sentinel, f)

    client.put("/api/account-profile", json={
        "total_assets": 100000, "available_cash": 20000,
    })

    with open(portfolio_file, encoding="utf-8") as f:
        after = json.load(f)
    assert after == sentinel


def test_api_only_writes_tmp_cache_dir(tmp_path):
    """PUT 只写入临时 CACHE_DIR，不写外部路径。"""
    # 在临时目录放一个 portfolio sentinel 用于验证
    portfolio_file = os.path.join(account_profile.CACHE_DIR, "portfolio.json")
    os.makedirs(account_profile.CACHE_DIR, exist_ok=True)
    sentinel = {"holdings": [], "last_refresh": "sentinel"}
    with open(portfolio_file, "w", encoding="utf-8") as f:
        json.dump(sentinel, f)

    client.put("/api/account-profile", json={
        "total_assets": 500000, "available_cash": 100000,
    })

    # 账户文件只应在 CACHE_DIR 内
    acct_file = os.path.join(account_profile.CACHE_DIR, "account_profile.json")
    assert os.path.exists(acct_file), "账户文件应生成在临时 CACHE_DIR"

    # portfolio sentinel 不变
    with open(portfolio_file, encoding="utf-8") as f:
        assert json.load(f) == sentinel

    # CACHE_DIR 外不应有 account_profile 写入（不读取真实 HOME 来验证）
    dir_files = os.listdir(account_profile.CACHE_DIR)
    tmp_files = [f for f in dir_files if f.startswith("account_profile") and ".tmp." in f]
    assert len(tmp_files) == 0, f"有残留临时文件: {tmp_files}"
