"""以 Context 为权威源重算持仓与账户汇总事实。"""

from __future__ import annotations

from typing import Any

from portfolio_advice_schema import as_dict, as_list, num_or_none, round2, safe_float


def context_holdings_index(context: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for holding in as_list(context.get("holdings")):
        if not isinstance(holding, dict):
            continue
        code = str(holding.get("code") or "").strip()
        if code:
            index[code] = holding
    return index


def reconcile_holding_facts(context_holding: dict) -> dict[str, Any]:
    shares = safe_float(context_holding.get("shares"), 0.0)
    cost = safe_float(context_holding.get("cost_price"), 0.0)
    price = safe_float(context_holding.get("current_price"), 0.0)
    market_value = round2(price * shares)
    cost_value = cost * shares
    pnl = round2(market_value - cost_value)
    pnl_pct = round2(pnl / cost_value * 100) if cost_value else 0.0
    weight = num_or_none(context_holding.get("holding_weight_pct"))
    return {
        "code": str(context_holding.get("code") or "").strip(),
        "name": str(
            context_holding.get("name") or context_holding.get("code") or ""
        ),
        "shares": shares,
        "cost_price": cost,
        "current_price": price,
        "market_value": market_value,
        "pnl_amount": pnl,
        "pnl_pct": pnl_pct,
        "holding_weight_pct": float(weight if weight is not None else 0.0),
    }


def market_status_from_context(context: dict) -> str:
    review_metadata = as_dict(as_dict(context.get("market_context")).get("review_metadata"))
    status = review_metadata.get("status")
    if isinstance(status, str) and status:
        return status
    evidence_status = as_dict(context.get("market_evidence")).get("review_status")
    return evidence_status if isinstance(evidence_status, str) and evidence_status else ""


def market_is_partial(context: dict) -> bool:
    return market_status_from_context(context) == "partial"


def portfolio_summary_from_context(context: dict) -> dict[str, Any]:
    source_summary = as_dict(context.get("portfolio_summary"))
    holdings = as_list(context.get("holdings"))
    if holdings:
        market_value = round2(
            sum(
                safe_float(holding.get("market_value"))
                for holding in holdings
                if isinstance(holding, dict)
            )
        )
        cost = round2(
            sum(
                safe_float(holding.get("cost_price"))
                * safe_float(holding.get("shares"))
                for holding in holdings
                if isinstance(holding, dict)
            )
        )
        pnl = round2(market_value - cost)
        return {
            "holding_count": len(
                [
                    holding
                    for holding in holdings
                    if isinstance(holding, dict) and holding.get("code")
                ]
            ),
            "market_value": market_value,
            "cost": cost,
            "pnl": pnl,
            "pnl_pct": round2(pnl / cost * 100) if cost else 0.0,
        }
    return {
        "holding_count": int(safe_float(source_summary.get("holding_count"), 0)),
        "market_value": round2(safe_float(source_summary.get("market_value"), 0)),
        "cost": round2(safe_float(source_summary.get("cost"), 0)),
        "pnl": round2(safe_float(source_summary.get("pnl"), 0)),
        "pnl_pct": round2(safe_float(source_summary.get("pnl_pct"), 0)),
    }


def trade_date_from_context(context: dict) -> str | None:
    candidates = (
        as_dict(context.get("portfolio_meta")).get("trade_date"),
        as_dict(context.get("market_evidence")).get("trade_date"),
        as_dict(as_dict(context.get("market_context")).get("review_metadata")).get(
            "trade_date"
        ),
    )
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
