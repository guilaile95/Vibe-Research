"""P0-CS1 — Campaign next-actions read-model HTTP contract tests.

只读 read-model：下一合法动作派生自 frozen graph 单一权威（campaign_store），
前端不得复制 transition graph。响应自包含 campaign 身份；terminal → 空列表。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import campaign_router
import campaign_service
import campaign_store


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


def _create(client, security_code: str = "600519", strategy: str = "SWING") -> dict:
    resp = client.post("/api/campaigns", json={
        "security_code": security_code,
        "strategy": strategy,
    })
    assert resp.status_code == 201
    return resp.json()["data"]


def _next_actions(client, campaign_id: str) -> dict:
    resp = client.get(f"/api/campaigns/{campaign_id}/next-actions")
    assert resp.status_code == 200
    return resp.json()["data"]


def _seed_verified_active(campaign_id: str) -> None:
    """Fixture-only: activation command tests own the cross-authority eligibility gate."""
    campaign_store.transition_campaign(
        campaign_id=campaign_id,
        expected_status="PRE-ENTRY",
        to_status="ACTIVE",
        transition_id="campaign_transition_" + "a" * 32,
        transitioned_at="2026-08-30T00:00:00.000000Z",
    )


def test_draft_next_actions_exact_order(client):
    campaign = _create(client)
    data = _next_actions(client, campaign["campaign_id"])
    assert data["campaign_id"] == campaign["campaign_id"]
    assert data["security_code"] == "600519"
    assert data["strategy"] == "SWING"
    assert data["status"] == "DRAFT"
    assert data["next_actions"] == ["RESEARCHING", "REJECTED", "EXPIRED"]


def test_active_next_actions(client):
    campaign = _create(client)
    client.post(
        f"/api/campaigns/{campaign['campaign_id']}/transitions",
        json={"expected_status": "DRAFT", "to_status": "RESEARCHING"},
    )
    client.post(
        f"/api/campaigns/{campaign['campaign_id']}/transitions",
        json={"expected_status": "RESEARCHING", "to_status": "PRE-ENTRY"},
    )
    _seed_verified_active(campaign["campaign_id"])
    data = _next_actions(client, campaign["campaign_id"])
    assert data["status"] == "ACTIVE"
    assert data["next_actions"] == ["REDUCING", "CLOSED"]


@pytest.mark.parametrize(
    "seed_status, expected",
    [
        ("DRAFT", ["RESEARCHING", "REJECTED", "EXPIRED"]),
        ("RESEARCHING", ["PRE-ENTRY", "REJECTED", "EXPIRED"]),
        ("PRE-ENTRY", ["REJECTED", "EXPIRED"]),
        ("ACTIVE", ["REDUCING", "CLOSED"]),
        ("REDUCING", ["CLOSED"]),
        ("CLOSED", []),
        ("REJECTED", []),
        ("EXPIRED", []),
    ],
)
def test_next_actions_all_frozen_statuses(client, seed_status, expected):
    """全 frozen 枚举：非 terminal 按 graph 声明顺序，terminal 一律空列表。"""
    campaign = _create(client)
    seed_paths = {
        "DRAFT": [],
        "RESEARCHING": [("DRAFT", "RESEARCHING")],
        "PRE-ENTRY": [
            ("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY"),
        ],
        "ACTIVE": [
            ("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY"),
            ("PRE-ENTRY", "ACTIVE"),
        ],
        "REDUCING": [
            ("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY"),
            ("PRE-ENTRY", "ACTIVE"), ("ACTIVE", "REDUCING"),
        ],
        "CLOSED": [
            ("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY"),
            ("PRE-ENTRY", "ACTIVE"), ("ACTIVE", "REDUCING"),
            ("REDUCING", "CLOSED"),
        ],
        "REJECTED": [("DRAFT", "REJECTED")],
        "EXPIRED": [("DRAFT", "EXPIRED")],
    }
    for expected_status, to_status in seed_paths[seed_status]:
        if expected_status == "PRE-ENTRY" and to_status == "ACTIVE":
            _seed_verified_active(campaign["campaign_id"])
            campaign = client.get(
                f"/api/campaigns/{campaign['campaign_id']}"
            ).json()["data"]
            continue
        resp = client.post(
            f"/api/campaigns/{campaign['campaign_id']}/transitions",
            json={"expected_status": expected_status, "to_status": to_status},
        )
        assert resp.status_code == 200
        campaign = resp.json()["data"]["campaign"]
    data = _next_actions(client, campaign["campaign_id"])
    assert data["status"] == seed_status
    assert data["next_actions"] == expected


def test_next_actions_read_only_no_mutation(client):
    """GET next-actions 不得改变 campaign / transition 历史。"""
    campaign = _create(client)
    before = client.get(
        f"/api/campaigns/{campaign['campaign_id']}/transitions"
    ).json()["data"]
    _next_actions(client, campaign["campaign_id"])
    after = client.get(
        f"/api/campaigns/{campaign['campaign_id']}/transitions"
    ).json()["data"]
    assert before == after == []
    assert client.get(
        f"/api/campaigns/{campaign['campaign_id']}"
    ).json()["data"]["status"] == "DRAFT"


def test_next_actions_unknown_campaign_404(client):
    resp = client.get(f"/api/campaigns/campaign_{'f' * 32}/next-actions")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Campaign 不存在"


def test_next_actions_invalid_id_422(client):
    resp = client.get("/api/campaigns/not-an-id/next-actions")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Campaign 参数无效"


def test_next_actions_unexpected_error_500_sanitized(client, monkeypatch):
    def broken(campaign_id):
        raise RuntimeError("secret-detail")

    monkeypatch.setattr(
        campaign_service, "next_campaign_actions", broken
    )
    resp = client.get(f"/api/campaigns/campaign_{'e' * 32}/next-actions")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Campaign 服务暂不可用"
    assert "secret" not in resp.text
