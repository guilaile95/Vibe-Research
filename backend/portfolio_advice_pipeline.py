"""portfolio-advice-v0.1 Validator 的固定阶段 Pipeline。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from portfolio_advice_compat import align_holdings, normalize_account_action
from portfolio_advice_contracts import LOT_SIZE, SCHEMA_VERSION
from portfolio_advice_errors import PortfolioAdviceValidationError
from portfolio_advice_execution import calculate_execution
from portfolio_advice_fact_reconciler import (
    context_holdings_index,
    market_is_partial,
    market_status_from_context,
    portfolio_summary_from_context,
    reconcile_holding_facts,
    trade_date_from_context,
)
from portfolio_advice_narrative_audit import (
    audit_holding_narrative,
    collect_context_numbers,
    normalize_top_level_lists,
)
from portfolio_advice_policy import POLICY
from portfolio_advice_policy_audit import audit_execution_size
from portfolio_advice_schema import normalize_matching_holdings, validate_inputs


PIPELINE_STAGE_NAMES = (
    "schema_validation",
    "legacy_compatibility",
    "fact_reconciliation",
    "policy_audit",
    "execution_calculation",
    "narrative_audit",
    "final_assembly",
)


@dataclass
class PipelineState:
    ai_result: Any
    context: Any
    generated_at: str | None
    ai_work: dict | None = None
    context_index: dict[str, dict] | None = None
    items: list[dict] | None = None
    allowed_base_numbers: set[float] | None = None
    validated_holdings: list[dict] | None = None
    account_action: dict | None = None
    portfolio_summary: dict | None = None
    market_status: str | None = None
    trade_date: str | None = None
    warnings: list[str] | None = None
    limitations: list[str] | None = None
    resolved_generated_at: str = ""
    result: dict | None = None


def resolve_generated_at(
    explicit_generated_at: str | None,
    ai_work: dict,
) -> str:
    value = explicit_generated_at
    if value is None:
        value = ai_work.get("generated_at")
    return value if isinstance(value, str) else ""


def schema_validation(state: PipelineState) -> PipelineState:
    ai_work, context = validate_inputs(state.ai_result, state.context)
    context_index = context_holdings_index(context)
    normalized = normalize_matching_holdings(ai_work, set(context_index))
    state.ai_work = ai_work
    state.context = context
    state.context_index = context_index
    state.resolved_generated_at = resolve_generated_at(
        state.generated_at,
        ai_work,
    )
    state.items = [
        {"schema": schema, "context_holding": context_index[code]}
        for code, schema in normalized.items()
    ]
    return state


def legacy_compatibility(state: PipelineState) -> PipelineState:
    assert state.ai_work is not None
    assert state.context_index is not None
    normalized_by_code = {
        item["schema"]["code"]: item["schema"] for item in state.items or []
    }
    state.items = align_holdings(state.context_index, normalized_by_code)
    state.account_action = normalize_account_action(
        state.ai_work.get("account_action")
    )
    return state


def fact_reconciliation(state: PipelineState) -> PipelineState:
    for item in state.items or []:
        item["facts"] = reconcile_holding_facts(item["context_holding"])
    state.portfolio_summary = portfolio_summary_from_context(state.context)
    state.market_status = (state.ai_work or {}).get("market_status")
    if not isinstance(state.market_status, str) or not state.market_status.strip():
        state.market_status = market_status_from_context(state.context)
    state.trade_date = trade_date_from_context(state.context)
    return state


def policy_audit(state: PipelineState) -> PipelineState:
    partial = market_is_partial(state.context)
    for item in state.items or []:
        schema = item["schema"]
        item["size_pct"] = audit_execution_size(
            schema["action"],
            schema["raw"].get("execution_size_pct_of_holding"),
            confidence=schema["confidence"],
            market_partial=partial,
            code=schema["code"],
        )
    return state


def execution_calculation(state: PipelineState) -> PipelineState:
    for item in state.items or []:
        item["execution"] = calculate_execution(
            item["schema"]["action"],
            item["size_pct"],
            item["facts"],
            item["context_holding"],
        )
    return state


def narrative_audit(state: PipelineState) -> PipelineState:
    allowed_base: set[float] = set()
    collect_context_numbers(state.context, allowed_base)
    allowed_base.update(POLICY.add_tiers)
    allowed_base.update(POLICY.reduce_tiers)
    allowed_base.update({POLICY.sell_tier, 0.0, float(LOT_SIZE)})
    state.allowed_base_numbers = allowed_base
    state.validated_holdings = [
        audit_holding_narrative(item, allowed_base_numbers=allowed_base)
        for item in state.items or []
    ]
    state.limitations, state.warnings = normalize_top_level_lists(
        state.ai_work, state.context
    )
    return state


def final_assembly(state: PipelineState) -> PipelineState:
    state.result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": state.resolved_generated_at,
        "trade_date": state.trade_date,
        "market_status": state.market_status,
        "portfolio_summary": state.portfolio_summary or {},
        "account_action": state.account_action or {},
        "holdings": state.validated_holdings or [],
        "warnings": state.warnings or [],
        "data_limitations": state.limitations or [],
    }
    return state


def validate_portfolio_advice(
    ai_result: dict,
    context: dict,
    *,
    generated_at: str | None = None,
) -> dict:
    """按固定顺序运行 Schema、兼容、事实、政策、执行和文案阶段。"""
    state = PipelineState(ai_result, context, generated_at)
    state = schema_validation(state)
    state = legacy_compatibility(state)
    state = fact_reconciliation(state)
    state = policy_audit(state)
    state = execution_calculation(state)
    state = narrative_audit(state)
    state = final_assembly(state)
    assert state.result is not None
    return state.result
