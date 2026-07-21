"""持仓操作建议公共契约——策略常量唯一来源。

本模块定义 portfolio-advice-v0.1 的所有策略枚举与规则常量。
任何模块若需要这些常量，应从本模块导入，而非从 prompt 或 validator 导入。

依赖关系（重构后）：
    portfolio_advice_contracts  ← 任何人都可以依赖
        ↑
    portfolio_advice_prompt     (re-export，保持向后兼容)
    portfolio_advice_validator  (取代原来对 prompt 的导入)
    portfolio_advice_account_metrics
    portfolio_advice_service

本模块不包含任何 Prompt 文本、HTTP 逻辑、IO 操作或模型调用。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 输出 Schema 版本
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "portfolio-advice-v0.1"

# ---------------------------------------------------------------------------
# 动作枚举
# ---------------------------------------------------------------------------

#: 持仓级操作动作（add/hold/reduce/sell/watch/avoid）
ACTIONS: tuple[str, ...] = (
    "add",
    "hold",
    "reduce",
    "sell",
    "watch",
    "avoid",
)

#: 账户级操作倾向（hold/reduce_risk/selective_add/defensive）
ACCOUNT_ACTIONS: tuple[str, ...] = (
    "hold",
    "reduce_risk",
    "selective_add",
    "defensive",
)

#: 置信度等级
CONFIDENCE_LEVELS: frozenset[str] = frozenset({"high", "medium", "low"})

# ---------------------------------------------------------------------------
# 策略规则（Tier Policy）
# ---------------------------------------------------------------------------

#: add 动作允许的档位比例（%）——正常市场
ADD_TIERS: frozenset[float] = frozenset({10.0, 20.0})

#: reduce 动作允许的档位比例（%）——正常市场
REDUCE_TIERS: frozenset[float] = frozenset({10.0, 20.0, 30.0})

#: sell 动作固定比例（%）
SELL_TIER: float = 100.0

#: 置信度对应的单票操作比例上限（%）
CONFIDENCE_CAP: dict[str, float] = {
    "low": 10.0,
    "medium": 20.0,
    "high": 30.0,
}

#: partial 市场时 add 最大比例（%）
PARTIAL_MARKET_ADD_MAX: float = 10.0

#: partial 市场时 reduce 最大比例（%）
PARTIAL_MARKET_REDUCE_MAX: float = 20.0

# ---------------------------------------------------------------------------
# 交易单位
# ---------------------------------------------------------------------------

#: A 股标准交易单位（100 股/手）
LOT_SIZE: int = 100
