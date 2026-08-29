"""Campaign API v0.1 专项测试（P0-S2A，test-only FastAPI app，不触碰 app.py）。

覆盖：POST 201 → DRAFT / strategy 枚举 / 无 PATCH/PUT/DELETE /
客户端无法伪造 status / 404 / 422 / 确定性 list + 过滤 / 重复创建独立 ID /
500 脱敏（不泄漏 SQL/path/traceback）/ 域隔离（无 forbidden imports）。
"""
from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import campaign_router
import campaign_service

_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(campaign_router.router)
    return app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "VIBE_RESEARCH_CAMPAIGN_DB", str(tmp_path / "campaigns.sqlite3")
    )
    return TestClient(make_app())


def _post(client, **body) -> dict:
    return client.post("/api/campaigns", json=body)


# ---------------------------------------------------------------------------
# Create contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("strategy", ["SHORT", "SWING", "MEDIUM"])
def test_post_valid_201_draft(client, strategy):
    r = _post(client, security_code="600519", strategy=strategy)
    assert r.status_code == 201
    data = r.json()["data"]
    assert _ID_RE.fullmatch(data["campaign_id"])
    assert data["security_code"] == "600519"
    assert data["strategy"] == strategy
    assert data["status"] == "DRAFT"  # status 恒为服务端 DRAFT
    assert _TS_RE.fullmatch(data["created_at"])
    assert set(data) == {"campaign_id", "security_code", "strategy", "status", "created_at"}


def test_post_invalid_strategy_422(client):
    """schema 级（Literal）校验由 FastAPI 处理 → 422；不得泄漏内部信息。"""
    r = _post(client, security_code="600519", strategy="MEDIUM2")
    assert r.status_code == 422
    body = str(r.json())
    for leaked in ("sqlite", "Users", "Traceback", "SELECT", "secret"):
        assert leaked not in body


def test_post_lowercase_strategy_422(client):
    """lowercase/typo strategy 不被 silent normalize → 422。"""
    r = _post(client, security_code="600519", strategy="short")
    assert r.status_code == 422
    body = str(r.json())
    for leaked in ("sqlite", "Users", "Traceback", "SELECT", "secret"):
        assert leaked not in body


def test_post_invalid_security_code_422(client):
    for bad in ("12345", "abcdef", "6005191", ""):
        r = _post(client, security_code=bad, strategy="SHORT")
        assert r.status_code == 422
        assert r.json()["detail"] == "Campaign 参数无效"


def test_post_client_cannot_forge_status(client):
    """extra="forbid"：请求体带 status 字段 → 422，客户端无法伪造成 ACTIVE。"""
    r = _post(client, security_code="600519", strategy="SHORT", status="ACTIVE")
    assert r.status_code == 422
    assert client.get("/api/campaigns").json()["data"] == []


def test_post_extra_unknown_field_422(client):
    r = _post(client, security_code="600519", strategy="SHORT", campaign_id="x")
    assert r.status_code == 422


def test_no_patch_put_delete_routes(client):
    assert client.patch("/api/campaigns/x", json={}).status_code in (404, 405)
    assert client.put("/api/campaigns/x", json={}).status_code in (404, 405)
    assert client.delete("/api/campaigns/x").status_code in (404, 405)
    assert client.patch("/api/campaigns/x/transitions", json={}).status_code in (404, 405)
    assert client.put("/api/campaigns/x/transitions", json={}).status_code in (404, 405)
    assert client.delete("/api/campaigns/x/transitions").status_code in (404, 405)


# ---------------------------------------------------------------------------
# GET contract
# ---------------------------------------------------------------------------
def test_get_by_id_exact(client):
    created = _post(client, security_code="600519", strategy="MEDIUM").json()["data"]
    r = client.get(f"/api/campaigns/{created['campaign_id']}")
    assert r.status_code == 200
    assert r.json()["data"] == created


def test_get_unknown_404_stable(client):
    cid = "campaign_" + "0" * 32
    r = client.get(f"/api/campaigns/{cid}")
    assert r.status_code == 404
    assert r.json()["detail"] == "Campaign 不存在"


def test_get_invalid_id_format_422(client):
    """空路径命中 list 路由；其余非法 ID 格式 → 422 稳定 detail。"""
    for bad in ("abc", "campaign_xyz", "campaign_123"):
        r = client.get(f"/api/campaigns/{bad}")
        assert r.status_code == 422
        assert r.json()["detail"] == "Campaign 参数无效"


def test_list_empty_and_deterministic(client):
    assert client.get("/api/campaigns").json() == {"data": []}
    for i in range(3):
        _post(client, security_code=f"{600000 + i}", strategy="SHORT")
    recs = client.get("/api/campaigns").json()["data"]
    keys = [(r["created_at"], r["campaign_id"]) for r in recs]
    assert keys == sorted(keys)  # 确定性全序


def test_list_filters(client):
    _post(client, security_code="600519", strategy="MEDIUM")
    _post(client, security_code="600519", strategy="SWING")
    _post(client, security_code="000001", strategy="SHORT")
    only = client.get("/api/campaigns", params={"security_code": "600519"}).json()["data"]
    assert len(only) == 2 and all(r["security_code"] == "600519" for r in only)
    assert len(client.get("/api/campaigns", params={"strategy": "SHORT"}).json()["data"]) == 1
    assert len(client.get("/api/campaigns", params={"status": "DRAFT"}).json()["data"]) == 3


def test_list_invalid_filter_422(client):
    for params in ({"security_code": "123"}, {"strategy": "SHORT2"}, {"status": "ACTIVE2"}):
        r = client.get("/api/campaigns", params=params)
        assert r.status_code == 422
        assert r.json()["detail"] == "Campaign 参数无效"


# ---------------------------------------------------------------------------
# Multi-campaign
# ---------------------------------------------------------------------------
def test_twice_same_security_strategy_two_campaigns(client):
    a = _post(client, security_code="600519", strategy="SWING").json()["data"]
    b = _post(client, security_code="600519", strategy="SWING").json()["data"]
    assert a["campaign_id"] != b["campaign_id"]
    assert client.get(f"/api/campaigns/{a['campaign_id']}").json()["data"] == a
    assert client.get(f"/api/campaigns/{b['campaign_id']}").json()["data"] == b
    assert len(client.get("/api/campaigns").json()["data"]) == 2


# ---------------------------------------------------------------------------
# API Security（500 脱敏）
# ---------------------------------------------------------------------------
def test_unexpected_error_500_sanitized(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(
            "ProxyError https://secret-provider.example/token=abc "
            "C:\\Users\\evil\\campaigns.sqlite3 SELECT * FROM campaigns"
        )

    monkeypatch.setattr(campaign_router.campaign_service, "create_campaign", boom)
    r = _post(client, security_code="600519", strategy="SHORT")
    assert r.status_code == 500
    body = str(r.json())
    assert r.json()["detail"] == "Campaign 服务暂不可用"
    for leaked in ("secret-provider", "token=abc", "Users", "sqlite3", "SELECT", "ProxyError", "Traceback"):
        assert leaked not in body


def test_list_internal_error_500_sanitized(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db path leak /var/data/campaigns.sqlite3")

    monkeypatch.setattr(campaign_router.campaign_service, "list_campaigns", boom)
    r = client.get("/api/campaigns")
    assert r.status_code == 500
    assert r.json()["detail"] == "Campaign 服务暂不可用"
    assert "campaigns.sqlite3" not in str(r.json())


# ---------------------------------------------------------------------------
# 域隔离（无 Account/NAV/portfolio/trade ledger/Market Regime/AI/app 依赖）
# ---------------------------------------------------------------------------
def test_campaign_modules_do_not_import_forbidden_domains():
    import campaign_store

    for mod in (campaign_store, campaign_service, campaign_router):
        for name in (
            "app", "portfolio", "trade_ledger", "account_reality",
            "market_regime", "ai_result", "position_reality", "account_event",
        ):
            assert name not in mod.__dict__, f"{mod.__name__} imports {name}"


# ---------------------------------------------------------------------------
# S2B. Transition API（P0-S2B）
# ---------------------------------------------------------------------------
def _post_transition(client, cid, expected, to) -> dict:
    return client.post(
        f"/api/campaigns/{cid}/transitions",
        json={"expected_status": expected, "to_status": to},
    )


def test_transition_api_success_200(client):
    created = _post(client, security_code="600519", strategy="SWING").json()["data"]
    r = _post_transition(client, created["campaign_id"], "DRAFT", "RESEARCHING")
    assert r.status_code == 200  # 仓库动作型 POST 语义：200
    body = r.json()["data"]
    assert body["campaign"]["status"] == "RESEARCHING"
    assert body["campaign"]["strategy"] == "SWING"
    assert body["transition"]["from_status"] == "DRAFT"
    assert body["transition"]["to_status"] == "RESEARCHING"
    assert body["transition"]["campaign_id"] == created["campaign_id"]
    assert body["transition"]["transition_id"].startswith("campaign_transition_")


def test_transition_api_requires_trade_proven_activation(client):
    created = _post(client, security_code="600519", strategy="MEDIUM").json()["data"]
    cid = created["campaign_id"]
    for frm, to in (
        ("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY"),
    ):
        r = _post_transition(client, cid, frm, to)
        assert r.status_code == 200
        assert r.json()["data"]["campaign"]["status"] == to
    assert _post_transition(client, cid, "PRE-ENTRY", "ACTIVE").status_code == 409
    assert client.get(f"/api/campaigns/{cid}").json()["data"]["status"] == "PRE-ENTRY"


def test_transition_api_unknown_campaign_404(client):
    cid = "campaign_" + "0" * 32
    r = _post_transition(client, cid, "DRAFT", "RESEARCHING")
    assert r.status_code == 404
    assert r.json()["detail"] == "Campaign 不存在"


def test_transition_api_cas_mismatch_409(client):
    created = _post(client, security_code="600519", strategy="SHORT").json()["data"]
    cid = created["campaign_id"]
    assert _post_transition(client, cid, "DRAFT", "RESEARCHING").status_code == 200
    r = _post_transition(client, cid, "DRAFT", "REJECTED")  # stale expected
    assert r.status_code == 409
    assert r.json()["detail"] == "Campaign 状态冲突"
    assert _post(client, security_code="600519", strategy="SHORT").json()["data"]


def test_transition_api_illegal_edge_409(client):
    created = _post(client, security_code="600519", strategy="SHORT").json()["data"]
    cid = created["campaign_id"]
    r = _post_transition(client, cid, "DRAFT", "ACTIVE")
    assert r.status_code == 409
    assert r.json()["detail"] == "Campaign 状态冲突"
    assert _post_transition(client, cid, "DRAFT", "DRAFT").status_code == 409
    assert client.get(f"/api/campaigns/{cid}").json()["data"]["status"] == "DRAFT"


def test_transition_api_invalid_enum_422(client):
    created = _post(client, security_code="600519", strategy="SHORT").json()["data"]
    cid = created["campaign_id"]
    r = client.post(
        f"/api/campaigns/{cid}/transitions",
        json={"expected_status": "DRAFT2", "to_status": "RESEARCHING"},
    )
    assert r.status_code == 422
    body = str(r.json())
    for leaked in ("sqlite", "Users", "Traceback", "SELECT", "secret"):
        assert leaked not in body
    r2 = client.post(
        f"/api/campaigns/{cid}/transitions",
        json={"expected_status": "DRAFT", "to_status": "short"},
    )
    assert r2.status_code == 422


def test_transition_api_extra_field_422(client):
    created = _post(client, security_code="600519", strategy="SHORT").json()["data"]
    r = client.post(
        f"/api/campaigns/{created['campaign_id']}/transitions",
        json={"expected_status": "DRAFT", "to_status": "RESEARCHING", "strategy": "MEDIUM"},
    )
    assert r.status_code == 422  # 不得借 transition body 传新 strategy


def test_transition_api_unexpected_error_500_sanitized(client, monkeypatch):
    created = _post(client, security_code="600519", strategy="SHORT").json()["data"]

    def boom(*a, **k):
        raise RuntimeError(
            "ProxyError https://secret-provider.example/token=abc "
            "C:\\Users\\evil\\campaigns.sqlite3 SELECT * FROM campaign_transitions"
        )

    monkeypatch.setattr(campaign_router.campaign_service, "transition_campaign", boom)
    r = _post_transition(client, created["campaign_id"], "DRAFT", "RESEARCHING")
    assert r.status_code == 500
    body = str(r.json())
    assert r.json()["detail"] == "Campaign 服务暂不可用"
    for leaked in ("secret-provider", "token=abc", "Users", "sqlite3", "SELECT", "ProxyError", "Traceback"):
        assert leaked not in body


def test_transition_history_api_deterministic(client):
    created = _post(client, security_code="600519", strategy="SHORT").json()["data"]
    cid = created["campaign_id"]
    assert client.get(f"/api/campaigns/{cid}/transitions").json() == {"data": []}
    _post_transition(client, cid, "DRAFT", "RESEARCHING")
    _post_transition(client, cid, "RESEARCHING", "PRE-ENTRY")
    r = client.get(f"/api/campaigns/{cid}/transitions")
    assert r.status_code == 200
    history = r.json()["data"]
    assert [h["to_status"] for h in history] == ["RESEARCHING", "PRE-ENTRY"]
    keys = [(h["transitioned_at"], h["transition_id"]) for h in history]
    assert keys == sorted(keys)
    assert set(history[0]) == {
        "transition_id", "campaign_id", "from_status", "to_status", "transitioned_at",
    }


def test_transition_history_api_invalid_id_422(client):
    r = client.get("/api/campaigns/abc/transitions")
    assert r.status_code == 422
    assert r.json()["detail"] == "Campaign 参数无效"
