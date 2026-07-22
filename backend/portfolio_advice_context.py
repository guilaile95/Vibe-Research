"""持仓操作建议 → AI 上下文投影器（纯函数，不联网、不改输入、不生成建议）。

将 get_portfolio() 风格的持仓数据 + 每日复盘包 + 可选个股行情，
压缩为结构稳定、可审计的事实上下文，供后续持仓建议提示词注入。

本模块不调用 AI、不写库、不修改 portfolio.json、不给出买卖建议。
"""

from __future__ import annotations

import copy
import json
from typing import Any

from daily_review_context import build_daily_review_ai_context

SCHEMA_VERSION = "portfolio-advice-context-v0.1"

# 个股行情字段（优先来自注入的 quotes；缺失保持 null，不编造）
_QUOTE_FIELDS = (
    "open",
    "high",
    "low",
    "prev_close",
    "price",
    "change_pct",
    "amount",
    "turnover_pct",
    "amplitude_pct",
    "limit_up",
    "limit_down",
)

# 系统已知的数据边界（第一版固定声明）
_BASE_LIMITATIONS = (
    "未提供账户总资产与可用现金，无法计算绝对账户仓位与具体买入金额。",
    "未提供可卖数量（sellable_shares），执行前需人工确认实际可卖股数。",
    "第一版未接入公告、新闻、机构与龙虎榜等催化数据，不得猜测消息驱动。",
    "未提供历史K线与技术指标计算结果，不得编造压力位、支撑位、均线、N日高低点或精确买卖价位区间。",
    "holding_weight_pct 表示占股票持仓市值比例，不是账户总仓位（无总资产/现金数据）。",
    "成本价仅作用户盈亏和风险参考，不是技术支撑位。",
)

# 市场字段语义（写入 context，避免模型混淆 valid_count 与 amount_valid_count、下跌与跌停）
_FIELD_SEMANTICS = {
    "stock_count": "全市场快照股票总数",
    "valid_count": "涨跌幅 change_pct 有效的股票数（与成交额有效数不同）",
    "amount_valid_count": "成交额 amount 有效的股票数（与 valid_count 不同）",
    "up_count": "上涨家数（非涨停家数）",
    "down_count": "下跌家数（非跌停家数）",
    "flat_count": "平盘家数",
    "up_ratio": "上涨家数/涨跌幅有效样本数",
    "limit_up_count": "涨停家数（仅来自短线情绪 zt_count / 涨停池）",
    "limit_down_count": "跌停家数（仅来自短线情绪 dt_count / 跌停池；不得用 down_count 代替）",
    "holding_weight_pct": "占股票持仓市值比例，非账户总仓位",
    "cost_price": "用户持仓成本，仅作盈亏与风险参考，非技术支撑位",
}

def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _num_or_none(value: Any) -> float | None:
    """解析数值；无法解析返回 None（不把 0 与缺失混为一谈时由调用方处理）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    n = _num_or_none(value)
    return default if n is None else n


def _round2(value: float) -> float:
    return round(value, 2)


def _empty_quote() -> dict[str, Any]:
    return {k: None for k in _QUOTE_FIELDS}


def _is_valid_price(px: Any) -> bool:
    if isinstance(px, bool) or not isinstance(px, (int, float)):
        return False
    if px <= 0 or px != px or px in (float("inf"), float("-inf")):
        return False
    return True


def _project_quote(raw: Any, *, fallback_price: float | None = None) -> dict[str, Any]:
    """将注入行情投影为固定字段；缺失为 null。不编造。"""
    out = _empty_quote()
    if isinstance(raw, dict):
        normalized = dict(raw)
        if "prev_close" not in normalized and "last_close" in normalized:
            normalized["prev_close"] = normalized.get("last_close")

        for k in _QUOTE_FIELDS:
            if k not in normalized:
                continue
            raw_val = normalized.get(k)
            if k == "price":
                out[k] = float(raw_val) if _is_valid_price(raw_val) else None
            else:
                out[k] = _num_or_none(raw_val)

    px = out.get("price")
    if not _is_valid_price(px):
        if _is_valid_price(fallback_price):
            out["price"] = float(fallback_price)
        else:
            out["price"] = None

    return out


def _project_holding(
    row: dict,
    *,
    total_mv: float,
    quotes: dict[str, dict],
) -> dict[str, Any]:
    code = str(row.get("code") or "").strip()
    name = str(row.get("name") or code)
    shares = _safe_float(row.get("shares"), 0.0)
    cost = _safe_float(row.get("cost"), 0.0)

    row_price = row.get("price")
    q = quotes.get(code) if code else None
    quote = _project_quote(
        q,
        fallback_price=row_price if _is_valid_price(row_price) else None,
    )

    q_price = quote.get("price")
    if _is_valid_price(q_price):
        price: float | None = float(q_price)
    elif _is_valid_price(row_price):
        price = float(row_price)
    else:
        price = None

    if price is not None:
        quote["price"] = price
        market_value: float | None = _round2(price * shares)
        cost_value = cost * shares
        pnl_amount: float | None = _round2(market_value - cost_value)
        pnl_pct: float | None = _round2(pnl_amount / cost_value * 100) if cost_value else 0.0
        distance_to_cost_pct: float | None = _round2((price - cost) / cost * 100) if cost else None
    else:
        quote["price"] = None
        market_value = None
        pnl_amount = None
        pnl_pct = None
        distance_to_cost_pct = None

    missing_quote_fields = [k for k in _QUOTE_FIELDS if quote.get(k) is None]

    return {
        "code": code,
        "name": name,
        "shares": shares,
        "cost_price": cost,
        "current_price": price,
        "market_value": market_value,
        "pnl_amount": pnl_amount,
        "pnl_pct": pnl_pct,
        "holding_weight_pct": None,
        "distance_to_cost_pct": distance_to_cost_pct,
        "quote": quote,
        "missing_quote_fields": missing_quote_fields,
    }


def _portfolio_summary(holdings: list[dict], totals_in: dict, *, complete_coverage: bool = True) -> dict[str, Any]:
    """用投影后的持仓重算汇总；totals 字段仅作对照参考。"""
    tcost = _round2(
        sum(
            _safe_float(h.get("cost_price")) * _safe_float(h.get("shares"))
            for h in holdings
        )
    )
    if complete_coverage or len(holdings) == 0:
        tmv: float | None = _round2(sum(_safe_float(h.get("market_value")) for h in holdings))
        tpnl: float | None = _round2(tmv - tcost)
        tpnl_pct: float | None = _round2(tpnl / tcost * 100) if tcost else 0.0
    else:
        tmv = None
        tpnl = None
        tpnl_pct = None

    return {
        "holding_count": len(holdings),
        "market_value": tmv,
        "cost": tcost,
        "pnl": tpnl,
        "pnl_pct": tpnl_pct,
        # 原始 totals 仅供审计，不作为权威
        "source_totals": {
            "market_value": _num_or_none(totals_in.get("market_value")),
            "cost": _num_or_none(totals_in.get("cost")),
            "pnl": _num_or_none(totals_in.get("pnl")),
            "pnl_pct": _num_or_none(totals_in.get("pnl_pct")),
        },
    }

def _dedupe_keep_order(items: list[Any]) -> list[str]:
    """字符串列表稳定去重：保留首次出现顺序。"""
    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, str):
            continue
        s = it.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _pick_present(data: dict | None, key: str):
    """仅当键存在时返回值（含 0）；键缺失返回 None。不把缺失默认成 0。"""
    if not isinstance(data, dict) or key not in data:
        return None
    return data.get(key)


def _build_market_evidence(market_ctx: dict) -> dict[str, Any]:
    """从投影后的 market_context 抽取可审计证据字段（明确命名，避免误读）。"""
    me = _as_dict(market_ctx.get("market_environment"))
    breadth = me.get("breadth") if isinstance(me.get("breadth"), dict) else None
    emotion = (
        market_ctx.get("short_term_emotion")
        if isinstance(market_ctx.get("short_term_emotion"), dict)
        else None
    )
    capital = (
        market_ctx.get("capital_activity")
        if isinstance(market_ctx.get("capital_activity"), dict)
        else None
    )
    meta = _as_dict(market_ctx.get("review_metadata"))

    breadth_evidence: dict[str, Any] | None
    if breadth is None:
        breadth_evidence = None
    else:
        breadth_evidence = {
            "status": breadth.get("status"),
            "stock_count": _pick_present(breadth, "stock_count"),
            "valid_count": _pick_present(breadth, "valid_count"),
            "up_count": _pick_present(breadth, "up_count"),
            "down_count": _pick_present(breadth, "down_count"),
            "flat_count": _pick_present(breadth, "flat_count"),
            "up_ratio": _pick_present(breadth, "up_ratio"),
            "up_3pct_count": _pick_present(breadth, "up_3pct_count"),
            "down_3pct_count": _pick_present(breadth, "down_3pct_count"),
            "total_amount": _pick_present(breadth, "total_amount"),
            "amount_valid_count": _pick_present(breadth, "amount_valid_count"),
        }

    limit_stats: dict[str, Any] | None
    if emotion is None:
        limit_stats = None
    else:
        # 仅当情绪包提供 zt/dt 时写出涨跌停；禁止用 breadth.down_count 冒充跌停
        limit_stats = {
            "status": emotion.get("status"),
            "trade_date": _pick_present(emotion, "date"),
            "limit_up_count": _pick_present(emotion, "zt_count"),
            "limit_down_count": _pick_present(emotion, "dt_count"),
            "break_board_count": _pick_present(emotion, "zb_count"),
            "source_field_map": {
                "limit_up_count": "short_term_emotion.zt_count",
                "limit_down_count": "short_term_emotion.dt_count",
                "break_board_count": "short_term_emotion.zb_count",
            },
            "note": "limit_down_count 仅表示跌停池家数；breadth.down_count 是普通下跌家数，二者不可互换。",
        }

    amount_valid = None
    if breadth is not None and "amount_valid_count" in breadth:
        amount_valid = breadth.get("amount_valid_count")
    elif capital is not None and "amount_valid_count" in capital:
        amount_valid = capital.get("amount_valid_count")

    return {
        "field_semantics": dict(_FIELD_SEMANTICS),
        "trade_date": meta.get("trade_date"),
        "review_generated_at": meta.get("generated_at"),
        "data_cutoff": meta.get("data_cutoff"),
        "review_status": meta.get("status"),
        "breadth": breadth_evidence,
        "limit_stats": limit_stats,
        "capital_amount_valid_count": amount_valid,
        "history_kline_available": False,
        "technical_indicators_available": False,
        "account_total_assets_available": False,
    }


def _dynamic_market_limitations(market_ctx: dict, evidence: dict) -> list[str]:
    """根据实际证据追加数据限制（不编造数值）。"""
    out: list[str] = []
    breadth = evidence.get("breadth") if isinstance(evidence.get("breadth"), dict) else None
    if breadth is None:
        out.append("市场广度数据不可用，不得据此判断多空占优或编造涨跌家数。")
    else:
        vc = breadth.get("valid_count")
        sc = breadth.get("stock_count")
        if vc is None:
            out.append("缺少 valid_count（涨跌幅有效样本），不得编造有效比例或空头/多头占优结论。")
        av = breadth.get("amount_valid_count")
        if av is None:
            out.append("缺少 amount_valid_count，不得编造成交额覆盖率。")
        elif isinstance(av, (int, float)) and av == 0:
            out.append(
                "全市场快照成交额有效样本为 0（amount_valid_count=0），"
                "不得据此判断成交额、资金面或空头占优；注意勿与 valid_count（涨跌幅有效样本）混淆。"
            )
        if breadth.get("total_amount") is None:
            out.append("total_amount 不可用，不得编造全市场成交额数值。")
        # 防止把 0 有效成交额误写成 valid_count/stock_count
        if (
            isinstance(av, (int, float))
            and av == 0
            and isinstance(sc, (int, float))
            and sc
            and isinstance(vc, (int, float))
            and vc > 0
        ):
            out.append(
                f"涨跌幅有效样本 valid_count={int(vc)}、股票总数 stock_count={int(sc)}；"
                "成交额有效样本 amount_valid_count=0。二者口径不同，禁止写成 valid_count/stock_count=0/…。"
            )

    limit_stats = evidence.get("limit_stats") if isinstance(evidence.get("limit_stats"), dict) else None
    if limit_stats is None:
        out.append("短线情绪/涨跌停池不可用，不得编造涨停家数或跌停家数。")
    else:
        if limit_stats.get("limit_down_count") is None:
            out.append("未提供 limit_down_count（跌停池），不得声称跌停家数。")
        if limit_stats.get("limit_up_count") is None:
            out.append("未提供 limit_up_count（涨停池），不得声称涨停家数。")

    if not evidence.get("history_kline_available"):
        out.append(
            "无历史K线数据：禁止输出压力位、支撑位、均线、连续N日板块强弱、趋势突破或精确买卖价格区间。"
        )
    if evidence.get("data_cutoff") is None:
        out.append("缺少统一数据截止时间 data_cutoff，不得伪造行情更新时刻。")
    if not evidence.get("trade_date"):
        out.append("缺少明确交易日期 trade_date，不得伪造交易日。")
    return out


def _build_limitations(
    holdings: list[dict],
    *,
    market_ctx: dict | None = None,
    evidence: dict | None = None,
) -> list[str]:
    out: list[str] = list(_BASE_LIMITATIONS)
    if not holdings:
        out.append("当前无持仓，无法生成逐股操作建议。")
    missing_any = any(h.get("missing_quote_fields") for h in holdings)
    missing_prices = any(h.get("current_price") is None for h in holdings)
    if holdings and missing_prices:
        out.append("部分持仓缺少有效行情价格，相关市值与浮动盈亏已标记为 null。")
    if holdings and missing_any:
        out.append("部分持仓缺少完整日内行情字段，缺失值已标记为 null。")
    if market_ctx is not None and evidence is not None:
        out.extend(_dynamic_market_limitations(market_ctx, evidence))
    return _dedupe_keep_order(out)


def _normalize_quotes(quotes: Any) -> dict[str, dict]:
    if not isinstance(quotes, dict):
        return {}
    out: dict[str, dict] = {}
    for k, v in quotes.items():
        code = str(k).strip()
        if not code:
            continue
        if isinstance(v, dict):
            out[code] = v
    return out


def build_portfolio_advice_context(
    portfolio: dict,
    review: dict,
    *,
    quotes: dict[str, dict] | None = None,
    board_limit: int = 5,
    stock_limit: int = 10,
) -> dict:
    """构建持仓建议 AI 上下文（事实 + 数据边界，无操作建议）。

    Parameters
    ----------
    portfolio
        与 ``portfolio.get_portfolio()`` 相同形状的字典：
        ``{holdings: [...], totals: {...}, ...}``。
    review
        ``daily_review.generate_daily_review()`` 完整包。
    quotes
        可选，code → 行情字典。优先复用 a_share_snapshot / tencent_quote 字段。
        不注入时仅使用持仓行内 price，其余 quote 字段为 null。
    board_limit / stock_limit
        透传给每日复盘上下文投影器。
    """
    if not isinstance(portfolio, dict):
        raise TypeError("portfolio 必须是字典")
    if not isinstance(review, dict):
        raise TypeError("review 必须是字典")
    if not isinstance(board_limit, int) or isinstance(board_limit, bool) or not (1 <= board_limit <= 20):
        raise ValueError(f"board_limit 必须在 1..20 之间，收到：{board_limit!r}")
    if not isinstance(stock_limit, int) or isinstance(stock_limit, bool) or not (1 <= stock_limit <= 30):
        raise ValueError(f"stock_limit 必须在 1..30 之间，收到：{stock_limit!r}")

    quote_map = _normalize_quotes(quotes)

    raw_holdings = _as_list(portfolio.get("holdings"))
    holdings: list[dict] = []
    for row in raw_holdings:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        h = _project_holding(row, total_mv=0.0, quotes=quote_map)
        holdings.append(h)

    complete_coverage = len(holdings) > 0 and all(h.get("current_price") is not None for h in holdings)

    if complete_coverage:
        final_tmv = sum(_safe_float(h.get("market_value")) for h in holdings)
        if final_tmv > 0:
            for h in holdings:
                h["holding_weight_pct"] = _round2(
                    _safe_float(h.get("market_value")) / final_tmv * 100
                )
        else:
            for h in holdings:
                h["holding_weight_pct"] = 0.0
    else:
        for h in holdings:
            h["holding_weight_pct"] = None

    totals_in = _as_dict(portfolio.get("totals"))
    summary = _portfolio_summary(holdings, totals_in, complete_coverage=complete_coverage)

    market_ctx = build_daily_review_ai_context(
        review, board_limit=board_limit, stock_limit=stock_limit
    )
    market_evidence = _build_market_evidence(market_ctx)

    limitations = _build_limitations(
        holdings, market_ctx=market_ctx, evidence=market_evidence
    )
    warnings = list(_as_list(market_ctx.get("data_health", {}).get("warnings")))
    # 仅保留字符串 warnings，并稳定去重；清洗网络异常泄漏
    try:
        from daily_review_errors import sanitize_warning_list
        warnings = sanitize_warning_list(warnings)
    except Exception:  # noqa: BLE001
        warnings = _dedupe_keep_order(
            [w for w in warnings if isinstance(w, str) and w.strip()]
        )
    else:
        warnings = _dedupe_keep_order(warnings)

    ctx = {
        "schema_version": SCHEMA_VERSION,
        "portfolio_meta": {
            "updated": _str_or_none(portfolio.get("updated")),
            "last_refresh": _str_or_none(portfolio.get("last_refresh")),
            "holding_count": summary["holding_count"],
            "trade_date": market_evidence.get("trade_date"),
            "review_generated_at": market_evidence.get("review_generated_at"),
            "data_cutoff": market_evidence.get("data_cutoff"),
        },
        "portfolio_summary": {
            "holding_count": summary["holding_count"],
            "market_value": summary["market_value"],
            "cost": summary["cost"],
            "pnl": summary["pnl"],
            "pnl_pct": summary["pnl_pct"],
            # 明确权重分母语义，防止模型写成账户总仓位
            "weight_basis": "stock_holdings_market_value",
            "weight_basis_note": "权重分母为股票持仓市值合计，非账户总资产。",
        },
        "holdings": holdings,
        "market_context": market_ctx,
        "market_evidence": market_evidence,
        "data_limitations": limitations,
        "warnings": warnings,
        # 明确声明无账户层与可卖层字段
        "account_fields_available": {
            "total_assets": False,
            "cash_available": False,
            "sellable_shares": False,
            "today_buy_shares": False,
            "today_sell_shares": False,
            "history_kline": False,
            "technical_indicators": False,
        },
    }
    return ctx


def render_portfolio_advice_context(
    portfolio: dict,
    review: dict,
    *,
    quotes: dict[str, dict] | None = None,
    board_limit: int = 5,
    stock_limit: int = 10,
) -> str:
    """将持仓建议上下文渲染为紧凑 JSON 字符串。"""
    context = build_portfolio_advice_context(
        portfolio,
        review,
        quotes=quotes,
        board_limit=board_limit,
        stock_limit=stock_limit,
    )
    return json.dumps(
        context,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    )


def snapshot_context_without_advice(context: dict) -> dict:
    """浅层审计：确保上下文不含操作建议类键（递归扫描一级禁止键）。

    仅用于测试/调试；不修改输入。
    """
    if not isinstance(context, dict):
        raise TypeError("context 必须是字典")
    return copy.deepcopy(context)
