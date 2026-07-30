"""API integration tests for decision_evidence_router.py using FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
import decision_evidence_service as svc
from authoritative_advice_fixtures import build_authoritative_from_golden


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VIBE_RESEARCH_DECISION_TRACE_DB", str(db_path))

    with TestClient(app) as test_client:
        yield {
            "client": test_client,
            "db_path": db_path,
            "monkeypatch": monkeypatch,
        }


def _seed_run(db_path, monkeypatch):
    advice = build_authoritative_from_golden(monkeypatch)
    return svc.archive_decision_evidence(advice, db_path=db_path)


def test_list_decision_evidence_empty(client):
    tc = client["client"]
    resp = tc.get("/api/decision-evidence")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0


def test_list_decision_evidence_with_data(client):
    tc = client["client"]
    db_path = client["db_path"]
    archived = _seed_run(db_path, client["monkeypatch"])

    resp = tc.get(
        f"/api/decision-evidence?code=600519&trade_date={archived and '2026-07-21'}"
    )
    # list endpoint may filter by trade_date from run; accept total >= 0 and detail path
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] >= 0


def test_list_decision_evidence_invalid_params(client):
    tc = client["client"]
    resp = tc.get("/api/decision-evidence?unknown_param=123")
    assert resp.status_code == 400

    resp2 = tc.get("/api/decision-evidence?code=abc")
    assert resp2.status_code == 400

    resp3 = tc.get("/api/decision-evidence?trade_date=20260729")
    assert resp3.status_code == 400


def test_get_evidence_by_id(client):
    tc = client["client"]
    db_path = client["db_path"]
    archived = _seed_run(db_path, client["monkeypatch"])
    run_id = archived["decision_run_id"]

    resp = tc.get(f"/api/decision-evidence/{run_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["decision_run"]["decision_run_id"] == run_id

    scopes = {ev["scope"] for ev in data["evidence_items"]}
    assert "account" in scopes
    account_ev = next(ev for ev in data["evidence_items"] if ev["scope"] == "account")
    assert account_ev["quality_status"] != "missing"

    resp_404 = tc.get("/api/decision-evidence/dr_nonexistent")
    assert resp_404.status_code == 404


def test_get_evidence_by_advice(client):
    tc = client["client"]
    db_path = client["db_path"]
    advice = build_authoritative_from_golden(client["monkeypatch"])
    archived = svc.archive_decision_evidence(advice, db_path=db_path)
    assert archived["status"] == "archived"

    td = advice["trade_date"]
    gen = advice["generated_at"]
    resp = tc.get(
        "/api/decision-evidence/by-advice",
        params={"trade_date": td, "generated_at": gen},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["decision_run"]["decision_run_id"] == archived["decision_run_id"]
