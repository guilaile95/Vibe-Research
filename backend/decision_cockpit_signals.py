"""明日决策驱动舱的确定性信号评估（价值 / 趋势 / 短线）。

纯阈值规则，零模型依赖；所有输出 ``assessment`` 取值于
``strong / medium / weak / unknown``，``confidence`` 取值 [0, 1]，数据缺失
一律 ``unknown`` 不猜测。K 线不复权（price_adjustment: none）。

模块只读数据（K 线 / 财务 / 估值分位 / 全市场快照 / 情绪），不持久化；
证据落盘由 ``decision_cockpit_service`` 编排层负责。
"""

from __future__ import annotations

from typing import Any

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
# 价值信号（value-v0.1）
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


def evaluate_value(code: str, valuation: dict | None, financials: dict | None) -> list[dict]:
    """价值维度信号：PE / PB 分位、同比增速、ROE、毛利率、经营现金流、PEG。"""
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

    # 财务同比 / 盈利
    if isinstance(financials, dict) and financials:
        rev_yoy = _safe_float(financials.get("revenue_yoy"))
        sigs.append({
            "dimension": "value", "label": "revenue_yoy",
            "assessment": _yoy_assess(rev_yoy), "confidence": 0.6,
            "value": rev_yoy, "context": {"revenue_yoy": rev_yoy},
        })
        np_yoy = _safe_float(financials.get("net_profit_yoy"))
        sigs.append({
            "dimension": "value", "label": "net_profit_yoy",
            "assessment": _yoy_assess(np_yoy), "confidence": 0.6,
            "value": np_yoy, "context": {"net_profit_yoy": np_yoy},
        })
        roe = _safe_float(financials.get("roe"))
        sigs.append({
            "dimension": "value", "label": "roe",
            "assessment": _roe_assess(roe), "confidence": 0.6,
            "value": roe, "context": {"roe": roe},
        })
        # 毛利率：仅事实披露，不做强弱判断（行业差异大）。
        gm = _safe_float(financials.get("gross_margin"))
        sigs.append({
            "dimension": "value", "label": "gross_margin",
            "assessment": "medium" if gm is not None else "unknown",
            "confidence": None, "value": gm,
            "context": {"gross_margin": gm, "fact_only": True},
        })
        # 每股经营现金流：正/负事实 + 粗略强弱。
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
            "context": {"op_cf_ps": op_cf},
        })

        # PEG = PE-TTM / CAGR(净利同比)。仅当 CAGR>0 且 PE>0 可算。
        pe_m = metrics.get("pe_ttm") if isinstance(metrics, dict) else None
        pe_cur = _safe_float(pe_m.get("current")) if isinstance(pe_m, dict) else None
        if pe_cur is not None and pe_cur > 0 and np_yoy is not None and np_yoy > 0:
            peg = round(pe_cur / np_yoy, 3)
            sigs.append({
                "dimension": "value", "label": "peg",
                "assessment": _peg_assess(peg), "confidence": 0.5,
                "value": peg,
                "context": {"peg": peg, "pe_ttm": pe_cur, "cagr_proxy": np_yoy},
            })

    return sigs


# ---------------------------------------------------------------------------
# 趋势信号（trend-v0.1-unadjusted, 不复权）
# ---------------------------------------------------------------------------

MA_DIRECTION_WINDOW = 5
TREND_MIN_BARS = 60
TREND_SHORT_MA = 20
TREND_LONG_MA = 60


def _ma(bars: list[dict], field: str, window: int) -> float | None:
    vals = [_safe_float(b.get(field)) for b in bars[-window:]]
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


def _close_only(bars: list[dict]) -> list[float]:
    out = []
    for b in bars:
        c = _safe_float(b.get("close"))
        if c is not None:
            out.append(c)
    return out


def _gaps(bars: list[dict]) -> list[dict]:
    """相邻 K 线跳空（前收→今开涨幅 > 18%）。返回触发点列表。"""
    res: list[dict] = []
    for i in range(1, len(bars)):
        prev = _safe_float(bars[i - 1].get("close"))
        cur_open = _safe_float(bars[i].get("open"))
        if prev is None or cur_open is None or prev <= 0:
            continue
        jump = (cur_open - prev) / prev * 100
        if abs(jump) > 18:
            res.append({"index": i, "jump_pct": round(jump, 2)})
    return res


def evaluate_trend(code: str, kline_bars: list[dict]) -> list[dict]:
    """趋势维度信号（不复权）：MA20/MA60 排列、回撤、量价比、20 日涨幅、趋势失效、跳空。"""
    if not _is_valid_code(code):
        return []
    bars = kline_bars if isinstance(kline_bars, list) else []
    n = len(bars)
    sigs: list[dict] = []

    ma20 = _ma(bars, "close", TREND_SHORT_MA)
    ma60 = _ma(bars, "close", TREND_LONG_MA)
    last_close = _safe_float(bars[-1].get("close")) if bars else None

    if n < TREND_MIN_BARS or ma20 is None or ma60 is None or last_close is None:
        sigs.append({
            "dimension": "trend", "label": "ma_alignment",
            "assessment": "unknown", "confidence": None, "value": None,
            "context": {"n": n, "min_bars": TREND_MIN_BARS, "reason": "insufficient_data"},
        })
        return sigs

    # MA 排列：多头 / 空头 / 震荡
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
            "close": last_close, "n": n, "price_adjustment": "none",
        },
    })

    # MA 方向（近 MA_DIRECTION_WINDOW 根 K 线的单调性）
    def _dir(window: int) -> str | None:
        seq = _close_only(bars[-window:])
        if len(seq) < 2:
            return None
        if all(seq[i] > seq[i - 1] for i in range(1, len(seq))):
            return "rising"
        if all(seq[i] < seq[i - 1] for i in range(1, len(seq))):
            return "falling"
        return "flat"

    ma20_dir = _dir(min(MA_DIRECTION_WINDOW, n))
    sigs.append({
        "dimension": "trend", "label": "ma20_direction",
        "assessment": "strong" if ma20_dir == "rising" else ("weak" if ma20_dir == "falling" else "medium"),
        "confidence": 0.4, "value": ma20_dir,
        "context": {"window": MA_DIRECTION_WINDOW},
    })

    # 相对 MA20 的阶段高低（当前价 / MA20 偏离）
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

    # 最大回撤
    dd = _max_drawdown(bars)
    sigs.append({
        "dimension": "trend", "label": "max_drawdown",
        "assessment": "weak" if (dd is not None and dd <= -0.30) else "medium",
        "confidence": 0.4,
        "value": round(dd, 4) if dd is not None else None,
        "context": {"max_drawdown": round(dd, 4) if dd is not None else None},
    })

    # 量价比：近 5 日 / 20 日均量比
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

    # 20 日涨幅
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

    # 趋势失效：close<MA20<MA60 同时 MA20 方向转跌
    if ma20 and ma60 and last_close is not None:
        if last_close < ma20 < ma60 and ma20_dir == "falling":
            sigs.append({
                "dimension": "trend", "label": "trend_failure",
                "assessment": "weak", "confidence": 0.5,
                "value": True,
                "context": {"close": last_close, "ma20": round(ma20, 3), "ma60": round(ma60, 3)},
            })

    # 跳空（|前收→今开| > 18%）
    gaps = _gaps(bars)
    if gaps:
        worst = max(gaps, key=lambda g: abs(g["jump_pct"]))
        sigs.append({
            "dimension": "trend", "label": "gap",
            "assessment": "strong" if abs(worst["jump_pct"]) > 25 else "medium",
            "confidence": 0.4, "value": worst,
            "context": {"gaps": gaps[:5], "worst": worst},
        })

    return sigs


# ---------------------------------------------------------------------------
# 短线 / 候选池（short-v0.1）
# ---------------------------------------------------------------------------

MAX_CANDIDATES = 60
_AMOUNT_TOP_N = 30
_HIGH_TURNOVER_N = 30
_HIGH_TURNOVER_MIN = 15.0
CASH_LOT = 100  # 每手股数


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
    """候选池 = 持仓 + 自选 + 板块代表（受保护，计入上限前保留）+ 连板 / 成交额 / 高换手（填充剩余名额）。

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

    # 受保护源：持仓
    for h in holdings or []:
        if not isinstance(h, dict):
            continue
        add(h.get("code", ""), h.get("name", ""), "holding")
    # 受保护源：自选
    for c in watchlist or []:
        add(c, "", "watchlist")
    # 受保护源：板块代表公司
    for c in sector_codes or []:
        add(c, "", "sector")

    protected = list(order)  # 快照受保护集合

    # 填充源
    def feed(items: list[dict] | None, source: str) -> None:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            add(it.get("code", ""), it.get("name", ""), source)

    feed(lianban, "lianban")
    feed(turnover_top, "turnover_top")
    feed(high_turnover, "high_turnover")

    # 受保护候选保留；填充源受上限裁剪
    protected_codes = {c["code"] for c in protected}
    capped_fill = [c for c in order if c["code"] not in protected_codes]
    keep_fill = capped_fill[: max(0, max_candidates - len(protected))]
    result = protected + keep_fill
    return result[:max_candidates]


def compute_cash_exec(
    raw_shares: int | float | None,
    latest_price: float | None,
    available_cash: float | None,
) -> dict:
    """可买手数（100 的整数倍），与可用现金取交集。"""
    shares = _safe_float(raw_shares)
    price = _safe_float(latest_price)
    cash = _safe_float(available_cash)
    if shares is None or price is None or price <= 0:
        return {"executable": False, "reason": "invalid_inputs", "lots": 0, "shares": 0}
    lots = int(shares // CASH_LOT)
    if cash is not None and cash >= 0:
        max_by_cash = int((cash // (price * CASH_LOT))) if price > 0 else 0
        lots = min(lots, max_by_cash)
    lots = max(lots, 0)
    return {
        "executable": lots > 0,
        "lots": lots,
        "shares": lots * CASH_LOT,
        "estimated_cost": round(lots * CASH_LOT * price, 2) if lots else 0.0,
    }


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
