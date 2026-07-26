"""portfolio-advice-v0.1 投资政策唯一代码来源。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from portfolio_advice_contracts import CONFIDENCE_LEVELS


POLICY_VERSION = "portfolio-policy-v0.1"


@dataclass(frozen=True)
class PortfolioAdvicePolicy:
    """持仓建议比例、置信度和 partial 市场约束。"""

    version: str
    add_tiers: frozenset[float]
    reduce_tiers: frozenset[float]
    sell_tier: float
    confidence_caps: Mapping[str, float]
    partial_market_add_max: float
    partial_market_reduce_max: float
    cash_reserve_pct: float


ADD_TIERS: frozenset[float] = frozenset({10.0, 20.0})
REDUCE_TIERS: frozenset[float] = frozenset({10.0, 20.0, 30.0})
SELL_TIER: float = 100.0
CONFIDENCE_CAP: Mapping[str, float] = MappingProxyType(
    {
        "low": 10.0,
        "medium": 20.0,
        "high": 30.0,
    }
)
PARTIAL_MARKET_ADD_MAX: float = 10.0
PARTIAL_MARKET_REDUCE_MAX: float = 20.0
#: 可用现金安全垫比例：spendable = 可用现金 * (1 - 该值)。
#: 仅作用于「可用现金」，不是总资产现金仓位目标，也不是「保留总资产 10%」。
CASH_RESERVE_PCT: float = 0.10


if set(CONFIDENCE_CAP) != set(CONFIDENCE_LEVELS):
    raise RuntimeError("Policy confidence caps must cover every confidence level")


POLICY = PortfolioAdvicePolicy(
    version=POLICY_VERSION,
    add_tiers=ADD_TIERS,
    reduce_tiers=REDUCE_TIERS,
    sell_tier=SELL_TIER,
    confidence_caps=CONFIDENCE_CAP,
    partial_market_add_max=PARTIAL_MARKET_ADD_MAX,
    partial_market_reduce_max=PARTIAL_MARKET_REDUCE_MAX,
    cash_reserve_pct=CASH_RESERVE_PCT,
)
