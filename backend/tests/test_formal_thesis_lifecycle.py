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


def _formalized_with_link(db, *, frozen: bool):
    """Create a Formal thesis with one linked evidence record.

    The evidence link is created before confirmation so the mutation-closure
    tests can assert that confirmed/frozen states reject stance changes and
    unlink operations without touching the real database.
    """
    result = _thesis(db)
    tid = result["thesis"]["id"]
    svc.begin_formalization(db, tid)
    evidence = svc.create_evidence(db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "claim", "source_title": "source", "source_url": None,
        "source_date": None, "accessed_at": "2026-01-01T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    svc.link_evidence(db, tid, evidence["id"], "support", 1)
    svc.update_thesis(db, tid, {
        "title": "标题", "summary": "摘要", "status": "active",
        "core_claims": ["a", "b", "c"], "catalysts": [], "risks": [],
        "invalidation_conditions": [], "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
        "free_notes": "note",
    }, 2)
    svc.confirm_formalization(db, tid, 3)
    expected_revision = 3
    if frozen:
        svc.freeze_formalization(db, tid, expected_revision)
        expected_revision = 4
    return tid, evidence["id"], expected_revision


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "evidence.db"
    store.initialize_store(path)
    return path


def test_begin_confirm_freeze_archive_without_revision_bump_on_markers(db):
    tid = _draft(db)
    assert svc.confirm_formalization(db, tid, 2)["thesis"]["current_revision"] == 2
    frozen = svc.freeze_formalization(db, tid, 2)
    assert frozen["formal_state"] == "frozen"
    assert frozen["current_revision"] == frozen["frozen_revision"] == 3
    archived = svc.archive_formalization(db, tid, 3)
    assert archived["status"] == "archived"
    assert archived["current_revision"] == 4
    assert archived["frozen_revision"] == 3
    assert archived["thesis"]["status"] == "archived"
    assert archived["thesis"]["current_revision"] == 4
    assert archived["thesis"]["archived_at"] == archived["archived_at"]
    fetched = svc.get_thesis(db, tid)
    assert fetched["thesis"]["status"] == "archived"
    assert fetched["thesis"]["current_revision"] == 4


def test_confirm_hard_gate_and_content_lock(db):
    result = _thesis(db)
    tid = result["thesis"]["id"]
    svc.begin_formalization(db, tid)
    with pytest.raises(svc.ValidationError):
        svc.confirm_formalization(db, tid, 1)
    draft_id = _draft(db)
    svc.confirm_formalization(db, draft_id, 2)
    with pytest.raises(svc.ContentLockedError):
        svc.update_thesis(db, draft_id, {
            "title": "改", "summary": "摘要", "status": "active",
            "core_claims": ["a", "b", "c"], "catalysts": [], "risks": [],
            "invalidation_conditions": [],
        }, 2)


def test_draft_rejects_legacy_archive_without_persisted_mutation(db):
    tid = _draft(db)

    with pytest.raises(svc.FormalLifecycleConflictError):
        svc.archive_thesis(db, tid, 2)

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT formal_state, status, current_revision FROM investment_theses WHERE id=?",
            (tid,),
        ).fetchone()
        assert row == ("draft", "active", 2)
        assert conn.execute(
            "SELECT COUNT(*) FROM thesis_revisions WHERE thesis_id=?", (tid,)
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_vnext_revisions_have_explicit_content_kind(db):
    tid = _thesis(db)["thesis"]["id"]
    svc.begin_formalization(db, tid)
    svc.update_thesis(db, tid, {
        "title": "标题", "summary": "摘要", "status": "active",
        "core_claims": ["a", "b", "c"], "catalysts": [], "risks": [],
        "invalidation_conditions": [], "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
        "free_notes": "note",
    }, 1)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            "SELECT revision_number, revision_kind FROM thesis_revisions "
            "WHERE thesis_id=? ORDER BY revision_number", (tid,)
        ).fetchall() == [(1, "CONTENT"), (2, "CONTENT")]
    finally:
        conn.close()


def test_preconfirm_evidence_cascade_revisions_have_content_kind(db):
    tid = _thesis(db)["thesis"]["id"]
    svc.begin_formalization(db, tid)
    ev = svc.create_evidence(db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "claim", "source_title": "source", "source_url": None,
        "source_date": None, "accessed_at": "2026-01-01T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    svc.link_evidence(db, tid, ev["id"], "support", 1)
    svc.update_stance(db, tid, ev["id"], "oppose", 2)
    svc.update_evidence(db, ev["id"], {
        "evidence_type": "news", "claim": "changed", "source_title": "source",
        "source_url": None, "source_date": None, "accessed_at": "2026-01-02T00:00:00+00:00",
        "classification": "inference", "confidence": "medium",
    })
    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            "SELECT revision_number, revision_kind FROM thesis_revisions "
            "WHERE thesis_id=? ORDER BY revision_number", (tid,)
        ).fetchall() == [(1, "CONTENT"), (2, "CONTENT"), (3, "CONTENT"), (4, "CONTENT")]
    finally:
        conn.close()


def test_legacy_null_revision_kind_remains_readable(db):
    tid = _thesis(db)["thesis"]["id"]
    conn = sqlite3.connect(db)
    conn.execute("UPDATE thesis_revisions SET revision_kind=NULL WHERE thesis_id=? AND revision_number=1", (tid,))
    conn.commit(); conn.close()
    assert svc.get_revision(db, tid, 1)["revision_kind"] is None
    assert svc.list_revisions(db, tid)["items"][0]["revision_number"] == 1


def test_freeze_preserves_confirmed_evidence_and_rejects_live_drift(db):
    tid = _draft(db)
    evidence = svc.create_evidence(db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "confirmed claim", "source_title": "source", "source_url": None,
        "source_date": None, "accessed_at": "2026-01-01T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    svc.link_evidence(db, tid, evidence["id"], "support", 2)
    svc.confirm_formalization(db, tid, 3)
    svc.update_evidence(db, evidence["id"], {
        "evidence_type": "news", "claim": "mutated later", "source_title": "source",
        "source_url": None, "source_date": None, "accessed_at": "2026-01-01T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    frozen = svc.freeze_formalization(db, tid, 3)
    assert frozen["evidence_links"][0]["claim"] == "confirmed claim"

    # Direct live-row drift on a still-confirmed thesis is fail-closed.
    drift_id = _draft(db)
    svc.confirm_formalization(db, drift_id, 2)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE investment_theses SET strategy='SHORT' WHERE id=?", (drift_id,))
    conn.commit(); conn.close()
    with pytest.raises(store.EvidenceLedgerCorruptedError):
        svc.freeze_formalization(db, drift_id, 2)


@pytest.mark.parametrize("frozen", [False, True], ids=["confirmed", "frozen"])
@pytest.mark.parametrize("operation", ["update_stance", "unlink_evidence"])
def test_formal_content_lock_closes_stance_and_unlink_mutations(db, frozen, operation):
    """Confirmed/Frozen states reject link-content mutations atomically."""
    tid, evidence_id, expected_revision = _formalized_with_link(db, frozen=frozen)

    with pytest.raises(svc.ContentLockedError):
        if operation == "update_stance":
            svc.update_stance(db, tid, evidence_id, "oppose", expected_revision)
        else:
            svc.unlink_evidence(db, tid, evidence_id, expected_revision)

    conn = sqlite3.connect(db)
    try:
        thesis = conn.execute(
            "SELECT formal_state, current_revision FROM investment_theses WHERE id=?",
            (tid,),
        ).fetchone()
        assert thesis == ("frozen" if frozen else "confirmed", expected_revision)
        expected_revision_count = 4 if frozen else 3
        assert conn.execute(
            "SELECT COUNT(*) FROM thesis_revisions WHERE thesis_id=?", (tid,)
        ).fetchone()[0] == expected_revision_count
        link = conn.execute(
            "SELECT stance FROM thesis_evidence_links WHERE thesis_id=? AND evidence_id=?",
            (tid, evidence_id),
        ).fetchone()
        assert link == ("support",)
    finally:
        conn.close()
