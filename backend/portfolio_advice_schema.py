"""portfolio-advice-v0.1 基础 Schema 校验与值清洗。"""

from __future__ import annotations

import copy
import math
from typing import Any

from portfolio_advice_contracts import ACTIONS, CONFIDENCE_LEVELS
from portfolio_advice_errors import PortfolioAdviceValidationError


CONDITION_FIELDS = (
    "trigger_conditions",
    "price_conditions",
    "execution_plan",
    "risk_conditions",
    "invalidation_conditions",
)


def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def num_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    return None


def safe_float(value: Any, default: float = 0.0) -> float:
    number = num_or_none(value)
    return default if number is None else number


def round2(value: float) -> float:
    return round(value, 2)


def dedupe_str_list(items: list[str]) -> list[str]:
    """稳定去重：完全相同文案只保留首次出现。"""
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def str_list(value: Any) -> list[str]:
    output: list[str] = []
    for item in as_list(value):
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
        elif item is not None and not isinstance(item, str):
            text = str(item).strip()
            if text:
                output.append(text)
    return dedupe_str_list(output)


def append_unique(items: list[str], message: str) -> None:
    if message and message not in items:
        items.append(message)


def normalize_pct(value: Any) -> float | None:
    if value is None:
        return None
    number = num_or_none(value)
    if number is None:
        raise PortfolioAdviceValidationError(
            f"execution_size_pct_of_holding 非法：{value!r}"
        )
    if number < 0 or number > 100:
        raise PortfolioAdviceValidationError(
            f"execution_size_pct_of_holding 必须在 0—100，收到：{number}"
        )
    return float(number)


def validate_inputs(ai_result: Any, context: Any) -> tuple[dict, dict]:
    if not isinstance(ai_result, dict):
        raise PortfolioAdviceValidationError("ai_result 必须是字典")
    if not isinstance(context, dict):
        raise PortfolioAdviceValidationError("context 必须是字典")
    return copy.deepcopy(ai_result), context


def normalize_holding_schema(ai_holding: dict, code: str) -> dict:
    """校验单条模型建议的枚举并清洗条件字段。"""
    action = ai_holding.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise PortfolioAdviceValidationError(
            f"非法 action：{action!r}（code={code}）"
        )
    confidence = ai_holding.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "low"
    conditions = {
        field: str_list(ai_holding.get(field)) for field in CONDITION_FIELDS
    }
    return {
        "raw": ai_holding,
        "code": code,
        "action": action,
        "confidence": confidence,
        "conditions": conditions,
        "data_limitations": str_list(ai_holding.get("data_limitations")),
    }


def normalize_matching_holdings(ai_work: dict, context_codes: set[str]) -> dict[str, dict]:
    """只校验上下文中的持仓；额外模型代码沿用旧行为直接忽略。"""
    by_code: dict[str, dict] = {}
    for holding in as_list(ai_work.get("holdings")):
        if not isinstance(holding, dict):
            continue
        code = str(holding.get("code") or "").strip()
        if code and code in context_codes:
            by_code[code] = normalize_holding_schema(holding, code)
    return by_code
