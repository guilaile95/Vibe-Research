"""持仓建议加仓可用现金约束（确定性后端计算，不改模型 prompt、不写文件）。

在 attach_account_funding_metrics 之后，按账户可用现金与现金安全垫，
约束 action=add 的 execution_quantity / estimated_amount。
不修改 action 字段。
"""

from __future__ import annotations

from typing import Any

from portfolio_advice_contracts import LOT_SIZE
from portfolio_advice_execution import compute_estimated_amount, floor_to_lot
from portfolio_advice_policy import CASH_RESERVE_PCT, POLICY

_LIMITATION_UNCONFIGURED = "账户资金未配置，加仓金额未校验可用现金"
_LIMITATION_INSUFFICIENT = (
    "可用现金不足（已预留现金安全垫），本次加仓无法形成可执行数量"
)
_LIMITATION_ADJUSTED = "已按现金安全垫与可用现金下调加仓数量与金额"


def _is_valid_positive_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and value > 0
        and value == value
        and value not in (float("inf"), float("-inf"))
    )


def _append_limitation(target: list[str], message: str) -> None:
    if message not in target:
        target.append(message)


def _resolve_add_amount(holding: dict[str, Any]) -> float | None:
    """解析加仓预估金额；缺失时尝试用数量×现价回算。"""
    amount = holding.get("estimated_amount")
    if _is_valid_positive_number(amount):
        return float(amount)

    qty = holding.get("execution_quantity")
    price = holding.get("current_price")
    if (
        isinstance(qty, (int, float))
        and not isinstance(qty, bool)
        and qty is not None
        and int(qty) > 0
        and _is_valid_positive_number(price)
    ):
        computed = compute_estimated_amount(int(qty), float(price))
        if computed is not None and computed > 0:
            return float(computed)
    return None


def _funding_usable_cash(result: dict) -> tuple[bool, float | None]:
    """返回 (funding_valid, usable_cash)。

    funding 无效时 usable 为 None；有效时 usable = max(0, cash * (1 - reserve)).
    """
    funding = result.get("account_funding")
    if not isinstance(funding, dict):
        return False, None
    if funding.get("configured") is not True:
        return False, None
    cash = funding.get("available_cash")
    if (
        isinstance(cash, bool)
        or not isinstance(cash, (int, float))
        or cash != cash
        or cash in (float("inf"), float("-inf"))
        or cash < 0
    ):
        return False, None

    reserve = float(getattr(POLICY, "cash_reserve_pct", CASH_RESERVE_PCT))
    if reserve < 0 or reserve >= 1:
        reserve = float(CASH_RESERVE_PCT)
    usable = max(0.0, float(cash) * (1.0 - reserve))
    return True, usable


def apply_available_cash_constraints(result: dict) -> dict:
    """按可用现金约束各 add 持仓的可执行数量与金额。

    Parameters
    ----------
    result
        已注入 account_funding 的权威建议 dict（就地修改并返回）。

    Returns
    -------
    dict
        约束后的结果。action / execution_size_pct_of_holding 不变。
    """
    if not isinstance(result, dict):
        return result

    holdings = result.get("holdings")
    if not isinstance(holdings, list):
        return result

    top_limitations = list(result.get("data_limitations") or [])
    funding_valid, remaining = _funding_usable_cash(result)

    has_add = any(
        isinstance(h, dict) and h.get("action") == "add" for h in holdings
    )
    if not funding_valid:
        if has_add:
            _append_limitation(top_limitations, _LIMITATION_UNCONFIGURED)
            result["data_limitations"] = top_limitations
        return result

    assert remaining is not None
    new_holdings: list[Any] = []
    for item in holdings:
        if not isinstance(item, dict):
            new_holdings.append(item)
            continue

        h = dict(item)
        if h.get("action") != "add":
            new_holdings.append(h)
            continue

        amount = _resolve_add_amount(h)
        if amount is None:
            # 无金额可约束（数量本就不可执行），不消耗额度
            new_holdings.append(h)
            continue

        if amount <= remaining:
            remaining -= amount
            new_holdings.append(h)
            continue

        # 超额：按现价向下取整到整手
        price = h.get("current_price")
        holding_lims = list(h.get("data_limitations") or [])
        if not _is_valid_positive_number(price):
            h["execution_quantity"] = None
            h["estimated_amount"] = None
            _append_limitation(holding_lims, _LIMITATION_INSUFFICIENT)
            h["data_limitations"] = holding_lims
            new_holdings.append(h)
            continue

        max_qty = floor_to_lot(remaining / float(price), lot=LOT_SIZE)
        if max_qty < LOT_SIZE:
            h["execution_quantity"] = None
            h["estimated_amount"] = None
            _append_limitation(holding_lims, _LIMITATION_INSUFFICIENT)
            h["data_limitations"] = holding_lims
            new_holdings.append(h)
            continue

        new_amount = compute_estimated_amount(max_qty, float(price))
        h["execution_quantity"] = max_qty
        h["estimated_amount"] = new_amount
        _append_limitation(holding_lims, _LIMITATION_ADJUSTED)
        h["data_limitations"] = holding_lims
        if new_amount is not None and new_amount > 0:
            remaining = max(0.0, remaining - float(new_amount))
        new_holdings.append(h)

    result["holdings"] = new_holdings
    result["data_limitations"] = top_limitations
    return result
