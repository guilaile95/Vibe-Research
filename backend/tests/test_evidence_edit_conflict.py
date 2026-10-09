"""Synthetic Evidence read/edit races; no providers or production data."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

import evidence_thesis_service as svc
import evidence_thesis_store as store
from test_evidence_thesis_service import _make_evidence_payload, _make_thesis_payload


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "conflict.db"
    store.initialize_store(path)
    return path


def edit(record, **changes):
    return {**record, "expected_edit_token": record["edit_token"], **changes}


def state(db):
    with sqlite3.connect(db) as conn:
        return (conn.execute("SELECT * FROM evidence_records").fetchall(),
                conn.execute("SELECT * FROM thesis_revisions").fetchall(),
                conn.execute("SELECT * FROM investment_theses").fetchall())


def test_stale_editor_and_delete_leave_all_business_state_unchanged(db, monkeypatch):
    monkeypatch.setattr(svc, "_utc_now_iso", lambda: "2026-10-09T00:00:00+00:00")
    ev = svc.create_evidence(db, _make_evidence_payload())
    thesis = svc.create_thesis(db, _make_thesis_payload())
    svc.link_evidence(db, thesis["thesis"]["id"], ev["id"], "support", 1)
    current = svc.update_evidence(db, ev["id"], edit(ev, claim="Tab A corrected claim"))
    assert current["updated_at"] == ev["updated_at"]
    assert current["edit_token"] != ev["edit_token"]
    before = state(db)
    for action in [lambda: svc.update_evidence(db, ev["id"], edit(ev, source_title="Tab B source")),
                   lambda: svc.soft_delete_evidence(db, ev["id"], ev["edit_token"]),
                   # A lost response is not permission to replay an old complete form.
                   lambda: svc.update_evidence(db, ev["id"], edit(ev, claim="Tab A corrected claim"))]:
        with pytest.raises(svc.EvidenceEditConflictError):
            action()
        assert state(db) == before
    latest = svc.get_evidence(db, ev["id"])
    latest = svc.update_evidence(db, ev["id"], edit(latest, source_title="Reviewed source"))
    deleted = svc.soft_delete_evidence(db, ev["id"], latest["edit_token"])
    assert deleted["deleted"] == 1
    assert deleted["edit_token"] != latest["edit_token"]
    with pytest.raises(svc.EvidenceNotFoundError):
        svc.update_evidence(db, ev["id"], edit(deleted))
    with pytest.raises(svc.EvidenceNotFoundError):
        svc.soft_delete_evidence(db, ev["id"], deleted["edit_token"])


@pytest.mark.parametrize("value", [None, "", True, 7, [], "a" * 64, "evidence-edit.v1:" + "A" * 64,
                                        "evidence-edit.v1:" + "0" * 64 + "\n"])
def test_missing_or_malformed_preconditions_fail_closed(db, value):
    ev = svc.create_evidence(db, _make_evidence_payload())
    before = state(db)
    with pytest.raises(svc.ValidationError):
        svc.update_evidence(db, ev["id"], edit(ev, expected_edit_token=value))
    with pytest.raises(svc.ValidationError):
        svc.soft_delete_evidence(db, ev["id"], value)
    assert state(db) == before


def test_tokens_bind_identity_and_canonical_persisted_content(db):
    ev = svc.create_evidence(db, _make_evidence_payload())
    other = svc.create_evidence(db, _make_evidence_payload())
    with pytest.raises(svc.EvidenceEditConflictError):
        svc.update_evidence(db, ev["id"], edit(other))
    assert ev["edit_token"] == svc.get_evidence(db, ev["id"])["edit_token"]
    assert ev["edit_token"] in {item["edit_token"] for item in svc.list_evidence(db)["items"]}
    assert store.evidence_edit_token(dict(reversed(list(ev.items())))) == ev["edit_token"]
    for field in store._EVIDENCE_EDIT_FIELDS:
        changed = {**ev, field: "different" if field != "deleted" else 1}
        assert store.evidence_edit_token(changed) != ev["edit_token"], field
    assert store.evidence_edit_token({**ev, "source_url": None}) != store.evidence_edit_token({**ev, "source_url": ""})
    assert store.evidence_edit_token({**ev, "presentation_only": "ignored"}) == ev["edit_token"]


@pytest.mark.parametrize("second_action", ["update", "delete"])
def test_two_independent_connections_compare_inside_write_transaction(db, monkeypatch, second_action):
    """Bypass only the Python mutex so SQLite itself serializes the writers."""
    ev = svc.create_evidence(db, _make_evidence_payload())
    barrier = threading.Barrier(2)
    connections = []
    trace = []

    def independent_transaction(path, callback):
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        connections.append(conn)
        conn.set_trace_callback(trace.append)
        barrier.wait(timeout=10)
        try:
            with store._Tx(conn):
                return callback(conn)
        finally:
            conn.close()

    monkeypatch.setattr(store, "write_transaction", independent_transaction)
    def save(claim):
        try:
            if claim == "editor B" and second_action == "delete":
                return svc.soft_delete_evidence(db, ev["id"], ev["edit_token"])
            return svc.update_evidence(db, ev["id"], edit(ev, claim=claim))
        except (svc.EvidenceEditConflictError, svc.EvidenceNotFoundError):
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["editor A", "editor B"]))
    assert len(connections) == 2 and connections[0] is not connections[1]
    assert sum(result == "conflict" for result in results) == 1
    winner = next(result for result in results if isinstance(result, dict))
    assert svc.get_evidence(db, ev["id"]) == winner
    assert sum(sql.startswith("BEGIN IMMEDIATE") for sql in trace) == 2
    assert sum(sql.lstrip().startswith("UPDATE evidence_records") for sql in trace) == 1
    assert "ROLLBACK" in trace
