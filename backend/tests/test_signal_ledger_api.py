"""Unit tests for signal ledger REST API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
import decision_trace_store as trace_store
import signal_ledger_service as svc
import signal_ledger_store as store

client = TestClient(app)


@pytest.fixture
def setup_signal_db(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_DECISION_TRACE_DB", str(db_path))

    # Pre-populate advice and signals
    advice_result = {
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00Z",
        "market_overview": {
            "market_sentiment": "cautious_optimistic",
            "position_recommendation": "moderate",
        },
        "actions": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "action": "buy",
                "target_ratio": 0.20,
                "reason": "估值回落",
            }
        ],
    }
    # Pre-insert decision_run
    run_id = svc.decision_evidence_service.generate_decision_run_id("2026-07-29", "2026-07-29T10:00:00Z")
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
    svc.archive_signal_ledger(advice_result, db_path=db_path)
    return db_path, run_id


def test_list_signal_entries_api(setup_signal_db):
    db_path, run_id = setup_signal_db

    res = client.get("/api/signal-ledger", params={"decision_run_id": run_id})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total"] >= 2
    assert len(data["items"]) >= 2


def test_list_signal_entries_filtering_api(setup_signal_db):
    db_path, run_id = setup_signal_db

    res = client.get("/api/signal-ledger", params={"code": "600519"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["code"] == "600519"

    # Unknown filter param
    res_bad = client.get("/api/signal-ledger", params={"foo": "bar"})
    assert res_bad.status_code == 400


def test_get_run_signal_ledger_api(setup_signal_db):
    db_path, run_id = setup_signal_db

    res = client.get(f"/api/signal-ledger/run/{run_id}")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["run"]["decision_run_id"] == run_id
    assert len(data["signal_entries"]) >= 2
    assert len(data["decision_outcomes"]) == 1


def test_get_run_signal_ledger_not_found(setup_signal_db):
    res = client.get("/api/signal-ledger/run/dr_non_existent")
    assert res.status_code == 404
