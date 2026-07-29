"""Unit tests for decision_evidence_service.py."""

from __future__ import annotations

import hashlib
import pytest
import decision_evidence_service as svc
import decision_trace_store as store


def test_generate_decision_run_id():
    td = "2026-07-29"
    gen_at = "2026-07-29T09:30:00.000000+00:00"
    expected_hash = hashlib.sha256(f"portfolio_advice\n{td}\n{gen_at}".encode("utf-8")).hexdigest()
    expected_id = f"dr_{expected_hash}"

    run_id = svc.generate_decision_run_id(td, gen_at)
    assert run_id == expected_id

    # Determinism
    assert svc.generate_decision_run_id(td, gen_at) == run_id


def test_archive_decision_evidence_success(tmp_path):
    db_path = tmp_path / "test_evidence.sqlite3"

    advice_result = {
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00.000000+00:00",
        "market_status": "normal",
        "account_action": "hold",
        "account_reason": "Maintain balanced posture",
        "account_funding_metrics": {
            "total_asset": 100000.0,
            "cash": 20000.0,
        },
        "items": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "action": "hold",
                "reason": "Stable fundamental outlook",
                "current_price": 1800.0,
                "change_pct": 0.5,
                "holding_weight_pct": 25.0,
                "shares": 100,
                "sellable_shares": 100,
                "execution_size_pct_of_holding": 0.0,
            }
        ],
    }

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

    explanations = bundle["explanation_items"]
    assert len(explanations) >= 1
    stock_exp = next(exp for exp in explanations if exp["code"] == "600519")
    assert stock_exp["conclusion_value"] == "hold"
    assert len(stock_exp["supporting_evidence_ids"]) > 0


def test_archive_decision_evidence_error_resilience(tmp_path):
    db_path = tmp_path / "test_evidence.sqlite3"

    # Non-dict advice_result handled gracefully
    res1 = svc.archive_decision_evidence("invalid_str", db_path=db_path)
    assert res1["status"] == "failed"

    # Corrupted database handled gracefully without throwing
    corrupt_db = tmp_path / "corrupt.sqlite3"
    with open(corrupt_db, "wb") as f:
        f.write(b"BAD DB DATA")

    valid_advice = {
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00.000000+00:00",
    }
    res2 = svc.archive_decision_evidence(valid_advice, db_path=corrupt_db)
    assert res2["status"] == "failed"
