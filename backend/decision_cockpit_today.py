"""决策驾驶舱「今日实时行动」只读聚合。

规则确定性、不调模型、GET 路径零写库：
- portfolio.get_portfolio() 持仓 + 行情
- get_current_plan(trade_date) 信号压缩
- ai_result_service.get_ai_result(portfolio_advice) 精确 trade_date 匹配
- watchlist_store + quote，按 |change_pct| 取前 8
"""

from __future__ import annotations

from typing import Any

import ai_result_service
import astock
import portfolio as pf
import watchlist_store
from decision_cockpit_service import (
    DecisionCockpitError,
    _now_beijing,
    _validate_trade_date,
    get_current_plan,
)

_DIM_LABEL = {"value": "价值", "trend": "趋势", "short": "短线"}
_ASSESS_LABEL = {
    "strong": "强",
    "medium": "中",
    "weak": "弱",
    "unknown": "未知",
}


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _quotes_for_codes(codes: list[str]) -> dict[str, dict]:
    """批量行情；失败返回空 dict，不抛。"""
    uniq = [c for c in dict.fromkeys(codes) if isinstance(c, str) and c]
    if not uniq:
        return {}
    try:
        quotes = astock.tencent_quote(uniq)
    except Exception:  # noqa: BLE001 — 只读聚合，行情失败不阻断
        return {}
    return quotes if isinstance(quotes, dict) else {}


def _compress_plan_signals(signals: list[dict] | None, code: str) -> str | None:
    """把某 code 的 value/trend/short 信号压成一句话。"""
    if not signals:
        return None
    by_dim: dict[str, str] = {}
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        if str(sig.get("candidate_code") or "") != code:
            continue
        dim = str(sig.get("dimension") or "")
        if dim not in _DIM_LABEL:
            continue
        assess = str(sig.get("assessment") or "unknown")
        # 同维多条：优先 strong > medium > weak > unknown；保留最后一条也行，这里取「最强」
        rank = {"strong": 3, "medium": 2, "weak": 1, "unknown": 0}
        prev = by_dim.get(dim)
        if prev is None or rank.get(assess, 0) >= rank.get(prev, 0):
            by_dim[dim] = assess
    if not by_dim:
        return None
    parts: list[str] = []
    for dim in ("value", "trend", "short"):
        if dim not in by_dim:
            continue
        parts.append(f"{_DIM_LABEL[dim]}{_ASSESS_LABEL.get(by_dim[dim], by_dim[dim])}")
    return " / ".join(parts) if parts else None


def _advice_by_code(trade_date: str) -> dict[str, dict[str, Any]]:
    """精确 trade_date 的 portfolio_advice → code → {action, qty}。"""
    try:
        rec = ai_result_service.get_ai_result(
            ai_result_service.PORTFOLIO_ADVICE,
            trade_date=trade_date,
        )
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(rec, dict):
        return {}
    if str(rec.get("trade_date") or "") != str(trade_date):
        return {}
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return {}
    holdings = payload.get("holdings")
    if not isinstance(holdings, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for h in holdings:
        if not isinstance(h, dict):
            continue
        code = h.get("code")
        if not isinstance(code, str) or not code:
            continue
        action = h.get("action")
        qty = h.get("execution_quantity")
        out[code] = {
            "action": action if isinstance(action, str) else None,
            "qty": int(qty) if isinstance(qty, int) else (
                int(qty) if isinstance(qty, float) and qty == int(qty) else None
            ),
        }
    return out


def _build_flags(
    *,
    pnl_pct: float | None,
    change_pct: float | None,
) -> list[str]:
    flags: list[str] = []
    if pnl_pct is not None:
        if pnl_pct <= -5:
            flags.append("浮亏加深")
        elif pnl_pct >= 10:
            flags.append("浮盈较大")
        if abs(pnl_pct) <= 2:
            flags.append("接近成本")
    if change_pct is not None:
        if change_pct <= -5:
            flags.append("当日大跌")
        elif change_pct >= 5:
            flags.append("当日大涨")
    return flags


def _plan_meta(plan: dict | None) -> dict | None:
    if not isinstance(plan, dict):
        return None
    return {
        "id": plan.get("id"),
        "status": plan.get("status"),
        "version": plan.get("version"),
        "generated_at": plan.get("generated_at"),
        "is_current": plan.get("is_current"),
    }


def _watchlist_movers(holding_codes: set[str], limit: int = 8) -> list[dict]:
    try:
        codes = list(watchlist_store.load_watchlist() or [])
    except Exception:  # noqa: BLE001
        codes = []
    # 自选可与持仓重叠；仍展示异动
    codes = [c for c in codes if isinstance(c, str) and c]
    quotes = _quotes_for_codes(codes)
    rows: list[dict] = []
    for code in codes:
        q = quotes.get(code) or {}
        if not isinstance(q, dict):
            q = {}
        change_pct = _safe_float(q.get("change_pct"))
        price = _safe_float(q.get("price"))
        name = q.get("name") if isinstance(q.get("name"), str) and q.get("name") else code
        flag = None
        if change_pct is not None:
            if change_pct <= -5:
                flag = "大跌关注"
            elif change_pct >= 5:
                flag = "大涨关注"
            elif abs(change_pct) >= 3:
                flag = "波动加大"
        rows.append(
            {
                "code": code,
                "name": name,
                "price": price,
                "change_pct": change_pct,
                "flag": flag,
                "in_holdings": code in holding_codes,
            }
        )
    rows.sort(
        key=lambda r: abs(r["change_pct"]) if r["change_pct"] is not None else -1.0,
        reverse=True,
    )
    # 无涨跌幅的排后；截断前 N
    top = [r for r in rows if r["change_pct"] is not None][:limit]
    if len(top) < limit:
        rest = [r for r in rows if r["change_pct"] is None]
        top.extend(rest[: limit - len(top)])
    return [
        {
            "code": r["code"],
            "name": r["name"],
            "price": r["price"],
            "change_pct": r["change_pct"],
            "flag": r["flag"],
        }
        for r in top
    ]


def get_today_actions(trade_date: str) -> dict[str, Any]:
    """聚合「今日实时行动」面板数据（只读、确定性）。

    Raises:
        DecisionCockpitError: trade_date 非法（HTTP 层映射 400）
    """
    trade_date = _validate_trade_date(trade_date)
    warnings: list[str] = []

    # 1) 持仓 + 行情
    try:
        portfolio = pf.get_portfolio()
    except Exception as e:  # noqa: BLE001
        portfolio = {"holdings": []}
        warnings.append(f"持仓行情读取失败：{type(e).__name__}")

    holdings_raw = portfolio.get("holdings") if isinstance(portfolio, dict) else []
    if not isinstance(holdings_raw, list):
        holdings_raw = []

    holding_codes = [
        str(h.get("code"))
        for h in holdings_raw
        if isinstance(h, dict) and h.get("code")
    ]
    # portfolio 行通常不含 change_pct，补拉一次
    extra_quotes = _quotes_for_codes(holding_codes)

    # 2) 当前计划（只读）
    plan = None
    signals: list[dict] = []
    try:
        plan = get_current_plan(trade_date)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"当前计划读取失败：{type(e).__name__}")
        plan = None
    if isinstance(plan, dict):
        raw_sigs = plan.get("signals")
        if isinstance(raw_sigs, list):
            signals = [s for s in raw_sigs if isinstance(s, dict)]

    plan_meta = _plan_meta(plan)
    if plan_meta is None:
        plan_note = "该交易日尚无冻结的当前计划；持仓行动仅基于实时行情与已保存建议。"
    else:
        plan_note = None

    # 3) 持仓建议（精确 trade_date）
    advice_map = _advice_by_code(trade_date)
    if not advice_map:
        # 非致命：可能无建议或日期不匹配
        pass

    # 4) 持仓行动行
    holdings_out: list[dict] = []
    for h in holdings_raw:
        if not isinstance(h, dict):
            continue
        code = str(h.get("code") or "")
        if not code:
            continue
        q = extra_quotes.get(code) or {}
        if not isinstance(q, dict):
            q = {}
        change_pct = _safe_float(q.get("change_pct"))
        # portfolio 已有 price/pnl；优先 portfolio，缺省回退 quote
        price = _safe_float(h.get("price"))
        if price is None:
            price = _safe_float(q.get("price"))
        pnl_pct = _safe_float(h.get("pnl_pct"))
        name = h.get("name") if isinstance(h.get("name"), str) and h.get("name") else (
            q.get("name") if isinstance(q.get("name"), str) else code
        )
        adv = advice_map.get(code) or {}
        holdings_out.append(
            {
                "code": code,
                "name": name,
                "shares": h.get("shares"),
                "price": price,
                "change_pct": change_pct,
                "pnl_pct": pnl_pct,
                "plan_signals_summary": _compress_plan_signals(signals, code),
                "advice_action": adv.get("action"),
                "advice_qty": adv.get("qty"),
                "flags": _build_flags(pnl_pct=pnl_pct, change_pct=change_pct),
            }
        )

    # 5) 自选异动
    try:
        movers = _watchlist_movers(set(holding_codes), limit=8)
    except Exception as e:  # noqa: BLE001
        movers = []
        warnings.append(f"自选异动读取失败：{type(e).__name__}")

    return {
        "trade_date": trade_date,
        "as_of": _now_beijing(),
        "plan": plan_meta,
        "plan_note": plan_note,
        "holdings": holdings_out,
        "watchlist_movers": movers,
        "warnings": warnings,
    }
