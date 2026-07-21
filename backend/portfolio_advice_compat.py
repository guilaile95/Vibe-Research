"""portfolio-advice-v0.1 Legacy fallback 兼容层。

这些 fallback 仅用于保持既有输出，不代表新增投资判断：
模型遗漏持仓仍合成为 watch；非法账户动作仍回落为 hold。
"""

from __future__ import annotations

from typing import Any

from portfolio_advice_contracts import ACCOUNT_ACTIONS, CONFIDENCE_LEVELS
from portfolio_advice_schema import as_dict, normalize_holding_schema


def synthesize_missing_holding(code: str) -> dict:
    return normalize_holding_schema(
        {
            "code": code,
            "action": "watch",
            "confidence": "low",
            "trigger_conditions": ["模型未返回该持仓建议"],
            "price_conditions": [],
            "execution_plan": ["暂不操作，等待补全建议"],
            "risk_conditions": ["建议不完整"],
            "invalidation_conditions": ["获得完整建议后重新评估"],
            "data_limitations": ["模型未覆盖该持仓"],
        },
        code,
    )


def align_holdings(
    context_index: dict[str, dict],
    normalized_by_code: dict[str, dict],
) -> list[dict]:
    return [
        {
            "schema": normalized_by_code.get(code)
            or synthesize_missing_holding(code),
            "context_holding": context_holding,
        }
        for code, context_holding in context_index.items()
    ]


def normalize_account_action(raw: Any) -> dict[str, str]:
    data = as_dict(raw)
    action = data.get("action")
    if action not in ACCOUNT_ACTIONS:
        return {
            "action": "hold",
            "reason": str(
                data.get("reason") or "账户动作非法，已回落为 hold"
            ).strip(),
            "confidence": "low",
        }
    confidence = data.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "low"
    return {
        "action": action,
        "reason": str(data.get("reason") or "").strip(),
        "confidence": confidence,
    }
