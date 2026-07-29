"""API integration tests for decision_feedback_router.py using FastAPI TestClient."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ai_result_store
from app import app
import decision_feedback_store as df_store
import trade_ledger_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    feedback_db = tmp_path / "decision_feedback.sqlite3"
    review_db = tmp_path / "review_history.sqlite3"
    trade_db = tmp_path / "trade_ledger.sqlite3"

    monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(feedback_db))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(review_db))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(trade_db))

    with TestClient(app) as test_client:
        yield {
            "client": test_client,
            "feedback_db": feedback_db,
            "review_db": review_db,
            "trade_db": trade_db,
        }


def _seed_advice(review_db, trade_date="2026-07-29", generated_at="2026-07-29T10:00:00.000000+00:00", holdings=None):
    if holdings is None:
        holdings = [{"code": "600519", "name": "贵州茅台", "action": "hold"}]
    payload = {
        "trade_date": trade_date,
        "generated_at": generated_at,
        "holdings": holdings,
    }
    record = {
        "result_type": "portfolio_advice",
        "trade_date": trade_date,
        "schema_version": "portfolio_advice.v1",
        "payload": payload,
        "generated_at": generated_at,
        "model_provider": "test_provider",
        "model_name": "test_model",
        "input_fingerprint": "a" * 64,
    }
    ai_result_store.upsert_result(review_db, record)


def _seed_trade(trade_db, trade_id="tr_001", code="600519", advice_trade_date="2026-07-29", advice_generated_at="2026-07-29T10:00:00.000000+00:00"):
    rec = {
        "trade_id": trade_id,
        "code": code,
        "name": "贵州茅台",
        "operation": "buy",
        "execution_status": "full",
        "planned_price": 1700.0,
        "planned_quantity": 100,
        "actual_price": 1700.0,
        "actual_quantity": 100,
        "executed_at": "2026-07-29T10:01:00.000000+00:00",
        "fee": 5.0,
        "other_cost": 0.0,
        "unexecuted_reason": None,
        "note": None,
        "advice_trade_date": advice_trade_date,
        "advice_generated_at": advice_generated_at,
        "advice_snapshot": None,
        "thesis_id": None,
        "thesis_revision": None,
        "created_at": "2026-07-29T10:01:00.000000+00:00",
    }
    trade_ledger_store.insert_record(trade_db, rec)


def test_post_decision_feedback_success(client):
    _seed_advice(client["review_db"])
    _seed_trade(client["trade_db"], trade_id="tr_001")

    payload = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "trade_id": "tr_001",
        "adoption_status": "followed",
        "outcome_status": "better_than_expected",
        "note": "Worked great",
    }
    res = client["client"].post("/api/decision-feedback", json=payload)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["feedback_id"].startswith("fb_")
    assert data["code"] == "600519"
    assert data["adoption_status"] == "followed"


def test_post_decision_feedback_errors(client):
    tc = client["client"]
    _seed_advice(client["review_db"])

    # 400 Non-JSON body
    res = tc.post("/api/decision-feedback", content="not json")
    assert res.status_code == 400

    # 404 Advice missing
    payload = {
        "code": "600519",
        "advice_trade_date": "2026-01-01",
        "advice_generated_at": "2026-01-01T10:00:00.000000+00:00",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    res = tc.post("/api/decision-feedback", json=payload)
    assert res.status_code == 404

    # 409 Advice timestamp conflict
    payload = {
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T11:11:11.000000+00:00",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    res = tc.post("/api/decision-feedback", json=payload)
    assert res.status_code == 409

    # 404 Advice holding code missing
    _seed_advice(client["review_db"], trade_date="2026-07-30", holdings=[{"code": "000001"}])
    payload = {
        "code": "600519",
        "advice_trade_date": "2026-07-30",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    res = tc.post("/api/decision-feedback", json=payload)
    assert res.status_code in (404, 409)

    # 422 Invalid enum status
    payload = {
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "adoption_status": "invalid_status",
        "outcome_status": "as_expected",
    }
    res = tc.post("/api/decision-feedback", json=payload)
    assert res.status_code == 422


def test_get_and_list_feedbacks(client):
    tc = client["client"]
    _seed_advice(client["review_db"])

    payload = {
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    create_res = tc.post("/api/decision-feedback", json=payload)
    assert create_res.status_code == 200
    fb_id = create_res.json()["data"]["feedback_id"]

    # GET single record
    res = tc.get(f"/api/decision-feedback/{fb_id}")
    assert res.status_code == 200
    assert res.json()["data"]["feedback_id"] == fb_id

    # GET nonexistent
    res = tc.get("/api/decision-feedback/nonexistent_id")
    assert res.status_code == 404

    # LIST records
    res = tc.get("/api/decision-feedback?code=600519")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 1

    # LIST with invalid filter
    res = tc.get("/api/decision-feedback?code=123")
    assert res.status_code == 422


def test_void_feedback(client):
    tc = client["client"]
    _seed_advice(client["review_db"])

    payload = {
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    create_res = tc.post("/api/decision-feedback", json=payload)
    fb_id = create_res.json()["data"]["feedback_id"]

    # Voiding
    res = tc.post(f"/api/decision-feedback/{fb_id}/void", json={"reason": "User requested"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["voided_at"] is not None
    assert data["void_reason"] == "User requested"

    # Repeat voiding -> 409
    res = tc.post(f"/api/decision-feedback/{fb_id}/void", json={"reason": "Repeat"})
    assert res.status_code == 409

    # Voiding missing -> 404
    res = tc.post("/api/decision-feedback/fb_missing/void", json={})
    assert res.status_code == 404


def test_corrupted_db_response_500(client):
    tc = client["client"]
    # Write corrupt data into feedback db
    client["feedback_db"].write_bytes(b"CORRUPTED FILE CONTENT")

    res = tc.get("/api/decision-feedback")
    assert res.status_code == 500
    assert res.json()["detail"] == "决策反馈数据损坏，已停止读写"
