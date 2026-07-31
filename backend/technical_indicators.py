"""技术指标纯计算模块。

所有函数只接受内存数据（K 线 list[dict]），禁止网络访问。
计算第 i 个交易日的指标时，只用 klines[0..i] 的数据（无未来函数）。
缺失一律返回 null（None），NaN / Infinity 在输出前清洗为 None。
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timezone

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "technical-indicators-v0.1"
MAX_SERIES_POINTS = 60

# Public stable prefix for incomplete 20d high/low window (consumed by screener)
PRICE_RANGE_TRIGGER_UNAVAILABLE_PREFIX = "价格区间触发不可评估"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _clean_float(v) -> float | None:
    """把任意值转为 float；None / NaN / Infinity → None。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _parse_klines(raw: list[dict]) -> list[dict]:
    """清洗、确定性去重并按真实交易日升序标准化 K 线。"""
    if not raw:
        return []

    candidates: dict[str, list[tuple[tuple, dict]]] = {}

    for row in raw:
        if not row:
            continue

        dt_raw = row.get("datetime") or row.get("date")
        parsed = _parse_datetime_value(dt_raw)
        if parsed is None:
            continue

        close = _clean_float(row.get("close"))
        if close is None:
            continue

        high = _clean_float(row.get("high"))
        low = _clean_float(row.get("low"))
        volume = _clean_float(row.get("volume"))
        if volume is None:
            volume = _clean_float(row.get("vol"))

        date_str, timestamp = parsed
        normalized = {"date": date_str, "close": close, "high": high, "low": low, "volume": volume}
        completeness = sum(value is not None for value in (high, low, volume))
        canonical = tuple("" if value is None else f"{value:.12g}" for value in (close, high, low, volume))
        key = (close is not None, completeness, timestamp, canonical)
        candidates.setdefault(date_str, []).append((key, normalized))

    cleaned = [max(options, key=lambda item: item[0])[1] for options in candidates.values()]
    cleaned.sort(key=lambda row: row["date"])
    return cleaned


def _parse_datetime_value(value) -> tuple[str, datetime] | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(text), time.min)
            except ValueError:
                return None
    calendar_date = parsed.date().isoformat()
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return calendar_date, parsed


def _is_finite(v) -> bool:
    return v is not None and math.isfinite(v)


# ---------------------------------------------------------------------------
# 指标计算（全部返回 list，长度与输入对齐，无法计算的位置为 None）
# ---------------------------------------------------------------------------


def _sma(values: list[float | None], n: int) -> list[float | None]:
    """简单移动平均。第 i 位用 values[i-n+1..i]；不足 n 个有效值 → None。"""
    result: list[float | None] = []
    for i in range(len(values)):
        if i < n - 1:
            result.append(None)
            continue
        window = values[i - n + 1 : i + 1]
        valid = [v for v in window if v is not None]
        if len(valid) < n:
            result.append(None)
        else:
            result.append(sum(valid) / n)
    return result


def _ema(values: list[float | None], n: int) -> list[float | None]:
    """指数移动平均。k = 2/(N+1)。

    第一个有效值作为初始 EMA；后续递推。中间有 None 则跳过该日（保持前值）。
    """
    result: list[float | None] = []
    k = 2.0 / (n + 1)
    prev: float | None = None
    for v in values:
        if v is None:
            result.append(prev)
            continue
        if prev is None:
            prev = v
        else:
            prev = v * k + prev * (1 - k)
        result.append(prev)
    return result


def _macd(closes: list[float | None]) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD：DIF = EMA12 − EMA26；DEA = DIF 的 EMA9；Histogram = 2 × (DIF − DEA)。"""
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)

    dif = []
    for a, b in zip(ema12, ema26):
        if a is not None and b is not None:
            dif.append(a - b)
        else:
            dif.append(None)

    dea = _ema(dif, 9)

    histogram = []
    for d, m in zip(dif, dea):
        if d is not None and m is not None:
            histogram.append(2.0 * (d - m))
        else:
            histogram.append(None)

    return dif, dea, histogram


def _rsi(closes: list[float | None], n: int = 14) -> list[float | None]:
    """RSI（Wilder 平滑）。需要 n+1 个收盘价（n 个变化）。"""
    result: list[float | None] = [None] * len(closes)
    if len(closes) < n + 1:
        return result

    # 计算价格变化
    changes: list[float | None] = [None]  # 第一个无变化
    for i in range(1, len(closes)):
        if closes[i] is not None and closes[i - 1] is not None:
            changes.append(closes[i] - closes[i - 1])
        else:
            changes.append(None)

    # 初始 avg_gain / avg_loss：前 n 个有效变化的均值
    first_valid = []
    for c in changes[1:]:
        if c is not None:
            first_valid.append(c)
        if len(first_valid) == n:
            break

    if len(first_valid) < n:
        return result

    gains = [c if c > 0 else 0.0 for c in first_valid]
    losses = [-c if c < 0 else 0.0 for c in first_valid]
    avg_gain = sum(gains) / n
    avg_loss = sum(losses) / n

    # RSI 在第 n 个变化处（索引 n）产出第一个值
    if avg_loss == 0:
        result[n] = 50.0 if avg_gain == 0 else 100.0
    else:
        rs = avg_gain / avg_loss
        result[n] = 100.0 - 100.0 / (1.0 + rs)

    # 后续递推
    for i in range(n + 1, len(closes)):
        c = changes[i]
        if c is None:
            result[i] = result[i - 1]
            continue
        gain = c if c > 0 else 0.0
        loss = -c if c < 0 else 0.0
        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
        if avg_loss == 0:
            result[i] = 50.0 if avg_gain == 0 else 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - 100.0 / (1.0 + rs)

    return result


def _bollinger(
    closes: list[float | None], n: int = 20, k: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """布林带：middle = SMA20；upper = middle + 2σ；lower = middle − 2σ。"""
    middle = _sma(closes, n)
    upper: list[float | None] = []
    lower: list[float | None] = []

    for i in range(len(closes)):
        if i < n - 1 or middle[i] is None:
            upper.append(None)
            lower.append(None)
            continue
        window = [c for c in closes[i - n + 1 : i + 1] if c is not None]
        if len(window) < n:
            upper.append(None)
            lower.append(None)
            continue
        m = middle[i]
        variance = sum((c - m) ** 2 for c in window) / n
        sigma = math.sqrt(variance)
        upper.append(m + k * sigma)
        lower.append(m - k * sigma)

    return upper, middle, lower


def _volume_ratio(
    volumes: list[float | None], short_n: int = 5, long_n: int = 20
) -> list[float | None]:
    """5/20 日均量比 = SMA(vol, 5) / SMA(vol, 20)。"""
    sma_short = _sma(volumes, short_n)
    sma_long = _sma(volumes, long_n)

    result: list[float | None] = []
    for a, b in zip(sma_short, sma_long):
        if a is not None and b is not None and b > 0:
            result.append(a / b)
        else:
            result.append(None)
    return result


# ---------------------------------------------------------------------------
# 触发检测
# ---------------------------------------------------------------------------


def _detect_triggers(
    klines: list[dict],
    sma20: list[float | None],
    sma60: list[float | None],
    volume_ratio: list[float | None],
    idx: int,
) -> list[dict]:
    """检测最新交易日（idx）的触发。返回触发列表。"""
    triggers: list[dict] = []
    if idx < 0 or idx >= len(klines):
        return triggers

    close = klines[idx].get("close")
    if close is None:
        return triggers

    # 1. 收盘价突破过去 20 日高点（不含当前日）
    if idx >= 20:
        historical_highs = [
            klines[j]["high"]
            for j in range(idx - 20, idx)
            if klines[j].get("high") is not None
        ]
        if len(historical_highs) == 20 and close > max(historical_highs):
            triggers.append(
                {
                    "type": "close_above_20d_high",
                    "message": f"收盘价突破过去 20 个交易日最高价 {max(historical_highs):.2f}",
                    "value": close,
                }
            )

    # 2. 收盘价跌破过去 20 日低点（不含当前日）
    if idx >= 20:
        historical_lows = [
            klines[j]["low"]
            for j in range(idx - 20, idx)
            if klines[j].get("low") is not None
        ]
        if len(historical_lows) == 20 and close < min(historical_lows):
            triggers.append(
                {
                    "type": "close_below_20d_low",
                    "message": f"收盘价跌破过去 20 个交易日最低价 {min(historical_lows):.2f}",
                    "value": close,
                }
            )

    # 3. 均线金叉 / 死叉（比较当前与前一个交易日）
    if idx >= 1:
        cur_20 = sma20[idx] if idx < len(sma20) else None
        cur_60 = sma60[idx] if idx < len(sma60) else None
        prev_20 = sma20[idx - 1] if (idx - 1) < len(sma20) else None
        prev_60 = sma60[idx - 1] if (idx - 1) < len(sma60) else None

        if all(v is not None for v in (cur_20, cur_60, prev_20, prev_60)):
            if cur_20 > cur_60 and prev_20 <= prev_60:
                triggers.append(
                    {
                        "type": "sma_golden_cross",
                        "message": "检测到 SMA20 上穿 SMA60 均线",
                        "value": None,
                    }
                )
            elif cur_20 < cur_60 and prev_20 >= prev_60:
                triggers.append(
                    {
                        "type": "sma_death_cross",
                        "message": "检测到 SMA20 下穿 SMA60 均线",
                        "value": None,
                    }
                )

    # 4. 5/20 日均量比触发
    vr = volume_ratio[idx] if idx < len(volume_ratio) else None
    if vr is not None and vr > 2.0:
        triggers.append(
            {
                "type": "volume_spike",
                "message": f"5 日平均成交量超过 20 日平均成交量的 2 倍（5/20 日均量比 {vr:.2f}）",
                "value": vr,
            }
        )

    return triggers


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def compute_indicators(
    klines: list[dict],
    *,
    code: str,
    period: str,
    days: int,
    trade_date: str | None = None,
    fetched_at: str,
) -> dict:
    """入口：原始 K 线 → 清洗 → 逐指标计算 → 触发检测 → envelope。永不抛异常。"""
    try:
        return _compute_indicators_inner(klines, code=code, period=period, days=days, trade_date=trade_date, fetched_at=fetched_at)
    except Exception:
        # 整体计算失败 → unavailable
        return {
            "schema_version": SCHEMA_VERSION,
            "code": code,
            "period": period,
            "trade_date": None,
            "fetched_at": fetched_at,
            "status": "unavailable",
            "warnings": [],
            "limitations": ["指标计算失败"],
            "latest": _empty_latest(),
            "triggers": [],
            "series": [],
        }


def _empty_latest() -> dict:
    return {
        "close": None,
        "sma5": None,
        "sma10": None,
        "sma20": None,
        "sma60": None,
        "ema12": None,
        "ema26": None,
        "macd_dif": None,
        "macd_dea": None,
        "macd_histogram": None,
        "rsi14": None,
        "bollinger_upper": None,
        "bollinger_middle": None,
        "bollinger_lower": None,
        "volume_ratio_5_20": None,
    }


def _compute_indicators_inner(
    raw_klines: list[dict],
    *,
    code: str,
    period: str,
    days: int,
    trade_date: str | None,
    fetched_at: str,
) -> dict:
    klines = _parse_klines(raw_klines)
    normalized_trade_date = klines[-1]["date"] if klines else None

    if not klines:
        return {
            "schema_version": SCHEMA_VERSION,
            "code": code,
            "period": period,
            "trade_date": normalized_trade_date,
            "fetched_at": fetched_at,
            "status": "unavailable",
            "warnings": [],
            "limitations": ["无有效 K 线数据"],
            "latest": _empty_latest(),
            "triggers": [],
            "series": [],
        }

    closes = [k["close"] for k in klines]
    volumes = [k.get("volume") for k in klines]

    # 指标计算
    sma5 = _sma(closes, 5)
    sma10 = _sma(closes, 10)
    sma20 = _sma(closes, 20)
    sma60 = _sma(closes, 60)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_dif, macd_dea, macd_histogram = _macd(closes)
    rsi14 = _rsi(closes, 14)
    bollinger_upper, bollinger_middle, bollinger_lower = _bollinger(closes, 20, 2.0)
    vr_5_20 = _volume_ratio(volumes, 5, 20)

    # 最新日
    idx = len(klines) - 1

    # status 判定
    limitations: list[str] = []
    has_sma60 = sma60[idx] is not None
    has_macd = macd_dif[idx] is not None
    has_rsi = rsi14[idx] is not None
    has_bollinger = bollinger_middle[idx] is not None

    has_volume_ratio = vr_5_20[idx] is not None
    has_sma_cross_history = idx >= 60 and sma20[idx - 1] is not None and sma60[idx - 1] is not None
    historical_highs = [klines[j].get("high") for j in range(max(0, idx - 20), idx) if klines[j].get("high") is not None]
    historical_lows = [klines[j].get("low") for j in range(max(0, idx - 20), idx) if klines[j].get("low") is not None]
    trigger_window_complete = idx >= 20 and len(historical_highs) == 20 and len(historical_lows) == 20

    if len(klines) >= 60 and all([has_sma60, has_macd, has_rsi, has_bollinger, has_volume_ratio, trigger_window_complete, has_sma_cross_history]):
        status = "normal"
    elif len(klines) >= 20:
        status = "partial"
        if not has_sma60:
            limitations.append(f"历史长度 {len(klines)} 不足 60 个交易日，SMA60 不可用")
        if not has_rsi:
            limitations.append("历史长度不足 15 个交易日，RSI14 不可用")
        if not has_volume_ratio:
            limitations.append("成交量历史不足，5/20 日均量比不可用")
        if not trigger_window_complete:
            limitations.append(
                f"{PRICE_RANGE_TRIGGER_UNAVAILABLE_PREFIX}：过去 20 个交易日的 high/low 数据不完整"
            )
        if not has_sma_cross_history:
            limitations.append("均线交叉不可评估：缺少前一交易日 SMA60")
    else:
        status = "unavailable"
        limitations.append(f"历史长度 {len(klines)} 不足 20 个交易日，无法计算主要指标")

    # 触发检测
    triggers = _detect_triggers(klines, sma20, sma60, vr_5_20, idx)

    # latest
    latest = {
        "close": _clean_v(closes[idx]),
        "sma5": _clean_v(sma5[idx]),
        "sma10": _clean_v(sma10[idx]),
        "sma20": _clean_v(sma20[idx]),
        "sma60": _clean_v(sma60[idx]),
        "ema12": _clean_v(ema12[idx]),
        "ema26": _clean_v(ema26[idx]),
        "macd_dif": _clean_v(macd_dif[idx]),
        "macd_dea": _clean_v(macd_dea[idx]),
        "macd_histogram": _clean_v(macd_histogram[idx]),
        "rsi14": _clean_v(rsi14[idx]),
        "bollinger_upper": _clean_v(bollinger_upper[idx]),
        "bollinger_middle": _clean_v(bollinger_middle[idx]),
        "bollinger_lower": _clean_v(bollinger_lower[idx]),
        "volume_ratio_5_20": _clean_v(vr_5_20[idx]),
    }

    # series：最多 60 个数据点
    series_start = max(0, len(klines) - MAX_SERIES_POINTS)
    series: list[dict] = []
    for i in range(series_start, len(klines)):
        series.append(
            {
                "date": klines[i]["date"],
                "sma20": _clean_v(sma20[i]),
                "sma60": _clean_v(sma60[i]),
                "bollinger_upper": _clean_v(bollinger_upper[i]),
                "bollinger_middle": _clean_v(bollinger_middle[i]),
                "bollinger_lower": _clean_v(bollinger_lower[i]),
                "macd_dif": _clean_v(macd_dif[i]),
                "macd_dea": _clean_v(macd_dea[i]),
                "macd_histogram": _clean_v(macd_histogram[i]),
                "rsi14": _clean_v(rsi14[i]),
                "volume_ratio_5_20": _clean_v(vr_5_20[i]),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "code": code,
        "period": period,
        "trade_date": normalized_trade_date,
        "fetched_at": fetched_at,
        "status": status,
        "warnings": [],
        "limitations": limitations,
        "latest": latest,
        "triggers": triggers,
        "series": series,
    }


def _clean_v(v) -> float | None:
    if v is None:
        return None
    if not math.isfinite(v):
        return None
    return v
