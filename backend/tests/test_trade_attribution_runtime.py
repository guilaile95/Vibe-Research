from __future__ import annotations

from decision_clock_fixtures import synthetic_execution_clock as _synthetic_execution_clock  # noqa: F401

import concurrent.futures
import os
from copy import deepcopy

import pytest

import formal_trade_attribution as fta
import formal_trade_attribution_store as attribution_store
import frozen_decision_service
import trade_attribution_runtime as runtime
import trade_ledger_service
import trade_origin_store as origin_store


def decision_payload(**overrides):
    value = {
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": "campaign_" + "a" * 32,
        "thesis_id": "b" * 32,
        "thesis_revision": 1,
        "asset_view": {}, "trade_view": {}, "portfolio_view": {},
        "next_best_action": "BUY SMALL", "action_envelope": {},
        "maintain_conditions": [], "upgrade_conditions": [],
        "downgrade_conditions": [], "invalidation_conditions": [],
        "strategy_horizon": "2w", "review_by": "2099-01-01T00:00:00Z",
        "key_assumptions": [], "event_invalidation_conditions": [],
        "risk_policy_version": "risk", "opportunity_policy_version": "opp",
        "decision_policy_version": "decision", "behavior_model_version": "behavior",
        "data_quality": {}, "evidence_confidence": None,
        "inference_confidence": None, "decision_confidence": None,
        "evidence_refs": [], "risk_refs": [], "source_refs": [],
        "user_confirmed": True,
    }
    value.update(overrides)
    return value


def trade_payload(**overrides):
    value = {
        "code": "600519", "name": "贵州茅台", "operation": "buy",
        "execution_status": "full", "actual_price": 100.0,
        "actual_quantity": 1, "executed_at": "2098-01-01T01:00:00Z",
        "fee": 0.0,
        "other_cost": 0.0,
    }
    value.update(overrides)
    return value


@pytest.fixture
def runtime_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(tmp_path / "trades.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(tmp_path / "decisions.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", str(tmp_path / "attributions.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_ORIGIN_DB", str(tmp_path / "origins.sqlite3"))


def _setup(runtime_env):
    decision = frozen_decision_service.freeze_decision(decision_payload())
    trade = trade_ledger_service.create_trade(trade_payload())
    return decision, trade


def test_initial_complete_scan_is_unallocated_and_no_inference(runtime_env):
    decision, trade = _setup(runtime_env)
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "UNALLOCATED"
    assert result["reconciliation_requirement"] == "REQUIRED"
    assert result["campaign_id"] is None
    assert runtime.list_candidates(trade["trade_id"])[0]["decision_id"] == decision["decision_id"]
    scan = runtime.scan_candidates(trade["trade_id"])
    assert scan["scan_state"] == "COMPLETE"
    assert scan["reason_codes"] == []
    assert scan["candidates"][0]["decision_id"] == decision["decision_id"]


@pytest.mark.parametrize(
    ("next_best_action", "operation"),
    [("WAIT", "buy"), ("EXIT", "add")],
)
def test_candidate_scan_and_explicit_attribution_preserve_action_deviation(
    runtime_env, next_best_action, operation
):
    decision = frozen_decision_service.freeze_decision(
        decision_payload(next_best_action=next_best_action)
    )
    trade = trade_ledger_service.create_trade(trade_payload(operation=operation))
    scan = runtime.scan_candidates(trade["trade_id"])
    assert scan["scan_state"] == "COMPLETE"
    assert [item["decision_id"] for item in scan["candidates"]] == [decision["decision_id"]]
    result = runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    assert result["record"]["decision_next_best_action"] == next_best_action
    assert result["record"]["trade_operation"] == operation
    assert runtime.reconciliation_for_trade(trade["trade_id"])["allocation_state"] == "ALLOCATED"


@pytest.mark.parametrize("reference", ["different_id", "different_revision", "matching", "unlinked"])
def test_candidate_thesis_reference_matches_write_boundary(runtime_env, tmp_path, monkeypatch, reference):
    import socket
    import evidence_thesis_service

    def deny_network(*args, **kwargs):
        raise AssertionError("Synthetic attribution tests forbid network access")
    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    thesis_db = tmp_path / "theses.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(thesis_db))
    thesis = evidence_thesis_service.create_thesis(thesis_db, {
        "subject_type": "stock", "subject_id": "600519", "title": "Synthetic thesis",
        "summary": "Synthetic", "core_claims": ["Synthetic"], "catalysts": [],
        "risks": [], "invalidation_conditions": [],
    })
    thesis_id = thesis["thesis"]["id"]
    decision = frozen_decision_service.freeze_decision(decision_payload(
        thesis_id="c" * 32 if reference == "different_id" else thesis_id,
        thesis_revision=2 if reference == "different_revision" else 1,
    ))
    payload = trade_payload()
    if reference != "unlinked":
        payload["thesis_ref"] = {"thesis_id": thesis_id, "revision_number": 1}
    trade = trade_ledger_service.create_trade(payload)
    scan = runtime.scan_candidates(trade["trade_id"])
    if reference in ("different_id", "different_revision"):
        assert scan["scan_state"] == "COMPLETE_EMPTY"
        assert scan["reason_codes"] == ["NO_ELIGIBLE_CANDIDATE"]
        assert scan["candidates"] == []
        assert runtime.list_candidates(trade["trade_id"]) == []
        with pytest.raises(runtime.TradeAttributionValidationError):
            runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
        assert attribution_store.get_attribution_for_trade(
            db_path=attribution_store.resolve_formal_trade_attribution_db_path(),
            trade_id=trade["trade_id"],
        ) is None
    else:
        assert scan["scan_state"] == "COMPLETE"
        assert scan["reason_codes"] == []
        assert [item["decision_id"] for item in scan["candidates"]] == [decision["decision_id"]]
        result = runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
        assert result["record"]["decision_id"] == decision["decision_id"]


def test_not_executed_trade_has_non_applicable_candidate_scan(runtime_env):
    decision = frozen_decision_service.freeze_decision(decision_payload())
    trade = trade_ledger_service.create_trade(
        trade_payload(
            execution_status="not_executed",
            executed_at=None,
            actual_price=None,
            actual_quantity=0,
            unexecuted_reason="等待确认",
        )
    )
    scan = runtime.scan_candidates(trade["trade_id"])
    assert scan == {
        "candidates": [],
        "scan_state": "NOT_APPLICABLE",
        "reason_codes": ["TRADE_NOT_APPLICABLE"],
    }
    assert runtime.reconciliation_for_trade(trade["trade_id"])["allocation_state"] == "NOT_APPLICABLE"
    with pytest.raises(runtime.TradeAttributionValidationError):
        runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})


def test_invalid_witness_scan_state_does_not_look_like_empty(runtime_env, monkeypatch):
    decision, trade = _setup(runtime_env)
    invalid = deepcopy(decision)
    invalid["snapshot_hash"] = "0" * 64
    monkeypatch.setattr(
        runtime.frozen_decision_service,
        "list_decisions",
        lambda **_kwargs: [invalid],
    )
    scan = runtime.scan_candidates(trade["trade_id"])
    assert scan["candidates"] == []
    assert scan["scan_state"] == "INVALID_WITNESS"
    assert scan["reason_codes"] == ["FROZEN_DECISION_WITNESS_INVALID"]


def test_mixed_valid_and_invalid_witness_fails_closed(runtime_env, monkeypatch):
    valid, trade = _setup(runtime_env)
    invalid = deepcopy(valid)
    invalid["decision_id"] = "decision_" + "d" * 32
    invalid["snapshot_hash"] = "0" * 64
    monkeypatch.setattr(
        runtime.frozen_decision_service,
        "list_decisions",
        lambda **_kwargs: [valid, invalid],
    )

    scan = runtime.scan_candidates(trade["trade_id"])

    assert scan["scan_state"] == "INVALID_WITNESS"
    assert scan["scan_state"] != "COMPLETE"
    assert scan["candidates"] == []
    assert "FROZEN_DECISION_WITNESS_INVALID" in scan["reason_codes"]


def test_explicit_attribution_is_exact_and_replay_is_idempotent(runtime_env):
    decision, trade = _setup(runtime_env)
    first = runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    second = runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    assert first["record"] == second["record"]
    assert second["idempotent"] is True
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "ALLOCATED"
    assert result["campaign_id"] == decision["campaign_id"]
    assert result["decision_id"] == decision["decision_id"]


def test_caller_cannot_supply_formal_identity_and_post_trade_decision_is_rejected(runtime_env):
    decision, trade = _setup(runtime_env)
    with pytest.raises(runtime.TradeAttributionValidationError):
        runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"], "campaign_id": decision["campaign_id"]})
    late = frozen_decision_service.freeze_decision(decision_payload(campaign_id="campaign_" + "c" * 32))
    # The service-generated commit is after the already-created trade.
    with pytest.raises(runtime.TradeAttributionValidationError):
        runtime.attribute(trade["trade_id"], {"decision_id": late["decision_id"]})


def test_unplanned_is_durable_without_fake_formal_identity(runtime_env):
    _, trade = _setup(runtime_env)
    first = runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
    second = runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
    assert second["idempotent"] is True
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "UNPLANNED"
    assert result["reconciliation_requirement"] == "NOT_REQUIRED"
    assert result["campaign_id"] is None
    assert result["decision_id"] is None
    assert result["pre_trade_decision"] == "NONE"
    assert result["pre_trade_thesis"] == "NONE"
    assert first["record"]["trade_id"] == trade["trade_id"]


def test_voided_and_not_executed_are_not_applicable(runtime_env):
    decision, trade = _setup(runtime_env)
    trade_ledger_service.void_trade(trade["trade_id"], "test")
    assert runtime.reconciliation_for_trade(trade["trade_id"])["allocation_state"] == "NOT_APPLICABLE"
    with pytest.raises(runtime.TradeAttributionValidationError):
        runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})


def test_corrupt_attribution_store_is_error_not_unallocated(runtime_env):
    _, trade = _setup(runtime_env)
    # pytest's MonkeyPatch has no getenv; use the same deterministic path from
    # the fixture environment without touching any real user data.
    import os
    corrupt_path = os.environ["VIBE_RESEARCH_TRADE_ATTRIBUTION_DB"]
    with open(corrupt_path, "wb") as handle:
        handle.write(b"not sqlite")
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "ERROR"
    assert result["allocation_state"] != "UNALLOCATED"


def test_resolution_mutual_exclusion_in_both_directions(runtime_env):
    decision, trade = _setup(runtime_env)
    runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
    with pytest.raises(runtime.TradeAttributionConflictError):
        runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    assert attribution_store.get_attribution_for_trade(
        db_path=attribution_store.resolve_formal_trade_attribution_db_path(),
        trade_id=trade["trade_id"],
    ) is None

    _, second_trade = _setup(runtime_env)
    runtime.attribute(second_trade["trade_id"], {"decision_id": decision["decision_id"]})
    with pytest.raises(runtime.TradeAttributionConflictError):
        runtime.mark_unplanned(second_trade["trade_id"], {"confirm": True})
    assert origin_store.get_for_trade(
        db_path=origin_store.resolve_db_path(), trade_id=second_trade["trade_id"]
    ) is None


def test_dual_authority_read_fails_closed(runtime_env):
    decision, trade = _setup(runtime_env)
    runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    origin_store.write(
        db_path=origin_store.resolve_db_path(),
        record={
            "resolution_id": "trade_origin_" + "c" * 32,
            "trade_id": trade["trade_id"],
            "origin": "UNPLANNED",
            "pre_trade_decision": "NONE",
            "pre_trade_thesis": "NONE",
            "created_at": "2026-08-17T00:00:00.000000Z",
        },
    )
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "ERROR"
    assert result["reconciliation_requirement"] == "ERROR"
    assert result["reason_codes"] == ["CONFLICTING_TRADE_RESOLUTION_AUTHORITIES"]


def test_unplanned_rejects_existing_pre_trade_thesis(runtime_env, monkeypatch):
    _, trade = _setup(runtime_env)
    contradictory = dict(trade, thesis_id="b" * 32, thesis_revision=1)
    monkeypatch.setattr(runtime, "_trade", lambda trade_id: contradictory)
    with pytest.raises(runtime.TradeAttributionConflictError):
        runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
    assert not os.path.exists(os.environ["VIBE_RESEARCH_TRADE_ORIGIN_DB"])


def test_concurrent_resolution_writes_have_one_winner(runtime_env):
    decision, trade = _setup(runtime_env)

    def attempt(kind):
        try:
            if kind == "attribution":
                return "attribution", runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
            return "unplanned", runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
        except runtime.TradeAttributionRuntimeError as exc:
            return kind, exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("attribution", "unplanned")))
    successes = [item for _, item in results if not isinstance(item, Exception)]
    assert len(successes) == 1
    assert runtime.reconciliation_for_trade(trade["trade_id"])["allocation_state"] in {"ALLOCATED", "UNPLANNED"}


def test_candidate_pagination_reaches_page_after_500(runtime_env, monkeypatch):
    decision, trade = _setup(runtime_env)
    calls = []

    def paged(*, security_code, limit, offset, **kwargs):
        calls.append(offset)
        if offset == 0:
            return [{} for _ in range(500)]
        if offset == 500:
            return [decision]
        return []

    monkeypatch.setattr(runtime.frozen_decision_service, "list_decisions", paged)
    scan = runtime.scan_candidates(trade["trade_id"])
    assert calls == [0, 500]
    assert scan["scan_state"] == "INVALID_WITNESS"
    assert scan["candidates"] == []
    assert "FROZEN_DECISION_WITNESS_INVALID" in scan["reason_codes"]


def test_exact_trade_lookup_survives_more_than_500_other_attributions(runtime_env):
    decision, trade = _setup(runtime_env)
    runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    db_path = attribution_store.resolve_formal_trade_attribution_db_path()
    for index in range(500):
        other_trade = dict(trade, trade_id=f"{index + 1:032x}")
        record = fta.create_attribution(
            decision,
            other_trade,
            attribution_id="trade_attribution_" + f"{index + 1:032x}",
            created_at="2026-08-17T00:00:00.000000Z",
        ).to_dict()
        attribution_store.write_attribution(db_path=db_path, record=record)
    result = runtime.reconciliation_for_trade(trade["trade_id"])
    assert result["allocation_state"] == "ALLOCATED"
    assert result["reconciliation_requirement"] == "NOT_REQUIRED"
    assert result["decision_id"] == decision["decision_id"]


def _resolution_process(kind, trade_id, decision_id, pipe, pause_trade_read=False):
    """Real spawned worker; pause after its opposing-authority read, before write."""
    store = origin_store if kind == "attribution" else attribution_store
    name = "get_for_trade" if kind == "attribution" else "get_attribution_for_trade"
    original = getattr(store, name)

    def paused_read(**kwargs):
        result = original(**kwargs)
        if result is None:
            pipe.send("checked_absent")
            if not pipe.poll(10):
                raise TimeoutError("parent did not release paused authority read")
            assert pipe.recv() == "release"
        return result

    setattr(store, name, paused_read)
    if pause_trade_read:
        original_trade = runtime._trade
        initial_read = True

        def paused_trade_read(trade_id):
            nonlocal initial_read
            result = original_trade(trade_id)
            if initial_read:
                initial_read = False
                pipe.send("trade_read")
                if not pipe.poll(10):
                    raise TimeoutError("parent did not release initial trade read")
                assert pipe.recv() == "release"
            return result

        runtime._trade = paused_trade_read
    pipe.send("started")
    try:
        if kind == "attribution":
            runtime.attribute(trade_id, {"decision_id": decision_id})
        else:
            runtime.mark_unplanned(trade_id, {"confirm": True})
        pipe.send("success")
    except runtime.TradeAttributionConflictError:
        pipe.send("conflict")
    except Exception as exc:
        pipe.send((type(exc).__name__, str(exc)))
    finally:
        pipe.close()


@pytest.mark.parametrize("first_kind", ["attribution", "unplanned"])
def test_cross_process_resolution_has_one_winner(runtime_env, first_kind):
    import multiprocessing

    decision, trade = _setup(runtime_env)
    context = multiprocessing.get_context("spawn")
    processes, pipes = [], []

    def receive(pipe):
        assert pipe.poll(10), "resolution worker timed out"
        return pipe.recv()

    def start(kind):
        parent, child = context.Pipe()
        process = context.Process(
            target=_resolution_process,
            args=(kind, trade["trade_id"], decision["decision_id"], child),
        )
        process.start()
        child.close()
        processes.append(process)
        pipes.append(parent)
        assert receive(parent) == "started"
        return parent

    try:
        first = start(first_kind)
        assert receive(first) == "checked_absent"
        second = start("unplanned" if first_kind == "attribution" else "attribution")
        # The first process deliberately holds the critical section. On the old
        # thread-only lock, the second also observes absence and can write.
        second_passed_guard = second.poll(1)
        if second_passed_guard:
            assert second.recv() == "checked_absent"
        first.send("release")
        assert receive(first) == "success"
        if second_passed_guard:
            second.send("release")
        second_result = receive(second)
        assert second_result == "conflict"
        assert not second_passed_guard
        assert runtime.reconciliation_for_trade(trade["trade_id"])["allocation_state"] in {"ALLOCATED", "UNPLANNED"}
    finally:
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
        for pipe in pipes:
            pipe.close()


def test_resolution_lock_failure_writes_neither_authority(runtime_env, monkeypatch):
    import sqlite3

    decision, trade = _setup(runtime_env)
    blocker = sqlite3.connect(trade_ledger_service.resolve_db_path())
    blocker.execute("BEGIN IMMEDIATE")
    original_connect = sqlite3.connect

    def short_timeout(*args, **kwargs):
        kwargs["timeout"] = 0.01
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(runtime.sqlite3, "connect", short_timeout)
    try:
        with pytest.raises(runtime.TradeAttributionRuntimeError, match="写入锁不可用"):
            runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
        with pytest.raises(runtime.TradeAttributionRuntimeError, match="写入锁不可用"):
            runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
        assert not attribution_store.resolve_formal_trade_attribution_db_path().exists()
        assert not origin_store.resolve_db_path().exists()
    finally:
        blocker.close()
    assert runtime.mark_unplanned(trade["trade_id"], {"confirm": True})["idempotent"] is False


def test_resolution_store_failure_releases_guard(runtime_env, monkeypatch):
    decision, trade = _setup(runtime_env)

    def fail_write(**kwargs):
        raise attribution_store.FormalTradeAttributionStoreCorruptedError()

    monkeypatch.setattr(attribution_store, "write_attribution", fail_write)
    with pytest.raises(attribution_store.FormalTradeAttributionStoreCorruptedError):
        runtime.attribute(trade["trade_id"], {"decision_id": decision["decision_id"]})
    assert runtime.mark_unplanned(trade["trade_id"], {"confirm": True})["idempotent"] is False
    assert runtime.mark_unplanned(trade["trade_id"], {"confirm": True})["idempotent"] is True


def test_terminated_resolution_process_releases_guard(runtime_env):
    import multiprocessing

    decision, trade = _setup(runtime_env)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_resolution_process,
        args=("attribution", trade["trade_id"], decision["decision_id"], child),
    )
    process.start()
    child.close()
    try:
        assert parent.poll(10)
        assert parent.recv() == "started"
        assert parent.poll(10)
        assert parent.recv() == "checked_absent"
        process.terminate()
        process.join(10)
        assert not process.is_alive()
        result = runtime.mark_unplanned(trade["trade_id"], {"confirm": True})
        assert result["idempotent"] is False
        assert runtime.reconciliation_for_trade(trade["trade_id"])["allocation_state"] == "UNPLANNED"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()


@pytest.mark.parametrize("kind", ["attribution", "unplanned"])
def test_trade_voided_after_initial_read_cannot_resolve(runtime_env, kind):
    import multiprocessing
    import trade_ledger_store

    decision, trade = _setup(runtime_env)
    conn = trade_ledger_store.open_write_connection(trade_ledger_service.resolve_db_path())
    conn.execute("BEGIN IMMEDIATE")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_resolution_process,
        args=(kind, trade["trade_id"], decision["decision_id"], child, True),
    )
    process.start()
    child.close()
    try:
        assert parent.poll(10)
        assert parent.recv() == "started"
        assert parent.poll(10)
        assert parent.recv() == "trade_read"
        # Worker holds the pre-void snapshot. The SQLite reservation prevents
        # it from resolving until this concurrent void has committed.
        parent.send("release")
        trade_ledger_store.void_trade_on_connection(
            conn, trade["trade_id"], "2098-01-02T00:00:00.000000Z", "synthetic race"
        )
        conn.commit()
        assert parent.poll(10)
        assert parent.recv() == "conflict"
        assert not attribution_store.resolve_formal_trade_attribution_db_path().exists()
        assert not origin_store.resolve_db_path().exists()
    finally:
        conn.close()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()


def test_resolution_guard_does_not_create_missing_trade_ledger(runtime_env):
    path = trade_ledger_service.resolve_db_path()
    assert not path.exists()
    with pytest.raises(runtime.TradeAttributionRuntimeError, match="写入锁不可用"):
        with runtime._resolution_write_guard("a" * 32):
            pytest.fail("missing ledger must fail before the critical section")
    assert not path.exists()
