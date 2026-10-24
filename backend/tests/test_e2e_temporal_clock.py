"""The browser clock fixture controls time, never production business rules."""
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path

import pytest

from test_frozen_decision_service import valid_payload


@pytest.fixture
def clock(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "frontend/tests/e2e/temporal_clock.py"
    spec = importlib.util.spec_from_file_location("e2e_temporal_clock", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock_file = tmp_path / "clock.txt"
    clock_file.write_text("2026-08-28T08:00:00.000000Z")
    monkeypatch.setenv("E2E_CLOCK_FILE", str(clock_file))
    module.install(monkeypatch.setattr)
    return module, clock_file


def test_all_boundary_clocks_follow_explicit_phases(clock):
    import decision_commit_runtime as commit
    import decision_challenge_runtime as challenge
    import formal_decision_outcome_runtime as outcome
    import frozen_decision_service as frozen
    import trade_ledger_service as trades
    import importlib
    module, file = clock
    for instant in ("2026-08-28T08:00:00.000000Z", "2026-09-02T08:00:00.000000Z"):
        file.write_text(instant)
        assert module.utc_now_iso() == commit.utc_now_iso() == frozen._utc_now_iso() == instant
        assert challenge.PRODUCTION_PORTS.clock() == outcome._now() == instant
        assert trades._execution_now() == datetime.fromisoformat(instant.replace("Z", "+00:00"))
        for name, field in (("evidence_thesis_service", "_utc_now_iso"), ("evidence_thesis_store", "_utc_now_iso"), ("decision_trace_store", "_utc_now"), ("account_reality_service", "_utc_now"), ("position_reality_service", "_utc_now"), ("trade_ledger_store", "_utc_now")):
            assert getattr(importlib.import_module(name), field)() == instant.replace("Z", "+00:00")


def test_expiry_blocks_new_decisions_but_keeps_exact_historical_replay(clock, tmp_path):
    import frozen_decision_service as frozen
    _, file = clock
    db = tmp_path / "decisions.sqlite3"
    payload = valid_payload(review_by="2026-08-29T10:00:00Z")
    original = frozen.freeze_decision(payload, db)
    assert original["committed_at"] == "2026-08-28T08:00:00.000000Z"
    file.write_text("2026-09-02T08:00:00Z")
    with pytest.raises(frozen.FrozenDecisionReviewBoundaryExpiredError):
        frozen.freeze_decision(payload, db)
    assert frozen.freeze_decision(original, db) == original
    assert frozen.get_decision(original["decision_id"], db) == original


def test_preview_still_rejects_expired_review_before_reading_authorities(clock):
    import decision_commit_runtime as commit
    payload = {
        "asset_view": {}, "trade_view": {}, "portfolio_view": {},
        "review_by": "2026-08-28T08:00:00Z", "key_assumptions": [],
        "event_invalidation_conditions": [], "strategy_horizon": "2w",
    }
    with pytest.raises(commit.DecisionCommitInputError, match="review_by"):
        commit.preview_decision_proposal("campaign_" + "a" * 32, payload)


def test_executed_trade_boundary_is_unchanged(clock, monkeypatch, tmp_path):
    import trade_ledger_service as trades
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(tmp_path / "trades.sqlite3"))
    module, file = clock
    payload = {
        "code": "600519", "name": "Synthetic", "operation": "buy",
        "execution_status": "full", "actual_price": 100, "actual_quantity": 1,
        "fee": 0, "other_cost": 0,
    }
    boundary = module.now() + timedelta(minutes=5)
    payload["executed_at"] = (boundary + timedelta(microseconds=1)).isoformat()
    with pytest.raises(trades.TradeValidationError, match="未来"):
        trades.create_trade(payload)
    payload["executed_at"] = boundary.isoformat()
    accepted = trades.create_trade(payload)
    assert datetime.fromisoformat(accepted["executed_at"]) == boundary
    # TAR1 facts are after freeze but already executed in the observation phase.
    file.write_text("2026-09-02T08:00:00Z")
    for instant in ("2026-08-29T01:00:00Z", "2026-08-30T10:00:00Z", "2026-08-31T11:15:00Z"):
        payload["executed_at"] = instant
        assert trades.create_trade(payload)["execution_status"] == "full"


def test_missing_or_invalid_clock_fails_closed(clock, monkeypatch):
    import frozen_decision_service as frozen
    module, file = clock
    previous = frozen._utc_now_iso
    monkeypatch.delenv("E2E_CLOCK_FILE")
    module.install(monkeypatch.setattr)
    assert frozen._utc_now_iso is previous
    monkeypatch.setenv("E2E_CLOCK_FILE", str(file))
    for invalid in ("not-a-time", "2026-08-28T08:00:00", "2026-08-28T08:00:00+08:00"):
        file.write_text(invalid)
        with pytest.raises(ValueError):
            module.install(monkeypatch.setattr)
    file.unlink()
    with pytest.raises(FileNotFoundError):
        module.install(monkeypatch.setattr)


@pytest.fixture
def api(clock, tmp_path, monkeypatch):
    """Real routes and stores; external Critical Data providers stay offline."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from dataclasses import replace
    import importlib
    import campaign_critical_data_runtime as critical
    import os
    from validation_environment import configure_pytest_environment

    isolated = dict(os.environ)
    configure_pytest_environment(tmp_path / "api", isolated)
    for key, value in isolated.items():
        if os.environ.get(key) != value:
            monkeypatch.setenv(key, value)
    ports = critical.PRODUCTION_PORTS
    ports = replace(
        ports,
        market_sector_evaluator=lambda _lake, definition: critical._not_evaluated_result(critical.market_sector_adapter.DEPENDENCY_ID, definition["as_of"]),
        disclosures_evaluator=lambda _lake, definition: critical._not_evaluated_result(critical.disclosures_adapter.DEPENDENCY_ID, definition["as_of"]),
        financials_evaluator=lambda _lake, definition: critical._not_evaluated_result(critical.financials_adapter.DEPENDENCY_ID, definition["as_of"]),
    )
    project = critical.project_campaign_critical_data
    monkeypatch.setattr(critical, "project_campaign_critical_data", lambda *args, **kw: project(*args, **{**kw, "ports": ports}))
    app = FastAPI()
    for module in ("campaign_router", "evidence_thesis_router", "position_reality_router", "decision_commit_router", "trade_ledger_router", "trade_attribution_router", "formal_decision_outcome_router"):
        app.include_router(importlib.import_module(module).router)
    return TestClient(app)


def request_data(api, method, path, payload=None, status=200):
    response = api.request(method, path, **({"json": payload} if payload is not None else {}))
    assert response.status_code == status, f"{method} {path}: {response.text}"
    return response.json()["data"]


@pytest.mark.parametrize("close_campaign", [False, True])
def test_real_api_thesis_formalization_preview_freeze_readback(clock, api, close_campaign):
    import campaign_store
    import uuid
    import evidence_thesis_store
    module, file = clock
    request_data(api, "POST", "/api/position/bootstrap-commit", {
        "ledger_start_at": "2026-08-01", "opening_cash": 1000000, "positions": [], "note": "synthetic clock regression",
    })
    campaign = request_data(api, "POST", "/api/campaigns", {"security_code": "600519", "strategy": "SWING"}, 201)
    evidence = request_data(api, "POST", "/api/evidence", {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "synthetic supporting claim", "source_title": "synthetic source", "source_url": "https://example.test/source",
        "source_date": "2026-08-01", "accessed_at": "2026-08-01T00:00:00.000Z", "classification": "fact", "confidence": "high",
    })
    created = request_data(api, "POST", "/api/thesis", {
        "subject_type": "stock", "subject_id": "600519", "title": "clock regression", "summary": "synthetic",
        "core_claims": ["one", "two", "three"], "catalysts": [], "risks": [], "invalidation_conditions": [], "change_summary": "fixture",
    })
    thesis_id = created["thesis"]["id"]
    begun = request_data(api, "POST", f"/api/thesis/{thesis_id}/begin-formalization", {})
    updated = request_data(api, "PUT", f"/api/thesis/{thesis_id}", {
        "title": "clock regression", "summary": "synthetic", "status": "active", "core_claims": ["one", "two", "three"],
        "catalysts": [], "risks": [], "invalidation_conditions": [], "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 10, "max": 30, "anchor": "FREEZE_AT"},
        "free_notes": None, "expected_revision": begun["thesis"]["current_revision"], "change_summary": "formal fixture",
    })
    request_data(api, "POST", f"/api/thesis/{thesis_id}/evidence", {"evidence_id": evidence["id"], "stance": "support", "expected_revision": updated["thesis"]["current_revision"]})
    current = request_data(api, "GET", f"/api/thesis/{thesis_id}")
    confirmed = request_data(api, "POST", f"/api/thesis/{thesis_id}/confirm", {"expected_revision": current["thesis"]["current_revision"]})
    frozen = request_data(api, "POST", f"/api/thesis/{thesis_id}/freeze", {"expected_revision": confirmed["thesis"]["current_revision"]})
    assert frozen["thesis"]["formal_state"] == "frozen"
    assert evidence_thesis_store._is_canonical_utc_timestamp(frozen["thesis"]["frozen_at"])
    assert not evidence_thesis_store._is_canonical_utc_timestamp(frozen["thesis"]["frozen_at"].replace("+00:00", "Z"))
    # DCR1 late-edit stage: a stale reviewed timestamp must cause 409,
    # then an explicit re-review can append exactly one delta.
    module.advance()
    late = request_data(api, "POST", "/api/evidence", {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "post-freeze synthetic", "source_title": "version one", "source_url": None,
        "source_date": "2026-08-28", "accessed_at": module.utc_now_iso(), "classification": "fact", "confidence": "high",
    })
    stale_delta = {"delta_state": "WEAKENED", "reason": "explicit review", "new_evidence": [
        {"evidence_id": late["id"], "stance": "oppose", "expected_updated_at": late["updated_at"]},
    ]}
    update = {key: late[key] for key in ("evidence_type", "claim", "source_title", "source_url", "source_date", "accessed_at", "classification", "confidence")}
    module.advance()
    edited = request_data(api, "PUT", f"/api/evidence/{late['id']}", {**update, "source_title": "version two", "expected_edit_token": late["edit_token"]})
    assert edited["updated_at"] != late["updated_at"]
    rejected = api.post(f"/api/thesis/{thesis_id}/deltas", json=stale_delta)
    assert rejected.status_code == 409, rejected.text
    assert request_data(api, "GET", f"/api/thesis/{thesis_id}/deltas")["items"] == []
    module.advance()
    stale_delta["new_evidence"][0]["expected_updated_at"] = edited["updated_at"]
    request_data(api, "POST", f"/api/thesis/{thesis_id}/deltas", stale_delta)
    assert len(request_data(api, "GET", f"/api/thesis/{thesis_id}/deltas")["items"]) == 1
    campaign_id = campaign["campaign_id"]
    request_data(api, "POST", f"/api/campaigns/{campaign_id}/thesis-binding", {"thesis_id": thesis_id}, 201)
    for old, new in (("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY")):
        request_data(api, "POST", f"/api/campaigns/{campaign_id}/transitions", {"expected_status": old, "to_status": new})
    # Same explicit historical ACTIVE seed used by the browser fixtures.
    campaign_store.transition_campaign(campaign_id=campaign_id, expected_status="PRE-ENTRY", to_status="ACTIVE", transition_id=f"campaign_transition_{uuid.uuid4().hex}", transitioned_at=module.utc_now_iso())
    draft = {
        "asset_view": {"view": "ASSET", "stance": "WAIT"}, "trade_view": {"view": "TRADE", "stance": "WAIT"},
        "portfolio_view": {"view": "PORTFOLIO", "constraint": "unknown"}, "review_by": "2026-08-30T10:00:00.000000Z",
        "key_assumptions": ["synthetic"], "event_invalidation_conditions": ["synthetic"], "strategy_horizon": "2w",
    }
    base = f"/api/campaigns/{campaign_id}/decision-proposal"
    preview = request_data(api, "POST", f"{base}/preview", draft)
    commit_payload = {
        **draft, "as_of": preview["proposal"]["as_of"], "expected_proposal_fingerprint": preview["proposal_fingerprint"], "user_confirmed": True,
    }
    committed = request_data(api, "POST", f"{base}/commit", commit_payload)
    decision = committed["committed"]
    assert decision["committed_at"] == module.utc_now_iso()
    if close_campaign:
        # The browser's terminal race follows its second successful decision.
        # First-freeze authority changes are not equivalent to this later stage.
        first_decision = decision
        module.advance()
        preview = request_data(api, "POST", f"{base}/preview", draft)
        commit_payload = {**draft, "as_of": preview["proposal"]["as_of"], "expected_proposal_fingerprint": preview["proposal_fingerprint"], "user_confirmed": True}
        decision = request_data(api, "POST", f"{base}/commit", commit_payload)["committed"]
        assert decision["decision_id"] != first_decision["decision_id"]
        repeated = request_data(api, "POST", f"{base}/preview", draft)
        assert repeated["proposal_fingerprint"] == preview["proposal_fingerprint"], "same phase is the prior proposal, not a new freeze"
        module.advance()
        pending = request_data(api, "POST", f"{base}/preview", draft)
        assert pending["proposal_fingerprint"] != preview["proposal_fingerprint"]
        new_commit = {**draft, "as_of": pending["proposal"]["as_of"], "expected_proposal_fingerprint": pending["proposal_fingerprint"], "user_confirmed": True}
        request_data(api, "POST", f"/api/campaigns/{campaign_id}/transitions", {"expected_status": "ACTIVE", "to_status": "CLOSED"})
        rejected = api.post(f"{base}/commit", json=new_commit)
        assert rejected.status_code == 409, rejected.text
        assert request_data(api, "GET", f"{base}/committed")["total"] == 2
        assert request_data(api, "GET", f"{base}/committed/{first_decision['decision_id']}")["committed"] == first_decision
        exact_retry = request_data(api, "POST", f"{base}/commit", commit_payload)
        assert exact_retry["idempotent"] is True
        assert exact_retry["committed"] == decision
        # The browser's remaining terminal case has no Thesis binding at all.
        no_thesis = request_data(api, "POST", "/api/campaigns", {"security_code": "000001", "strategy": "SWING"}, 201)
        no_thesis_path = f"/api/campaigns/{no_thesis['campaign_id']}"
        request_data(api, "POST", f"{no_thesis_path}/transitions", {"expected_status": "DRAFT", "to_status": "REJECTED"})
        assert request_data(api, "GET", no_thesis_path)["status"] == "REJECTED"
        assert api.get(f"{no_thesis_path}/thesis-binding").status_code == 404
        assert api.post(f"{no_thesis_path}/decision-proposal/preview", json=draft).status_code == 409
        assert request_data(api, "GET", f"{no_thesis_path}/decision-proposal/committed")["total"] == 0
    file.write_text("2026-09-02T08:00:00Z")
    readback = request_data(api, "GET", f"{base}/committed/{decision['decision_id']}")
    assert readback["committed"] == decision
    replay = request_data(api, "POST", f"{base}/commit", commit_payload)
    assert replay["idempotent"] is True
    assert replay["committed"] == decision
    response = api.post(f"{base}/preview", json=draft)
    assert response.status_code == 422


def test_real_api_trade_reconciliation_and_attribution(clock, api):
    import frozen_decision_service as frozen
    module, file = clock
    request_data(api, "POST", "/api/position/bootstrap-commit", {"ledger_start_at": "2026-08-01", "opening_cash": 1000000, "positions": []})
    campaign = request_data(api, "POST", "/api/campaigns", {"security_code": "600519", "strategy": "SWING"}, 201)
    decision = frozen.freeze_decision(valid_payload(campaign_id=campaign["campaign_id"], review_by="2026-09-10T00:00:00Z"))
    file.write_text("2026-09-02T08:00:00Z")
    trade = request_data(api, "POST", "/api/trades", {
        "code": "600519", "name": "synthetic", "operation": "buy", "execution_status": "full",
        "actual_price": 100, "actual_quantity": 1, "executed_at": "2026-08-29T01:00:00Z", "fee": 0, "other_cost": 0,
    })
    base = f"/api/trades/{trade['trade_id']}"
    readback = request_data(api, "GET", base)
    assert datetime.fromisoformat(readback["created_at"]) == module.now()
    reconciliation = request_data(api, "GET", f"{base}/reconciliation")
    assert reconciliation["allocation_state"] == "UNALLOCATED", reconciliation
    candidates = request_data(api, "GET", f"{base}/attribution-candidates")
    assert decision["decision_id"] in str(candidates)
    request_data(api, "POST", f"{base}/attribution", {"decision_id": decision["decision_id"]})
    reconciled = request_data(api, "GET", f"{base}/reconciliation")
    assert reconciled["allocation_state"] == "ALLOCATED", reconciled
    assert reconciled["decision_id"] == decision["decision_id"]
    module.advance()
    second = request_data(api, "POST", "/api/trades", {
        "code": "600519", "name": "synthetic", "operation": "add", "execution_status": "full",
        "actual_price": 101, "actual_quantity": 1, "executed_at": "2026-08-29T01:01:00Z", "fee": 0, "other_cost": 0,
    })
    listing = request_data(api, "GET", "/api/trades?include_voided=false&limit=10&offset=0")
    assert [row["trade_id"] for row in listing] == [second["trade_id"], trade["trade_id"]]
    assert request_data(api, "GET", f"/api/trades/{listing[-1]['trade_id']}/reconciliation")["allocation_state"] == "ALLOCATED"
    assert request_data(api, "GET", f"/api/trades/{listing[0]['trade_id']}/reconciliation")["allocation_state"] == "UNALLOCATED"


def test_real_api_outcome_preserves_pre_evaluation_trade_visibility(clock, api):
    import frozen_decision_service as frozen
    module, file = clock
    request_data(api, "POST", "/api/position/bootstrap-commit", {"ledger_start_at": "2026-08-01", "opening_cash": 1000000, "positions": []})
    campaign = request_data(api, "POST", "/api/campaigns", {"security_code": "600519", "strategy": "SWING"}, 201)
    decision = frozen.freeze_decision(valid_payload(campaign_id=campaign["campaign_id"], review_by="2026-08-30T10:00:00Z"))
    file.write_text("2026-08-28T09:00:00Z")
    trade_data = {"code": "600519", "name": "synthetic", "operation": "buy", "execution_status": "full", "actual_price": 100, "actual_quantity": 1, "executed_at": "2026-08-28T08:00:01Z", "fee": 0, "other_cost": 0}
    trade = request_data(api, "POST", "/api/trades", trade_data)
    request_data(api, "POST", f"/api/trades/{trade['trade_id']}/attribution", {"decision_id": decision["decision_id"]})
    file.write_text("2026-09-02T08:00:00Z")
    path = f"/api/formal-decisions/{decision['decision_id']}/outcome?evaluation_as_of=2026-08-31T08:00:00Z"
    before = request_data(api, "GET", path)
    assert before["actual_capital_outcome"]["trade_ids"] == [trade["trade_id"]]
    later = request_data(api, "POST", "/api/trades", {**trade_data, "executed_at": "2026-09-01T01:00:00Z"})
    request_data(api, "POST", f"/api/trades/{later['trade_id']}/attribution", {"decision_id": decision["decision_id"]})
    after = request_data(api, "GET", path)
    assert after["actual_capital_outcome"] == before["actual_capital_outcome"]
    assert after["decision_snapshot_hash"] == before["decision_snapshot_hash"]


def run_actual_seed_contract(mode, extra):
    import json
    import os
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHON": sys.executable, **extra}
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        ["node", str(root / "frontend/tests/e2e/temporal-seeds.contract.mjs"), mode],
        cwd=root / "backend", env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_actual_active_seed_without_pythonpath(clock, api):
    campaign = request_data(api, "POST", "/api/campaigns", {"security_code": "600519", "strategy": "SWING"}, 201)
    campaign_id = campaign["campaign_id"]
    for old, new in (("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY")):
        request_data(api, "POST", f"/api/campaigns/{campaign_id}/transitions", {"expected_status": old, "to_status": new})
    result = run_actual_seed_contract("active", {"TEMPORAL_CAMPAIGN_ID": campaign_id})
    assert result["status"] == "ACTIVE_SEED_OK"
    assert request_data(api, "GET", f"/api/campaigns/{campaign_id}")["status"] == "ACTIVE"


def test_actual_history_seed_has_total_order_and_exact_page_boundary(clock, api, monkeypatch):
    import json
    import frozen_decision_service as frozen
    module, _ = clock
    first = frozen.freeze_decision(valid_payload(review_by="2026-08-29T10:00:00Z"))
    module.advance()
    second = frozen.freeze_decision(valid_payload(review_by="2026-08-30T10:00:00Z"))
    seeded = run_actual_seed_contract("history", {"TEMPORAL_DECISION_TEMPLATE": json.dumps(second)})
    monkeypatch.setenv("E2E_CLOCK_FILE", seeded["clock"])
    third = frozen.freeze_decision(valid_payload(review_by="2026-09-10T10:00:00Z"))
    all_rows = frozen.list_decisions(limit=100)
    times = [row["committed_at"] for row in all_rows]
    assert times == sorted(set(times)), "all seeded decisions have distinct chronological timestamps"
    page = frozen.list_decisions(limit=50)
    assert [row["decision_id"] for row in page] == [first["decision_id"], second["decision_id"], *seeded["fillers"][:48]]
    assert third["decision_id"] not in {row["decision_id"] for row in page}
    assert seeded["fillers"][0] in {row["decision_id"] for row in page}
