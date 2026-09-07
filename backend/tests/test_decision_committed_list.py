"""R5: GET /campaigns/{id}/decision-proposal/committed — read-only per-campaign list."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module
import campaign_service
import frozen_decision_service


def _payload(campaign: dict, decision_suffix: str) -> dict:
    return {
        "security_code": campaign["security_code"],
        "strategy": campaign["strategy"],
        "campaign_id": campaign["campaign_id"],
        "thesis_id": "b" * 32,
        "thesis_revision": 3,
        "asset_view": {}, "trade_view": {}, "portfolio_view": {},
        "next_best_action": "RESEARCH MORE",
        "action_envelope": {},
        "maintain_conditions": [], "upgrade_conditions": [],
        "downgrade_conditions": [], "invalidation_conditions": [],
        "strategy_horizon": "5-20 trading days",
        "review_by": "2026-09-30T00:00:00Z",
        "key_assumptions": [], "event_invalidation_conditions": [],
        "risk_policy_version": "test", "opportunity_policy_version": "test",
        "decision_policy_version": "test", "behavior_model_version": "test",
        "data_quality": {}, "evidence_confidence": 0.8,
        "inference_confidence": "medium", "decision_confidence": None,
        "evidence_refs": [], "risk_refs": [], "source_refs": [],
        "user_confirmed": True,
    }


def test_committed_list_is_empty_without_decisions_and_404_for_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(tmp_path / "campaigns.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(tmp_path / "decisions.sqlite3"))
    client = TestClient(app_module.app)
    campaign = campaign_service.create_campaign("600519", "SWING")

    response = client.get(f"/api/campaigns/{campaign['campaign_id']}/decision-proposal/committed")
    assert response.status_code == 200
    assert response.json()["data"] == {"items": [], "total": 0}

    missing = client.get("/api/campaigns/campaign_" + "b" * 32 + "/decision-proposal/committed")
    assert missing.status_code == 404


def test_committed_list_returns_only_that_campaigns_decisions(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(tmp_path / "campaigns.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(tmp_path / "decisions.sqlite3"))
    client = TestClient(app_module.app)
    campaign = campaign_service.create_campaign("600519", "SWING")
    other = campaign_service.create_campaign("000001", "SHORT")

    frozen_decision_service.freeze_decision(_payload(campaign, "a"))

    own = client.get(f"/api/campaigns/{campaign['campaign_id']}/decision-proposal/committed")
    assert own.status_code == 200
    body = own.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["campaign_id"] == campaign["campaign_id"]
    assert body["items"][0]["decision_id"]
    assert body["items"][0]["committed_at"]
    assert body["items"][0]["next_best_action"] == "RESEARCH MORE"

    foreign = client.get(f"/api/campaigns/{other['campaign_id']}/decision-proposal/committed")
    assert foreign.status_code == 200
    assert foreign.json()["data"] == {"items": [], "total": 0}
