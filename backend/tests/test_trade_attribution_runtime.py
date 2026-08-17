from __future__ import annotations

import concurrent.futures
import os

import pytest

import formal_trade_attribution as fta
import formal_trade_attribution_store as attribution_store
import frozen_decision_service
import trade_attribution_runtime as runtime
import trade_ledger_service
import trade_origin_store as origin_store


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


def test_resolution_mutual_exclusion_in_both_directions(runtime_env):
    decision, trade = _setup(runtime_env)
    runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
    with pytest.raises(runtime.TradeAttributionConflictError):
        runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    assert attribution_store.get_attribution_for_trade(
        db_path=attribution_store.resolve_formal_trade_attribution_db_path(),
        trade_id=trade["trade_id"],
    ) is None

    _, second_trade = _setup(runtime_env)
    runtime.attribute(second_trade["trade_id"], {"decision_id": decision["decision_id"]})
    with pytest.raises(runtime.TradeAttributionConflictError):
        runtime.mark_unplanned(second_trade["trade_id"], {"confirm": True})
    assert origin_store.get_for_trade(
        db_path=origin_store.resolve_db_path(), trade_id=second_trade["trade_id"]
    ) is None


def test_dual_authority_read_fails_closed(runtime_env):
    decision, trade = _setup(runtime_env)
    runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    origin_store.write(
        db_path=origin_store.resolve_db_path(),
        record={
            "resolution_id": "trade_origin_" + "c" * 32,
            "trade_id": trade["trade_id"],
            "origin": "UNPLANNED",
            "pre_trade_decision": "NONE",
            "pre_trade_thesis": "NONE",
            "created_at": "2026-08-17T00:00:00.000000Z",
        },
    )
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "ERROR"
    assert result["reconciliation_requirement"] == "ERROR"
    assert result["reason_codes"] == ["CONFLICTING_TRADE_RESOLUTION_AUTHORITIES"]


def test_unplanned_rejects_existing_pre_trade_thesis(runtime_env, monkeypatch):
    _, trade = _setup(runtime_env)
    contradictory = dict(trade, thesis_id="b" * 32, thesis_revision=1)
    monkeypatch.setattr(runtime, "_trade", lambda trade_id: contradictory)
    with pytest.raises(runtime.TradeAttributionConflictError):
        runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
    assert not os.path.exists(os.environ["VIBE_RESEARCH_TRADE_ORIGIN_DB"])


def test_concurrent_resolution_writes_have_one_winner(runtime_env):
    decision, trade = _setup(runtime_env)

    def attempt(kind):
        try:
            if kind == "attribution":
                return "attribution", runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
            return "unplanned", runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
        except runtime.TradeAttributionRuntimeError as exc:
            return kind, exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("attribution", "unplanned")))
    successes = [item for _, item in results if not isinstance(item, Exception)]
    assert len(successes) == 1
    assert runtime.reconciliation_for_trade(trade["trade_id"])["allocation_state"] in {"ALLOCATED", "UNPLANNED"}


def test_candidate_pagination_reaches_page_after_500(runtime_env, monkeypatch):
    decision, trade = _setup(runtime_env)
    calls = []

    def paged(*, security_code, limit, offset, **kwargs):
        calls.append(offset)
        if offset == 0:
            return [{} for _ in range(500)]
        if offset == 500:
            return [decision]
        return []

    monkeypatch.setattr(runtime.frozen_decision_service, "list_decisions", paged)
    candidates = runtime.list_candidates(trade["trade_id"])
    assert calls == [0, 500]
    assert [item["decision_id"] for item in candidates] == [decision["decision_id"]]


def test_exact_trade_lookup_survives_more_than_500_other_attributions(runtime_env):
    decision, trade = _setup(runtime_env)
    runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    db_path = attribution_store.resolve_formal_trade_attribution_db_path()
    for index in range(500):
        other_trade = dict(trade, trade_id=f"{index + 1:032x}")
        record = fta.create_attribution(
            decision,
            other_trade,
            attribution_id="trade_attribution_" + f"{index + 1:032x}",
            created_at="2026-08-17T00:00:00.000000Z",
        ).to_dict()
        attribution_store.write_attribution(db_path=db_path, record=record)
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "ALLOCATED"
    assert result["reconciliation_requirement"] == "NOT_REQUIRED"
    assert result["decision_id"] == decision["decision_id"]
