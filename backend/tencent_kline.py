"""Bounded Tencent daily/weekly/monthly parsing shared by existing consumers.

Reuses the existing fqkline HTTP capability and PR #355 sequence invariants.
No minute route, host rotation, estimated turnover or adjustment substitution.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
MAX_COUNT = 320


def fetch(code: str, period: str, count: int, *, adjustment: str) -> list[dict]:
    import requests

    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("Tencent K-line requires a six-digit security code")
    if code.startswith(("4", "8", "92")):
        raise ValueError("Tencent K-line history does not support BSE")
    if period not in ("day", "week", "month") or adjustment not in ("", "qfq"):
        raise ValueError("Unsupported Tencent K-line contract")
    if type(count) is not int or not 1 <= count <= MAX_COUNT:
        raise ValueError(f"Tencent K-line count must be between 1 and {MAX_COUNT}")
    prefix = "sh" if code.startswith(("6", "9", "5")) else "sz"
    symbol = prefix + code
    response = requests.get(URL, params={"param": f"{symbol},{period},,,{count},{adjustment}"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    try:
        response.raise_for_status()
        payload = response.json()
    finally:
        response.close()
    data = payload.get("data") if isinstance(payload, dict) else None
    series = data.get(symbol) if isinstance(data, dict) else None
    if not isinstance(series, dict):
        raise ValueError("Tencent K-line security identity is missing")
    # A security without adjustments can expose only the raw key for a qfq
    # request. A present-but-empty qfq key is never substituted. Raw requests
    # never consume any adjusted key.
    key = adjustment + period
    raw = series[key] if key in series else series.get(period) if adjustment else None
    if not isinstance(raw, list) or not raw or len(raw) > count:
        raise ValueError("Tencent K-line series is missing or exceeds the request")
    today = datetime.now(timezone(timedelta(hours=8))).date()
    out = []
    previous = None
    for item in raw:
        if not isinstance(item, list) or len(item) < 6:
            raise ValueError("Tencent K-line row is malformed")
        stamp = date.fromisoformat(item[0])
        if stamp.isoformat() != item[0] or stamp > today or previous is not None and stamp <= previous:
            raise ValueError("Tencent K-line dates are invalid or not increasing")
        values = []
        for value in item[1:6]:
            if value is None or isinstance(value, bool):
                raise ValueError("Tencent K-line numeric value is missing")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("Tencent K-line numeric value is not finite")
            values.append(number)
        opened, closed, high, low, volume = values
        if min(opened, closed, high, low) <= 0 or volume < 0 or not low <= opened <= high or not low <= closed <= high:
            raise ValueError("Tencent K-line OHLC or volume is invalid")
        out.append({"date": stamp.isoformat(), "open": opened, "close": closed,
                    "high": high, "low": low, "volume": volume})
        previous = stamp
    return out


def unadjusted_bars(code: str, period: str, count: int) -> list[dict]:
    rows = fetch(code, period, count, adjustment="")
    for row in rows:
        # Tencent reports lots, while the astock bars contract reports shares.
        shares = row["volume"] * 100
        if not math.isfinite(shares):
            raise ValueError("Tencent K-line share volume overflow")
        row.update(volume=shares, vol=shares, amount=None,
                   datetime=f"{row['date']} 15:00:00", provider_id="tencent",
                   price_adjustment="none", provider_contract="tencent-fqkline-unadjusted.v1")
    return rows
