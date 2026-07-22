"""持仓操作建议公共契约。

本模块只定义 portfolio-advice-v0.1 的 Schema、枚举和交易单位。
投资比例与置信度政策由 ``portfolio_advice_policy`` 唯一定义。

依赖关系（重构后）：
    portfolio_advice_contracts  ← 中立契约
        ↑
    portfolio_advice_policy
        ↑
    portfolio_advice_prompt / portfolio_advice_pipeline
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
# 交易单位
# ---------------------------------------------------------------------------

#: A 股标准交易单位（100 股/手）
LOT_SIZE: int = 100
