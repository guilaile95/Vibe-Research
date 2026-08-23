"""BK-11 Slice 2K 日事实组合层 v0.1。

基于已批准的 Slice 2F final-snapshot producer envelope 与 Slice 1
市场事实输入组件（breadth / limit_activity / facts_data_health），
编排三个已批准纯计算器：

    compute_limit_up_ladder           (Slice 2A)
    compute_ladder_gap                (Slice 2J)
    compute_short_term_market_facts   (Slice 1)

输出 ``short-term-daily-facts-v0.1`` envelope：sections 精确包含
``facts`` / ``ladder`` / ``gap`` 三个已批准 envelope，顶层提供组合
状态、组合 reason codes 与 producer 元数据（单日权威）。

本模块不计算 layered_promotion_rates；不验证 consecutive lbc 来源
语义（adapter ``lbc`` -> ladder ``consecutive_limit_up_days`` 仅为
机械字段映射）；不评估 legal zero 正向来源；不接入生产页面。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import short_term_ladder_gap
import short_term_limit_up_ladder
import short_term_market_facts

__all__ = [
    "SCHEMA_VERSION",
    "compute_daily_facts",
]

SCHEMA_VERSION = "short-term-daily-facts-v0.1"
PRODUCER_SCHEMA_VERSION = "short-term-limit-up-final-snapshot-v0.1"
ADAPTER_SCHEMA_VERSION = "short-term-limit-up-pool-adapter-v0.2"

# 固定组合 reason-code 顺序（gate 层专属；上游码保留在各 section envelope 内）
_REASON_ORDER: Tuple[str, ...] = (
    "INPUT_CONTRACT_INVALID",
    "PRODUCER_CONTRACT_INVALID",
    "UPSTREAM_LADDER_UNAVAILABLE",
    "UPSTREAM_LADDER_PARTIAL",
    "OUTPUT_SUPPRESSED",
)

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

# 2F producer envelope 的 session 词表（final / not_final）
_PRODUCER_SESSIONS = frozenset({"final", "not_final"})

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SIX_DIGIT_RE = re.compile(r"^\d{6}$")
_ZT_STAT_RE = re.compile(r"^(?P<days>[1-9]\d*)/(?P<count>[1-9]\d*)$")

_INPUT_FIELDS: Tuple[str, ...] = (
    "final_snapshot",
    "breadth",
    "limit_activity",
    "facts_data_health",
)

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

_ADAPTER_SOURCE_ID = "eastmoney_getTopicZTPool"
_ADAPTER_ENDPOINT = "getTopicZTPool"
_FINALITY_BASIS = "three_identical_normal_observations"
_REQUIRED_OBSERVATIONS = 3
_OBSERVATION_INTERVAL_SECONDS = 2.2
_REQUIRED_STABILITY_WINDOW_SECONDS = 4.4
_STABILITY_EPSILON = 1e-9

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


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_utc(value: str) -> Optional[datetime]:
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _valid_utc_timestamp(value: Any) -> bool:
    if value is None:
        return True
    if type(value) is not str:
        return False
    if value != value.strip():
        return False
    parsed = _parse_utc(value)
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    return parsed.utcoffset().total_seconds() == 0


def _valid_trade_date(value: Any) -> bool:
    if type(value) is not str or _TRADE_DATE_RE.match(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_string_list(value: Any) -> bool:
    if type(value) is not list:
        return False
    return all(type(item) is str and item for item in value)


def _validate_metadata(envelope: Dict[str, Any]) -> bool:
    if not _valid_trade_date(envelope.get("trade_date")):
        return False
    session = envelope.get("session")
    if type(session) is not str or session not in _ALLOWED_SESSIONS:
        return False
    is_final = envelope.get("is_final")
    if type(is_final) is not bool or is_final != (session == "final"):
        return False
    if not _valid_string_list(envelope.get("source_ids")):
        return False
    fetched_at = envelope.get("fetched_at")
    snapshot_at = envelope.get("snapshot_at")
    if not _valid_utc_timestamp(fetched_at):
        return False
    if not _valid_utc_timestamp(snapshot_at):
        return False
    if fetched_at is not None and snapshot_at is not None:
        left = _parse_utc(fetched_at)
        right = _parse_utc(snapshot_at)
        if left is not None and right is not None and left > right:
            return False
    return True


def _valid_zt_stat(value: Any) -> bool:
    if value is None:
        return True
    if type(value) is not str:
        return False
    match = _ZT_STAT_RE.fullmatch(value)
    return match is not None and int(match.group("days")) >= int(match.group("count"))


def _validate_nested_adapter(snapshot: Dict[str, Any], outer_date: str) -> bool:
    if type(snapshot) is not dict or set(snapshot.keys()) != _ADAPTER_FIELDS:
        return False
    if snapshot.get("schema_version") != ADAPTER_SCHEMA_VERSION:
        return False
    if snapshot.get("source_id") != _ADAPTER_SOURCE_ID:
        return False
    if snapshot.get("endpoint") != _ADAPTER_ENDPOINT:
        return False
    if snapshot.get("requested_trade_date") != outer_date:
        return False
    if snapshot.get("status") != "normal":
        return False
    reason_codes = snapshot.get("reason_codes")
    if type(reason_codes) is not list or reason_codes != []:
        return False
    observed_at = snapshot.get("observed_at")
    if observed_at is None or not _valid_utc_timestamp(observed_at):
        return False
    http_status = snapshot.get("http_status")
    if http_status is not None and (
            type(http_status) is not int or http_status < 100
            or http_status > 599):
        return False
    for key in _DATA_HEALTH_BOOL_FIELDS:
        if type(snapshot.get(key)) is not bool:
            return False
    for key in ("transport_success", "parse_success", "required_field_present",
                "data_array_present", "trade_date_match"):
        if snapshot.get(key) is not True:
            return False
    for key in ("coverage_warning", "upstream_null", "unexplained_empty",
                "legal_zero"):
        if snapshot.get(key) is not False:
            return False
    if type(snapshot.get("invalid_row_count")) is not int \
            or snapshot.get("invalid_row_count") != 0:
        return False
    if type(snapshot.get("duplicate_code_count")) is not int \
            or snapshot.get("duplicate_code_count") != 0:
        return False
    if type(snapshot.get("error_class")) is not str \
            or snapshot.get("error_class") != "NONE":
        return False
    rows = snapshot.get("rows")
    if type(rows) is not list:
        return False
    seen: set = set()
    prev_code: Optional[str] = None
    for row in rows:
        if type(row) is not dict or set(row.keys()) not in (
            {"stock_code", "lbc"}, {"stock_code", "lbc", "zt_stat"}
        ):
            return False
        code = row.get("stock_code")
        lbc = row.get("lbc")
        zt_stat = row.get("zt_stat")
        if type(code) is not str or _SIX_DIGIT_RE.match(code) is None:
            return False
        if not _is_strict_int(lbc) or lbc <= 0 or not _valid_zt_stat(zt_stat):
            return False
        if code in seen:
            return False
        if prev_code is not None and code < prev_code:
            return False
        seen.add(code)
        prev_code = code
    row_count = snapshot.get("row_count")
    if not _is_strict_int(row_count) or row_count < 0 \
            or row_count != len(rows):
        return False
    source_count = snapshot.get("source_pool_row_count")
    if not _is_strict_int(source_count) or source_count < 0:
        return False
    excluded = snapshot.get("excluded_universe_count")
    if not _is_strict_int(excluded) or excluded < 0:
        return False
    if source_count != row_count + excluded:
        return False
    target_empty = snapshot.get("target_universe_empty_after_filter")
    if type(target_empty) is not bool:
        return False
    if rows:
        if target_empty is not False:
            return False
    else:
        if source_count <= 0 or excluded != source_count \
                or target_empty is not True:
            return False
    return True


def _validate_producer(envelope: Any) -> Optional[Dict[str, Any]]:
    """producer envelope 基本合同 + 元数据 + status 形状。

    返回 {"status", "metadata"}；合同非法返回 None。
    metadata 仅在 producer 合法时有效。
    """
    if type(envelope) is not dict or set(envelope.keys()) != _PRODUCER_FIELDS:
        return None
    if envelope.get("schema_version") != PRODUCER_SCHEMA_VERSION:
        return None
    trade_date = envelope.get("requested_trade_date")
    if not _valid_trade_date(trade_date):
        return None
    observed_at = envelope.get("observed_at")
    if observed_at is None or not _valid_utc_timestamp(observed_at):
        return None
    status = envelope.get("status")
    if status not in ("normal", "partial", "unavailable"):
        return None
    reason_codes = envelope.get("reason_codes")
    if not _valid_string_list(reason_codes):
        return None
    session = envelope.get("session")
    if type(session) is not str or session not in _PRODUCER_SESSIONS:
        return None
    is_final = envelope.get("is_final")
    if type(is_final) is not bool or is_final != (session == "final"):
        return None
    finality_basis = envelope.get("finality_basis")
    if finality_basis is not None and type(finality_basis) is not str:
        return None
    required = envelope.get("required_observations")
    if not _is_strict_int(required) or required <= 0:
        return None
    completed = envelope.get("completed_observations")
    if not _is_strict_int(completed) or completed < 0 or completed > required:
        return None
    stable = envelope.get("stable_observation_count")
    if not _is_strict_int(stable) or stable < 0 or stable > completed:
        return None
    interval = envelope.get("observation_interval_seconds")
    if type(interval) is not float or not (interval > 0):
        return None
    required_window = envelope.get("required_stability_window_seconds")
    if type(required_window) is not float or required_window < 0:
        return None
    actual = envelope.get("actual_stability_window_seconds")
    if actual is not None and type(actual) is not float:
        return None
    first = envelope.get("first_observation_monotonic")
    if first is not None and type(first) is not float:
        return None
    last = envelope.get("last_observation_monotonic")
    if last is not None and type(last) is not float:
        return None
    if (first is None) != (last is None):
        return None
    if first is not None and last is not None:
        if first > last:
            return None
        if actual is None or actual != last - first:
            return None
    else:
        if actual is not None:
            return None
    snapshot = envelope.get("snapshot")
    if snapshot is not None and type(snapshot) is not dict:
        return None
    if status in ("partial", "unavailable"):
        if snapshot is not None:
            return None
        if not reason_codes:
            return None
    warnings = envelope.get("warnings")
    if not _valid_string_list(warnings):
        return None
    return {
        "status": status,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "metadata": {
            "trade_date": trade_date,
            # 组合词表映射：producer "final" -> "final"；
            # "not_final" -> "unavailable"（保留在 source_status/session 语义，
            # 信息不丢失；避免把 2F 词表泄漏进组合 envelope）
            "session": "final" if session == "final" else "unavailable",
            "is_final": is_final,
            "source_ids": (
                [_ADAPTER_SOURCE_ID] if snapshot is not None else []
            ),
            "fetched_at": envelope.get("observed_at"),
            "snapshot_at": envelope.get("observed_at"),
        },
        "snapshot": snapshot,
        "observed_at": envelope.get("observed_at"),
        "first": first,
        "last": last,
        "actual": actual,
    }


def _is_producer_complete(producer: Dict[str, Any]) -> bool:
    """normal 状态 complete-side 不变量（对齐 Slice 2H 合同）。"""
    envelope = producer["_envelope"]
    if envelope.get("status") != "normal" or envelope.get("reason_codes") != []:
        return False
    if envelope.get("session") != "final" or envelope.get("is_final") is not True:
        return False
    if envelope.get("finality_basis") != _FINALITY_BASIS:
        return False
    if envelope.get("required_observations") != _REQUIRED_OBSERVATIONS:
        return False
    if envelope.get("completed_observations") != _REQUIRED_OBSERVATIONS:
        return False
    if envelope.get("stable_observation_count") != _REQUIRED_OBSERVATIONS:
        return False
    if envelope.get("observation_interval_seconds") \
            != _OBSERVATION_INTERVAL_SECONDS:
        return False
    if envelope.get("required_stability_window_seconds") \
            != _REQUIRED_STABILITY_WINDOW_SECONDS:
        return False
    first = envelope.get("first_observation_monotonic")
    last = envelope.get("last_observation_monotonic")
    actual = envelope.get("actual_stability_window_seconds")
    if first is None or last is None or actual is None:
        return False
    if actual + _STABILITY_EPSILON < _REQUIRED_STABILITY_WINDOW_SECONDS:
        return False
    if envelope.get("warnings") != []:
        return False
    return True


def _build_ladder_snapshot(producer: Dict[str, Any]) -> Dict[str, Any]:
    """把 complete producer 转换为 Slice 2A 规范化 snapshot。"""
    adapter = producer["snapshot"]
    health = {name: adapter.get(name) for name in _DATA_HEALTH_BOOL_FIELDS}
    health["row_count"] = adapter.get("row_count")
    return {
        "trade_date": producer["metadata"]["trade_date"],
        "session": producer["metadata"]["session"],
        "is_final": producer["metadata"]["is_final"],
        "source_ids": [adapter.get("source_id")],
        "fetched_at": adapter.get("observed_at"),
        "snapshot_at": producer["observed_at"],
        "data_health": health,
        "limit_up_pool": [
            {
                "stock_code": row["stock_code"],
                "consecutive_limit_up_days": row["lbc"],
                "zt_stat": row.get("zt_stat"),
            }
            for row in adapter["rows"]
        ],
    }


def _build_facts_snapshot(
    producer: Dict[str, Any],
    breadth: Any,
    limit_activity: Any,
    facts_data_health: Any,
) -> Dict[str, Any]:
    return {
        "trade_date": producer["metadata"]["trade_date"],
        "session": producer["metadata"]["session"],
        "is_final": producer["metadata"]["is_final"],
        "source_ids": list(producer["metadata"]["source_ids"]),
        "fetched_at": producer["metadata"]["fetched_at"],
        "snapshot_at": producer["metadata"]["snapshot_at"],
        "data_health": facts_data_health,
        "breadth": breadth,
        "limit_activity": limit_activity,
    }


_STATUS_RANK = {"normal": 0, "partial": 1, "unavailable": 2, "invalid": 3}


def _worst_status(statuses: List[str]) -> str:
    return max(statuses, key=lambda s: _STATUS_RANK[s])


def _compose_reason_codes(producer_status: str, section_statuses: List[str]) -> List[str]:
    codes: List[str] = []
    if producer_status == "unavailable":
        codes.append("UPSTREAM_LADDER_UNAVAILABLE")
    elif producer_status == "partial":
        codes.append("UPSTREAM_LADDER_PARTIAL")
    if producer_status != "normal" or any(
            status != "normal" for status in section_statuses):
        codes.append("OUTPUT_SUPPRESSED")
    return codes


def _fixed_limitations() -> List[str]:
    return [
        "composed from approved BK-11 pure calculators",
        "does not validate upstream consecutive-limit-up semantics",
        "does not compute layered promotion rates",
        "production integration not authorized",
    ]


def _null_sections() -> Dict[str, Any]:
    return {"facts": None, "ladder": None, "gap": None}


def _normal_envelope(
    metadata: Dict[str, Any],
    status: str,
    reason_codes: List[str],
    source_status: str,
    source_reason_codes: List[str],
    sections: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": metadata["trade_date"],
        "session": metadata["session"],
        "is_final": metadata["is_final"],
        "source_ids": list(metadata["source_ids"]),
        "fetched_at": metadata["fetched_at"],
        "snapshot_at": metadata["snapshot_at"],
        "status": status,
        "reason_codes": reason_codes,
        "warnings": [],
        "limitations": _fixed_limitations(),
        "source_schema_version": PRODUCER_SCHEMA_VERSION,
        "source_status": source_status,
        "source_reason_codes": list(source_reason_codes),
        "sections": sections,
    }


def _invalid_envelope(reason_code: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": None,
        "session": "unavailable",
        "is_final": False,
        "source_ids": [],
        "fetched_at": None,
        "snapshot_at": None,
        "status": "invalid",
        "reason_codes": [reason_code, "OUTPUT_SUPPRESSED"],
        "warnings": [],
        "limitations": _fixed_limitations(),
        "source_schema_version": None,
        "source_status": None,
        "source_reason_codes": [],
        "sections": _null_sections(),
    }


def _evaluate(input_envelope: Any) -> Dict[str, Any]:
    if type(input_envelope) is not dict:
        return _invalid_envelope("INPUT_CONTRACT_INVALID")
    for field in _INPUT_FIELDS:
        if field not in input_envelope:
            return _invalid_envelope("INPUT_CONTRACT_INVALID")

    producer_envelope = input_envelope["final_snapshot"]
    producer = _validate_producer(producer_envelope)
    if producer is None:
        return _invalid_envelope("PRODUCER_CONTRACT_INVALID")
    producer_status = producer["status"]

    # producer 元数据为单日权威（fetched/snapshot 时间取自 producer 观测）
    if not _validate_metadata(producer["metadata"]):
        return _invalid_envelope("PRODUCER_CONTRACT_INVALID")

    # facts section：独立于 producer 状态，始终计算
    facts_snapshot = _build_facts_snapshot(
        producer,
        input_envelope["breadth"],
        input_envelope["limit_activity"],
        input_envelope["facts_data_health"],
    )
    facts_envelope = short_term_market_facts.compute_short_term_market_facts(
        facts_snapshot)

    # ladder / gap sections：仅 producer normal（complete-side）时计算
    ladder_envelope = None
    gap_envelope = None
    if producer_status == "normal":
        producer["_envelope"] = producer_envelope
        if not _is_producer_complete(producer):
            return _invalid_envelope("PRODUCER_CONTRACT_INVALID")
        adapter = producer["snapshot"]
        if type(adapter) is not dict or not _validate_nested_adapter(
                adapter, producer_envelope.get("requested_trade_date")):
            return _invalid_envelope("PRODUCER_CONTRACT_INVALID")
        ladder_snapshot = _build_ladder_snapshot(producer)
        ladder_envelope = short_term_limit_up_ladder.compute_limit_up_ladder(
            ladder_snapshot)
        gap_envelope = short_term_ladder_gap.compute_ladder_gap(
            ladder_envelope)

    section_statuses = [facts_envelope["status"]]
    if ladder_envelope is not None:
        section_statuses.append(ladder_envelope["status"])
    if gap_envelope is not None:
        section_statuses.append(gap_envelope["status"])
    if producer_status != "normal":
        section_statuses.append(producer_status)

    status = _worst_status(section_statuses)
    reason_codes = _compose_reason_codes(
        producer_status,
        [facts_envelope["status"]]
        + ([ladder_envelope["status"]] if ladder_envelope is not None else [])
        + ([gap_envelope["status"]] if gap_envelope is not None else []),
    )
    if status == "normal":
        reason_codes = []

    return _normal_envelope(
        metadata=producer["metadata"],
        status=status,
        reason_codes=reason_codes,
        source_status=producer_status,
        source_reason_codes=producer["reason_codes"],
        sections={
            "facts": facts_envelope,
            "ladder": ladder_envelope,
            "gap": gap_envelope,
        },
    )


def compute_daily_facts(input_envelope: dict) -> dict:
    """计算日事实组合 envelope（Slice 2K 范围），永不抛异常。

    输入为组合 dict（final_snapshot + breadth + limit_activity +
    facts_data_health）。纯计算，不修改输入。普通异常返回固定
    invalid envelope（不调用任何业务 helper、不包含异常文本）；
    KeyboardInterrupt / SystemExit / GeneratorExit 自然传播。
    """
    try:
        return _evaluate(input_envelope)
    except Exception:
        # emergency fail-closed envelope：直接构造完整固定字面量，
        # 不得调用任何业务 helper，不得读取输入对象与异常对象，
        # 不得依赖模块级可变模板。
        return {
            "schema_version": SCHEMA_VERSION,
            "trade_date": None,
            "session": "unavailable",
            "is_final": False,
            "source_ids": [],
            "fetched_at": None,
            "snapshot_at": None,
            "status": "invalid",
            "reason_codes": ["INPUT_CONTRACT_INVALID", "OUTPUT_SUPPRESSED"],
            "warnings": [],
            "limitations": [
                "composed from approved BK-11 pure calculators",
                "does not validate upstream consecutive-limit-up semantics",
                "does not compute layered promotion rates",
                "production integration not authorized",
            ],
            "source_schema_version": None,
            "source_status": None,
            "source_reason_codes": [],
            "sections": {
                "facts": None,
                "ladder": None,
                "gap": None,
            },
        }
