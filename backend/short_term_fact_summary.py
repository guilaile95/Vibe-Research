"""BK-11 Slice 3c 多日事实摘要纯计算层 v0.1。

接收已批准的 ``short-term-daily-facts-v0.1`` envelope 列表（按
trade_date 严格升序、无重复快照），输出窗口内描述性摘要：

- 窗口信息（数量 / 首末日期）
- 状态分布（normal / partial / unavailable / invalid）
- 关键事实统计（limit_up_count / advance_count / failed_board_rate /
  seal_rate / up_ratio 的 min / max / avg / count）
- 梯队统计（有梯队天数 / max_boards 与 lianban_count 的 max / avg）
- 断层统计（有断层段天数 / gap_level_count 与 largest_gap_width 的
  max / avg / 连续天数）

统计只覆盖 envelope status == normal 的天（partial/unavailable/invalid
仅计入状态分布）。硬性非目标：不进行逐股身份跨日追踪、不计算晋级率、
不评估 legal zero、不验证 consecutive lbc 语义、不依赖存储或 live 数据。
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Dict, List, Optional

__all__ = [
    "SCHEMA_VERSION",
    "compute_fact_summary",
]

SCHEMA_VERSION = "short-term-fact-summary-v0.1"
SOURCE_SCHEMA_VERSION = "short-term-daily-facts-v0.1"

_REASON_ORDER: tuple[str, ...] = (
    "INPUT_CONTRACT_INVALID",
    "ENVELOPE_CONTRACT_INVALID",
    "DUPLICATE_SNAPSHOT_INVALID",
    "DATE_ORDER_INVALID",
    "SOURCE_UNAVAILABLE",
    "SOURCE_PARTIAL",
    "OUTPUT_SUPPRESSED",
)

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_SESSIONS = frozenset({
    "pre_open",
    "call_auction",
    "morning_session",
    "midday_break",
    "afternoon_session",
    "close_pending",
    "final",
    "unavailable",
})
_ALLOWED_STATUSES = frozenset({
    "normal",
    "partial",
    "unavailable",
    "invalid",
})

# 会话时间序（与字典序不同；排序按此时间序比较）
_SESSION_ORDER = {
    "pre_open": 0,
    "call_auction": 1,
    "morning_session": 2,
    "midday_break": 3,
    "afternoon_session": 4,
    "close_pending": 5,
    "final": 6,
    "unavailable": 7,
}

_ENVELOPE_FIELDS = frozenset({
    "schema_version",
    "trade_date",
    "session",
    "is_final",
    "source_ids",
    "fetched_at",
    "snapshot_at",
    "status",
    "reason_codes",
    "warnings",
    "limitations",
    "source_schema_version",
    "source_status",
    "source_reason_codes",
    "sections",
})

# 摘要统计的事实字段（int 计数 / float 比率）
_FACT_INT_FIELDS: tuple[str, ...] = (
    "limit_up_count",
    "advance_count",
)
_FACT_RATE_FIELDS: tuple[str, ...] = (
    "failed_board_rate",
    "seal_rate",
    "up_ratio",
)


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _round4(value: float) -> float:
    return round(value, 4)


def _valid_trade_date(value: Any) -> bool:
    if type(value) is not str or _TRADE_DATE_RE.match(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_envelope(envelope: Any) -> Optional[Dict[str, Any]]:
    """daily-facts envelope 形状校验；非法返回 None。"""
    if type(envelope) is not dict:
        return None
    if envelope.get("schema_version") != SOURCE_SCHEMA_VERSION:
        return None
    if set(envelope.keys()) != _ENVELOPE_FIELDS:
        return None
    if not _valid_trade_date(envelope.get("trade_date")):
        return None
    session = envelope.get("session")
    if type(session) is not str or session not in _ALLOWED_SESSIONS:
        return None
    status = envelope.get("status")
    if type(status) is not str or status not in _ALLOWED_STATUSES:
        return None
    if type(envelope.get("is_final")) is not bool:
        return None
    source_ids = envelope.get("source_ids")
    if type(source_ids) is not list or any(
            type(item) is not str for item in source_ids):
        return None
    sections = envelope.get("sections")
    if type(sections) is not dict or set(sections.keys()) != {
            "facts", "ladder", "gap"}:
        return None
    return {
        "trade_date": envelope["trade_date"],
        "session": session,
        "status": status,
        "sections": sections,
    }


def _stats_add(bucket: Dict[str, Any], value: float) -> None:
    bucket["count"] += 1
    if bucket["min"] is None or value < bucket["min"]:
        bucket["min"] = value
    if bucket["max"] is None or value > bucket["max"]:
        bucket["max"] = value
    bucket["sum"] += value


def _stats_finalize(bucket: Dict[str, Any]) -> Dict[str, Any]:
    if bucket["count"] == 0:
        return {"min": None, "max": None, "avg": None, "count": 0}
    if bucket["is_int"]:
        return {
            "min": int(bucket["min"]),
            "max": int(bucket["max"]),
            "avg": _round4(bucket["sum"] / bucket["count"]),
            "count": bucket["count"],
        }
    return {
        "min": bucket["min"],
        "max": bucket["max"],
        "avg": _round4(bucket["sum"] / bucket["count"]),
        "count": bucket["count"],
    }


def _collect_fact_stats(
    sections: Dict[str, Any],
    field: str,
    bucket: Dict[str, Any],
) -> None:
    facts_section = sections.get("facts")
    if type(facts_section) is not dict:
        return
    facts = facts_section.get("facts")
    if type(facts) is not dict:
        return
    value = facts.get(field)
    if value is None:
        return
    if bucket["is_int"]:
        # int 字段只接受严格 int；float/bool 等类型非法，跳过而非截断
        if not _is_strict_int(value):
            return
        _stats_add(bucket, float(value))
    elif _is_finite_number(value):
        _stats_add(bucket, float(value))


def _collect_ladder_stats(
    sections: Dict[str, Any],
    buckets: Dict[str, Any],
) -> None:
    ladder_section = sections.get("ladder")
    if type(ladder_section) is not dict:
        return
    metrics = ladder_section.get("metrics")
    if type(metrics) is not dict:
        return
    max_boards = metrics.get("max_boards")
    lianban_count = metrics.get("lianban_count")
    if _is_strict_int(max_boards):
        _stats_add(buckets["max_boards"], float(max_boards))
    if _is_strict_int(lianban_count):
        _stats_add(buckets["lianban_count"], float(lianban_count))


def _collect_gap_stats(
    sections: Dict[str, Any],
    buckets: Dict[str, Any],
    meta: Dict[str, Any],
) -> None:
    gap_section = sections.get("gap")
    if type(gap_section) is not dict:
        return
    metrics = gap_section.get("metrics")
    if type(metrics) is not dict:
        return
    glc = metrics.get("gap_level_count")
    lgw = metrics.get("largest_gap_width")
    continuous = metrics.get("is_continuous")
    if _is_strict_int(glc):
        meta["days_with_gap_section"] += 1
        _stats_add(buckets["gap_level_count"], float(glc))
    if _is_strict_int(lgw):
        _stats_add(buckets["largest_gap_width"], float(lgw))
    if type(continuous) is bool and continuous:
        meta["continuous_days"] += 1


def _new_bucket(is_int: bool = False) -> Dict[str, Any]:
    return {"min": None, "max": None, "sum": 0.0, "count": 0,
            "is_int": is_int}


def _compute_stats(envelopes: List[Dict[str, Any]]) -> Dict[str, Any]:
    status_counts = {name: 0 for name in _ALLOWED_STATUSES}
    fact_buckets = {
        **{field: _new_bucket(is_int=True) for field in _FACT_INT_FIELDS},
        **{field: _new_bucket(is_int=False) for field in _FACT_RATE_FIELDS},
    }
    ladder_buckets = {
        "max_boards": _new_bucket(is_int=True),
        "lianban_count": _new_bucket(is_int=True),
    }
    gap_buckets = {
        "gap_level_count": _new_bucket(is_int=True),
        "largest_gap_width": _new_bucket(is_int=True),
    }
    gap_meta = {
        "days_with_gap_section": 0,
        "continuous_days": 0,
    }
    for envelope in envelopes:
        status = envelope["status"]
        status_counts[status] += 1
        if status != "normal":
            continue
        sections = envelope["sections"]
        for field in _FACT_INT_FIELDS + _FACT_RATE_FIELDS:
            _collect_fact_stats(sections, field, fact_buckets[field])
        _collect_ladder_stats(sections, ladder_buckets)
        _collect_gap_stats(sections, gap_buckets, gap_meta)

    facts: Dict[str, Any] = {}
    for field in _FACT_INT_FIELDS + _FACT_RATE_FIELDS:
        facts[field] = _stats_finalize(fact_buckets[field])

    ladder: Dict[str, Any] = {}
    for field in ("max_boards", "lianban_count"):
        ladder[field] = _stats_finalize(ladder_buckets[field])
    ladder["days_with_ladder"] = ladder["max_boards"]["count"]

    gap: Dict[str, Any] = {}
    for field in ("gap_level_count", "largest_gap_width"):
        gap[field] = _stats_finalize(gap_buckets[field])
    gap["days_with_gap_section"] = gap_meta["days_with_gap_section"]
    gap["continuous_days"] = gap_meta["continuous_days"]

    return {
        "status_distribution": status_counts,
        "facts": facts,
        "ladder": ladder,
        "gap": gap,
    }


def _fixed_limitations() -> List[str]:
    return [
        "descriptive window summary of daily-facts envelopes",
        "stats computed over normal-status days only",
        "does not compute layered promotion rates",
        "does not validate consecutive-limit-up semantics",
        "no per-stock cross-day identity tracking",
        "does not evaluate legal zero",
    ]


def _normal_envelope(
    first_trade_date: str,
    last_trade_date: str,
    count: int,
    status: str,
    reason_codes: List[str],
    stats: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "window": {
            "count": count,
            "first_trade_date": first_trade_date,
            "last_trade_date": last_trade_date,
        },
        "status": status,
        "reason_codes": reason_codes,
        "warnings": [],
        "limitations": _fixed_limitations(),
        "stats": stats,
    }


def _invalid_envelope(reason_code: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "window": {"count": None, "first_trade_date": None,
                   "last_trade_date": None},
        "status": "invalid",
        "reason_codes": [reason_code, "OUTPUT_SUPPRESSED"],
        "warnings": [],
        "limitations": _fixed_limitations(),
        "stats": None,
    }


def _evaluate(envelopes: Any) -> Dict[str, Any]:
    if type(envelopes) is not list:
        return _invalid_envelope("INPUT_CONTRACT_INVALID")
    if not envelopes:
        return _invalid_envelope("INPUT_CONTRACT_INVALID")

    validated: List[Dict[str, Any]] = []
    seen: set = set()
    prev_key: Optional[tuple] = None
    for envelope in envelopes:
        item = _validate_envelope(envelope)
        if item is None:
            return _invalid_envelope("ENVELOPE_CONTRACT_INVALID")
        key = (item["trade_date"], _SESSION_ORDER[item["session"]])
        if key in seen:
            return _invalid_envelope("DUPLICATE_SNAPSHOT_INVALID")
        seen.add(key)
        if prev_key is not None and key <= prev_key:
            return _invalid_envelope("DATE_ORDER_INVALID")
        prev_key = key
        validated.append(item)

    statuses = [item["status"] for item in validated]
    if "invalid" in statuses:
        # 窗口含 invalid 状态 envelope：该日数据不可用，窗口整体失败关闭
        return _invalid_envelope("ENVELOPE_CONTRACT_INVALID")

    codes: List[str] = []
    if "unavailable" in statuses:
        codes.append("SOURCE_UNAVAILABLE")
    if "partial" in statuses:
        codes.append("SOURCE_PARTIAL")
    if any(status != "normal" for status in statuses):
        codes.append("OUTPUT_SUPPRESSED")

    overall = "normal"
    if "unavailable" in statuses:
        overall = "unavailable"
    elif "partial" in statuses:
        overall = "partial"
    if overall == "normal":
        codes = []

    stats = _compute_stats(validated)
    return _normal_envelope(
        first_trade_date=validated[0]["trade_date"],
        last_trade_date=validated[-1]["trade_date"],
        count=len(validated),
        status=overall,
        reason_codes=codes,
        stats=stats,
    )


def compute_fact_summary(envelopes: list) -> dict:
    """计算多日事实窗口摘要（Slice 3c 范围）。

    输入为 daily-facts envelope 列表（trade_date 严格升序、无重复快照）。
    纯计算，不修改输入。普通异常返回固定 invalid envelope（不调用任何
    业务 helper、不包含异常文本）；KeyboardInterrupt / SystemExit /
    GeneratorExit 自然传播。
    """
    try:
        return _evaluate(envelopes)
    except Exception:
        # emergency fail-closed envelope：直接构造完整固定字面量。
        return {
            "schema_version": SCHEMA_VERSION,
            "window": {"count": None, "first_trade_date": None,
                       "last_trade_date": None},
            "status": "invalid",
            "reason_codes": ["INPUT_CONTRACT_INVALID", "OUTPUT_SUPPRESSED"],
            "warnings": [],
            "limitations": [
                "descriptive window summary of daily-facts envelopes",
                "stats computed over normal-status days only",
                "does not compute layered promotion rates",
                "does not validate consecutive-limit-up semantics",
                "no per-stock cross-day identity tracking",
                "does not evaluate legal zero",
            ],
            "stats": None,
        }
