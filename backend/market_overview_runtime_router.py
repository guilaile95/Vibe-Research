"""Current Market Overview runtime API（P0-MO1）。

只读 endpoint：组合既有 market facts authority，返回首页可消费的 Market
Overview read model（诚实标注 freshness / coverage / source health）。

数据来源：既有 snapshot producer（``fetch_final_limit_up_pool_snapshot``
T+1 可信 final）→ ``short_term_market_facts.compute_short_term_market_facts``
（纯 producer）→ ``market_overview_runtime.build_market_overview`` 投影。

诚实纪律：
- 不提供 ``trade_date`` → UNAVAILABLE（不猜 today；retrieval time ≠ market
  fact time，绝不把"现在"当"该交易日已收盘"）。
- provider/日历失败 → facts unavailable → data_state=UNAVAILABLE（绝不伪造
  中性市场）。零写、fail closed。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import market_overview_runtime as overview
import short_term_limit_up_final_snapshot as final_snapshot
import short_term_market_facts

router = APIRouter(prefix="/api/market", tags=["market-overview"])


@router.get("/overview/facts")
def market_overview_facts(
    trade_date: str | None = Query(default=None, description="A-share 交易日 YYYY-MM-DD"),
) -> dict:
    """当前 A 股 Market Overview（read model，非决策权威）。

    - 提供 ``trade_date``（已完成交易日）→ T+1 可信 final 快照。
    - 不提供 → data_state=UNAVAILABLE（诚实：无法确定该 overview 属于哪个
      交易日；不读墙钟推断"今天"）。
    """
    if trade_date is None or not trade_date.strip():
        return {
            "data": {
                "schema_version": overview.SCHEMA_VERSION,
                "data_state": overview.DATA_STATE_UNAVAILABLE,
                "status": "unavailable",
                "reason_codes": ["TRADE_DATE_REQUIRED"],
                "warnings": [],
                "limitations": [],
                "trade_date": None,
                "session": "unavailable",
                "is_final": False,
                "temporal_state": overview.TEMPORAL_STATE_UNAVAILABLE,
            }
        }
    snapshot = final_snapshot.fetch_final_limit_up_pool_snapshot(trade_date.strip())
    facts = short_term_market_facts.compute_short_term_market_facts(snapshot)
    try:
        return {"data": overview.build_market_overview(facts)}
    except overview.MarketOverviewInputError as exc:
        raise HTTPException(status_code=500, detail="market overview 契约违反") from exc


__all__ = ["router"]
