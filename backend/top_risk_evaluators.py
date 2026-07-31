"""顶部风险评估器（Phase 1）。

硬约束（与旧原型的关键区别）：
- 每个 evaluator 只接收 TopRiskFact（service 已标准化），禁止访问网络、禁止取数；
- 不得修改共享状态、不得引入未来函数或事后数据；
- 缺失依赖数据源时返回 skipped（部分缺失 → partial，而非伪造 0）；
- 输出方向 RISK/SAFE/NEUTRAL 与 step_risk ∈ [-0.5, 1.0]，由引擎聚合。

Phase 1 边界：
- events / sentiment_series 主项目暂无可靠来源 → narrative_divergence / catalyst_priced_in
  直接 skipped（产生 limitation，使整体进入 partial），不伪造数据。
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional

from top_risk_schema import TopRiskFact, TopRiskStepResult

EVALUATORS: Dict[str, Callable[[TopRiskFact, dict], TopRiskStepResult]] = {}


def register(name: str):
    def deco(fn):
        EVALUATORS[name] = fn
        return fn

    return deco


# ---------------------------------------------------------------------------
# 数值工具
# ---------------------------------------------------------------------------
def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _mean(xs: list) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _std(xs: list) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def _z(v: Optional[float], mean: Optional[float], std: Optional[float]) -> Optional[float]:
    if v is None or mean is None or std in (None, 0):
        return None
    return (v - mean) / std


def _last_n(xs: list, n: int) -> list:
    return xs[-n:] if n > 0 else xs[:]


def _first_n(xs: list, n: int) -> list:
    return xs[:n] if n > 0 else xs[:]


# ---------------------------------------------------------------------------
# 1. 叙事背离（Phase 1：sentiment_series 缺失 → skipped）
# ---------------------------------------------------------------------------
@register("narrative_divergence")
def narrative_divergence(facts: TopRiskFact, params: dict) -> TopRiskStepResult:
    required = bool(params.get("sentiment_required", True))
    if facts.sentiment_series is None:
        return TopRiskStepResult(
            step_id="narrative_divergence",
            label="叙事背离",
            direction="NEUTRAL",
            weight=float(params.get("weight", 1.0)),
            step_risk=0.0,
            confidence=0.0,
            skipped=True,
            skip_reason="sentiment_series 缺失（Phase1 无可靠舆情来源）",
        )
    # 若未来接入舆情：价格强涨但舆情热度/看多比例未同步放大 → 背离 RISK。
    # Phase 1 不应到达此分支（service 恒置 None）。
    if required:
        return TopRiskStepResult(
            step_id="narrative_divergence",
            label="叙事背离",
            direction="NEUTRAL",
            weight=float(params.get("weight", 1.0)),
            step_risk=0.0,
            confidence=0.0,
            skipped=True,
            skip_reason="sentiment_series 存在但语义未定义（保留跳过）",
        )
    return TopRiskStepResult(
        step_id="narrative_divergence",
        label="叙事背离",
        direction="NEUTRAL",
        weight=float(params.get("weight", 1.0)),
        step_risk=0.0,
        confidence=0.0,
        skipped=True,
        skip_reason="未启用",
    )


# ---------------------------------------------------------------------------
# 2. 拥挤度（量能极端 + 融资余额快速攀升）
# ---------------------------------------------------------------------------
@register("crowding")
def crowding(facts: TopRiskFact, params: dict) -> TopRiskStepResult:
    weight = float(params.get("weight", 1.0))
    margin_window = max(1, int(params.get("margin_window", 20)))
    margin_rise_threshold = float(params.get("margin_rise_threshold", 0.25))
    z_threshold = float(params.get("turnover_z_threshold", 2.0))

    raw_volumes: list[Optional[float]] = []
    for value in facts.volume_history or []:
        parsed = _num(value)
        raw_volumes.append(parsed if parsed is not None and parsed > 0 else None)
    recent_period_count = max(5, len(raw_volumes) // 5)
    vol = [value for value in raw_volumes if value is not None]
    recent_vol = [
        value for value in _last_n(raw_volumes, recent_period_count)
        if value is not None
    ]

    margin = list(facts.margin_trading or [])[-margin_window:]
    rzye_series = [_num(row.get("rzye")) for row in margin]
    rzye_series = [
        value for value in rzye_series
        if value is not None and value >= 0
    ]

    margin_rise: Optional[float] = None
    if len(rzye_series) >= 2 and rzye_series[0] > 0:
        margin_rise = (rzye_series[-1] - rzye_series[0]) / rzye_series[0]

    # 数据可用性评估
    has_vol = len(vol) >= 10 and len(recent_vol) >= 3
    has_margin = (
        len(rzye_series) >= 2
        and rzye_series[0] > 0
        and margin_rise is not None
    )
    if not has_vol and not has_margin:
        return TopRiskStepResult(
            step_id="crowding",
            label="拥挤度",
            direction="NEUTRAL",
            weight=weight,
            step_risk=0.0,
            confidence=0.0,
            skipped=True,
            skip_reason="量能与融资余额均不足",
            details={
                "volume_points": len(vol),
                "recent_volume_points": len(recent_vol),
                "margin_points": len(rzye_series),
            },
        )

    reasons: list[str] = []
    turnover_z: Optional[float] = None

    # 近期均量 z 分数（相对全样本基线）
    if has_vol:
        m = _mean(vol)
        s = _std(vol)
        recent_avg = _mean(recent_vol)
        turnover_z = _z(recent_avg, m, s)
        if turnover_z is not None and turnover_z >= z_threshold:
            reasons.append(
                f"近月均量相对历史基线放大（z={turnover_z:+.2f}）"
            )

    # 融资余额相对窗口初值涨幅
    if has_margin and margin_rise is not None:
        if margin_rise >= margin_rise_threshold:
            reasons.append(
                f"融资余额较 {margin_window} 日初值上涨 {margin_rise*100:.0f}%（杠杆资金快速涌入）"
            )
        elif margin_rise <= -margin_rise_threshold:
            reasons.append(
                f"融资余额较窗口初值下降 {abs(margin_rise)*100:.0f}%（杠杆去化）"
            )

    # 风险分构建
    step_risk = 0.0
    direction = "NEUTRAL"
    z_hit = turnover_z is not None and turnover_z >= z_threshold
    margin_hit = margin_rise is not None and margin_rise >= margin_rise_threshold
    margin_off = margin_rise is not None and margin_rise <= -margin_rise_threshold

    if z_hit and margin_hit:
        step_risk = 0.85
        direction = "RISK"
        reasons.append("量能与杠杆资金共振，拥挤度显著偏高")
    elif z_hit or margin_hit:
        step_risk = 0.45
        direction = "RISK"
    elif margin_off:
        step_risk = -0.2
        direction = "SAFE"
        reasons.append("融资余额回落，拥挤风险缓和")

    if not reasons:
        reasons.append("量能与融资余额未见显著拥挤信号")

    # 置信度：依赖字段越全越高
    conf = 50
    if has_vol:
        conf += 20
    if has_margin:
        conf += 20
    conf = min(90, conf)

    return TopRiskStepResult(
        step_id="crowding",
        label="拥挤度",
        direction=direction,  # type: ignore[arg-type]
        weight=weight,
        step_risk=step_risk,
        confidence=float(conf),
        skipped=False,
        reasons=reasons,
        details={
            "turnover_z": round(turnover_z, 3) if turnover_z is not None else None,
            "margin_rise_ratio": round(margin_rise, 4) if margin_rise is not None else None,
            "volume_points": len(vol),
            "recent_volume_points": len(recent_vol),
            "margin_points": len(rzye_series),
        },
    )


# ---------------------------------------------------------------------------
# 3. 涨幅耗竭（区间涨幅大 + 量能萎缩 / 价格滞涨）
# ---------------------------------------------------------------------------
@register("runup_exhaustion")
def runup_exhaustion(facts: TopRiskFact, params: dict) -> TopRiskStepResult:
    weight = float(params.get("weight", 1.0))
    window = max(1, int(params.get("window", 60)))
    runup_strong = float(params.get("runup_strong", 0.5))
    runup_medium = float(params.get("runup_medium", 0.25))
    vol_shrink_ratio = float(params.get("vol_shrink_ratio", 0.7))

    # 标准化 price/volume 已按索引对齐：先截取同一尾部窗口，再过滤。
    price_window = list(facts.price_history or [])[-window:]
    volume_window = list(facts.volume_history or [])[-window:]
    prices = [p for p in price_window if p is not None and p > 0]
    vols: list[Optional[float]] = []
    for value in volume_window:
        parsed = _num(value)
        vols.append(parsed if parsed is not None and parsed > 0 else None)

    if len(prices) < max(10, window // 2):
        return TopRiskStepResult(
            step_id="runup_exhaustion",
            label="涨幅耗竭",
            direction="NEUTRAL",
            weight=weight,
            step_risk=0.0,
            confidence=0.0,
            skipped=True,
            skip_reason="价格序列过短，无法评估涨幅耗竭",
        )

    first = prices[0]
    last = prices[-1]
    runup = (last - first) / first if first else 0.0
    peak = max(prices)
    peak_off = (last - peak) / peak if peak else 0.0  # <=0 表示距高点回撤

    reasons: list[str] = []
    # 区间涨幅基础风险
    step_risk = 0.0
    if runup >= runup_strong:
        step_risk = 0.5
        reasons.append(f"区间涨幅 {runup*100:.0f}%（强拉升）")
    elif runup >= runup_medium:
        step_risk = 0.3
        reasons.append(f"区间涨幅 {runup*100:.0f}%（中等拉升）")
    else:
        reasons.append(f"区间涨幅 {runup*100:.0f}%（温和）")

    # 耗竭信号：末期量能萎缩 + 价格滞后于高点
    exhaustion = False
    vol_ratio = None
    if len(vols) >= 10:
        third = max(3, len(vols) // 3)
        early_vol = _mean(_first_n(vols, third))
        late_vol = _mean(_last_n(vols, third))
        vol_ratio = (late_vol / early_vol) if early_vol else None
        if vol_ratio is not None and vol_ratio <= vol_shrink_ratio and peak_off <= -0.03:
            exhaustion = True
            reasons.append(
                f"量能较早期萎缩 { (1-vol_ratio)*100:.0f}% 且价格距区间高点回撤 {abs(peak_off)*100:.0f}%，呈现冲顶乏力"
            )

    if exhaustion:
        step_risk = min(1.0, step_risk + 0.35)
        if step_risk > 0:
            reasons.append("涨幅耗竭特征明显，顶部风险上升")

    direction = "RISK" if step_risk > 0.05 else "NEUTRAL"

    conf = 80 if len(prices) >= window else 60

    return TopRiskStepResult(
        step_id="runup_exhaustion",
        label="涨幅耗竭",
        direction=direction,  # type: ignore[arg-type]
        weight=weight,
        step_risk=step_risk,
        confidence=float(conf),
        skipped=False,
        reasons=reasons,
        details={
            "runup_ratio": round(runup, 4),
            "peak_off_ratio": round(peak_off, 4),
            "late_early_vol_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
            "price_points": len(prices),
        },
    )


# ---------------------------------------------------------------------------
# 4. 利好兑现（Phase 1：events 缺失 → skipped）
# ---------------------------------------------------------------------------
@register("catalyst_priced_in")
def catalyst_priced_in(facts: TopRiskFact, params: dict) -> TopRiskStepResult:
    required = bool(params.get("events_required", True))
    if facts.events is None:
        return TopRiskStepResult(
            step_id="catalyst_priced_in",
            label="利好兑现",
            direction="NEUTRAL",
            weight=float(params.get("weight", 1.0)),
            step_risk=0.0,
            confidence=0.0,
            skipped=True,
            skip_reason="events 缺失（Phase1 无可靠事件来源）",
        )
    # 若未来接入事件：重大利好已公告且价格已充分反映 → 利好兑现 RISK。
    if required:
        return TopRiskStepResult(
            step_id="catalyst_priced_in",
            label="利好兑现",
            direction="NEUTRAL",
            weight=float(params.get("weight", 1.0)),
            step_risk=0.0,
            confidence=0.0,
            skipped=True,
            skip_reason="events 存在但语义未定义（保留跳过）",
        )
    return TopRiskStepResult(
        step_id="catalyst_priced_in",
        label="利好兑现",
        direction="NEUTRAL",
        weight=float(params.get("weight", 1.0)),
        step_risk=0.0,
        confidence=0.0,
        skipped=True,
        skip_reason="未启用",
    )


# ---------------------------------------------------------------------------
# 5. 估值硬顶（PE-TTM / PB 历史分位）
# ---------------------------------------------------------------------------
@register("valuation_cap")
def valuation_cap(facts: TopRiskFact, params: dict) -> TopRiskStepResult:
    weight = float(params.get("weight", 1.0))
    pe_high = float(params.get("pe_percentile_high", 90.0))
    pb_high = float(params.get("pb_percentile_high", 90.0))

    metrics = facts.valuation or {}
    pe = metrics.get("pe_ttm") or {}
    pb = metrics.get("pb") or {}

    pe_pct = _num(pe.get("percentile"))
    pb_pct = _num(pb.get("percentile"))

    if pe_pct is None and pb_pct is None:
        return TopRiskStepResult(
            step_id="valuation_cap",
            label="估值硬顶",
            direction="NEUTRAL",
            weight=weight,
            step_risk=0.0,
            confidence=0.0,
            skipped=True,
            skip_reason="估值分位数据缺失",
        )

    reasons: list[str] = []
    hits = 0
    if pe_pct is not None and pe_pct >= pe_high:
        hits += 1
        reasons.append(f"PE-TTM 处历史 {pe_pct:.0f}% 分位（接近估值硬顶）")
    if pb_pct is not None and pb_pct >= pb_high:
        hits += 1
        reasons.append(f"PB 处历史 {pb_pct:.0f}% 分位（接近估值硬顶）")

    if hits == 0:
        # 估值不贵：若两者都明显偏低，给轻微安全信号
        low = (pe_pct is not None and pe_pct < 50) or (pb_pct is not None and pb_pct < 50)
        direction = "SAFE" if low else "NEUTRAL"
        step_risk = -0.15 if low else 0.0
        if low:
            reasons.append("估值分位偏低，不构成顶部风险")
        else:
            reasons.append("估值分位处于中性区间")
    else:
        direction = "RISK"
        step_risk = 0.7 if hits == 1 else 0.9

    conf = 70
    if pe_pct is not None:
        conf += 10
    if pb_pct is not None:
        conf += 10
    conf = min(90, conf)

    return TopRiskStepResult(
        step_id="valuation_cap",
        label="估值硬顶",
        direction=direction,  # type: ignore[arg-type]
        weight=weight,
        step_risk=step_risk,
        confidence=float(conf),
        skipped=False,
        reasons=reasons,
        details={
            "pe_percentile": round(pe_pct, 1) if pe_pct is not None else None,
            "pb_percentile": round(pb_pct, 1) if pb_pct is not None else None,
        },
    )
