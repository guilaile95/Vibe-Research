from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import campaign_router
import campaign_service
import frozen_decision_service
import position_reality_service
import trade_attribution_runtime
import trade_ledger_service


@pytest.fixture
def pre_entry(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "VIBE_RESEARCH_CAMPAIGN_DB", str(tmp_path / "campaigns.sqlite3")
    )
    campaign = campaign_service.create_campaign("600519", "SWING")
    campaign_service.transition_campaign(
        campaign["campaign_id"], "DRAFT", "RESEARCHING"
    )
    campaign_service.transition_campaign(
        campaign["campaign_id"], "RESEARCHING", "PRE-ENTRY"
    )
    return campaign_service.get_campaign(campaign["campaign_id"])


def _authorities(monkeypatch, campaign_id: str, *, holdings: list[dict]):
    trade = {
        "trade_id": "1" * 32,
        "code": "600519",
        "operation": "buy",
        "execution_status": "full",
        "voided_at": None,
    }
    monkeypatch.setattr(trade_ledger_service, "get_trade", lambda _trade_id: trade)
    monkeypatch.setattr(
        trade_attribution_runtime,
        "reconciliation_for_trade",
        lambda _trade_id: {
            "allocation_state": "ALLOCATED",
            "reconciliation_requirement": "NOT_REQUIRED",
            "campaign_id": campaign_id,
            "decision_id": "decision_" + "2" * 32,
            "attribution_id": "trade_attribution_" + "3" * 32,
        },
    )
    monkeypatch.setattr(
        frozen_decision_service,
        "get_decision",
        lambda _decision_id: {
            "campaign_id": campaign_id,
            "security_code": "600519",
            "next_best_action": "BUY SMALL",
        },
    )
    monkeypatch.setattr(
        position_reality_service, "get_holding_authority_state", lambda: "CANONICAL"
    )
    monkeypatch.setattr(
        position_reality_service,
        "read_current_holdings_snapshot",
        lambda: {"holdings": holdings},
    )
    return trade


def test_pre_entry_cannot_use_generic_active_transition(pre_entry):
    with pytest.raises(campaign_service.CampaignActivationNotEligibleError):
        campaign_service.transition_campaign(
            pre_entry["campaign_id"], "PRE-ENTRY", "ACTIVE"
        )
    campaign, actions = campaign_service.next_campaign_actions(pre_entry["campaign_id"])
    assert campaign["status"] == "PRE-ENTRY"
    assert actions == ["REJECTED", "EXPIRED"]


def test_activation_fails_closed_until_position_reality_proves_open(
    pre_entry, monkeypatch
):
    _authorities(monkeypatch, pre_entry["campaign_id"], holdings=[])
    with pytest.raises(campaign_service.CampaignActivationNotEligibleError):
        campaign_service.activate_pre_entry_campaign_from_trade(
            pre_entry["campaign_id"], "1" * 32
        )
    assert campaign_service.get_campaign(pre_entry["campaign_id"])["status"] == "PRE-ENTRY"


def test_activation_rejects_legacy_position_authority(pre_entry, monkeypatch):
    _authorities(
        monkeypatch,
        pre_entry["campaign_id"],
        holdings=[{"code": "600519", "shares": 100, "cost": 1500.0}],
    )
    monkeypatch.setattr(
        position_reality_service, "get_holding_authority_state", lambda: "LEGACY"
    )
    with pytest.raises(campaign_service.CampaignServiceError):
        campaign_service.activate_pre_entry_campaign_from_trade(
            pre_entry["campaign_id"], "1" * 32
        )
    assert campaign_service.get_campaign(pre_entry["campaign_id"])["status"] == "PRE-ENTRY"


def test_explicit_executed_attributed_buy_activates_exact_campaign(
    pre_entry, monkeypatch
):
    trade = _authorities(
        monkeypatch,
        pre_entry["campaign_id"],
        holdings=[{"code": "600519", "shares": 100, "cost": 1500.0}],
    )
    result = campaign_service.activate_pre_entry_campaign_from_trade(
        pre_entry["campaign_id"], trade["trade_id"]
    )
    assert result["campaign"]["status"] == "ACTIVE"
    assert result["transition"]["from_status"] == "PRE-ENTRY"
    assert result["transition"]["to_status"] == "ACTIVE"
    assert result["trade_id"] == trade["trade_id"]
    assert result["decision_id"] == "decision_" + "2" * 32
    assert result["position_authority"] == "CANONICAL"


def test_activation_http_command_uses_same_fail_closed_authority(pre_entry, monkeypatch):
    trade = _authorities(
        monkeypatch,
        pre_entry["campaign_id"],
        holdings=[{"code": "600519", "shares": 100, "cost": 1500.0}],
    )
    app = FastAPI()
    app.include_router(campaign_router.router)
    response = TestClient(app).post(
        f"/api/campaigns/{pre_entry['campaign_id']}/activate-from-trade",
        json={"trade_id": trade["trade_id"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["campaign"]["status"] == "ACTIVE"
