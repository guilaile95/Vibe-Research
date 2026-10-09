"""Offline restore drill through real formal-authority services, not generic SQL.

Synthetic data only. This composes existing bundle/store/runtime contracts; it
is not browser, provider, broker, automatic configuration, or live-use evidence.
The quiescence probe is injected because this test owns every temporary source.
"""
from __future__ import annotations

import hashlib
import os
import socket
import zipfile
from pathlib import Path

import pytest

import formal_trade_attribution_store as attribution_store
import frozen_decision_service as decisions
import local_data_snapshot as snapshot
import trade_attribution_runtime as resolution
import trade_ledger_service as trades
import vibe_data_backup as backup


DB_NAMES = {
    "VIBE_RESEARCH_FROZEN_DECISION_DB": "frozen_decisions.sqlite3",
    "VIBE_RESEARCH_TRADE_LEDGER_DB": "trade_ledger.sqlite3",
    "VIBE_RESEARCH_TRADE_ATTRIBUTION_DB": "formal_trade_attributions.sqlite3",
    "VIBE_RESEARCH_TRADE_ORIGIN_DB": "trade_origins.sqlite3",
}


def _fingerprint(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


@pytest.fixture(params=["default", "external"])
def source(request, tmp_path, monkeypatch):
    # Do not inherit any developer/local DB override, even one not used below.
    for name in list(os.environ):
        if (name.startswith("VIBE_RESEARCH_") and name.endswith("_DB")) or name in {
            "VR_DATA_DIR", "VR_REPORTS_DIR", "VR_FACT_LAKE_ROOT",
            "VIBE_RESEARCH_RESEARCH_DATA_DIR", "VIBE_NATIVE_INTEL_DB",
        }:
            monkeypatch.delenv(name, raising=False)
    root = tmp_path / "original"
    data = root / "data"
    data.mkdir(parents=True)
    monkeypatch.setenv("VR_DATA_DIR", str(data))
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "empty-home"))
    monkeypatch.setattr(backup.review_db_path, "resolve_review_db_path",
                        lambda: root / "absent-review.sqlite3")
    if request.param == "external":
        for name, filename in DB_NAMES.items():
            monkeypatch.setenv(name, str(root / "external" / filename))

    attempts = []
    def forbidden(*_args, **_kwargs):
        attempts.append(True)
        pytest.fail("Formal backup journey attempted network transport")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    yield root, request.param
    assert not attempts


def _decision():
    return decisions.freeze_decision({
        "security_code": "600519", "strategy": "SWING",
        "campaign_id": "campaign_" + "a" * 32,
        "thesis_id": "b" * 32, "thesis_revision": 1,
        "asset_view": {}, "trade_view": {}, "portfolio_view": {},
        "next_best_action": "BUY SMALL", "action_envelope": {},
        "maintain_conditions": [], "upgrade_conditions": [],
        "downgrade_conditions": [], "invalidation_conditions": [],
        "strategy_horizon": "2w", "review_by": "2099-01-01T00:00:00Z",
        "key_assumptions": [], "event_invalidation_conditions": [],
        "risk_policy_version": "synthetic-risk", "opportunity_policy_version": "synthetic-opp",
        "decision_policy_version": "synthetic-decision", "behavior_model_version": "synthetic-behavior",
        "data_quality": {}, "evidence_confidence": None,
        "inference_confidence": None, "decision_confidence": None,
        "evidence_refs": [], "risk_refs": [], "source_refs": [], "user_confirmed": True,
    })


def _trade(**overrides):
    return trades.create_trade({
        "code": "600519", "name": "Synthetic restore fixture", "operation": "buy",
        "execution_status": "full", "actual_price": 100.0,
        "actual_quantity": 1, "executed_at": "2098-01-01T01:00:00Z", **overrides,
    })


def _seed():
    decision = _decision()
    records = {name: _trade() for name in ("allocated", "unplanned", "unallocated", "voided")}
    records["not_executed"] = _trade(
        execution_status="not_executed", actual_price=None, actual_quantity=0,
        executed_at=None, unexecuted_reason="Synthetic cancellation",
    )
    records["voided"] = trades.void_trade(records["voided"]["trade_id"], "Synthetic pre-backup void")
    attribution = resolution.attribute(records["allocated"]["trade_id"], {"decision_id": decision["decision_id"]})
    origin = resolution.mark_unplanned(records["unplanned"]["trade_id"], {"confirm": True})
    # Compare the same public read contract on both sides of the restore.
    records = {name: trades.get_trade(record["trade_id"]) for name, record in records.items()}
    return decision, records, attribution["record"], origin["record"]


def test_restored_formal_authorities_reopen_replay_and_continue(source, tmp_path, monkeypatch):
    root, topology = source
    decision, records, attribution, origin = _seed()
    before = {name: resolution.reconciliation_for_trade(record["trade_id"])
              for name, record in records.items()}
    assert {name: value["allocation_state"] for name, value in before.items()} == {
        "allocated": "ALLOCATED", "unplanned": "UNPLANNED", "unallocated": "UNALLOCATED",
        "voided": "NOT_APPLICABLE", "not_executed": "NOT_APPLICABLE",
    }
    archive = tmp_path / "formal.zip"
    source_bytes = _fingerprint(root)
    assert backup.create_bundle(archive, quiescent_probe=lambda: backup.QUIESCENT)["status"] == "OK"
    assert _fingerprint(root) == source_bytes
    assert backup.verify_bundle(archive)["status"] == "OK"
    restored = tmp_path / "restored"
    report = backup.restore_bundle(archive, restored)
    assert report["status"] == "OK"

    # Detach the source before reopening. A stale path must not accidentally pass
    # by reading still-present originals or silently creating replacement stores.
    detached = tmp_path / "detached-original"
    root.rename(detached)
    monkeypatch.setenv("VR_DATA_DIR", str(restored / "data"))
    if topology == "external":
        assets = {asset["name"]: asset for asset in report["assets"]}
        for name in DB_NAMES:
            assert assets[name]["status"] == "EXTERNAL_OVERRIDE_INCLUDED"
            monkeypatch.setenv(name, str(restored / assets[name]["archive_prefix"]))
    for name, record in records.items():
        assert trades.get_trade(record["trade_id"]) == record
        reopened = resolution.reconciliation_for_trade(record["trade_id"])
        assert ("as_of" in reopened) == ("as_of" in before[name])
        if "as_of" in before[name]:
            assert reopened["as_of"] >= before[name]["as_of"]
        assert {k: v for k, v in reopened.items() if k != "as_of"} == {
            k: v for k, v in before[name].items() if k != "as_of"
        }
    assert decisions.get_decision(decision["decision_id"]) == decision
    assert resolution.attribute(records["allocated"]["trade_id"], {"decision_id": decision["decision_id"]}) == {
        "record": attribution, "idempotent": True,
    }
    assert resolution.mark_unplanned(records["unplanned"]["trade_id"], {"confirm": True}) == {
        "record": origin, "idempotent": True,
    }
    # Restoring does not reopen authority choice or infer attribution by ticker.
    with pytest.raises(resolution.TradeAttributionConflictError):
        resolution.attribute(records["unplanned"]["trade_id"], {"decision_id": decision["decision_id"]})
    with pytest.raises(resolution.TradeAttributionConflictError):
        resolution.mark_unplanned(records["allocated"]["trade_id"], {"confirm": True})
    assert resolution.reconciliation_for_trade(records["unallocated"]["trade_id"])["allocation_state"] == "UNALLOCATED"

    trades.void_trade(records["allocated"]["trade_id"], "Synthetic post-restore void")
    assert resolution.reconciliation_for_trade(records["allocated"]["trade_id"])["allocation_state"] == "NOT_APPLICABLE"
    assert attribution_store.get_attribution_for_trade(
        db_path=attribution_store.resolve_formal_trade_attribution_db_path(),
        trade_id=records["allocated"]["trade_id"],
    ) == attribution
    assert decisions.get_decision(decision["decision_id"]) == decision
    assert len(trades.list_trades(include_voided=True)) == 5
    assert len(trades.list_trades()) == 3
    assert _fingerprint(detached) == source_bytes
    assert not root.exists(), "No production service may fall back to the detached source"


def test_tampered_formal_database_refuses_restore_before_target_creation(source, tmp_path):
    root, _topology = source
    _seed()
    archive = tmp_path / "formal.zip"
    backup.create_bundle(archive, quiescent_probe=lambda: backup.QUIESCENT)
    source_bytes = _fingerprint(root)
    tampered = tmp_path / "tampered.zip"
    # A ZIP with valid CRC but altered SQLite bytes must fail manifest integrity.
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(tampered, "w") as output:
        changed = False
        for info in original.infolist():
            raw = original.read(info.filename)
            if not changed and info.filename.endswith(".sqlite3"):
                raw = raw[:-1] + bytes([raw[-1] ^ 1])
                changed = True
            output.writestr(info, raw)
    assert changed
    assert backup.verify_bundle(tampered)["status"] == "FAILED"
    target = tmp_path / "refused"
    with pytest.raises(snapshot.RestoreRefused):
        backup.restore_bundle(tampered, target)
    assert not target.exists()
    assert _fingerprint(root) == source_bytes
