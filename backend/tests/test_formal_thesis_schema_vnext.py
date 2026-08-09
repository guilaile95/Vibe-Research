"""P0-PH2 S2D-A：Formal Thesis vNext schema 模型契约测试（non-migration）。

覆盖：五态合法 round-trip、五态 DB CHECK、persisted-row validator（corruption
matrix 主行/跨 revision 部分）、SQLite JSON functions 可用性。
全部使用全新 v2_vnext 测试库；绝不触碰真实用户 DB。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import evidence_thesis_service as svc
import evidence_thesis_store as store
from evidence_thesis_store import EvidenceLedgerCorruptedError


def _db(tmp_path, monkeypatch):
    path = tmp_path / "formal_vnext.sqlite3"
    store.initialize_store(path)
    return path


def _ro_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _base_row(thesis_id: str = "t" * 32) -> dict:
    return {
        "id": thesis_id,
        "subject_type": "stock",
        "subject_id": "600519",
        "market": "CN",
        "title": "茅台研究",
        "summary": "s",
        "status": "active",
        "core_claims": json.dumps(["c1", "c2", "c3"], ensure_ascii=False),
        "catalysts": json.dumps(["k1"], ensure_ascii=False),
        "risks": json.dumps(["r1"], ensure_ascii=False),
        "invalidation_conditions": json.dumps(["i1"], ensure_ascii=False),
        "created_at": "2026-08-01T00:00:00.000000+00:00",
        "updated_at": "2026-08-01T00:00:00.000000+00:00",
        "current_revision": 1,
        "formal_state": None,
        "formalization_started_at": None,
        "strategy": None,
        "expected_horizon": None,
        "free_notes": None,
        "confirmed_at": None,
        "frozen_at": None,
        "frozen_revision": None,
        "archived_at": None,
    }


def _insert(db_path, row: dict) -> None:
    conn = _ro_conn(db_path)
    try:
        cols = ", ".join(row.keys())
        marks = ", ".join("?" for _ in row)
        conn.execute(
            f"INSERT INTO investment_theses ({cols}) VALUES ({marks})", list(row.values())
        )
        conn.commit()
    finally:
        conn.close()


def _insert_revision(db_path, thesis_id, revision_number, snapshot: dict, kind):
    conn = _ro_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO thesis_revisions "
            "(id, thesis_id, revision_number, snapshot, change_summary, created_at, revision_kind) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"rev_{thesis_id[:8]}_{revision_number}",
                thesis_id,
                revision_number,
                json.dumps(snapshot, ensure_ascii=False),
                "s",
                "2026-08-01T00:00:00.000000+00:00",
                kind,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _fetch_thesis(db_path, thesis_id):
    conn = _ro_conn(db_path)
    try:
        return conn.execute(
            "SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)
        ).fetchone()
    finally:
        conn.close()


def _content() -> dict:
    return {
        "title": "茅台研究",
        "summary": "s",
        "core_claims": ["c1", "c2", "c3"],
        "catalysts": ["k1"],
        "risks": ["r1"],
        "invalidation_conditions": ["i1"],
        "free_notes": "note",
        "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
        "status": "active",
        "current_revision": 1,
        "created_at": "2026-08-01T00:00:00.000000+00:00",
        "updated_at": "2026-08-01T00:00:00.000000+00:00",
    }


def _draft_row(thesis_id="t" * 32, **overrides):
    row = _base_row(thesis_id)
    row.update({
        "formal_state": "draft",
        "formalization_started_at": "2026-08-02T00:00:00.000000+00:00",
        "strategy": "SWING",
        "expected_horizon": json.dumps(
            {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"}
        ),
        "free_notes": "note",
    })
    row.update(overrides)
    return row


def _confirmed_row(thesis_id="t" * 32, **overrides):
    row = _draft_row(thesis_id)
    row.update({
        "formal_state": "confirmed",
        "confirmed_at": "2026-08-03T00:00:00.000000+00:00",
    })
    row.update(overrides)
    return row


def _frozen_row(thesis_id="t" * 32, **overrides):
    row = _confirmed_row(thesis_id)
    row.update({
        "formal_state": "frozen",
        "frozen_at": "2026-08-04T00:00:00.000000+00:00",
        "frozen_revision": 2,
        "current_revision": 2,
    })
    row.update(overrides)
    return row


def _frozen_archived_row(thesis_id="t" * 32, **overrides):
    row = _frozen_row(thesis_id)
    row.update({
        "status": "archived",
        "updated_at": "2026-08-05T00:00:00.000000+00:00",
        "archived_at": "2026-08-05T00:00:00.000000+00:00",
        "current_revision": 3,
    })
    row.update(overrides)
    return row


def _snapshot_content(**overrides) -> dict:
    snap = _content()
    snap.update(overrides)
    return snap


def _chain_ok(db_path, thesis_id, kind="FORMAL_FREEZE"):
    """写入 frozen 行 + 对应 FORMAL_FREEZE/ARCHIVE revision，通过 chain validator。"""
    frozen = _frozen_row(thesis_id)
    _insert(db_path, frozen)
    _insert_revision(db_path, thesis_id, 1, _snapshot_content(), "CONTENT")
    _insert_revision(
        db_path, thesis_id, 2, _snapshot_content(current_revision=2), kind
    )
    return frozen


# ---------------------------------------------------------------------------
# SQLite JSON functions compatibility（Linux + Windows CI 均需通过）
# ---------------------------------------------------------------------------


def test_sqlite_json_functions_available():
    conn = sqlite3.connect(":memory:")
    row = conn.execute(
        "SELECT json_valid('{\"unit\":\"TRADING_DAY\"}'), "
        "json_extract('{\"unit\":\"TRADING_DAY\"}', '$.unit'), "
        "json_type('{\"min\":5}', '$.min')"
    ).fetchone()
    conn.close()
    assert row[0] == 1
    assert row[1] == "TRADING_DAY"
    assert row[2] == "integer"


# ---------------------------------------------------------------------------
# 五态合法 round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row_builder, label",
    [
        (_base_row, "LEGACY"),
        (_draft_row, "DRAFT"),
        (_confirmed_row, "CONFIRMED"),
        (_frozen_row, "FROZEN_ACTIVE"),
        (_frozen_archived_row, "FROZEN_ARCHIVED"),
    ],
)
def test_five_state_roundtrip_valid(tmp_path, monkeypatch, row_builder, label):
    db_path = _db(tmp_path, monkeypatch)
    row = row_builder(f"{label.lower()[:5]}{'0' * 27}")
    _insert(db_path, row)
    if row["formal_state"] != "frozen":
        conn = _ro_conn(db_path)
        fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (row["id"],)).fetchone()
        store.validate_persisted_thesis_main(fetched)
        conn.close()


def test_frozen_chain_roundtrip_with_revisions(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "f" * 32
    _chain_ok(db_path, thesis_id)
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    store.validate_persisted_thesis_main(fetched)
    store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()


def test_all_thesis_read_paths_fail_closed_on_formal_chain_corruption(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "r" * 32
    _chain_ok(db_path, thesis_id)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE thesis_revisions SET revision_kind='CONTENT' "
        "WHERE thesis_id=? AND revision_number=2",
        (thesis_id,),
    )
    conn.commit()
    conn.close()

    reads = (
        lambda: svc.list_thesis(db_path),
        lambda: svc.list_revisions(db_path, thesis_id),
        lambda: svc.get_revision(db_path, thesis_id, 2),
        lambda: svc.diff_revisions(db_path, thesis_id, 1, 2),
    )
    for read in reads:
        with pytest.raises(EvidenceLedgerCorruptedError):
            read()


def test_frozen_archived_chain_roundtrip(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "a" * 32
    row = _frozen_archived_row(thesis_id)
    _insert(db_path, row)
    _insert_revision(db_path, thesis_id, 1, _snapshot_content(), "CONTENT")
    _insert_revision(
        db_path, thesis_id, 2,
        _snapshot_content(current_revision=2), "FORMAL_FREEZE",
    )
    archive_snap = _snapshot_content(
        current_revision=3,
        status="archived",
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )
    _insert_revision(db_path, thesis_id, 3, archive_snap, "FORMAL_ARCHIVE")
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    store.validate_persisted_thesis_main(fetched)
    store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()


# ---------------------------------------------------------------------------
# 五态 DB CHECK（SQLite 层直接拒绝非法 tuple）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutator, label",
    [
        (lambda r: r.update({"formal_state": "draft"}), "legacy_with_draft_marker"),
        (lambda r: r.update({"formal_state": "confirmed", "confirmed_at": "x"}),
         "legacy_with_confirmed_marker"),
        (lambda r: r.update({"formal_state": "bogus"}), "invalid_formal_state"),
        (lambda r: r.update({"strategy": "DAY_TRADE"}), "invalid_strategy"),
        (lambda r: r.update({"frozen_revision": 0}), "frozen_revision_zero"),
    ],
)
def test_db_check_rejects_invalid_state_tuples(tmp_path, monkeypatch, mutator, label):
    db_path = _db(tmp_path, monkeypatch)
    row = _base_row(label[:8] + "0" * 24)
    mutator(row)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db_path, row)  # 直接 SQL 绕过 service；CHECK 必须拒绝
    return
    conn = _ro_conn(db_path)
    try:
        fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (row["id"],)).fetchone()
        assert fetched is not None
        # 若 CHECK 未生效则 validator 必须拒绝（双保险 fail-closed）
        try:
            store.validate_persisted_thesis_main(fetched)
            raise AssertionError(f"invalid tuple accepted: {label}")
        except EvidenceLedgerCorruptedError:
            pass
    finally:
        conn.close()


def test_db_check_rejects_confirmed_without_strategy(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    row = _confirmed_row("c" * 32)
    row["strategy"] = None
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db_path, row)


def test_db_check_rejects_bad_horizon_structure(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    row = _confirmed_row("h" * 32)
    row["expected_horizon"] = json.dumps(
        {"unit": "CALENDAR_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"}
    )
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db_path, row)


def test_db_check_rejects_horizon_max_less_than_min(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    row = _confirmed_row("m" * 32)
    row["expected_horizon"] = json.dumps(
        {"unit": "TRADING_DAY", "min": 20, "max": 5, "anchor": "FREEZE_AT"}
    )
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db_path, row)


# ---------------------------------------------------------------------------
# persisted-row validator corruption matrix（主行 / 跨 revision）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row_builder, mutator, label",
    [
        (_base_row, lambda r: r.update({"formalization_started_at": "2026-08-02T00:00:00.000000+00:00"}),
         "corrupt_01_legacy_with_started"),
        (_draft_row, lambda r: r.update({"formalization_started_at": None}),
         "corrupt_02_draft_no_started"),
        (_draft_row, lambda r: r.update({"status": "archived"}),
         "corrupt_03_draft_archived"),
        (_draft_row, lambda r: r.update({"archived_at": "2026-08-02T00:00:00.000000+00:00"}),
         "corrupt_04_draft_archived_at"),
        (_confirmed_row, lambda r: r.update({"confirmed_at": None}),
         "corrupt_05_confirmed_no_confirmed_at"),
        (_confirmed_row, lambda r: r.update({"strategy": None}),
         "corrupt_06_confirmed_no_strategy"),
        (_confirmed_row, lambda r: r.update({"expected_horizon": None}),
         "corrupt_07_confirmed_no_horizon"),
        (_confirmed_row, lambda r: r.update({"archived_at": "2026-08-03T00:00:00.000000+00:00"}),
         "corrupt_08_confirmed_archived_at"),
        (_frozen_row, lambda r: r.update({"frozen_revision": None}),
         "corrupt_09_frozen_no_frozen_revision"),
        (_frozen_row, lambda r: r.update({"strategy": None}),
         "corrupt_10_frozen_no_strategy"),
        (_frozen_row, lambda r: r.update({"expected_horizon": None}),
         "corrupt_11_frozen_no_horizon"),
        (_frozen_row, lambda r: r.update({"current_revision": 1}),
         "corrupt_12_frozen_revision_mismatch"),
        (_frozen_archived_row, lambda r: r.update({"archived_at": None}),
         "corrupt_13_frozen_archived_no_archived_at"),
        (_frozen_archived_row, lambda r: r.update({"current_revision": 2}),
         "corrupt_14_frozen_archived_revision_mismatch"),
    ],
)
def test_corruption_matrix_main_row_fails_closed(
    tmp_path, monkeypatch, row_builder, mutator, label
):
    db_path = _db(tmp_path, monkeypatch)
    row = row_builder(label[:5] + "0" * 27)
    mutator(row)
    try:
        _insert(db_path, row)
    except sqlite3.IntegrityError:
        return  # DB CHECK 已拒绝，同样 fail-closed
    conn = _ro_conn(db_path)
    try:
        fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (row["id"],)).fetchone()
        with pytest.raises(EvidenceLedgerCorruptedError):
            store.validate_persisted_thesis_main(fetched)
    finally:
        conn.close()


def test_corrupt_15_freeze_revision_kind_wrong(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "15" + "0" * 30
    _insert(db_path, _frozen_row(thesis_id))
    _insert_revision(db_path, thesis_id, 1, _snapshot_content(), "CONTENT")
    _insert_revision(db_path, thesis_id, 2, _snapshot_content(current_revision=2), "CONTENT")
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()


def test_corrupt_16_frozen_archived_missing_archive_revision(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "16" + "0" * 30
    _insert(db_path, _frozen_archived_row(thesis_id))
    _insert_revision(db_path, thesis_id, 1, _snapshot_content(), "CONTENT")
    _insert_revision(db_path, thesis_id, 2, _snapshot_content(current_revision=2), "FORMAL_FREEZE")
    # 缺 revision 3（FORMAL_ARCHIVE）
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()


def test_corrupt_17_archive_snapshot_content_drift(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "17" + "0" * 30
    _insert(db_path, _frozen_archived_row(thesis_id))
    _insert_revision(db_path, thesis_id, 1, _snapshot_content(), "CONTENT")
    _insert_revision(db_path, thesis_id, 2, _snapshot_content(current_revision=2), "FORMAL_FREEZE")
    drifted = _snapshot_content(current_revision=3, status="archived", title="被篡改的标题")
    _insert_revision(db_path, thesis_id, 3, drifted, "FORMAL_ARCHIVE")
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()


def test_corrupt_18_confirmed_snapshot_missing(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "18" + "0" * 30
    _insert(db_path, _frozen_row(thesis_id))
    # 只写 revision 1，缺 revision 2（FORMAL_FREEZE）→ confirmed snapshot missing
    _insert_revision(db_path, thesis_id, 1, _snapshot_content(), "CONTENT")
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()


def test_corrupt_19_confirmed_main_drift(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "19" + "0" * 30
    row = _frozen_row(thesis_id)
    row["title"] = "live 行被改"
    _insert(db_path, row)
    _insert_revision(db_path, thesis_id, 1, _snapshot_content(), "CONTENT")
    _insert_revision(db_path, thesis_id, 2, _snapshot_content(current_revision=2), "FORMAL_FREEZE")
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()


def test_corrupt_20_invalid_horizon_json(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    row = _confirmed_row("20" + "0" * 30)
    row["expected_horizon"] = "not-json"
    try:
        _insert(db_path, row)
    except sqlite3.IntegrityError:
        return
    conn = _ro_conn(db_path)
    try:
        fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (row["id"],)).fetchone()
        with pytest.raises(EvidenceLedgerCorruptedError):
            store.validate_persisted_thesis_main(fetched)
    finally:
        conn.close()


def test_legacy_archived_at_parseable_iso_is_valid(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    row = _base_row("legacyarch" + "0" * 22)
    row.update({"status": "archived", "archived_at": "2026-08-05T00:00:00Z"})
    _insert(db_path, row)
    conn = _ro_conn(db_path)
    try:
        store.validate_persisted_thesis_main(
            conn.execute("SELECT * FROM investment_theses WHERE id = ?", (row["id"],)).fetchone()
        )
    finally:
        conn.close()


def test_confirmed_current_snapshot_required_and_content_match(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "confirmedmissing" + "0" * 17
    row = _confirmed_row(thesis_id)
    _insert(db_path, row)
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()

    db_path = _db(tmp_path / "drift", monkeypatch)
    thesis_id = "confirmeddrift" + "0" * 19
    _insert(db_path, _confirmed_row(thesis_id))
    drift = _snapshot_content(title="drift")
    _insert_revision(db_path, thesis_id, 1, drift, "CONTENT")
    conn = _ro_conn(db_path)
    fetched = conn.execute("SELECT * FROM investment_theses WHERE id = ?", (thesis_id,)).fetchone()
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_thesis_chain(conn, thesis_id, fetched)
    conn.close()


def test_formal_lifecycle_timestamp_must_be_canonical(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    row = _confirmed_row("timestampbad" + "0" * 21)
    row["confirmed_at"] = "2026-08-03T00:00:00Z"
    _insert(db_path, row)
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_thesis_main(_fetch_thesis(db_path, row["id"]))


def test_corrupt_24_delta_evidence_snapshot_fails_closed(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "24" + "0" * 30
    _chain_ok(db_path, thesis_id)
    _insert_delta(db_path, thesis_id, 1, "STABLE")
    conn = _ro_conn(db_path)
    conn.execute(
        "INSERT INTO thesis_delta_evidence_links "
        "(delta_id,evidence_id,evidence_type,claim,classification,confidence,source_title,source_url,source_date,accessed_at,stance,captured_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"delta_{thesis_id[:8]}_1", "ev24", "news", "claim", "bad", "high", "source", None, None,
         "2026-08-06T00:00:00.000000+00:00", "support", "2026-08-06T00:00:00.000000+00:00"),
    )
    conn.commit()
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_delta_chain(conn, thesis_id)
    conn.close()


# ---------------------------------------------------------------------------
# delta 链 validator（corrupt 21/22/23/24 在 S2D-C 测试补全；这里覆盖基础链）
# ---------------------------------------------------------------------------


def _insert_delta(db_path, thesis_id, seq, state, base_revision=2):
    conn = _ro_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO thesis_deltas "
            "(delta_id, thesis_id, delta_sequence, base_revision, delta_state, reason, confirmed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"delta_{thesis_id[:8]}_{seq}",
                thesis_id,
                seq,
                base_revision,
                state,
                "reason",
                "2026-08-06T00:00:00.000000+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_delta_chain_valid_sequences(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "d0" + "0" * 30
    _chain_ok(db_path, thesis_id)
    _insert_delta(db_path, thesis_id, 1, "STABLE")
    _insert_delta(db_path, thesis_id, 2, "WEAKENED")
    conn = _ro_conn(db_path)
    store.validate_persisted_delta_chain(conn, thesis_id)
    conn.close()


def test_corrupt_21_delta_base_revision_mismatch(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "21" + "0" * 30
    _chain_ok(db_path, thesis_id)
    _insert_delta(db_path, thesis_id, 1, "STABLE", base_revision=1)
    conn = _ro_conn(db_path)
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_delta_chain(conn, thesis_id)
    conn.close()


def test_corrupt_22_delta_sequence_gap(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "22" + "0" * 30
    _chain_ok(db_path, thesis_id)
    _insert_delta(db_path, thesis_id, 1, "STABLE")
    _insert_delta(db_path, thesis_id, 3, "WEAKENED")  # 跳过 2
    conn = _ro_conn(db_path)
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_delta_chain(conn, thesis_id)
    conn.close()


def test_corrupt_23_terminal_delta_then_more(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    thesis_id = "23" + "0" * 30
    _chain_ok(db_path, thesis_id)
    _insert_delta(db_path, thesis_id, 1, "DISPROVEN")
    _insert_delta(db_path, thesis_id, 2, "STABLE")  # terminal 之后
    conn = _ro_conn(db_path)
    with pytest.raises(EvidenceLedgerCorruptedError):
        store.validate_persisted_delta_chain(conn, thesis_id)
    conn.close()


def test_legacy_v1_db_rejected_without_migration(tmp_path, monkeypatch):
    """v1 旧库（无新列）打开即拒绝，绝不自动迁移。"""
    path = tmp_path / "legacy_v1.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (store.LEGACY_SCHEMA_VERSION,),
    )
    conn.execute("CREATE TABLE evidence_records (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    with pytest.raises(store.EvidenceLedgerSchemaVersionError):
        store.initialize_store(path)
