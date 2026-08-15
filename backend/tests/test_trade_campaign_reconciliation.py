"""Trade Campaign Reconciliation State tests (P0-TCR1)."""

from __future__ import annotations

import ast
import copy
import inspect
import sys
from pathlib import Path

import pytest

import formal_trade_attribution as fta
import frozen_decision_store as fd_store
import trade_campaign_reconciliation as tcr

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


AS_OF = "2026-08-13T12:00:00.000000Z"
COMMITTED_AT = "2026-08-10T06:00:00.000000Z"
TRADE_CREATED_AT = "2026-08-10T06:30:00.000000+00:00"
TRADE_EXECUTED_AT = "2026-08-10T06:45:00.000000+00:00"
REVIEW_BY = "2026-08-25T00:00:00.000000Z"
ATTR_CREATED_AT = "2026-08-10T07:00:00.000000Z"

DECISION_ID = "decision_" + "a" * 32
TRADE_ID = "b" * 32
OTHER_TRADE_ID = "1" * 32
ATTRIBUTION_ID = "trade_attribution_" + "c" * 32
CAMPAIGN_ID = "campaign_" + "d" * 32
THESIS_ID = "e" * 32
SECURITY = "600519"
POLICY = tcr.POLICY_VERSION_V01


def _snapshot(**overrides) -> dict:
    snapshot = {
        "snapshot_schema_version": fd_store.SCHEMA_VERSION,
        "decision_id": DECISION_ID,
        "security_code": SECURITY,
        "strategy": "SWING",
        "campaign_id": CAMPAIGN_ID,
        "committed_at": COMMITTED_AT,
        "thesis_id": THESIS_ID,
        "thesis_revision": 2,
        "asset_view": {"label": "贵州茅台"},
        "trade_view": {"size_pct": 0.1},
        "portfolio_view": {"target_weight": 0.15},
        "next_best_action": "BUY SMALL",
        "action_envelope": {"max_size": 0.1},
        "maintain_conditions": ["ok"],
        "upgrade_conditions": [],
        "downgrade_conditions": [],
        "invalidation_conditions": [],
        "strategy_horizon": "2 至 4 周",
        "review_by": REVIEW_BY,
        "key_assumptions": [],
        "event_invalidation_conditions": [],
        "validity_status_at_commit": "CURRENT",
        "risk_policy_version": "risk-policy-v0.1",
        "opportunity_policy_version": "opp-policy-v0.1",
        "decision_policy_version": "decision-policy-v0.1",
        "behavior_model_version": "behavior-v0.1",
        "data_quality": {},
        "evidence_confidence": 0.8,
        "inference_confidence": "medium",
        "decision_confidence": None,
        "evidence_refs": [],
        "risk_refs": [],
        "source_refs": [],
    }
    snapshot.update(overrides)
    return snapshot


def make_decision(**overrides) -> dict:
    snapshot = _snapshot(
        **{k: v for k, v in overrides.items() if k in fd_store.SNAPSHOT_KEYS}
    )
    frozen = {
        **snapshot,
        "snapshot_json": fd_store.canonical_json(snapshot),
        "snapshot_hash": fd_store.snapshot_hash(snapshot),
        "user_confirmed": True,
        "created_at": "2026-08-10T05:00:00.000000Z",
    }
    frozen.update({k: v for k, v in overrides.items() if k not in fd_store.SNAPSHOT_KEYS})
    return frozen


def make_trade(**overrides) -> dict:
    trade = {
        "trade_id": TRADE_ID,
        "code": SECURITY,
        "name": "贵州茅台",
        "operation": "buy",
        "execution_status": "full",
        "planned_price": 1500.0,
        "planned_quantity": 100,
        "actual_price": 1500.0,
        "actual_quantity": 100,
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


def make_attribution(trade=None, **create_kw):
    return fta.create_attribution(
        make_decision(),
        trade if trade is not None else make_trade(),
        attribution_id=create_kw.get("attribution_id", ATTRIBUTION_ID),
        created_at=create_kw.get("created_at", ATTR_CREATED_AT),
    )


def _project(**overrides):
    base = {
        "as_of": AS_OF,
        "policy_version": POLICY,
        "trade": make_trade(),
        "attribution_records": [],
        "attribution_coverage": "COMPLETE",
        "attribution_coverage_authority_refs": ["cov:1"],
        "trade_authority_refs": ["trade:1"],
    }
    base.update(overrides)
    return tcr.project_trade_campaign_reconciliation(**base)


def test_a_full_complete_matching_allocated():
    rec = make_attribution()
    out = _project(attribution_records=[rec])
    assert out["allocation_state"] == "ALLOCATED"
    assert out["reconciliation_requirement"] == "NOT_REQUIRED"
    assert out["campaign_id"] == CAMPAIGN_ID
    assert out["decision_id"] == DECISION_ID
    assert out["attribution_id"] == ATTRIBUTION_ID


def test_b_partial_valid_attribution_allocated():
    trade = make_trade(execution_status="partial")
    rec = make_attribution(trade)
    out = _project(trade=trade, attribution_records=[rec])
    assert out["allocation_state"] == "ALLOCATED"
    assert out["execution_status"] == "partial"


def test_c_full_complete_empty_set_unallocated():
    out = _project(attribution_records=[])
    assert out["allocation_state"] == "UNALLOCATED"
    assert out["reconciliation_requirement"] == "REQUIRED"
    assert "CAMPAIGN_ALLOCATION_MISSING" in out["reason_codes"]
    assert out["campaign_id"] is None


def test_d_partial_complete_no_matching_unallocated():
    other = make_attribution(make_trade(trade_id=OTHER_TRADE_ID))
    out = _project(
        trade=make_trade(execution_status="partial"),
        attribution_records=[other],
    )
    assert out["allocation_state"] == "UNALLOCATED"
    assert out["reconciliation_requirement"] == "REQUIRED"


def test_e_empty_records_without_complete_not_unallocated():
    out = _project(attribution_records=[], attribution_coverage="UNKNOWN")
    assert out["allocation_state"] != "UNALLOCATED"
    assert out["allocation_state"] == "UNKNOWN"


def test_f_coverage_unknown():
    out = _project(attribution_coverage="UNKNOWN", attribution_records=[])
    assert out["allocation_state"] == "UNKNOWN"
    assert out["reconciliation_requirement"] == "UNKNOWN"


def test_g_coverage_not_evaluated():
    out = _project(attribution_coverage="NOT_EVALUATED", attribution_records=[])
    assert out["allocation_state"] == "NOT_EVALUATED"
    assert out["reconciliation_requirement"] == "NOT_EVALUATED"


def test_h_coverage_error():
    out = _project(attribution_coverage="ERROR", attribution_records=[])
    assert out["allocation_state"] == "ERROR"
    assert out["reconciliation_requirement"] == "ERROR"


def test_i_not_executed_not_applicable():
    trade = make_trade(execution_status="not_executed", executed_at=None)
    out = _project(trade=trade, attribution_records=[])
    assert out["allocation_state"] == "NOT_APPLICABLE"
    assert out["reconciliation_requirement"] == "NOT_APPLICABLE"
    assert out["allocation_state"] != "UNALLOCATED"


def test_j_voided_trade_not_applicable():
    trade = make_trade(voided_at="2026-08-11T00:00:00.000000Z", void_reason="err")
    out = _project(trade=trade, attribution_records=[])
    assert out["allocation_state"] == "NOT_APPLICABLE"
    assert out["reconciliation_requirement"] == "NOT_APPLICABLE"
    assert "TRADE_VOIDED" in out["reason_codes"]


def test_k_other_trade_id_does_not_allocate_current():
    other = make_attribution(make_trade(trade_id=OTHER_TRADE_ID))
    out = _project(attribution_records=[other])
    assert out["trade_id"] == TRADE_ID
    assert out["allocation_state"] == "UNALLOCATED"


def test_l_same_security_campaign_not_inferred():
    out = _project(attribution_records=[])
    assert out["campaign_id"] is None
    assert out["allocation_state"] == "UNALLOCATED"
    assert "CAMPAIGN_INFERENCE=NO" in out["explainability"]["note"]


def test_m_conflicting_attributions_fail_closed():
    a = make_attribution()
    other_decision = make_decision(decision_id="decision_" + "f" * 32)
    other = fta.create_attribution(
        other_decision,
        make_trade(),
        attribution_id="trade_attribution_" + "9" * 32,
        created_at=ATTR_CREATED_AT,
    )
    with pytest.raises(tcr.TradeCampaignReconciliationValidationError):
        _project(attribution_records=[a, other])


def test_n_corrupted_attribution_hash_fail_closed():
    rec = make_attribution().to_dict()
    rec["attribution_hash"] = "0" * 64
    with pytest.raises(tcr.TradeCampaignReconciliationValidationError):
        _project(attribution_records=[rec])


def test_o_security_code_mismatch_fail_closed():
    rec = make_attribution().to_dict()
    trade = make_trade()
    # Mutate after TB1 create so hash still matches record but trade witness differs.
    # Cross-anchor must reject same trade_id / different security.
    rec_ok = make_attribution()
    bad_trade = make_trade()
    # Cannot change trade.code without breaking TB1 verify if we still match
    # attribution security via cross-anchor.
    mutated = rec_ok.to_dict()
    mutated["security_code"] = "000001"
    mutated["attribution_hash"] = fta.compute_attribution_hash(mutated)
    with pytest.raises(tcr.TradeCampaignReconciliationValidationError):
        _project(trade=bad_trade, attribution_records=[mutated])


def test_p_trade_operation_mismatch_fail_closed():
    rec = make_attribution()
    trade = make_trade(operation="sell")
    with pytest.raises(tcr.TradeCampaignReconciliationValidationError, match="operation"):
        _project(trade=trade, attribution_records=[rec])


def test_q_execution_status_mismatch_fail_closed():
    rec = make_attribution()
    trade = make_trade(execution_status="partial")
    with pytest.raises(
        tcr.TradeCampaignReconciliationValidationError, match="execution_status"
    ):
        _project(trade=trade, attribution_records=[rec])


def test_r_executed_at_mismatch_fail_closed():
    rec = make_attribution()
    trade = make_trade(executed_at="2026-08-10T08:00:00.000000+00:00")
    with pytest.raises(
        tcr.TradeCampaignReconciliationValidationError, match="executed_at"
    ):
        _project(trade=trade, attribution_records=[rec])


def test_s_future_trade_fail_closed():
    trade = make_trade(created_at="2026-08-14T00:00:00.000000+00:00")
    with pytest.raises(tcr.TradeCampaignReconciliationValidationError, match="as_of"):
        _project(trade=trade, attribution_records=[])


def test_t_future_attribution_fail_closed():
    rec = make_attribution(created_at="2026-08-14T00:00:00.000000Z")
    with pytest.raises(tcr.TradeCampaignReconciliationValidationError, match="as_of"):
        _project(attribution_records=[rec])


def test_u_unknown_policy_complete_empty_not_unallocated():
    out = _project(policy_version="tcr.unknown", attribution_records=[])
    assert out["allocation_state"] == "NOT_EVALUATED"
    assert out["reconciliation_requirement"] == "NOT_EVALUATED"
    assert out["allocation_state"] != "UNALLOCATED"
    assert "POLICY_VERSION_NOT_AVAILABLE" in out["reason_codes"]


def test_v_unknown_policy_matching_attribution_not_evaluated():
    rec = make_attribution()
    out = _project(policy_version="tcr.unknown", attribution_records=[rec])
    assert out["allocation_state"] == "NOT_EVALUATED"
    assert out["campaign_id"] is None
    assert out["attribution_id"] is None


def test_w_no_latest_policy_fallback():
    out = _project(policy_version="tcr.trade_campaign_reconciliation.v9.9")
    assert out["policy_authority_ref"] is None
    assert out["allocation_state"] == "NOT_EVALUATED"


def test_x_no_fifo():
    src = Path(tcr.__file__).read_text(encoding="utf-8")
    assert "def fifo" not in src.lower()
    assert "FIFO=FORBIDDEN" in _project()["explainability"]["note"]


def test_y_no_ai():
    src = Path(tcr.__file__).read_text(encoding="utf-8")
    assert "openai" not in src
    assert "anthropic" not in src


def test_z_no_campaign_store_search():
    src = Path(tcr.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {
        "campaign_store",
        "campaign_service",
        "trade_ledger_store",
        "trade_ledger_service",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden


def test_aa_no_post_entry_fabrication():
    out = _project()
    assert out.get("post_entry_campaign") is None
    assert "POST_ENTRY_BINDING_ENGINE=OUT_OF_SCOPE" in out["explainability"]["note"]


def test_ab_no_synthetic_pre_vibe_trade():
    src = Path(tcr.__file__).read_text(encoding="utf-8")
    assert "LEGACY_POSITION_OPENING" not in src
    out = _project()
    assert "PRE_VIBE_SYNTHETIC_BUY=FORBIDDEN" in out["explainability"]["note"]


def test_ac_input_immutability():
    recs = []
    trade = make_trade()
    cov = ["cov:1"]
    refs = ["trade:1"]
    snap = copy.deepcopy({"recs": recs, "trade": trade, "cov": cov, "refs": refs})
    tcr.project_trade_campaign_reconciliation(
        as_of=AS_OF,
        policy_version=POLICY,
        trade=trade,
        attribution_records=recs,
        attribution_coverage="COMPLETE",
        attribution_coverage_authority_refs=cov,
        trade_authority_refs=refs,
    )
    assert recs == snap["recs"]
    assert trade == snap["trade"]
    assert cov == snap["cov"]
    assert refs == snap["refs"]


def test_ad_deterministic_repeated_output():
    rec = make_attribution()
    assert _project(attribution_records=[rec]) == _project(attribution_records=[rec])


def test_ae_keyword_only_public_api():
    sig = inspect.signature(tcr.project_trade_campaign_reconciliation)
    assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in sig.parameters.values())
    assert tcr.POLICY_VERSION_V01 == "tcr.trade_campaign_reconciliation.v0.1"


def test_af_no_io():
    src = Path(tcr.__file__).read_text(encoding="utf-8")
    assert "sqlite3" not in src
    assert "open(" not in src


def test_ag_no_wall_clock():
    src = Path(tcr.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"now", "utcnow", "today"}:
                pytest.fail(f"wall clock forbidden: {node.func.attr}")


def test_adversarial_empty_list_alone_not_proven_unallocated():
    out = _project(attribution_records=[], attribution_coverage="NOT_EVALUATED")
    assert out["allocation_state"] != "UNALLOCATED"


def test_adversarial_complete_empty_is_proven_unallocated():
    out = _project(attribution_records=[], attribution_coverage="COMPLETE")
    assert out["allocation_state"] == "UNALLOCATED"
    assert out["reconciliation_requirement"] == "REQUIRED"


def test_naked_coverage_refs_rejected():
    with pytest.raises(
        tcr.TradeCampaignReconciliationValidationError,
        match="attribution_coverage_authority_refs",
    ):
        _project(attribution_coverage_authority_refs=[])


def test_voided_malformed_identity_still_rejected():
    with pytest.raises(tcr.TradeCampaignReconciliationValidationError, match="trade_id"):
        _project(
            trade=make_trade(trade_id="bad", voided_at="2026-08-11T00:00:00.000000Z")
        )
