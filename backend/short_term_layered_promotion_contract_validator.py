"""BK-11 layered-promotion fixture、reason-code 与状态映射机械验证器 v0.1。

纯离线、纯确定性、无文件系统写入、无网络请求、无真实行情依赖、无缓存、
无数据库、无生产指标输出。只验证合成 fixture 与已批准合同是否一致。

本模块不得被应用入口、调度器、API 或生产决策链引用；不是生产
``layered_promotion_rates`` 实现。仅允许 Python 标准库。

公开 API
--------
``validate_layered_promotion_fixture(fixture: dict) -> dict``

返回的 dict 始终包含完整合同字段。普通异常结构化失败为 ``status=invalid``；
``KeyboardInterrupt`` / ``SystemExit`` / ``GeneratorExit`` 自然传播。
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "validate_layered_promotion_fixture",
]

SCHEMA_VERSION = "short-term-layered-promotion-contract-validator-v0.1"
FIXTURE_SCHEMA_VERSION = "bk11-layered-promotion-fixture.v0.1"

# 固定 issue-code 集合与顺序（未知 code 不得输出）
_ISSUE_CODE_ORDER: tuple[str, ...] = (
    "FIXTURE_NOT_DICT",
    "FIXTURE_SCHEMA_INVALID",
    "TOP_LEVEL_FIELD_INVALID",
    "MARKET_SCOPE_INVALID",
    "CODE_PREFIX_CONTRACT_INVALID",
    "CASE_SET_INVALID",
    "DUPLICATE_CASE_ID",
    "CASE_SCHEMA_INVALID",
    "SNAPSHOT_SCHEMA_INVALID",
    "DATA_HEALTH_INVALID",
    "POOL_ROW_INVALID",
    "EXPECTED_SCHEMA_INVALID",
    "EXPECTED_STATUS_INVALID",
    "REASON_CODE_INVALID",
    "REASON_CODE_ORDER_INVALID",
    "RATE_SCHEMA_INVALID",
    "RATE_CALCULATION_MISMATCH",
    "STATUS_MAPPING_MISMATCH",
)
_ISSUE_CODE_SET = frozenset(_ISSUE_CODE_ORDER)

# 固定 reason-code 集合与顺序（layered-promotion 映射层，v0.1 共 9 个）
_REASON_CODE_ORDER: tuple[str, ...] = (
    "SOURCE_UNAVAILABLE",
    "PREVIOUS_SNAPSHOT_UNAVAILABLE",
    "CURRENT_SNAPSHOT_UNAVAILABLE",
    "TRADING_CALENDAR_UNAVAILABLE",
    "TRADE_DATE_MISMATCH",
    "NOT_FINAL",
    "SOURCE_PARTIAL",
    "PARTIAL_COVERAGE",
    "UNEXPLAINED_EMPTY",
)
_REASON_CODE_SET = frozenset(_REASON_CODE_ORDER)

# code_prefix_contract 精确字段集合与固定值（消除模糊语义）
_CODE_PREFIX_CONTRACT_FIELDS = frozenset({
    "sh_main",
    "sz_main",
    "chinext",
    "star",
    "excluded_prefixes",
    "normalization",
    "note",
})
_CODE_PREFIX_EXACT_VALUES: dict[str, str] = {
    "sh_main": "60xxxx",
    "sz_main": "00xxxx",
    "chinext": "30xxxx",
    "star": "68xxxx",
    "normalization": (
        "trim → keep string → validate 6 digits "
        "→ accept only 60/00/30/68 prefixes"
    ),
    "note": (
        "前缀合同用于市场板块形状校验，不用于排除 ST/*ST。"
        "ST/*ST 使用相同的市场代码前缀。代码前缀仅为辅助校验；"
        "长期市场身份应由明确的目标交易所/universe 规则决定，"
        "不能只依赖前缀。"
    ),
}
_EXCLUDED_PREFIXES: list[str] = ["4xxxxx", "8xxxxx", "920xxx", "9xxxxx"]
# unavailable 组合时保留的具体原因（partial 码被 unavailable 覆盖）
_UNAVAILABLE_SPECIFIC_CODES = frozenset({
    "TRADING_CALENDAR_UNAVAILABLE",
    "TRADE_DATE_MISMATCH",
    "NOT_FINAL",
})

_CASE_IDS: tuple[str, ...] = (
    "normal",
    "zero_denominator",
    "previous_legal_zero",
    "current_legal_zero",
    "partial",
    "unavailable",
    "identity_edge",
)

_TOP_LEVEL_FIELDS = frozenset({
    "schema_version",
    "fixture_kind",
    "generated_at",
    "description",
    "trade_dates",
    "market_scope",
    "code_prefix_contract",
    "cases",
})
_CASE_REQUIRED_FIELDS = frozenset({
    "case_id",
    "case_name",
    "description",
    "previous_trade_date",
    "current_trade_date",
    "previous_snapshot",
    "current_snapshot",
    "expected",
})
_SNAPSHOT_FIELDS = frozenset({
    "trade_date",
    "session",
    "is_final",
    "source_ids",
    "fetched_at",
    "snapshot_at",
    "limit_up_pool",
    "data_health",
})
_DATA_HEALTH_FIELDS = frozenset({
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
})
_EXPECTED_FIELDS = frozenset({
    "status",
    "reason_codes",
    "warnings",
    "layered_promotion_rates",
})
_RATE_FIELDS = frozenset({
    "from_level",
    "to_level",
    "numerator",
    "denominator",
    "sample_count",
    "rate",
})
_DATA_HEALTH_BOOL_KEYS = (
    "transport_success",
    "parse_success",
    "required_field_present",
    "data_array_present",
    "legal_zero",
    "upstream_null",
    "unexplained_empty",
    "coverage_warning",
)

_INCLUDED_SCOPE = frozenset({
    "SH main", "SZ main", "ChiNext", "STAR", "ST", "*ST",
})
_EXCLUDED_SCOPE = frozenset({
    "BSE", "IPO no-limit period", "delisting period", "B shares",
    "ETF", "LOF", "convertible bonds", "funds", "indexes",
})
_CODE_PREFIXES = ("60", "00", "30", "68")
_STRICT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SIX_DIGIT_RE = re.compile(r"^\d{6}$")


def _normalize_issue_codes(codes: list[str]) -> list[str]:
    """去重、固定顺序；未知 issue code 丢弃（不得进入输出）。"""
    seen: set[str] = set()
    out: list[str] = []
    for code in _ISSUE_CODE_ORDER:
        if code in codes and code not in seen:
            out.append(code)
            seen.add(code)
    return out


def _normalize_reason_codes(codes: list[str]) -> list[str]:
    """去重、固定顺序；未知 reason code 丢弃（防御性）。"""
    seen: set[str] = set()
    out: list[str] = []
    for code in _REASON_CODE_ORDER:
        if code in codes and code not in seen:
            out.append(code)
            seen.add(code)
    return out


def _strict_parse_date(s: Any) -> Optional[date]:
    """严格 YYYY-MM-DD → date；无效返回 None。"""
    if type(s) is not str or _STRICT_DATE_RE.match(s) is None:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _is_strict_json_value(value: Any) -> bool:
    """严格 JSON 树类型校验：只接受精确内建类型，递归验证全部成员。

    拒绝：dict/list/str/int/float/bool 子类、tuple、set、bytes、complex、
    object()、NaN、Infinity、-Infinity、非 str dict key。
    """
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


def _parse_utc_iso(s: Any) -> Optional[datetime]:
    """可解析的带时区 UTC ISO 时间（offset 必须为零）。"""
    if type(s) is not str or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        return None
    return dt


def _output(
    fixture: Any,
    issue_codes: list[str],
    case_results: list[dict],
) -> dict:
    normalized = _normalize_issue_codes(issue_codes)
    fixture_schema: Optional[str] = None
    if isinstance(fixture, dict) and isinstance(fixture.get("schema_version"), str):
        fixture_schema = fixture.get("schema_version")
    return {
        "schema_version": SCHEMA_VERSION,
        "fixture_schema_version": fixture_schema,
        "status": "valid" if not normalized else "invalid",
        "issue_codes": normalized,
        "issue_count": len(normalized),
        "case_count": len(case_results),
        "validated_case_ids": [
            r["case_id"] for r in case_results if r["status"] == "valid"
        ],
        "case_results": case_results,
        "warnings": [],
    }


def _invalid_case(
    case_id: str,
    issue_codes: list[str],
    derived_status: Optional[str] = None,
    derived_reason_codes: Optional[list[str]] = None,
    derived_rates: Any = None,
) -> dict:
    return {
        "case_id": case_id,
        "status": "invalid",
        "issue_codes": _normalize_issue_codes(issue_codes),
        "derived_status": derived_status,
        "derived_reason_codes": derived_reason_codes,
        "derived_layered_promotion_rates": derived_rates,
    }


def _valid_case(
    case_id: str,
    derived_status: str,
    derived_reason_codes: list[str],
    derived_rates: Any,
) -> dict:
    return {
        "case_id": case_id,
        "status": "valid",
        "issue_codes": [],
        "derived_status": derived_status,
        "derived_reason_codes": derived_reason_codes,
        "derived_layered_promotion_rates": derived_rates,
    }


# ---------------------------------------------------------------------------
# market scope / code prefix
# ---------------------------------------------------------------------------

def _validate_market_scope(market_scope: Any, issues: list[str]) -> None:
    if not isinstance(market_scope, dict):
        issues.append("MARKET_SCOPE_INVALID")
        return
    included = market_scope.get("included")
    excluded = market_scope.get("excluded")
    if not isinstance(included, list) or not isinstance(excluded, list):
        issues.append("MARKET_SCOPE_INVALID")
        return
    if any(type(item) is not str or not item for item in included + excluded):
        issues.append("MARKET_SCOPE_INVALID")
    if set(included) != _INCLUDED_SCOPE or len(included) != len(set(included)):
        issues.append("MARKET_SCOPE_INVALID")
    if set(excluded) != _EXCLUDED_SCOPE or len(excluded) != len(set(excluded)):
        issues.append("MARKET_SCOPE_INVALID")


def _validate_code_prefix_contract(value: Any, issues: list[str]) -> None:
    if type(value) is not dict or set(value.keys()) != _CODE_PREFIX_CONTRACT_FIELDS:
        issues.append("CODE_PREFIX_CONTRACT_INVALID")
        return
    for key, expected in _CODE_PREFIX_EXACT_VALUES.items():
        if value.get(key) != expected:
            issues.append("CODE_PREFIX_CONTRACT_INVALID")
    if value.get("excluded_prefixes") != _EXCLUDED_PREFIXES:
        issues.append("CODE_PREFIX_CONTRACT_INVALID")


# ---------------------------------------------------------------------------
# snapshot / pool / data health / expected
# ---------------------------------------------------------------------------

def _validate_pool(pool: Any, issues: list[str]) -> bool:
    """行合同校验。返回 pool 是否整体有效（不静默修复）。"""
    if not isinstance(pool, list):
        issues.append("POOL_ROW_INVALID")
        return False
    valid = True
    seen: set[str] = set()
    prev_code: Optional[str] = None
    for row in pool:
        if not isinstance(row, dict) or set(row.keys()) != {
                "stock_code", "consecutive_limit_up_days"}:
            issues.append("POOL_ROW_INVALID")
            valid = False
            continue
        code = row.get("stock_code")
        days = row.get("consecutive_limit_up_days")
        if not isinstance(code, str) or _SIX_DIGIT_RE.match(code) is None \
                or not code.startswith(_CODE_PREFIXES):
            issues.append("POOL_ROW_INVALID")
            valid = False
            continue
        if isinstance(days, bool) or type(days) is not int or days <= 0:
            issues.append("POOL_ROW_INVALID")
            valid = False
            continue
        if code in seen:
            issues.append("POOL_ROW_INVALID")
            valid = False
            continue
        if prev_code is not None and code < prev_code:
            issues.append("POOL_ROW_INVALID")
            valid = False
            continue
        seen.add(code)
        prev_code = code
    return valid


def _validate_data_health(data_health: Any, pool: Any, issues: list[str]) -> bool:
    """data_health 十字段与基本不变量。返回是否有效。"""
    if not isinstance(data_health, dict):
        issues.append("DATA_HEALTH_INVALID")
        return False
    if set(data_health.keys()) != _DATA_HEALTH_FIELDS:
        issues.append("DATA_HEALTH_INVALID")
    for key in _DATA_HEALTH_BOOL_KEYS:
        if type(data_health.get(key)) is not bool:
            issues.append("DATA_HEALTH_INVALID")
    trade_date_match = data_health.get("trade_date_match")
    if trade_date_match is not True and trade_date_match is not False \
            and trade_date_match is not None:
        issues.append("DATA_HEALTH_INVALID")
    row_count = data_health.get("row_count")
    if type(row_count) is not int or row_count < 0:
        issues.append("DATA_HEALTH_INVALID")
    if data_health.get("legal_zero") is True \
            and data_health.get("unexplained_empty") is True:
        issues.append("DATA_HEALTH_INVALID")
    if isinstance(pool, list):
        if row_count != len(pool):
            issues.append("DATA_HEALTH_INVALID")
        if data_health.get("legal_zero") is True and row_count != 0:
            issues.append("DATA_HEALTH_INVALID")
        if data_health.get("unexplained_empty") is True and row_count != 0:
            issues.append("DATA_HEALTH_INVALID")
    return True


def _validate_snapshot(
    snapshot: Any,
    expected_trade_date: str,
    issues: list[str],
) -> bool:
    """snapshot 结构合同（不含业务状态判定）。返回是否整体有效。"""
    if type(snapshot) is not dict:
        issues.append("SNAPSHOT_SCHEMA_INVALID")
        return False
    if set(snapshot.keys()) != _SNAPSHOT_FIELDS:
        issues.append("SNAPSHOT_SCHEMA_INVALID")
    # trade_date 只做格式校验；与 case 日期的匹配属业务状态（TRADE_DATE_MISMATCH）
    if _strict_parse_date(snapshot.get("trade_date")) is None:
        issues.append("SNAPSHOT_SCHEMA_INVALID")
    session = snapshot.get("session")
    is_final = snapshot.get("is_final")
    if session not in ("final", "not_final"):
        issues.append("SNAPSHOT_SCHEMA_INVALID")
    if type(is_final) is not bool:
        issues.append("SNAPSHOT_SCHEMA_INVALID")
    if (session == "final") != (is_final is True):
        issues.append("SNAPSHOT_SCHEMA_INVALID")
    source_ids = snapshot.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids \
            or any(type(item) is not str for item in source_ids):
        issues.append("SNAPSHOT_SCHEMA_INVALID")
    fetched = _parse_utc_iso(snapshot.get("fetched_at"))
    snap_at = _parse_utc_iso(snapshot.get("snapshot_at"))
    if fetched is None or snap_at is None or fetched > snap_at:
        issues.append("SNAPSHOT_SCHEMA_INVALID")
    pool = snapshot.get("limit_up_pool")
    if not isinstance(pool, list):
        issues.append("SNAPSHOT_SCHEMA_INVALID")
    data_health = snapshot.get("data_health")
    _validate_data_health(data_health, pool, issues)
    _validate_pool(pool, issues)
    return True


def _validate_rate_item(item: Any) -> bool:
    """rate item 合同。返回是否有效。"""
    if not isinstance(item, dict) or set(item.keys()) != _RATE_FIELDS:
        return False
    from_level = item.get("from_level")
    to_level = item.get("to_level")
    numerator = item.get("numerator")
    denominator = item.get("denominator")
    sample_count = item.get("sample_count")
    rate = item.get("rate")
    if isinstance(from_level, bool) or type(from_level) is not int or from_level < 1:
        return False
    if isinstance(to_level, bool) or type(to_level) is not int \
            or to_level != from_level + 1:
        return False
    if isinstance(numerator, bool) or type(numerator) is not int or numerator < 0:
        return False
    if isinstance(denominator, bool) or type(denominator) is not int \
            or denominator <= 0:
        return False
    if isinstance(sample_count, bool) or type(sample_count) is not int \
            or sample_count != denominator:
        return False
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        return False
    if type(rate) is not float:
        return False
    rate_f = float(rate)
    if not math.isfinite(rate_f) or rate_f < 0.0 or rate_f > 1.0:
        return False
    if rate != round(numerator / denominator, 4):
        return False
    return True


def _validate_expected(expected: Any, issues: list[str]) -> bool:
    """expected 合同。返回是否整体有效。"""
    if not isinstance(expected, dict) or set(expected.keys()) != _EXPECTED_FIELDS:
        issues.append("EXPECTED_SCHEMA_INVALID")
        return False
    status = expected.get("status")
    if status not in ("normal", "partial", "unavailable"):
        issues.append("EXPECTED_STATUS_INVALID")
        return False
    reason_codes = expected.get("reason_codes")
    if not isinstance(reason_codes, list) \
            or any(type(code) is not str for code in reason_codes):
        issues.append("EXPECTED_SCHEMA_INVALID")
        return False
    for code in reason_codes:
        if code not in _REASON_CODE_SET:
            issues.append("REASON_CODE_INVALID")
    if len(set(reason_codes)) != len(reason_codes):
        issues.append("REASON_CODE_INVALID")
    fixed_indices = [
        _REASON_CODE_ORDER.index(code) for code in reason_codes
        if code in _REASON_CODE_SET
    ]
    if fixed_indices != sorted(fixed_indices):
        issues.append("REASON_CODE_ORDER_INVALID")
    warnings = expected.get("warnings")
    if not isinstance(warnings, list) \
            or any(type(warning) is not str for warning in warnings):
        issues.append("EXPECTED_SCHEMA_INVALID")
    rates = expected.get("layered_promotion_rates")
    if status == "normal":
        if not isinstance(rates, list):
            issues.append("EXPECTED_SCHEMA_INVALID")
            return False
        for item in rates:
            if not _validate_rate_item(item):
                issues.append("RATE_SCHEMA_INVALID")
                return False
    else:
        if rates is not None:
            issues.append("EXPECTED_SCHEMA_INVALID")
    return True


# ---------------------------------------------------------------------------
# 离线 oracle
# ---------------------------------------------------------------------------

def _derive_side(
    snapshot: dict,
    expected_trade_date: str,
) -> tuple[str, list[str]]:
    """单侧业务状态推导：normal / partial / unavailable + reason codes。

    优先级：来源全局失败 > 日历不可验证 > 日期不匹配 > 非 final >
    partial coverage > normal。
    """
    data_health = snapshot["data_health"]
    # 1) 来源全局失败
    if not (
        data_health.get("transport_success") is True
        and data_health.get("parse_success") is True
        and data_health.get("required_field_present") is True
        and data_health.get("data_array_present") is True
        and data_health.get("upstream_null") is False
    ):
        return "unavailable", []
    # 2) 交易日历不可验证
    if data_health.get("trade_date_match") is None:
        return "unavailable", ["TRADING_CALENDAR_UNAVAILABLE"]
    # 3) 交易日期不匹配
    if snapshot.get("trade_date") != expected_trade_date \
            or data_health.get("trade_date_match") is False:
        return "unavailable", ["TRADE_DATE_MISMATCH"]
    # 4) 非 final
    if snapshot.get("session") == "not_final" \
            and snapshot.get("is_final") is False:
        return "unavailable", ["NOT_FINAL"]
    # 5) partial coverage
    if data_health.get("coverage_warning") is True \
            or data_health.get("unexplained_empty") is True:
        codes = ["SOURCE_PARTIAL"]
        if data_health.get("coverage_warning") is True:
            codes.append("PARTIAL_COVERAGE")
        if data_health.get("unexplained_empty") is True:
            codes.append("UNEXPLAINED_EMPTY")
        return "partial", codes
    # 6) normal
    return "normal", []


def _calculate_rates(previous_pool: list[dict], current_pool: list[dict]) -> list[dict]:
    """normal 三层计算：denominator=昨日层级，numerator=N→N+1 唯一晋级数。"""
    prev_by_code = {
        row["stock_code"]: row["consecutive_limit_up_days"]
        for row in previous_pool
    }
    curr_by_code = {
        row["stock_code"]: row["consecutive_limit_up_days"]
        for row in current_pool
    }
    denominators: dict[int, int] = {}
    for days in prev_by_code.values():
        denominators[days] = denominators.get(days, 0) + 1
    rates: list[dict] = []
    for level in sorted(denominators):
        denom = denominators[level]
        numerator = sum(
            1
            for code, days in prev_by_code.items()
            if days == level and curr_by_code.get(code) == level + 1
        )
        rates.append({
            "from_level": level,
            "to_level": level + 1,
            "numerator": numerator,
            "denominator": denom,
            "sample_count": denom,
            "rate": float(round(numerator / denom, 4)),
        })
    return rates


def _derive(
    snapshot_prev: dict,
    snapshot_curr: dict,
    prev_expected_date: str,
    curr_expected_date: str,
) -> tuple[str, list[str], Any]:
    """双侧组合推导：(derived_status, derived_reason_codes, derived_rates)。"""
    prev_status, prev_codes = _derive_side(snapshot_prev, prev_expected_date)
    curr_status, curr_codes = _derive_side(snapshot_curr, curr_expected_date)
    if prev_status == "unavailable" or curr_status == "unavailable":
        codes: list[str] = ["SOURCE_UNAVAILABLE"]
        if prev_status == "unavailable":
            codes.append("PREVIOUS_SNAPSHOT_UNAVAILABLE")
        if curr_status == "unavailable":
            codes.append("CURRENT_SNAPSHOT_UNAVAILABLE")
        # 保留各侧具体原因（日历不可验证 / 日期不匹配 / 非 final）；
        # partial 具体码被 unavailable 覆盖
        for code in prev_codes + curr_codes:
            if code in _UNAVAILABLE_SPECIFIC_CODES:
                codes.append(code)
        return "unavailable", _normalize_reason_codes(codes), None
    if prev_status == "partial" or curr_status == "partial":
        return "partial", _normalize_reason_codes(prev_codes + curr_codes), None
    # 双侧 normal
    prev_health = snapshot_prev["data_health"]
    if prev_health.get("legal_zero") is True:
        return "normal", [], []
    rates = _calculate_rates(
        snapshot_prev["limit_up_pool"],
        snapshot_curr["limit_up_pool"],
    )
    return "normal", [], rates


def _validate_case_semantics(
    case_id: str,
    previous_snapshot: dict,
    current_snapshot: dict,
    prev_expected_date: str,
    curr_expected_date: str,
    derived_status: str,
    derived_reason_codes: list[str],
    derived_rates: Any,
    issues: list[str],
) -> None:
    """七类 case 的命名语义独立验证（oracle 之后、expected 比较之前）。

    语义不满足 → CASE_SCHEMA_INVALID；不得依赖 expected 证明 case 语义。
    """
    prev_health = previous_snapshot["data_health"]
    curr_health = current_snapshot["data_health"]
    prev_pool = previous_snapshot["limit_up_pool"]
    curr_pool = current_snapshot["limit_up_pool"]
    prev_levels = {
        row["consecutive_limit_up_days"] for row in prev_pool
    }
    curr_codes = {row["stock_code"] for row in curr_pool}
    prev_by_code = {
        row["stock_code"]: row["consecutive_limit_up_days"] for row in prev_pool
    }

    def fail() -> None:
        issues.append("CASE_SCHEMA_INVALID")

    if case_id == "normal":
        if not (
            derived_status == "normal"
            and prev_health.get("legal_zero") is False
            and curr_health.get("legal_zero") is False
            and prev_levels == {1, 2, 3}
            and isinstance(derived_rates, list)
            and [r["from_level"] for r in derived_rates] == [1, 2, 3]
            and len(derived_rates) == 3
            and derived_rates[0]["numerator"] > 0
            and derived_rates[1]["numerator"] > 0
            and derived_rates[2]["numerator"] == 0
        ):
            fail()
    elif case_id == "zero_denominator":
        if not (
            derived_status == "normal"
            and prev_health.get("legal_zero") is False
            and prev_levels == {1, 2}
            and isinstance(derived_rates, list)
            and [r["from_level"] for r in derived_rates] == [1, 2]
        ):
            fail()
    elif case_id == "previous_legal_zero":
        if not (
            prev_health.get("legal_zero") is True
            and prev_pool == []
            and prev_health.get("row_count") == 0
            and curr_health.get("legal_zero") is False
            and derived_status == "normal"
            and derived_reason_codes == []
            and derived_rates == []
        ):
            fail()
    elif case_id == "current_legal_zero":
        if not (
            prev_health.get("legal_zero") is False
            and prev_pool
            and curr_health.get("legal_zero") is True
            and curr_pool == []
            and curr_health.get("row_count") == 0
            and derived_status == "normal"
            and isinstance(derived_rates, list)
            and len(derived_rates) == len(prev_levels)
            and all(item["numerator"] == 0 and item["rate"] == 0.0
                    for item in derived_rates)
        ):
            fail()
    elif case_id == "partial":
        prev_side_status, _ = _derive_side(previous_snapshot, prev_expected_date)
        if not (
            prev_side_status == "normal"
            and curr_health.get("coverage_warning") is True
            and curr_health.get("unexplained_empty") is False
            and derived_status == "partial"
            and derived_rates is None
            and derived_reason_codes == ["SOURCE_PARTIAL", "PARTIAL_COVERAGE"]
        ):
            fail()
    elif case_id == "unavailable":
        prev_side_status, _ = _derive_side(previous_snapshot, prev_expected_date)
        if not (
            prev_side_status == "normal"
            and curr_health.get("transport_success") is False
            and curr_health.get("trade_date_match") is True
            and curr_health.get("coverage_warning") is False
            and curr_health.get("unexplained_empty") is False
            and current_snapshot.get("session") == "final"
            and current_snapshot.get("is_final") is True
            and derived_status == "unavailable"
            and derived_rates is None
            and derived_reason_codes == [
                "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE"]
        ):
            fail()
    elif case_id == "identity_edge":
        not_incremented = any(
            code in curr_codes
            and prev_by_code[code] == _code_days(curr_pool, code)
            for code in prev_by_code
        )
        skipped = any(
            code in curr_codes
            and _code_days(curr_pool, code) >= prev_by_code[code] + 2
            for code in prev_by_code
        )
        missing = any(code not in curr_codes for code in prev_by_code)
        rate_2_3_zero = not (
            isinstance(derived_rates, list)
            and any(item["from_level"] == 2 for item in derived_rates)
            and next(item for item in derived_rates
                     if item["from_level"] == 2)["numerator"] == 0
        )
        if not (
            derived_status == "normal"
            and prev_health.get("legal_zero") is False
            and curr_health.get("legal_zero") is False
            and missing
            and not_incremented
            and skipped
            and not rate_2_3_zero
        ):
            fail()
    # 未知 case_id 已在 case 集合层拒绝；此处不额外处理


def _code_days(pool: list[dict], code: str) -> int:
    for row in pool:
        if row["stock_code"] == code:
            return row["consecutive_limit_up_days"]
    return 0


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def validate_layered_promotion_fixture(fixture: dict) -> dict:
    """机械验证 layered-promotion 合成 fixture 与已批准合同的一致性。

    不读取文件、不写入、不发网络请求、不修改输入。普通异常结构化失败；
    KeyboardInterrupt / SystemExit / GeneratorExit 自然传播。
    """
    try:
        return _validate_fixture(fixture)
    except Exception:
        return _output(fixture, ["FIXTURE_SCHEMA_INVALID"], [])


def _validate_fixture(fixture: Any) -> dict:
    # 顶层必须为精确 dict（dict 子类不接受）
    if type(fixture) is not dict:
        return _output(fixture, ["FIXTURE_NOT_DICT"], [])
    # 严格 JSON 树类型校验（精确内建类型，拒绝子类 / tuple / set / bytes /
    # object / NaN / Infinity 等）
    if not _is_strict_json_value(fixture):
        return _output(fixture, ["TOP_LEVEL_FIELD_INVALID"], [])
    # 非 JSON 值（object/set/bytes/NaN/Infinity 等）整体拒绝
    try:
        json.dumps(fixture, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return _output(fixture, ["TOP_LEVEL_FIELD_INVALID"], [])

    issues: list[str] = []
    case_results: list[dict] = []

    # 顶层合同
    if fixture.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        issues.append("FIXTURE_SCHEMA_INVALID")
    if set(fixture.keys()) != _TOP_LEVEL_FIELDS:
        issues.append("TOP_LEVEL_FIELD_INVALID")
    if fixture.get("fixture_kind") != "synthetic-normalized":
        issues.append("TOP_LEVEL_FIELD_INVALID")
    if _parse_utc_iso(fixture.get("generated_at")) is None:
        issues.append("TOP_LEVEL_FIELD_INVALID")
    description = fixture.get("description")
    if not isinstance(description, str) or not description \
            or "synthetic" not in description.lower():
        issues.append("TOP_LEVEL_FIELD_INVALID")
    trade_dates = fixture.get("trade_dates")
    if not isinstance(trade_dates, list) or len(trade_dates) != 2:
        issues.append("TOP_LEVEL_FIELD_INVALID")
    else:
        prev_date = _strict_parse_date(trade_dates[0])
        curr_date = _strict_parse_date(trade_dates[1])
        if prev_date is None or curr_date is None or prev_date >= curr_date:
            issues.append("TOP_LEVEL_FIELD_INVALID")
    _validate_market_scope(fixture.get("market_scope"), issues)
    _validate_code_prefix_contract(fixture.get("code_prefix_contract"), issues)

    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        issues.append("CASE_SET_INVALID")
        cases = None

    if cases is not None:
        case_ids: list[str] = []
        for case in cases:
            if isinstance(case, dict) and isinstance(case.get("case_id"), str):
                case_ids.append(case.get("case_id"))
            else:
                issues.append("CASE_SCHEMA_INVALID")
        if len(case_ids) != len(set(case_ids)):
            issues.append("DUPLICATE_CASE_ID")
        if case_ids != list(_CASE_IDS):
            issues.append("CASE_SET_INVALID")

        trade_prev = _strict_parse_date(trade_dates[0]) if (
            isinstance(trade_dates, list) and len(trade_dates) == 2) else None
        trade_curr = _strict_parse_date(trade_dates[1]) if (
            isinstance(trade_dates, list) and len(trade_dates) == 2) else None

        for case in cases:
            if not isinstance(case, dict):
                case_results.append(_invalid_case("", ["CASE_SCHEMA_INVALID"]))
                continue
            case_id = case.get("case_id") if isinstance(case.get("case_id"), str) else ""
            case_issues: list[str] = []
            if not _CASE_REQUIRED_FIELDS.issubset(set(case.keys())):
                case_issues.append("CASE_SCHEMA_INVALID")
            if not isinstance(case.get("case_name"), str) \
                    or not case.get("case_name"):
                case_issues.append("CASE_SCHEMA_INVALID")
            if not isinstance(case.get("description"), str) \
                    or not case.get("description"):
                case_issues.append("CASE_SCHEMA_INVALID")
            case_prev = _strict_parse_date(case.get("previous_trade_date"))
            case_curr = _strict_parse_date(case.get("current_trade_date"))
            if case_prev is None or case_curr is None or case_prev >= case_curr:
                case_issues.append("CASE_SCHEMA_INVALID")
            if trade_prev is not None and trade_curr is not None:
                if case_prev != trade_prev or case_curr != trade_curr:
                    case_issues.append("CASE_SCHEMA_INVALID")

            prev_snap = case.get("previous_snapshot")
            curr_snap = case.get("current_snapshot")
            _validate_snapshot(prev_snap, case.get("previous_trade_date", ""),
                               case_issues)
            _validate_snapshot(curr_snap, case.get("current_trade_date", ""),
                               case_issues)
            expected_ok = _validate_expected(case.get("expected"), case_issues)

            if case_issues:
                case_results.append(_invalid_case(case_id, case_issues))
                issues.extend(case_issues)
                continue

            # 离线 oracle（含日历不可验证 / 日期不匹配 / 非 final 业务映射）
            derived_status, derived_codes, derived_rates = _derive(
                prev_snap, curr_snap,
                case.get("previous_trade_date", ""),
                case.get("current_trade_date", ""))
            # 七类 case 命名语义独立验证（expected 比较之前）
            _validate_case_semantics(
                case_id, prev_snap, curr_snap,
                case.get("previous_trade_date", ""),
                case.get("current_trade_date", ""),
                derived_status, derived_codes, derived_rates,
                case_issues)
            expected = case.get("expected")
            if expected_ok and not case_issues:
                if expected.get("status") != derived_status:
                    case_issues.append("STATUS_MAPPING_MISMATCH")
                if expected.get("reason_codes") != derived_codes:
                    case_issues.append("STATUS_MAPPING_MISMATCH")
                if expected.get("layered_promotion_rates") != derived_rates:
                    case_issues.append("RATE_CALCULATION_MISMATCH")

            if case_issues:
                case_results.append(_invalid_case(
                    case_id, case_issues,
                    derived_status, derived_codes, derived_rates))
                issues.extend(case_issues)
            else:
                case_results.append(_valid_case(
                    case_id, derived_status, derived_codes, derived_rates))

    return _output(fixture, issues, case_results)
