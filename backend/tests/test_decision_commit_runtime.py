from __future__ import annotations

from copy import deepcopy

import pytest

import campaign_critical_data_projection as critical_data_projection
import decision_commit_runtime as runtime


AS_OF = "2026-08-16T00:00:00.000000Z"
CAMPAIGN_ID = "campaign_" + "a" * 32
THESIS_ID = "b" * 32
DECISION_ID = "decision_" + "c" * 32


def _campaign() -> dict:
    return {
        "campaign_id": CAMPAIGN_ID,
        "security_code": "600519",
        "strategy": "SWING",
        "status": "ACTIVE",
    }


def _thesis(**overrides) -> dict:
    value = {
        "campaign_id": CAMPAIGN_ID,
        "thesis_id": THESIS_ID,
        "binding": {
            "thesis_revision_at_bind": 1,
            "campaign_strategy_at_bind": "SWING",
            "bound_at": "2026-08-01T00:00:00.000000Z",
        },
        "frozen_revision": 1,
        "original_snapshot": {
            "thesis": {
                "subject_type": "stock",
                "subject_id": "600519",
                "strategy": "SWING",
            }
        },
        "deltas": [],
        "effective_state": "STABLE",
        "ready": True,
        "formal_status": "READY",
    }
    value.update(overrides)
    return value


def _draft() -> dict:
    return {
        "asset_view": {"view": "ASSET", "stance": "WAIT"},
        "trade_view": {"view": "TRADE", "stance": "WAIT"},
        "portfolio_view": {"view": "PORTFOLIO", "constraint": "unknown"},
        "review_by": "2026-08-30T00:00:00.000000Z",
        "key_assumptions": ["用户明确填写的假设"],
        "event_invalidation_conditions": ["用户明确填写的失效条件"],
        "strategy_horizon": "2 至 4 周",
    }


def _critical_data(
    *,
    evaluation: str = "UNKNOWN",
    state: str = "UNKNOWN",
    authority_refs: list[str] | None = None,
    reason_codes: list[str] | None = None,
) -> dict:
    return {
        "schema_version": "campaign_critical_data.v0.1",
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": CAMPAIGN_ID,
        "as_of": AS_OF,
        "dependency_set_state": "UNKNOWN",
        "dependency_set_authority_refs": ["dda:test"],
        "required_dependency_ids": ["cap.security.price_reference"],
        "dependency_results": [{
            "dependency_id": "cap.security.price_reference",
            "state": "UNKNOWN",
            "as_of": AS_OF,
            "authority_refs": ["cap:test"],
        }],
        "critical_data_state": state,
        "critical_data_evaluation": evaluation,
        "reason_codes": reason_codes or ["TEST_CRITICAL_DATA"],
        "authority_refs": authority_refs or ["ccd:test"],
    }


def _ports(
    thesis: dict | None = None,
    frozen: list[dict] | None = None,
    critical_data_reader=None,
):
    state = {"frozen": list(frozen or []), "writes": 0}

    def frozen_reader(*, campaign_id: str, limit: int, offset: int):
        assert campaign_id == CAMPAIGN_ID
        return deepcopy(state["frozen"])

    def freeze_writer(payload):
        state["writes"] += 1
        record = {
            **payload,
            "decision_id": DECISION_ID,
            "committed_at": AS_OF,
        }
        state["frozen"].append(record)
        return deepcopy(record)

    def decision_reader(decision_id: str):
        return next(
            (deepcopy(item) for item in state["frozen"] if item.get("decision_id") == decision_id),
            None,
        )

    return runtime.RuntimePorts(
        campaign_reader=lambda _campaign_id: _campaign(),
        thesis_reader=lambda _campaign_id: deepcopy(thesis) if thesis is not None else (_ for _ in ()).throw(
            __import__("campaign_service").ThesisBindingNotFoundError()
        ),
        frozen_reader=frozen_reader,
        evidence_reader=lambda _campaign: (),
        freeze_writer=freeze_writer,
        decision_reader=decision_reader,
        critical_data_reader=critical_data_reader or (
            lambda _campaign, as_of: {**_critical_data(), "as_of": as_of}
        ),
    ), state


def test_preview_is_uncommitted_and_has_no_prior_boundary_without_fake_id():
    ports, state = _ports(_thesis())
    result = runtime.preview_decision_proposal(
        CAMPAIGN_ID,
        _draft(),
        ports=ports,
        as_of=AS_OF,
    )

    assert result["proposal"]["proposal_status"] == "UNCOMMITTED"
    assert result["proposal"]["campaign_id"] == CAMPAIGN_ID
    assert result["proposal"]["security_code"] == "600519"
    assert result["proposal"]["strategy"] == "SWING"
    assert result["authority_evaluations"]["formal_decision"]["evaluation"] == "NOT_EVALUATED"
    assert result["authority_evaluations"]["material_change"]["reason_codes"] == [
        runtime.NO_PRIOR_DECISION_BOUNDARY
    ]
    assert "decision_id" not in result["proposal"]
    assert state["writes"] == 0


@pytest.mark.parametrize(
    ("evaluation", "state"),
    [
        ("UNKNOWN", "UNKNOWN"),
        ("EVALUATED", "USABLE"),
        ("EVALUATED", "BLOCKED"),
        ("EVALUATED", "STALE"),
        ("ERROR", "UNKNOWN"),
    ],
)
def test_preview_uses_real_critical_data_in_ra1_and_response(evaluation, state):
    ports, _state = _ports(
        _thesis(),
        critical_data_reader=lambda _campaign, as_of: {
            **_critical_data(evaluation=evaluation, state=state),
            "as_of": as_of,
        },
    )

    result = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF
    )

    critical_data = result["authority_evaluations"]["critical_data"]
    assert critical_data["critical_data_evaluation"] == evaluation
    assert critical_data["critical_data_state"] == state
    assert critical_data["campaign_id"] == CAMPAIGN_ID
    assert critical_data["as_of"] == AS_OF
    assert result["decision_assurance"]["dimension_states"]["CRITICAL_DATA"] == evaluation
    assert _state["writes"] == 0


def test_critical_data_state_vocabulary_is_canonical_not_locally_redefined():
    assert tuple(critical_data_projection.CRITICAL_DATA_STATES) == (
        "USABLE", "BLOCKED", "UNKNOWN", "STALE"
    )
    assert tuple(critical_data_projection.CRITICAL_DATA_EVALUATIONS) == (
        "EVALUATED", "UNKNOWN", "NOT_EVALUATED", "ERROR"
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [("BLOCKED", "STALE"), ("STALE", "BLOCKED")],
)
def test_critical_data_state_change_stales_commit_before_any_frozen_write(before, after):
    current = {"value": _critical_data(evaluation="EVALUATED", state=before)}
    ports, state = _ports(
        _thesis(),
        critical_data_reader=lambda _campaign, as_of: {
            **current["value"],
            "as_of": as_of,
        },
    )
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    current["value"] = _critical_data(evaluation="EVALUATED", state=after)
    commit = {
        **_draft(),
        "as_of": AS_OF,
        "expected_proposal_fingerprint": preview["proposal_fingerprint"],
        "user_confirmed": True,
    }

    with pytest.raises(runtime.ProposalStaleError):
        runtime.commit_decision_proposal(CAMPAIGN_ID, commit, ports=ports)
    assert state["writes"] == 0


def test_critical_data_authority_refs_change_stales_commit_before_any_frozen_write():
    current = {"value": _critical_data()}
    ports, state = _ports(
        _thesis(),
        critical_data_reader=lambda _campaign, as_of: {
            **current["value"],
            "as_of": as_of,
        },
    )
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    current["value"] = _critical_data(authority_refs=["ccd:changed"])
    commit = {
        **_draft(),
        "as_of": AS_OF,
        "expected_proposal_fingerprint": preview["proposal_fingerprint"],
        "user_confirmed": True,
    }

    with pytest.raises(runtime.ProposalStaleError):
        runtime.commit_decision_proposal(CAMPAIGN_ID, commit, ports=ports)
    assert state["writes"] == 0


def test_commit_requires_strict_confirmation_and_reuses_frozen_service_port():
    ports, state = _ports(_thesis())
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    commit = {
        **_draft(),
        "as_of": AS_OF,
        "expected_proposal_fingerprint": preview["proposal_fingerprint"],
        "user_confirmed": True,
    }

    result = runtime.commit_decision_proposal(CAMPAIGN_ID, commit, ports=ports)

    assert result["committed"]["decision_id"] == DECISION_ID
    assert result["committed"]["source_refs"] == [
        f"{runtime.PROPOSAL_SOURCE_PREFIX}{preview['proposal_fingerprint']}",
        *preview["proposal"]["authority_refs"],
    ]
    assert result["formal_decision"]["evaluation"] == "EVALUATED"
    assert state["writes"] == 1

    repeat = runtime.commit_decision_proposal(CAMPAIGN_ID, commit, ports=ports)
    assert repeat["idempotent"] is True
    assert repeat["committed"]["decision_id"] == DECISION_ID
    assert state["writes"] == 1

    commit["user_confirmed"] = False
    with pytest.raises(runtime.CommitConfirmationRequiredError):
        runtime.commit_decision_proposal(CAMPAIGN_ID, commit, ports=ports)


def test_idempotent_replay_revalidates_original_authority_graph():
    thesis = _thesis()
    ports, state = _ports(thesis)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    commit = {
        **_draft(),
        "as_of": AS_OF,
        "expected_proposal_fingerprint": preview["proposal_fingerprint"],
        "user_confirmed": True,
    }
    runtime.commit_decision_proposal(CAMPAIGN_ID, commit, ports=ports)

    # The existing marker alone is not enough.  A changed Current Thesis must
    # fail closed even though the retry points at the same decision marker.
    thesis["effective_state"] = "WEAKENED"
    thesis["deltas"] = [{
        "delta_id": "d" * 32,
        "delta_sequence": 1,
        "delta_state": "WEAKENED",
        "reason": "changed after first preview",
        "confirmed_at": "2026-08-12T00:00:00.000000Z",
        "evidence_snapshots": [],
    }]
    with pytest.raises(runtime.ProposalStaleError):
        runtime.commit_decision_proposal(CAMPAIGN_ID, commit, ports=ports)
    assert state["writes"] == 1


def test_changed_user_view_or_thesis_revision_requires_repreview():
    ports, _state = _ports(_thesis())
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    changed = _draft()
    changed["trade_view"] = {"view": "TRADE", "stance": "REDUCE"}
    changed.update(
        {
            "as_of": AS_OF,
            "expected_proposal_fingerprint": preview["proposal_fingerprint"],
            "user_confirmed": True,
        }
    )
    with pytest.raises(runtime.ProposalStaleError):
        runtime.commit_decision_proposal(CAMPAIGN_ID, changed, ports=ports)

    mismatched = _thesis()
    mismatched["original_snapshot"]["thesis"]["subject_id"] = "000001"
    bad_ports, _ = _ports(mismatched)
    with pytest.raises(runtime.CurrentThesisUnavailableError):
        runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=bad_ports, as_of=AS_OF)


def test_existing_frozen_boundary_drives_material_projection_and_formal_readback():
    existing = {
        "decision_id": DECISION_ID,
        "committed_at": "2026-08-10T00:00:00.000000Z",
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": CAMPAIGN_ID,
        "thesis_id": THESIS_ID,
        "thesis_revision": 1,
        "review_by": "2026-08-30T00:00:00.000000Z",
        "next_best_action": "WAIT",
        "source_refs": ["previous:decision"],
    }
    ports, _state = _ports(_thesis(), [existing])
    result = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)

    material = result["authority_evaluations"]["material_change"]
    assert material["decision_id"] == DECISION_ID
    assert material["decision_boundary_at"] == existing["committed_at"]
    assert result["authority_evaluations"]["formal_decision"]["evaluation"] == "EVALUATED"
