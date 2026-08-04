"""BK-11 layered-promotion coverage eligibility gate v0.1。

纯离线、纯确定性、无网络、无文件读写、无数据库、无缓存、无行情计算、
无生产接入。只消费 Slice 2F final-snapshot producer 的 previous/current
结果，判断 coverage 是否足以进入未来计算阶段。

本模块不计算、接收或透传任何晋级率：``layered_promotion_rates`` 在所有
路径均为 null；``implementation_allowed`` 恒为 false。

公开 API
--------
``evaluate_layered_promotion_coverage(previous_result, current_result) -> dict``

普通异常结构化失败为 ``status=invalid`` 且 ``rates_policy=must_be_null``；
``KeyboardInterrupt`` / ``SystemExit`` / ``GeneratorExit`` 自然传播。
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

__all__ = [
    "SCHEMA_VERSION",
    "FINAL_SNAPSHOT_SCHEMA_VERSION",
    "evaluate_layered_promotion_coverage",
]

SCHEMA_VERSION = "short-term-layered-promotion-coverage-gate-v0.1"
FINAL_SNAPSHOT_SCHEMA_VERSION = "short-term-limit-up-final-snapshot-v0.1"
_ADAPTER_SCHEMA_VERSION = "short-term-limit-up-pool-adapter-v0.1"
_FINALITY_BASIS = "three_identical_normal_observations"

# 固定 gate reason-code 集合与顺序（upstream producer reason code 不得透传）
_REASON_CODE_ORDER: tuple[str, ...] = (
    "PREVIOUS_INPUT_INVALID",
    "CURRENT_INPUT_INVALID",
    "DATE_ORDER_INVALID",
    "PREVIOUS_SOURCE_UNAVAILABLE",
    "CURRENT_SOURCE_UNAVAILABLE",
    "PREVIOUS_SOURCE_PARTIAL",
    "CURRENT_SOURCE_PARTIAL",
    "RATE_OUTPUT_SUPPRESSED",
)
_REASON_CODE_SET = frozenset(_REASON_CODE_ORDER)

_PRODUCER_FIELDS = frozenset({
    "schema_version",
    "requested_trade_date",
    "observed_at",
    "status",
    "reason_codes",
    "session",
    "is_final",
    "finality_basis",
    "required_observations",
    "completed_observations",
    "stable_observation_count",
    "observation_interval_seconds",
    "required_stability_window_seconds",
    "actual_stability_window_seconds",
    "first_observation_monotonic",
    "last_observation_monotonic",
    "snapshot",
    "warnings",
})
_ADAPTER_FIELDS = frozenset({
    "schema_version",
    "source_id",
    "endpoint",
    "requested_trade_date",
    "observed_at",
    "status",
    "reason_codes",
    "rows",
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
    "target_universe_empty_after_filter",
    "source_pool_row_count",
    "http_status",
    "error_class",
    "excluded_universe_count",
    "invalid_row_count",
    "duplicate_code_count",
})
_STRICT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SIX_DIGIT_RE = re.compile(r"^\d{6}$")
_STABILITY_EPSILON = 1e-9


def _normalize_reason_codes(codes: list[str]) -> list[str]:
    """去重、固定顺序；未知 reason code 丢弃（不得进入输出）。"""
    seen: set[str] = set()
    out: list[str] = []
    for code in _REASON_CODE_ORDER:
        if code in codes and code not in seen:
            out.append(code)
            seen.add(code)
    return out


def _strict_parse_date(value: Any) -> Optional[date]:
    if type(value) is not str or _STRICT_DATE_RE.match(value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_utc_iso(value: Any) -> Optional[datetime]:
    if type(value) is not str or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        return None
    return dt


def _is_strict_json_value(value: Any) -> bool:
    """严格 JSON 树类型：只接受精确内建类型（拒绝子类与 NaN/Infinity）。"""
    if value is None:
        return True
    if type(value) is bool:
        return True
    if type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is str:
        return True
    if type(value) is list:
        return all(_is_strict_json_value(item) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _is_strict_json_value(val)
            for key, val in value.items()
        )
    return False


def _extract_date(result: Any) -> Optional[str]:
    if type(result) is not dict:
        return None
    value = result.get("requested_trade_date")
    if _strict_parse_date(value) is None:
        return None
    return value


def _validate_producer_contract(result: Any) -> bool:
    """Slice 2F producer 顶层 18 字段合同 + 类型 + timing 关系。"""
    if type(result) is not dict or not _is_strict_json_value(result):
        return False
    if set(result.keys()) != _PRODUCER_FIELDS:
        return False
    if result.get("schema_version") != FINAL_SNAPSHOT_SCHEMA_VERSION:
        return False
    if _strict_parse_date(result.get("requested_trade_date")) is None:
        return False
    if _parse_utc_iso(result.get("observed_at")) is None:
        return False
    if result.get("status") not in ("normal", "partial", "unavailable"):
        return False
    reason_codes = result.get("reason_codes")
    if not isinstance(reason_codes, list) \
            or any(type(code) is not str for code in reason_codes):
        return False
    if result.get("session") not in ("final", "not_final"):
        return False
    if type(result.get("is_final")) is not bool:
        return False
    finality_basis = result.get("finality_basis")
    if finality_basis is not None and type(finality_basis) is not str:
        return False
    required = result.get("required_observations")
    if type(required) is not int or required <= 0:
        return False
    completed = result.get("completed_observations")
    if type(completed) is not int or completed < 0 or completed > required:
        return False
    stable = result.get("stable_observation_count")
    if type(stable) is not int or stable < 0 or stable > completed:
        return False
    interval = result.get("observation_interval_seconds")
    if type(interval) is not float or not math.isfinite(interval) or interval <= 0:
        return False
    required_window = result.get("required_stability_window_seconds")
    if type(required_window) is not float or not math.isfinite(required_window) \
            or required_window < 0:
        return False
    actual = result.get("actual_stability_window_seconds")
    if actual is not None and (type(actual) is not float or not math.isfinite(actual)):
        return False
    first = result.get("first_observation_monotonic")
    if first is not None and (type(first) is not float or not math.isfinite(first)):
        return False
    last = result.get("last_observation_monotonic")
    if last is not None and (type(last) is not float or not math.isfinite(last)):
        return False
    snapshot = result.get("snapshot")
    if snapshot is not None and type(snapshot) is not dict:
        return False
    warnings = result.get("warnings")
    if not isinstance(warnings, list) \
            or any(type(warning) is not str for warning in warnings):
        return False
    # timing 关系
    if first is not None or last is not None:
        if first is None or last is None:
            return False
        if first > last:
            return False
        if actual is None or actual != last - first:
            return False
    else:
        if actual is not None:
            return False
    return True


def _validate_adapter_row(row: Any) -> bool:
    if type(row) is not dict or set(row.keys()) != {"stock_code", "lbc"}:
        return False
    code = row.get("stock_code")
    lbc = row.get("lbc")
    if type(code) is not str or _SIX_DIGIT_RE.match(code) is None:
        return False
    if type(lbc) is not int or lbc <= 0:
        return False
    return True


def _validate_nested_adapter(snapshot: dict, outer_date: str) -> bool:
    """complete 侧的 nested pool-adapter v0.1 完整合同。"""
    if type(snapshot) is not dict or set(snapshot.keys()) != _ADAPTER_FIELDS:
        return False
    if snapshot.get("schema_version") != _ADAPTER_SCHEMA_VERSION:
        return False
    if snapshot.get("requested_trade_date") != outer_date:
        return False
    if snapshot.get("status") != "normal" or snapshot.get("reason_codes") != []:
        return False
    for key in ("transport_success", "parse_success", "required_field_present",
                "data_array_present", "trade_date_match"):
        if snapshot.get(key) is not True:
            return False
    for key in ("coverage_warning", "upstream_null", "unexplained_empty",
                "legal_zero"):
        if snapshot.get(key) is not False:
            return False
    if snapshot.get("invalid_row_count") != 0:
        return False
    if snapshot.get("duplicate_code_count") != 0:
        return False
    if snapshot.get("error_class") != "NONE":
        return False
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        return False
    seen: set[str] = set()
    prev_code: Optional[str] = None
    for row in rows:
        if not _validate_adapter_row(row):
            return False
        code = row["stock_code"]
        if code in seen:
            return False
        if prev_code is not None and code < prev_code:
            return False
        seen.add(code)
        prev_code = code
    row_count = snapshot.get("row_count")
    if type(row_count) is not int or row_count < 0 or row_count != len(rows):
        return False
    source_count = snapshot.get("source_pool_row_count")
    if type(source_count) is not int or source_count < 0:
        return False
    excluded = snapshot.get("excluded_universe_count")
    if type(excluded) is not int or excluded < 0:
        return False
    if source_count != row_count + excluded:
        return False
    target_empty = snapshot.get("target_universe_empty_after_filter")
    if rows:
        if target_empty is not False:
            return False
    else:
        if source_count <= 0 or excluded != source_count or target_empty is not True:
            return False
    return True


def _is_complete_side(result: dict) -> bool:
    """complete 侧合同：finality 不变量 + nested adapter 完整覆盖。"""
    if result.get("status") != "normal" or result.get("reason_codes") != []:
        return False
    if result.get("session") != "final" or result.get("is_final") is not True:
        return False
    if result.get("finality_basis") != _FINALITY_BASIS:
        return False
    if result.get("required_observations") != 3:
        return False
    if result.get("completed_observations") != 3:
        return False
    if result.get("stable_observation_count") != 3:
        return False
    first = result.get("first_observation_monotonic")
    last = result.get("last_observation_monotonic")
    actual = result.get("actual_stability_window_seconds")
    required_window = result.get("required_stability_window_seconds")
    if first is None or last is None or actual is None:
        return False
    if actual + _STABILITY_EPSILON < required_window:
        return False
    snapshot = result.get("snapshot")
    if type(snapshot) is not dict:
        return False
    if result.get("warnings") != []:
        return False
    if not _validate_nested_adapter(snapshot, result["requested_trade_date"]):
        return False
    return True


def _is_partial_shape(result: dict) -> bool:
    if result.get("status") != "partial":
        return False
    if result.get("session") != "not_final":
        return False
    if result.get("is_final") is not False:
        return False
    if result.get("finality_basis") is not None:
        return False
    if result.get("snapshot") is not None:
        return False
    reason_codes = result.get("reason_codes")
    if not isinstance(reason_codes, list) or not reason_codes:
        return False
    if "SOURCE_PARTIAL" not in reason_codes:
        return False
    if any(type(code) is not str for code in reason_codes):
        return False
    if not isinstance(result.get("warnings"), list):
        return False
    return True


def _is_unavailable_shape(result: dict) -> bool:
    if result.get("status") != "unavailable":
        return False
    if result.get("session") != "not_final":
        return False
    if result.get("is_final") is not False:
        return False
    if result.get("finality_basis") is not None:
        return False
    if result.get("snapshot") is not None:
        return False
    reason_codes = result.get("reason_codes")
    if not isinstance(reason_codes, list) or not reason_codes:
        return False
    if any(type(code) is not str or not code for code in reason_codes):
        return False
    if len(set(reason_codes)) != len(reason_codes):
        return False
    if not isinstance(result.get("warnings"), list):
        return False
    return True


def _classify_side(result: Any, side: str) -> tuple[str, str]:
    """返回 (state, gate_reason_code)。state: complete/partial/unavailable/invalid。"""
    invalid_code = (
        "PREVIOUS_INPUT_INVALID" if side == "previous" else "CURRENT_INPUT_INVALID"
    )
    if not _validate_producer_contract(result):
        return "invalid", invalid_code
    status = result.get("status")
    if status == "partial":
        if not _is_partial_shape(result):
            return "invalid", invalid_code
        return "partial", (
            "PREVIOUS_SOURCE_PARTIAL" if side == "previous"
            else "CURRENT_SOURCE_PARTIAL")
    if status == "unavailable":
        if not _is_unavailable_shape(result):
            return "invalid", invalid_code
        return "unavailable", (
            "PREVIOUS_SOURCE_UNAVAILABLE" if side == "previous"
            else "CURRENT_SOURCE_UNAVAILABLE")
    # status == normal：必须为 complete，否则 input invalid
    if not _is_complete_side(result):
        return "invalid", invalid_code
    return "complete", ""


def _output(
    *,
    previous_date: Optional[str],
    current_date: Optional[str],
    previous_state: str,
    current_state: str,
    status: str,
    reason_codes: list[str],
) -> dict:
    normalized = _normalize_reason_codes(reason_codes)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason_codes": normalized,
        "coverage_eligible": status == "complete",
        "rates_policy": "not_computed" if status == "complete" else "must_be_null",
        "layered_promotion_rates": None,
        "previous_trade_date": previous_date,
        "current_trade_date": current_date,
        "previous_state": previous_state,
        "current_state": current_state,
        "implementation_allowed": False,
        "warnings": [],
    }


def evaluate_layered_promotion_coverage(
    previous_result: dict,
    current_result: dict,
) -> dict:
    """评估 previous/current final-snapshot 的 coverage 是否足以进入未来计算。

    不计算、接收或透传任何晋级率。普通异常结构化失败；
    KeyboardInterrupt / SystemExit / GeneratorExit 自然传播。
    """
    try:
        return _evaluate(previous_result, current_result)
    except Exception:
        return _output(
            previous_date=None,
            current_date=None,
            previous_state="invalid",
            current_state="invalid",
            status="invalid",
            reason_codes=[
                "PREVIOUS_INPUT_INVALID", "CURRENT_INPUT_INVALID",
                "RATE_OUTPUT_SUPPRESSED",
            ],
        )


def _evaluate(previous_result: Any, current_result: Any) -> dict:
    prev_state, prev_code = _classify_side(previous_result, "previous")
    curr_state, curr_code = _classify_side(current_result, "current")
    prev_date = _extract_date(previous_result)
    curr_date = _extract_date(current_result)

    codes: list[str] = []
    if prev_state == "invalid" or curr_state == "invalid":
        status = "invalid"
        if prev_state == "invalid":
            codes.append(prev_code)
        if curr_state == "invalid":
            codes.append(curr_code)
    else:
        # 日期先后关系（两侧结构有效后）
        if prev_date is None or curr_date is None or not (prev_date < curr_date):
            status = "invalid"
            codes.append("DATE_ORDER_INVALID")
        elif prev_state == "unavailable" or curr_state == "unavailable":
            status = "unavailable"
            if prev_state == "unavailable":
                codes.append(prev_code)
            if curr_state == "unavailable":
                codes.append(curr_code)
        elif prev_state == "partial" or curr_state == "partial":
            status = "partial"
            if prev_state == "partial":
                codes.append(prev_code)
            if curr_state == "partial":
                codes.append(curr_code)
        else:
            status = "complete"
            codes = []

    if status != "complete":
        codes.append("RATE_OUTPUT_SUPPRESSED")

    return _output(
        previous_date=prev_date,
        current_date=curr_date,
        previous_state=prev_state,
        current_state=curr_state,
        status=status,
        reason_codes=codes,
    )
