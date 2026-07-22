"""持仓建议动作比例、置信度和 partial 市场政策审核。"""

from __future__ import annotations

from typing import Any

from portfolio_advice_errors import PortfolioAdviceValidationError
from portfolio_advice_policy import POLICY, PortfolioAdvicePolicy
from portfolio_advice_schema import normalize_pct


def _format_policy_values(values: frozenset[float], separator: str = "/") -> str:
    return separator.join(
        str(int(value)) if float(value).is_integer() else str(value)
        for value in sorted(values)
    )


def audit_execution_size(
    action: str,
    raw_pct: Any,
    *,
    confidence: str,
    market_partial: bool,
    code: str,
    policy: PortfolioAdvicePolicy = POLICY,
) -> float | None:
    """校验 action 对应比例，返回规范后的持股操作比例。"""
    if action in ("hold", "watch", "avoid"):
        return None
    if action == "sell":
        if raw_pct is not None:
            number = normalize_pct(raw_pct)
            if number is not None and abs(number - policy.sell_tier) > 1e-6:
                raise PortfolioAdviceValidationError(
                    f"sell 比例必须为 {_format_policy_values(frozenset({policy.sell_tier}))}，"
                    f"收到 {number}（code={code}）"
                )
        return policy.sell_tier
    if raw_pct is None:
        tiers = _format_policy_values(
            policy.add_tiers if action == "add" else policy.reduce_tiers
        )
        raise PortfolioAdviceValidationError(
            f"{action} 必须给出档位比例 {tiers}（code={code}）"
        )

    tier = normalize_pct(raw_pct)
    assert tier is not None
    if action == "add":
        allowed = set(policy.add_tiers)
        if market_partial:
            allowed = {
                value
                for value in allowed
                if value <= policy.partial_market_add_max
            }
    else:
        allowed = set(policy.reduce_tiers)
        if market_partial:
            allowed = {
                value
                for value in allowed
                if value <= policy.partial_market_reduce_max
            }
    if tier not in allowed:
        raise PortfolioAdviceValidationError(
            f"{action} 比例仅允许 {sorted(int(value) for value in allowed)}，"
            f"收到 {tier}（code={code}）"
        )

    normalized_confidence = (
        confidence if confidence in policy.confidence_caps else "low"
    )
    cap = policy.confidence_caps[normalized_confidence]
    if market_partial and action == "add":
        cap = min(cap, policy.partial_market_add_max)
    if market_partial and action == "reduce":
        cap = min(cap, policy.partial_market_reduce_max)
    if tier > cap:
        raise PortfolioAdviceValidationError(
            f"{action} 比例 {tier} 超过置信度 {normalized_confidence} "
            f"上限 {int(cap)}（code={code}）"
        )
    return tier
