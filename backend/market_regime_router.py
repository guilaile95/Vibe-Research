"""Market Regime API —— 只读，确定性派生状态，不调用 AI。

- 正常 / 部分数据 / 不可用 → 均返回 HTTP 200，状态以 body.data.market_regime 为准；
- 仅真正逃逸的未预期异常 → HTTP 502；
- 非买卖信号，不产生任何交易建议。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import market_regime

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/regime")
def get_regime():
    """当前 A 股整体市场风险环境（Market Regime v0.1，确定性规则）。

    输出：market_regime / risk_appetite / confidence / is_stale /
    trade_date / data_cutoff / components / reasons。
    数据不完整时降低 Confidence 或保持 UNKNOWN，不制造结论。
    """
    try:
        return {"data": market_regime.get_market_regime()}
    except Exception as e:  # noqa: BLE001 — 派生层意外逃逸
        raise HTTPException(502, f"市场状态异常：{e}") from e
