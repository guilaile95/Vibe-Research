from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

import decision_challenge_projection as challenge_domain
import decision_challenge_runtime as challenge_runtime
import decision_challenge_store as challenge_store
import formal_decision_outcome as domain
import formal_decision_outcome_runtime as runtime
import formal_trade_attribution_store as attribution_store
import frozen_decision_store as fd_store
import frozen_decision_service as fd_service
import performance_attribution_service as performance_service
import trade_ledger_store
import trade_origin_store
from app import app
from test_formal_decision_outcome import _attribution, make_decision, make_trade


EVALUATION_AS_OF = "2026-09-01T00:00:00.000000Z"
BEFORE_REVIEW = "2026-08-20T00:00:00.000000Z"


def _install_env(monkeypatch, tmp_path):
    paths = {
        "VIBE_RESEARCH_FROZEN_DECISION_DB": tmp_path / "frozen.sqlite3",
        "VIBE_RESEARCH_TRADE_LEDGER_DB": tmp_path / "trades.sqlite3",
        "VIBE_RESEARCH_TRADE_ATTRIBUTION_DB": tmp_path / "attributions.sqlite3",
        "VIBE_RESEARCH_TRADE_ORIGIN_DB": tmp_path / "origins.sqlite3",
    }
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    for name, path in paths.items():
        monkeypatch.setenv(name, str(path))
    return paths


def _write_decision(path, **overrides):
    decision = make_decision(**overrides)
    return fd_store.write_frozen_decision(path, decision)


def _write_trade(path, trade):
    trade_ledger_store.insert_record(path, trade)
    return trade


def _write_attribution(path, decision, trade, attribution_id):
    record = _attribution(
        decision=decision,
        trade=trade,
        attribution_id=attribution_id,
    ).to_dict()
    attribution_store.write_attribution(db_path=path, record=record)
    return record


def _challenge_packet(decision, *, challenge_id, finalized_at):
    dimensions = {
        name: {"status": "ANSWERED", "text": f"text:{name}"}
        for name in challenge_domain.REQUIRED_DIMENSIONS
    }
    dimensions["PRE_MORTEM"] = {"status": "UNKNOWN", "text": "not enough evidence"}
    return challenge_domain.project_challenge_packet(
        challenge_id=challenge_id,
        security_code=decision["security_code"],
        strategy=decision["strategy"],
        campaign_id=decision["campaign_id"],
        thesis_id=decision["thesis_id"],
        thesis_revision=decision["thesis_revision"],
        proposal_fingerprint="a" * 64,
        proposal_as_of="2026-08-09T00:00:00.000000Z",
        finalized_at=finalized_at,
        user_dimensions=dimensions,
    )


def test_process_review_none_is_neutral_and_durable_source_ref_derived(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    result = runtime.evaluate_outcome(decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF)
    assert result["process_review"]["state"] == "NONE"
    assert result["process_review"]["challenge_id"] is None
    assert result["process_quality"]["state"] == "NOT_EVALUATED"
    assert "NO_PROCESS_QUALITY_AUTHORITY" in result["process_quality"]["reason_codes"]


def test_process_review_bound_projects_unknown_dimensions_without_hash_contamination(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    packet = _challenge_packet(
        decision,
        challenge_id="decision_challenge_" + "a" * 32,
        finalized_at="2026-08-09T00:00:01.000000Z",
    )
    challenge_store.append_challenge(
        packet, db_path=tmp_path / "decision_challenges.sqlite3"
    )
    monkeypatch.setenv("VIBE_RESEARCH_DECISION_CHALLENGE_DB", str(tmp_path / "decision_challenges.sqlite3"))
    decision["source_refs"] = [
        "decision_proposal:" + "a" * 64,
        "decision_challenge:decision_challenge_" + "a" * 32,
    ]
    result = runtime._build_process_review(decision)
    assert result["state"] == "BOUND"
    assert result["dimensions"]["PRE_MORTEM"] == {
        "status": "UNKNOWN", "text": "not enough evidence"
    }
    assert result["process_quality"]["state"] == "NOT_EVALUATED"
    assert result["two_pass_semantic_independence_verified"] == "NO"


def test_process_review_malformed_or_multiple_refs_is_error_only():
    base = make_decision(source_refs=["decision_proposal:" + "a" * 64])
    malformed = {**base, "source_refs": ["decision_challenge:not-an-id"]}
    multiple = {**base, "source_refs": [
        "decision_proposal:" + "a" * 64,
        "decision_challenge:decision_challenge_" + "a" * 32,
        "decision_challenge:decision_challenge_" + "b" * 32,
    ]}
    duplicate_proposals = {**base, "source_refs": [
        "decision_proposal:" + "a" * 64,
        "decision_proposal:" + "b" * 64,
    ]}
    assert runtime._build_process_review(malformed)["state"] == "ERROR"
    assert runtime._build_process_review(multiple)["state"] == "ERROR"
    assert runtime._build_process_review(duplicate_proposals)["state"] == "ERROR"


def test_no_actual_trade_is_still_tracked_without_zero_pnl(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])

    result = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )

    assert result["outcome_status"] == "EVALUATED"
    assert result["actual_capital_outcome"]["state"] == "NO_ACTUAL_TRADE"
    assert result["actual_capital_outcome"]["pnl"] is None
    assert result["counterfactual_outcome"]["state"] == "NOT_EVALUATED"
    assert "pnl" not in result["counterfactual_outcome"]
    assert result["process_quality"]["state"] == "NOT_EVALUATED"


def test_review_by_is_explicit_pending_boundary(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])

    result = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=BEFORE_REVIEW
    )

    assert result["outcome_status"] == "PENDING"
    assert result["due_state"] == "NOT_DUE"
    assert result["actual_capital_outcome"]["state"] == "PENDING"
    assert result["outcome_reveal"] is None


def test_committed_at_boundary_and_malformed_id_fail_closed(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])

    with pytest.raises(runtime.FormalOutcomeValidationError):
        runtime.evaluate_outcome("not-a-decision", evaluation_as_of=EVALUATION_AS_OF)
    with pytest.raises(runtime.FormalOutcomeValidationError):
        runtime.evaluate_outcome(
            decision["decision_id"], evaluation_as_of="2026-08-01T00:00:00.000000Z"
        )


def test_exact_attribution_only_includes_exact_executed_trade(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    exact_trade = _write_trade(
        paths["VIBE_RESEARCH_TRADE_LEDGER_DB"],
        make_trade(trade_id="1" * 32),
    )
    same_security_unallocated = _write_trade(
        paths["VIBE_RESEARCH_TRADE_LEDGER_DB"],
        make_trade(trade_id="2" * 32, actual_price=1510.0),
    )
    same_security_unplanned = _write_trade(
        paths["VIBE_RESEARCH_TRADE_LEDGER_DB"],
        make_trade(trade_id="3" * 32, actual_price=1520.0),
    )
    _write_attribution(
        paths["VIBE_RESEARCH_TRADE_ATTRIBUTION_DB"],
        decision,
        exact_trade,
        "trade_attribution_" + "a" * 32,
    )
    trade_origin_store.write(
        db_path=paths["VIBE_RESEARCH_TRADE_ORIGIN_DB"],
        record={
            "resolution_id": "trade_origin_" + "b" * 32,
            "trade_id": same_security_unplanned["trade_id"],
            "origin": "UNPLANNED",
            "pre_trade_decision": "NONE",
            "pre_trade_thesis": "NONE",
            "created_at": "2026-08-10T07:00:00.000000Z",
        },
    )

    result = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )

    actual = result["actual_capital_outcome"]
    assert actual["trade_ids"] == [exact_trade["trade_id"]]
    assert actual["trade_count"] == 1
    assert same_security_unallocated["trade_id"] not in actual["trade_ids"]
    assert same_security_unplanned["trade_id"] not in actual["trade_ids"]
    assert actual["pnl"] is not None
    assert actual["pnl"]["computation_fingerprint"]


def test_second_decision_cannot_steal_first_decision_trade(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    first = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    second = _write_decision(
        paths["VIBE_RESEARCH_FROZEN_DECISION_DB"],
        decision_id="decision_" + "b" * 32,
    )
    trade = _write_trade(paths["VIBE_RESEARCH_TRADE_LEDGER_DB"], make_trade())
    _write_attribution(
        paths["VIBE_RESEARCH_TRADE_ATTRIBUTION_DB"],
        second,
        trade,
        "trade_attribution_" + "c" * 32,
    )

    result = runtime.evaluate_outcome(
        first["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )
    assert result["actual_capital_outcome"]["state"] == "NO_ACTUAL_TRADE"
    assert result["actual_capital_outcome"]["trade_ids"] == []


def test_voided_and_not_executed_trades_are_excluded(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    voided = _write_trade(
        paths["VIBE_RESEARCH_TRADE_LEDGER_DB"], make_trade(trade_id="4" * 32)
    )
    not_executed = _write_trade(
        paths["VIBE_RESEARCH_TRADE_LEDGER_DB"],
        make_trade(
            trade_id="5" * 32,
            execution_status="not_executed",
            executed_at=None,
            actual_quantity=0,
        ),
    )
    _write_attribution(
        paths["VIBE_RESEARCH_TRADE_ATTRIBUTION_DB"],
        decision,
        voided,
        "trade_attribution_" + "d" * 32,
    )
    _write_attribution(
        paths["VIBE_RESEARCH_TRADE_ATTRIBUTION_DB"],
        decision,
        not_executed,
        "trade_attribution_" + "e" * 32,
    )
    trade_ledger_store.void_record_atomic(
        paths["VIBE_RESEARCH_TRADE_LEDGER_DB"],
        voided["trade_id"],
        "test void",
    )

    result = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )
    assert result["actual_capital_outcome"]["state"] == "NO_ACTUAL_TRADE"
    assert result["actual_capital_outcome"]["trade_ids"] == []


def test_replay_hash_is_stable_when_later_trade_is_added(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    before = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )
    _write_trade(paths["VIBE_RESEARCH_TRADE_LEDGER_DB"], make_trade())
    after = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )

    assert before["decision_time_replay"]["replay_hash"] == after["decision_time_replay"]["replay_hash"]
    assert "actual_capital_outcome" not in before["decision_time_replay"]
    assert "outcome_reveal" not in before["decision_time_replay"]


def test_tampered_attribution_snapshot_hash_fails_closed(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    trade = _write_trade(paths["VIBE_RESEARCH_TRADE_LEDGER_DB"], make_trade())
    _write_attribution(
        paths["VIBE_RESEARCH_TRADE_ATTRIBUTION_DB"],
        decision,
        trade,
        "trade_attribution_" + "f" * 32,
    )
    conn = sqlite3.connect(paths["VIBE_RESEARCH_TRADE_ATTRIBUTION_DB"])
    conn.execute(
        "UPDATE formal_trade_attributions SET decision_snapshot_hash = ?",
        ("0" * 64,),
    )
    conn.commit()
    conn.close()

    with pytest.raises(runtime.FormalOutcomeRuntimeError):
        runtime.evaluate_outcome(
            decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
        )


def test_tampered_frozen_decision_snapshot_fails_closed(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    conn = sqlite3.connect(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    conn.execute(
        "UPDATE frozen_decisions SET snapshot_hash = ? WHERE decision_id = ?",
        ("0" * 64, decision["decision_id"]),
    )
    conn.commit()
    conn.close()

    with pytest.raises(runtime.FormalOutcomeRuntimeError):
        runtime.evaluate_outcome(
            decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
        )


def test_negative_pnl_does_not_grade_process_quality(tmp_path, monkeypatch):
    decision = make_decision()
    trade = make_trade()
    attribution = _attribution(trade=trade, decision=decision).to_dict()
    result = domain.project_ol1_outcome(
        decision,
        evaluation_as_of=EVALUATION_AS_OF,
        attributions=[attribution],
        trades=[trade],
        actual_performance={
            "authority_version": performance_service.AUTHORITY_VERSION,
            "selected_trade_ids": [trade["trade_id"]],
            "computation_fingerprint": "a" * 64,
            "positions": [{
                "closed_quantity": 0,
                "realized_pnl": -100.0,
                "unrealized_pnl": None,
                "cost_basis": 100.0,
                "total_fees": 0.0,
            }],
        },
    )
    assert result["actual_capital_outcome"]["pnl"]["realized_pnl"] == -100.0
    assert result["process_quality"]["state"] == "NOT_EVALUATED"


def test_legacy_feedback_cannot_become_formal_outcome(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    monkeypatch.setattr(
        "decision_feedback_service.list_feedbacks",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("legacy feedback read")),
    )
    result = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )
    assert result["outcome_status"] == "EVALUATED"
    assert result["actual_capital_outcome"]["state"] == "NO_ACTUAL_TRADE"


def test_list_keeps_corrupted_outcome_as_error(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    conn = sqlite3.connect(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    conn.execute(
        "UPDATE frozen_decisions SET snapshot_hash = ? WHERE decision_id = ?",
        ("1" * 64, decision["decision_id"]),
    )
    conn.commit()
    conn.close()
    with pytest.raises(runtime.FormalOutcomeRuntimeError):
        runtime.list_outcomes(evaluation_as_of=EVALUATION_AS_OF)


def test_existing_o1_projection_remains_available():
    decision = make_decision()
    result = domain.project_outcome(
        decision,
        [],
        [],
        measurement_start="2026-08-10T08:00:00.000000Z",
        measurement_end="2026-08-10T09:00:00.000000Z",
        as_of="2026-08-10T09:30:00.000000Z",
    )
    assert result.performance_evidence_state == "NOT_MEASURED"


def test_exact_pa1_trade_set_rejects_missing_ids(tmp_path):
    trade = make_trade()
    _write_trade(tmp_path / "trade.sqlite3", trade)
    result = performance_service.compute_attribution_for_trade_ids(
        [trade["trade_id"]], trade_db_path=tmp_path / "trade.sqlite3"
    )
    assert result["selected_trade_ids"] == [trade["trade_id"]]
    with pytest.raises(performance_service.PerformanceAttributionProvenanceError):
        performance_service.compute_attribution_for_trade_ids(
            ["2" * 32], trade_db_path=tmp_path / "trade.sqlite3"
        )


def test_formal_outcome_api_is_decision_id_scoped(tmp_path, monkeypatch):
    paths = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(paths["VIBE_RESEARCH_FROZEN_DECISION_DB"])
    client = TestClient(app)

    response = client.get(
        f"/api/formal-decisions/{decision['decision_id']}/outcome",
        params={"evaluation_as_of": EVALUATION_AS_OF},
    )
    assert response.status_code == 200
    assert response.json()["data"]["decision_id"] == decision["decision_id"]

    malformed = client.get(
        "/api/formal-decisions/not-a-decision/outcome",
        params={"evaluation_as_of": EVALUATION_AS_OF},
    )
    assert malformed.status_code == 422

    missing = client.get(
        "/api/formal-decisions/decision_" + "f" * 32 + "/outcome",
        params={"evaluation_as_of": EVALUATION_AS_OF},
    )
    assert missing.status_code == 404
