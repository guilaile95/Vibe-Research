"""Unit tests for decision_feedback_service.py."""
from __future__ import annotations

import hashlib
import os
import re
import pytest

import ai_result_store
import decision_feedback_service as svc
import decision_feedback_store as df_store
import review_history
import trade_ledger_service
import trade_ledger_store


@pytest.fixture
def test_dbs(tmp_path, monkeypatch):
    feedback_db = tmp_path / "decision_feedback.sqlite3"
    review_db = tmp_path / "review_history.sqlite3"
    trade_db = tmp_path / "trade_ledger.sqlite3"
    portfolio_json = tmp_path / "portfolio.json"
    account_profile_json = tmp_path / "account_profile.json"

    portfolio_json.write_text('{"holdings": [{"code": "600519"}]}', encoding="utf-8")
    account_profile_json.write_text('{"total_cash": 100000.0}', encoding="utf-8")

    monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(feedback_db))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(review_db))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(trade_db))

    return {
        "feedback_db": feedback_db,
        "review_db": review_db,
        "trade_db": trade_db,
        "portfolio_json": portfolio_json,
        "account_profile_json": account_profile_json,
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


def test_resolve_db_path(tmp_path, monkeypatch):
    monkeypatch.delenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", raising=False)
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))

    path = svc.resolve_db_path()
    assert str(path) == str(tmp_path / "decision_feedback.sqlite3")

    monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(tmp_path / "custom.db"))
    assert str(svc.resolve_db_path()) == str(tmp_path / "custom.db")

    explicit = tmp_path / "explicit.db"
    assert str(svc.resolve_db_path(explicit)) == str(explicit)


def test_create_feedback_success(test_dbs):
    _seed_advice(test_dbs["review_db"])
    _seed_trade(test_dbs["trade_db"], trade_id="tr_100")

    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "trade_id": "tr_100",
        "adoption_status": "followed",
        "outcome_status": "better_than_expected",
        "note": "Great advice!",
    }

    rec = svc.create_feedback(data)
    # Check 128-bit UUID format: 'fb_' + 32 hex chars = 35 chars
    assert rec["feedback_id"].startswith("fb_")
    assert len(rec["feedback_id"]) == 35
    assert re.fullmatch(r"^fb_[0-9a-f]{32}$", rec["feedback_id"])
    assert rec["code"] == "600519"
    assert rec["advice_trade_date"] == "2026-07-29"
    assert rec["advice_generated_at"] == "2026-07-29T10:00:00.000000+00:00"
    assert rec["trade_id"] == "tr_100"
    assert rec["adoption_status"] == "followed"
    assert rec["outcome_status"] == "better_than_expected"
    assert rec["note"] == "Great advice!"
    assert rec["voided_at"] is None


def test_create_feedback_advice_not_found(test_dbs):
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.AdviceNotFoundError):
        svc.create_feedback(data)


def test_create_feedback_advice_conflict(test_dbs):
    _seed_advice(test_dbs["review_db"], generated_at="2026-07-29T10:00:00.000000+00:00")
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T12:00:00.000000+00:00",  # mismatched timestamp
        },
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.AdviceConflictError):
        svc.create_feedback(data)


def test_create_feedback_advice_holding_not_found(test_dbs):
    _seed_advice(test_dbs["review_db"], holdings=[{"code": "000001", "name": "平安银行"}])
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.AdviceHoldingNotFoundError):
        svc.create_feedback(data)


def test_create_feedback_trade_not_found(test_dbs):
    _seed_advice(test_dbs["review_db"])
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "trade_id": "tr_nonexistent",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.TradeNotFoundError):
        svc.create_feedback(data)


def test_create_feedback_trade_code_mismatch(test_dbs):
    _seed_advice(test_dbs["review_db"])
    _seed_trade(test_dbs["trade_db"], trade_id="tr_200", code="000001")
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "trade_id": "tr_200",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.TradeInvalidError) as exc_info:
        svc.create_feedback(data)
    assert "股票代码与反馈不一致" in str(exc_info.value)


def test_create_feedback_trade_no_advice_ref(test_dbs):
    _seed_advice(test_dbs["review_db"])
    _seed_trade(test_dbs["trade_db"], trade_id="tr_300", advice_trade_date=None, advice_generated_at=None)
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "trade_id": "tr_300",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.TradeInvalidError) as exc_info:
        svc.create_feedback(data)
    assert "无持仓建议信息" in str(exc_info.value)


def test_create_feedback_pydantic_extra_forbid(test_dbs):
    _seed_advice(test_dbs["review_db"])

    # Forbidden top-level field advice_trade_date
    data = {
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.DecisionFeedbackValidationError):
        svc.create_feedback(data)

    # Forbidden top-level field feedback_id
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "feedback_id": "fb_123",
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.DecisionFeedbackValidationError):
        svc.create_feedback(data)

    # Forbidden extra field inside advice_ref
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
            "extra_field": "not_allowed",
        },
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.DecisionFeedbackValidationError):
        svc.create_feedback(data)


def test_create_feedback_field_validations(test_dbs):
    _seed_advice(test_dbs["review_db"])

    # Invalid code
    data = {
        "code": "123",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    with pytest.raises(svc.DecisionFeedbackValidationError):
        svc.create_feedback(data)

    # Invalid adoption_status
    data["code"] = "600519"
    data["adoption_status"] = "invalid_status"
    with pytest.raises(svc.DecisionFeedbackValidationError):
        svc.create_feedback(data)

    # Invalid outcome_status
    data["adoption_status"] = "followed"
    data["outcome_status"] = "invalid_outcome"
    with pytest.raises(svc.DecisionFeedbackValidationError):
        svc.create_feedback(data)

    # Long note
    data["outcome_status"] = "as_expected"
    data["note"] = "a" * 2001
    with pytest.raises(svc.DecisionFeedbackValidationError):
        svc.create_feedback(data)


def test_service_list_get_void(test_dbs):
    _seed_advice(test_dbs["review_db"])
    data = {
        "code": "600519",
        "advice_ref": {
            "trade_date": "2026-07-29",
            "generated_at": "2026-07-29T10:00:00.000000+00:00",
        },
        "adoption_status": "followed",
        "outcome_status": "as_expected",
    }
    created = svc.create_feedback(data)
    fb_id = created["feedback_id"]

    fetched = svc.get_feedback(fb_id)
    assert fetched is not None
    assert fetched["feedback_id"] == fb_id

    lst = svc.list_feedbacks(code="600519")
    assert len(lst) == 1

    voided = svc.void_feedback(fb_id, {"reason": "Mistake"})
    assert voided["voided_at"] is not None
    assert voided["void_reason"] == "Mistake"

    with pytest.raises(svc.DecisionFeedbackAlreadyVoidedError):
        svc.void_feedback(fb_id)


def test_source_data_no_side_effects(test_dbs):
    """Verify create and void feedback operations cause ZERO changes/side effects to source data files."""
    _seed_advice(test_dbs["review_db"])
    _seed_trade(test_dbs["trade_db"], trade_id="tr_side_effect")

    review_db = test_dbs["review_db"]
    trade_db = test_dbs["trade_db"]
    portfolio_json = test_dbs["portfolio_json"]
    account_json = test_dbs["account_profile_json"]

    def _get_hashes():
        return {
            "review": hashlib.sha256(review_db.read_bytes()).hexdigest(),
            "trade": hashlib.sha256(trade_db.read_bytes()).hexdigest(),
            "portfolio": hashlib.sha256(portfolio_json.read_bytes()).hexdigest(),
            "account": hashlib.sha256(account_json.read_bytes()).hexdigest(),
        }

    initial_hashes = _get_hashes()

    # Perform create
    rec = svc.create_feedback(
        {
            "code": "600519",
            "advice_ref": {
                "trade_date": "2026-07-29",
                "generated_at": "2026-07-29T10:00:00.000000+00:00",
            },
            "trade_id": "tr_side_effect",
            "adoption_status": "followed",
            "outcome_status": "as_expected",
            "note": "Side effect test",
        }
    )

    post_create_hashes = _get_hashes()
    assert initial_hashes == post_create_hashes

    # Perform void
    svc.void_feedback(rec["feedback_id"], {"reason": "Testing side effects"})

    post_void_hashes = _get_hashes()
    assert initial_hashes == post_void_hashes
