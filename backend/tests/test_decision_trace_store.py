"""Unit tests for decision_trace_store.py."""

from __future__ import annotations

import pytest
import sqlite3
import decision_trace_store as store


def test_init_db(tmp_path):
    db_path = tmp_path / "test_trace.sqlite3"
    store.init_db(db_path)
    assert db_path.exists()

    conn = sqlite3.connect(str(db_path))
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    conn.close()

    assert "schema_meta" in tables
    assert "decision_runs" in tables
    assert "evidence_items" in tables
    assert "explanation_items" in tables


def test_save_and_get_decision_run(tmp_path):
    db_path = tmp_path / "test_trace.sqlite3"

    run_record = {
        "decision_run_id": "dr_test123",
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00.000000+00:00",
        "result_type": "portfolio_advice",
        "schema_version": "decision_trace_v1",
        "market_status": "normal",
        "source_fingerprint": "fp_abc",
        "trace_status": "archived",
    }
    evidence_items = [
        {
            "evidence_id": "ev_001",
            "decision_run_id": "dr_test123",
            "scope": "stock",
            "code": "600519",
            "evidence_key": "stock_quote",
            "value_json": {"price": 1800.0},
            "unit": "yuan",
            "source_module": "portfolio_advice_context",
            "observed_at": "2026-07-29T10:00:00.000000+00:00",
            "quality_status": "valid",
        }
    ]
    explanation_items = [
        {
            "explanation_id": "exp_001",
            "decision_run_id": "dr_test123",
            "code": "600519",
            "conclusion_type": "action",
            "conclusion_value": "hold",
            "explanation_text": "Strong fundamental holding",
            "supporting_evidence_ids": ["ev_001"],
            "limiting_evidence_ids": [],
            "rule_id": "rule_hold",
        }
    ]

    store.save_decision_run_bundle(
        run_record, evidence_items, explanation_items, db_path=db_path
    )

    bundle = store.get_decision_run("dr_test123", db_path=db_path)
    assert bundle is not None
    assert bundle["decision_run"]["decision_run_id"] == "dr_test123"
    assert bundle["decision_run"]["trade_date"] == "2026-07-29"
    assert len(bundle["evidence_items"]) == 1
    assert bundle["evidence_items"][0]["evidence_id"] == "ev_001"
    assert bundle["evidence_items"][0]["value_json"] == {"price": 1800.0}
    assert len(bundle["explanation_items"]) == 1
    assert bundle["explanation_items"][0]["supporting_evidence_ids"] == ["ev_001"]


def test_save_idempotency(tmp_path):
    db_path = tmp_path / "test_trace.sqlite3"

    run_record = {
        "decision_run_id": "dr_test_idempotent",
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00.000000+00:00",
        "result_type": "portfolio_advice",
        "schema_version": "decision_trace_v1",
        "market_status": "normal",
        "source_fingerprint": "fp_v1",
        "trace_status": "archived",
    }
    ev = [
        {
            "evidence_id": "ev_idem_1",
            "decision_run_id": "dr_test_idempotent",
            "scope": "market",
            "evidence_key": "mkt_status",
            "value_json": {"status": "normal"},
            "source_module": "daily_review",
            "quality_status": "valid",
        }
    ]
    exp = [
        {
            "explanation_id": "exp_idem_1",
            "decision_run_id": "dr_test_idempotent",
            "conclusion_type": "account_action",
            "conclusion_value": "hold",
            "explanation_text": "Hold overall",
            "supporting_evidence_ids": ["ev_idem_1"],
            "limiting_evidence_ids": [],
        }
    ]

    store.save_decision_run_bundle(run_record, ev, exp, db_path=db_path)
    b1 = store.get_decision_run("dr_test_idempotent", db_path=db_path)
    assert b1["decision_run"]["source_fingerprint"] == "fp_v1"

    # Save second time with updated values
    run_record["source_fingerprint"] = "fp_v2"
    store.save_decision_run_bundle(run_record, ev, exp, db_path=db_path)
    b2 = store.get_decision_run("dr_test_idempotent", db_path=db_path)
    assert b2["decision_run"]["source_fingerprint"] == "fp_v2"


def test_list_evidence_items_filtering(tmp_path):
    db_path = tmp_path / "test_trace.sqlite3"

    run1 = {
        "decision_run_id": "dr_1",
        "trade_date": "2026-07-28",
        "generated_at": "2026-07-28T10:00:00.000000+00:00",
        "result_type": "portfolio_advice",
        "schema_version": "decision_trace_v1",
        "trace_status": "archived",
    }
    ev1 = [
        {
            "evidence_id": "ev_101",
            "decision_run_id": "dr_1",
            "scope": "stock",
            "code": "600519",
            "evidence_key": "quote",
            "value_json": {"p": 100},
            "source_module": "test",
            "quality_status": "valid",
        }
    ]
    run2 = {
        "decision_run_id": "dr_2",
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00.000000+00:00",
        "result_type": "portfolio_advice",
        "schema_version": "decision_trace_v1",
        "trace_status": "failed",
    }
    ev2 = [
        {
            "evidence_id": "ev_102",
            "decision_run_id": "dr_2",
            "scope": "stock",
            "code": "000001",
            "evidence_key": "quote",
            "value_json": {"p": 50},
            "source_module": "test",
            "quality_status": "partial",
        }
    ]

    store.save_decision_run_bundle(run1, ev1, [], db_path=db_path)
    store.save_decision_run_bundle(run2, ev2, [], db_path=db_path)

    # Filter by code
    res_code = store.list_evidence_items(code="600519", db_path=db_path)
    assert res_code["total"] == 1
    assert res_code["items"][0]["evidence_id"] == "ev_101"

    # Filter by trade_date
    res_date = store.list_evidence_items(trade_date="2026-07-29", db_path=db_path)
    assert res_date["total"] == 1
    assert res_date["items"][0]["evidence_id"] == "ev_102"

    # Filter by quality_status
    res_qual = store.list_evidence_items(quality_status="partial", db_path=db_path)
    assert res_qual["total"] == 1

    # Filter by trace_status
    res_trace = store.list_evidence_items(trace_status="failed", db_path=db_path)
    assert res_trace["total"] == 1


def test_corrupted_database(tmp_path):
    db_path = tmp_path / "corrupt.sqlite3"
    with open(db_path, "wb") as f:
        f.write(b"NOT A SQLITE DATABASE FILE HEADER CONTENT")

    with pytest.raises(store.DecisionTraceCorruptedError):
        store.get_decision_run("dr_anything", db_path=db_path)

    with pytest.raises(store.DecisionTraceCorruptedError):
        store.list_evidence_items(db_path=db_path)
