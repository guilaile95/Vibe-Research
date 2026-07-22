"""portfolio-advice-v0.1 Validator 兼容 Facade。

既有调用方可继续从本模块导入校验入口、错误类型和执行计算函数。
实际实现位于职责独立的 Policy、Pipeline 与 Audit 模块。
"""

from portfolio_advice_errors import PortfolioAdviceValidationError
from portfolio_advice_execution import (
    compute_add_execution_quantity,
    compute_estimated_amount,
    compute_execution_quantity,
    floor_to_lot,
)
from portfolio_advice_pipeline import validate_portfolio_advice


__all__ = [
    "PortfolioAdviceValidationError",
    "compute_add_execution_quantity",
    "compute_estimated_amount",
    "compute_execution_quantity",
    "floor_to_lot",
    "validate_portfolio_advice",
]
