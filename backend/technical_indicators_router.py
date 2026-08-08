"""技术指标、告警规则、筛选器与恢复市场路由的聚合入口。

当前 stable 的 app.py 只 include 本 router；历史功能链通过 APIRoute 聚合接入，
避免用旧分支整体覆盖后来稳定分支的 app.py。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

import alert_rule_router
import app as app_module
import astock
import northbound_capital_flow as ncf
import technical_indicators as ti

# Screener v0.1 relied on this public limitation prefix. The current technical-indicators
# implementation is v0.2 (with KDJ), so expose the historical contract without replacing it.
if not hasattr(ti, "PRICE_RANGE_TRIGGER_UNAVAILABLE_PREFIX"):
    ti.PRICE_RANGE_TRIGGER_UNAVAILABLE_PREFIX = "价格区间触发不可评估"

import screener_router

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/market/technical-indicators",
    tags=["technical-indicators"],
)

_ALLOWED_PERIODS = frozenset({"daily"})
_DAYS_MIN = 20
_DAYS_MAX = 240
_DAYS_DEFAULT = 120
_CACHE_TTL = 900


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _record_failure() -> None:
    try:
        import data_health_event_store as _dhes
        _dhes.safe_call(_dhes.record_failure, "technical_indicators", "SOURCE_UNAVAILABLE")
    except Exception:
        pass


def _upstream_unavailable_envelope(code: str, period: str, fetched_at: str, warnings: list[str]) -> dict:
    return {
        "schema_version": ti.SCHEMA_VERSION,
        "code": code,
        "period": period,
        "trade_date": None,
        "fetched_at": fetched_at,
        "status": "unavailable",
        "warnings": warnings,
        "limitations": ["核心行情数据当前不可用。"],
        "latest": ti._empty_latest(),
        "triggers": [],
        "series": [],
    }


@router.get("")
def get_technical_indicators(
    code: str = Query(...),
    period: str = Query("daily"),
    days: int = Query(_DAYS_DEFAULT),
):
    code = app_module._validate(code)
    period = (period or "daily").strip().lower()
    if period not in _ALLOWED_PERIODS:
        raise HTTPException(400, f"period 仅允许 daily，收到：{period}")

    warnings: list[str] = []
    if days < _DAYS_MIN:
        warnings.append(f"days={days} 低于最小值 {_DAYS_MIN}，已 clamp 到 {_DAYS_MIN}")
        days = _DAYS_MIN
    elif days > _DAYS_MAX:
        warnings.append(f"days={days} 超过最大值 {_DAYS_MAX}，已 clamp 到 {_DAYS_MAX}")
        days = _DAYS_MAX

    cache_key = ("technical_indicators", f"{code}:{period}:{days}")
    hit = app_module._DC_CACHE.get(cache_key, _CACHE_TTL)
    if hit is not app_module._CACHE_MISS:
        response = dict(hit)
        if warnings:
            response["warnings"] = warnings + list(hit.get("warnings", []))
        return {"data": response}

    try:
        raw_klines = astock.kline(code, category=4, offset=days)
    except Exception:
        fetched_at = _utc_now_iso()
        _record_failure()
        return {"data": _upstream_unavailable_envelope(code, period, fetched_at, warnings)}

    fetched_at = _utc_now_iso()
    envelope = ti.compute_indicators(
        raw_klines,
        code=code,
        period=period,
        days=days,
        trade_date=None,
        fetched_at=fetched_at,
    )
    response_envelope = dict(envelope)
    if warnings:
        response_envelope["warnings"] = warnings + list(envelope.get("warnings", []))

    st = envelope.get("status")
    if st != "unavailable":
        app_module._DC_CACHE.set(cache_key, envelope)

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

    return {"data": response_envelope}


northbound_history_router = APIRouter(prefix="/api/market/northbound", tags=["market"])


@northbound_history_router.get("/history")
def market_northbound_history(
    days: int = Query(20, description="历史交易日点数，仅支持 10、20、30"),
):
    """北向成交历史（成交额 / 成交笔数 / ETF 成交额），不提供净买入。"""
    try:
        days_n = ncf.validate_history_days(days)
    except ncf.NorthboundHistoryDaysError as exc:
        raise HTTPException(400, str(exc)) from None

    key = ("market_northbound_history", str(days_n))
    hit = app_module._DC_CACHE.get(key, 900)
    if hit is not app_module._CACHE_MISS:
        return {"data": hit}

    def _safe_unavailable_history() -> dict:
        return {
            "schema_version": ncf.HISTORY_SCHEMA_VERSION,
            "source": ncf.SOURCE_NAME,
            "source_tier": ncf.SOURCE_TIER,
            "status": "unavailable",
            "fetched_at": ncf._now_iso(),
            "requested_days": days_n,
            "returned_points": 0,
            "limitations": [
                dict(ncf.LIMITATION_HISTORY_NET_BUY),
                dict(ncf.LIMITATION_HISTORY_SOURCE_UNAVAILABLE),
            ],
            "series": [],
        }

    try:
        data = ncf.get_northbound_history(days_n)
    except Exception:
        data = _safe_unavailable_history()

    if not ncf._is_valid_history_envelope(data, days_n):
        data = _safe_unavailable_history()

    st = data.get("status") if isinstance(data, dict) else None
    if st != "unavailable":
        app_module._DC_CACHE.set(key, data)

    try:
        import data_health_event_store as _dhes
        if st == "normal":
            _dhes.safe_call(_dhes.record_success, "northbound_capital_flow_history")
        elif st == "partial":
            _dhes.safe_call(_dhes.record_partial, "northbound_capital_flow_history")
        else:
            _dhes.safe_call(_dhes.record_failure, "northbound_capital_flow_history", "SOURCE_UNAVAILABLE")
    except Exception:
        pass

    return {"data": data}


# Preserve full public paths from the recovered sibling routers while app.py keeps one
# authoritative include_router call for this aggregate router.
router.routes.extend(alert_rule_router.router.routes)
router.routes.extend(screener_router.router.routes)
router.routes.extend(northbound_history_router.routes)
