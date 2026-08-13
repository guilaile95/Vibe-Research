"""P0-TB2 Formal Trade Attribution persistence ledger tests."""

from __future__ import annotations

import ast
import concurrent.futures
import importlib
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import formal_trade_attribution as fta
import formal_trade_attribution_store as store
import frozen_decision_store as fd_store

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


COMMITTED_AT = "2026-08-10T06:00:00.000000Z"
TRADE_CREATED_AT = "2026-08-10T06:30:00.000000+00:00"
TRADE_EXECUTED_AT = "2026-08-10T06:45:00.000000+00:00"
REVIEW_BY = "2026-08-25T00:00:00.000000Z"
ATTR_CREATED = "2026-08-10T07:00:00.000000Z"
SECURITY = "600519"
THESIS_ID = "e" * 32
CAMPAIGN_A = "campaign_" + "d" * 32
DECISION_A = "decision_" + "a" * 32


def _snapshot(**overrides) -> dict:
    snap = {
        "snapshot_schema_version": fd_store.SCHEMA_VERSION,
        "decision_id": DECISION_A,
        "security_code": SECURITY,
        "strategy": "SWING",
        "campaign_id": CAMPAIGN_A,
        "committed_at": COMMITTED_AT,
        "thesis_id": THESIS_ID,
        "thesis_revision": 2,
        "asset_view": {},
        "trade_view": {},
        "portfolio_view": {},
        "next_best_action": "BUY SMALL",
        "action_envelope": {},
        "maintain_conditions": [],
        "upgrade_conditions": [],
        "downgrade_conditions": [],
        "invalidation_conditions": [],
        "strategy_horizon": "2w",
        "review_by": REVIEW_BY,
        "key_assumptions": [],
        "event_invalidation_conditions": [],
        "validity_status_at_commit": "CURRENT",
        "risk_policy_version": "rp",
        "opportunity_policy_version": "op",
        "decision_policy_version": "dp",
        "behavior_model_version": "bm",
        "data_quality": {},
        "evidence_confidence": None,
        "inference_confidence": None,
        "decision_confidence": None,
        "evidence_refs": [],
        "risk_refs": [],
        "source_refs": [],
    }
    snap.update(overrides)
    return snap


def make_decision(**overrides) -> dict:
    snap = _snapshot(**{k: v for k, v in overrides.items() if k in fd_store.SNAPSHOT_KEYS})
    return {
        **snap,
        "snapshot_json": fd_store.canonical_json(snap),
        "snapshot_hash": fd_store.snapshot_hash(snap),
        "user_confirmed": True,
        "created_at": "2026-08-10T05:00:00.000000Z",
    }


def make_trade(*, trade_id: str, **overrides) -> dict:
    trade = {
        "trade_id": trade_id,
        "code": SECURITY,
        "name": "茅台",
        "operation": "buy",
        "execution_status": "full",
        "planned_price": 1.0,
        "planned_quantity": 1,
        "actual_price": 1.0,
        "actual_quantity": 1,
        "executed_at": TRADE_EXECUTED_AT,
        "fee": 0.0,
        "other_cost": 0.0,
        "unexecuted_reason": None,
        "note": None,
        "advice_trade_date": None,
        "advice_generated_at": None,
        "advice_snapshot": None,
        "thesis_id": THESIS_ID,
        "thesis_revision": 2,
        "created_at": TRADE_CREATED_AT,
        "voided_at": None,
        "void_reason": None,
    }
    trade.update(overrides)
    return trade


def make_record(*, trade_id: str, attribution_id: str, **kw) -> dict:
    decision = make_decision(
        **{k: v for k, v in kw.items() if k in fd_store.SNAPSHOT_KEYS}
    )
    trade = make_trade(trade_id=trade_id)
    created = kw.get("created_at", ATTR_CREATED)
    return fta.create_attribution(
        decision, trade, attribution_id=attribution_id, created_at=created
    ).to_dict()


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "formal_trade_attributions.sqlite3"


def test_a_import_zero_side_effect(tmp_path, monkeypatch):
    monkeypatch.delenv("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", raising=False)
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "vr"))
    importlib.reload(store)
    assert not (tmp_path / "vr").exists()
    assert list(tmp_path.iterdir()) == [] or not any(
        p.suffix == ".sqlite3" for p in tmp_path.rglob("*")
    )


def test_b_c_read_missing_db_creates_nothing(tmp_path):
    missing = tmp_path / "nested" / "missing.sqlite3"
    parent = missing.parent
    assert store.get_attribution(db_path=missing, attribution_id="trade_attribution_" + "c" * 32) is None
    assert store.list_attributions(db_path=missing) == []
    assert not missing.exists()
    assert not parent.exists()


def test_d_e_first_write_creates_schema_and_roundtrip(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    out = store.write_attribution(db_path=db_path, record=rec)
    assert out == rec
    assert db_path.is_file()
    got = store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"])
    assert got == rec


def test_f_g_write_and_read_use_tb1_from_dict(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    assert store.get_attribution_for_trade(db_path=db_path, trade_id="b" * 32) == rec
    bad = dict(rec)
    bad["attribution_hash"] = "0" * 64
    with pytest.raises(store.FormalTradeAttributionStoreError):
        store.write_attribution(db_path=db_path, record=bad)


def test_h_exact_replay_idempotent(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    a = store.write_attribution(db_path=db_path, record=rec)
    b = store.write_attribution(db_path=db_path, record=rec)
    assert a == b == rec
    assert len(store.list_attributions(db_path=db_path)) == 1


def test_i_same_id_different_content_conflict(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    other = make_record(
        trade_id="1" * 32,
        attribution_id="trade_attribution_" + "c" * 32,
    )
    with pytest.raises(store.FormalTradeAttributionStoreConflictError):
        store.write_attribution(db_path=db_path, record=other)


def test_j_same_trade_different_attribution_conflict(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    other = make_record(
        trade_id="b" * 32,
        attribution_id="trade_attribution_" + "9" * 32,
    )
    with pytest.raises(store.FormalTradeAttributionStoreConflictError):
        store.write_attribution(db_path=db_path, record=other)


def test_k_one_decision_many_trades(db_path):
    a = make_record(trade_id="1" * 32, attribution_id="trade_attribution_" + "1" * 32)
    b = make_record(trade_id="2" * 32, attribution_id="trade_attribution_" + "2" * 32)
    store.write_attribution(db_path=db_path, record=a)
    store.write_attribution(db_path=db_path, record=b)
    listed = store.list_attributions(db_path=db_path, decision_id=DECISION_A)
    assert {r["trade_id"] for r in listed} == {"1" * 32, "2" * 32}


def test_l_one_campaign_many_trades(db_path):
    a = make_record(trade_id="1" * 32, attribution_id="trade_attribution_" + "1" * 32)
    b = make_record(trade_id="2" * 32, attribution_id="trade_attribution_" + "2" * 32)
    store.write_attribution(db_path=db_path, record=a)
    store.write_attribution(db_path=db_path, record=b)
    listed = store.list_attributions(db_path=db_path, campaign_id=CAMPAIGN_A)
    assert len(listed) == 2


def test_m_n_getters(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    assert store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"]) == rec
    assert store.get_attribution_for_trade(db_path=db_path, trade_id="b" * 32) == rec
    assert store.get_attribution(db_path=db_path, attribution_id="trade_attribution_" + "0" * 32) is None


def test_o_p_q_list_filters(db_path):
    a = make_record(trade_id="1" * 32, attribution_id="trade_attribution_" + "1" * 32)
    store.write_attribution(db_path=db_path, record=a)
    assert store.list_attributions(db_path=db_path, decision_id=DECISION_A) == [a]
    assert store.list_attributions(db_path=db_path, campaign_id=CAMPAIGN_A) == [a]
    assert store.list_attributions(db_path=db_path, security_code=SECURITY) == [a]
    assert store.list_attributions(db_path=db_path, security_code="000001") == []


def test_r_s_deterministic_order_and_pagination(db_path):
    earlier = make_record(
        trade_id="1" * 32,
        attribution_id="trade_attribution_" + "b" * 32,
        created_at="2026-08-10T07:00:00.000000Z",
    )
    later = make_record(
        trade_id="2" * 32,
        attribution_id="trade_attribution_" + "a" * 32,
        created_at="2026-08-10T08:00:00.000000Z",
    )
    store.write_attribution(db_path=db_path, record=later)
    store.write_attribution(db_path=db_path, record=earlier)
    listed = store.list_attributions(db_path=db_path)
    assert [r["attribution_id"] for r in listed] == [
        earlier["attribution_id"],
        later["attribution_id"],
    ]
    page = store.list_attributions(db_path=db_path, limit=1, offset=0)
    assert page == [earlier]
    page2 = store.list_attributions(db_path=db_path, limit=1, offset=1)
    assert page2 == [later]


def test_t_u_v_limit_rejects(db_path):
    with pytest.raises(store.FormalTradeAttributionStoreError):
        store.list_attributions(db_path=db_path, limit=-1)
    with pytest.raises(store.FormalTradeAttributionStoreError):
        store.list_attributions(db_path=db_path, limit=True)
    with pytest.raises(store.FormalTradeAttributionStoreError):
        store.list_attributions(db_path=db_path, limit=501)


def test_w_schema_version_mismatch(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE schema_meta SET value='formal-trade-attribution-ledger.v9.9'")
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreSchemaVersionError):
        store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"])


def test_x_missing_column(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE formal_trade_attributions DROP COLUMN note") if False else None
    conn.execute("BEGIN")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(formal_trade_attributions)")]
    keep = [c for c in cols if c != "strategy"]
    conn.execute("ALTER TABLE formal_trade_attributions RENAME TO old_fta")
    conn.execute(
        "CREATE TABLE formal_trade_attributions ("
        + ", ".join(f"{c} TEXT" for c in keep)
        + ")"
    )
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"])


def test_y_extra_column(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE formal_trade_attributions ADD COLUMN extra TEXT")
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.list_attributions(db_path=db_path)


def test_z_wrong_unique_constraint(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE formal_trade_attributions RENAME TO old_fta")
    conn.execute(
        """
        CREATE TABLE formal_trade_attributions (
            attribution_id TEXT PRIMARY KEY,
            trade_id TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            decision_snapshot_hash TEXT NOT NULL,
            security_code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            thesis_id TEXT NOT NULL,
            thesis_revision INTEGER NOT NULL,
            decision_committed_at TEXT NOT NULL,
            decision_review_by TEXT NOT NULL,
            decision_next_best_action TEXT NOT NULL,
            trade_operation TEXT NOT NULL,
            trade_execution_status TEXT NOT NULL,
            trade_executed_at TEXT,
            trade_created_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            attribution_hash TEXT NOT NULL
        )
        """
    )
    conn.execute("INSERT INTO formal_trade_attributions SELECT * FROM old_fta")
    conn.execute("DROP TABLE old_fta")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fta_decision_id ON formal_trade_attributions(decision_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fta_campaign_id ON formal_trade_attributions(campaign_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fta_security_code ON formal_trade_attributions(security_code)"
    )
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.list_attributions(db_path=db_path)


def test_aa_wrong_index(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("DROP INDEX idx_fta_decision_id")
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.list_attributions(db_path=db_path)


def test_ab_corrupted_hash(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE formal_trade_attributions SET attribution_hash = ?",
        ("0" * 64,),
    )
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"])


def test_ac_corrupted_timestamp(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE formal_trade_attributions SET created_at = 'not-a-ts'")
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"])


def test_ad_corrupted_campaign_id(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE formal_trade_attributions SET campaign_id = 'camp-bad'")
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"])


def test_ae_corrupted_trade_id(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE formal_trade_attributions SET trade_id = 'nothex'")
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"])


def test_af_invalid_tb1_schema_version(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE formal_trade_attributions SET schema_version = 'formal_trade_attribution.v9.9'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.get_attribution(db_path=db_path, attribution_id=rec["attribution_id"])


def test_ag_garbage_file(tmp_path):
    garbage = tmp_path / "formal_trade_attributions.sqlite3"
    garbage.write_bytes(b"not a sqlite database")
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.get_attribution(
            db_path=garbage, attribution_id="trade_attribution_" + "c" * 32
        )


def test_r2_production_has_no_test_instrumentation():
    src = Path(store.__file__).read_text(encoding="utf-8")
    assert "VIBE_RESEARCH_FTA_STORE_INIT_HOLD" not in src
    assert "VIBE_RESEARCH_FTA_STORE_INIT_HELD" not in src
    assert "VIBE_RESEARCH_FTA_STORE_OPEN_WAIT_SECONDS" not in src
    assert "_hold_after_excl_if_requested" not in src
    assert "Test-only gate" not in src


def test_ah_ai_aj_no_mutation_api():
    src = Path(store.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert "update_attribution" not in names
    assert "delete_attribution" not in names
    assert "REPLACE INTO" not in src.upper()
    assert "ON CONFLICT" not in src.upper()
    assert "UPDATE formal_trade_attributions" not in src
    assert "DELETE FROM formal_trade_attributions" not in src


def test_ak_no_wall_clock_for_domain():
    src = Path(store.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"now", "utcnow", "today"}:
                pytest.fail("wall clock forbidden")


def test_al_no_attribution_id_generation():
    src = Path(store.__file__).read_text(encoding="utf-8")
    assert "uuid4" not in src
    assert "new_attribution_id" not in src


def test_am_an_no_campaign_or_ledger_lookup():
    src = Path(store.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {
        "campaign_store",
        "campaign_service",
        "trade_ledger_store",
        "trade_ledger_service",
        "frozen_decision_store",
        "frozen_decision_service",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden


def test_ao_no_ai():
    src = Path(store.__file__).read_text(encoding="utf-8")
    assert "openai" not in src
    assert "anthropic" not in src


def test_ap_concurrent_first_initialization(db_path):
    recs = [
        make_record(
            trade_id=f"{i:032x}",
            attribution_id="trade_attribution_" + f"{i:032x}",
        )
        for i in range(4)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        results = list(
            ex.map(
                lambda rec: store.write_attribution(db_path=db_path, record=rec),
                recs,
            )
        )
    assert len(results) == 4
    assert len(store.list_attributions(db_path=db_path)) == 4


def test_aq_concurrent_exact_replay(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(
            ex.map(
                lambda _: store.write_attribution(db_path=db_path, record=rec),
                range(12),
            )
        )
    assert all(r["attribution_id"] == rec["attribution_id"] for r in results)
    assert len(store.list_attributions(db_path=db_path)) == 1


def test_ar_concurrent_conflicting_trade(db_path):
    a = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "1" * 32)
    b = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "2" * 32)
    conflicts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futs = [
            ex.submit(store.write_attribution, db_path=db_path, record=a),
            ex.submit(store.write_attribution, db_path=db_path, record=b),
        ]
        for fut in futs:
            try:
                fut.result()
            except store.FormalTradeAttributionStoreConflictError:
                conflicts.append(1)
    assert len(conflicts) == 1
    assert len(store.list_attributions(db_path=db_path)) == 1


def test_keyword_only_public_api():
    for name in (
        "write_attribution",
        "get_attribution",
        "get_attribution_for_trade",
        "list_attributions",
        "resolve_formal_trade_attribution_db_path",
    ):
        sig = inspect.signature(getattr(store, name))
        assert all(
            p.kind == inspect.Parameter.KEYWORD_ONLY for p in sig.parameters.values()
        )


def test_path_resolution_no_io(tmp_path, monkeypatch):
    monkeypatch.delenv("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", raising=False)
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "data"))
    resolved = store.resolve_formal_trade_attribution_db_path()
    assert resolved.name == "formal_trade_attributions.sqlite3"
    assert not resolved.exists()
    assert not (tmp_path / "data").exists()
    explicit = store.resolve_formal_trade_attribution_db_path(
        explicit_path=tmp_path / "x.sqlite3"
    )
    assert explicit == tmp_path / "x.sqlite3"
    assert not explicit.exists()


def test_r1_read_directory_fail_closed(tmp_path):
    directory = tmp_path / "not_a_db"
    directory.mkdir()
    with pytest.raises(store.FormalTradeAttributionStoreError):
        out = store.get_attribution(
            db_path=directory, attribution_id="trade_attribution_" + "c" * 32
        )
        assert out is not None
    with pytest.raises(store.FormalTradeAttributionStoreError):
        listed = store.list_attributions(db_path=directory)
        assert listed != []


def test_r1_stat_oserror_not_empty(tmp_path, monkeypatch):
    target = tmp_path / "ledger.sqlite3"
    target.write_bytes(b"x")

    def boom(self, *args, **kwargs):
        raise PermissionError("simulated stat failure")

    monkeypatch.setattr(store.Path, "stat", boom)
    with pytest.raises(store.FormalTradeAttributionStoreError):
        out = store.get_attribution(
            db_path=target, attribution_id="trade_attribution_" + "c" * 32
        )
        assert out is not None
    with pytest.raises(store.FormalTradeAttributionStoreError):
        listed = store.list_attributions(db_path=target)
        assert listed != []


def test_r1_readonly_open_oserror_fail_closed(db_path, monkeypatch):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)

    def boom(_path):
        raise PermissionError("readonly open denied")

    monkeypatch.setattr(store, "_connect_readonly", boom)
    with pytest.raises(store.FormalTradeAttributionStoreError):
        out = store.get_attribution(
            db_path=db_path, attribution_id=rec["attribution_id"]
        )
        assert out is not None
    with pytest.raises(store.FormalTradeAttributionStoreError):
        listed = store.list_attributions(db_path=db_path)
        assert listed != []


def test_r1_empty_file_non_owner_times_out_fail_closed(db_path, monkeypatch):
    db_path.write_bytes(b"")
    monkeypatch.setattr(store, "_OPEN_WAIT_TOTAL_SECONDS", 0.2)
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    with pytest.raises(
        store.FormalTradeAttributionStoreCorruptedError, match="INITIALIZATION_INCOMPLETE"
    ):
        store.write_attribution(db_path=db_path, record=rec)


def test_r1_partial_unique_trade_id_rejected(db_path):
    rec = make_record(trade_id="b" * 32, attribution_id="trade_attribution_" + "c" * 32)
    store.write_attribution(db_path=db_path, record=rec)
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE formal_trade_attributions RENAME TO old_fta")
    conn.execute(
        """
        CREATE TABLE formal_trade_attributions (
            attribution_id TEXT PRIMARY KEY,
            trade_id TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            decision_snapshot_hash TEXT NOT NULL,
            security_code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            thesis_id TEXT NOT NULL,
            thesis_revision INTEGER NOT NULL,
            decision_committed_at TEXT NOT NULL,
            decision_review_by TEXT NOT NULL,
            decision_next_best_action TEXT NOT NULL,
            trade_operation TEXT NOT NULL,
            trade_execution_status TEXT NOT NULL,
            trade_executed_at TEXT,
            trade_created_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            attribution_hash TEXT NOT NULL
        )
        """
    )
    conn.execute("INSERT INTO formal_trade_attributions SELECT * FROM old_fta")
    conn.execute("DROP TABLE old_fta")
    conn.execute(
        "CREATE UNIQUE INDEX idx_partial_trade_id "
        "ON formal_trade_attributions(trade_id) WHERE security_code = '600519'"
    )
    conn.execute(
        "CREATE INDEX idx_fta_decision_id ON formal_trade_attributions(decision_id)"
    )
    conn.execute(
        "CREATE INDEX idx_fta_campaign_id ON formal_trade_attributions(campaign_id)"
    )
    conn.execute(
        "CREATE INDEX idx_fta_security_code ON formal_trade_attributions(security_code)"
    )
    conn.commit()
    conn.close()
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.list_attributions(db_path=db_path)


def test_r1_multiprocess_first_init(tmp_path):
    db_path = tmp_path / "mp.sqlite3"
    hold = tmp_path / "release.flag"
    held = tmp_path / "held.flag"
    rec_a = make_record(
        trade_id="1" * 32, attribution_id="trade_attribution_" + "1" * 32
    )
    rec_b = make_record(
        trade_id="2" * 32, attribution_id="trade_attribution_" + "2" * 32
    )
    rec_a_path = tmp_path / "a.json"
    rec_b_path = tmp_path / "b.json"
    rec_a_path.write_text(json.dumps(rec_a), encoding="utf-8")
    rec_b_path.write_text(json.dumps(rec_b), encoding="utf-8")
    backend = str(Path(__file__).resolve().parents[1])
    # Test-only worker: pause after O_EXCL by wrapping production acquire.
    # Production store has no hold/env instrumentation.
    worker = r"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import formal_trade_attribution_store as s
hold, held = sys.argv[4], sys.argv[5]
orig = s._acquire_initialization_ownership
def acquire(path):
    owned = orig(path)
    if owned and hold:
        Path(held).write_text("held", encoding="utf-8")
        release = Path(hold)
        deadline = time.monotonic() + 30
        while not release.is_file():
            if time.monotonic() >= deadline:
                raise SystemExit("hold timeout")
            time.sleep(0.02)
    return owned
s._acquire_initialization_ownership = acquire
rec = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
s.write_attribution(db_path=sys.argv[3], record=rec)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = backend
    proc_a = subprocess.Popen(
        [
            sys.executable,
            "-c",
            worker,
            backend,
            str(rec_a_path),
            str(db_path),
            str(hold),
            str(held),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not held.is_file():
        if time.monotonic() >= deadline:
            proc_a.kill()
            out, err = proc_a.communicate()
            pytest.fail(f"owner never signaled hold: {out} {err}")
        if proc_a.poll() is not None:
            out, err = proc_a.communicate()
            pytest.fail(f"owner exited before hold: {out} {err}")
        time.sleep(0.02)
    assert db_path.is_file()
    proc_b = subprocess.Popen(
        [
            sys.executable,
            "-c",
            worker,
            backend,
            str(rec_b_path),
            str(db_path),
            "",
            "",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.2)
    hold.write_text("go", encoding="utf-8")
    rc_a = proc_a.wait(timeout=20)
    rc_b = proc_b.wait(timeout=20)
    if rc_a != 0 or rc_b != 0:
        pytest.fail(
            f"A={rc_a} {proc_a.stderr.read() if proc_a.stderr else ''} "
            f"B={rc_b} {proc_b.stderr.read() if proc_b.stderr else ''}"
        )
    listed = store.list_attributions(db_path=db_path)
    assert len(listed) == 2
    assert {r["trade_id"] for r in listed} == {"1" * 32, "2" * 32}
