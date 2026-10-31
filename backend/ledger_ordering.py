"""Shared financial replay order (not exchange execution priority).

Trades replay by UTC execution instant, UTC recording instant, then immutable
trade_id. Recording order breaks equal execution times without treating UUIDs as
creation order; trade_id is the deterministic final tie breaker. Legacy opening
positions remain a separate, preceding phase. Corrections change economic fields,
not identity/order. No stored trade, performance snapshot or outcome is rewritten.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def _utc_instant(value: Any) -> datetime:
    instant = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("ledger ordering timestamp requires timezone")
    return instant.astimezone(timezone.utc)


def trade_order_key(trade: Mapping[str, Any]) -> tuple[datetime, datetime, str]:
    """Total order shared by canonical holdings and performance attribution."""
    return (
        _utc_instant(trade.get("executed_at") or trade.get("created_at")),
        _utc_instant(trade.get("created_at")),
        str(trade["trade_id"]),
    )
