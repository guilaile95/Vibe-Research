from __future__ import annotations

from copy import deepcopy

import pytest

import candidate_opportunity_projection as candidate
import decision_commit_runtime as runtime
import decision_inbox_runtime_assembler as inbox_runtime
from hard_risk_contract import HardRiskEvaluation


AS_OF = "2026-08-16T00:00:00.000000Z"
CAMPAIGN_ID = "campaign_" + "a" * 32
THESIS_ID = "b" * 32
DECISION_ID = "decision_" + "c" * 32


def _support_evidence() -> dict:
    return {
        "evidence_id": "e" * 32,
        "evidence_type": "financial",
        "stance": "support",
        "claim": "用户确认的支持事实",
        "classification": "fact",
        "confidence": "high",
        "source_title": "公开财报",
        "source_url": None,
        "source_date": "2026-08-15",
        "accessed_at": "2026-08-15T00:00:00+00:00",
    }


def _case(low: float, high: float) -> dict:
    return {
        "assumptions": ["用户确认的核心假设"],
        "inputs": [{"metric": "forward_profit", "value": 100, "period": "FY2027"}],
        "source": "用户确认的公开财报",
        "data_at": "2026-08-15",
        "price_range": {"low": low, "high": high},
        "horizon": "12 months",
        "change_conditions": ["下一期利润事实改变"],
    }


def _asset(confidence: str = "HIGH") -> dict:
    return {
        "view": "ASSET",
        "stance": "SUPPORT",
        "candidate_valuation": {
            "bear": _case(85, 90),
            "base": _case(130, 135),
            "bull": _case(160, 170),
        },
        "data_quality": confidence,
        "evidence_confidence": confidence,
        "inference_confidence": confidence,
        "decision_confidence": confidence,
    }


def _trade() -> dict:
    return {
        "view": "TRADE",
        "stance": "SUPPORT",
        "entry_range": {"low": 100, "high": 102},
        "invalidation_price": 90,
    }


def _critical(state: str = "USABLE", evaluation: str = "EVALUATED") -> dict:
    return {
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": CAMPAIGN_ID,
        "as_of": AS_OF,
        "critical_data_state": state,
        "critical_data_evaluation": evaluation,
        "authority_refs": ["critical-data:test"],
    }


def _project(**overrides):
    values = {
        "security_code": "600519",
        "strategy": "SWING",
        "as_of": AS_OF,
        "asset_view": _asset(),
        "trade_view": _trade(),
        "portfolio_view": {"view": "PORTFOLIO"},
        "hard_risk_state": "CLEAR",
        "hard_risk_evaluation": "EVALUATED",
        "hard_risk_refs": ("hard-risk:test",),
        "critical_data": _critical(),
        "evidence_links": [_support_evidence()],
        "position_snapshot": {"authority_state": "CANONICAL", "holdings": []},
        "account_reality": {
            "canonical": True,
            "confidence": "HIGH",
            "settled_nav": 1_000_000,
            "cash": {"current_fact": {"status": "AVAILABLE", "value": 200_000}},
            "positions": [],
        },
    }
    values.update(overrides)
    return candidate.project_candidate_opportunity(**values)


def test_candidate_missing_valuation_fails_closed_without_target_or_position():
    result = _project(asset_view={"view": "ASSET", "stance": "SUPPORT"})

    assert result.next_best_action == "RESEARCH MORE"
    assert result.authority_fact["valuation_status"] == "UNKNOWN"
    assert result.asset_view["candidate_valuation"] == {"status": "UNKNOWN", "cases": {}}
    assert result.portfolio_view["risk_cap"]["max_position_value"] is None
    assert "BUY NOW" in result.action_envelope["blocked_actions"]
    assert "SCALE IN" in result.action_envelope["blocked_actions"]


def test_formal_evidence_not_self_reported_confidence_controls_buy_gate():
    empty = _project(evidence_links=[])
    opposed = {
        **_support_evidence(),
        "evidence_id": "f" * 32,
        "stance": "oppose",
    }
    conflict = _project(evidence_links=[_support_evidence(), opposed])
    sufficient = _project(
        hard_risk_state="UNKNOWN",
        hard_risk_evaluation="UNKNOWN",
        hard_risk_refs=(),
    )

    assert empty.next_best_action == "RESEARCH MORE"
    assert "FORMAL_EVIDENCE_SUPPORTING_FACT_MISSING" in empty.authority_fact["reason_codes"]
    assert conflict.next_best_action == "WAIT"
    assert "FORMAL_EVIDENCE_OPPOSING_HIGH_CONFLICT" in conflict.authority_fact["reason_codes"]
    assert sufficient.next_best_action == "BUY SMALL"
    assert sufficient.authority_fact["evidence_refs"] == ["e" * 32]


def test_valid_candidate_computes_bounded_buy_and_low_confidence_caps_action():
    high = _project()
    low = _project(asset_view=_asset("LOW"))

    assert high.next_best_action == "BUY NOW"
    assert high.authority_fact["risk_reward"]["ratio"] >= 2
    assert high.authority_fact["risk_cap"]["max_shares"] == 800
    assert high.authority_fact["risk_cap"]["max_position_value"] == 81_600
    assert high.authority_fact["account_canonical"] is True
    assert high.authority_fact["risk_cap"]["status"] == "AVAILABLE"
    assert low.next_best_action == "BUY SMALL"
    assert "BUY NOW" in low.action_envelope["blocked_actions"]
    assert "SCALE IN" in low.action_envelope["blocked_actions"]


def test_candidate_hard_risk_and_unknown_account_never_open_positive_action():
    hard = _project(hard_risk_state="CONFIRMED")
    unknown_risk = _project(
        hard_risk_state="UNKNOWN",
        hard_risk_evaluation="UNKNOWN",
        hard_risk_refs=(),
    )
    unknown_account = _project(account_reality=None)

    assert hard.next_best_action == "AVOID"
    assert candidate.BUY_ACTIONS <= set(hard.action_envelope["blocked_actions"])
    assert unknown_risk.next_best_action == "BUY SMALL"
    assert "BUY NOW" in unknown_risk.action_envelope["blocked_actions"]
    assert "SCALE IN" in unknown_risk.action_envelope["blocked_actions"]
    assert unknown_account.next_best_action == "WAIT"
    assert unknown_account.portfolio_view["account_state"] == "UNKNOWN"
    assert unknown_account.portfolio_view["risk_cap"]["max_position_value"] is None


def _incumbent_context(*, thesis: str = "STABLE", hard: str = "CLEAR", material: str = "NONE") -> dict:
    return {
        "evaluation_status": "EVALUATED",
        "canonical": True,
        "reason_codes": [],
        "holding_setup_items": [],
        "campaign_items": [{
            "security_code": "000001",
            "strategy": "SWING",
            "campaign_id": "campaign_" + "d" * 32,
            "campaign_status": "ACTIVE",
            "current_thesis_state": thesis,
            "thesis_identity": {
                "thesis_id": "e" * 32,
                "frozen_revision": 1,
                "effective_state": thesis,
                "deltas": [],
            },
            "last_frozen_decision": {
                "frozen_decision_ref": "decision_" + "f" * 32 + ":snapshot-test",
                "review_by": "2026-09-30T00:00:00.000000Z",
            },
            "hard_risk_state": hard,
            "material_change_state": material,
            "sell_state": None,
            "reason_codes": [],
        }],
        "authority_refs": ["incumbent:test"],
    }


def _constrained_account(*, incumbent_shares: int | None = None) -> dict:
    return {
        "canonical": True,
        "confidence": "HIGH",
        "settled_nav": 1_000_000,
        "cash": {"current_fact": {"status": "AVAILABLE", "value": 50_000}},
        "positions": (
            [{"code": "000001", "shares": incumbent_shares}]
            if incumbent_shares is not None
            else []
        ),
    }


def test_capital_context_a_to_e_is_fail_closed_and_never_auto_replaces():
    available = _project()
    available_context = available.portfolio_view["portfolio_capital_context"]
    assert available_context["capital_availability"]["state"] == "AVAILABLE"
    assert available_context["portfolio_fit"]["state"] == "SUPPORTIVE"
    assert available_context["replacement_review"]["state"] == "NOT_REQUIRED"

    constrained = _project(
        account_reality=_constrained_account(incumbent_shares=1000),
        position_snapshot={
            "authority_state": "CANONICAL",
            "holdings": [{"code": "000001", "shares": 1000}],
        },
        incumbent_context=_incumbent_context(),
    )
    constrained_context = constrained.portfolio_view["portfolio_capital_context"]
    assert constrained_context["capital_availability"]["state"] == "CONSTRAINED"
    assert constrained_context["portfolio_fit"]["state"] == "CONSTRAINED"
    assert constrained_context["replacement_review"]["state"] == "NOT_PROVEN"
    assert constrained.next_best_action == "BUY SMALL"
    assert "BUY NOW" in constrained.action_envelope["blocked_actions"]
    assert "SCALE IN" in constrained.action_envelope["blocked_actions"]

    unknown = _project(account_reality=None)
    unknown_context = unknown.portfolio_view["portfolio_capital_context"]
    assert unknown_context["capital_availability"]["state"] == "UNKNOWN"
    assert unknown_context["capital_availability"]["confirmed_cash"] is None
    assert unknown_context["portfolio_fit"]["state"] == "UNKNOWN"
    assert unknown_context["replacement_review"]["state"] == "UNKNOWN"
    assert candidate.BUY_ACTIONS <= set(unknown.action_envelope["blocked_actions"])

    review = _project(
        account_reality=_constrained_account(incumbent_shares=1000),
        position_snapshot={
            "authority_state": "CANONICAL",
            "holdings": [{"code": "000001", "shares": 1000}],
        },
        incumbent_context=_incumbent_context(thesis="WEAKENED"),
    )
    review_context = review.portfolio_view["portfolio_capital_context"]
    assert review_context["replacement_review"]["state"] == "WORTH_REVIEW"
    assert review_context["replacement_review"]["candidates"][0]["reason_codes"] == [
        "INCUMBENT_THESIS_WEAKENED"
    ]
    assert not ({"REDUCE", "EXIT"} & set(review.action_envelope["allowed_actions"]))

    unqualified = _project(
        evidence_links=[],
        account_reality=_constrained_account(incumbent_shares=1000),
        position_snapshot={
            "authority_state": "CANONICAL",
            "holdings": [{"code": "000001", "shares": 1000}],
        },
        incumbent_context=_incumbent_context(thesis="WEAKENED"),
    )
    unqualified_review = unqualified.portfolio_view["portfolio_capital_context"]["replacement_review"]
    assert unqualified_review["state"] == "NOT_PROVEN"
    assert unqualified_review["candidates"] == []
    assert unqualified_review["reason_codes"] == [
        "CANDIDATE_REPLACEMENT_ELIGIBILITY_NOT_PROVEN"
    ]


def test_noncanonical_account_is_unknown_not_confirmed_capital():
    result = _project(
        account_reality={
            "canonical": False,
            "confidence": "MEDIUM",
            "settled_nav": 1_000_000,
            "cash": {"current_fact": {"status": "AVAILABLE", "value": 200_000}},
            "positions": [],
        }
    )
    context = result.portfolio_view["portfolio_capital_context"]
    assert context["capital_availability"]["state"] == "UNKNOWN"
    assert context["capital_availability"]["confirmed_cash"] is None
    assert candidate.BUY_ACTIONS <= set(result.action_envelope["blocked_actions"])


def test_existing_portfolio_without_exposure_authority_keeps_fit_unknown():
    result = _project(
        account_reality={
            "canonical": True,
            "confidence": "HIGH",
            "settled_nav": 1_000_000,
            "cash": {"current_fact": {"status": "AVAILABLE", "value": 200_000}},
            "positions": [{"code": "000001", "shares": 1000}],
        },
        position_snapshot={
            "authority_state": "CANONICAL",
            "holdings": [{"code": "000001", "shares": 1000}],
        },
        incumbent_context=_incumbent_context(),
    )
    context = result.portfolio_view["portfolio_capital_context"]
    assert context["capital_availability"]["state"] == "AVAILABLE"
    assert context["portfolio_fit"] == {
        "state": "UNKNOWN",
        "existing_position_count": 1,
        "reason_codes": ["PORTFOLIO_EXPOSURE_NOT_PROVEN"],
    }
    assert candidate.BUY_ACTIONS <= set(result.action_envelope["blocked_actions"])


def test_legacy_empty_portfolio_is_unknown_not_not_held():
    legacy = _project(position_snapshot={"authority_state": "LEGACY"})
    canonical = _project(
        position_snapshot={"authority_state": "CANONICAL", "holdings": []}
    )

    assert legacy.authority_fact["position_state"] == "UNKNOWN"
    assert legacy.next_best_action == "WAIT"
    assert candidate.BUY_ACTIONS <= set(legacy.action_envelope["blocked_actions"])
    assert canonical.authority_fact["position_state"] == "NOT_HELD"
    assert canonical.next_best_action == "BUY NOW"


def test_production_position_reader_preserves_authority_state(monkeypatch):
    monkeypatch.setattr(runtime.position_reality_service, "get_holding_authority_state", lambda: "LEGACY")
    monkeypatch.setattr(
        runtime.position_reality_service,
        "read_current_holdings_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("legacy snapshot must not be treated as canonical")),
    )
    assert runtime._production_position_reader() == {"authority_state": "LEGACY"}

    monkeypatch.setattr(runtime.position_reality_service, "get_holding_authority_state", lambda: "CANONICAL")
    monkeypatch.setattr(
        runtime.position_reality_service,
        "read_current_holdings_snapshot",
        lambda: {"holdings": []},
    )
    assert runtime._production_position_reader() == {
        "authority_state": "CANONICAL",
        "holdings": [],
    }


def test_production_incumbent_reader_reuses_named_authorities(monkeypatch):
    incumbent_id = "campaign_" + "d" * 32
    decision_id = "decision_" + "f" * 32
    monkeypatch.setattr(
        inbox_runtime,
        "assemble_current_decision_inbox",
        lambda **_kwargs: {
            "evaluation_status": "EVALUATED",
            "canonical": True,
            "reason_codes": [],
            "holding_setup_items": [],
            "campaign_items": [{
                "security_code": "000001",
                "strategy": "SWING",
                "campaign_id": incumbent_id,
                "campaign_status": "ACTIVE",
                "current_thesis": {"current_thesis": "WEAKENED"},
                "last_frozen_decision": {
                    "decision_id": decision_id,
                    "committed_at": "2026-08-01T00:00:00.000000Z",
                    "review_by": "2026-09-01T00:00:00.000000Z",
                    "previous_next_best_action": "HOLD",
                },
                "hard_risk_state": "CLEAR",
                "hard_risk_reason_codes": [],
                "hard_risk_authority_refs": ["hard-risk:incumbent"],
                "material_change_state": "MATERIAL",
                "material_change_reason_codes": ["THESIS_WEAKENED"],
                "sell_engine": {"sell_state": "WATCH_TO_REDUCE"},
                "reason_codes": ["THESIS_WEAKENED"],
            }],
        },
    )
    monkeypatch.setattr(
        runtime.formal_thesis_projection,
        "project_current_thesis",
        lambda _campaign_id: {
            "campaign_id": incumbent_id,
            "thesis_id": "e" * 32,
            "frozen_revision": 1,
            "formal_status": "READY",
            "effective_state": "WEAKENED",
            "deltas": [{
                "delta_id": "1" * 32,
                "delta_sequence": 1,
                "delta_state": "WEAKENED",
                "confirmed_at": "2026-08-15T00:00:00.000000Z",
                "evidence_links": [{"evidence_id": "2" * 32}],
            }],
        },
    )
    monkeypatch.setattr(
        runtime.frozen_decision_service,
        "get_decision",
        lambda _decision_id: {
            "campaign_id": incumbent_id,
            "snapshot_hash": "a" * 64,
        },
    )

    result = runtime._production_incumbent_reader(AS_OF)

    item = result["campaign_items"][0]
    assert item["current_thesis_state"] == "WEAKENED"
    assert item["thesis_identity"]["deltas"][0]["evidence_ids"] == ["2" * 32]
    assert item["last_frozen_decision"]["frozen_decision_ref"] == f"{decision_id}:{'a' * 64}"
    assert "hard-risk:incumbent" in result["authority_refs"]
    assert f"frozen_decision:{decision_id}:{'a' * 64}" in result["authority_refs"]


@pytest.mark.parametrize("strategy", ["SHORT", "SWING", "MEDIUM"])
def test_strategy_specific_risk_reward_gate(strategy):
    gate = candidate.RISK_REWARD_GATE[strategy]

    def asset_for_ratio(ratio: float) -> dict:
        value = _asset()
        base_mid = 101 + 11 * ratio
        value["candidate_valuation"]["base"] = _case(base_mid, base_mid)
        return value

    below = _project(strategy=strategy, asset_view=asset_for_ratio(gate - 0.01))
    at_gate = _project(strategy=strategy, asset_view=asset_for_ratio(gate))

    assert below.next_best_action == "WAIT"
    assert at_gate.next_best_action == "BUY NOW"


def _thesis() -> dict:
    return {
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
            },
            "evidence_links": [_support_evidence()],
        },
        "deltas": [],
        "effective_state": "STABLE",
        "ready": True,
        "formal_status": "READY",
    }


def _draft() -> dict:
    return {
        "asset_view": _asset(),
        "trade_view": _trade(),
        "portfolio_view": {"view": "PORTFOLIO"},
        "review_by": "2026-08-30T00:00:00.000000Z",
        "key_assumptions": ["用户确认的假设"],
        "event_invalidation_conditions": ["用户确认的失效条件"],
        "strategy_horizon": "12 months",
    }


def _ports(thesis: dict | None = None):
    state = {
        "frozen": [],
        "writes": 0,
        "position": {"authority_state": "CANONICAL", "holdings": []},
        "account": {
            "canonical": True,
            "confidence": "HIGH",
            "settled_nav": 1_000_000,
            "cash": {"current_fact": {"status": "AVAILABLE", "value": 200_000}},
            "positions": [],
        },
        "incumbents": _incumbent_context(),
    }
    thesis_source = thesis if thesis is not None else _thesis()

    def frozen_reader(**_kwargs):
        return deepcopy(state["frozen"])

    def freeze_writer(payload):
        state["writes"] += 1
        record = {**payload, "decision_id": DECISION_ID, "committed_at": AS_OF}
        state["frozen"].append(record)
        return deepcopy(record)

    def freeze_validated(payload, *, pre_write_validator=None):
        if pre_write_validator is not None:
            pre_write_validator(payload, AS_OF)
        return freeze_writer(payload)

    return runtime.RuntimePorts(
        campaign_reader=lambda _campaign_id: {
            "campaign_id": CAMPAIGN_ID,
            "security_code": "600519",
            "strategy": "SWING",
            "status": "PRE-ENTRY",
        },
        thesis_reader=lambda _campaign_id: deepcopy(thesis_source),
        frozen_reader=frozen_reader,
        evidence_reader=lambda _campaign: (),
        freeze_writer=freeze_writer,
        freeze_writer_with_pre_write_validation=freeze_validated,
        decision_reader=lambda decision_id: next(
            (deepcopy(item) for item in state["frozen"] if item["decision_id"] == decision_id),
            None,
        ),
        critical_data_reader=lambda _campaign, as_of: {**_critical(), "as_of": as_of},
        position_reader=lambda: deepcopy(state["position"]),
        account_reader=lambda: deepcopy(state["account"]),
        incumbent_reader=lambda _as_of: deepcopy(state["incumbents"]),
    ), state


def _clear_hard_risk(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "_hard_risk_for_snapshot",
        lambda campaign, as_of, _thesis: HardRiskEvaluation(
            security_code=campaign["security_code"],
            strategy=campaign["strategy"],
            campaign_id=campaign["campaign_id"],
            as_of=as_of,
            hard_risk_state="CLEAR",
            hard_risk_evaluation="EVALUATED",
            reason_codes=(),
            authority_refs=("hard-risk:test",),
        ),
    )


def test_pre_entry_buy_requires_challenge_and_freezes_candidate_policy(monkeypatch):
    ports, state = _ports()
    _clear_hard_risk(monkeypatch)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF
    )
    commit = {
        **_draft(),
        "as_of": AS_OF,
        "expected_proposal_fingerprint": preview["proposal_fingerprint"],
        "user_confirmed": True,
    }

    assert preview["proposal"]["next_best_action"] == "BUY NOW"
    assert preview["commit_requirements"]["challenge_required"] is True
    with pytest.raises(runtime.ChallengeBindingError):
        runtime.commit_decision_proposal(CAMPAIGN_ID, commit, ports=ports)
    assert state["writes"] == 0

    monkeypatch.setattr(runtime, "_bind_challenge_packet", lambda **_kwargs: {"status": "BOUND"})
    result = runtime.commit_decision_proposal(
        CAMPAIGN_ID, {**commit, "challenge_id": "challenge_test"}, ports=ports
    )
    frozen = result["committed"]
    assert frozen["risk_policy_version"] == candidate.RISK_POLICY_VERSION
    assert frozen["opportunity_policy_version"] == candidate.OPPORTUNITY_POLICY_VERSION
    assert frozen["decision_policy_version"] == candidate.DECISION_POLICY_VERSION
    assert frozen["decision_confidence"] == "HIGH"
    assert frozen["evidence_refs"] == ["e" * 32]
    assert frozen["asset_view"]["analysis_metadata"]["analysis_policy_version"] == candidate.ANALYSIS_POLICY_VERSION
    assert frozen["portfolio_view"]["portfolio_capital_context"]["capital_availability"]["state"] == "AVAILABLE"
    assert frozen["portfolio_view"]["portfolio_capital_context"]["replacement_review"]["state"] == "NOT_REQUIRED"
    assert state["writes"] == 1


@pytest.mark.parametrize("changed", ["account", "position", "position_cost", "incumbent"])
def test_cap1_authority_change_stales_preview_before_freeze(monkeypatch, changed):
    ports, state = _ports()
    state["account"] = _constrained_account(incumbent_shares=1000)
    state["position"] = {
        "authority_state": "CANONICAL",
        "holdings": [{"code": "000001", "shares": 1000, "cost": 10.0, "cost_known": True}],
    }
    _clear_hard_risk(monkeypatch)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF
    )
    assert preview["proposal"]["next_best_action"] == "BUY SMALL"

    if changed == "account":
        state["account"]["cash"]["current_fact"]["value"] = 40_000
    elif changed == "position":
        state["position"]["holdings"][0]["shares"] = 900
    elif changed == "position_cost":
        state["position"]["holdings"][0]["cost"] = 11.0
    else:
        state["incumbents"]["campaign_items"][0]["thesis_identity"]["deltas"] = [
            {"delta_id": "1" * 32, "delta_sequence": 1, "delta_state": "STABLE"}
        ]

    with pytest.raises(runtime.ProposalStaleError):
        runtime.commit_decision_proposal(
            CAMPAIGN_ID,
            {
                **_draft(),
                "as_of": AS_OF,
                "expected_proposal_fingerprint": preview["proposal_fingerprint"],
                "user_confirmed": True,
            },
            ports=ports,
        )
    assert state["writes"] == 0


def test_cap1_account_retrieval_clock_is_not_a_false_stale_signal(monkeypatch):
    ports, state = _ports()
    state["account"]["as_of"] = "2026-08-16T00:00:01.000000Z"
    _clear_hard_risk(monkeypatch)
    before = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF
    )
    state["account"]["as_of"] = "2026-08-16T00:00:02.000000Z"
    after = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF
    )
    assert after["proposal_fingerprint"] == before["proposal_fingerprint"]


def test_current_thesis_delta_evidence_conflict_changes_fingerprint_and_freeze_refs(monkeypatch):
    thesis = _thesis()
    thesis["effective_state"] = "STRENGTHENED"
    thesis["deltas"] = [{
        "delta_id": "d" * 32,
        "delta_sequence": 1,
        "delta_state": "STRENGTHENED",
        "reason": "new immutable evidence",
        "confirmed_at": "2026-08-15T12:00:00.000000Z",
        "evidence_links": [],
    }]
    ports, state = _ports(thesis)
    _clear_hard_risk(monkeypatch)

    before = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    assert before["proposal"]["next_best_action"] == "BUY NOW"

    opposing = {
        **_support_evidence(),
        "evidence_id": "f" * 32,
        "stance": "oppose",
        "claim": "后续 Delta 的高置信度反对事实",
    }
    thesis["deltas"][0]["evidence_links"] = [_support_evidence(), opposing]
    after = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    candidate_fact = after["proposal"]["authority_facts"]["candidate_opportunity"]

    assert after["proposal_fingerprint"] != before["proposal_fingerprint"]
    assert candidate_fact["evidence"]["status"] == "CONFLICT"
    assert candidate_fact["evidence"]["total_count"] == 2
    assert "FORMAL_EVIDENCE_OPPOSING_HIGH_CONFLICT" in candidate_fact["reason_codes"]
    assert candidate.BUY_ACTIONS <= set(after["proposal"]["action_envelope"]["blocked_actions"])

    stale = {
        **_draft(),
        "as_of": AS_OF,
        "expected_proposal_fingerprint": before["proposal_fingerprint"],
        "user_confirmed": True,
    }
    with pytest.raises(runtime.ProposalStaleError):
        runtime.commit_decision_proposal(CAMPAIGN_ID, stale, ports=ports)

    committed = runtime.commit_decision_proposal(
        CAMPAIGN_ID,
        {
            **stale,
            "expected_proposal_fingerprint": after["proposal_fingerprint"],
        },
        ports=ports,
    )["committed"]
    assert committed["evidence_refs"] == ["e" * 32, "f" * 32]
    assert any(ref.startswith("current_thesis_evidence:original:") for ref in committed["source_refs"])
    assert any(ref.startswith("current_thesis_evidence:delta:") for ref in committed["source_refs"])
    assert state["writes"] == 1


@pytest.mark.parametrize(
    ("state", "expected_action"),
    [("WEAKENED", "WAIT"), ("DISPROVEN", "AVOID"), ("INVALIDATED", "AVOID")],
)
def test_current_thesis_pressure_cannot_reopen_candidate_buy(monkeypatch, state, expected_action):
    thesis = _thesis()
    thesis["effective_state"] = state
    thesis["deltas"] = [{
        "delta_id": "d" * 32,
        "delta_sequence": 1,
        "delta_state": state,
        "reason": "authoritative Current Thesis pressure",
        "confirmed_at": "2026-08-15T12:00:00.000000Z",
        "evidence_links": [],
    }]
    ports, _state = _ports(thesis)
    _clear_hard_risk(monkeypatch)

    proposal = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF
    )["proposal"]

    assert proposal["next_best_action"] == expected_action
    assert candidate.BUY_ACTIONS <= set(proposal["action_envelope"]["blocked_actions"])
    if state == "WEAKENED":
        assert "review the confirmed change before taking a new positive-risk action" in proposal["maintain_conditions"]
    else:
        assert "thesis invalidation remains acknowledged" in proposal["maintain_conditions"]
