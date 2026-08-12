"""P0 decision-authority integration: DDA1 → CCD1 → RA1 / EC1 → DI1.

These tests intentionally compose only real public projections.  They do not
recreate a runtime assembler or make any claim about runtime I/O.
"""

from __future__ import annotations

import ast
import inspect

from campaign_critical_data_projection import project_campaign_critical_data
from critical_data_dependency_policy import (
    POLICY_VERSION_V01,
    resolve_strategy_dependencies,
)
import decision_assurance_projection as assurance_module
from decision_assurance_projection import project_decision_assurance
from decision_evidence_delta_projection import (
    DecisionContext,
    project_decision_evidence_delta,
)
import decision_inbox_projection as inbox_module
from decision_inbox_projection import CampaignFacts, project_campaign


SECURITY = "600519"
STRATEGY = "SWING"
CAMPAIGN = "campaign_" + "a" * 32
DECISION = "decision_" + "b" * 32
AS_OF = "2026-08-12T08:00:00.000000Z"
DECISION_BOUNDARY = "2026-08-11T08:00:00.000000Z"
REVIEW_BY = "2026-08-20T08:00:00.000000Z"


def test_unknown_dda_policy_flows_to_not_evaluated_coverage_and_setup_action():
    definition = resolve_strategy_dependencies(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        policy_version="dda.strategy_dependency.unknown.v0",
    )
    critical = project_campaign_critical_data(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        dependency_set_state=definition["dependency_set_state"],
        dependency_set_authority_refs=definition["dependency_set_authority_refs"],
        required_dependency_ids=definition["required_dependency_ids"],
        dependency_results=[],
    )
    assurance = project_decision_assurance(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        formal_thesis_evaluation="EVALUATED",
        formal_decision_evaluation="NOT_EVALUATED",
        hard_risk_evaluation="EVALUATED",
        material_change_evaluation="EVALUATED",
        critical_data_evaluation=critical["critical_data_evaluation"],
        as_of=AS_OF,
    )
    delta = project_decision_evidence_delta(
        context=DecisionContext(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            decision_id=DECISION,
            decision_boundary_at=DECISION_BOUNDARY,
        ),
        evidence_items=(),
    )
    item = project_campaign(
        CampaignFacts(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            campaign_status="ACTIVE",
            thesis_state="READY",
            current_thesis="STABLE",
            latest_frozen_decision=None,
            hard_risk_state="CLEAR",
            material_change_state="NONE",
            critical_data_state=critical["critical_data_state"],
            critical_data_evaluation=critical["critical_data_evaluation"],
            decision_confidence="HIGH",
            coverage_complete=assurance["coverage_complete"],
            as_of=AS_OF,
            authority_refs=("thesis:integration",),
        )
    )

    assert definition["dependency_set_state"] == "NOT_EVALUATED"
    assert critical["critical_data_state"] == "UNKNOWN"
    assert critical["critical_data_evaluation"] == "NOT_EVALUATED"
    assert assurance["dimension_states"]["CRITICAL_DATA"] == "NOT_EVALUATED"
    assert assurance["not_evaluated_dimensions"] == [
        "FORMAL_DECISION",
        "CRITICAL_DATA",
    ]
    assert assurance["coverage_complete"] is False
    assert delta.security_code == item.security_code == SECURITY
    assert delta.strategy == item.strategy == STRATEGY
    assert delta.campaign_id == item.campaign_id == CAMPAIGN
    assert delta.decision_id == DECISION
    assert critical["as_of"] == assurance["as_of"] == item.as_of == AS_OF
    assert item.critical_data_state == "UNKNOWN"
    assert item.critical_data_evaluation == "NOT_EVALUATED"
    assert item.coverage_complete is False
    assert item.visible_state == "SETUP_REQUIRED"
    assert item.reason_codes == (
        "FORMAL_DECISION_MISSING",
        "CRITICAL_DATA_NOT_EVALUATED",
        "COVERAGE_INCOMPLETE",
    )
    assert item.explainability["next_workflow_action"] == "CREATE_FORMAL_DECISION"


def test_ccd_dependency_error_is_data_error_not_unknown_reason_in_di():
    definition = resolve_strategy_dependencies(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        policy_version=POLICY_VERSION_V01,
    )
    assert definition["dependency_set_state"] == "RESOLVED"
    critical = project_campaign_critical_data(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        dependency_set_state=definition["dependency_set_state"],
        dependency_set_authority_refs=definition["dependency_set_authority_refs"],
        required_dependency_ids=definition["required_dependency_ids"],
        dependency_results=[
            {
                "dependency_id": definition["required_dependency_ids"][0],
                "state": "USABLE",
                "as_of": AS_OF,
                "authority_refs": ("health:price",),
            },
            {
                "dependency_id": definition["required_dependency_ids"][1],
                "state": "ERROR",
                "as_of": AS_OF,
                "authority_refs": ("health:market",),
            },
            {
                "dependency_id": definition["required_dependency_ids"][2],
                "state": "USABLE",
                "as_of": AS_OF,
                "authority_refs": ("health:disclosures",),
            },
        ],
    )
    assurance = project_decision_assurance(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        formal_thesis_evaluation="EVALUATED",
        formal_decision_evaluation="EVALUATED",
        hard_risk_evaluation="EVALUATED",
        material_change_evaluation="EVALUATED",
        critical_data_evaluation=critical["critical_data_evaluation"],
        as_of=AS_OF,
    )
    delta = project_decision_evidence_delta(
        context=DecisionContext(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            decision_id=DECISION,
            decision_boundary_at=DECISION_BOUNDARY,
        ),
        evidence_items=(),
    )
    item = project_campaign(
        CampaignFacts(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            campaign_status="ACTIVE",
            thesis_state="READY",
            current_thesis="STABLE",
            latest_frozen_decision={
                "decision_id": DECISION,
                "committed_at": DECISION_BOUNDARY,
                "review_by": REVIEW_BY,
                "previous_next_best_action": "HOLD",
            },
            hard_risk_state="CLEAR",
            material_change_state="NONE",
            critical_data_state=critical["critical_data_state"],
            critical_data_evaluation=critical["critical_data_evaluation"],
            decision_confidence="HIGH",
            coverage_complete=assurance["coverage_complete"],
            as_of=AS_OF,
            authority_refs=("thesis:integration",),
        )
    )

    assert critical["critical_data_state"] == "UNKNOWN"
    assert critical["critical_data_evaluation"] == "ERROR"
    assert assurance["error_dimensions"] == ["CRITICAL_DATA"]
    assert assurance["coverage_complete"] is False
    assert delta.has_new_evidence is False
    assert delta.temporal_coverage_complete is True
    assert item.critical_data_state == "UNKNOWN"
    assert item.critical_data_evaluation == "ERROR"
    assert item.coverage_complete is False
    assert item.visible_state == "BLOCKED_BY_DATA"
    assert "CRITICAL_DATA_ERROR" in item.reason_codes
    assert "CRITICAL_DATA_UNKNOWN" not in item.reason_codes
    assert item.explainability["next_workflow_action"] == "REPAIR_DATA"
    assert critical["as_of"] == assurance["as_of"] == item.as_of == AS_OF


def test_blocked_and_error_remain_cumulative_while_blocked_is_primary():
    definition = resolve_strategy_dependencies(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        policy_version=POLICY_VERSION_V01,
    )
    critical = project_campaign_critical_data(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        dependency_set_state=definition["dependency_set_state"],
        dependency_set_authority_refs=definition["dependency_set_authority_refs"],
        required_dependency_ids=definition["required_dependency_ids"],
        dependency_results=[
            {
                "dependency_id": definition["required_dependency_ids"][0],
                "state": "BLOCKED",
                "as_of": AS_OF,
                "authority_refs": ("health:price",),
            },
            {
                "dependency_id": definition["required_dependency_ids"][1],
                "state": "ERROR",
                "as_of": AS_OF,
                "authority_refs": ("health:market",),
            },
            {
                "dependency_id": definition["required_dependency_ids"][2],
                "state": "USABLE",
                "as_of": AS_OF,
                "authority_refs": ("health:disclosures",),
            },
        ],
    )
    assurance = project_decision_assurance(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        formal_thesis_evaluation="EVALUATED",
        formal_decision_evaluation="NOT_EVALUATED",
        hard_risk_evaluation="EVALUATED",
        material_change_evaluation="EVALUATED",
        critical_data_evaluation=critical["critical_data_evaluation"],
        as_of=AS_OF,
    )
    delta = project_decision_evidence_delta(
        context=DecisionContext(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            decision_id=DECISION,
            decision_boundary_at=DECISION_BOUNDARY,
        ),
        evidence_items=(),
    )
    item = project_campaign(
        CampaignFacts(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            campaign_status="ACTIVE",
            thesis_state="READY",
            current_thesis="STABLE",
            latest_frozen_decision=None,
            hard_risk_state="CLEAR",
            material_change_state="NONE",
            critical_data_state=critical["critical_data_state"],
            critical_data_evaluation=critical["critical_data_evaluation"],
            decision_confidence="HIGH",
            coverage_complete=assurance["coverage_complete"],
            as_of=AS_OF,
            authority_refs=("thesis:integration",),
        )
    )

    assert critical["critical_data_state"] == "BLOCKED"
    assert critical["critical_data_evaluation"] == "ERROR"
    assert assurance["dimension_states"]["CRITICAL_DATA"] == "ERROR"
    assert "FORMAL_DECISION" in assurance["not_evaluated_dimensions"]
    assert "CRITICAL_DATA" in assurance["error_dimensions"]
    assert assurance["coverage_complete"] is False
    assert delta.security_code == item.security_code == SECURITY
    assert delta.campaign_id == item.campaign_id == CAMPAIGN
    assert item.critical_data_state == "BLOCKED"
    assert item.critical_data_evaluation == "ERROR"
    assert item.visible_state == "BLOCKED_BY_DATA"
    assert item.reason_codes == (
        "CRITICAL_DATA_BLOCKED",
        "FORMAL_DECISION_MISSING",
        "CRITICAL_DATA_ERROR",
        "COVERAGE_INCOMPLETE",
    )
    assert item.explainability["next_workflow_action"] == "REPAIR_DATA"
    assert critical["as_of"] == assurance["as_of"] == item.as_of == AS_OF


def test_unknown_dependency_is_an_actual_data_blocker_even_when_ra_coverage_is_complete():
    definition = resolve_strategy_dependencies(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        policy_version=POLICY_VERSION_V01,
    )
    critical = project_campaign_critical_data(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        dependency_set_state=definition["dependency_set_state"],
        dependency_set_authority_refs=definition["dependency_set_authority_refs"],
        required_dependency_ids=definition["required_dependency_ids"],
        dependency_results=[
            {
                "dependency_id": definition["required_dependency_ids"][0],
                "state": "UNKNOWN",
                "as_of": AS_OF,
                "authority_refs": ("health:price",),
            },
            {
                "dependency_id": definition["required_dependency_ids"][1],
                "state": "USABLE",
                "as_of": AS_OF,
                "authority_refs": ("health:market",),
            },
            {
                "dependency_id": definition["required_dependency_ids"][2],
                "state": "USABLE",
                "as_of": AS_OF,
                "authority_refs": ("health:disclosures",),
            },
        ],
    )
    assurance = project_decision_assurance(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        formal_thesis_evaluation="EVALUATED",
        formal_decision_evaluation="EVALUATED",
        hard_risk_evaluation="EVALUATED",
        material_change_evaluation="EVALUATED",
        critical_data_evaluation=critical["critical_data_evaluation"],
        as_of=AS_OF,
    )
    delta = project_decision_evidence_delta(
        context=DecisionContext(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            decision_id=DECISION,
            decision_boundary_at=DECISION_BOUNDARY,
        ),
        evidence_items=(),
    )
    item = project_campaign(
        CampaignFacts(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            campaign_status="ACTIVE",
            thesis_state="READY",
            current_thesis="STABLE",
            latest_frozen_decision={
                "decision_id": DECISION,
                "committed_at": DECISION_BOUNDARY,
                "review_by": REVIEW_BY,
                "previous_next_best_action": "HOLD",
            },
            hard_risk_state="CLEAR",
            material_change_state="NONE",
            critical_data_state=critical["critical_data_state"],
            critical_data_evaluation=critical["critical_data_evaluation"],
            decision_confidence="HIGH",
            coverage_complete=assurance["coverage_complete"],
            as_of=AS_OF,
            authority_refs=("thesis:integration",),
        )
    )

    assert critical["critical_data_state"] == "UNKNOWN"
    assert critical["critical_data_evaluation"] == "UNKNOWN"
    assert assurance["unknown_dimensions"] == ["CRITICAL_DATA"]
    assert assurance["coverage_complete"] is True
    assert delta.has_new_evidence is False
    assert delta.temporal_coverage_complete is True
    assert item.critical_data_state == "UNKNOWN"
    assert item.critical_data_evaluation == "UNKNOWN"
    assert item.coverage_complete is True
    assert item.visible_state == "BLOCKED_BY_DATA"
    assert item.reason_codes == ("CRITICAL_DATA_UNKNOWN",)
    assert "CRITICAL_DATA_EVALUATION_UNKNOWN" not in item.reason_codes
    assert item.explainability["next_workflow_action"] == "REPAIR_DATA"


def test_ec1_empty_delta_locks_public_composition_surface_without_assembler():
    """Current repository has no assembler; lock authority boundaries only."""
    delta = project_decision_evidence_delta(
        context=DecisionContext(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            decision_id=DECISION,
            decision_boundary_at=DECISION_BOUNDARY,
        ),
        evidence_items=(),
    )
    ec1_only_fields = {
        "hard_risk_state",
        "hard_risk_evaluation",
        "material_change_state",
        "material_change_evaluation",
        "coverage_complete",
        "critical_data_state",
        "critical_data_evaluation",
    }
    ec1_composition_inputs = {
        "has_new_evidence",
        "temporal_coverage_complete",
        "new_evidence",
        "preexisting_evidence",
        "unknown_temporal_evidence",
        "out_of_scope_evidence",
    }

    assert delta.has_new_evidence is False
    assert delta.temporal_coverage_complete is True
    assert ec1_only_fields.isdisjoint(delta.to_dict())
    assert ec1_composition_inputs.isdisjoint(
        inspect.signature(project_decision_assurance).parameters
    )
    assert ec1_composition_inputs.isdisjoint(CampaignFacts.__dataclass_fields__)

    for module in (assurance_module, inbox_module):
        tree = ast.parse(inspect.getsource(module))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "decision_evidence_delta_projection" not in imported_modules
