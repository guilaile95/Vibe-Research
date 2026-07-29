"""Internal adapter: authoritative portfolio advice → decision-trace fields.

Not a second validator or business layer. Only field extraction / normalization
for Signal Ledger and Decision Evidence archive services.
"""

from __future__ import annotations

from typing import Any, Mapping

REASON_FALLBACK = "结构化执行条件已归档"
REASON_SOURCES = (
    "execution_plan",
    "trigger_conditions",
    "risk_conditions",
    "invalidation_conditions",
    "data_limitations",
)

CONDITION_COUNT_KEYS = (
    "trigger_conditions",
    "price_conditions",
    "execution_plan",
    "risk_conditions",
    "invalidation_conditions",
    "data_limitations",
)


def iter_authoritative_holdings(advice_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    holdings = advice_result.get("holdings")
    if not isinstance(holdings, list):
        return []
    out: list[dict[str, Any]] = []
    for item in holdings:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        out.append(item)
    return out


def execution_size_to_target_ratio(execution_size_pct_of_holding: Any) -> float | None:
    """Map execution_size_pct_of_holding (0-100) to target_ratio fraction (0-1)."""
    if execution_size_pct_of_holding is None:
        return None
    try:
        return float(execution_size_pct_of_holding) / 100.0
    except (TypeError, ValueError):
        return None


def _append_text_parts(parts: list[str], value: Any, *, max_parts: int) -> bool:
    """Append non-empty strings from value into parts. Return True if full."""
    if isinstance(value, list):
        for item in value:
            text = str(item).strip() if item is not None else ""
            if not text:
                continue
            parts.append(text)
            if len(parts) >= max_parts:
                return True
    elif isinstance(value, str):
        text = value.strip()
        if text:
            parts.append(text)
            if len(parts) >= max_parts:
                return True
    return False


def summarize_holding_reason(holding: Mapping[str, Any], *, max_parts: int = 3) -> str:
    """Deterministic reason from structured condition lists. No model call."""
    parts: list[str] = []
    for key in REASON_SOURCES:
        if _append_text_parts(parts, holding.get(key), max_parts=max_parts):
            break
    return "；".join(parts) if parts else REASON_FALLBACK


def count_condition_fields(holding: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in CONDITION_COUNT_KEYS:
        value = holding.get(key)
        if isinstance(value, list):
            counts[f"{key}_count"] = len(value)
        elif isinstance(value, str) and value.strip():
            counts[f"{key}_count"] = 1
        else:
            counts[f"{key}_count"] = 0
    return counts


def parse_account_funding(
    advice_result: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """Return (funding_dict_or_None, quality_status).

    quality: valid | partial | missing
    """
    if "account_funding" not in advice_result:
        return None, "missing"
    funding = advice_result.get("account_funding")
    if not isinstance(funding, dict):
        return None, "missing"
    if funding.get("configured") is True:
        return funding, "valid"
    return funding, "partial"


def account_funding_severity(funding: Mapping[str, Any] | None) -> str | None:
    """Severity for account_constraint signal. None if no funding object."""
    if not isinstance(funding, dict):
        return None
    if funding.get("configured") is not True:
        return "warning"
    coverage = funding.get("quote_coverage")
    if isinstance(coverage, dict) and coverage.get("complete") is True:
        return "info"
    return "warning"


def parse_account_action(advice_result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize account_action to {action, reason, confidence}."""
    raw = advice_result.get("account_action")
    if isinstance(raw, dict):
        action = str(raw.get("action") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        if not action and not reason:
            return None
        return {
            "action": action or None,
            "reason": reason,
            "confidence": raw.get("confidence"),
        }
    if isinstance(raw, str) and raw.strip():
        # defensive path for malformed payloads only
        return {"action": raw.strip(), "reason": "", "confidence": None}
    return None


def extract_constraint_state(advice_result: Mapping[str, Any]) -> dict[str, Any]:
    """Constraint evaluation flags from authoritative holdings + funding."""
    holdings = advice_result.get("holdings")
    if not isinstance(holdings, list):
        holdings = []

    funding_present = isinstance(advice_result.get("account_funding"), dict)
    sellable_advisory_count = 0
    constrained_add_count = 0

    for holding in holdings:
        if not isinstance(holding, dict):
            continue
        if "sellable_quantity_advisory" in holding:
            sellable_advisory_count += 1
        action = str(holding.get("action") or "").lower()
        size = holding.get("execution_size_pct_of_holding")
        qty = holding.get("execution_quantity")
        if action == "add" and size is not None:
            try:
                size_val = float(size)
            except (TypeError, ValueError):
                size_val = 0.0
            if size_val > 0 and qty is None:
                constrained_add_count += 1

    return {
        "account_funding_available": funding_present,
        "cash_constraint_evaluated": funding_present,
        "sellable_quantity_evaluated": sellable_advisory_count > 0,
        "constrained_add_count": constrained_add_count,
        "sellable_advisory_count": sellable_advisory_count,
    }


def holding_execution_payload(holding: Mapping[str, Any]) -> dict[str, Any]:
    """Payload fields for execution / outcome archive."""
    return {
        "name": holding.get("name"),
        "action": str(holding.get("action") or "hold").lower(),
        "execution_size_pct_of_holding": holding.get("execution_size_pct_of_holding"),
        "execution_quantity": holding.get("execution_quantity"),
        "estimated_amount": holding.get("estimated_amount"),
        "sellable_quantity_advisory": holding.get("sellable_quantity_advisory")
        if "sellable_quantity_advisory" in holding
        else None,
        "confidence": holding.get("confidence"),
        "trigger_conditions": holding.get("trigger_conditions") or [],
        "price_conditions": holding.get("price_conditions") or [],
        "execution_plan": holding.get("execution_plan") or [],
        "risk_conditions": holding.get("risk_conditions") or [],
        "invalidation_conditions": holding.get("invalidation_conditions") or [],
        "data_limitations": holding.get("data_limitations") or [],
    }
