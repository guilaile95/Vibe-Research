"""技术指标 HTTP 路由：/api/market/technical-indicators。

只负责 HTTP 适配（参数校验、拉 K 线、缓存、错误隔离）；
纯计算委托给 technical_indicators.compute_indicators。
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

import app as app_module
import astock
import technical_indicators as ti

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market/technical-indicators", tags=["technical-indicators"])

_ALLOWED_PERIODS = frozenset({"daily"})
_DAYS_MIN = 20
_DAYS_MAX = 240
_DAYS_DEFAULT = 120
_CACHE_TTL = 900  # 15 分钟


@router.get("")
def get_technical_indicators(
    code: str = Query(...),
    period: str = Query("daily"),
    days: int = Query(_DAYS_DEFAULT),
):
    """技术指标与价格触发。"""
    # 1. 参数校验
    code = app_module._validate(code)

    period = (period or "daily").strip().lower()
    if period not in _ALLOWED_PERIODS:
        raise HTTPException(400, f"period 仅允许 daily，收到：{period}")

    # 2. days clamp
    warnings: list[str] = []
    if days < _DAYS_MIN:
        warnings.append(f"days={days} 低于最小值 {_DAYS_MIN}，已 clamp 到 {_DAYS_MIN}")
        days = _DAYS_MIN
    elif days > _DAYS_MAX:
        warnings.append(f"days={days} 超过最大值 {_DAYS_MAX}，已 clamp 到 {_DAYS_MAX}")
        days = _DAYS_MAX

    # 3. 缓存
    cache_key = ("technical_indicators", f"{code}:{period}:{days}")
    hit = app_module._DC_CACHE.get(cache_key, _CACHE_TTL)
    if hit is not app_module._CACHE_MISS:
        return {"data": hit}

    # 4. 拉一次 K 线
    try:
        raw_klines = astock.kline(code, category=4, offset=days)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"行情源异常：{e}") from e

    # 5. 计算
    fetched_at = datetime.now().isoformat(timespec="seconds")
    trade_date = ""
    if raw_klines:
        last = raw_klines[-1]
        dt_raw = last.get("datetime") or last.get("date")
        if dt_raw:
            trade_date = str(dt_raw)[:10]

    envelope = ti.compute_indicators(
        raw_klines,
        code=code,
        period=period,
        days=days,
        trade_date=trade_date,
        fetched_at=fetched_at,
    )

    # 合并 warning
    if warnings:
        envelope["warnings"] = warnings + list(envelope.get("warnings", []))

    # 6. 缓存（unavailable 不缓存）
    st = envelope.get("status")
    if st != "unavailable":
        app_module._DC_CACHE.set(cache_key, envelope)

    # 7. Data Health 事件
    try:
        import data_health_event_store as _dhes
        if st == "normal":
            _dhes.safe_call(_dhes.record_success, "technical_indicators")
        elif st == "partial":
            _dhes.safe_call(_dhes.record_partial, "technical_indicators")
        else:
            _dhes.safe_call(_dhes.record_failure, "technical_indicators", "SOURCE_UNAVAILABLE")
    except Exception:
        pass

    return {"data": envelope}
