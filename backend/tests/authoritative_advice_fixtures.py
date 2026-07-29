"""Shared helpers to build authoritative portfolio advice for decision-trace tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from portfolio_advice_account_metrics import attach_account_funding_metrics
from portfolio_advice_cash_constraint import apply_available_cash_constraints
from portfolio_advice_sellable import apply_sellable_quantity_advisory
from portfolio_advice_validator import validate_portfolio_advice

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "portfolio_advice"


def load_golden(name: str) -> dict[str, Any]:
    path = _FIXTURE_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def portfolio_data_from_context(context: dict[str, Any]) -> dict[str, Any]:
    holdings = []
    for h in context.get("holdings") or []:
        if not isinstance(h, dict):
            continue
        holdings.append(
            {
                "code": h.get("code"),
                "name": h.get("name"),
                "shares": h.get("shares"),
                "cost": h.get("cost_price"),
                "price": h.get("current_price"),
            }
        )
    return {"holdings": holdings, "closed": []}


def patch_account_profile(monkeypatch, *, configured: bool = True) -> None:
    import account_profile

    if configured:
        status = {
            "status": "valid",
            "data": {
                "total_assets": 500000.0,
                "available_cash": 100000.0,
                "updated_at": "2026-07-29T09:00:00+00:00",
            },
        }
    else:
        status = {"status": "missing", "data": None}

    monkeypatch.setattr(account_profile, "get_account_profile_status", lambda: status)


def build_authoritative_from_golden(
    monkeypatch,
    golden_name: str = "s05_reduce_high_conf_normal_input.json",
    *,
    configured: bool = True,
) -> dict[str, Any]:
    """validate → funding → cash → sellable using real production modules."""
    patch_account_profile(monkeypatch, configured=configured)
    payload = load_golden(golden_name)
    ai_result = payload["ai_result"]
    context = payload["context"]
    # ensure trade_date present for decision_run_id
    if not ai_result.get("trade_date"):
        review_td = (
            (context.get("market_context") or {})
            .get("review_metadata", {})
            .get("trade_date")
        )
        ai_result = dict(ai_result)
        ai_result["trade_date"] = review_td or "2026-07-21"
        ai_result["generated_at"] = ai_result.get("generated_at") or "2026-07-21T15:00:00"

    validated = validate_portfolio_advice(ai_result, context)
    portfolio = portfolio_data_from_context(context)
    authoritative = attach_account_funding_metrics(validated, portfolio)
    authoritative = apply_available_cash_constraints(authoritative)
    authoritative = apply_sellable_quantity_advisory(authoritative, portfolio)
    return authoritative
