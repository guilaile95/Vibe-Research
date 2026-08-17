from __future__ import annotations

import sqlite3

import pytest

import formal_trade_attribution as fta
import formal_trade_attribution_store as store
import trade_campaign_reconciliation as tcr
import trade_origin_store as origin_store


def _create_attribution_schema_variant(
    path,
    *,
    attribution_id_pk=True,
    schema_meta_key_pk=True,
    thesis_revision_type="INTEGER",
    decision_id_notnull=True,
    trade_unique="full",
    decision_index="normal",
    campaign_index="normal",
    security_index="normal",
):
    meta_key = "key TEXT PRIMARY KEY" if schema_meta_key_pk else "key TEXT"
    attribution_id = (
        "attribution_id TEXT PRIMARY KEY"
        if attribution_id_pk
        else "attribution_id TEXT"
    )
    decision_id = "decision_id TEXT NOT NULL" if decision_id_notnull else "decision_id TEXT"
    trade_id = "trade_id TEXT NOT NULL"
    if trade_unique == "full":
        trade_id += " UNIQUE"
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE schema_meta ({meta_key}, value TEXT NOT NULL)")
    conn.execute(
        f"""CREATE TABLE formal_trade_attributions (
            {attribution_id},
            {trade_id},
            {decision_id},
            decision_snapshot_hash TEXT NOT NULL,
            security_code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            thesis_id TEXT NOT NULL,
            thesis_revision {thesis_revision_type} NOT NULL,
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
        )"""
    )
    if trade_unique == "partial":
        conn.execute(
            "CREATE UNIQUE INDEX uq_fta_trade_id_partial "
            "ON formal_trade_attributions(trade_id) WHERE trade_id IS NOT NULL"
        )

    def add_index(name, column, mode):
        if mode == "normal":
            conn.execute(f"CREATE INDEX {name} ON formal_trade_attributions({column})")
        elif mode == "unique":
            conn.execute(
                f"CREATE UNIQUE INDEX {name} ON formal_trade_attributions({column})"
            )
        elif mode == "partial":
            conn.execute(
                f"CREATE INDEX {name} ON formal_trade_attributions({column}) "
                f"WHERE {column} IS NOT NULL"
            )
        elif mode == "wrong_table":
            conn.execute(f"CREATE INDEX {name} ON schema_meta(key)")
        elif mode == "wrong_column":
            conn.execute(
                f"CREATE INDEX {name} ON formal_trade_attributions(trade_id)"
            )
        else:
            raise AssertionError(mode)

    add_index("idx_fta_decision_id", "decision_id", decision_index)
    add_index("idx_fta_campaign_id", "campaign_id", campaign_index)
    add_index("idx_fta_security_code", "security_code", security_index)
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (store.STORE_SCHEMA_VERSION,),
    )
    conn.commit()
    conn.close()


def _valid_attribution():
    from test_formal_trade_attribution import make_decision, make_trade

    return fta.create_attribution(
        make_decision(),
        make_trade(),
        attribution_id="trade_attribution_" + "b" * 32,
        created_at="2026-08-17T00:00:00.000000Z",
    ).to_dict()


def test_missing_read_has_no_side_effect(tmp_path):
    path = tmp_path / "nested" / "missing.sqlite3"
    assert store.list_attributions(db_path=path) == []
    assert store.get_attribution_for_trade(db_path=path, trade_id="a" * 32) is None
    assert not path.exists()
    assert not path.parent.exists()


def test_append_only_roundtrip_and_conflicts(tmp_path):
    decision = {
        "snapshot_schema_version": "frozen_decision.v0.1",
    }
    # This test exercises the append-only boundary with a TB1 record created
    # by the existing TB1 tests' canonical construction path below.
    from test_formal_trade_attribution import make_decision, make_trade
    decision = make_decision()
    trade = make_trade(trade_id="a" * 32)
    record = fta.create_attribution(decision, trade, attribution_id="trade_attribution_" + "b" * 32, created_at="2026-08-10T07:00:00.000000Z").to_dict()
    path = tmp_path / "attributions.sqlite3"
    assert store.write_attribution(db_path=path, record=record) == record
    assert store.write_attribution(db_path=path, record=record) == record
    assert store.get_attribution_for_trade(db_path=path, trade_id=trade["trade_id"]) == record
    other = dict(record)
    other["trade_id"] = "c" * 32
    with pytest.raises(store.FormalTradeAttributionStoreError):
        store.write_attribution(db_path=path, record=other)


def test_corrupt_existing_store_fails_closed(tmp_path):
    path = tmp_path / "attributions.sqlite3"
    path.write_bytes(b"not sqlite")
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.list_attributions(db_path=path)


@pytest.mark.parametrize(
    "variant",
    [
        {"attribution_id_pk": False},
        {"schema_meta_key_pk": False},
        {"thesis_revision_type": "TEXT"},
        {"decision_id_notnull": False},
        {"trade_unique": "partial"},
        {"decision_index": "unique"},
        {"campaign_index": "partial"},
        {"security_index": "wrong_table"},
        {"security_index": "wrong_column"},
    ],
)
def test_existing_malformed_schema_fails_closed_for_reads_and_writes(tmp_path, variant):
    path = tmp_path / "malformed.sqlite3"
    _create_attribution_schema_variant(path, **variant)
    record = _valid_attribution()

    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.list_attributions(db_path=path)
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.write_attribution(db_path=path, record=record)


def test_valid_existing_schema_roundtrip_remains_pass(tmp_path):
    path = tmp_path / "valid.sqlite3"
    record = _valid_attribution()
    store.write_attribution(db_path=path, record=record)
    assert store.get_attribution_for_trade(db_path=path, trade_id=record["trade_id"]) == record
    assert store.write_attribution(db_path=path, record=record) == record


def test_bad_attribution_hash_still_fails_closed(tmp_path):
    path = tmp_path / "bad-row.sqlite3"
    record = _valid_attribution()
    store.write_attribution(db_path=path, record=record)
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE formal_trade_attributions SET attribution_hash = 'bad'"
    )
    conn.commit()
    conn.close()

    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.get_attribution_for_trade(db_path=path, trade_id=record["trade_id"])
    with pytest.raises(store.FormalTradeAttributionStoreCorruptedError):
        store.write_attribution(db_path=path, record=record)


def test_origin_store_validates_identity_time_and_rows(tmp_path):
    path = tmp_path / "origins.sqlite3"
    valid = {
        "resolution_id": "trade_origin_" + "a" * 32,
        "trade_id": "b" * 32,
        "origin": "UNPLANNED",
        "pre_trade_decision": "NONE",
        "pre_trade_thesis": "NONE",
        "created_at": "2026-08-17T00:00:00.000000Z",
    }
    assert origin_store.write(db_path=path, record=valid) == valid
    assert origin_store.get_for_trade(db_path=path, trade_id=valid["trade_id"]) == valid
    for field, value in (("resolution_id", "bad"), ("trade_id", "bad"), ("created_at", "2026-08-17T00:00:00Z")):
        bad = dict(valid, **{field: value})
        with pytest.raises(origin_store.TradeOriginStoreError):
            origin_store.write(db_path=tmp_path / f"{field}.sqlite3", record=bad)

    conn = sqlite3.connect(path)
    conn.execute("UPDATE trade_origin_resolutions SET pre_trade_thesis='bad'")
    conn.commit()
    conn.close()
    with pytest.raises(origin_store.TradeOriginStoreCorruptedError):
        origin_store.get_for_trade(db_path=path, trade_id=valid["trade_id"])


def _trade(status="full"):
    return {
        "trade_id": "a" * 32, "code": "600519", "operation": "buy",
        "execution_status": status,
        "created_at": "2026-08-10T06:30:00Z",
        "executed_at": None if status == "not_executed" else "2026-08-10T06:45:00Z",
        "voided_at": None, "thesis_id": None, "thesis_revision": None,
    }


def test_reconciliation_requires_explicit_complete_coverage():
    base = dict(
        as_of="2026-08-10T08:00:00Z", policy_version=tcr.POLICY_VERSION_V01,
        trade=_trade(), attribution_records=[],
        attribution_coverage_authority_refs=["runtime:scan"],
        trade_authority_refs=["trade-ledger:a"],
    )
    unknown = tcr.project_trade_campaign_reconciliation(**base, attribution_coverage="UNKNOWN")
    assert unknown["allocation_state"] == "UNKNOWN"
    complete = tcr.project_trade_campaign_reconciliation(**base, attribution_coverage="COMPLETE")
    assert complete["allocation_state"] == "UNALLOCATED"
    assert complete["reconciliation_requirement"] == "REQUIRED"
