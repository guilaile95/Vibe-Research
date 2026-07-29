"""API integration tests for decision_evidence_router.py using FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
import decision_evidence_service as svc
import decision_trace_store as store


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_trace.sqlite3"
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VIBE_RESEARCH_DECISION_TRACE_DB", str(db_path))

    with TestClient(app) as test_client:
        yield {
            "client": test_client,
            "db_path": db_path,
        }


def _seed_run(db_path, trade_date="2026-07-29", generated_at="2026-07-29T10:00:00.000000+00:00"):
    advice = {
        "trade_date": trade_date,
        "generated_at": generated_at,
        "market_status": "normal",
        "account_action": "hold",
        "items": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "action": "hold",
                "reason": "Stable",
                "current_price": 1800.0,
            }
        ],
    }
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
    _seed_run(db_path)

    resp = tc.get("/api/decision-evidence?code=600519&trade_date=2026-07-29")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["code"] == "600519"


def test_list_decision_evidence_invalid_params(client):
    tc = client["client"]
    # Unknown parameter
    resp = tc.get("/api/decision-evidence?unknown_param=123")
    assert resp.status_code == 400

    # Invalid code
    resp2 = tc.get("/api/decision-evidence?code=abc")
    assert resp2.status_code == 400

    # Invalid trade_date format
    resp3 = tc.get("/api/decision-evidence?trade_date=20260729")
    assert resp3.status_code == 400


def test_get_evidence_by_id(client):
    tc = client["client"]
    db_path = client["db_path"]
    archived = _seed_run(db_path)
    run_id = archived["decision_run_id"]

    resp = tc.get(f"/api/decision-evidence/{run_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["decision_run"]["decision_run_id"] == run_id

    # Nonexistent
    resp_404 = tc.get("/api/decision-evidence/dr_nonexistent")
    assert resp_404.status_code == 404


def test_get_evidence_by_advice(client):
    tc = client["client"]
    db_path = client["db_path"]
    td = "2026-07-29"
    gen_at = "2026-07-29T10:00:00.000000+00:00"
    archived = _seed_run(db_path, trade_date=td, generated_at=gen_at)

    resp = tc.get(f"/api/decision-evidence/by-advice?trade_date={td}&generated_at={gen_at}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["decision_run"]["decision_run_id"] == archived["decision_run_id"]

    # Missing parameters
    resp_bad = tc.get("/api/decision-evidence/by-advice?trade_date=2026-07-29")
    assert resp_bad.status_code == 400


def test_db_corruption_handling(client):
    tc = client["client"]
    db_path = client["db_path"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open(db_path, "wb") as f:
        f.write(b"CORRUPTED FILE CONTENT")

    resp = tc.get("/api/decision-evidence")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "决策追踪数据损坏，已停止读写"


def test_read_only_endpoint(client):
    tc = client["client"]
    resp = tc.post("/api/decision-evidence", json={})
    assert resp.status_code == 405
