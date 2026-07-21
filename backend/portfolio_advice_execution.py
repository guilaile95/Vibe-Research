"""持仓建议执行数量与金额计算。"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from portfolio_advice_contracts import LOT_SIZE
from portfolio_advice_schema import num_or_none


def floor_to_lot(quantity: float, lot: int = LOT_SIZE) -> int:
    """向下取整到交易单位（默认 100 股）。负数归零。"""
    if lot <= 0:
        raise ValueError("lot 必须为正整数")
    if quantity is None:
        return 0
    value = float(quantity)
    if value <= 0:
        return 0
    return int(value // lot) * lot


def compute_execution_quantity(
    shares: float,
    size_pct: float | None,
    *,
    lot: int = LOT_SIZE,
) -> int | None:
    """reduce/sell：按持股比例向下取整，且不超过持股数。"""
    if size_pct is None:
        return None
    pct = min(max(float(size_pct), 0.0), 100.0)
    quantity = floor_to_lot(float(shares) * pct / 100.0, lot=lot)
    if quantity > float(shares):
        quantity = floor_to_lot(float(shares), lot=lot)
    return quantity


def compute_add_execution_quantity(
    shares: float | None,
    size_pct: float | None,
    *,
    lot: int = LOT_SIZE,
) -> int | None:
    """add：按持股比例向下取整；不足一个交易单位返回 None。"""
    if size_pct is None or shares is None:
        return None
    share_count = float(shares)
    pct = float(size_pct)
    if share_count <= 0 or not math.isfinite(share_count):
        return None
    if pct <= 0 or not math.isfinite(pct):
        return None
    quantity = floor_to_lot(share_count * pct / 100.0, lot=lot)
    return quantity if quantity >= lot else None


def compute_estimated_amount(
    quantity: int | None,
    current_price: float | None,
) -> float | None:
    """数量乘当前价，按 ROUND_HALF_UP 精确到分。"""
    if quantity is None or quantity <= 0 or current_price is None:
        return None
    try:
        price = Decimal(str(current_price))
    except Exception:  # noqa: BLE001
        return None
    if price <= 0:
        return None
    amount = (Decimal(int(quantity)) * price).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(amount)


def calculate_execution(
    action: str,
    size_pct: float | None,
    facts: dict[str, Any],
    context_holding: dict,
) -> dict[str, Any]:
    """覆盖模型数量和金额，并返回 narrative 所需的缺失标记。"""
    result = {
        "execution_quantity": None,
        "estimated_amount": None,
        "add_shares_missing": False,
        "add_price_missing": False,
        "add_lot_insufficient": False,
    }
    if action in ("hold", "watch", "avoid"):
        return result
    if action in ("reduce", "sell"):
        quantity = compute_execution_quantity(facts["shares"], size_pct)
        if quantity is not None and quantity > facts["shares"]:
            quantity = floor_to_lot(facts["shares"])
        result["execution_quantity"] = quantity
        return result

    shares = num_or_none(context_holding.get("shares"))
    price = num_or_none(context_holding.get("current_price"))
    if shares is not None and shares <= 0:
        shares = None
    if price is not None and price <= 0:
        price = None
    if shares is None:
        result["add_shares_missing"] = True
        return result

    quantity = compute_add_execution_quantity(shares, size_pct)
    result["execution_quantity"] = quantity
    if quantity is None:
        result["add_lot_insufficient"] = True
        return result
    if price is None:
        result["add_price_missing"] = True
        return result
    amount = compute_estimated_amount(quantity, price)
    result["estimated_amount"] = amount
    if amount is None:
        result["add_price_missing"] = True
    return result
