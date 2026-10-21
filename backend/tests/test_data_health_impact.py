"""Synthetic persisted links only; never contacts a provider or mutates during reads."""
from __future__ import annotations

import copy
import sqlite3

import pytest

import data_health_impact as impact
import evidence_thesis_service as service
import evidence_thesis_store as store
from test_evidence_thesis_service import _make_evidence_payload, _make_thesis_payload


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "evidence.db"
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(path))
    store.initialize_store(path)
    evidence = service.create_evidence(path, _make_evidence_payload())
    thesis = service.create_thesis(path, _make_thesis_payload())["thesis"]
    service.link_evidence(path, thesis["id"], evidence["id"], "support", 1, "synthetic link")
    return path, thesis["id"], evidence["id"]


def _bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_real_registered_link_normal_and_readonly(ledger):
    path, tid, eid = ledger
    before = _bytes(path.parent)
    result = impact.get_source_impact("evidence_ledger")
    assert result["mapping_state"] == "mapped"
    assert result["items"] == [{"thesis_id": tid, "title": "thesis", "subject_type": "stock",
        "subject_id": "600519", "frozen": False, "path": f"/thesis/{tid}",
        "evidence": [{"evidence_id": eid, "state": "available", "path": f"/evidence/{eid}"}]}]
    assert _bytes(path.parent) == before


def test_missing_and_recovered_live_record(ledger):
    path, _, eid = ledger
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE evidence_records SET deleted = 1 WHERE id = ?", (eid,))
    missing = impact.get_source_impact("evidence_ledger")["items"][0]["evidence"][0]
    assert missing["state"] == "missing" and missing["path"] is None
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE evidence_records SET deleted = 0 WHERE id = ?", (eid,))
    assert impact.get_source_impact("evidence_ledger")["items"][0]["evidence"][0]["state"] == "available"


def test_wrong_subject_never_attributed_or_linked(ledger):
    path, _, eid = ledger
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE evidence_records SET subject_id = '000001' WHERE id = ?", (eid,))
    result = impact.get_source_impact("evidence_ledger")
    assert result["items"][0]["subject_id"] == "600519"
    assert result["items"][0]["evidence"][0] == {"evidence_id": eid, "state": "subject_mismatch", "path": None}
    assert "000001" not in str(result)


def test_unmapped_provider_cannot_borrow_ledger_objects(ledger):
    for source in ("quotes", "financials", "announcements", "portfolio_advice_gate", "my_reports"):
        result = impact.get_source_impact(source)
        assert result["mapping_state"] == "unmapped"
        assert result["items"] == []


def test_uninitialized_and_corrupt_ledger_unknown(tmp_path, monkeypatch):
    path = tmp_path / "absent.db"
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(path))
    assert impact.get_source_impact("evidence_ledger")["mapping_state"] == "unknown"
    assert not path.exists()
    path.write_bytes(b"not sqlite")
    before = _bytes(tmp_path)
    assert impact.get_source_impact("evidence_ledger")["mapping_state"] == "unknown"
    assert _bytes(tmp_path) == before


def _row(**changes):
    return {"thesis_id": "t", "title": "Thesis", "subject_type": "stock", "subject_id": "600519",
        "formal_state": None, "evidence_id": "e", "live_evidence_id": "e", "deleted": 0,
        "evidence_subject_type": "stock", "evidence_subject_id": "600519", **changes}


def test_duplicate_conflicting_identity_fail_closed():
    for second in (_row(), _row(subject_id="000001")):
        result = impact.project_ledger_links([_row(), second])
        assert result["mapping_state"] == "unknown" and result["items"] == []


def test_frozen_notice_only_and_no_input_mutation():
    rows = [_row(formal_state="frozen", deleted=1)]
    before = copy.deepcopy(rows)
    result = impact.project_ledger_links(rows)
    assert result["items"][0]["frozen"] is True
    assert result["items"][0]["path"] == "/thesis/t"
    assert rows == before
    assert not any(key in str(result) for key in ("rerun", "ignore", "unfreeze"))


def test_bounded_links_disclose_truncation(ledger, monkeypatch):
    monkeypatch.setattr(impact, "MAX_LINK_ROWS", 0)
    result = impact.get_source_impact("evidence_ledger")
    assert result["truncated"] is True and result["items"] == []


def test_empty_registered_link_set_is_not_unmapped(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(path))
    store.initialize_store(path)
    result = impact.get_source_impact("evidence_ledger")
    assert result["mapping_state"] == "mapped" and result["items"] == []


def test_orphan_thesis_does_not_become_empty_or_invent_subject(ledger):
    path, tid, _ = ledger
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM investment_theses WHERE id = ?", (tid,))
    result = impact.get_source_impact("evidence_ledger")
    assert result["mapping_state"] == "unknown" and result["items"] == []
