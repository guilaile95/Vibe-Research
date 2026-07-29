"""Unit tests for signal ledger SQLite storage layer."""

from __future__ import annotations

import sqlite3
import pytest

import decision_trace_store as trace_store
import signal_ledger_store as store


def test_init_and_save_signal_ledger_bundle(tmp_path):
    db_path = tmp_path / "decision_trace.sqlite3"
    run_id = "dr_test_123456"

    # Pre-insert a decision run into decision_trace DB
    trace_store.save_decision_run_bundle(
        run_record={
            "decision_run_id": run_id,
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00Z",
            "result_type": "portfolio_advice",
            "schema_version": "v1",
            "market_status": "normal",
            "source_fingerprint": "abc",
            "trace_status": "archived",
            "created_at": "2026-07-29T10:00:00Z",
        },
        evidence_items=[],
        explanation_items=[],
        db_path=db_path,
    )

    signal_entries = [
        {
            "entry_id": "sig_1",
            "stage": "execution",
            "code": "600519",
            "signal_type": "action_generation",
            "severity": "info",
            "payload_json": {"action": "buy", "reason": "支撑强劲"},
            "created_at": "2026-07-29T10:00:01Z",
        },
        {
            "entry_id": "sig_2",
            "stage": "account_constraint",
            "code": None,
            "signal_type": "account_funding_constraint",
            "severity": "info",
            "payload_json": {"is_sufficient": True},
            "created_at": "2026-07-29T10:00:02Z",
        },
    ]

    decision_outcomes = [
        {
            "outcome_id": "out_1",
            "code": "600519",
            "action": "buy",
            "target_ratio": 0.15,
            "reason": "支撑强劲",
            "constraints_applied_json": ["sellable_quantity_advisory"],
            "created_at": "2026-07-29T10:00:03Z",
        }
    ]

    store.save_signal_ledger_bundle(run_id, signal_entries, decision_outcomes, db_path=db_path)

    # Query signal entries
    query_res = store.query_signal_entries(decision_run_id=run_id, db_path=db_path)
    assert query_res["total"] == 2
    assert len(query_res["items"]) == 2

    # Query full run timeline
    timeline = store.get_run_signal_ledger(run_id, db_path=db_path)
    assert timeline["run"]["decision_run_id"] == run_id
    assert len(timeline["signal_entries"]) == 2
    assert len(timeline["decision_outcomes"]) == 1
    assert timeline["decision_outcomes"][0]["code"] == "600519"
    assert timeline["decision_outcomes"][0]["constraints_applied_json"] == ["sellable_quantity_advisory"]


def test_signal_ledger_corrupted(tmp_path):
    db_path = tmp_path / "decision_trace.sqlite3"
    db_path.write_bytes(b"corrupted binary data header")

    with pytest.raises(store.SignalLedgerCorruptedError):
        store.query_signal_entries(db_path=db_path)
