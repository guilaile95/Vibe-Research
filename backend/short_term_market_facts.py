"""BK-11 Slice 1 短线市场事实纯计算层。

纯计算模块：只接受内存 dict，不联网、不读写文件、不访问数据库、
不读环境变量、不使用系统时间、不调用其他业务模块、不修改输入。

范围严格限定为 Slice 1 已获准指标：
市场宽度（advance/decline/flat/suspended/eligible/valid/up_ratio）
与涨跌停/炸板（limit_up/limit_down/failed_limit_up/touched_limit_up/
sealed_limit_up/failed_board_rate/seal_rate）。

Slice 1 阻断清单中的其余能力（见 BK-11 Slice 0 审计文档的 Slice 1
blocked scope 与 fixture slice1_blocked_scope）一律不实现、不输出。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "short-term-market-facts-v0.1"

# ---------------------------------------------------------------------------
# 集中定义：错误码、字段模板、常量
# ---------------------------------------------------------------------------

# reason code 的确定性优先级顺序（输出去重后按此排序）
_REASON_ORDER: Tuple[str, ...] = (
    "SOURCE_UNAVAILABLE",
    "SOURCE_PARTIAL",
    "TRADE_DATE_MISMATCH",
    "PARTIAL_COVERAGE",
    "BREADTH_UNAVAILABLE",
    "LIMIT_ACTIVITY_UNAVAILABLE",
    "BREADTH_IDENTITY_INVALID",
    "INVALID_COUNT",
    "DERIVED_VALUE_MISMATCH",
    "METADATA_INVALID",
    "UNEXPLAINED_EMPTY",
)
_KNOWN_REASON_CODES = frozenset(_REASON_ORDER)

_STATUS_NORMAL = "normal"
_STATUS_PARTIAL = "partial"
_STATUS_UNAVAILABLE = "unavailable"

_ALLOWED_SESSIONS = frozenset(
    {
        "pre_open",
        "call_auction",
        "morning_session",
        "midday_break",
        "afternoon_session",
        "close_pending",
        "final",
        "unavailable",
    }
)

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
    "warnings",
    "limitations",
    "data_health",
    "facts",
)

_FACT_FIELDS: Tuple[str, ...] = (
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

_BREADTH_RAW_FIELDS: Tuple[str, ...] = (
    "advance_count",
    "decline_count",
    "flat_count",
    "suspended_count",
    "eligible_count",
)

_LIMIT_RAW_FIELDS: Tuple[str, ...] = (
    "limit_up_count",
    "limit_down_count",
    "failed_limit_up_count",
)

_DATA_HEALTH_FIELDS: Tuple[str, ...] = (
    "transport_success",
    "parse_success",
    "required_field_present",
    "data_array_present",
    "trade_date_match",
    "row_count",
    "legal_zero",
    "upstream_null",
    "unexplained_empty",
    "coverage_warning",
)

_DATA_HEALTH_BOOL_FIELDS: Tuple[str, ...] = (
    "transport_success",
    "parse_success",
    "required_field_present",
    "data_array_present",
    "trade_date_match",
    "legal_zero",
    "upstream_null",
    "unexplained_empty",
    "coverage_warning",
)

_MODULE_LIMITATION = (
    "BK-11 Slice 1 scope: market breadth and limit-up/down/failed-board "
    "facts only; blocked metrics are not computed"
)

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_WARNING_UNAVAILABLE = "snapshot unavailable; no facts emitted"
_WARNING_PARTIAL = "snapshot partially available; see reason_codes"
_WARNING_INTERNAL = "internal computation failed; snapshot marked unavailable"


# ---------------------------------------------------------------------------
# 私有清洗/校验辅助函数
# ---------------------------------------------------------------------------


def _null_facts() -> Dict[str, None]:
    return {name: None for name in _FACT_FIELDS}


def _null_data_health() -> Dict[str, Any]:
    health: Dict[str, Any] = {name: False for name in _DATA_HEALTH_BOOL_FIELDS}
    health["row_count"] = 0
    return health


def _is_strict_int(value: Any) -> bool:
    """严格 int：拒绝 bool、float、字符串等。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_count_value(value: Any) -> bool:
    return _is_strict_int(value) and value >= 0


def _round4(value: float) -> float:
    return round(value, 4)


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _parse_utc(value: str) -> Optional[datetime]:
    """解析已确认为合法 UTC 的 ISO 8601 字符串。"""
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _normalize_utc_timestamp(value: Any) -> Optional[str]:
    """仅接受可解析且时区为 UTC 的 ISO 8601 字符串；否则返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    parsed = _parse_utc(text)
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    if parsed.utcoffset().total_seconds() != 0:
        return None
    return text


def _finalize_reason_codes(codes: Any) -> List[str]:
    """去重并按固定优先级排序；仅保留已知稳定公开码。"""
    present = {code for code in codes if code in _KNOWN_REASON_CODES}
    return [code for code in _REASON_ORDER if code in present]


def _normalize_source_ids(value: Any, codes: Any) -> List[str]:
    if not isinstance(value, list):
        codes.add("METADATA_INVALID")
        return []
    seen = set()
    result: List[str] = []
    rejected = False
    for item in value:
        if not isinstance(item, str) or item == "":
            rejected = True
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    if rejected:
        codes.add("METADATA_INVALID")
    return result


def _normalize_metadata(snapshot: Dict[str, Any], codes: Any) -> Dict[str, Any]:
    trade_date = snapshot.get("trade_date")
    if not (isinstance(trade_date, str) and _TRADE_DATE_RE.match(trade_date)):
        if trade_date is not None:
            codes.add("METADATA_INVALID")
        trade_date = None

    session = snapshot.get("session")
    if session not in _ALLOWED_SESSIONS:
        if session is not None:
            codes.add("METADATA_INVALID")
        session = None

    is_final = snapshot.get("is_final")
    if not isinstance(is_final, bool):
        if is_final is not None:
            codes.add("METADATA_INVALID")
        is_final = False

    # session 与 is_final 一致性：final 必须 is_final=true，其余必须 false
    if session == "final" and is_final is not True:
        codes.add("METADATA_INVALID")
    elif session is not None and session != "final" and is_final is not False:
        codes.add("METADATA_INVALID")

    fetched_at = _normalize_utc_timestamp(snapshot.get("fetched_at"))
    if fetched_at is None and snapshot.get("fetched_at") is not None:
        codes.add("METADATA_INVALID")
    snapshot_at = _normalize_utc_timestamp(snapshot.get("snapshot_at"))
    if snapshot_at is None and snapshot.get("snapshot_at") is not None:
        codes.add("METADATA_INVALID")
    if fetched_at is not None and snapshot_at is not None:
        left = _parse_utc(fetched_at)
        right = _parse_utc(snapshot_at)
        if left is not None and right is not None and left > right:
            codes.add("METADATA_INVALID")

    source_ids = _normalize_source_ids(snapshot.get("source_ids"), codes)

    return {
        "trade_date": trade_date,
        "session": session,
        "is_final": is_final,
        "source_ids": source_ids,
        "fetched_at": fetched_at,
        "snapshot_at": snapshot_at,
    }


def _normalize_data_health(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """严格化 Data Health 字段：布尔必须为严格 bool，否则按 False 处理。"""
    raw = snapshot.get("data_health")
    health = _null_data_health()
    if not isinstance(raw, dict):
        return health
    for name in _DATA_HEALTH_BOOL_FIELDS:
        value = raw.get(name, False)
        health[name] = value if isinstance(value, bool) else False
    row_count = raw.get("row_count", 0)
    health["row_count"] = row_count if _valid_count_value(row_count) else 0
    return health


def _global_health_failure(health: Dict[str, Any]) -> bool:
    return not (
        health["transport_success"]
        and health["parse_success"]
        and health["required_field_present"]
        and health["data_array_present"]
    ) or health["upstream_null"]


def _extract_raw_counts(
    component: Any, fields: Tuple[str, ...], codes: Any
) -> Optional[Dict[str, int]]:
    """从组件 dict 提取并校验原始计数；任一非法返回 None。"""
    if not isinstance(component, dict):
        return None
    counts: Dict[str, int] = {}
    invalid = False
    for name in fields:
        value = component.get(name)
        if _valid_count_value(value):
            counts[name] = value
        else:
            invalid = True
    if invalid:
        codes.add("INVALID_COUNT")
        return None
    return counts


def _derived_int_mismatch(component: Dict[str, Any], key: str, expected: int) -> bool:
    if key not in component:
        return False
    provided = component[key]
    if not _is_strict_int(provided):
        return True
    return provided != expected


def _derived_rate_mismatch(
    component: Dict[str, Any], key: str, expected: Optional[float]
) -> bool:
    if key not in component:
        return False
    provided = component[key]
    if expected is None:
        # 合法零值场景下不得携带非 null 派生比例
        return provided is not None
    if not _is_finite_number(provided):
        return True
    return _round4(float(provided)) != expected


def _compute_breadth(snapshot: Dict[str, Any], codes: Any) -> Optional[Dict[str, Any]]:
    breadth = snapshot.get("breadth")
    counts = _extract_raw_counts(breadth, _BREADTH_RAW_FIELDS, codes)
    if counts is None:
        codes.add("BREADTH_UNAVAILABLE")
        return None

    valid_count = (
        counts["advance_count"] + counts["decline_count"] + counts["flat_count"]
    )
    if counts["eligible_count"] != valid_count + counts["suspended_count"]:
        codes.add("BREADTH_IDENTITY_INVALID")
        codes.add("BREADTH_UNAVAILABLE")
        return None

    up_ratio: Optional[float] = None
    if valid_count > 0:
        up_ratio = _round4(counts["advance_count"] / valid_count)

    mismatch = False
    mismatch |= _derived_int_mismatch(breadth, "valid_count", valid_count)
    mismatch |= _derived_rate_mismatch(breadth, "up_ratio", up_ratio)
    if mismatch:
        codes.add("DERIVED_VALUE_MISMATCH")

    return {
        "advance_count": counts["advance_count"],
        "decline_count": counts["decline_count"],
        "flat_count": counts["flat_count"],
        "suspended_count": counts["suspended_count"],
        "eligible_count": counts["eligible_count"],
        "valid_count": valid_count,
        "up_ratio": up_ratio,
    }


def _compute_limits(snapshot: Dict[str, Any], codes: Any) -> Optional[Dict[str, Any]]:
    activity = snapshot.get("limit_activity")
    counts = _extract_raw_counts(activity, _LIMIT_RAW_FIELDS, codes)
    if counts is None:
        codes.add("LIMIT_ACTIVITY_UNAVAILABLE")
        return None

    limit_up = counts["limit_up_count"]
    failed = counts["failed_limit_up_count"]
    touched = limit_up + failed
    sealed = limit_up

    failed_board_rate: Optional[float] = None
    seal_rate: Optional[float] = None
    if touched > 0:
        failed_board_rate = _round4(failed / touched)
        seal_rate = _round4(limit_up / touched)

    mismatch = False
    mismatch |= _derived_int_mismatch(activity, "touched_limit_up_count", touched)
    mismatch |= _derived_int_mismatch(activity, "sealed_limit_up_count", sealed)
    mismatch |= _derived_rate_mismatch(activity, "failed_board_rate", failed_board_rate)
    mismatch |= _derived_rate_mismatch(activity, "seal_rate", seal_rate)
    if mismatch:
        codes.add("DERIVED_VALUE_MISMATCH")

    return {
        "limit_up_count": limit_up,
        "limit_down_count": counts["limit_down_count"],
        "failed_limit_up_count": failed,
        "touched_limit_up_count": touched,
        "sealed_limit_up_count": sealed,
        "failed_board_rate": failed_board_rate,
        "seal_rate": seal_rate,
    }


def _normalize_limitations(snapshot: Dict[str, Any]) -> List[str]:
    raw = snapshot.get("limitations")
    kept: List[str] = []
    seen = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item and item not in seen:
                seen.add(item)
                kept.append(item)
    if _MODULE_LIMITATION not in seen:
        kept.append(_MODULE_LIMITATION)
    return kept


def _assemble_facts(
    breadth: Optional[Dict[str, Any]], limits: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    facts = _null_facts()
    if breadth is not None:
        facts.update(breadth)
    if limits is not None:
        facts.update(limits)
    return facts


def _build_envelope(
    metadata: Dict[str, Any],
    status: str,
    codes: Any,
    warnings: List[str],
    limitations: List[str],
    health: Dict[str, Any],
    facts: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": metadata["trade_date"],
        "session": metadata["session"],
        "is_final": metadata["is_final"],
        "source_ids": metadata["source_ids"],
        "fetched_at": metadata["fetched_at"],
        "snapshot_at": metadata["snapshot_at"],
        "status": status,
        "reason_codes": _finalize_reason_codes(codes),
        "warnings": warnings,
        "limitations": limitations,
        "data_health": health,
        "facts": facts,
    }


def _fallback_envelope(snapshot: Any) -> Dict[str, Any]:
    """未知异常/结构损坏时的安全兜底：不泄漏异常原文。"""
    codes = {"SOURCE_UNAVAILABLE"}
    metadata = {
        "trade_date": None,
        "session": None,
        "is_final": False,
        "source_ids": [],
        "fetched_at": None,
        "snapshot_at": None,
    }
    if isinstance(snapshot, dict):
        # 对恶意 dict 子类的读取单独兜底，绝不泄漏异常原文。
        try:
            trade_date = snapshot.get("trade_date")
            if isinstance(trade_date, str) and _TRADE_DATE_RE.match(trade_date):
                metadata["trade_date"] = trade_date
            source_ids = snapshot.get("source_ids")
            if isinstance(source_ids, list):
                seen = set()
                for item in source_ids:
                    if isinstance(item, str) and item and item not in seen:
                        seen.add(item)
                        metadata["source_ids"].append(item)
        except Exception:
            metadata["trade_date"] = None
            metadata["source_ids"] = []
    return _build_envelope(
        metadata=metadata,
        status=_STATUS_UNAVAILABLE,
        codes=codes,
        warnings=[_WARNING_UNAVAILABLE, _WARNING_INTERNAL],
        limitations=[_MODULE_LIMITATION],
        health=_null_data_health(),
        facts=_null_facts(),
    )


def _compute(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    codes: set = set()

    # 保留输入中已有的稳定公开 reason code（如 PARTIAL_COVERAGE）
    raw_reason_codes = snapshot.get("reason_codes")
    if isinstance(raw_reason_codes, list):
        for code in raw_reason_codes:
            if isinstance(code, str) and code in _KNOWN_REASON_CODES:
                codes.add(code)

    metadata = _normalize_metadata(snapshot, codes)
    health = _normalize_data_health(snapshot)
    limitations = _normalize_limitations(snapshot)

    # 全局 transport/parse/必需字段/数据数组/upstream_null 失败：
    # 无论局部计数看似有效，一律 unavailable，不使用失败响应中的残留数据。
    if _global_health_failure(health):
        codes.add("SOURCE_UNAVAILABLE")
        return _build_envelope(
            metadata=metadata,
            status=_STATUS_UNAVAILABLE,
            codes=codes,
            warnings=[_WARNING_UNAVAILABLE],
            limitations=limitations,
            health=health,
            facts=_null_facts(),
        )

    breadth = _compute_breadth(snapshot, codes)
    limits = _compute_limits(snapshot, codes)

    if breadth is None and limits is None:
        return _build_envelope(
            metadata=metadata,
            status=_STATUS_UNAVAILABLE,
            codes=codes,
            warnings=[_WARNING_UNAVAILABLE],
            limitations=limitations,
            health=health,
            facts=_null_facts(),
        )

    degraded = False
    if not health["trade_date_match"]:
        codes.add("TRADE_DATE_MISMATCH")
        degraded = True
    if health["coverage_warning"]:
        codes.add("PARTIAL_COVERAGE")
        degraded = True
    if health["unexplained_empty"] and not health["legal_zero"]:
        codes.add("UNEXPLAINED_EMPTY")
        degraded = True
    if breadth is None or limits is None:
        degraded = True
    if "DERIVED_VALUE_MISMATCH" in codes or "METADATA_INVALID" in codes:
        degraded = True

    status = _STATUS_PARTIAL if degraded else _STATUS_NORMAL
    if status == _STATUS_PARTIAL:
        codes.add("SOURCE_PARTIAL")
        warnings = [_WARNING_PARTIAL]
    else:
        warnings = []

    return _build_envelope(
        metadata=metadata,
        status=status,
        codes=codes,
        warnings=warnings,
        limitations=limitations,
        health=health,
        facts=_assemble_facts(breadth, limits),
    )


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def compute_short_term_market_facts(snapshot: dict) -> dict:
    """计算短线市场事实（Slice 1 范围），永不抛异常。

    输入为规范化 snapshot dict（允许直接传入 BK-11 Slice 0 fixture 的单个
    case）。输入不是 dict、结构损坏或发生未知计算错误时，返回 unavailable
    envelope。对相同输入返回完全相同结果，不修改输入。
    """
    try:
        if not isinstance(snapshot, dict):
            return _fallback_envelope(snapshot)
        return _compute(snapshot)
    except Exception:
        # 公共边界最终兜底：不向调用者泄漏任意异常。
        return _fallback_envelope(snapshot if isinstance(snapshot, dict) else None)
