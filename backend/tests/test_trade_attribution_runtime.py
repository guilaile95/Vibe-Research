from __future__ import annotations

import sqlite3

import pytest

import frozen_decision_service
import trade_attribution_runtime as runtime
import trade_ledger_service


def decision_payload(**overrides):
    value = {
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": "campaign_" + "a" * 32,
        "thesis_id": "b" * 32,
        "thesis_revision": 1,
        "asset_view": {}, "trade_view": {}, "portfolio_view": {},
        "next_best_action": "BUY SMALL", "action_envelope": {},
        "maintain_conditions": [], "upgrade_conditions": [],
        "downgrade_conditions": [], "invalidation_conditions": [],
        "strategy_horizon": "2w", "review_by": "2099-01-01T00:00:00Z",
        "key_assumptions": [], "event_invalidation_conditions": [],
        "risk_policy_version": "risk", "opportunity_policy_version": "opp",
        "decision_policy_version": "decision", "behavior_model_version": "behavior",
        "data_quality": {}, "evidence_confidence": None,
        "inference_confidence": None, "decision_confidence": None,
        "evidence_refs": [], "risk_refs": [], "source_refs": [],
        "user_confirmed": True,
    }
    value.update(overrides)
    return value


def trade_payload(**overrides):
    value = {
        "code": "600519", "name": "贵州茅台", "operation": "buy",
        "execution_status": "full", "actual_price": 100.0,
        "actual_quantity": 1, "executed_at": "2098-01-01T01:00:00Z",
    }
    value.update(overrides)
    return value


@pytest.fixture
def runtime_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(tmp_path / "trades.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(tmp_path / "decisions.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", str(tmp_path / "attributions.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_ORIGIN_DB", str(tmp_path / "origins.sqlite3"))


def _setup(runtime_env):
    decision = frozen_decision_service.freeze_decision(decision_payload())
    trade = trade_ledger_service.create_trade(trade_payload())
    return decision, trade


def test_initial_complete_scan_is_unallocated_and_no_inference(runtime_env):
    decision, trade = _setup(runtime_env)
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "UNALLOCATED"
    assert result["reconciliation_requirement"] == "REQUIRED"
    assert result["campaign_id"] is None
    assert runtime.list_candidates(trade["trade_id"])[0]["decision_id"] == decision["decision_id"]


def test_explicit_attribution_is_exact_and_replay_is_idempotent(runtime_env):
    decision, trade = _setup(runtime_env)
    first = runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    second = runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    assert first["record"] == second["record"]
    assert second["idempotent"] is True
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "ALLOCATED"
    assert result["campaign_id"] == decision["campaign_id"]
    assert result["decision_id"] == decision["decision_id"]


def test_caller_cannot_supply_formal_identity_and_post_trade_decision_is_rejected(runtime_env):
    decision, trade = _setup(runtime_env)
    with pytest.raises(runtime.TradeAttributionValidationError):
        runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"], "campaign_id": decision["campaign_id"]})
    late = frozen_decision_service.freeze_decision(decision_payload(campaign_id="campaign_" + "c" * 32))
    # The service-generated commit is after the already-created trade.
    with pytest.raises(runtime.TradeAttributionValidationError):
        runtime.attribute(trade["trade_id"], {"decision_id": late["decision_id"]})


def test_unplanned_is_durable_without_fake_formal_identity(runtime_env):
    _, trade = _setup(runtime_env)
    first = runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
    second = runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
    assert second["idempotent"] is True
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "UNPLANNED"
    assert result["reconciliation_requirement"] == "NOT_REQUIRED"
    assert result["campaign_id"] is None
    assert result["decision_id"] is None
    assert result["pre_trade_decision"] == "NONE"
    assert result["pre_trade_thesis"] == "NONE"
    assert first["record"]["trade_id"] == trade["trade_id"]


def test_voided_and_not_executed_are_not_applicable(runtime_env):
    decision, trade = _setup(runtime_env)
    trade_ledger_service.void_trade(trade["trade_id"], "test")
    assert runtime.reconciliation_for_trade(trade["trade_id"])["allocation_state"] == "NOT_APPLICABLE"
    with pytest.raises(runtime.TradeAttributionValidationError):
        runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})


def test_corrupt_attribution_store_is_error_not_unallocated(runtime_env):
    _, trade = _setup(runtime_env)
    # pytest's MonkeyPatch has no getenv; use the same deterministic path from
    # the fixture environment without touching any real user data.
    import os
    corrupt_path = os.environ["VIBE_RESEARCH_TRADE_ATTRIBUTION_DB"]
    with open(corrupt_path, "wb") as handle:
        handle.write(b"not sqlite")
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "ERROR"
    assert result["allocation_state"] != "UNALLOCATED"
