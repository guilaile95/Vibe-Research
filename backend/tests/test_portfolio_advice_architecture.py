"""持仓建议 Policy 与 Validator Pipeline 架构约束测试。"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import portfolio_advice_contracts as contracts
import portfolio_advice_prompt as prompt
import portfolio_advice_validator as validator


BACKEND_DIR = Path(__file__).parent.parent


def test_policy_is_strategy_rules_single_source() -> None:
    import portfolio_advice_policy as policy

    assert policy.POLICY_VERSION == "portfolio-policy-v0.1"
    assert policy.POLICY.add_tiers == frozenset({10.0, 20.0})
    assert policy.POLICY.reduce_tiers == frozenset({10.0, 20.0, 30.0})
    assert policy.POLICY.sell_tier == 100.0
    assert dict(policy.POLICY.confidence_caps) == {
        "low": 10.0,
        "medium": 20.0,
        "high": 30.0,
    }
    assert policy.POLICY.partial_market_add_max == 10.0
    assert policy.POLICY.partial_market_reduce_max == 20.0


def test_contracts_do_not_duplicate_or_reexport_policy_values() -> None:
    import portfolio_advice_policy as policy

    for name in (
        "ADD_TIERS",
        "REDUCE_TIERS",
        "CONFIDENCE_CAP",
        "SELL_TIER",
        "PARTIAL_MARKET_ADD_MAX",
        "PARTIAL_MARKET_REDUCE_MAX",
    ):
        assert not hasattr(contracts, name)
        assert hasattr(policy, name)


def test_prompt_and_pipeline_share_policy() -> None:
    import portfolio_advice_pipeline as pipeline
    import portfolio_advice_policy as policy

    assert prompt.POLICY is policy.POLICY
    assert pipeline.POLICY is policy.POLICY


def test_validator_facade_preserves_public_imports() -> None:
    import portfolio_advice_execution as execution
    import portfolio_advice_pipeline as pipeline

    assert validator.PortfolioAdviceValidationError is pipeline.PortfolioAdviceValidationError
    assert validator.validate_portfolio_advice is pipeline.validate_portfolio_advice
    assert validator.floor_to_lot is execution.floor_to_lot
    assert validator.compute_execution_quantity is execution.compute_execution_quantity
    assert validator.compute_add_execution_quantity is execution.compute_add_execution_quantity
    assert validator.compute_estimated_amount is execution.compute_estimated_amount


def test_validator_is_thin_facade_without_business_implementation() -> None:
    source = (BACKEND_DIR / "portfolio_advice_validator.py").read_text(encoding="utf-8")

    assert "re.compile" not in source
    assert "Decimal(" not in source
    assert "def _validate_one_holding" not in source
    assert "from portfolio_advice_prompt import" not in source
    assert len(source.splitlines()) <= 50


def test_pipeline_stage_order_is_explicit_and_fixed() -> None:
    import portfolio_advice_pipeline as pipeline

    assert pipeline.PIPELINE_STAGE_NAMES == (
        "schema_validation",
        "legacy_compatibility",
        "fact_reconciliation",
        "policy_audit",
        "execution_calculation",
        "narrative_audit",
        "final_assembly",
    )
    source = inspect.getsource(pipeline.validate_portfolio_advice)
    positions = [source.index(stage_name) for stage_name in pipeline.PIPELINE_STAGE_NAMES]
    assert positions == sorted(positions)


def test_pipeline_modules_have_single_direction_dependencies() -> None:
    policy_source = (BACKEND_DIR / "portfolio_advice_policy.py").read_text(
        encoding="utf-8"
    )
    contracts_source = (BACKEND_DIR / "portfolio_advice_contracts.py").read_text(
        encoding="utf-8"
    )
    policy_audit_source = (BACKEND_DIR / "portfolio_advice_policy_audit.py").read_text(
        encoding="utf-8"
    )

    assert "from portfolio_advice_policy import" not in contracts_source
    assert "import portfolio_advice_policy" not in contracts_source
    assert "portfolio_advice_contracts" in policy_source
    assert "from portfolio_advice_policy import" in policy_audit_source
    assert "account_funding" not in policy_source
    assert "available_cash" not in policy_source


def test_narrative_add_tier_pattern_is_derived_from_policy() -> None:
    import portfolio_advice_narrative_audit as narrative
    import portfolio_advice_policy as policy

    custom = policy.PortfolioAdvicePolicy(
        version="test-policy",
        add_tiers=frozenset({15.0, 25.0}),
        reduce_tiers=policy.POLICY.reduce_tiers,
        sell_tier=policy.POLICY.sell_tier,
        confidence_caps=policy.POLICY.confidence_caps,
        partial_market_add_max=policy.POLICY.partial_market_add_max,
        partial_market_reduce_max=policy.POLICY.partial_market_reduce_max,
    )

    pattern = narrative.build_tier_pattern(custom.add_tiers)

    assert pattern.fullmatch("15")
    assert pattern.fullmatch("25")
    assert not pattern.fullmatch("10")


def test_policy_audit_errors_are_derived_from_supplied_policy() -> None:
    import portfolio_advice_policy as policy
    from portfolio_advice_errors import PortfolioAdviceValidationError
    from portfolio_advice_policy_audit import audit_execution_size

    custom = policy.PortfolioAdvicePolicy(
        version="test-policy",
        add_tiers=frozenset({15.0, 25.0}),
        reduce_tiers=frozenset({5.0, 15.0, 25.0}),
        sell_tier=90.0,
        confidence_caps={"low": 5.0, "medium": 15.0, "high": 25.0},
        partial_market_add_max=5.0,
        partial_market_reduce_max=15.0,
    )

    with pytest.raises(PortfolioAdviceValidationError, match="15/25"):
        audit_execution_size(
            "add",
            None,
            confidence="high",
            market_partial=False,
            code="000001",
            policy=custom,
        )
    with pytest.raises(PortfolioAdviceValidationError, match="90"):
        audit_execution_size(
            "sell",
            100,
            confidence="high",
            market_partial=False,
            code="000001",
            policy=custom,
        )


def test_compatibility_stage_resolves_account_action() -> None:
    import portfolio_advice_pipeline as pipeline

    state = pipeline.PipelineState(
        ai_result={"account_action": {"action": "invalid"}},
        context={"holdings": []},
        generated_at=None,
        ai_work={"account_action": {"action": "invalid"}},
        context_index={},
        items=[],
    )

    pipeline.legacy_compatibility(state)

    assert state.account_action == {
        "action": "hold",
        "reason": "账户动作非法，已回落为 hold",
        "confidence": "low",
    }


def test_fact_stage_resolves_summary_and_context_metadata() -> None:
    import portfolio_advice_pipeline as pipeline

    context = {
        "holdings": [],
        "portfolio_summary": {"holding_count": 0, "market_value": 0},
        "market_context": {"review_metadata": {"status": "partial"}},
    }
    state = pipeline.PipelineState(
        ai_result={},
        context=context,
        generated_at=None,
        context_index={},
        items=[],
    )

    pipeline.fact_reconciliation(state)

    assert state.portfolio_summary is not None
    assert state.market_status == "partial"
    assert state.trade_date is None


def test_narrative_stage_resolves_top_level_lists() -> None:
    import portfolio_advice_pipeline as pipeline

    state = pipeline.PipelineState(
        ai_result={},
        context={"data_limitations": [], "warnings": []},
        generated_at=None,
        ai_work={"data_limitations": [], "warnings": []},
        items=[],
    )

    pipeline.narrative_audit(state)

    assert state.limitations is not None
    assert state.warnings == []


def test_final_assembly_only_reads_resolved_state(monkeypatch) -> None:
    import portfolio_advice_pipeline as pipeline

    def fail(*args, **kwargs):
        raise AssertionError("final_assembly called a prior-stage function")

    monkeypatch.setattr(pipeline, "normalize_top_level_lists", fail)
    monkeypatch.setattr(pipeline, "portfolio_summary_from_context", fail)
    monkeypatch.setattr(pipeline, "normalize_account_action", fail)
    monkeypatch.setattr(pipeline, "market_status_from_context", fail)
    monkeypatch.setattr(pipeline, "trade_date_from_context", fail)

    state = pipeline.PipelineState(
        ai_result={},
        context={},
        generated_at=None,
        ai_work={"generated_at": "generated"},
        account_action={"action": "hold", "reason": "r", "confidence": "low"},
        portfolio_summary={"holding_count": 0},
        market_status="normal",
        trade_date="2026-07-21",
        validated_holdings=[],
        warnings=["warning"],
        limitations=["limitation"],
    )

    pipeline.final_assembly(state)

    assert state.result["account_action"]["action"] == "hold"
    assert state.result["portfolio_summary"] == {"holding_count": 0}
    assert state.result["market_status"] == "normal"
    assert state.result["trade_date"] == "2026-07-21"
    assert state.result["warnings"] == ["warning"]
    assert state.result["data_limitations"] == ["limitation"]


@pytest.mark.parametrize(
    ("explicit", "model_value", "expected"),
    [
        ("explicit-time", "model-time", "explicit-time"),
        (None, "model-time", "model-time"),
        (None, 123, ""),
    ],
)
def test_schema_stage_resolves_generated_at_priority(
    explicit, model_value, expected
) -> None:
    import portfolio_advice_pipeline as pipeline

    state = pipeline.PipelineState(
        ai_result={"generated_at": model_value, "holdings": []},
        context={"holdings": []},
        generated_at=explicit,
    )

    pipeline.schema_validation(state)

    assert state.resolved_generated_at == expected


def test_final_assembly_does_not_access_raw_pipeline_inputs() -> None:
    import portfolio_advice_pipeline as pipeline

    class FailOnAccess(dict):
        def get(self, *args, **kwargs):
            raise AssertionError("Final Assembly accessed raw state")

        def __bool__(self):
            raise AssertionError("Final Assembly inspected raw state")

    state = pipeline.PipelineState(
        ai_result=FailOnAccess(),
        context=FailOnAccess(),
        generated_at=None,
        ai_work=FailOnAccess(),
        resolved_generated_at="resolved-time",
        account_action={"action": "hold", "reason": "r", "confidence": "low"},
        portfolio_summary={"holding_count": 0},
        market_status="normal",
        trade_date="2026-07-21",
        validated_holdings=[],
        warnings=[],
        limitations=[],
    )

    pipeline.final_assembly(state)

    assert state.result["generated_at"] == "resolved-time"
