"""Unit tests for signal ledger REST API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
import decision_trace_store as trace_store
import signal_ledger_service as svc
from authoritative_advice_fixtures import build_authoritative_from_golden

client = TestClient(app)


@pytest.fixture
def setup_signal_db(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_DECISION_TRACE_DB", str(db_path))

    advice_result = build_authoritative_from_golden(monkeypatch)
    run_id = svc.decision_evidence_service.generate_decision_run_id(
        str(advice_result["trade_date"]), str(advice_result["generated_at"])
    )
    trace_store.save_decision_run_bundle(
        run_record={
            "decision_run_id": run_id,
            "trade_date": advice_result["trade_date"],
            "generated_at": advice_result["generated_at"],
            "result_type": "portfolio_advice",
            "schema_version": advice_result.get("schema_version") or "portfolio-advice-v0.1",
            "market_status": advice_result.get("market_status") or "normal",
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
    assert data["total"] >= 1
    assert all(item["code"] == "600519" for item in data["items"])

    res2 = client.get("/api/signal-ledger", params={"stage": "schema"})
    assert res2.status_code == 200
    data2 = res2.json()["data"]
    assert data2["total"] >= 1
    assert all(item["stage"] == "schema" for item in data2["items"])


def test_get_run_signal_ledger_api(setup_signal_db):
    db_path, run_id = setup_signal_db
    res = client.get(f"/api/signal-ledger/run/{run_id}")
    assert res.status_code == 200
    data = res.json()["data"]
    stages = {e["stage"] for e in data["signal_entries"]}
    assert stages == set(svc.VALID_STAGES)
    assert len(data["decision_outcomes"]) == 1
    assert data["decision_outcomes"][0]["code"] == "600519"
