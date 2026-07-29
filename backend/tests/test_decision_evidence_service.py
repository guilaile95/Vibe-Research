"""Unit tests for decision_evidence_service against authoritative advice contract."""

from __future__ import annotations

import hashlib

import decision_evidence_service as svc
import decision_trace_store as store
from authoritative_advice_fixtures import build_authoritative_from_golden


def test_generate_decision_run_id():
    td = "2026-07-29"
    gen_at = "2026-07-29T09:30:00.000000+00:00"
    expected_hash = hashlib.sha256(
        f"portfolio_advice\n{td}\n{gen_at}".encode("utf-8")
    ).hexdigest()
    expected_id = f"dr_{expected_hash}"

    run_id = svc.generate_decision_run_id(td, gen_at)
    assert run_id == expected_id
    assert svc.generate_decision_run_id(td, gen_at) == run_id


def test_archive_decision_evidence_success(tmp_path, monkeypatch):
    db_path = tmp_path / "test_evidence.sqlite3"
    advice_result = build_authoritative_from_golden(monkeypatch)

    res = svc.archive_decision_evidence(advice_result, db_path=db_path)
    assert res["status"] == "archived"
    assert res["evidence_count"] > 0
    assert res["explanation_count"] > 0

    run_id = res["decision_run_id"]
    bundle = store.get_decision_run(run_id, db_path=db_path)
    assert bundle is not None
    assert bundle["decision_run"]["trace_status"] == "archived"

    scopes = {ev["scope"] for ev in bundle["evidence_items"]}
    assert "market" in scopes
    assert "stock" in scopes
    assert "account" in scopes
    assert "portfolio" in scopes
    assert "risk" in scopes

    account_ev = next(ev for ev in bundle["evidence_items"] if ev["scope"] == "account")
    assert account_ev["quality_status"] != "missing"
    assert account_ev["evidence_key"] == "account_funding"
    assert isinstance(account_ev["value_json"], dict)
    assert "configured" in account_ev["value_json"]

    risk_ev = next(ev for ev in bundle["evidence_items"] if ev["scope"] == "risk")
    assert "sellable_quantity_evaluated" in risk_ev["value_json"]
    assert risk_ev["value_json"]["sellable_quantity_evaluated"] is True
    assert "cash_constraint_evaluated" in risk_ev["value_json"]
    assert "sellable_quantity_applied" not in risk_ev["value_json"]

    explanations = bundle["explanation_items"]
    stock_exp = next(exp for exp in explanations if exp["code"] == "600519")
    assert stock_exp["conclusion_value"] == "reduce"
    assert stock_exp["explanation_text"]
    assert "Stock 600519" not in stock_exp["explanation_text"]

    account_exp = next(
        exp for exp in explanations if exp["conclusion_type"] == "account_action"
    )
    assert account_exp["conclusion_value"] == "hold"
    assert "{" not in str(account_exp["conclusion_value"])
    assert account_exp["explanation_text"]


def test_archive_decision_evidence_account_missing(tmp_path):
    db_path = tmp_path / "test_evidence.sqlite3"
    advice = {
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00.000000+00:00",
        "market_status": "normal",
        "portfolio_summary": {"holding_count": 0},
        "account_action": {"action": "hold", "reason": "空仓", "confidence": "low"},
        "holdings": [],
        "warnings": [],
        "data_limitations": [],
    }
    res = svc.archive_decision_evidence(advice, db_path=db_path)
    assert res["status"] == "archived"
    bundle = store.get_decision_run(res["decision_run_id"], db_path=db_path)
    account_ev = next(ev for ev in bundle["evidence_items"] if ev["scope"] == "account")
    assert account_ev["quality_status"] == "missing"


def test_archive_decision_evidence_error_resilience(tmp_path):
    db_path = tmp_path / "test_evidence.sqlite3"

    res1 = svc.archive_decision_evidence("invalid_str", db_path=db_path)
    assert res1["status"] == "failed"

    corrupt_db = tmp_path / "corrupt.sqlite3"
    with open(corrupt_db, "wb") as f:
        f.write(b"BAD DB DATA")

    valid_advice = {
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00.000000+00:00",
    }
    res2 = svc.archive_decision_evidence(valid_advice, db_path=corrupt_db)
    assert res2["status"] == "failed"
