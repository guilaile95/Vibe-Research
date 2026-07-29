"""Unit tests for decision_feedback_store.py."""
from __future__ import annotations

import concurrent.futures
import sqlite3
import uuid
import pytest

import decision_feedback_store as store


def test_insert_and_get_record(tmp_path):
    db_path = tmp_path / "test_feedback.sqlite3"
    rec = {
        "feedback_id": "fb_001",
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "trade_id": "tr_001",
        "adoption_status": "followed",
        "outcome_status": "better_than_expected",
        "note": "Test note",
        "created_at": "2026-07-29T10:05:00.000000+00:00",
        "voided_at": None,
        "void_reason": None,
    }
    store.insert_record(db_path, rec)

    retrieved = store.get_record(db_path, "fb_001")
    assert retrieved is not None
    assert retrieved["feedback_id"] == "fb_001"
    assert retrieved["code"] == "600519"
    assert retrieved["adoption_status"] == "followed"
    assert retrieved["outcome_status"] == "better_than_expected"
    assert retrieved["note"] == "Test note"
    assert retrieved["voided_at"] is None


def test_get_nonexistent_record(tmp_path):
    db_path = tmp_path / "test_feedback.sqlite3"
    assert store.get_record(db_path, "nonexistent") is None


def test_list_records_and_filters(tmp_path):
    db_path = tmp_path / "test_feedback.sqlite3"

    rec1 = {
        "feedback_id": "fb_101",
        "code": "600519",
        "advice_trade_date": "2026-07-28",
        "advice_generated_at": "2026-07-28T10:00:00.000000+00:00",
        "trade_id": None,
        "adoption_status": "followed",
        "outcome_status": "as_expected",
        "note": None,
        "created_at": "2026-07-28T10:00:00.000000+00:00",
        "voided_at": None,
        "void_reason": None,
    }
    rec2 = {
        "feedback_id": "fb_102",
        "code": "000001",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "trade_id": None,
        "adoption_status": "not_followed",
        "outcome_status": "worse_than_expected",
        "note": "Bad decision",
        "created_at": "2026-07-29T10:00:00.000000+00:00",
        "voided_at": None,
        "void_reason": None,
    }
    store.insert_record(db_path, rec1)
    store.insert_record(db_path, rec2)

    # Filter by code
    res = store.list_records(db_path, code="600519")
    assert len(res) == 1
    assert res[0]["feedback_id"] == "fb_101"

    # Filter by adoption_status
    res = store.list_records(db_path, adoption_status="not_followed")
    assert len(res) == 1
    assert res[0]["feedback_id"] == "fb_102"

    # Filter by outcome_status
    res = store.list_records(db_path, outcome_status="as_expected")
    assert len(res) == 1
    assert res[0]["feedback_id"] == "fb_101"

    # Date range filter
    res = store.list_records(db_path, date_from="2026-07-29")
    assert len(res) == 1
    assert res[0]["feedback_id"] == "fb_102"

    res = store.list_records(db_path, date_to="2026-07-28")
    assert len(res) == 1
    assert res[0]["feedback_id"] == "fb_101"

    # Pagination
    res = store.list_records(db_path, limit=1, offset=0)
    assert len(res) == 1
    assert res[0]["feedback_id"] == "fb_102"  # DESC order


def test_void_record(tmp_path):
    db_path = tmp_path / "test_feedback.sqlite3"
    rec = {
        "feedback_id": "fb_201",
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "trade_id": None,
        "adoption_status": "followed",
        "outcome_status": "as_expected",
        "note": None,
        "created_at": "2026-07-29T10:00:00.000000+00:00",
        "voided_at": None,
        "void_reason": None,
    }
    store.insert_record(db_path, rec)

    # Voiding nonexistent
    with pytest.raises(store.DecisionFeedbackNotFoundError):
        store.void_record(db_path, "fb_missing")

    # Voiding valid record
    voided = store.void_record(db_path, "fb_201", void_reason="Entered by mistake")
    assert voided["feedback_id"] == "fb_201"
    assert voided["voided_at"] is not None
    assert voided["void_reason"] == "Entered by mistake"

    # Default list excludes voided
    assert len(store.list_records(db_path)) == 0
    # Include voided returns it
    assert len(store.list_records(db_path, include_voided=True)) == 1

    # Voiding already voided raises 409 exception
    with pytest.raises(store.DecisionFeedbackAlreadyVoidedError):
        store.void_record(db_path, "fb_201")


def test_concurrent_void_record(tmp_path):
    db_path = tmp_path / "concurrent_test.sqlite3"
    fb_id = f"fb_{uuid.uuid4().hex}"
    rec = {
        "feedback_id": fb_id,
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "trade_id": None,
        "adoption_status": "followed",
        "outcome_status": "as_expected",
        "note": None,
        "created_at": "2026-07-29T10:00:00.000000+00:00",
        "voided_at": None,
        "void_reason": None,
    }
    store.insert_record(db_path, rec)

    results = []
    errors = []

    def _do_void(reason: str):
        try:
            res = store.void_record(db_path, fb_id, void_reason=reason)
            results.append(res)
        except Exception as exc:
            errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_do_void, "reason 1")
        f2 = executor.submit(_do_void, "reason 2")
        f1.result()
        f2.result()

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], store.DecisionFeedbackAlreadyVoidedError)
    assert not isinstance(errors[0], store.DecisionFeedbackCorruptedError)


def test_corrupted_database_handling(tmp_path):
    db_path = tmp_path / "corrupted.sqlite3"
    db_path.write_bytes(b"NOT A SQLITE FILE HELLO WORLD")

    with pytest.raises(store.DecisionFeedbackCorruptedError):
        store.get_record(db_path, "fb_001")

    with pytest.raises(store.DecisionFeedbackCorruptedError):
        store.list_records(db_path)

    rec = {
        "feedback_id": "fb_err",
        "code": "600519",
        "advice_trade_date": "2026-07-29",
        "advice_generated_at": "2026-07-29T10:00:00.000000+00:00",
        "trade_id": None,
        "adoption_status": "followed",
        "outcome_status": "as_expected",
        "note": None,
        "created_at": "2026-07-29T10:00:00.000000+00:00",
        "voided_at": None,
        "void_reason": None,
    }
    with pytest.raises(store.DecisionFeedbackCorruptedError):
        store.insert_record(db_path, rec)

    with pytest.raises(store.DecisionFeedbackCorruptedError):
        store.void_record(db_path, "fb_err")
