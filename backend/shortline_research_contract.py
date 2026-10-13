"""Versioned, retrospective research inputs. No formal decision authority."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import re

VERSION = "shortline-research.v1"
KINDS = ("limit_up", "broken", "limit_down", "daily_prices", "daily_limits")
DATASETS = {kind: f"research_shortline_{kind}_v1" for kind in KINDS}
ENDPOINTS = {"limit_up": "getTopicZTPool", "broken": "getTopicZBPool", "limit_down": "getTopicDTPool",
             "daily_prices": "daily", "daily_limits": "stk_limit"}
MAX_ROWS = 10000
MAX_BYTES = 16 * 1024 * 1024
MAX_PAGES = 100
LIMITATIONS = [
    "当前归档版本的事后研究；后续来源修订可能改变结果，不证明历史当时已知。",
    "完整昨日名单固定分母；缺行情、停牌、退市和不兼容价格保持未知，不作为零收益。",
    "收益为来源同日可比参考价至收盘的描述性变动，不含排队成交、手续费、滑点或可成交性。",
    "10/20/30/60及20/30/60/90窗口均为固定交易日跨度，缺失日期不向前补齐。",
    "统计不构成预测、买卖建议、正式晋级权威或Day 1验收；既有冻结决策不变。",
]


def day(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("invalid trade date")
    date.fromisoformat(value)
    return value


def instant(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value):
        raise ValueError("invalid timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone required")
    return result.astimezone(timezone.utc)


def utc(value):
    return instant(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def code(value):
    if type(value) is not str or not re.fullmatch(r"\d{6}(?:\.(?:SH|SZ|BJ))?", value):
        raise ValueError("invalid stock identity")
    digits = value[:6]
    exchange = "SH" if digits.startswith(("60", "68")) else "SZ" if digits.startswith(("00", "30")) else "BJ" if digits.startswith(("43", "83", "87", "88", "92")) else None
    if exchange is None or ("." in value and value[7:] != exchange):
        raise ValueError("invalid stock exchange")
    return digits


def finite(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        return None
    return float(value)


def integer(value, *, minimum=0):
    return value if type(value) is int and minimum <= value <= 2_147_483_647 else None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def decode(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("invalid raw response size")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON field")
            out[key] = value
        return out
    def invalid_constant(_):
        raise ValueError("nonfinite JSON")
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    if type(result) is not dict:
        raise ValueError("response must be an object")
    return result


def source_fields(rows):
    if not rows:
        return None
    fields = sorted({str(key) for row in rows for key in row} |
                    {f"{key}.{child}" for row in rows for key, value in row.items() if type(value) is dict for child in value})
    if len(fields) > 512 or any(len(field) > 128 for field in fields):
        raise ValueError("raw field catalogue exceeds bounded research schema")
    return fields
