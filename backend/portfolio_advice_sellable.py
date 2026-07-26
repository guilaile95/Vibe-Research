"""持仓建议「理论建议卖出数量（非券商可卖数量）」标注。

在现金约束之后追加：
- holding 级 sellable_quantity_advisory = min(建议数量, 持股数)
- 顶层 data_limitations 说明：理论值，非券商可卖 / 无 T+1 明细

语义（advisory only）：
- 公式仅为 min(execution_quantity, shares)，不做 T+1、不做券商冻结股计算。
- 不得单独表述为「可卖数量」；必须标明理论建议、非券商可卖。
- 不修改 execution_quantity。
"""

from __future__ import annotations

from typing import Any

from portfolio_advice_cash_constraint import _append_limitation

# 用户可见：明确理论建议卖出数量，非券商可卖数量
_LIMITATION_ADVISORY = (
    "理论建议卖出数量（非券商可卖数量）：系统无券商可卖与 T+1 明细，"
    "sellable_quantity_advisory 仅为 min(建议数量, 持股数) 的理论值，执行前请以券商可卖为准"
)

_REDUCE_SELL_ACTIONS = frozenset({"reduce", "sell"})


def _is_non_bool_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and value == value
        and value not in (float("inf"), float("-inf"))
    )


def _as_non_negative_int(value: Any) -> int | None:
    """将持仓股数等转为非负 int；无效则 None。"""
    if not _is_non_bool_number(value):
        return None
    if float(value) < 0:
        return None
    return int(value)


def _normalize_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip()
    return code or None


def _closed_same_day_codes(
    portfolio_data: Any,
    trade_date: Any,
) -> set[str]:
    """portfolio.closed 中清仓日期等于建议 trade_date 的 code 集合。

    当日清仓记录仅作「信息不足」标记；不改变 advisory 计算公式，
    也不假装可精确推算 T+1 / 券商可卖。
    """
    if not isinstance(portfolio_data, dict):
        return set()
    if not isinstance(trade_date, str) or not trade_date.strip():
        return set()
    day = trade_date.strip()
    closed = portfolio_data.get("closed")
    if not isinstance(closed, list):
        return set()

    codes: set[str] = set()
    for row in closed:
        if not isinstance(row, dict):
            continue
        code = _normalize_code(row.get("code"))
        if code is None:
            continue
        # closed 记录字段为 date（见 portfolio.close_position）
        close_date = row.get("date")
        if isinstance(close_date, str) and close_date.strip() == day:
            codes.add(code)
    return codes


def _compute_advisory(
    *,
    execution_quantity: Any,
    shares: Any,
) -> int | None:
    """理论建议卖出数量（非券商可卖数量）= min(execution_quantity, shares)。

    数量空则 null。无 T+1、无券商冻结股逻辑。
    """
    h = _as_non_negative_int(shares)
    if h is None:
        return None
    qty = execution_quantity
    if qty is None:
        return None
    if not _is_non_bool_number(qty):
        return None
    q = int(qty)
    if q < 0:
        return None
    return min(q, h)


def apply_sellable_quantity_advisory(
    result: dict,
    portfolio_data: dict | None = None,
) -> dict:
    """为 reduce/sell 持仓追加 sellable_quantity_advisory，并写顶层 limitation。

    Parameters
    ----------
    result
        已经过校验与现金约束的权威建议 dict（就地修改并返回）。
    portfolio_data
        本地持仓（含 closed）；用于识别当日清仓等不足信息，不改变公式。

    Returns
    -------
    dict
        追加 advisory 字段后的结果。不修改 execution_quantity。

    Notes
    -----
    sellable_quantity_advisory 是「理论建议卖出数量（非券商可卖数量）」，
    公式 min(建议数量, 持股数)，不得当作券商真实可卖。
    """
    if not isinstance(result, dict):
        return result

    holdings = result.get("holdings")
    if not isinstance(holdings, list):
        return result

    trade_date = result.get("trade_date")
    same_day_closed = _closed_same_day_codes(portfolio_data, trade_date)

    top_limitations = list(result.get("data_limitations") or [])
    new_holdings: list[Any] = []
    need_top_limitation = False

    for item in holdings:
        if not isinstance(item, dict):
            new_holdings.append(item)
            continue

        h = dict(item)
        action = h.get("action")
        if action not in _REDUCE_SELL_ACTIONS:
            # 非减仓/卖出不挂 advisory 字段，避免前端误读为券商可卖
            h.pop("sellable_quantity_advisory", None)
            new_holdings.append(h)
            continue

        need_top_limitation = True
        code = _normalize_code(h.get("code"))
        # 当日 closed 同 code：信息不足，公式仍用 min(qty, H)，不假装精确
        _ = code is not None and code in same_day_closed

        shares = h.get("shares")
        # 兼容 facts.shares（若未来/测试注入）
        facts = h.get("facts")
        if isinstance(facts, dict) and "shares" in facts:
            shares = facts.get("shares")

        advisory = _compute_advisory(
            execution_quantity=h.get("execution_quantity"),
            shares=shares,
        )
        h["sellable_quantity_advisory"] = advisory
        # 不改 execution_quantity
        new_holdings.append(h)

    if need_top_limitation:
        _append_limitation(top_limitations, _LIMITATION_ADVISORY)

    result["holdings"] = new_holdings
    result["data_limitations"] = top_limitations
    return result
