"""Metadata order + idempotent archive tests for decision trace."""

from __future__ import annotations

import decision_evidence_service as evidence_svc
import decision_trace_store as trace_store
import signal_ledger_service as ledger_svc
import signal_ledger_store as ledger_store
from authoritative_advice_fixtures import build_authoritative_from_golden


def _count_rows(db_path, table: str) -> int:
    conn = trace_store._get_read_connection(db_path)
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"] if row["c"] is not None else 0)
    finally:
        conn.close()


def test_archive_order_evidence_then_ledger_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    advice = build_authoritative_from_golden(monkeypatch)

    r1 = evidence_svc.archive_decision_evidence(advice, db_path=db_path)
    r2 = ledger_svc.archive_signal_ledger(advice, db_path=db_path)
    assert r1["status"] == "archived"
    assert r2["status"] == "success"
    assert r1["decision_run_id"] == r2["decision_run_id"]

    bundle = trace_store.get_decision_run(r1["decision_run_id"], db_path=db_path)
    run = bundle["decision_run"]
    assert run["schema_version"] == "portfolio-advice-v0.1"
    assert run["market_status"] in ("normal", "partial", "unavailable")
    assert run["result_type"] == "portfolio_advice"
    assert run["trace_status"] == "archived"


def test_archive_order_ledger_then_evidence_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    advice = build_authoritative_from_golden(monkeypatch)

    r1 = ledger_svc.archive_signal_ledger(advice, db_path=db_path)
    r2 = evidence_svc.archive_decision_evidence(advice, db_path=db_path)
    assert r1["status"] == "success"
    assert r2["status"] == "archived"
    assert r1["decision_run_id"] == r2["decision_run_id"]

    bundle = trace_store.get_decision_run(r1["decision_run_id"], db_path=db_path)
    run = bundle["decision_run"]
    # evidence uses ON CONFLICT DO UPDATE — final schema_version remains advice schema
    assert run["schema_version"] == "portfolio-advice-v0.1"
    assert run["trace_status"] == "archived"


def test_rearchive_idempotent_counts(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    advice = build_authoritative_from_golden(monkeypatch)

    evidence_svc.archive_decision_evidence(advice, db_path=db_path)
    ledger_svc.archive_signal_ledger(advice, db_path=db_path)
    run_id = evidence_svc.generate_decision_run_id(
        str(advice["trade_date"]), str(advice["generated_at"])
    )

    e1 = _count_rows(db_path, "evidence_items")
    x1 = _count_rows(db_path, "explanation_items")
    s1 = _count_rows(db_path, "signal_entries")
    o1 = _count_rows(db_path, "decision_outcomes")

    evidence_svc.archive_decision_evidence(advice, db_path=db_path)
    ledger_svc.archive_signal_ledger(advice, db_path=db_path)

    assert _count_rows(db_path, "evidence_items") == e1
    assert _count_rows(db_path, "explanation_items") == x1
    assert _count_rows(db_path, "signal_entries") == s1
    assert _count_rows(db_path, "decision_outcomes") == o1

    timeline = ledger_store.get_run_signal_ledger(run_id, db_path=db_path)
    stages = {e["stage"] for e in timeline["signal_entries"]}
    assert stages == set(ledger_svc.VALID_STAGES)


def test_empty_holdings_stages_not_passed_placeholders(tmp_path):
    db_path = tmp_path / "decision_trace.sqlite3"
    advice = {
        "schema_version": "portfolio-advice-v0.1",
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00+00:00",
        "market_status": "normal",
        "portfolio_summary": {"holding_count": 0},
        "account_action": {"action": "hold", "reason": "空仓", "confidence": "low"},
        "holdings": [],
        "warnings": [],
        "data_limitations": [],
    }
    res = ledger_svc.archive_signal_ledger(advice, db_path=db_path)
    assert res["status"] == "success"
    timeline = ledger_store.get_run_signal_ledger(res["decision_run_id"], db_path=db_path)
    stages = {e["stage"] for e in timeline["signal_entries"]}
    assert stages == set(ledger_svc.VALID_STAGES)
    placeholders = [
        e for e in timeline["signal_entries"] if e["signal_type"].endswith("_placeholder")
    ]
    for p in placeholders:
        assert p["payload_json"].get("status") == "not_applicable"


def test_reject_bad_ratio_not_written(tmp_path):
    db_path = tmp_path / "decision_trace.sqlite3"
    advice = {
        "schema_version": "portfolio-advice-v0.1",
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00+00:00",
        "market_status": "normal",
        "portfolio_summary": {"holding_count": 1},
        "account_action": {"action": "hold", "reason": "x", "confidence": "low"},
        "holdings": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "action": "reduce",
                "execution_size_pct_of_holding": True,  # bool must not become 0.01
                "execution_quantity": 100,
                "shares": 300,
                "sellable_quantity_advisory": 100,
                "execution_plan": [{"bad": 1}],
                "trigger_conditions": [],
                "price_conditions": [],
                "risk_conditions": [],
                "invalidation_conditions": [],
                "data_limitations": [],
                "confidence": "low",
            }
        ],
        "warnings": [],
        "data_limitations": [],
    }
    res = ledger_svc.archive_signal_ledger(advice, db_path=db_path)
    assert res["status"] == "success"
    timeline = ledger_store.get_run_signal_ledger(res["decision_run_id"], db_path=db_path)
    outcome = timeline["decision_outcomes"][0]
    assert outcome["target_ratio"] is None
    assert outcome["reason"] == "结构化执行条件已归档"
