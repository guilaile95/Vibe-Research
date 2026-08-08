"""Market Regime API —— 只读，确定性派生状态，不调用 AI。

- 正常 / 部分数据 / 不可用 → 均返回 HTTP 200，状态以 body.data.market_regime 为准；
- 仅真正逃逸的未预期异常 → HTTP 502，响应体为稳定脱敏文本，不泄漏异常细节
  （Security Boundary：str(e) / URL / traceback / provider error 一律不返回客户端）；
- 非买卖信号，不产生任何交易建议。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import market_regime

router = APIRouter(prefix="/api/market", tags=["market"])

# 稳定脱敏文本：客户端唯一可见的 502 描述，不携带任何异常信息。
_UNEXPECTED_ERROR_MESSAGE = "市场状态暂不可用"


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
        # Security Boundary：异常链保留在服务端（日志可查），客户端只见稳定脱敏文本。
        raise HTTPException(502, _UNEXPECTED_ERROR_MESSAGE) from e
