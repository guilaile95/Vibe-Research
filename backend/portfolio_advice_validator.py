"""持仓操作建议结构化结果校验与数量约束（纯函数，不联网、不调模型）。

对 AI 输出的 JSON 进行：
- 动作枚举与字段形状校验；
- 代码重算市值/盈亏/权重（覆盖模型数值）；
- reduce/sell 数量按 100 股向下取整并截断；
- add/hold/watch/avoid 清空不可靠数量；
- 自动补充可卖数量等 data_limitations；
- 忽略并剥离模型额外输出的 t_trade 字段（第一版不支持做 T）。

不信任模型自行计算的数量与盈亏。
"""

from __future__ import annotations

import copy
import math
from typing import Any

from portfolio_advice_prompt import ACCOUNT_ACTIONS, ACTIONS, SCHEMA_VERSION

LOT_SIZE = 100

_SELLABLE_LIMITATION = "未提供可卖数量，执行前需要人工确认实际可卖股数。"
_CASH_LIMITATION = "未提供可用现金和账户总资产，无法计算具体买入股数。"

_CONFIDENCE = frozenset({"high", "medium", "low"})


class PortfolioAdviceValidationError(ValueError):
    """结构化结果无法校验时抛出。"""


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _num_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            v = float(s)
        except ValueError:
            return None
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    n = _num_or_none(value)
    return default if n is None else n


def _round2(v: float) -> float:
    return round(v, 2)


def _str_list(value: Any) -> list[str]:
    out: list[str] = []
    for it in _as_list(value):
        if isinstance(it, str) and it.strip():
            out.append(it.strip())
        elif it is not None and not isinstance(it, str):
            s = str(it).strip()
            if s:
                out.append(s)
    return _dedupe_str_list(out)


def _dedupe_str_list(items: list[str]) -> list[str]:
    """稳定去重：完全相同文案只保留首次出现。"""
    out: list[str] = []
    seen: set[str] = set()
    for s in items:
        if not isinstance(s, str):
            continue
        t = s.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _append_unique(lst: list[str], msg: str) -> None:
    if msg and msg not in lst:
        lst.append(msg)


def floor_to_lot(quantity: float, lot: int = LOT_SIZE) -> int:
    """向下取整到交易单位（默认 100 股）。负数归零。"""
    if lot <= 0:
        raise ValueError("lot 必须为正整数")
    if quantity is None:
        return 0
    q = float(quantity)
    if q <= 0:
        return 0
    return int(q // lot) * lot


def compute_execution_quantity(
    shares: float,
    size_pct: float | None,
    *,
    lot: int = LOT_SIZE,
) -> int | None:
    """reduce/sell：shares × pct/100 后向下取整到 lot，且不超过 shares。"""
    if size_pct is None:
        return None
    pct = float(size_pct)
    if pct < 0:
        pct = 0.0
    if pct > 100:
        pct = 100.0
    raw = float(shares) * pct / 100.0
    qty = floor_to_lot(raw, lot=lot)
    # 允许非整数 shares（ETF），但仍按 lot 约束；不得超过 shares
    if qty > float(shares):
        qty = floor_to_lot(float(shares), lot=lot)
    # 若 shares 本身不足 1 手且 pct>0，可能得到 0
    return qty


def _normalize_pct(value: Any) -> float | None:
    if value is None:
        return None
    n = _num_or_none(value)
    if n is None:
        raise PortfolioAdviceValidationError(
            f"execution_size_pct_of_holding 非法：{value!r}"
        )
    if n < 0 or n > 100:
        raise PortfolioAdviceValidationError(
            f"execution_size_pct_of_holding 必须在 0—100，收到：{n}"
        )
    return float(n)


def _context_holdings_index(context: dict) -> dict[str, dict]:
    holdings = _as_list(context.get("holdings"))
    idx: dict[str, dict] = {}
    for h in holdings:
        if not isinstance(h, dict):
            continue
        code = str(h.get("code") or "").strip()
        if code:
            idx[code] = h
    return idx


def _recompute_fact_fields(ctx_h: dict) -> dict[str, Any]:
    """从上下文持仓行提取/重算权威事实字段。"""
    shares = _safe_float(ctx_h.get("shares"), 0.0)
    cost = _safe_float(ctx_h.get("cost_price"), 0.0)
    price = _safe_float(ctx_h.get("current_price"), 0.0)
    mv = _round2(price * shares)
    cost_v = cost * shares
    pnl = _round2(mv - cost_v)
    pnl_pct = _round2(pnl / cost_v * 100) if cost_v else 0.0
    weight = _num_or_none(ctx_h.get("holding_weight_pct"))
    if weight is None:
        weight = 0.0
    return {
        "code": str(ctx_h.get("code") or "").strip(),
        "name": str(ctx_h.get("name") or ctx_h.get("code") or ""),
        "shares": shares,
        "cost_price": cost,
        "current_price": price,
        "market_value": mv,
        "pnl_amount": pnl,
        "pnl_pct": pnl_pct,
        "holding_weight_pct": float(weight),
    }


def _validate_one_holding(
    ai_h: dict,
    ctx_h: dict,
) -> dict[str, Any]:
    facts = _recompute_fact_fields(ctx_h)
    action = ai_h.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise PortfolioAdviceValidationError(
            f"非法 action：{action!r}（code={facts['code']}）"
        )

    limitations = _str_list(ai_h.get("data_limitations"))

    size_pct: float | None
    raw_pct = ai_h.get("execution_size_pct_of_holding")
    if action in ("reduce", "sell"):
        if raw_pct is None:
            # 允许 null：则 execution_quantity 也为 null
            size_pct = None
        else:
            size_pct = _normalize_pct(raw_pct)
        qty = compute_execution_quantity(facts["shares"], size_pct)
        # 再保险：不得超过 shares
        if qty is not None and qty > facts["shares"]:
            qty = floor_to_lot(facts["shares"])
        _append_unique(limitations, _SELLABLE_LIMITATION)
    elif action == "add":
        size_pct = _normalize_pct(raw_pct) if raw_pct is not None else None
        qty = None  # 强制清空
        _append_unique(limitations, _CASH_LIMITATION)
    elif action in ("hold", "watch", "avoid"):
        size_pct = _normalize_pct(raw_pct) if raw_pct is not None else None
        if size_pct is not None and size_pct != 0:
            # 非操作动作不应带正比例；归一为 null
            size_pct = None
        qty = None
    else:
        size_pct = None
        qty = None

    conf = ai_h.get("confidence")
    if conf not in _CONFIDENCE:
        conf = "low"

    # 权威结果不包含 t_trade；模型若额外输出该字段，在此丢弃
    return {
        **facts,
        "action": action,
        "execution_size_pct_of_holding": size_pct,
        "execution_quantity": qty,
        "trigger_conditions": _str_list(ai_h.get("trigger_conditions")),
        "price_conditions": _str_list(ai_h.get("price_conditions")),
        "execution_plan": _str_list(ai_h.get("execution_plan")),
        "risk_conditions": _str_list(ai_h.get("risk_conditions")),
        "invalidation_conditions": _str_list(ai_h.get("invalidation_conditions")),
        "confidence": conf,
        "data_limitations": _dedupe_str_list(limitations),
    }


def _portfolio_summary_from_context(context: dict) -> dict[str, Any]:
    s = _as_dict(context.get("portfolio_summary"))
    holdings = _as_list(context.get("holdings"))
    if holdings:
        tmv = _round2(sum(_safe_float(h.get("market_value")) for h in holdings if isinstance(h, dict)))
        tcost = _round2(
            sum(
                _safe_float(h.get("cost_price")) * _safe_float(h.get("shares"))
                for h in holdings
                if isinstance(h, dict)
            )
        )
        tpnl = _round2(tmv - tcost)
        tpnl_pct = _round2(tpnl / tcost * 100) if tcost else 0.0
        return {
            "holding_count": len([h for h in holdings if isinstance(h, dict) and h.get("code")]),
            "market_value": tmv,
            "cost": tcost,
            "pnl": tpnl,
            "pnl_pct": tpnl_pct,
        }
    return {
        "holding_count": int(_safe_float(s.get("holding_count"), 0)),
        "market_value": _round2(_safe_float(s.get("market_value"), 0)),
        "cost": _round2(_safe_float(s.get("cost"), 0)),
        "pnl": _round2(_safe_float(s.get("pnl"), 0)),
        "pnl_pct": _round2(_safe_float(s.get("pnl_pct"), 0)),
    }


def _validate_account_action(raw: Any) -> dict[str, str]:
    d = _as_dict(raw)
    action = d.get("action")
    if action not in ACCOUNT_ACTIONS:
        # 宽松回落：非法则 hold + 低置信
        action = "hold"
        reason = str(d.get("reason") or "账户动作非法，已回落为 hold").strip()
        conf = "low"
    else:
        reason = str(d.get("reason") or "").strip()
        conf = d.get("confidence") if d.get("confidence") in _CONFIDENCE else "low"
    return {"action": action, "reason": reason, "confidence": conf}


def validate_portfolio_advice(
    ai_result: dict,
    context: dict,
    *,
    generated_at: str | None = None,
) -> dict:
    """校验并约束 AI 持仓建议结果。

    Parameters
    ----------
    ai_result
        模型输出的结构化 dict（已解析 JSON）。
    context
        ``build_portfolio_advice_context`` 的输出；作为事实权威源。
    generated_at
        可选覆盖时间戳；默认取 ai_result 或空字符串。

    Returns
    -------
    规范化后的权威结果 dict（schema_version=portfolio-advice-v0.1）。
    结果中绝不包含 t_trade 字段。

    Notes
    -----
    - 不修改输入对象（内部 deepcopy 工作副本）。
    - 相同输入结果确定。
    - action=t_trade 视为非法并抛出 PortfolioAdviceValidationError。
    - 模型额外输出的 t_trade 字段被忽略并从权威结果中移除。
    """
    if not isinstance(ai_result, dict):
        raise PortfolioAdviceValidationError("ai_result 必须是字典")
    if not isinstance(context, dict):
        raise PortfolioAdviceValidationError("context 必须是字典")

    # 不修改调用方输入
    ai_work = copy.deepcopy(ai_result)

    ctx_index = _context_holdings_index(context)
    ai_holdings_raw = _as_list(ai_work.get("holdings"))
    ai_by_code: dict[str, dict] = {}
    for h in ai_holdings_raw:
        if not isinstance(h, dict):
            continue
        code = str(h.get("code") or "").strip()
        if code:
            ai_by_code[code] = h

    # 以上下文持仓为准：不得遗漏；上下文没有的 code 丢弃
    validated_holdings: list[dict] = []
    for code, ctx_h in ctx_index.items():
        ai_h = ai_by_code.get(code)
        if ai_h is None:
            # 模型遗漏：合成 watch + 低置信，强制 limitation
            ai_h = {
                "code": code,
                "action": "watch",
                "confidence": "low",
                "trigger_conditions": ["模型未返回该持仓建议"],
                "price_conditions": [],
                "execution_plan": ["暂不操作，等待补全建议"],
                "risk_conditions": ["建议不完整"],
                "invalidation_conditions": ["获得完整建议后重新评估"],
                "data_limitations": ["模型未覆盖该持仓"],
            }
        validated_holdings.append(_validate_one_holding(ai_h, ctx_h))

    summary = _portfolio_summary_from_context(context)
    account_action = _validate_account_action(ai_work.get("account_action"))

    top_limitations = _str_list(ai_work.get("data_limitations"))
    # 合并上下文固定 limitations
    for msg in _as_list(context.get("data_limitations")):
        if isinstance(msg, str):
            _append_unique(top_limitations, msg.strip())
    _append_unique(top_limitations, _SELLABLE_LIMITATION)
    _append_unique(top_limitations, _CASH_LIMITATION)
    top_limitations = _dedupe_str_list(top_limitations)

    warnings = _str_list(ai_work.get("warnings"))
    for w in _as_list(context.get("warnings")):
        if isinstance(w, str):
            _append_unique(warnings, w.strip())
    warnings = _dedupe_str_list(warnings)

    market_status = ai_work.get("market_status")
    if not isinstance(market_status, str):
        # 尝试从市场上下文推断
        mc = _as_dict(context.get("market_context"))
        rm = _as_dict(mc.get("review_metadata"))
        market_status = str(rm.get("status") or "")

    ts = generated_at
    if ts is None:
        ts = ai_work.get("generated_at")
    if not isinstance(ts, str):
        ts = ""

    # 交易日：仅透传上下文已有值，不伪造
    trade_date: str | None = None
    meta = _as_dict(context.get("portfolio_meta"))
    raw_td = meta.get("trade_date")
    if isinstance(raw_td, str) and raw_td.strip():
        trade_date = raw_td.strip()
    else:
        me = _as_dict(context.get("market_evidence"))
        raw_td = me.get("trade_date")
        if isinstance(raw_td, str) and raw_td.strip():
            trade_date = raw_td.strip()
        else:
            mc = _as_dict(context.get("market_context"))
            rm = _as_dict(mc.get("review_metadata"))
            raw_td = rm.get("trade_date")
            if isinstance(raw_td, str) and raw_td.strip():
                trade_date = raw_td.strip()

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": ts,
        "trade_date": trade_date,
        "market_status": market_status,
        "portfolio_summary": summary,
        "account_action": account_action,
        "holdings": validated_holdings,
        "warnings": warnings,
        "data_limitations": top_limitations,
    }
