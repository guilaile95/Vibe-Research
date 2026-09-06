"""P0-PH2 S2D-C canonical thesis delta contract tests."""

from __future__ import annotations

import sqlite3
import threading

import pytest

import evidence_thesis_router as router
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
    svc.confirm_formalization(db, tid, 2)
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
    svc.confirm_formalization(db, tid, 3)
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


def test_delta_routes_are_append_only():
    delta_routes = [r for r in router.router.routes if r.path.endswith("/deltas")]
    methods = {method for route in delta_routes for method in (route.methods or set())}
    assert methods == {"GET", "POST"}


def _post_freeze_evidence(db, claim='冻结后才有的一手信息'):
    return svc.create_evidence(db, {
        'subject_type': 'stock', 'subject_id': '600519', 'evidence_type': 'news',
        'claim': claim, 'source_title': '新纪要', 'source_url': None,
        'source_date': '2026-09-01', 'accessed_at': '2026-09-01T00:00:00+00:00',
        'classification': 'fact', 'confidence': 'medium',
    })


def test_post_freeze_new_evidence_enters_delta_chain(db):
    tid = _frozen(db)
    ev = _post_freeze_evidence(db)
    # 冻结后原始关联仍锁定：这是被保护的行为，不是要删除的护栏。
    with pytest.raises(svc.ContentLockedError):
        svc.link_evidence(db, tid, ev['id'], 'oppose', 3)
    delta = svc.create_thesis_delta(db, tid, 'WEAKENED', '新证据削弱核心假设', new_evidence=[
        {'evidence_id': ev['id'], 'stance': 'oppose', 'expected_updated_at': ev['updated_at']},
    ])
    assert delta['delta_sequence'] == 1
    assert len(delta['evidence_links']) == 1
    snapshot = delta['evidence_links'][0]
    assert snapshot['evidence_id'] == ev['id']
    assert snapshot['stance'] == 'oppose'  # 本次变更的显式立场，非旧 link 继承
    assert snapshot['claim'] == '冻结后才有的一手信息'
    assert snapshot['source_title'] == '新纪要'
    assert snapshot['captured_at'] == delta['confirmed_at']
    # canonical 读回一致
    readback = svc.list_thesis_deltas(db, tid)['items'][0]
    assert readback['evidence_links'][0]['stance'] == 'oppose'
    assert readback['evidence_links'][0]['claim'] == '冻结后才有的一手信息'
    # 冻结原文的关联表未被反向写入；快照只存在于 delta 链
    conn = sqlite3.connect(db)
    assert conn.execute(
        'SELECT COUNT(*) FROM thesis_evidence_links WHERE thesis_id=?', (tid,)
    ).fetchone()[0] == 0


def test_post_freeze_new_evidence_rejections_leave_no_partial_delta(db):
    tid = _frozen(db)
    other = svc.create_evidence(db, {
        'subject_type': 'stock', 'subject_id': '000001', 'evidence_type': 'news',
        'claim': '别的标的', 'source_title': 's', 'source_url': None,
        'source_date': '2026-09-01', 'accessed_at': '2026-09-01T00:00:00+00:00',
        'classification': 'fact', 'confidence': 'high',
    })
    with pytest.raises(svc.SubjectMismatchError):
        svc.create_thesis_delta(db, tid, 'WEAKENED', 'x', new_evidence=[
            {'evidence_id': other['id'], 'stance': 'oppose'},
        ])
    ev = _post_freeze_evidence(db)
    with pytest.raises(svc.ThesisDeltaConflictError, match='重新核对'):
        svc.create_thesis_delta(db, tid, 'WEAKENED', 'x', new_evidence=[
            {'evidence_id': ev['id'], 'stance': 'oppose', 'expected_updated_at': '2000-01-01T00:00:00+00:00'},
        ])
    with pytest.raises(svc.ValidationError):
        svc.create_thesis_delta(db, tid, 'WEAKENED', 'x', new_evidence=[
            {'evidence_id': ev['id'], 'stance': 'guess'},
        ])
    with pytest.raises(svc.ValidationError):
        svc.create_thesis_delta(db, tid, 'WEAKENED', 'x', evidence_ids=[ev['id']], new_evidence=[
            {'evidence_id': ev['id'], 'stance': 'oppose'},
        ])
    # 失败不得留下半个 delta 或部分关联
    conn = sqlite3.connect(db)
    assert conn.execute('SELECT COUNT(*) FROM thesis_deltas').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM thesis_delta_evidence_links').fetchone()[0] == 0
    # 已删除证据不能作为新的正常确认输入
    svc.soft_delete_evidence(db, ev['id'])
    with pytest.raises(svc.EvidenceNotFoundError):
        svc.create_thesis_delta(db, tid, 'WEAKENED', 'x', new_evidence=[
            {'evidence_id': ev['id'], 'stance': 'oppose'},
        ])


def test_evidence_edit_after_confirm_keeps_immutable_snapshot(db):
    tid = _frozen(db)
    ev = _post_freeze_evidence(db)
    svc.create_thesis_delta(db, tid, 'STABLE', '确认一条新证据', new_evidence=[
        {'evidence_id': ev['id'], 'stance': 'neutral'},
    ])
    before = svc.list_thesis_deltas(db, tid)['items'][0]['evidence_links'][0]
    svc.update_evidence(db, ev['id'], {
        'evidence_type': 'news', 'claim': '事后被编辑过的陈述',
        'source_title': '新纪要', 'source_url': None,
        'source_date': '2026-09-01', 'accessed_at': '2026-09-01T00:00:00+00:00',
        'classification': 'fact', 'confidence': 'high',
    })
    after = svc.list_thesis_deltas(db, tid)['items'][0]['evidence_links'][0]
    assert after == before  # 历史快照不被后续编辑倒改
