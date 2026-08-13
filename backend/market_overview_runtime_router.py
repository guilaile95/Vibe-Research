"""Current Market Overview runtime API（P0-MO1）。

只读 endpoint：组合既有 market facts authority，返回首页可消费的 Market
Overview read model（诚实标注 current/historical、freshness、coverage）。

数据来源：既有 snapshot producer（``fetch_final_limit_up_pool_snapshot``
T+1 可信 final）→ ``short_term_market_facts.compute_short_term_market_facts``
（纯 producer）→ ``market_overview_runtime.build_market_overview`` 投影。

**Reference 语义（P0-MO1-R1）**：current vs historical 由显式 reference 判定，
零墙钟——复用 stable 既有 ``trade_calendar.completed_trade_date_at(as_of)``
权威（与 #116 critical_data_price_reference_adapter 同一模式）。调用方传入
显式 UTC ``as_of``；缺失时诚实 UNAVAILABLE（不猜 today）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import market_overview_runtime as overview
import short_term_limit_up_final_snapshot as final_snapshot
import short_term_market_facts
from trade_calendar import completed_trade_date_at

router = APIRouter(prefix="/api/market", tags=["market-overview"])


@router.get("/overview/facts")
def market_overview_facts(
    trade_date: str | None = Query(default=None, description="A-share 交易日 YYYY-MM-DD"),
    as_of: str | None = Query(default=None, description="显式 UTC reference instant"),
) -> dict:
    """当前 A 股 Market Overview（read model，非决策权威）。

    - ``trade_date``：要评估的交易日（通常由 caller 提供最近已完成交易日）。
    - ``as_of``：显式 UTC reference instant；经 ``completed_trade_date_at``
      权威映射为 completed/relevant trade date，用于 current vs historical 判定。
    - 二者缺失 → UNAVAILABLE（不读墙钟、不猜 today）。
    """
    if trade_date is None or not trade_date.strip():
        return _unavailable("TRADE_DATE_REQUIRED")
    if as_of is None or not as_of.strip():
        return _unavailable("AS_OF_REQUIRED")
    reference_trade_date = completed_trade_date_at(as_of.strip())
    if reference_trade_date is None:
        return _unavailable("REFERENCE_TRADE_DATE_UNAVAILABLE")
    snapshot = final_snapshot.fetch_final_limit_up_pool_snapshot(trade_date.strip())
    facts = short_term_market_facts.compute_short_term_market_facts(snapshot)
    try:
        return {"data": overview.build_market_overview(
            facts, reference_trade_date=reference_trade_date)}
    except overview.MarketOverviewInputError as exc:
        raise HTTPException(status_code=500, detail="market overview 契约违反") from exc


def _unavailable(reason_code: str) -> dict:
    return {
        "data": {
            "schema_version": overview.SCHEMA_VERSION,
            "data_state": overview.DATA_STATE_UNAVAILABLE,
            "status": "unavailable",
            "reason_codes": [reason_code],
            "warnings": [],
            "limitations": [],
            "trade_date": None,
            "session": "unavailable",
            "is_final": False,
            "temporal_state": overview.TEMPORAL_STATE_UNAVAILABLE,
        }
    }


__all__ = ["router"]
