from __future__ import annotations

import sqlite3

import pytest

import formal_trade_attribution as fta
import formal_trade_attribution_store as store
import trade_campaign_reconciliation as tcr


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
