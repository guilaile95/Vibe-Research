"""BK-11 Slice 2A 连板梯队纯计算层。

纯计算模块：只接受内存 dict，不联网、不读写文件、不访问数据库、
不读环境变量、不使用系统时间、不调用其他业务模块、不修改输入。

范围严格限定为 Slice 2A 已获准指标：
max_boards / lianban_count / ladder（仅 boards>=2 档位，结构为
``[{"boards": int, "count": int}, ...]``，按 boards 升序）。

Slice 2A 阻断清单中的其余能力（layered_promotion_rates、
next_open_return、next_close_return、next_high_return、loss_effect、
theme_structure、seal_quality、history、T+1）一律不实现、不输出。
fixture 中的展示性 ``plus`` 字段不属于已验收计算合同，本模块不依赖、不输出。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "short-term-limit-up-ladder-v0.1"

# ---------------------------------------------------------------------------
# 集中定义：错误码、字段模板、常量
# ---------------------------------------------------------------------------

# reason code 的确定性优先级顺序（输出去重后按此排序）
_REASON_ORDER: Tuple[str, ...] = (
    "SOURCE_UNAVAILABLE",
    "SOURCE_PARTIAL",
    "METADATA_INVALID",
    "TRADE_DATE_MISMATCH",
    "PARTIAL_COVERAGE",
    "UNEXPLAINED_EMPTY",
    "LIMIT_UP_POOL_UNAVAILABLE",
    "INVALID_POOL_ROW",
    "DUPLICATE_STOCK_CODE",
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
    "metrics",
)

_METRIC_FIELDS: Tuple[str, ...] = ("max_boards", "lianban_count", "ladder")

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

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_WARNING_UNAVAILABLE = "snapshot unavailable; no ladder metrics emitted"
_WARNING_PARTIAL = "snapshot partially available; see reason_codes"

# 固定 limitations：不信任或透传调用方 limitations
_LIMITATIONS: Tuple[str, ...] = (
    "single-source (eastmoney push2ex), not cross-validated",
    "licensing_status: unclear",
    "consecutive limit-up day semantics not independently verified",
)


# ---------------------------------------------------------------------------
# 私有清洗/校验辅助函数
# ---------------------------------------------------------------------------


def _null_metrics() -> Dict[str, None]:
    return {name: None for name in _METRIC_FIELDS}


def _null_data_health() -> Dict[str, Any]:
    health: Dict[str, Any] = {name: False for name in _DATA_HEALTH_BOOL_FIELDS}
    health["row_count"] = 0
    return health


def _is_strict_int(value: Any) -> bool:
    """严格 int：拒绝 bool、float、字符串等。"""
    return isinstance(value, int) and not isinstance(value, bool)


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
    if not isinstance(session, str) or session not in _ALLOWED_SESSIONS:
        codes.add("METADATA_INVALID")
        session = "unavailable"

    # is_final 必须由归一化后的 session 强制决定，绝不保留调用方冲突值。
    raw_is_final = snapshot.get("is_final")
    if not isinstance(raw_is_final, bool):
        codes.add("METADATA_INVALID")
    elif raw_is_final != (session == "final"):
        codes.add("METADATA_INVALID")
    is_final = session == "final"

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
    health["row_count"] = (
        row_count if _is_strict_int(row_count) and row_count >= 0 else 0
    )
    return health


def _global_health_failure(health: Dict[str, Any]) -> bool:
    return not (
        health["transport_success"]
        and health["parse_success"]
        and health["required_field_present"]
        and health["data_array_present"]
    ) or health["upstream_null"]


def _normalize_pool(
    raw: Any, codes: Any
) -> Tuple[List[Dict[str, Any]], bool]:
    """规范化 limit_up_pool。

    返回 (valid_rows, pool_is_list)。
    - valid_rows: 去重后保留首次合法记录的列表
    - pool_is_list: 原始输入是否为 list
    - 非法记录 → INVALID_POOL_ROW
    - 重复 stock_code → DUPLICATE_STOCK_CODE
    """
    if not isinstance(raw, list):
        return [], False
    seen_codes: set = set()
    valid: List[Dict[str, Any]] = []
    had_invalid = False
    had_duplicate = False
    for item in raw:
        if not isinstance(item, dict):
            had_invalid = True
            continue
        stock_code = item.get("stock_code")
        if not isinstance(stock_code, str):
            had_invalid = True
            continue
        code = stock_code.strip()
        if not code:
            had_invalid = True
            continue
        days = item.get("consecutive_limit_up_days")
        if not _is_strict_int(days) or days < 1:
            had_invalid = True
            continue
        if code in seen_codes:
            had_duplicate = True
            continue
        seen_codes.add(code)
        valid.append({"stock_code": code, "consecutive_limit_up_days": days})
    if had_invalid:
        codes.add("INVALID_POOL_ROW")
    if had_duplicate:
        codes.add("DUPLICATE_STOCK_CODE")
    return valid, True


def _compute_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """根据合法记录计算 max_boards / lianban_count / ladder。"""
    max_boards = 0
    lianban_count = 0
    buckets: Dict[int, int] = {}
    for row in rows:
        days = row["consecutive_limit_up_days"]
        if days > max_boards:
            max_boards = days
        if days >= 2:
            lianban_count += 1
            buckets[days] = buckets.get(days, 0) + 1
    ladder = [
        {"boards": boards, "count": buckets[boards]}
        for boards in sorted(buckets.keys())
    ]
    return {
        "max_boards": max_boards,
        "lianban_count": lianban_count,
        "ladder": ladder,
    }


def _legal_zero_metrics() -> Dict[str, Any]:
    return {"max_boards": 0, "lianban_count": 0, "ladder": []}


def _row_count_mismatch(health: Dict[str, Any], raw_pool_len: int) -> bool:
    row_count = health["row_count"]
    return _is_strict_int(row_count) and raw_pool_len != row_count


def _build_envelope(
    metadata: Dict[str, Any],
    health: Dict[str, Any],
    status: str,
    codes: Any,
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    warnings: List[str] = []
    if status == _STATUS_PARTIAL:
        warnings = [_WARNING_PARTIAL]
    elif status == _STATUS_UNAVAILABLE:
        warnings = [_WARNING_UNAVAILABLE]
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
        "limitations": list(_LIMITATIONS),
        "data_health": health,
        "metrics": metrics,
    }


def _fallback_envelope() -> Dict[str, Any]:
    codes = {"SOURCE_UNAVAILABLE"}
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": None,
        "session": "unavailable",
        "is_final": False,
        "source_ids": [],
        "fetched_at": None,
        "snapshot_at": None,
        "status": _STATUS_UNAVAILABLE,
        "reason_codes": _finalize_reason_codes(codes),
        "warnings": [_WARNING_UNAVAILABLE],
        "limitations": list(_LIMITATIONS),
        "data_health": _null_data_health(),
        "metrics": _null_metrics(),
    }


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------


def compute_limit_up_ladder(snapshot: Any) -> Dict[str, Any]:
    """计算连板梯队指标。

    纯计算：不联网、不读写文件、不访问数据库、不读环境变量、
    不使用系统时间、不修改输入。任何非法输入或未知异常返回安全
    ``unavailable`` envelope，不泄漏异常类名、路径、URL 或 traceback。
    """
    try:
        if not isinstance(snapshot, dict):
            return _fallback_envelope()

        codes: set = set()
        metadata = _normalize_metadata(snapshot, codes)
        health = _normalize_data_health(snapshot)
        raw_pool = snapshot.get("limit_up_pool")
        valid_rows, pool_is_list = _normalize_pool(raw_pool, codes)
        raw_pool_len = len(raw_pool) if pool_is_list else 0

        # 1. 全局 Data Health 失败 → unavailable, metrics=null
        if _global_health_failure(health):
            codes.add("SOURCE_UNAVAILABLE")
            return _build_envelope(
                metadata, health, _STATUS_UNAVAILABLE, codes, _null_metrics()
            )

        # 2. trade_date 不匹配 → partial, metrics=null
        if health["trade_date_match"] is False:
            codes.add("SOURCE_PARTIAL")
            codes.add("TRADE_DATE_MISMATCH")
            return _build_envelope(
                metadata, health, _STATUS_PARTIAL, codes, _null_metrics()
            )

        # 3. 池为空或无合法记录的处理
        if not valid_rows:
            if (
                pool_is_list
                and raw_pool_len == 0
                and health["legal_zero"]
                and health["row_count"] == 0
            ):
                # 合法零值
                metrics = _legal_zero_metrics()
            elif (
                pool_is_list
                and raw_pool_len == 0
                and health["unexplained_empty"]
            ):
                # 未解释空集合
                codes.add("SOURCE_PARTIAL")
                codes.add("UNEXPLAINED_EMPTY")
                return _build_envelope(
                    metadata, health, _STATUS_PARTIAL, codes, _null_metrics()
                )
            else:
                # 普通空池或全部记录非法或 pool 非 list
                codes.add("SOURCE_UNAVAILABLE")
                codes.add("LIMIT_UP_POOL_UNAVAILABLE")
                return _build_envelope(
                    metadata, health, _STATUS_UNAVAILABLE, codes, _null_metrics()
                )
        else:
            # 4. 有合法记录 → 计算指标
            metrics = _compute_metrics(valid_rows)

        # 5. coverage / row_count 检查（对合法零值和有合法记录均适用）
        if health["coverage_warning"]:
            codes.add("PARTIAL_COVERAGE")
        if pool_is_list and _row_count_mismatch(health, raw_pool_len):
            codes.add("PARTIAL_COVERAGE")

        # 6. 确定最终状态
        if codes:
            codes.add("SOURCE_PARTIAL")
            return _build_envelope(
                metadata, health, _STATUS_PARTIAL, codes, metrics
            )

        return _build_envelope(
            metadata, health, _STATUS_NORMAL, codes, metrics
        )
    except Exception:
        return _fallback_envelope()
