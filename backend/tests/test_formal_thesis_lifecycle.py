"""P0-PH2 S2D-B Formal Thesis lifecycle contract tests."""

import json
import sqlite3

import pytest

import evidence_thesis_service as svc
import evidence_thesis_store as store


def _thesis(db):
    return svc.create_thesis(db, {
        "subject_type": "stock", "subject_id": "600519",
        "title": "标题", "summary": "摘要", "core_claims": ["a", "b", "c"],
        "catalysts": [], "risks": [], "invalidation_conditions": [],
    })


def _draft(db):
    result = _thesis(db)
    tid = result["thesis"]["id"]
    svc.begin_formalization(db, tid)
    svc.update_thesis(db, tid, {
        "title": "标题", "summary": "摘要", "status": "active",
        "core_claims": ["a", "b", "c"], "catalysts": [], "risks": [],
        "invalidation_conditions": [], "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
        "free_notes": "note",
    }, 1)
    return tid


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "evidence.db"
    store.initialize_store(path)
    return path


def test_begin_confirm_freeze_archive_without_revision_bump_on_markers(db):
    tid = _draft(db)
    assert svc.confirm_formalization(db, tid)["thesis"]["current_revision"] == 2
    frozen = svc.freeze_formalization(db, tid, 2)
    assert frozen["formal_state"] == "frozen"
    assert frozen["current_revision"] == frozen["frozen_revision"] == 3
    archived = svc.archive_formalization(db, tid, 3)
    assert archived["status"] == "archived"
    assert archived["current_revision"] == 4
    assert archived["frozen_revision"] == 3


def test_confirm_hard_gate_and_content_lock(db):
    result = _thesis(db)
    tid = result["thesis"]["id"]
    svc.begin_formalization(db, tid)
    with pytest.raises(svc.ValidationError):
        svc.confirm_formalization(db, tid)
    draft_id = _draft(db)
    svc.confirm_formalization(db, draft_id)
    with pytest.raises(svc.ContentLockedError):
        svc.update_thesis(db, draft_id, {
            "title": "改", "summary": "摘要", "status": "active",
            "core_claims": ["a", "b", "c"], "catalysts": [], "risks": [],
            "invalidation_conditions": [],
        }, 2)


def test_freeze_preserves_confirmed_evidence_and_rejects_live_drift(db):
    tid = _draft(db)
    evidence = svc.create_evidence(db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "confirmed claim", "source_title": "source", "source_url": None,
        "source_date": None, "accessed_at": "2026-01-01T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    svc.link_evidence(db, tid, evidence["id"], "support", 2)
    svc.confirm_formalization(db, tid)
    svc.update_evidence(db, evidence["id"], {
        "evidence_type": "news", "claim": "mutated later", "source_title": "source",
        "source_url": None, "source_date": None, "accessed_at": "2026-01-01T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    frozen = svc.freeze_formalization(db, tid, 3)
    assert frozen["evidence_links"][0]["claim"] == "confirmed claim"

    # Direct live-row drift on a still-confirmed thesis is fail-closed.
    drift_id = _draft(db)
    svc.confirm_formalization(db, drift_id)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE investment_theses SET strategy='SHORT' WHERE id=?", (drift_id,))
    conn.commit(); conn.close()
    with pytest.raises(store.EvidenceLedgerCorruptedError):
        svc.freeze_formalization(db, drift_id, 2)
