"""Read-only seal-quality observations from exact captured EastMoney bytes.

This is an additive research projection, not a final snapshot producer. It
reuses the existing adapter's date, universe and coverage admission without
changing its output, fingerprints, promotion gates or canonical authority.
No network, clock, calendar, filesystem, persistence or trading operations.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import short_term_limit_up_pool_adapter as adapter

SCHEMA_VERSION = "short-term-seal-quality-observation-v0.1"
_SH = timezone(timedelta(hours=8))
_FIELDS = ("first_seal", "last_seal", "broken_times")
_METRICS = (
    "never_broken_count", "never_broken_ratio", "reopened_count",
    "ever_opened_ratio", "average_broken_times", "first_seal_by_0935_count",
    "late_seal_count",
)
_LIMITATIONS = (
    "仅描述同一涨停池观测中的沪深主板、创业板、科创板样本；不含北交所。",
    "日期绑定不证明池子完整、收盘定稿或当时可成交；本投影不授予 final authority。",
    "涨停股盘中开板比例不等于全市场炸板率；未读取炸板池，不计算炸板率。",
    "每项指标只有相关字段覆盖全部入选样本才计算；缺失和无效值不是零。",
    "首封与末封为来源当日上海时间，非首次抓取时间；不回填历史缺失字段。",
    "不计算收益、分层晋级率、题材归因、交易信号或持仓动作。",
)


def _binding(requested_trade_date: Any, observed_at: Any) -> tuple[date, datetime] | None:
    if type(requested_trade_date) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested_trade_date):
        return None
    if type(observed_at) is not str or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", observed_at
    ):
        return None
    try:
        day = date.fromisoformat(requested_trade_date)
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(_SH)
    except (ValueError, OverflowError):
        return None
    return (day, observed) if observed.date() >= day else None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _seal_time(value: Any, day: date, observed: datetime) -> str | None:
    # Integers omit the leading zero; floats, booleans and guessed formats do not.
    if type(value) is int and 0 <= value <= 235959:
        value = str(value).zfill(6)
    if type(value) is not str or not re.fullmatch(r"\d{6}", value):
        return None
    try:
        stamp = datetime.combine(day, datetime.strptime(value, "%H%M%S").time(), _SH)
    except ValueError:
        return None
    in_session = "092500" <= value <= "113000" or "130000" <= value <= "150000"
    return value if in_session and stamp <= observed else None


def _row(raw: dict[str, Any], admitted: dict[str, Any], day: date, observed: datetime) -> dict[str, Any]:
    first = _seal_time(raw.get("fbt"), day, observed)
    last = _seal_time(raw.get("lbt"), day, observed)
    broken = raw.get("zbc")
    broken = broken if type(broken) is int and 0 <= broken <= 2_147_483_647 else None
    issues = {
        field: ["MISSING_SOURCE_FIELD" if raw.get(source) in (None, "", "-") else "INVALID_SOURCE_FIELD"]
        for field, source, value in (
            ("first_seal", "fbt", first), ("last_seal", "lbt", last), ("broken_times", "zbc", broken)
        ) if value is None
    }
    if first is not None and last is not None and last < first:
        first = last = None
        issues["first_seal"] = issues["last_seal"] = ["SEAL_TIME_ORDER_INVALID"]
    return {
        "stock_code": admitted["stock_code"], "lbc": admitted["lbc"],
        "zt_stat": admitted.get("zt_stat"),
        "first_seal": first, "last_seal": last, "broken_times": broken,
        "field_issues": issues,
    }


def build_seal_quality_observation(
    raw_bytes: bytes, *, requested_trade_date: str, http_status: int | None, observed_at: str,
) -> dict[str, Any]:
    """Project a captured response deterministically; never fetch missing data.

    ``observed_at`` is the capture time supplied by the caller, not date proof.
    The existing adapter must independently bind a date inside the payload.
    A content hash identifies the exact input, not a committed/final snapshot.
    Old captures with no quality fields remain useful to the old ladder but
    produce unavailable quality metrics here. No legacy result is rewritten.
    """
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "layer": "RESEARCH_OBSERVATION",
        "status": "unavailable", "reason_codes": [],
        "requested_trade_date": requested_trade_date, "source_trade_date": None,
        "observed_at": observed_at,
        "raw_payload_sha256": hashlib.sha256(raw_bytes).hexdigest() if type(raw_bytes) is bytes else None,
        "source_id": "eastmoney_getTopicZTPool",
        "source_schema_version": adapter.SCHEMA_VERSION,
        "source_status": None, "source_reason_codes": [],
        "finality": "NOT_ESTABLISHED", "canonical_authority": False,
        "sample_count": None, "excluded_universe_count": None,
        "coverage": {field: {"known_count": 0, "unknown_count": None, "complete": False} for field in _FIELDS},
        "rows": [], "metrics": {metric: None for metric in _METRICS},
        "units": {"time": "HHMMSS Asia/Shanghai", "ratio": "fraction_0_1", "count": "stocks", "average_broken_times": "times"},
        "descriptive_cutoffs": {"first_seal_at_or_before": "093500", "last_seal_at_or_after": "143000", "auction_included": True, "authority": "LOCAL_DESCRIPTIVE_CONVENTION"},
        "limitations": list(_LIMITATIONS),
    }
    binding = _binding(requested_trade_date, observed_at)
    if binding is None:
        result["reason_codes"] = ["OBSERVATION_BINDING_INVALID"]
        return result
    source = adapter.interpret_limit_up_pool_response_bytes(
        raw_bytes, requested_trade_date=requested_trade_date,
        http_status=http_status, observed_at=observed_at,
    )
    result.update(source_status=source["status"], source_reason_codes=list(source["reason_codes"]))
    if source["status"] != "normal" or source["trade_date_match"] is not True:
        result["reason_codes"] = ["SOURCE_NOT_QUALIFIED"]
        return result
    result["source_trade_date"] = requested_trade_date
    result["excluded_universe_count"] = source["excluded_universe_count"]
    if not source["rows"]:
        result["reason_codes"] = ["EMPTY_TARGET_SAMPLE"]
        result["sample_count"] = 0
        return result
    # The legacy interpreter already checked size/HTTP/JSON/date/identity.
    # Reject duplicate properties as well; never silently select the last one.
    try:
        payload = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError):
        result["reason_codes"] = ["AMBIGUOUS_SOURCE_JSON"]
        return result
    raw_by_code = {}
    for raw in payload["data"]["pool"]:
        if not isinstance(raw, dict):
            continue
        code = raw.get("c")
        if code is None:
            code = raw.get("code")
        if type(code) is str:
            raw_by_code[code.strip()] = raw
    day, observed = binding
    rows = [_row(raw_by_code[row["stock_code"]], row, day, observed) for row in source["rows"]]
    n = len(rows)
    result.update(rows=rows, sample_count=n)
    for field in _FIELDS:
        known = sum(row[field] is not None for row in rows)
        result["coverage"][field] = {"known_count": known, "unknown_count": n - known, "complete": known == n}
    metrics = result["metrics"]
    if result["coverage"]["broken_times"]["complete"]:
        never = sum(row["broken_times"] == 0 for row in rows)
        metrics.update(
            never_broken_count=never, never_broken_ratio=round(never / n, 6),
            reopened_count=n - never, ever_opened_ratio=round((n - never) / n, 6),
            average_broken_times=round(sum(row["broken_times"] for row in rows) / n, 6),
        )
    if result["coverage"]["first_seal"]["complete"]:
        metrics["first_seal_by_0935_count"] = sum(row["first_seal"] <= "093500" for row in rows)
    if result["coverage"]["last_seal"]["complete"]:
        metrics["late_seal_count"] = sum(row["last_seal"] >= "143000" for row in rows)
    available = sum(value is not None for value in metrics.values())
    result["status"] = "normal" if available == len(metrics) else "partial" if available else "unavailable"
    result["reason_codes"] = [] if result["status"] == "normal" else ["QUALITY_FIELDS_INCOMPLETE"]
    return result
