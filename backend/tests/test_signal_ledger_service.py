"""Unit tests for signal ledger extraction against authoritative advice contract."""

from __future__ import annotations

import signal_ledger_service as svc
import signal_ledger_store as store
from authoritative_advice_fixtures import build_authoritative_from_golden


def test_archive_signal_ledger_authoritative_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    advice_result = build_authoritative_from_golden(monkeypatch)

    res = svc.archive_signal_ledger(advice_result, db_path=db_path)
    assert res["status"] == "success"
    assert res["decision_outcomes_count"] == len(advice_result["holdings"])

    run_id = res["decision_run_id"]
    timeline = store.get_run_signal_ledger(run_id, db_path=db_path)
    stages = {entry["stage"] for entry in timeline["signal_entries"]}
    assert stages == set(svc.VALID_STAGES)

    outcome = timeline["decision_outcomes"][0]
    assert outcome["code"] == "600519"
    assert outcome["action"] == "reduce"
    # golden reduce size 30% → target_ratio 0.3
    assert abs(float(outcome["target_ratio"]) - 0.30) < 1e-9
    assert outcome["reason"]
    assert "sellable_quantity_advisory" in (outcome.get("constraints_applied_json") or [])

    fact = next(
        e for e in timeline["signal_entries"] if e["stage"] == "fact_reconciliation"
    )
    assert fact["payload_json"]["market_status"] in ("normal", "partial", "unavailable")
    assert "portfolio_summary" in fact["payload_json"]
    assert "market_sentiment" not in fact["payload_json"]
    assert "position_recommendation" not in fact["payload_json"]

    funding_entries = [
        e
        for e in timeline["signal_entries"]
        if e["signal_type"] == "account_funding_constraint"
    ]
    assert funding_entries
    assert "account_funding" in funding_entries[0]["payload_json"]

    sellable_entries = [
        e
        for e in timeline["signal_entries"]
        if e["signal_type"] == "sellable_quantity_check"
    ]
    assert sellable_entries
    advisory = sellable_entries[0]["payload_json"]["sellable_quantity_advisory"]
    assert not isinstance(advisory, dict)


def test_archive_signal_ledger_null_sellable_advisory(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    advice = build_authoritative_from_golden(monkeypatch)
    for h in advice["holdings"]:
        h["action"] = "reduce"
        h["sellable_quantity_advisory"] = None

    res = svc.archive_signal_ledger(advice, db_path=db_path)
    assert res["status"] == "success"
    timeline = store.get_run_signal_ledger(res["decision_run_id"], db_path=db_path)
    sellable = [
        e
        for e in timeline["signal_entries"]
        if e["signal_type"] == "sellable_quantity_check"
    ]
    assert sellable
    assert sellable[0]["payload_json"]["sellable_quantity_advisory"] is None


def test_archive_signal_ledger_malformed_non_dict(tmp_path):
    res = svc.archive_signal_ledger("bad", db_path=tmp_path / "x.sqlite3")
    assert res["status"] == "failed"
