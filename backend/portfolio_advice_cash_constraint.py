"""持仓建议加仓可用现金约束（确定性后端计算，不改模型 prompt、不写文件）。

在 attach_account_funding_metrics 之后，按账户「可用现金安全垫」约束
action=add 的 execution_quantity / estimated_amount。

语义（安全约定，非新策略）：
- spendable = available_cash * (1 - cash_reserve_pct)，默认 90% 可用现金可作建议加仓。
- cash_reserve_pct 是「可用现金安全垫」，**不是**「总资产现金仓位目标」，
  也**不得**表述为保留总资产 10%。
- 不修改 action / execution_size_pct_of_holding。
- 多笔 action=add：不按模型输出顺序静默瓜分现金；全部可执行数量置 null。
- 账户未配置：加仓方向保留，可执行数量/金额置 null。
"""

from __future__ import annotations

from typing import Any

from account_execution_policy import get_account_execution_policy
from portfolio_advice_contracts import LOT_SIZE
from portfolio_advice_execution import compute_estimated_amount, floor_to_lot
from portfolio_advice_policy import CASH_RESERVE_PCT

# 未配置账户：无法形成可执行加仓数量（方向性 action 仍保留）
_LIMITATION_UNCONFIGURED = "未配置账户资金，无法形成可执行加仓数量"
_LIMITATION_INSUFFICIENT = (
    "可用现金不足（已预留可用现金安全垫），本次加仓无法形成可执行数量"
)
_LIMITATION_ADJUSTED = "已按可用现金安全垫与可用现金下调加仓数量与金额"
_LIMITATION_ALLOCATED_BY_POLICY = "已按账户资金执行策略及代码字典序完成加仓资金分配"
_LIMITATION_MULTI_ADD = (
    "存在多个加仓方向，资金分配优先级无法由系统自动确定，可执行数量已置空，请人工决策分配"
)


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


def _funding_usable_cash(result: dict, policy: dict[str, Any] | None = None) -> tuple[bool, float | None]:
    """返回 (funding_valid, usable_cash)。

    funding 无效时 usable 为 None。
    有效时 usable = max(0, available_cash * (1 - reserve))，
    即「可用现金」扣除「可用现金安全垫」后的可建议花费额度
    （与总资产无关，不是总资产 10%）。
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

    pol = policy or get_account_execution_policy()
    reserve = float(pol.get("min_cash_reserve_pct", CASH_RESERVE_PCT))
    if reserve < 0 or reserve >= 1:
        reserve = float(CASH_RESERVE_PCT)
    # 可用现金安全垫：仅作用于 available_cash，非总资产比例
    usable = max(0.0, float(cash) * (1.0 - reserve))
    return True, usable


def _null_add_executables(holding: dict[str, Any]) -> dict[str, Any]:
    """清空加仓可执行数量/金额，保留 action 与方向性比例。"""
    h = dict(holding)
    h["execution_quantity"] = None
    h["estimated_amount"] = None
    return h


def apply_available_cash_constraints(result: dict) -> dict:
    """按可用现金与账户执行策略约束各 add 持仓的可执行数量与金额。

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

    policy = get_account_execution_policy()
    lot_unit = int(policy.get("lot_size", LOT_SIZE))

    top_limitations = list(result.get("data_limitations") or [])
    funding_valid, remaining = _funding_usable_cash(result, policy=policy)

    add_indices = [
        i
        for i, h in enumerate(holdings)
        if isinstance(h, dict) and h.get("action") == "add"
    ]
    has_add = len(add_indices) > 0
    multi_add = len(add_indices) > 1

    # 1) 账户未配置：方向保留，可执行数量/金额清空
    if not funding_valid:
        if has_add:
            new_holdings: list[Any] = []
            for item in holdings:
                if isinstance(item, dict) and item.get("action") == "add":
                    new_holdings.append(_null_add_executables(item))
                elif isinstance(item, dict):
                    new_holdings.append(dict(item))
                else:
                    new_holdings.append(item)
            result["holdings"] = new_holdings
            _append_limitation(top_limitations, _LIMITATION_UNCONFIGURED)
            result["data_limitations"] = top_limitations
        return result

    assert remaining is not None
    new_holdings = [dict(h) if isinstance(h, dict) else h for h in holdings]

    # 2) 多笔加仓：不按顺序静默瓜分现金，全部可执行数量/金额置 null
    if multi_add:
        for idx in add_indices:
            item = new_holdings[idx]
            if not isinstance(item, dict):
                continue
            item["execution_quantity"] = None
            item["estimated_amount"] = None
        _append_limitation(top_limitations, _LIMITATION_MULTI_ADD)
        result["holdings"] = new_holdings
        result["data_limitations"] = top_limitations
        return result

    # 3) 单笔加仓：按可用现金约束
    for idx in add_indices:
        item = new_holdings[idx]
        if not isinstance(item, dict):
            continue

        amount = _resolve_add_amount(item)
        if amount is None:
            continue

        if amount <= remaining:
            remaining -= amount
            continue

        # 超额：按现价向下取整到整手
        price = item.get("current_price")
        holding_lims = list(item.get("data_limitations") or [])
        if not _is_valid_positive_number(price):
            item["execution_quantity"] = None
            item["estimated_amount"] = None
            _append_limitation(holding_lims, _LIMITATION_INSUFFICIENT)
            item["data_limitations"] = holding_lims
            continue

        max_qty = floor_to_lot(remaining / float(price), lot=lot_unit)
        if max_qty < lot_unit:
            item["execution_quantity"] = None
            item["estimated_amount"] = None
            _append_limitation(holding_lims, _LIMITATION_INSUFFICIENT)
            item["data_limitations"] = holding_lims
            continue

        new_amount = compute_estimated_amount(max_qty, float(price))
        item["execution_quantity"] = max_qty
        item["estimated_amount"] = new_amount
        _append_limitation(holding_lims, _LIMITATION_ADJUSTED)
        item["data_limitations"] = holding_lims
        if new_amount is not None and new_amount > 0:
            remaining = max(0.0, remaining - float(new_amount))

    result["holdings"] = new_holdings
    result["data_limitations"] = top_limitations
    return result
