"""Offline cross-domain regressions for P1-02, P1-05 and P2-01."""
from datetime import datetime, timezone
import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import account_event_store
import decision_commit_runtime as commit
import formal_decision_outcome_runtime as outcome
import frozen_decision_service as frozen
import performance_attribution_service as performance
import position_reality_router
import position_reality_service as position
import trade_attribution_runtime as attribution
import trade_ledger_router
import trade_ledger_service as trades
import trade_ledger_store as store
from test_trade_attribution_runtime import decision_payload
from test_decision_commit_runtime import _draft, _ports, CAMPAIGN_ID


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for variable, filename in [
        ("VIBE_RESEARCH_TRADE_LEDGER_DB", "trades.sqlite"),
        ("VIBE_RESEARCH_FROZEN_DECISION_DB", "frozen.sqlite"),
        ("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", "attributions.sqlite"),
        ("VIBE_RESEARCH_TRADE_ORIGIN_DB", "origins.sqlite"),
    ]:
        monkeypatch.setenv(variable, str(tmp_path / filename))
    def blocked(*args, **kwargs):
        raise AssertionError("Network prohibited in account authority regressions")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(trades, "_execution_now", lambda: datetime(2026, 10, 23, tzinfo=timezone.utc))
    monkeypatch.setattr(position, "_utc_now", lambda: "2026-10-23T00:00:00+00:00")


def payload(**changes):
    return {"code": "600519", "name": "SYNTHETIC", "operation": "buy",
            "execution_status": "full", "actual_price": 10, "actual_quantity": 100,
            "executed_at": "2026-08-03T02:00:00Z", "fee": 0, "other_cost": 0, **changes}


def bootstrap(shares=0):
    return position.bootstrap_commit({"ledger_start_at": "2026-08-01", "opening_cash": 100000,
        "positions": [{"code": "600519", "name": "SYNTHETIC", "shares": shares, "cost_basis": 20}] if shares else []})


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(trade_ledger_router.router)
    app.include_router(position_reality_router.router)
    return TestClient(app)


@pytest.mark.parametrize("endpoint", ["/api/trades", "/api/position/trades"])
def test_all_void_endpoints_cascade_keep_history(client, endpoint):
    bootstrap()
    trade = trades.create_trade(payload())
    correction = position.create_correction({"target_event_id": trade["trade_id"], "target_event_type": "trade",
        "after_payload": {"actual_quantity": 200}, "reason": "synthetic correction"})
    response = client.post(f"{endpoint}/{trade['trade_id']}/void", json={"reason": "void"})
    assert response.status_code == 200
    if endpoint == "/api/trades":
        assert response.json()["data"]["trade_id"] == trade["trade_id"]
    assert client.get("/api/position/derived").json()["data"]["positions"] == []
    historical = account_event_store.list_events(position.resolve_db_path(), include_voided=True)
    assert len([e for e in historical if e["event_type"] == "CORRECTION" and e["voided_at"]]) == 1
    assert client.post(f"{endpoint}/{trade['trade_id']}/void", json={"reason": "again"}).status_code == 409
    assert client.post(f"{endpoint}/missing/void", json={"reason": "again"}).status_code == 404


def test_old_void_endpoint_recovers_historical_orphan(client):
    bootstrap()
    trade = trades.create_trade(payload())
    position.create_correction({"target_event_id": trade["trade_id"], "target_event_type": "trade", "after_payload": {"actual_quantity": 200}})
    store.void_record_atomic(position.resolve_db_path(), trade["trade_id"], "historical")
    before = store.get_record(position.resolve_db_path(), trade["trade_id"])
    response = client.post(f"/api/trades/{trade['trade_id']}/void", json={"reason": "repair"})
    assert response.status_code == 200
    assert response.json()["data"]["voided_at"] == before["voided_at"]
    assert store.get_record(position.resolve_db_path(), trade["trade_id"]) == before
    assert position.derive_positions()["positions"] == []


def test_legacy_void_cascade_rolls_back_on_failure(monkeypatch):
    bootstrap()
    trade = trades.create_trade(payload())
    position.create_correction({"target_event_id": trade["trade_id"], "target_event_type": "trade", "after_payload": {"actual_quantity": 200}})
    def fail(*args):
        raise RuntimeError("injected failure after cascade")
    monkeypatch.setattr(store, "void_trade_on_connection", fail)
    with pytest.raises(RuntimeError):
        trades.void_trade(trade["trade_id"], "void")
    assert trades.get_trade(trade["trade_id"])["voided_at"] is None
    assert position.derive_positions()["positions"][0]["shares"] == 200


def test_valid_account_partial_decision_cost_is_not_measured(monkeypatch):
    bootstrap(100)
    monkeypatch.setattr(frozen, "_utc_now_iso", lambda: "2026-08-02T00:00:00.000000Z")
    decision = frozen.freeze_decision(decision_payload(review_by="2026-08-30T00:00:00Z"))
    selected = [trades.create_trade(payload()), trades.create_trade(payload(operation="sell", actual_quantity=200, actual_price=15, executed_at="2026-08-04T02:00:00Z"))]
    for trade in selected:
        attribution.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    assert position.derive_positions()["positions"][0]["status"] == "CLOSED"
    pa = performance.compute_attribution_for_trade_ids([t["trade_id"] for t in selected])
    assert pa["measurement_state"] == "PARTIAL"
    assert pa["reason_codes"] == ["MISSING_COST_BASIS"]
    actual = outcome.evaluate_outcome(decision["decision_id"])["actual_capital_outcome"]
    assert actual["pnl_state"] == "NOT_EVALUATED"
    assert actual["pnl"] is None
    assert actual["reason_codes"] == ["MISSING_COST_BASIS"]


@pytest.mark.parametrize("review", ["2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", "2026-08-02T08:00:00+08:00"])
def test_new_freeze_rejects_expired_or_equal_boundary(monkeypatch, review):
    monkeypatch.setattr(frozen, "_utc_now_iso", lambda: "2026-08-02T00:00:00.000000Z")
    with pytest.raises(frozen.FrozenDecisionValidationError, match="review_by"):
        frozen.freeze_decision(decision_payload(review_by=review))
    assert frozen.list_decisions() == []


def test_expired_historical_replay_keeps_identity(monkeypatch):
    monkeypatch.setattr(frozen, "_utc_now_iso", lambda: "2026-08-02T00:00:00.000000Z")
    original = frozen.freeze_decision(decision_payload(review_by="2026-08-30T00:00:00Z"))
    monkeypatch.setattr(frozen, "_utc_now_iso", lambda: "2026-10-23T00:00:00.000000Z")
    assert frozen.freeze_decision(original) == original
    assert len(frozen.list_decisions()) == 1


def test_preview_uses_server_clock_not_backdated_as_of(monkeypatch):
    monkeypatch.setattr(commit, "utc_now_iso", lambda: "2026-10-23T00:00:00.000000Z")
    with pytest.raises(commit.DecisionCommitInputError, match="review_by"):
        commit.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=_ports(), as_of="2026-08-16T00:00:00.000000Z")


@pytest.mark.parametrize("status", ["full", "partial"])
def test_future_execution_is_rejected_without_write(client, status):
    response = client.post("/api/trades", json=payload(execution_status=status, executed_at="2099-01-01T00:00:00Z"))
    assert response.status_code == 422
    assert trades.list_trades() == []


def test_existing_future_fact_and_correction_not_current_or_deleted():
    bootstrap()
    record = trades.validate_and_build_record(payload(executed_at="2099-01-01T00:00:00Z"))
    store.insert_record(position.resolve_db_path(), record)
    position.create_correction({"target_event_id": record["trade_id"], "target_event_type": "trade", "after_payload": {"actual_quantity": 200}})
    assert position.derive_positions()["positions"] == []
    assert trades.get_trade(record["trade_id"])["actual_quantity"] == 100
    assert len(account_event_store.list_events(position.resolve_db_path())) == 2


def test_clock_skew_is_recordable_but_not_yet_current():
    bootstrap()
    trade = trades.create_trade(payload(executed_at="2026-10-23T00:04:00Z"))
    assert trade["trade_id"]
    assert position.derive_positions()["positions"] == []


@pytest.mark.parametrize("changes", [{"operation": "sell"}, {"executed_at": "2026-07-01T00:00:00Z"}])
def test_canonical_invalid_insert_returns_reconciliation_without_poisoning(client, changes):
    bootstrap()
    response = client.post("/api/trades", json=payload(**changes))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RECONCILIATION_REQUIRED"
    assert trades.list_trades() == []
    assert client.get("/api/position/derived").status_code == 200


def test_legacy_historical_recording_retains_time_and_identity():
    record = trades.create_trade(payload(operation="sell", executed_at="2000-01-01T00:00:00Z"))
    assert record["executed_at"].startswith("2000-01-01")
    assert trades.get_trade(record["trade_id"])["trade_id"] == record["trade_id"]


def test_future_skew_oversell_cannot_become_invalid_later(client):
    bootstrap()
    response = client.post("/api/trades", json=payload(operation="sell", executed_at="2026-10-23T00:04:00Z"))
    assert response.status_code == 409
    assert trades.list_trades() == []


def test_concurrent_sells_have_one_atomic_winner():
    from concurrent.futures import ThreadPoolExecutor
    bootstrap(100)
    def sell():
        try:
            trades.create_trade(payload(operation="sell", actual_quantity=100))
            return "written"
        except trades.TradeReconciliationRequiredError:
            return "reconciliation"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sell(), range(2)))
    assert sorted(results) == ["reconciliation", "written"]
    assert len(trades.list_trades()) == 1
    assert position.derive_positions()["positions"][0]["shares"] == 0


def test_future_existing_trade_does_not_reduce_current_cash():
    import account_reality_service
    bootstrap()
    record = trades.validate_and_build_record(payload(executed_at="2099-01-01T00:00:00Z"))
    store.insert_record(position.resolve_db_path(), record)
    derived = position.derive_positions()
    assert account_reality_service._ledger_cash_candidate(derived)["value"] == 100000
