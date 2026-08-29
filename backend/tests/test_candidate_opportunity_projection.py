from __future__ import annotations

from copy import deepcopy

import pytest

import candidate_opportunity_projection as candidate
import decision_commit_runtime as runtime
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
            "canonical": False,
            "confidence": "MEDIUM",
            "settled_nav": 1_000_000,
            "cash": {"current_fact": {"status": "AVAILABLE", "value": 200_000}},
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
    assert high.authority_fact["account_canonical"] is False
    assert high.authority_fact["risk_cap"]["status"] == "AVAILABLE_CANDIDATE"
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


def _ports():
    state = {"frozen": [], "writes": 0}

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
        thesis_reader=lambda _campaign_id: _thesis(),
        frozen_reader=frozen_reader,
        evidence_reader=lambda _campaign: (),
        freeze_writer=freeze_writer,
        freeze_writer_with_pre_write_validation=freeze_validated,
        decision_reader=lambda decision_id: next(
            (deepcopy(item) for item in state["frozen"] if item["decision_id"] == decision_id),
            None,
        ),
        critical_data_reader=lambda _campaign, as_of: {**_critical(), "as_of": as_of},
        position_reader=lambda: {"authority_state": "CANONICAL", "holdings": []},
        account_reader=lambda: {
            "canonical": False,
            "confidence": "MEDIUM",
            "settled_nav": 1_000_000,
            "cash": {"current_fact": {"status": "AVAILABLE", "value": 200_000}},
        },
    ), state


def test_pre_entry_buy_requires_challenge_and_freezes_candidate_policy(monkeypatch):
    ports, state = _ports()
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
    assert state["writes"] == 1
