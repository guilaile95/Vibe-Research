"""TrendRadar 自选股 Attention Context 聚合（TR1-P2）。

该模块只组合后端权威自选股与现有单证券 observation projection，不创建新的
自选股、投资评分、Thesis、Decision、Holding 或 Trade authority。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import trendradar_attention_context as attention_context
import trendradar_gateway as gateway

WATCHLIST_CONTEXT_AUTHORITY_REF = "vibe:trendradar_watchlist_context:v0.1"
USAGE_BOUNDARY = "observation_only_not_an_investment_authority"
MAX_WATCHLIST_CODES = 50


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_codes(codes: Any) -> list[str]:
    if not isinstance(codes, list):
        raise ValueError("watchlist codes must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
            raise ValueError("watchlist contains an invalid A-share code")
        if code not in seen:
            seen.add(code)
            normalized.append(code)
    if len(normalized) > MAX_WATCHLIST_CODES:
        raise ValueError(f"watchlist exceeds {MAX_WATCHLIST_CODES} codes")
    return normalized


def _unavailable_item(code: str) -> dict[str, Any]:
    return {
        "status": gateway.STATUS_UNAVAILABLE,
        "retrieved_at": utc_now_iso(),
        "authority_ref": attention_context.ATTENTION_CONTEXT_AUTHORITY_REF,
        "usage_boundary": USAGE_BOUNDARY,
        "upstream": gateway.upstream_identity(),
        "error": gateway.safe_public_error(gateway.STATUS_UNAVAILABLE),
        "security": {"code": code, "company_name": None},
        "mapping": {
            "status": "EXACT_CODE_ONLY",
            "sector": None,
            "topics": [],
            "matched_terms": [code],
            "reasons": [{"kind": "security_code", "value": code, "source": "user_query_exact"}],
            "errors": [],
        },
        "observation": {
            "window_days": attention_context.SEARCH_DAYS_BACK,
            "window_semantics": "TrendRadar search_news date_range relative window",
            "items": [],
            "item_count": 0,
            "rank_history_semantics": "Only returned when upstream exposes rank_timeline; missing means UNKNOWN",
        },
        "source_statuses": [],
    }


def _overall_status(statuses: list[str]) -> str:
    if not statuses:
        return gateway.STATUS_OK
    if all(status == gateway.STATUS_DISABLED for status in statuses):
        return gateway.STATUS_DISABLED
    if all(status == statuses[0] for status in statuses):
        return statuses[0]
    if any(status in {gateway.STATUS_OK, attention_context.STATUS_PARTIAL} for status in statuses):
        return attention_context.STATUS_PARTIAL
    return gateway.STATUS_UNAVAILABLE


def build_watchlist_context(
    codes: Any,
    *,
    watchlist_status: str = "valid",
    env: dict[str, str] | None = None,
    transport_factory: Callable[[gateway.GatewayConfig], Any] = gateway.default_transport_factory,
    context_builder: Callable[..., dict[str, Any]] = attention_context.build_attention_context,
) -> dict[str, Any]:
    """按后端权威自选顺序构造逐证券 Attention Context。"""
    normalized_codes = _validate_codes(codes)
    if watchlist_status != "valid":
        status = gateway.STATUS_UNAVAILABLE
        return {
            "status": status,
            "retrieved_at": utc_now_iso(),
            "authority_ref": WATCHLIST_CONTEXT_AUTHORITY_REF,
            "usage_boundary": USAGE_BOUNDARY,
            "upstream": gateway.upstream_identity(),
            "error": "后端权威自选不可用",
            "watchlist": {"status": watchlist_status, "codes": [], "count": 0},
            "items": [],
        }
    items: list[dict[str, Any]] = []
    for code in normalized_codes:
        try:
            item = context_builder(
                code,
                env=env,
                transport_factory=transport_factory,
            )
        except Exception:  # noqa: BLE001 - one code failure must remain isolated
            item = _unavailable_item(code)
        if not isinstance(item, dict) or not isinstance(item.get("status"), str):
            item = _unavailable_item(code)
        items.append(item)

    statuses = [str(item.get("status")) for item in items]
    status = _overall_status(statuses)
    result: dict[str, Any] = {
        "status": status,
        "retrieved_at": utc_now_iso(),
        "authority_ref": WATCHLIST_CONTEXT_AUTHORITY_REF,
        "usage_boundary": USAGE_BOUNDARY,
        "upstream": gateway.upstream_identity(),
        "watchlist": {
            "status": watchlist_status,
            "codes": normalized_codes,
            "count": len(normalized_codes),
        },
        "items": items,
    }
    if status not in {gateway.STATUS_OK, attention_context.STATUS_PARTIAL}:
        result["error"] = gateway.safe_public_error(status)
    return result
