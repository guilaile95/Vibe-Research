"""P0-PH2 S2D-C canonical thesis delta contract tests."""

from __future__ import annotations

import sqlite3
import threading

import pytest

import evidence_thesis_service as svc
import evidence_thesis_store as store


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "evidence.db"
    store.initialize_store(path)
    return path


def _frozen(db):
    result = svc.create_thesis(db, {
        "subject_type": "stock", "subject_id": "600519",
        "title": "标题", "summary": "摘要", "core_claims": ["a", "b", "c"],
        "catalysts": [], "risks": [], "invalidation_conditions": [],
    })
    tid = result["thesis"]["id"]
    svc.begin_formalization(db, tid)
    svc.update_thesis(db, tid, {
        "title": "标题", "summary": "摘要", "status": "active",
        "core_claims": ["a", "b", "c"], "catalysts": [], "risks": [],
        "invalidation_conditions": [], "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
        "free_notes": "note",
    }, 1)
    svc.confirm_formalization(db, tid)
    svc.freeze_formalization(db, tid, 2)
    return tid


def _evidence(db, tid):
    ev = svc.create_evidence(db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "claim", "source_title": "source", "source_url": "https://example.test",
        "source_date": "2026-01-01", "accessed_at": "2026-01-02T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    # frozen_revision is 3 and current_revision remains 3; linking before freeze
    # is therefore done by a dedicated thesis fixture in tests that need it.
    return ev["id"]


def test_append_and_ordered_read(db):
    tid = _frozen(db)
    first = svc.create_thesis_delta(db, tid, "STRENGTHENED", "first")
    second = svc.create_thesis_delta(db, tid, "WEAKENED", "second", base_revision=3)
    assert first["delta_sequence"] == 1
    assert second["delta_sequence"] == 2
    assert [x["delta_state"] for x in svc.list_thesis_deltas(db, tid)["items"]] == [
        "STRENGTHENED", "WEAKENED"
    ]


def test_preconditions_and_terminal_are_conflicts(db):
    tid = _frozen(db)
    with pytest.raises(svc.ThesisDeltaConflictError, match="base_revision"):
        svc.create_thesis_delta(db, tid, "STABLE", "x", base_revision=2)
    with pytest.raises(svc.ValidationError):
        svc.create_thesis_delta(db, tid, "BOGUS", "x")
    with pytest.raises(svc.ValidationError):
        svc.create_thesis_delta(db, tid, "STABLE", " ")
    svc.create_thesis_delta(db, tid, "DISPROVEN", "terminal")
    with pytest.raises(svc.ThesisDeltaConflictError, match="terminal"):
        svc.create_thesis_delta(db, tid, "STRENGTHENED", "after")


def test_unfrozen_and_archived_rejected(db):
    result = svc.create_thesis(db, {
        "subject_type": "stock", "subject_id": "600519", "title": "t", "summary": "s",
        "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
    })
    tid = result["thesis"]["id"]
    with pytest.raises(svc.ThesisDeltaConflictError, match="NEEDS_FROZEN"):
        svc.create_thesis_delta(db, tid, "STABLE", "x")
    frozen = _frozen(db)
    svc.archive_formalization(db, frozen, 3)
    with pytest.raises(svc.ThesisDeltaConflictError):
        svc.create_thesis_delta(db, frozen, "STABLE", "x")


def test_evidence_snapshot_is_immutable(db):
    # Build and link evidence before confirming/freeze so the frozen snapshot has
    # the thesis_evidence_links stance available to the delta writer.
    result = svc.create_thesis(db, {
        "subject_type": "stock", "subject_id": "600519", "title": "t", "summary": "s",
        "core_claims": ["a", "b", "c"], "catalysts": [], "risks": [], "invalidation_conditions": [],
    })
    tid = result["thesis"]["id"]
    svc.begin_formalization(db, tid)
    ev = svc.create_evidence(db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news", "claim": "before",
        "source_title": "source", "source_url": None, "source_date": None,
        "accessed_at": "2026-01-02T00:00:00+00:00", "classification": "fact", "confidence": "high",
    })
    svc.link_evidence(db, tid, ev["id"], "support", 1)
    svc.update_thesis(db, tid, {
        "title": "t", "summary": "s", "status": "active", "core_claims": ["a", "b", "c"],
        "catalysts": [], "risks": [], "invalidation_conditions": [], "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
        "free_notes": "note",
    }, 2)
    svc.confirm_formalization(db, tid)
    svc.freeze_formalization(db, tid, 3)
    delta = svc.create_thesis_delta(db, tid, "STRENGTHENED", "snapshot", [ev["id"]])
    svc.update_evidence(db, ev["id"], {
        "evidence_type": "news", "claim": "after", "source_title": "changed", "source_url": None,
        "source_date": None, "accessed_at": "2026-01-03T00:00:00+00:00",
        "classification": "inference", "confidence": "low",
    })
    snapshot = svc.list_thesis_deltas(db, tid)["items"][0]["evidence_links"][0]
    assert snapshot["claim"] == "before"
    assert snapshot["source_title"] == "source"
    assert delta["evidence_links"][0]["stance"] == "support"


def test_concurrent_writers_get_unique_sequences(db):
    tid = _frozen(db)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def writer(label):
        try:
            barrier.wait(timeout=5)
            results.append(svc.create_thesis_delta(db, tid, "STABLE", label))
        except Exception as exc:  # pragma: no cover - assertion below reports details
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(str(i),)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert sorted(item["delta_sequence"] for item in results) == [1, 2]


def test_corrupt_chain_fails_closed(db):
    tid = _frozen(db)
    svc.create_thesis_delta(db, tid, "STABLE", "first")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE thesis_deltas SET delta_sequence=2 WHERE thesis_id=?", (tid,))
    conn.commit()
    conn.close()
    with pytest.raises(store.EvidenceLedgerCorruptedError):
        svc.list_thesis_deltas(db, tid)

