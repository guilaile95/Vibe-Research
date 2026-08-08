"""Market Regime 派生状态层 v0.1 —— 确定性规则，不调用 AI，不新增数据源。

输入复用 ``market.py`` 已有确定性事实：
- ``market.get_market_breadth()``：广度 + 总成交额（normal/partial/unavailable 信封）
- ``market.get_short_term_emotion()``：涨停/跌停/炸板/封板等短线情绪

本模块只做「派生状态」，不抓取任何新数据；同一输入永远产生同一输出。

时间语义（P1 修正后）：
- ``fetched_at`` 只是 retrieval/fetch 时间，**不**用于判断行情新鲜度，也不作为 data_cutoff；
- 行情新鲜度只以可靠的 source ``data_time`` 为准：缺失 / 不可解析 / 在未来 → freshness
  UNKNOWN（fail closed：``is_stale=True`` + ``DATA_FRESHNESS_UNKNOWN`` + Confidence 降级），
  绝不声明 fresh；
- ``data_cutoff`` 只能来自可靠 ``data_time``，否则为 ``None``；
- top-level ``trade_date`` 需要多来源日期一致才确认（当前 breadth.trade_date 恒为 None，
  因此生产环境下 trade_date 保持 None，不伪造统一日期）；
- 时间对齐（P1-2）：breadth 有效交易日（优先 ``breadth.trade_date``，缺失时用可靠
  ``data_time`` 的日期部分，**禁止**用 ``fetched_at`` 推导）与 ``emotion.date`` 必须一致，
  ``temporal_alignment`` ∈ ALIGNED / CONFLICT / UNKNOWN；非 ALIGNED 时 speculation /
  emotion 状态 fail-closed 置 UNKNOWN，不得作为当前交易日事实参与方向判断，
  raw 值保留供审计展示。

输出统一信封（v0.1）：
- market_regime ∈ RISK_ON / NEUTRAL / RISK_OFF / STRESSED / UNKNOWN
- risk_appetite ∈ HIGH / MEDIUM / LOW / UNKNOWN
- confidence ∈ HIGH / MEDIUM / LOW
- is_stale / trade_date / temporal_alignment / data_cutoff / fetched_at / components / reasons

Market Regime 不是 BUY/SELL 信号；不因为环境好产生买入建议，
也不因为环境差产生卖出建议。Sector Regime 不在本层范围。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import market

BEIJING = timezone(timedelta(hours=8))

# ---- v0.1 有限枚举 ----
REGIMES = ("RISK_ON", "NEUTRAL", "RISK_OFF", "STRESSED", "UNKNOWN")
APPETITES = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")
CONFIDENCES = ("HIGH", "MEDIUM", "LOW")

# ---- 组件派生状态 ----
_STATE_STRONG = "STRONG"
_STATE_NEUTRAL = "NEUTRAL"
_STATE_WEAK = "WEAK"
_STATE_UNKNOWN = "UNKNOWN"
_STATE_STRESSED = "STRESSED"
_STATE_NORMAL = "NORMAL"

# ---- 确定性阈值（PROVISIONAL_HEURISTIC_V0_1：v0.1 固定常量，校准属后续任务）----
_STALE_AFTER_SECONDS = 4 * 3600      # data_time 距今超过 4 小时 → stale（PROVISIONAL_HEURISTIC_V0_1）
_LIQUIDITY_STRONG_MIN = 1.2e12       # 总成交额 >= 1.2 万亿 → 流动性强（PROVISIONAL_HEURISTIC_V0_1）
_LIQUIDITY_WEAK_MAX = 0.8e12         # 总成交额 < 8000 亿 → 流动性弱（PROVISIONAL_HEURISTIC_V0_1）
_STRESS_DT_MIN = 30                  # 跌停家数 >= 30 → 情绪承压（PROVISIONAL_HEURISTIC_V0_1）
_STRESS_BREAK_RATE = 0.50            # 炸板率 >= 50% → 情绪承压（PROVISIONAL_HEURISTIC_V0_1）

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S")
_DATE_FORMAT = "%Y-%m-%d"

# ---- reason code → 中文展示文本（全部确定性，可审计）----
_REASON_MESSAGES = {
    "DATA_UNAVAILABLE": "核心市场数据不可用，无法判断市场状态",
    "BREADTH_WEAK": "市场宽度偏弱（上涨占比低于 40%）",
    "BREADTH_NEUTRAL": "市场宽度中性（上涨占比 40%~60%）",
    "BREADTH_STRONG": "市场宽度偏强（上涨占比高于 60%）",
    "BREADTH_UNAVAILABLE": "市场宽度数据不可用",
    "RISK_APPETITE_LOW": "风险偏好低（涨停家数少于 30）",
    "RISK_APPETITE_MEDIUM": "风险偏好中性（涨停家数 30~59）",
    "RISK_APPETITE_HIGH": "风险偏好高（涨停家数不低于 60）",
    "RISK_APPETITE_UNAVAILABLE": "风险偏好数据不可用",
    "LIQUIDITY_STRONG": "流动性强（总成交额不低于 1.2 万亿）",
    "LIQUIDITY_NEUTRAL": "流动性中性（总成交额 8000 亿~1.2 万亿）",
    "LIQUIDITY_WEAK": "流动性弱（总成交额低于 8000 亿）",
    "LIQUIDITY_UNAVAILABLE": "流动性数据不可用",
    "EMOTION_NORMAL": "短线情绪正常",
    "EMOTION_STRESSED": "短线情绪承压（跌停家数不低于 30 或炸板率不低于 50%）",
    "EMOTION_UNAVAILABLE": "短线情绪数据不可用",
    "SIGNAL_CONFLICT": "市场信号相互冲突，不强行判断方向",
    "SOURCE_DATE_CONFLICT": "情绪数据与广度数据交易日期不一致，情绪信号不作为当前交易日事实",
    "TEMPORAL_ALIGNMENT_UNKNOWN": "无法确认情绪与广度数据属于同一交易日，情绪信号不作为当前事实",
    "DATA_PARTIAL": "部分数据缺失，判断置信度下降",
    "DATA_FRESHNESS_UNKNOWN": "无可靠行情数据时间，无法确认新鲜度",
    "DATA_STALE": "行情数据已过期（数据时间超过 4 小时）",
    "TRADE_DATE_UNKNOWN": "无法确认统一交易日期",
}


def _reason(code: str) -> dict:
    return {"code": code, "message": _REASON_MESSAGES[code]}


def _is_number(v) -> bool:
    """数值有效性：int/float、非 bool、非 NaN。"""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    return v == v  # noqa: PLR0124 — NaN != NaN


def _breadth_state(up_ratio) -> str:
    """广度状态：复用 market._breadth_label 的同一分档边界（冰点/偏弱/中性/偏强/普涨）。"""
    label = market._breadth_label(up_ratio)
    if label is None:
        return _STATE_UNKNOWN
    if label in ("冰点", "偏弱"):
        return _STATE_WEAK
    if label == "中性":
        return _STATE_NEUTRAL
    return _STATE_STRONG  # 偏强 / 普涨


def _appetite_state(zt_count) -> str:
    """风险偏好（投机代理）：复用 market._speculation_label 的同一分档边界（冰点/普通/活跃/亢奋）。"""
    label = market._speculation_label(zt_count)
    if label is None:
        return _STATE_UNKNOWN
    if label in ("亢奋", "活跃"):
        return _STATE_STRONG
    if label == "普通":
        return _STATE_NEUTRAL
    return _STATE_WEAK  # 冰点


def _liquidity_state(total_amount) -> str:
    """流动性状态（总成交额绝对分档）。"""
    if not _is_number(total_amount):
        return _STATE_UNKNOWN
    amount = float(total_amount)
    if amount >= _LIQUIDITY_STRONG_MIN:
        return _STATE_STRONG
    if amount < _LIQUIDITY_WEAK_MAX:
        return _STATE_WEAK
    return _STATE_NEUTRAL


def _emotion_state(emotion: dict) -> str:
    """情绪压力状态（P1-1 契约）：

    - 任一已知指标达到 stress 阈值（dt_count >= 30 或 break_rate >= 0.50）
      → STRESSED（另一字段缺失不影响，已有足够确定性证据）；
    - 仅当 dt_count 与 break_rate 均有效且均未达阈值 → NORMAL；
    - 其余（无越阈信号但任一缺失）→ UNKNOWN：部分数据缺失不得伪装成 NORMAL。
    """
    dt = emotion.get("dt_count")
    break_rate = emotion.get("break_rate")
    dt_valid = _is_number(dt)
    break_valid = _is_number(break_rate)
    if (dt_valid and float(dt) >= _STRESS_DT_MIN) or (
        break_valid and float(break_rate) >= _STRESS_BREAK_RATE
    ):
        return _STATE_STRESSED
    if dt_valid and break_valid:
        return _STATE_NORMAL
    return _STATE_UNKNOWN


def _parse_timestamp(raw) -> datetime | None:
    """解析行情时间戳；不可解析 → None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=BEIJING)
        except ValueError:
            continue
    return None


def _valid_date_str(raw) -> str | None:
    """仅接受合法 YYYY-MM-DD；缺失 / 非字符串 / 不可解析 → None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        datetime.strptime(text, _DATE_FORMAT)
    except ValueError:
        return None
    return text


def _breadth_effective_date(breadth: dict, reliable_data_time: datetime | None) -> str | None:
    """广度有效交易日：优先 ``breadth.trade_date``；缺失时用可靠 ``data_time`` 的日期部分。

    禁止用 ``fetched_at`` 推导交易日期。``reliable_data_time`` 为已解析且不晚于 now 的
    行情事实时间（不可靠 / 缺失 → None）。
    """
    trade_date = _valid_date_str(breadth.get("trade_date"))
    if trade_date is not None:
        return trade_date
    if reliable_data_time is not None:
        return reliable_data_time.strftime(_DATE_FORMAT)
    return None


def _temporal_alignment(breadth_effective_date: str | None, emotion_date: str | None) -> str:
    """最小时间对齐契约：两者都存在且相等 → ALIGNED；都存在但不同 → CONFLICT；任一无法确认 → UNKNOWN。"""
    if breadth_effective_date is not None and emotion_date is not None:
        return "ALIGNED" if breadth_effective_date == emotion_date else "CONFLICT"
    return "UNKNOWN"


def _confirmed_trade_date(breadth_trade_date, emotion_date) -> str | None:
    """统一 trade_date 只在多来源日期一致时确认；任一缺失/冲突 → None（不伪造）。"""
    b = _valid_date_str(breadth_trade_date)
    e = _valid_date_str(emotion_date)
    if b is not None and e is not None and b == e:
        return b
    return None


def derive_market_regime(breadth: dict, emotion: dict, *, now: datetime | None = None) -> dict:
    """由市场事实确定性推导 Market Regime（纯函数，不联网、不读缓存）。

    ``breadth`` 为 ``market.get_market_breadth()`` 的信封；``emotion`` 为
    ``market.get_short_term_emotion()`` 的结果（允许 ``{}``）。
    同一输入 → 同一输出；核心数据不可用 → UNKNOWN；无可靠行情时间 → 不声明 fresh。
    """
    if now is None:
        now = datetime.now(BEIJING)

    if not isinstance(breadth, dict):
        breadth = {}
    if not isinstance(emotion, dict):
        emotion = {}

    b_status = breadth.get("status")
    b_data = breadth.get("data") if isinstance(breadth.get("data"), dict) else None
    b_partial = b_status == "partial"
    up_ratio = b_data.get("up_ratio") if b_data else None
    total_amount = b_data.get("total_amount") if b_data else None
    amount_valid = b_data.get("amount_valid_count") if b_data else None

    zt_count = emotion.get("zt_count") if emotion else None
    dt_count = emotion.get("dt_count") if emotion else None
    break_rate = emotion.get("break_rate") if emotion else None
    seal_rate = emotion.get("seal_rate") if emotion else None
    emotion_date = emotion.get("date") if emotion else None

    # ---- 核心可用性：广度（含上涨占比）不可用 → 无法形成任何方向 ----
    core_available = (
        b_status in ("normal", "partial")
        and b_data is not None
        and _is_number(up_ratio)
    )

    breadth_state = _breadth_state(up_ratio if core_available else None)
    appetite_state = _appetite_state(zt_count)
    liquidity_state = _liquidity_state(total_amount)
    emo_state = _emotion_state(emotion)

    # ---- 新鲜度：只以可靠 source data_time 为准（fetched_at 仅作 retrieval 时间）----
    fetched_at_raw = breadth.get("fetched_at")
    fetched_at = fetched_at_raw.strip() if isinstance(fetched_at_raw, str) and fetched_at_raw.strip() else None

    data_time_raw = breadth.get("data_time")
    data_time_dt = _parse_timestamp(data_time_raw)
    # 可靠：可解析、不晚于 now（未来时间戳视为不可靠，fail closed）
    freshness_known = data_time_dt is not None and data_time_dt <= now
    data_cutoff = data_time_raw.strip() if freshness_known else None

    is_stale = True  # 无可靠行情时间 → fail closed：不得声明 fresh
    if freshness_known:
        is_stale = (now - data_time_dt).total_seconds() > _STALE_AFTER_SECONDS
    fresh = not is_stale

    # ---- 时间对齐（P1-2）：breadth 有效交易日 vs emotion.date ----
    # breadth 有效交易日优先 trade_date，缺失时用可靠 data_time 的日期部分（禁止 fetched_at）；
    # emotion.date 仅接受合法 YYYY-MM-DD。
    reliable_data_time = data_time_dt if freshness_known else None
    breadth_effective_date = _breadth_effective_date(breadth, reliable_data_time)
    emotion_date_valid = _valid_date_str(emotion_date)
    alignment = _temporal_alignment(breadth_effective_date, emotion_date_valid)

    # ---- fail-closed：时间对齐未确认时，emotion-derived 状态不得作为当前交易日事实 ----
    # 跨日拼接（CONFLICT）或无法确认同一交易日（UNKNOWN）→ speculation / emotion 置
    # UNKNOWN（raw 值保留供审计），不参与当前 regime 方向与冲突裁决。
    if alignment != "ALIGNED":
        appetite_state = _STATE_UNKNOWN
        emo_state = _STATE_UNKNOWN

    # ---- 统一 trade_date：多来源一致才确认 ----
    trade_date = _confirmed_trade_date(breadth.get("trade_date"), emotion_date)

    # ---- 缺失统计（影响 Confidence；不因缺失自动转 RISK_OFF）----
    missing_count = sum(
        state == _STATE_UNKNOWN
        for state in (appetite_state, liquidity_state, emo_state)
    )

    # ---- 强冲突：不强行给激进状态 ----
    # - 宽度/偏好直接对立；
    # - EMOTION_STRESSED 与「明显积极市场状态」（宽度强 + 偏好高 + 流动性不弱）对立。
    conflict = (
        (breadth_state == _STATE_STRONG and appetite_state == _STATE_WEAK)
        or (breadth_state == _STATE_WEAK and appetite_state == _STATE_STRONG)
        or (
            emo_state == _STATE_STRESSED
            and breadth_state == _STATE_STRONG
            and appetite_state == _STATE_STRONG
            and liquidity_state != _STATE_WEAK
        )
    )

    # ---- 规则（优先级从上到下，首个命中生效）----
    if not core_available:
        regime = "UNKNOWN"
    elif breadth_state == _STATE_WEAK and emo_state == _STATE_STRESSED:
        regime = "STRESSED"
    elif conflict:
        regime = "NEUTRAL"
    elif breadth_state == _STATE_WEAK and (appetite_state == _STATE_WEAK or liquidity_state == _STATE_WEAK):
        regime = "RISK_OFF"
    elif appetite_state == _STATE_WEAK and liquidity_state == _STATE_WEAK:
        regime = "RISK_OFF"
    elif breadth_state == _STATE_STRONG and appetite_state == _STATE_STRONG and liquidity_state != _STATE_WEAK:
        regime = "RISK_ON"
    else:
        regime = "NEUTRAL"

    # ---- Confidence（累计降级，不制造结论）----
    confidence = "HIGH"
    if regime == "UNKNOWN":
        confidence = "LOW"
    else:
        if b_partial or missing_count >= 1 or not freshness_known:
            confidence = "MEDIUM"
        if missing_count >= 2:
            confidence = "LOW"
        if conflict:
            confidence = "LOW"
        if is_stale and confidence == "HIGH":
            confidence = "MEDIUM"

    # ---- reasons（固定顺序，可审计）----
    reasons: list[dict] = []
    if not core_available:
        reasons.append(_reason("DATA_UNAVAILABLE"))
    reasons.append(_reason(_breadth_reason_code(breadth_state)))
    reasons.append(_reason(_appetite_reason_code(appetite_state)))
    reasons.append(_reason(_liquidity_reason_code(liquidity_state)))
    reasons.append(_reason(_emotion_reason_code(emo_state)))
    if alignment == "CONFLICT":
        reasons.append(_reason("SOURCE_DATE_CONFLICT"))
    elif alignment == "UNKNOWN":
        reasons.append(_reason("TEMPORAL_ALIGNMENT_UNKNOWN"))
    if conflict:
        reasons.append(_reason("SIGNAL_CONFLICT"))
    if core_available and (b_partial or missing_count >= 1):
        reasons.append(_reason("DATA_PARTIAL"))
    if not freshness_known:
        reasons.append(_reason("DATA_FRESHNESS_UNKNOWN"))
    elif is_stale:
        reasons.append(_reason("DATA_STALE"))
    if trade_date is None:
        reasons.append(_reason("TRADE_DATE_UNKNOWN"))

    # ---- 组件载荷 ----
    raw_breadth = {}
    if b_data is not None:
        raw_breadth = {
            "status": b_status,
            "up_ratio": up_ratio,
            "up_count": b_data.get("up_count"),
            "down_count": b_data.get("down_count"),
            "valid_count": b_data.get("valid_count"),
            "trade_date": breadth.get("trade_date"),
            "data_time": data_time_raw,
        }
    raw_speculation = {
        "zt_count": zt_count,
        "dt_count": dt_count,
        "break_rate": break_rate,
        "seal_rate": seal_rate,
    }
    raw_liquidity = {
        "total_amount": total_amount,
        "amount_valid_count": amount_valid,
    }
    raw_emotion = {
        "dt_count": dt_count,
        "break_rate": break_rate,
        "seal_rate": seal_rate,
        "promotion_rate": emotion.get("promotion_rate") if emotion else None,
        "max_boards": emotion.get("max_boards") if emotion else None,
    }

    components = {
        "breadth": {
            "state": breadth_state,
            "available": core_available,
            "fresh": fresh,
            "raw": raw_breadth,
        },
        "speculation": {
            "state": appetite_state,
            "available": appetite_state != _STATE_UNKNOWN,
            "fresh": fresh and alignment == "ALIGNED",
            "raw": raw_speculation,
        },
        "liquidity": {
            "state": liquidity_state,
            "available": liquidity_state != _STATE_UNKNOWN,
            "fresh": fresh,
            "raw": raw_liquidity,
        },
        "emotion": {
            "state": emo_state,
            "available": emo_state != _STATE_UNKNOWN,
            "fresh": fresh and alignment == "ALIGNED",
            "raw": raw_emotion,
        },
    }

    return {
        "market_regime": regime,
        "risk_appetite": _appetite_display(appetite_state),
        "confidence": confidence,
        "is_stale": is_stale,
        "trade_date": trade_date,
        "temporal_alignment": alignment,
        "data_cutoff": data_cutoff,
        "fetched_at": fetched_at,
        "components": components,
        "reasons": reasons,
    }


def _breadth_reason_code(state: str) -> str:
    if state == _STATE_WEAK:
        return "BREADTH_WEAK"
    if state == _STATE_STRONG:
        return "BREADTH_STRONG"
    if state == _STATE_NEUTRAL:
        return "BREADTH_NEUTRAL"
    return "BREADTH_UNAVAILABLE"


def _appetite_reason_code(state: str) -> str:
    if state == _STATE_WEAK:
        return "RISK_APPETITE_LOW"
    if state == _STATE_STRONG:
        return "RISK_APPETITE_HIGH"
    if state == _STATE_NEUTRAL:
        return "RISK_APPETITE_MEDIUM"
    return "RISK_APPETITE_UNAVAILABLE"


def _liquidity_reason_code(state: str) -> str:
    if state == _STATE_STRONG:
        return "LIQUIDITY_STRONG"
    if state == _STATE_WEAK:
        return "LIQUIDITY_WEAK"
    if state == _STATE_NEUTRAL:
        return "LIQUIDITY_NEUTRAL"
    return "LIQUIDITY_UNAVAILABLE"


def _emotion_reason_code(state: str) -> str:
    if state == _STATE_STRESSED:
        return "EMOTION_STRESSED"
    if state == _STATE_NORMAL:
        return "EMOTION_NORMAL"
    return "EMOTION_UNAVAILABLE"


def _appetite_display(state: str) -> str:
    if state == _STATE_STRONG:
        return "HIGH"
    if state == _STATE_WEAK:
        return "LOW"
    if state == _STATE_NEUTRAL:
        return "MEDIUM"
    return "UNKNOWN"


def get_market_regime() -> dict:
    """实时入口：复用 market.py 事实（各自带 5 分钟共享缓存），再派生状态。

    广度信封从不抛异常（unavailable 兜底）；情绪池单独失败只丢情绪组件。
    """
    breadth = market.get_market_breadth()
    try:
        emotion = market.get_short_term_emotion()
    except Exception:  # noqa: BLE001 — 外部数据边界，情绪组件置为缺失
        emotion = {}
    return derive_market_regime(breadth, emotion)
