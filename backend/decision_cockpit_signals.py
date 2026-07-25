"""明日决策驱动舱的确定性信号评估（价值 / 趋势 / 短线）。

纯阈值规则，零模型依赖；所有输出 ``assessment`` 取值于
``strong / medium / weak / unknown``，``confidence`` 取值 [0, 1]，数据缺失
一律 ``unknown`` 不猜测。K 线不复权（price_adjustment: none）。

模块只读数据（K 线 / 财务 / 估值 / 全市场快照 / 情绪），不持久化；
证据落盘由 ``decision_cockpit_service`` 编排层负责。
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# 规则版本（写库时写入 decision_signals.rule_version）
# ---------------------------------------------------------------------------

RULE_VERSION_VALUE = "value-v0.2"
RULE_VERSION_TREND = "trend-v0.2-unadjusted"
RULE_VERSION_SHORT = "short-v0.2"

MIN_USABLE_SIGNALS_FOR_DIM = 3  # 候选级维度聚合最少可用信号数


def _stamp_rule_version(sigs: list[dict], version: str) -> list[dict]:
    for s in sigs:
        if isinstance(s, dict) and not s.get("rule_version"):
            s["rule_version"] = version
    return sigs



# ---------------------------------------------------------------------------
# 公共小工具
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):  # NaN/Inf
        return None
    return f


def _is_valid_code(code: Any) -> bool:
    return isinstance(code, str) and len(code) == 6 and code.isdigit()


# ---------------------------------------------------------------------------
# 价值信号（value-v0.2）
# ---------------------------------------------------------------------------

PE_STRONG_MAX = 20.0  # PE 分位 <= 20 → 低估区间
PE_WEAK_MIN = 80.0  # PE 分位 >= 80 → 高估区间
PB_STRONG_MAX = 20.0
PB_WEAK_MIN = 80.0
YOY_STRONG = 10.0  # 营收/净利同比 >= 10%
YOY_WEAK = -10.0
ROE_STRONG = 15.0
ROE_WEAK = 5.0
PEG_STRONG_MAX = 1.0  # PEG < 1 → 相对增长便宜
PEG_WEAK_MIN = 2.0  # PEG > 2 → 相对增长贵
CAGR_STRONG = 15.0
CAGR_WEAK = 0.0


def _percentile_assess(v: float | None, strong_max: float, weak_min: float) -> str:
    if v is None:
        return "unknown"
    if v <= strong_max:
        return "strong"
    if v >= weak_min:
        return "weak"
    return "medium"


def _yoy_assess(v: float | None) -> str:
    if v is None:
        return "unknown"
    if v >= YOY_STRONG:
        return "strong"
    if v <= YOY_WEAK:
        return "weak"
    return "medium"


def _roe_assess(v: float | None) -> str:
    if v is None:
        return "unknown"
    if v >= ROE_STRONG:
        return "strong"
    if v <= ROE_WEAK:
        return "weak"
    return "medium"


def _peg_assess(peg: float | None) -> str:
    if peg is None or peg <= 0:
        return "unknown"
    if peg < PEG_STRONG_MAX:
        return "strong"
    if peg > PEG_WEAK_MIN:
        return "weak"
    return "medium"


def _cagr_assess(cagr: float | None) -> str:
    if cagr is None:
        return "unknown"
    if cagr >= CAGR_STRONG:
        return "strong"
    if cagr <= CAGR_WEAK:
        return "weak"
    return "medium"


def evaluate_value(
    code: str,
    valuation: dict | None,
    financials: dict | None,
    full_valuation: dict | None = None,
) -> list[dict]:
    """价值维度信号。

    - PE/PB 历史分位：来自 ``valuation_percentile``。
    - 单期财务（营收/净利同比、ROE、毛利率、经营现金流）：仅作单期证据，
      不把净利同比当作 CAGR。
    - EPS/PE/CAGR/PEG：仅来自 ``astock.full_valuation`` 一致预期字段
      （eps_26e / pe_26e / cagr_pct / peg）。
    """
    if not _is_valid_code(code):
        return []
    sigs: list[dict] = []

    # PE / PB 历史分位
    metrics = (valuation or {}).get("metrics") if isinstance(valuation, dict) else {}
    if isinstance(metrics, dict):
        for key, strong_max, weak_min in (
            ("pe_ttm", PE_STRONG_MAX, PE_WEAK_MIN),
            ("pb", PB_STRONG_MAX, PB_WEAK_MIN),
        ):
            m = metrics.get(key) if isinstance(metrics.get(key), dict) else None
            if m is None:
                continue
            pct = _safe_float(m.get("percentile"))
            cur = _safe_float(m.get("current"))
            sigs.append({
                "dimension": "value",
                "label": f"{key}_percentile",
                "assessment": _percentile_assess(pct, strong_max, weak_min),
                "confidence": 0.7 if pct is not None else None,
                "value": cur,
                "context": {
                    "percentile": pct,
                    "band": {k: m.get(k) for k in ("min", "p20", "p50", "p80", "max", "n")},
                },
            })

    # 单期财务：只作 single_period 证据，禁止把 YoY 当 CAGR
    if isinstance(financials, dict) and financials:
        period = financials.get("period")
        single_ctx = {"evidence_kind": "single_period", "period": period}
        rev_yoy = _safe_float(financials.get("revenue_yoy"))
        sigs.append({
            "dimension": "value", "label": "revenue_yoy",
            "assessment": _yoy_assess(rev_yoy), "confidence": 0.6,
            "value": rev_yoy,
            "context": {**single_ctx, "revenue_yoy": rev_yoy},
        })
        np_yoy = _safe_float(financials.get("net_profit_yoy"))
        sigs.append({
            "dimension": "value", "label": "net_profit_yoy",
            "assessment": _yoy_assess(np_yoy), "confidence": 0.6,
            "value": np_yoy,
            "context": {**single_ctx, "net_profit_yoy": np_yoy},
        })
        roe = _safe_float(financials.get("roe"))
        sigs.append({
            "dimension": "value", "label": "roe",
            "assessment": _roe_assess(roe), "confidence": 0.6,
            "value": roe,
            "context": {**single_ctx, "roe": roe},
        })
        gm = _safe_float(financials.get("gross_margin"))
        sigs.append({
            "dimension": "value", "label": "gross_margin",
            "assessment": "medium" if gm is not None else "unknown",
            "confidence": None, "value": gm,
            "context": {**single_ctx, "gross_margin": gm, "fact_only": True},
        })
        op_cf = _safe_float(financials.get("op_cf_ps"))
        if op_cf is None:
            op_assess = "unknown"
        elif op_cf > 0:
            op_assess = "strong"
        else:
            op_assess = "weak"
        sigs.append({
            "dimension": "value", "label": "op_cf_ps",
            "assessment": op_assess, "confidence": 0.5, "value": op_cf,
            "context": {**single_ctx, "op_cf_ps": op_cf},
        })

    # 一致预期 EPS / 前向 PE / CAGR / PEG（full_valuation）
    fv = full_valuation if isinstance(full_valuation, dict) else None
    if fv:
        eps_26e = _safe_float(fv.get("eps_26e"))
        pe_26e = _safe_float(fv.get("pe_26e"))
        cagr_pct = _safe_float(fv.get("cagr_pct"))
        peg = _safe_float(fv.get("peg"))
        pe_ttm = _safe_float(fv.get("pe_ttm"))
        fv_ctx = {
            "source": "full_valuation",
            "eps_26e": eps_26e,
            "eps_27e": _safe_float(fv.get("eps_27e")),
            "pe_26e": pe_26e,
            "pe_ttm": pe_ttm,
            "cagr_pct": cagr_pct,
            "peg": peg,
            "analyst_count": fv.get("analyst_count"),
        }
        sigs.append({
            "dimension": "value", "label": "eps_26e",
            "assessment": "medium" if eps_26e is not None and eps_26e > 0 else "unknown",
            "confidence": 0.5 if eps_26e is not None else None,
            "value": eps_26e, "context": fv_ctx,
        })
        if pe_26e is not None and pe_26e > 0:
            if pe_26e <= 15:
                pe_assess = "strong"
            elif pe_26e >= 40:
                pe_assess = "weak"
            else:
                pe_assess = "medium"
        else:
            pe_assess = "unknown"
        sigs.append({
            "dimension": "value", "label": "pe_26e",
            "assessment": pe_assess,
            "confidence": 0.5 if pe_assess != "unknown" else None,
            "value": pe_26e, "context": fv_ctx,
        })
        sigs.append({
            "dimension": "value", "label": "cagr_pct",
            "assessment": _cagr_assess(cagr_pct),
            "confidence": 0.5 if cagr_pct is not None else None,
            "value": cagr_pct, "context": fv_ctx,
        })
        # PEG 仅在一致预期字段齐全时输出；禁止用单期净利 YoY 伪造
        if peg is not None and peg > 0 and cagr_pct is not None and cagr_pct > 0:
            sigs.append({
                "dimension": "value", "label": "peg",
                "assessment": _peg_assess(peg), "confidence": 0.55,
                "value": peg, "context": fv_ctx,
            })
        else:
            sigs.append({
                "dimension": "value", "label": "peg",
                "assessment": "unknown", "confidence": None,
                "value": peg,
                "context": {**fv_ctx, "reason": "missing_consistent_eps_cagr_peg"},
            })
    else:
        sigs.append({
            "dimension": "value", "label": "peg",
            "assessment": "unknown", "confidence": None, "value": None,
            "context": {
                "source": "full_valuation",
                "reason": "full_valuation_unavailable",
            },
        })

    return _stamp_rule_version(sigs, RULE_VERSION_VALUE)


# ---------------------------------------------------------------------------
# 趋势信号（trend-v0.2-unadjusted, 不复权）
# ---------------------------------------------------------------------------

MA_DIRECTION_WINDOW = 5
TREND_MIN_BARS = 60
TREND_SHORT_MA = 20
TREND_LONG_MA = 60
GAP_DISCONTINUITY_PCT = 18.0  # 不复权断点阈值


def _ma(bars: list[dict], field: str, window: int) -> float | None:
    vals = [_safe_float(b.get(field)) for b in bars[-window:]]
    vals = [v for v in vals if v is not None]
    if len(vals) < window:
        return None
    return sum(vals) / len(vals)


def _ma_at(bars: list[dict], field: str, window: int, end_index: int) -> float | None:
    """在 ``end_index``（含）处结束的 ``window`` 日均线。"""
    if end_index < 0 or end_index >= len(bars):
        return None
    start = end_index - window + 1
    if start < 0:
        return None
    vals = [_safe_float(b.get(field)) for b in bars[start: end_index + 1]]
    vals = [v for v in vals if v is not None]
    if len(vals) < window:
        return None
    return sum(vals) / len(vals)


def _max_drawdown(bars: list[dict], field: str = "close") -> float | None:
    """最大回撤（从峰值到谷底的最大跌幅，负数或 None）。"""
    peak: float | None = None
    worst: float | None = None
    for b in bars:
        p = _safe_float(b.get(field))
        if p is None or p <= 0:
            continue
        if peak is None or p > peak:
            peak = p
        if peak is not None:
            dd = (p - peak) / peak
            if worst is None or dd < worst:
                worst = dd
    return worst


def _gaps(bars: list[dict]) -> list[dict]:
    """相邻 K 线跳空（前收→今开涨幅绝对 > GAP_DISCONTINUITY_PCT）。"""
    res: list[dict] = []
    for i in range(1, len(bars)):
        prev = _safe_float(bars[i - 1].get("close"))
        cur_open = _safe_float(bars[i].get("open"))
        if prev is None or cur_open is None or prev <= 0:
            continue
        jump = (cur_open - prev) / prev * 100
        if abs(jump) > GAP_DISCONTINUITY_PCT:
            res.append({
                "index": i,
                "jump_pct": round(jump, 2),
                "direction": "up" if jump > 0 else "down",
            })
    return res


def evaluate_trend(code: str, kline_bars: list[dict]) -> list[dict]:
    """趋势维度信号（不复权）。

    - MA20 方向：当前 MA20 vs 5 个交易日前的 MA20（不是收盘价单调性）。
    - 负向跳空不得判 strong；不复权断点（|跳空| > 18%）→ 相关评估 unknown。
    """
    if not _is_valid_code(code):
        return []
    bars = kline_bars if isinstance(kline_bars, list) else []
    n = len(bars)
    sigs: list[dict] = []
    price_adj = "none"

    ma20 = _ma(bars, "close", TREND_SHORT_MA)
    ma60 = _ma(bars, "close", TREND_LONG_MA)
    last_close = _safe_float(bars[-1].get("close")) if bars else None
    gaps = _gaps(bars)
    has_discontinuity = bool(gaps)

    if n < TREND_MIN_BARS or ma20 is None or ma60 is None or last_close is None:
        sigs.append({
            "dimension": "trend", "label": "ma_alignment",
            "assessment": "unknown", "confidence": None, "value": None,
            "context": {
                "n": n, "min_bars": TREND_MIN_BARS, "reason": "insufficient_data",
                "price_adjustment": price_adj,
            },
        })
        return _stamp_rule_version(sigs, RULE_VERSION_TREND)

    # 不复权断点：核心趋势评估降为 unknown（避免除权缺口误判）
    if has_discontinuity:
        worst = max(gaps, key=lambda g: abs(g["jump_pct"]))
        sigs.append({
            "dimension": "trend", "label": "ma_alignment",
            "assessment": "unknown", "confidence": None,
            "value": {"ma20": round(ma20, 3), "ma60": round(ma60, 3)},
            "context": {
                "ma20": round(ma20, 3), "ma60": round(ma60, 3),
                "close": last_close, "n": n, "price_adjustment": price_adj,
                "reason": "non_adjusted_discontinuity",
                "worst_gap": worst,
            },
        })
        sigs.append({
            "dimension": "trend", "label": "ma20_direction",
            "assessment": "unknown", "confidence": None, "value": None,
            "context": {
                "window": MA_DIRECTION_WINDOW, "price_adjustment": price_adj,
                "reason": "non_adjusted_discontinuity", "worst_gap": worst,
            },
        })
        # 跳空本身：负向不得 strong
        jump = worst["jump_pct"]
        if jump < 0:
            gap_assess = "weak" if abs(jump) > 25 else "medium"
        else:
            gap_assess = "medium"  # 正向大跳空在不复权下不可信，不给 strong
        sigs.append({
            "dimension": "trend", "label": "gap",
            "assessment": gap_assess, "confidence": 0.3, "value": worst,
            "context": {
                "gaps": gaps[:5], "worst": worst,
                "price_adjustment": price_adj,
                "note": "negative_gap_not_strong",
            },
        })
        return _stamp_rule_version(sigs, RULE_VERSION_TREND)

    # MA 排列
    if last_close > ma20 > ma60:
        align = "strong"
    elif last_close < ma20 < ma60:
        align = "weak"
    elif ma20 > ma60:
        align = "medium"
    else:
        align = "weak"
    sigs.append({
        "dimension": "trend", "label": "ma_alignment",
        "assessment": align, "confidence": 0.6,
        "value": {"ma20": round(ma20, 3), "ma60": round(ma60, 3)},
        "context": {
            "ma20": round(ma20, 3), "ma60": round(ma60, 3),
            "close": last_close, "n": n, "price_adjustment": price_adj,
        },
    })

    # MA20 方向：当前 MA20 vs 5 个交易日前的 MA20
    end_idx = n - 1
    past_idx = end_idx - MA_DIRECTION_WINDOW
    ma20_now = ma20
    ma20_past = _ma_at(bars, "close", TREND_SHORT_MA, past_idx)
    if ma20_now is None or ma20_past is None or ma20_past == 0:
        ma20_dir = None
        ma20_assess = "unknown"
        delta_pct = None
    else:
        delta_pct = (ma20_now - ma20_past) / abs(ma20_past) * 100
        if delta_pct > 0.5:
            ma20_dir = "rising"
            ma20_assess = "strong"
        elif delta_pct < -0.5:
            ma20_dir = "falling"
            ma20_assess = "weak"
        else:
            ma20_dir = "flat"
            ma20_assess = "medium"
    sigs.append({
        "dimension": "trend", "label": "ma20_direction",
        "assessment": ma20_assess, "confidence": 0.5 if ma20_dir else None,
        "value": ma20_dir,
        "context": {
            "window": MA_DIRECTION_WINDOW,
            "ma20_now": round(ma20_now, 3) if ma20_now is not None else None,
            "ma20_past": round(ma20_past, 3) if ma20_past is not None else None,
            "delta_pct": round(delta_pct, 3) if delta_pct is not None else None,
            "price_adjustment": price_adj,
            "method": "ma20_vs_ma20_n_sessions_ago",
        },
    })

    # 相对 MA20 的阶段高低
    if ma20 and ma20 > 0:
        dev = (last_close - ma20) / ma20 * 100
        if dev >= 15:
            stage = "high"
        elif dev <= -10:
            stage = "low"
        else:
            stage = "mid"
        sigs.append({
            "dimension": "trend", "label": "stage",
            "assessment": "weak" if stage == "high" else ("strong" if stage == "low" else "medium"),
            "confidence": 0.4, "value": stage,
            "context": {"dev_ma20_pct": round(dev, 2), "stage": stage},
        })

    dd = _max_drawdown(bars)
    sigs.append({
        "dimension": "trend", "label": "max_drawdown",
        "assessment": "weak" if (dd is not None and dd <= -0.30) else "medium",
        "confidence": 0.4,
        "value": round(dd, 4) if dd is not None else None,
        "context": {"max_drawdown": round(dd, 4) if dd is not None else None},
    })

    vol5 = _ma(bars, "volume", 5)
    vol20 = _ma(bars, "volume", 20)
    if vol5 is not None and vol20 and vol20 > 0:
        ratio = round(vol5 / vol20, 3)
        sigs.append({
            "dimension": "trend", "label": "vol_ratio_5_20",
            "assessment": "strong" if ratio > 1.5 else ("weak" if ratio < 0.7 else "medium"),
            "confidence": 0.4, "value": ratio,
            "context": {"vol5": vol5, "vol20": vol20, "ratio": ratio},
        })

    if n >= 21:
        ref = _safe_float(bars[-21].get("close"))
        if ref and ref > 0 and last_close is not None:
            gain20 = (last_close - ref) / ref * 100
            if gain20 >= 20:
                g20 = "strong"
            elif gain20 <= -20:
                g20 = "weak"
            else:
                g20 = "medium"
            sigs.append({
                "dimension": "trend", "label": "gain_20d",
                "assessment": g20, "confidence": 0.4,
                "value": round(gain20, 2),
                "context": {"gain_20d_pct": round(gain20, 2)},
            })

    if ma20 and ma60 and last_close is not None:
        if last_close < ma20 < ma60 and ma20_dir == "falling":
            sigs.append({
                "dimension": "trend", "label": "trend_failure",
                "assessment": "weak", "confidence": 0.5,
                "value": True,
                "context": {
                    "close": last_close,
                    "ma20": round(ma20, 3),
                    "ma60": round(ma60, 3),
                },
            })

    return _stamp_rule_version(sigs, RULE_VERSION_TREND)


# ---------------------------------------------------------------------------
# 短线 / 候选池（short-v0.2）
# ---------------------------------------------------------------------------

MAX_CANDIDATES = 60
_AMOUNT_TOP_N = 30
_HIGH_TURNOVER_N = 30
_HIGH_TURNOVER_MIN = 15.0
CASH_LOT = 100  # 每手股数
SECTOR_STRONG_RANK_MAX = 20  # 行业排名前 20 视为强


def build_candidate_pool(
    holdings: list[dict] | None,
    watchlist: list[str],
    sector_codes: list[str],
    lianban: list[dict] | None,
    turnover_top: list[dict] | None,
    high_turnover: list[dict] | None,
    *,
    max_candidates: int = MAX_CANDIDATES,
) -> list[dict]:
    """候选池 = 持仓 + 自选 + 板块代表（受保护）+ 连板 / 成交额 / 高换手（填充）。

    返回去重候选列表 ``[{"code", "name", "sources": [...]}]``，最多 ``max_candidates`` 个。
    """
    order: list[dict] = []
    seen: set[str] = set()

    def add(code: str, name: str, source: str) -> None:
        if not _is_valid_code(code) or code in seen:
            if code in seen:
                for c in order:
                    if c["code"] == code and source not in c["sources"]:
                        c["sources"].append(source)
            return
        seen.add(code)
        order.append({"code": code, "name": (name or "").strip(), "sources": [source]})

    for h in holdings or []:
        if not isinstance(h, dict):
            continue
        add(h.get("code", ""), h.get("name", ""), "holding")
    for c in watchlist or []:
        add(c, "", "watchlist")
    for c in sector_codes or []:
        add(c, "", "sector")

    protected = list(order)

    def feed(items: list[dict] | None, source: str) -> None:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            add(it.get("code", ""), it.get("name", ""), source)

    feed(lianban, "lianban")
    feed(turnover_top, "turnover_top")
    feed(high_turnover, "high_turnover")

    protected_codes = {c["code"] for c in protected}
    capped_fill = [c for c in order if c["code"] not in protected_codes]
    keep_fill = capped_fill[: max(0, max_candidates - len(protected))]
    result = protected + keep_fill
    return result[:max_candidates]


def compute_cash_exec(
    intended_shares: int | float | None,
    latest_price: float | None,
    available_cash: float | None,
) -> dict:
    """现金可执行性：按建议原始买入数量 + 最新价 + 可用现金。

    返回字段（P7）：
    ``required_cash``, ``available_cash``, ``latest_price``,
    ``max_executable_shares``, ``funding_gap``, ``is_executable``。

    - 买入数量向下取整到 100 股（A 股一手）；
    - 不得用「当前持仓股数」充当买入需求——调用方应传入建议
      ``execution_quantity`` / 估算买入股数。
    """
    qty = _safe_float(intended_shares)
    price = _safe_float(latest_price)
    cash = _safe_float(available_cash)

    base = {
        "required_cash": None,
        "available_cash": cash,
        "latest_price": price,
        "max_executable_shares": 0,
        "funding_gap": None,
        "is_executable": False,
        # 兼容旧字段
        "executable": False,
        "lots": 0,
        "shares": 0,
        "estimated_cost": 0.0,
        "reason": None,
    }
    if qty is None or qty <= 0 or price is None or price <= 0:
        base["reason"] = "invalid_inputs"
        return base

    # 建议原始需求：向下取整到 100 股
    intended_lots = int(qty // CASH_LOT)
    intended_shares = intended_lots * CASH_LOT
    required_cash = round(intended_shares * price, 2) if intended_shares else 0.0
    base["required_cash"] = required_cash

    if cash is None:
        base["reason"] = "cash_unconfigured"
        base["funding_gap"] = required_cash
        return base

    max_lots_by_cash = int(cash // (price * CASH_LOT)) if price > 0 else 0
    max_executable_shares = max(0, max_lots_by_cash) * CASH_LOT
    executable_lots = min(intended_lots, max_lots_by_cash)
    executable_shares = executable_lots * CASH_LOT
    estimated = round(executable_shares * price, 2) if executable_shares else 0.0
    funding_gap = round(max(0.0, required_cash - cash), 2)

    # is_executable：原建议数量在现金内可完整执行（无资金缺口）
    fully_executable = (
        intended_shares > 0
        and executable_shares == intended_shares
        and funding_gap == 0
    )
    reason = None
    if executable_shares <= 0:
        reason = "insufficient_cash"
    elif executable_shares < intended_shares:
        reason = "partial"
    base.update({
        "max_executable_shares": max_executable_shares,
        "funding_gap": funding_gap,
        "is_executable": fully_executable,
        "executable": executable_shares > 0,
        "lots": executable_lots,
        "shares": executable_shares,
        "estimated_cost": estimated,
        "reason": reason,
    })
    return base


def evaluate_market_short(breadth: dict | None, emotion: dict | None) -> dict:
    """市场级短线状态（广度 + 情绪），返回统一信封。"""
    data: dict = {"breadth": breadth, "emotion": emotion}
    status = "partial"
    warnings: list[str] = []
    try:
        if isinstance(breadth, dict) and breadth.get("status") == "normal":
            if isinstance(emotion, dict) and emotion:
                status = "normal"
            else:
                warnings.append("情绪数据不可用")
        else:
            warnings.append("市场广度不可用")
            status = "unavailable"
            data["breadth"] = None
    except Exception as e:  # noqa: BLE001
        status = "unavailable"
        warnings.append(f"市场评估异常：{type(e).__name__}")
    return {
        "status": status,
        "is_stale": False,
        "warnings": warnings,
        "data": data if status != "unavailable" else None,
    }


def evaluate_candidate_short(
    code: str,
    *,
    market_short: dict | None,
    lianban_codes: set[str] | None = None,
    turnover_top_codes: set[str] | None = None,
    high_turnover_codes: set[str] | None = None,
    sector_rank: int | None = None,
    lianban_meta: dict | None = None,
) -> list[dict]:
    """候选级短线维度：连板 / 成交额榜 / 高换手 / 板块强弱 / 市场环境。

    任一输入不足时对应标签 ``unknown``；不可仅返回市场级 status。
    """
    if not _is_valid_code(code):
        return []
    sigs: list[dict] = []
    lianban = lianban_codes or set()
    turnover = turnover_top_codes or set()
    high_to = high_turnover_codes or set()

    has_any_list = bool(lianban or turnover or high_to or sector_rank is not None)
    mkt_status = (market_short or {}).get("status") if isinstance(market_short, dict) else None

    # 市场环境（候选上下文，不是唯一输出）
    if mkt_status == "normal":
        mkt_assess = "medium"
    elif mkt_status == "partial":
        mkt_assess = "medium"
    elif mkt_status == "unavailable":
        mkt_assess = "unknown"
    else:
        mkt_assess = "unknown"
    sigs.append({
        "dimension": "short", "label": "market_environment",
        "assessment": mkt_assess,
        "confidence": 0.4 if mkt_assess != "unknown" else None,
        "value": mkt_status,
        "context": {"market_status": mkt_status},
    })

    if not has_any_list and mkt_assess == "unknown":
        # 完全无短线数据
        for label in ("lianban", "turnover_top", "high_turnover", "sector_strength"):
            sigs.append({
                "dimension": "short", "label": label,
                "assessment": "unknown", "confidence": None, "value": None,
                "context": {"reason": "insufficient_data"},
            })
        return _stamp_rule_version(sigs, RULE_VERSION_SHORT)

    # 连板
    if code in lianban:
        boards = None
        if isinstance(lianban_meta, dict):
            boards = lianban_meta.get("boards")
        assess = "strong" if (boards is None or (isinstance(boards, (int, float)) and boards >= 2)) else "medium"
        sigs.append({
            "dimension": "short", "label": "lianban",
            "assessment": assess, "confidence": 0.6,
            "value": True,
            "context": {"in_lianban": True, "boards": boards},
        })
    elif lianban:
        sigs.append({
            "dimension": "short", "label": "lianban",
            "assessment": "medium", "confidence": 0.4,
            "value": False,
            "context": {"in_lianban": False},
        })
    else:
        sigs.append({
            "dimension": "short", "label": "lianban",
            "assessment": "unknown", "confidence": None, "value": None,
            "context": {"reason": "lianban_data_unavailable"},
        })

    # 成交额榜
    if code in turnover:
        sigs.append({
            "dimension": "short", "label": "turnover_top",
            "assessment": "strong", "confidence": 0.55,
            "value": True, "context": {"in_turnover_top": True},
        })
    elif turnover:
        sigs.append({
            "dimension": "short", "label": "turnover_top",
            "assessment": "medium", "confidence": 0.4,
            "value": False, "context": {"in_turnover_top": False},
        })
    else:
        sigs.append({
            "dimension": "short", "label": "turnover_top",
            "assessment": "unknown", "confidence": None, "value": None,
            "context": {"reason": "turnover_top_unavailable"},
        })

    # 高换手
    if code in high_to:
        sigs.append({
            "dimension": "short", "label": "high_turnover",
            "assessment": "strong", "confidence": 0.5,
            "value": True, "context": {"in_high_turnover": True},
        })
    elif high_to:
        sigs.append({
            "dimension": "short", "label": "high_turnover",
            "assessment": "medium", "confidence": 0.4,
            "value": False, "context": {"in_high_turnover": False},
        })
    else:
        sigs.append({
            "dimension": "short", "label": "high_turnover",
            "assessment": "unknown", "confidence": None, "value": None,
            "context": {"reason": "high_turnover_unavailable"},
        })

    # 板块强弱（行业排名）
    if sector_rank is None:
        sigs.append({
            "dimension": "short", "label": "sector_strength",
            "assessment": "unknown", "confidence": None, "value": None,
            "context": {"reason": "sector_rank_unavailable"},
        })
    elif sector_rank <= SECTOR_STRONG_RANK_MAX:
        sigs.append({
            "dimension": "short", "label": "sector_strength",
            "assessment": "strong", "confidence": 0.5,
            "value": sector_rank,
            "context": {"industry_rank": sector_rank, "strong_max": SECTOR_STRONG_RANK_MAX},
        })
    elif sector_rank <= 50:
        sigs.append({
            "dimension": "short", "label": "sector_strength",
            "assessment": "medium", "confidence": 0.4,
            "value": sector_rank,
            "context": {"industry_rank": sector_rank},
        })
    else:
        sigs.append({
            "dimension": "short", "label": "sector_strength",
            "assessment": "weak", "confidence": 0.4,
            "value": sector_rank,
            "context": {"industry_rank": sector_rank},
        })

    return _stamp_rule_version(sigs, RULE_VERSION_SHORT)


def _usable_assessment(assessment: str | None) -> bool:
    """可用信号：非 unknown 且 assessment 合法。"""
    return assessment in ("strong", "medium", "weak")


def _dim_summary_from_signals(dim_signals: list[dict]) -> dict:
    """对单维度信号列表做透明聚合（无星级打分）。

    规则：
    - 可用信号数 < MIN_USABLE_SIGNALS_FOR_DIM → assessment=unknown
    - 否则：若有 strong 且无 weak 偏 strong；strong/weak 并存 → medium；
      全 weak → weak；否则取众数（strong>medium>weak 优先）。
    """
    usable = [s for s in dim_signals if _usable_assessment(s.get("assessment"))]
    n_usable = len(usable)
    n_total = len(dim_signals)
    base = {
        "usable_count": n_usable,
        "total_count": n_total,
        "min_required": MIN_USABLE_SIGNALS_FOR_DIM,
        "labels": [s.get("label") for s in dim_signals],
    }
    if n_usable < MIN_USABLE_SIGNALS_FOR_DIM:
        return {
            "assessment": "unknown",
            "reason": "insufficient_usable_signals",
            **base,
        }
    counts = {"strong": 0, "medium": 0, "weak": 0}
    for s in usable:
        counts[s["assessment"]] = counts.get(s["assessment"], 0) + 1
    if counts["strong"] > 0 and counts["weak"] == 0:
        assess = "strong" if counts["strong"] >= counts["medium"] else "medium"
    elif counts["weak"] > 0 and counts["strong"] == 0:
        assess = "weak" if counts["weak"] >= counts["medium"] else "medium"
    elif counts["strong"] > 0 and counts["weak"] > 0:
        assess = "medium"
    else:
        assess = "medium"
    return {
        "assessment": assess,
        "counts": counts,
        "reason": "aggregated",
        **base,
    }


def aggregate_candidate_dimensions(
    candidates: list[dict],
    signals: list[dict],
) -> list[dict]:
    """候选级 value/trend/short 三维摘要。

    透明规则：每维 ≥3 条可用信号才给出 strong/medium/weak，否则 unknown。
    不输出星级分数。
    """
    by_code: dict[str, list[dict]] = {}
    for s in signals or []:
        code = s.get("candidate_code") or s.get("code")
        if not isinstance(code, str):
            continue
        by_code.setdefault(code, []).append(s)

    out: list[dict] = []
    for c in candidates or []:
        code = c.get("code") if isinstance(c, dict) else None
        if not isinstance(code, str):
            continue
        sigs = by_code.get(code, [])
        dims: dict[str, dict] = {}
        for dim, rule_ver in (
            ("value", RULE_VERSION_VALUE),
            ("trend", RULE_VERSION_TREND),
            ("short", RULE_VERSION_SHORT),
        ):
            dim_sigs = [s for s in sigs if s.get("dimension") == dim]
            summary = _dim_summary_from_signals(dim_sigs)
            summary["rule_version"] = rule_ver
            dims[dim] = summary
        out.append({
            "code": code,
            "name": (c.get("name") if isinstance(c, dict) else "") or "",
            "sources": list(c.get("sources") or []) if isinstance(c, dict) else [],
            "dimensions": dims,
        })
    return out
