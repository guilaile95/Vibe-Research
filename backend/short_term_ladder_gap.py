"""BK-11 Slice 2J 连板梯队断层纯计算层 v0.1。

基于已批准的 short-term-limit-up-ladder-v0.1 输出 envelope，计算
2 板至 max_boards 之间缺失的整数板级与连续缺口区间。

纯计算模块：不联网、不读写文件、不访问数据库、不读环境变量、
不使用系统时间、不调用 astock / adapter / producer /
compute_limit_up_ladder、不修改输入、不保存全局可变状态。

本模块不计算、不接收、不透传 layered_promotion_rates；不验证上游
consecutive lbc 的来源语义；不接入生产页面 / API / 调度器。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "SCHEMA_VERSION",
    "compute_ladder_gap",
]

SCHEMA_VERSION = "short-term-ladder-gap-v0.1"
SOURCE_SCHEMA_VERSION = "short-term-limit-up-ladder-v0.1"

# 固定 reason-code 顺序（gate 层专属；未知上游码不得进入本模块 reason_codes）
_REASON_ORDER: Tuple[str, ...] = (
    "SOURCE_UNAVAILABLE",
    "SOURCE_PARTIAL",
    "UPSTREAM_LADDER_UNAVAILABLE",
    "UPSTREAM_LADDER_PARTIAL",
    "LADDER_CONTRACT_INVALID",
    "GAP_OUTPUT_SUPPRESSED",
)

# 镜像上游 ladder 合同的合法 session 集合（不 import 上游模块，保持独立）
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

_ENVELOPE_FIELDS: Tuple[str, ...] = (
    "schema_version",
    "trade_date",
    "session",
    "is_final",
    "source_ids",
    "fetched_at",
    "snapshot_at",
    "status",
    "reason_codes",
    "metrics",
)

_METRIC_FIELDS: Tuple[str, ...] = ("max_boards", "lianban_count", "ladder")

_OUTPUT_METRIC_FIELDS: Tuple[str, ...] = (
    "max_boards",
    "sample_lianban_count",
    "occupied_boards",
    "missing_boards",
    "gap_segments",
    "gap_level_count",
    "gap_segment_count",
    "largest_gap_width",
    "first_gap_board",
    "is_continuous",
)

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 固定 limitations：不信任、不透传调用方 limitations
_LIMITATIONS: Tuple[str, ...] = (
    "derived from an already-computed ladder envelope",
    "gap domain starts at board level 2",
    "does not validate upstream consecutive-limit-up semantics",
    "does not compute layered promotion rates",
)

_METRICS_NULL = {
    name: None for name in _OUTPUT_METRIC_FIELDS
}


def _is_strict_int(value: Any) -> bool:
    """严格 int：拒绝 bool、float、字符串等。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_utc(value: str) -> Optional[datetime]:
    """解析 ISO 8601 字符串为带时区的 datetime；失败返回 None。"""
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _valid_utc_timestamp(value: Any) -> bool:
    """fetched_at / snapshot_at：null 或可解析的 UTC ISO 8601 字符串。"""
    if value is None:
        return True
    if type(value) is not str:
        return False
    text = value.strip()
    if not text:
        return False
    parsed = _parse_utc(text)
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    return parsed.utcoffset().total_seconds() == 0


def _normalize_source_reason_codes(value: Any) -> Optional[List[str]]:
    """source reason codes：精确 list[str]（拒绝子类）、非空、去重保序。

    合同非法返回 None。未知上游码保留在 source_reason_codes 中，
    不进入本模块 reason_codes。
    """
    if type(value) is not list:
        return None
    seen: List[str] = []
    for item in value:
        if type(item) is not str or not item:
            return None
        if item not in seen:
            seen.append(item)
    return seen


def _validate_input_contract(envelope: Any) -> Optional[Dict[str, Any]]:
    """输入 envelope 基本合同：dict、schema、10 字段存在、status、reason_codes、
    metrics 键集合。返回 None 表示合同非法。"""
    if type(envelope) is not dict:
        return None
    if envelope.get("schema_version") != SOURCE_SCHEMA_VERSION:
        return None
    for field in _ENVELOPE_FIELDS:
        if field not in envelope:
            return None
    status = envelope.get("status")
    if status not in ("normal", "partial", "unavailable"):
        return None
    source_reason_codes = _normalize_source_reason_codes(envelope.get("reason_codes"))
    if source_reason_codes is None:
        return None
    metrics = envelope.get("metrics")
    if type(metrics) is not dict or set(metrics.keys()) != set(_METRIC_FIELDS):
        return None
    return {
        "status": status,
        "source_reason_codes": source_reason_codes,
        "metrics": metrics,
    }


def _validate_metadata(envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """元数据严格验证（normal 计算路径）：真实日历日期、上游 session、
    is_final 一致性、source_ids、UTC 时间戳与先后关系。

    返回归一化后的元数据 dict；非法返回 None。
    """
    trade_date = envelope.get("trade_date")
    if type(trade_date) is not str or _TRADE_DATE_RE.match(trade_date) is None:
        return None
    try:
        date.fromisoformat(trade_date)
    except ValueError:
        return None

    session = envelope.get("session")
    if type(session) is not str or session not in _ALLOWED_SESSIONS:
        return None

    is_final = envelope.get("is_final")
    if type(is_final) is not bool:
        return None
    if is_final != (session == "final"):
        return None

    source_ids_value = envelope.get("source_ids")
    if type(source_ids_value) is not list:
        return None
    source_ids: List[str] = []
    for item in source_ids_value:
        if type(item) is not str or not item:
            return None
        if item not in source_ids:
            source_ids.append(item)

    fetched_at = envelope.get("fetched_at")
    snapshot_at = envelope.get("snapshot_at")
    if not _valid_utc_timestamp(fetched_at):
        return None
    if not _valid_utc_timestamp(snapshot_at):
        return None
    if fetched_at is not None and snapshot_at is not None:
        left = _parse_utc(fetched_at)
        right = _parse_utc(snapshot_at)
        if left is not None and right is not None and left > right:
            return None

    return {
        "trade_date": trade_date,
        "session": session,
        "is_final": is_final,
        "source_ids": source_ids,
        "fetched_at": fetched_at,
        "snapshot_at": snapshot_at,
    }


def _validate_metrics(metrics: Dict[str, Any]) -> bool:
    """normal 状态上游 metrics 严格验证（§五）。"""
    max_boards = metrics.get("max_boards")
    if not _is_strict_int(max_boards) or max_boards < 0:
        return False
    lianban_count = metrics.get("lianban_count")
    if not _is_strict_int(lianban_count) or lianban_count < 0:
        return False
    ladder = metrics.get("ladder")
    if type(ladder) is not list:
        return False

    if lianban_count == 0:
        if ladder != []:
            return False
        return max_boards in (0, 1)

    if not ladder:
        return False
    total = 0
    prev_boards: Optional[int] = None
    for item in ladder:
        if type(item) is not dict or set(item.keys()) != {"boards", "count"}:
            return False
        boards = item.get("boards")
        count = item.get("count")
        if not _is_strict_int(boards) or boards < 2:
            return False
        if not _is_strict_int(count) or count <= 0:
            return False
        if prev_boards is not None and boards <= prev_boards:
            return False
        prev_boards = boards
        total += count
    if total != lianban_count:
        return False
    if max_boards != ladder[-1]["boards"]:
        return False
    return True


def _compute_gap_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """断层计算：域 [2, max_boards]，occupied 来自已验证 ladder。"""
    max_boards = metrics["max_boards"]
    ladder = metrics["ladder"]
    occupied = [item["boards"] for item in ladder]
    occupied_set = set(occupied)
    missing = [
        boards for boards in range(2, max_boards + 1)
        if boards not in occupied_set
    ]
    segments: List[Dict[str, int]] = []
    index = 0
    while index < len(missing):
        end = index
        while (
            end + 1 < len(missing)
            and missing[end + 1] == missing[end] + 1
        ):
            end += 1
        segments.append({
            "from_board": missing[index],
            "to_board": missing[end],
            "width": missing[end] - missing[index] + 1,
        })
        index = end + 1
    return {
        "max_boards": max_boards,
        "sample_lianban_count": metrics["lianban_count"],
        "occupied_boards": occupied,
        "missing_boards": missing,
        "gap_segments": segments,
        "gap_level_count": len(missing),
        "gap_segment_count": len(segments),
        "largest_gap_width": max(
            (segment["width"] for segment in segments), default=0),
        "first_gap_board": missing[0] if missing else None,
        "is_continuous": not missing,
    }


def _normal_envelope(
    metadata: Dict[str, Any],
    source_reason_codes: List[str],
    gap_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": metadata["trade_date"],
        "session": metadata["session"],
        "is_final": metadata["is_final"],
        "source_ids": list(metadata["source_ids"]),
        "fetched_at": metadata["fetched_at"],
        "snapshot_at": metadata["snapshot_at"],
        "status": "normal",
        "reason_codes": [],
        "warnings": [],
        "limitations": list(_LIMITATIONS),
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "source_status": "normal",
        "source_reason_codes": list(source_reason_codes),
        "metrics": gap_metrics,
    }


def _suppressed_envelope(
    kind: str,
    source_reason_codes: List[str],
) -> Dict[str, Any]:
    if kind == "partial":
        status = "partial"
        reason_codes = [
            "SOURCE_PARTIAL",
            "UPSTREAM_LADDER_PARTIAL",
            "GAP_OUTPUT_SUPPRESSED",
        ]
        source_status = "partial"
    else:
        status = "unavailable"
        reason_codes = [
            "SOURCE_UNAVAILABLE",
            "UPSTREAM_LADDER_UNAVAILABLE",
            "GAP_OUTPUT_SUPPRESSED",
        ]
        source_status = "unavailable"
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": None,
        "session": "unavailable",
        "is_final": False,
        "source_ids": [],
        "fetched_at": None,
        "snapshot_at": None,
        "status": status,
        "reason_codes": reason_codes,
        "warnings": [],
        "limitations": list(_LIMITATIONS),
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "source_status": source_status,
        "source_reason_codes": list(source_reason_codes),
        "metrics": dict(_METRICS_NULL),
    }


def _invalid_envelope() -> Dict[str, Any]:
    """合同非法 / 元数据非法 / metrics 非法的固定 invalid envelope。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": None,
        "session": "unavailable",
        "is_final": False,
        "source_ids": [],
        "fetched_at": None,
        "snapshot_at": None,
        "status": "invalid",
        "reason_codes": ["LADDER_CONTRACT_INVALID", "GAP_OUTPUT_SUPPRESSED"],
        "warnings": [],
        "limitations": list(_LIMITATIONS),
        "source_schema_version": None,
        "source_status": None,
        "source_reason_codes": [],
        "metrics": dict(_METRICS_NULL),
    }


def _evaluate(ladder_envelope: Any) -> Dict[str, Any]:
    contract = _validate_input_contract(ladder_envelope)
    if contract is None:
        return _invalid_envelope()
    status = contract["status"]
    source_reason_codes = contract["source_reason_codes"]
    if status == "partial":
        return _suppressed_envelope("partial", source_reason_codes)
    if status == "unavailable":
        return _suppressed_envelope("unavailable", source_reason_codes)
    metadata = _validate_metadata(ladder_envelope)
    if metadata is None:
        return _invalid_envelope()
    if not _validate_metrics(contract["metrics"]):
        return _invalid_envelope()
    gap_metrics = _compute_gap_metrics(contract["metrics"])
    return _normal_envelope(metadata, source_reason_codes, gap_metrics)


def compute_ladder_gap(ladder_envelope: dict) -> dict:
    """计算连板梯队断层指标。

    输入为上游 short-term-limit-up-ladder-v0.1 envelope。纯计算，
    不修改输入。普通异常返回固定 invalid envelope（不调用任何业务
    helper、不包含异常文本）；KeyboardInterrupt / SystemExit /
    GeneratorExit 自然传播。
    """
    try:
        return _evaluate(ladder_envelope)
    except Exception:
        # emergency fail-closed envelope：直接返回固定字面量，
        # 不得调用 _invalid_envelope 或任何业务 helper。
        return {
            "schema_version": SCHEMA_VERSION,
            "trade_date": None,
            "session": "unavailable",
            "is_final": False,
            "source_ids": [],
            "fetched_at": None,
            "snapshot_at": None,
            "status": "invalid",
            "reason_codes": ["LADDER_CONTRACT_INVALID", "GAP_OUTPUT_SUPPRESSED"],
            "warnings": [],
            "limitations": list(_LIMITATIONS),
            "source_schema_version": None,
            "source_status": None,
            "source_reason_codes": [],
            "metrics": dict(_METRICS_NULL),
        }
