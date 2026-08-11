"""P0-PH2 S2D-D：Current Thesis Projection 专项测试（真实 SQLite fixture，不联网）。

使用全新 tmp 数据库（campaign store + evidence ledger），绝不触碰真实用户 DB。
Frozen thesis 按 S2D-A 五态契约手工构造（FORMAL_FREEZE revision + deltas），
不依赖 S2D-B 的 freeze 写路径。

覆盖：frozen 无 delta / non-terminal latest wins / terminal last /
NOT_READY（draft/confirmed/legacy）/ strategy mismatch 409 /
404（无绑定/无 Campaign）/ corrupted chain 500 / fail-closed（缺 thesis/缺 db）/
archived frozen 仍可投影 / API contract。
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import campaign_router
import campaign_service
import campaign_store
import evidence_thesis_store as store
import formal_thesis_projection
from campaign_service import (
    CampaignNotFoundError,
    CampaignThesisStrategyConflictError,
    ThesisBindingNotFoundError,
    create_campaign,
)
from evidence_thesis_store import EvidenceLedgerCorruptedError
from formal_thesis_projection import CurrentThesisProjectionError


def _tid(seed: int = 0) -> str:
    return f"{seed:032x}"


@pytest.fixture
def campaign_db(tmp_path, monkeypatch):
    path = tmp_path / "campaigns.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(path))
    return path


@pytest.fixture
def evidence_db(tmp_path, monkeypatch):
    path = tmp_path / "evidence_thesis.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(path))
    store.initialize_store(path)
    return path


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _exec(db_path, sql, params=()):
    conn = _conn(db_path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


_TS = "2026-08-01T00:00:00.000000+00:00"
_HORIZON = {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"}
_HORIZONS = {
    "SHORT": {"unit": "TRADING_DAY", "min": 5, "max": 10, "anchor": "FREEZE_AT"},
    "SWING": _HORIZON,
    "MEDIUM": {"unit": "TRADING_DAY", "min": 40, "max": 60, "anchor": "FREEZE_AT"},
}


def _thesis_row(
    thesis_id: str,
    *,
    formal_state="frozen",
    strategy="SWING",
    horizon=None,
    revision=2,
    status="active",
    archived_at=None,
) -> dict:
    frozen = formal_state == "frozen"
    return {
        "id": thesis_id,
        "subject_type": "stock",
        "subject_id": "600519",
        "market": "CN",
        "title": "t",
        "summary": "s",
        "status": status,
        "core_claims": json.dumps(["c1"], ensure_ascii=False),
        "catalysts": json.dumps(["k1"], ensure_ascii=False),
        "risks": json.dumps(["r1"], ensure_ascii=False),
        "invalidation_conditions": json.dumps(["i1"], ensure_ascii=False),
        "created_at": _TS,
        "updated_at": _TS,
        "current_revision": revision if not archived_at else revision + 1,
        "formal_state": formal_state,
        "formalization_started_at": _TS if (frozen or formal_state in ("draft", "confirmed")) else None,
        "strategy": strategy if (frozen or formal_state == "confirmed") else None,
        "expected_horizon": (
            json.dumps(horizon or _HORIZONS[strategy], ensure_ascii=False)
            if (frozen or formal_state == "confirmed")
            else None
        ),
        "free_notes": None,
        "confirmed_at": _TS if (frozen or formal_state == "confirmed") else None,
        "frozen_at": _TS if frozen else None,
        "frozen_revision": revision if frozen else None,
        "archived_at": archived_at,
    }


def _snapshot(
    *, strategy="SWING", horizon=None, revision=2, status="active", archived_at=None
) -> dict:
    snap = {
        "title": "t",
        "summary": "s",
        "core_claims": ["c1"],
        "catalysts": ["k1"],
        "risks": ["r1"],
        "invalidation_conditions": ["i1"],
        "free_notes": None,
        "strategy": strategy,
        "expected_horizon": horizon or _HORIZONS[strategy],
        "status": status,
        "current_revision": revision,
        "created_at": _TS,
        "updated_at": _TS,
    }
    if archived_at is not None:
        snap["archived_at"] = archived_at
    return snap


def _insert_thesis(db_path, row: dict) -> None:
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    _exec(
        db_path,
        f"INSERT INTO investment_theses ({cols}) VALUES ({marks})",
        list(row.values()),
    )


def _insert_revision(
    db_path, thesis_id, revision_number, snapshot: dict, kind: str
) -> None:
    _exec(
        db_path,
        "INSERT INTO thesis_revisions "
        "(id, thesis_id, revision_number, snapshot, change_summary, created_at, revision_kind) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            f"rev_{thesis_id[:8]}_{revision_number}",
            thesis_id,
            revision_number,
            json.dumps(snapshot, ensure_ascii=False),
            "s",
            _TS,
            kind,
        ),
    )


def _insert_delta(
    db_path, thesis_id, seq, base_revision, delta_state, reason="reason"
) -> None:
    _exec(
        db_path,
        "INSERT INTO thesis_deltas "
        "(delta_id, thesis_id, delta_sequence, base_revision, delta_state, reason, confirmed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (f"delta_{thesis_id[:8]}_{seq}", thesis_id, seq, base_revision, delta_state, reason, _TS),
    )


def _insert_evidence_record(db_path, evidence_id: str) -> None:
    """Insert the mutable live record paired with a delta snapshot fixture."""
    _exec(
        db_path,
        "INSERT INTO evidence_records "
        "(id, subject_type, subject_id, evidence_type, claim, source_title, "
        "source_url, source_date, accessed_at, classification, confidence, "
        "created_at, updated_at, deleted, deleted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            evidence_id,
            "stock",
            "600519",
            "news",
            "mutable claim before",
            "mutable source before",
            "https://mutable.example/before",
            "2026-08-01",
            _TS,
            "fact",
            "high",
            _TS,
            _TS,
            0,
            None,
        ),
    )


def _insert_delta_evidence_snapshot(
    db_path,
    thesis_id: str,
    seq: int,
    *,
    evidence_id: str = "ev_snapshot",
    classification: str = "fact",
) -> None:
    _exec(
        db_path,
        "INSERT INTO thesis_delta_evidence_links "
        "(delta_id, evidence_id, evidence_type, claim, classification, confidence, "
        "source_title, source_url, source_date, accessed_at, stance, captured_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"delta_{thesis_id[:8]}_{seq}",
            evidence_id,
            "news",
            "immutable claim at delta time",
            classification,
            "high",
            "immutable source at delta time",
            "https://snapshot.example/source",
            "2026-08-01",
            _TS,
            "support",
            _TS,
        ),
    )


def _install_frozen(
    db_path,
    thesis_id,
    *,
    strategy="SWING",
    revision=2,
    archived=False,
    deltas=(),
) -> None:
    archived_at = _TS if archived else None
    status = "archived" if archived else "active"
    _insert_thesis(
        db_path,
        _thesis_row(
            thesis_id,
            formal_state="frozen",
            strategy=strategy,
            revision=revision,
            status=status,
            archived_at=archived_at,
        ),
    )
    # Revision history is append-only and must be complete 1..current_revision:
    # the freeze snapshot at revision 2 is preceded by the normal content
    # revision at revision 1.
    for revision_number in range(1, revision):
        _insert_revision(
            db_path,
            thesis_id,
            revision_number,
            _snapshot(
                strategy=strategy, revision=revision_number, status="active"
            ),
            "CONTENT",
        )
    _insert_revision(
        db_path,
        thesis_id,
        revision,
        _snapshot(strategy=strategy, revision=revision, status="active"),
        "FORMAL_FREEZE",
    )
    if archived:
        _insert_revision(
            db_path,
            thesis_id,
            revision + 1,
            _snapshot(
                strategy=strategy,
                revision=revision + 1,
                status="archived",
                archived_at=archived_at,
            ),
            "FORMAL_ARCHIVE",
        )
    for seq, delta_state in deltas:
        _insert_delta(db_path, thesis_id, seq, revision, delta_state)


def _install_non_frozen(db_path, thesis_id, kind: str) -> None:
    if kind == "draft":
        row = _thesis_row(thesis_id, formal_state="draft", revision=1)
    elif kind == "confirmed":
        row = _thesis_row(thesis_id, formal_state="confirmed", revision=1)
    else:  # legacy
        row = _thesis_row(thesis_id, formal_state=None, strategy=None, revision=1)
    _insert_thesis(db_path, row)
    _insert_revision(
        db_path,
        thesis_id,
        1,
        _snapshot(strategy="SWING", revision=1),
        "CONTENT",
    )


def _setup_campaign(db_path, strategy="SWING") -> dict:
    return create_campaign("600519", strategy)


def _bind(campaign_id, thesis_id, revision, strategy) -> dict:
    """store 层直插 binding（绕过 service gates，模拟 grandfather binding）。"""
    return campaign_store.bind_campaign_thesis(
        campaign_id=campaign_id,
        thesis_id=thesis_id,
        thesis_revision_at_bind=revision,
        campaign_strategy_at_bind=strategy,
        bound_at="2026-08-01T00:00:00.000000Z",
    )


# ---------------------------------------------------------------------------
# A. OPTION A: pure-core domain authority + adapter has no duplicate rules
# ---------------------------------------------------------------------------

def _normalized_inputs(*, formal_state="frozen", deltas=None, strategy="SWING"):
    """Build normalized pure-domain inputs for core / adapter parity tests."""
    campaign_id = "campaign_" + "c" * 24
    thesis_id = _tid(90)
    binding = {
        "campaign_id": campaign_id,
        "thesis_id": thesis_id,
        "thesis_revision_at_bind": 2,
        "campaign_strategy_at_bind": strategy,
        "bound_at": _TS,
    }
    thesis = {
        "id": thesis_id,
        "formal_state": formal_state,
        "frozen_revision": 2 if formal_state == "frozen" else None,
        "strategy": strategy if formal_state == "frozen" else None,
        "expected_horizon": _HORIZONS[strategy] if formal_state == "frozen" else None,
    }
    frozen_original = {
        "revision_number": 2,
        "snapshot": _snapshot(strategy=strategy, revision=2),
    }
    delta_rows = []
    for sequence, state in deltas or ():
        delta_rows.append(
            {
                "delta_id": f"delta_{sequence:032x}",
                "thesis_id": thesis_id,
                "delta_sequence": sequence,
                "base_revision": 2,
                "delta_state": state,
                "reason": f"r{sequence}",
                "confirmed_at": _TS,
                "evidence_links": [],
            }
        )
    return campaign_id, binding, thesis, frozen_original, delta_rows


def test_adapter_has_no_independent_effective_state_authority():
    """OPTION A: adapter must not reimplement effective_state / terminal rules."""
    assert not hasattr(formal_thesis_projection, "_effective_state")


def test_core_and_adapter_semantic_parity_effective_state():
    import formal_thesis_projection_core as core

    cases = [
        ((), "STABLE"),
        (((1, "STRENGTHENED"),), "STRENGTHENED"),
        (((1, "STRENGTHENED"), (2, "WEAKENED")), "WEAKENED"),
        (((1, "STRENGTHENED"), (2, "DISPROVEN")), "DISPROVEN"),
    ]
    for deltas, expected in cases:
        campaign_id, binding, thesis, frozen_original, delta_rows = _normalized_inputs(
            deltas=deltas
        )
        core_result = core.project_current_thesis(
            campaign_id=campaign_id,
            binding=binding,
            thesis=thesis,
            frozen_original=frozen_original,
            deltas=[
                {
                    "delta_id": d["delta_id"],
                    "thesis_id": d["thesis_id"],
                    "delta_sequence": d["delta_sequence"],
                    "base_revision": d["base_revision"],
                    "delta_state": d["delta_state"],
                    "reason": d["reason"],
                    "confirmed_at": d["confirmed_at"],
                }
                for d in delta_rows
            ],
        )
        adapted = formal_thesis_projection.project_current_thesis_from_normalized(
            campaign_id=campaign_id,
            binding=binding,
            thesis=thesis,
            frozen_original=frozen_original,
            deltas=delta_rows,
        )
        assert core_result["formal_status"] == "READY"
        assert core_result["effective_state"] == expected
        assert adapted["formal_status"] == "READY"
        assert adapted["ready"] is True
        assert adapted["effective_state"] == core_result["effective_state"]
        assert adapted["frozen_revision"] == core_result["original"]["revision"]
        assert adapted["original_snapshot"] == core_result["original"]["snapshot"]


def test_core_terminal_not_last_fail_closed_maps_through_adapter():
    import formal_thesis_projection_core as core
    from formal_thesis_projection_core import ProjectionIntegrityError

    campaign_id, binding, thesis, frozen_original, delta_rows = _normalized_inputs(
        deltas=((1, "DISPROVEN"), (2, "STRENGTHENED"))
    )
    with pytest.raises(ProjectionIntegrityError):
        core.project_current_thesis(
            campaign_id=campaign_id,
            binding=binding,
            thesis=thesis,
            frozen_original=frozen_original,
            deltas=delta_rows,
        )
    with pytest.raises(CurrentThesisProjectionError):
        formal_thesis_projection.project_current_thesis_from_normalized(
            campaign_id=campaign_id,
            binding=binding,
            thesis=thesis,
            frozen_original=frozen_original,
            deltas=delta_rows,
        )


def test_core_and_adapter_not_frozen_parity():
    import formal_thesis_projection_core as core

    campaign_id, binding, thesis, frozen_original, delta_rows = _normalized_inputs(
        formal_state="draft",
        deltas=(),
    )
    thesis["strategy"] = None
    thesis["frozen_revision"] = None
    core_result = core.project_current_thesis(
        campaign_id=campaign_id,
        binding=binding,
        thesis=thesis,
        frozen_original={},
        deltas=[],
    )
    adapted = formal_thesis_projection.project_current_thesis_from_normalized(
        campaign_id=campaign_id,
        binding=binding,
        thesis=thesis,
        frozen_original={},
        deltas=[],
    )
    assert core_result["formal_status"] == "NOT_READY"
    assert core_result["reason"] == "NOT_FROZEN"
    assert adapted["formal_status"] == "NOT_READY"
    assert adapted["ready"] is False
    assert adapted["reason"] == "NOT_FROZEN"


# ---------------------------------------------------------------------------
# B. 投影成功路径
# ---------------------------------------------------------------------------

def test_projection_ready_frozen_no_deltas(campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(1)
    _install_frozen(evidence_db, tid, revision=2)
    binding = _bind(rec["campaign_id"], tid, 2, "SWING")

    p = formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    assert p["ready"] is True
    assert p["formal_status"] == "READY"
    assert p["campaign_id"] == rec["campaign_id"]
    assert p["thesis_id"] == tid
    assert p["frozen_revision"] == 2
    assert p["effective_state"] == "STABLE"
    assert p["deltas"] == []
    assert p["original_snapshot"] == _snapshot(strategy="SWING", revision=2)
    assert p["binding"] == {
        "thesis_revision_at_bind": 2,
        "campaign_strategy_at_bind": "SWING",
        "bound_at": binding["bound_at"],
    }


def test_projection_ready_validates_persisted_layers_in_order(
    campaign_db, evidence_db, monkeypatch
):
    rec = _setup_campaign(campaign_db)
    tid = _tid(19)
    _install_frozen(evidence_db, tid, revision=2)
    _bind(rec["campaign_id"], tid, 2, "SWING")

    calls = []
    for name in (
        "validate_persisted_thesis_main",
        "validate_persisted_revision_history",
        "validate_persisted_thesis_chain",
        "validate_persisted_delta_chain",
    ):
        original = getattr(store, name)

        def wrapped(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(store, name, wrapped)

    projection = formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    assert projection["ready"] is True
    assert calls == [
        "validate_persisted_thesis_main",
        "validate_persisted_revision_history",
        "validate_persisted_thesis_chain",
        "validate_persisted_delta_chain",
    ]


def test_projection_non_terminal_deltas_latest_wins(campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(2)
    _install_frozen(
        evidence_db, tid, revision=2, deltas=((1, "STRENGTHENED"), (2, "WEAKENED"))
    )
    _bind(rec["campaign_id"], tid, 2, "SWING")

    p = formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    assert p["ready"] is True
    assert p["effective_state"] == "WEAKENED"
    assert [d["delta_state"] for d in p["deltas"]] == ["STRENGTHENED", "WEAKENED"]
    assert [d["delta_sequence"] for d in p["deltas"]] == [1, 2]
    assert p["deltas"][0]["base_revision"] == 2


def test_projection_delta_evidence_uses_immutable_snapshot(
    campaign_db, evidence_db
):
    """Live evidence edits/deletes must not alter a persisted delta snapshot."""
    rec = _setup_campaign(campaign_db)
    tid = _tid(17)
    _install_frozen(evidence_db, tid, revision=2, deltas=((1, "STRENGTHENED"),))
    _insert_evidence_record(evidence_db, "ev_snapshot")
    _insert_delta_evidence_snapshot(evidence_db, tid, 1)
    _bind(rec["campaign_id"], tid, 2, "SWING")

    before = formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    snapshot = before["deltas"][0]["evidence_links"]
    assert snapshot == [
        {
            "delta_id": f"delta_{tid[:8]}_1",
            "evidence_id": "ev_snapshot",
            "evidence_type": "news",
            "claim": "immutable claim at delta time",
            "classification": "fact",
            "confidence": "high",
            "source_title": "immutable source at delta time",
            "source_url": "https://snapshot.example/source",
            "source_date": "2026-08-01",
            "accessed_at": _TS,
            "stance": "support",
            "captured_at": _TS,
        }
    ]

    _exec(
        evidence_db,
        "UPDATE evidence_records SET claim = ?, source_title = ?, "
        "classification = ?, confidence = ?, updated_at = ? WHERE id = ?",
        ("mutable claim after", "mutable source after", "inference", "low", _TS, "ev_snapshot"),
    )
    _exec(
        evidence_db,
        "UPDATE evidence_records SET deleted = 1, deleted_at = ?, updated_at = ? WHERE id = ?",
        (_TS, _TS, "ev_snapshot"),
    )

    after = formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    assert after["deltas"][0]["evidence_links"] == snapshot


def test_projection_corrupt_delta_evidence_snapshot_fails_closed(
    campaign_db, evidence_db
):
    rec = _setup_campaign(campaign_db)
    tid = _tid(18)
    _install_frozen(evidence_db, tid, revision=2, deltas=((1, "STRENGTHENED"),))
    _insert_delta_evidence_snapshot(
        evidence_db, tid, 1, classification="not-a-valid-classification"
    )
    _bind(rec["campaign_id"], tid, 2, "SWING")

    with pytest.raises(EvidenceLedgerCorruptedError):
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])


def test_projection_terminal_delta_last_wins(campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(3)
    _install_frozen(
        evidence_db, tid, revision=2, deltas=((1, "STRENGTHENED"), (2, "DISPROVEN"))
    )
    _bind(rec["campaign_id"], tid, 2, "SWING")

    p = formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    assert p["ready"] is True
    assert p["effective_state"] == "DISPROVEN"


def test_projection_frozen_archived_still_projects(campaign_db, evidence_db):
    """grandfather binding + 冻结后归档：Formal Original 仍来自 frozen_revision。"""
    rec = _setup_campaign(campaign_db)
    tid = _tid(4)
    _install_frozen(evidence_db, tid, revision=2, archived=True)
    _bind(rec["campaign_id"], tid, 2, "SWING")

    p = formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    assert p["ready"] is True
    assert p["frozen_revision"] == 2
    assert p["original_snapshot"]["status"] == "active"
    assert p["original_snapshot"]["current_revision"] == 2


@pytest.mark.parametrize("corruption", ["missing_rev1", "future_orphan", "non_object", "archive_kind"])
def test_projection_historical_revision_corruption_fails_closed(
    campaign_db, evidence_db, corruption
):
    rec = _setup_campaign(campaign_db)
    tid = _tid({"missing_rev1": 20, "future_orphan": 21, "non_object": 22, "archive_kind": 23}[corruption])
    _install_frozen(evidence_db, tid, revision=2)

    if corruption == "missing_rev1":
        _exec(
            evidence_db,
            "DELETE FROM thesis_revisions WHERE thesis_id = ? AND revision_number = 1",
            (tid,),
        )
    elif corruption == "future_orphan":
        _insert_revision(
            evidence_db,
            tid,
            3,
            _snapshot(strategy="SWING", revision=3),
            "CONTENT",
        )
    elif corruption == "non_object":
        _exec(
            evidence_db,
            "UPDATE thesis_revisions SET snapshot = ? WHERE thesis_id = ? AND revision_number = 1",
            (json.dumps(["not", "an", "object"]), tid),
        )
    else:
        _exec(
            evidence_db,
            "UPDATE thesis_revisions SET revision_kind = ? WHERE thesis_id = ? AND revision_number = 1",
            ("FORMAL_ARCHIVE", tid),
        )

    _bind(rec["campaign_id"], tid, 2, "SWING")
    with pytest.raises(EvidenceLedgerCorruptedError):
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])


# ---------------------------------------------------------------------------
# C. NOT_READY（未冻结，绝不伪造 Formal Original）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["draft", "confirmed", "legacy"])
def test_projection_not_ready_not_frozen(campaign_db, evidence_db, kind):
    rec = _setup_campaign(campaign_db)
    tid = _tid(5)
    _install_non_frozen(evidence_db, tid, kind)
    _bind(rec["campaign_id"], tid, 1, "SWING")

    p = formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    assert p["ready"] is False
    assert p["formal_status"] == "NOT_READY"
    assert p["reason"] == "NOT_FROZEN"
    assert p["campaign_id"] == rec["campaign_id"]
    assert p["thesis_id"] == tid
    assert p["binding"]["campaign_strategy_at_bind"] == "SWING"
    assert p["frozen_revision"] is None
    # 不得用 thesis_revision_at_bind 冒充 Formal Original
    assert "original_snapshot" not in p
    assert "deltas" not in p
    assert "effective_state" not in p


# ---------------------------------------------------------------------------
# D. Strategy consistency（409 semantic conflict）
# ---------------------------------------------------------------------------

def test_projection_strategy_mismatch_semantic_conflict(campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db, strategy="SWING")
    tid = _tid(6)
    _install_frozen(evidence_db, tid, strategy="MEDIUM", revision=2)
    _bind(rec["campaign_id"], tid, 2, "SWING")  # grandfather binding（pre-gate）

    with pytest.raises(CampaignThesisStrategyConflictError) as exc_info:
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])
    assert exc_info.value.thesis_strategy == "MEDIUM"
    assert exc_info.value.campaign_strategy == "SWING"


# ---------------------------------------------------------------------------
# E. 404 / fail-closed
# ---------------------------------------------------------------------------

def test_projection_no_binding_not_found(campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    with pytest.raises(ThesisBindingNotFoundError):
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])


def test_projection_unknown_campaign_not_found(campaign_db, evidence_db):
    with pytest.raises(CampaignNotFoundError):
        formal_thesis_projection.project_current_thesis("campaign_" + "0" * 32)


def test_projection_bound_thesis_missing_fails_closed(campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(7)
    _install_frozen(evidence_db, tid, revision=2)
    _bind(rec["campaign_id"], tid, 2, "SWING")
    _exec(evidence_db, "DELETE FROM investment_theses WHERE id = ?", (tid,))

    with pytest.raises(CurrentThesisProjectionError):
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])


def test_projection_evidence_db_missing_fails_closed(campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(8)
    _install_frozen(evidence_db, tid, revision=2)
    _bind(rec["campaign_id"], tid, 2, "SWING")
    evidence_db.unlink()

    with pytest.raises(CurrentThesisProjectionError):
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])


def test_projection_terminal_then_delta_corrupted(campaign_db, evidence_db):
    """terminal 之后仍有 delta：读路径 validator fail-closed → corrupted。"""
    rec = _setup_campaign(campaign_db)
    tid = _tid(9)
    _install_frozen(evidence_db, tid, revision=2)
    _insert_delta(evidence_db, tid, 1, 2, "DISPROVEN")
    _insert_delta(evidence_db, tid, 2, 2, "STRENGTHENED")  # 非法续链
    _bind(rec["campaign_id"], tid, 2, "SWING")

    with pytest.raises(EvidenceLedgerCorruptedError):
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])


def test_projection_delta_base_revision_mismatch_corrupted(campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(10)
    _install_frozen(evidence_db, tid, revision=2)
    _insert_delta(evidence_db, tid, 1, 1, "STRENGTHENED")  # base != frozen_revision
    _bind(rec["campaign_id"], tid, 2, "SWING")

    with pytest.raises(EvidenceLedgerCorruptedError):
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])


def test_projection_draft_with_deltas_corrupted(campaign_db, evidence_db):
    """未冻结却存在 delta：deltas 只允许锚定 frozen_revision，fail-closed。"""
    rec = _setup_campaign(campaign_db)
    tid = _tid(11)
    _install_non_frozen(evidence_db, tid, "draft")
    _insert_delta(evidence_db, tid, 1, 1, "STRENGTHENED")
    _bind(rec["campaign_id"], tid, 1, "SWING")

    with pytest.raises(EvidenceLedgerCorruptedError):
        formal_thesis_projection.project_current_thesis(rec["campaign_id"])


# ---------------------------------------------------------------------------
# F. API contract
# ---------------------------------------------------------------------------

def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(campaign_router.router)
    return app


@pytest.fixture
def client(campaign_db, evidence_db):
    return TestClient(make_app())


def test_api_current_thesis_200_full_shape(client, campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(12)
    _install_frozen(evidence_db, tid, revision=2)
    _bind(rec["campaign_id"], tid, 2, "SWING")

    r = client.get(f"/api/campaigns/{rec['campaign_id']}/current-thesis")
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data) == {
        "campaign_id", "thesis_id", "binding", "frozen_revision",
        "original_snapshot", "deltas", "effective_state", "ready",
        "formal_status",
    }
    assert data["ready"] is True
    assert data["effective_state"] == "STABLE"


def test_api_current_thesis_not_ready_200(client, campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(13)
    _install_non_frozen(evidence_db, tid, "draft")
    _bind(rec["campaign_id"], tid, 1, "SWING")

    r = client.get(f"/api/campaigns/{rec['campaign_id']}/current-thesis")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["ready"] is False
    assert data["formal_status"] == "NOT_READY"
    assert data["reason"] == "NOT_FROZEN"


def test_api_current_thesis_strategy_conflict_409(client, campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db, strategy="SWING")
    tid = _tid(14)
    _install_frozen(evidence_db, tid, strategy="SHORT", revision=2)
    _bind(rec["campaign_id"], tid, 2, "SWING")

    r = client.get(f"/api/campaigns/{rec['campaign_id']}/current-thesis")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "SHORT" in detail and "SWING" in detail


def test_api_current_thesis_no_binding_404(client, campaign_db):
    rec = _setup_campaign(campaign_db)
    r = client.get(f"/api/campaigns/{rec['campaign_id']}/current-thesis")
    assert r.status_code == 404
    assert r.json()["detail"] == "Thesis Binding 不存在"


def test_api_current_thesis_unknown_campaign_404(client):
    r = client.get(f"/api/campaigns/{'campaign_' + '0' * 32}/current-thesis")
    assert r.status_code == 404
    assert r.json()["detail"] == "Campaign 不存在"


def test_api_current_thesis_corrupted_500_sanitized(client, campaign_db, evidence_db):
    rec = _setup_campaign(campaign_db)
    tid = _tid(15)
    _install_frozen(evidence_db, tid, revision=2)
    _insert_delta(evidence_db, tid, 1, 2, "DISPROVEN")
    _insert_delta(evidence_db, tid, 2, 2, "STRENGTHENED")
    _bind(rec["campaign_id"], tid, 2, "SWING")

    r = client.get(f"/api/campaigns/{rec['campaign_id']}/current-thesis")
    assert r.status_code == 500
    assert r.json()["detail"] == "Campaign 服务暂不可用"


def test_api_current_thesis_missing_ledger_500_sanitized(
    client, campaign_db, evidence_db
):
    rec = _setup_campaign(campaign_db)
    tid = _tid(16)
    _install_frozen(evidence_db, tid, revision=2)
    _bind(rec["campaign_id"], tid, 2, "SWING")
    evidence_db.unlink()

    r = client.get(f"/api/campaigns/{rec['campaign_id']}/current-thesis")
    assert r.status_code == 500
    assert r.json()["detail"] == "Campaign 服务暂不可用"
