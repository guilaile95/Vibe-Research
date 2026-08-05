"""BK-11 Slice 3b 日事实历史比较纯计算层 v0.1。

对两份已批准的 ``short-term-daily-facts-v0.1`` envelope（previous /
current）做描述性差异计算：

- facts 段：Slice 1 全部 14 个事实字段的数值 delta（null 安全）
- ladder 段：max_boards / lianban_count / 板级 count 变化的分布对比
- gap 段：缺口层级数 / 段数 / 最大宽度 / 首缺口 / 连续性对比

硬性非目标（文档必须逐条写死）：

- 不进行逐股身份跨日追踪（晋级率，Blocker 2）
- 不计算次日收益 / premium / loss_effect（Slice 0 阻断范围）
- 不评估 legal zero（Blocker 6）
- 不验证 consecutive lbc 来源语义
- 不依赖 live 外部数据 / 交易日历模块（仅要求 prev_date < curr_date）
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Dict, List, Optional

__all__ = [
    "SCHEMA_VERSION",
    "compute_fact_compare",
]

SCHEMA_VERSION = "short-term-fact-compare-v0.1"
SOURCE_SCHEMA_VERSION = "short-term-daily-facts-v0.1"

_REASON_ORDER: tuple[str, ...] = (
    "INPUT_CONTRACT_INVALID",
    "ENVELOPE_CONTRACT_INVALID",
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

_FACT_FIELDS: tuple[str, ...] = (
    "advance_count",
    "decline_count",
    "flat_count",
    "suspended_count",
    "eligible_count",
    "valid_count",
    "up_ratio",
    "limit_up_count",
    "limit_down_count",
    "failed_limit_up_count",
    "touched_limit_up_count",
    "sealed_limit_up_count",
    "failed_board_rate",
    "seal_rate",
)

_STATUS_RANK = {"normal": 0, "partial": 1, "unavailable": 2, "invalid": 3}


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


def _worst(statuses: List[str]) -> str:
    return max(statuses, key=lambda s: _STATUS_RANK[s])


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
        "status": status,
        "sections": sections,
    }


def _section_status(section: Any) -> str:
    """section envelope 的状态；缺失视为 unavailable。"""
    if type(section) is not dict:
        return "unavailable"
    status = section.get("status")
    if type(status) is not str or status not in _ALLOWED_STATUSES:
        return "unavailable"
    return status


def _delta_or_null(prev: Any, curr: Any) -> Any:
    """数值 delta：两侧均为 int -> int；均为有限数 -> round4；
    任一为 None/非法 -> None。"""
    if prev is None or curr is None:
        return None
    if _is_strict_int(prev) and _is_strict_int(curr):
        return curr - prev
    if _is_finite_number(prev) and _is_finite_number(curr):
        return _round4(float(curr) - float(prev))
    return None


def _compute_facts_delta(prev_section: Any, curr_section: Any) -> Dict[str, Any]:
    prev_facts = prev_section.get("facts") if type(prev_section) is dict else None
    curr_facts = curr_section.get("facts") if type(curr_section) is dict else None
    delta: Dict[str, Any] = {}
    for field in _FACT_FIELDS:
        prev_value = prev_facts.get(field) if type(prev_facts) is dict else None
        curr_value = curr_facts.get(field) if type(curr_facts) is dict else None
        delta[field] = _delta_or_null(prev_value, curr_value)
    return delta


def _compute_ladder_delta(prev_section: Any, curr_section: Any) -> Dict[str, Any]:
    prev_metrics = (
        prev_section.get("metrics") if type(prev_section) is dict else None)
    curr_metrics = (
        curr_section.get("metrics") if type(curr_section) is dict else None)
    if type(prev_metrics) is not dict or type(curr_metrics) is not dict:
        return {
            "prev_max_boards": None,
            "curr_max_boards": None,
            "max_boards_delta": None,
            "prev_lianban_count": None,
            "curr_lianban_count": None,
            "lianban_count_delta": None,
            "prev_occupied_boards": None,
            "curr_occupied_boards": None,
            "board_level_changes": None,
        }
    prev_max = prev_metrics.get("max_boards")
    curr_max = curr_metrics.get("max_boards")
    prev_lianban = prev_metrics.get("lianban_count")
    curr_lianban = curr_metrics.get("lianban_count")
    prev_ladder = prev_metrics.get("ladder")
    curr_ladder = curr_metrics.get("ladder")
    prev_counts = {
        item["boards"]: item["count"]
        for item in prev_ladder
        if type(item) is dict and _is_strict_int(item.get("boards"))
        and _is_strict_int(item.get("count"))
    } if type(prev_ladder) is list else {}
    curr_counts = {
        item["boards"]: item["count"]
        for item in curr_ladder
        if type(item) is dict and _is_strict_int(item.get("boards"))
        and _is_strict_int(item.get("count"))
    } if type(curr_ladder) is list else {}
    board_levels = sorted(set(prev_counts) | set(curr_counts))
    changes = [
        {
            "boards": level,
            "prev_count": prev_counts.get(level, 0),
            "curr_count": curr_counts.get(level, 0),
            "delta": curr_counts.get(level, 0) - prev_counts.get(level, 0),
        }
        for level in board_levels
    ]
    return {
        "prev_max_boards": prev_max,
        "curr_max_boards": curr_max,
        "max_boards_delta": _delta_or_null(prev_max, curr_max),
        "prev_lianban_count": prev_lianban,
        "curr_lianban_count": curr_lianban,
        "lianban_count_delta": _delta_or_null(prev_lianban, curr_lianban),
        "prev_occupied_boards": sorted(prev_counts),
        "curr_occupied_boards": sorted(curr_counts),
        "board_level_changes": changes,
    }


def _compute_gap_delta(prev_section: Any, curr_section: Any) -> Dict[str, Any]:
    prev_metrics = (
        prev_section.get("metrics") if type(prev_section) is dict else None)
    curr_metrics = (
        curr_section.get("metrics") if type(curr_section) is dict else None)
    if type(prev_metrics) is not dict or type(curr_metrics) is not dict:
        return {
            "prev_gap_level_count": None,
            "curr_gap_level_count": None,
            "gap_level_count_delta": None,
            "prev_gap_segment_count": None,
            "curr_gap_segment_count": None,
            "gap_segment_count_delta": None,
            "prev_largest_gap_width": None,
            "curr_largest_gap_width": None,
            "largest_gap_width_delta": None,
            "prev_first_gap_board": None,
            "curr_first_gap_board": None,
            "prev_is_continuous": None,
            "curr_is_continuous": None,
        }

    def _as_int(value: Any) -> Optional[int]:
        return value if _is_strict_int(value) else None

    prev_glc = _as_int(prev_metrics.get("gap_level_count"))
    curr_glc = _as_int(curr_metrics.get("gap_level_count"))
    prev_gsc = _as_int(prev_metrics.get("gap_segment_count"))
    curr_gsc = _as_int(curr_metrics.get("gap_segment_count"))
    prev_lgw = _as_int(prev_metrics.get("largest_gap_width"))
    curr_lgw = _as_int(curr_metrics.get("largest_gap_width"))
    prev_fgb = prev_metrics.get("first_gap_board")
    curr_fgb = curr_metrics.get("first_gap_board")
    prev_cont = prev_metrics.get("is_continuous")
    curr_cont = curr_metrics.get("is_continuous")
    return {
        "prev_gap_level_count": prev_glc,
        "curr_gap_level_count": curr_glc,
        "gap_level_count_delta": _delta_or_null(prev_glc, curr_glc),
        "prev_gap_segment_count": prev_gsc,
        "curr_gap_segment_count": curr_gsc,
        "gap_segment_count_delta": _delta_or_null(prev_gsc, curr_gsc),
        "prev_largest_gap_width": prev_lgw,
        "curr_largest_gap_width": curr_lgw,
        "largest_gap_width_delta": _delta_or_null(prev_lgw, curr_lgw),
        "prev_first_gap_board": prev_fgb,
        "curr_first_gap_board": curr_fgb,
        "prev_is_continuous": prev_cont,
        "curr_is_continuous": curr_cont,
    }


def _fixed_limitations() -> List[str]:
    return [
        "descriptive aggregate comparison of two daily-facts envelopes",
        "no per-stock cross-day identity tracking",
        "does not compute layered promotion rates",
        "does not validate consecutive-limit-up semantics",
        "does not evaluate legal zero",
    ]


def _normal_envelope(
    previous_trade_date: str,
    current_trade_date: str,
    status: str,
    reason_codes: List[str],
    section_status: Dict[str, str],
    deltas: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "previous_trade_date": previous_trade_date,
        "current_trade_date": current_trade_date,
        "status": status,
        "reason_codes": reason_codes,
        "warnings": [],
        "limitations": _fixed_limitations(),
        "section_status": section_status,
        "deltas": deltas,
    }


def _invalid_envelope(reason_code: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "previous_trade_date": None,
        "current_trade_date": None,
        "status": "invalid",
        "reason_codes": [reason_code, "OUTPUT_SUPPRESSED"],
        "warnings": [],
        "limitations": _fixed_limitations(),
        "section_status": {"facts": "invalid", "ladder": "invalid",
                           "gap": "invalid"},
        "deltas": {"facts": None, "ladder": None, "gap": None},
    }


def _evaluate(previous: Any, current: Any) -> Dict[str, Any]:
    prev = _validate_envelope(previous)
    if prev is None:
        return _invalid_envelope("ENVELOPE_CONTRACT_INVALID")
    curr = _validate_envelope(current)
    if curr is None:
        return _invalid_envelope("ENVELOPE_CONTRACT_INVALID")
    if prev["trade_date"] >= curr["trade_date"]:
        return _invalid_envelope("DATE_ORDER_INVALID")

    statuses = [prev["status"], curr["status"]]
    section_status: Dict[str, str] = {}
    deltas: Dict[str, Any] = {}

    # facts 段（daily-facts 恒存在；envelope 状态 partial 时仍逐字段
    # null 安全计算，缺失字段 delta=null）
    facts_status = _worst([
        _section_status(prev["sections"].get("facts")),
        _section_status(curr["sections"].get("facts")),
    ])
    section_status["facts"] = facts_status
    deltas["facts"] = _compute_facts_delta(
        prev["sections"].get("facts"), curr["sections"].get("facts"))

    # ladder / gap 段（可能缺失；缺失即 unavailable）
    for name in ("ladder", "gap"):
        prev_section = prev["sections"].get(name)
        curr_section = curr["sections"].get(name)
        sec_status = _worst([
            _section_status(prev_section),
            _section_status(curr_section),
        ])
        section_status[name] = sec_status
        if type(prev_section) is not dict or type(curr_section) is not dict:
            deltas[name] = None
        elif name == "ladder":
            deltas[name] = _compute_ladder_delta(prev_section, curr_section)
        else:
            deltas[name] = _compute_gap_delta(prev_section, curr_section)

    all_statuses = list(statuses) + list(section_status.values())
    overall = _worst(all_statuses)

    codes: List[str] = []
    if overall in ("unavailable", "invalid"):
        if "unavailable" in statuses:
            codes.append("SOURCE_UNAVAILABLE")
        if "invalid" in statuses:
            codes.append("ENVELOPE_CONTRACT_INVALID")
    if "partial" in statuses:
        codes.append("SOURCE_PARTIAL")
    if any(s != "normal" for s in all_statuses):
        codes.append("OUTPUT_SUPPRESSED")
    if overall == "normal":
        codes = []

    return _normal_envelope(
        previous_trade_date=prev["trade_date"],
        current_trade_date=curr["trade_date"],
        status=overall,
        reason_codes=codes,
        section_status=section_status,
        deltas=deltas,
    )


def compute_fact_compare(previous_envelope: dict, current_envelope: dict) -> dict:
    """计算两份日事实 envelope 的描述性差异（Slice 3b 范围）。

    纯计算，不修改输入。普通异常返回固定 invalid envelope（不调用任何
    业务 helper、不包含异常文本）；KeyboardInterrupt / SystemExit /
    GeneratorExit 自然传播。
    """
    try:
        return _evaluate(previous_envelope, current_envelope)
    except Exception:
        # emergency fail-closed envelope：直接构造完整固定字面量，
        # 不得调用任何业务 helper，不得读取输入对象与异常对象。
        return {
            "schema_version": SCHEMA_VERSION,
            "previous_trade_date": None,
            "current_trade_date": None,
            "status": "invalid",
            "reason_codes": ["INPUT_CONTRACT_INVALID", "OUTPUT_SUPPRESSED"],
            "warnings": [],
            "limitations": [
                "descriptive aggregate comparison of two daily-facts envelopes",
                "no per-stock cross-day identity tracking",
                "does not compute layered promotion rates",
                "does not validate consecutive-limit-up semantics",
                "does not evaluate legal zero",
            ],
            "section_status": {"facts": "invalid", "ladder": "invalid",
                               "gap": "invalid"},
            "deltas": {"facts": None, "ladder": None, "gap": None},
        }
