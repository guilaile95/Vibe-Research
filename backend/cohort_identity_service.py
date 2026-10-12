"""Read-only navigation between two complete archived membership lists.

No transition classifier, promotion calculator, prices, PIT selection, or provider.
The frozen promotion coverage gate remains untouched and is not an input here.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import re

import short_term_board_semantics as semantics
import short_term_fact_store as store
import trade_calendar

SCHEMA_VERSION = "archived-cohort-identity.v0.1"
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CODE = re.compile(r"(\d{6})(?:\.(SH|SZ))?")


def _now():
    return datetime.now(timezone.utc)


def _instant(value):
    if type(value) is not str:
        raise ValueError("invalid timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp requires timezone")
    return result.astimezone(timezone.utc)


def _identity(code):
    match = _CODE.fullmatch(code) if type(code) is str else None
    if not match:
        raise ValueError("invalid stock identity")
    digits, exchange = match.groups()
    # Same target universe as the archived EastMoney adapter: Shanghai/Shenzhen A shares.
    expected = "SH" if digits.startswith(("60", "68")) else "SZ" if digits.startswith(("00", "30")) else None
    if expected is None or exchange not in (None, expected):
        raise ValueError("invalid stock exchange")
    return digits


def _checked(record, day, now):
    env = record["envelope"]
    store._validate_envelope(env)
    if env["schema_version"] != "short-term-daily-facts-v0.2":
        raise ValueError("member archive version missing")
    if (env.get("source_schema_version") != env["schema_version"] or env.get("source_status") != "normal"
            or env.get("source_reason_codes") != []):
        raise ValueError("contradictory source status")
    ladder = env["sections"]["ladder"]
    if type(ladder) is not dict or ladder.get("schema_version") != "short-term-limit-up-ladder-v0.1":
        raise ValueError("invalid ladder")
    stored = _instant(record["stored_at"])
    if any(type(env["sections"][key]) is not dict for key in ("facts", "gap")):
        raise ValueError("incomplete sections")
    for layer in (env, ladder, env["sections"]["facts"], env["sections"]["gap"]):
        if (layer.get("trade_date") != day or layer.get("session") != "final"
                or layer.get("is_final") is not True or layer.get("status") != "normal"
                or layer.get("reason_codes") != [] or layer.get("warnings") != []):
            raise ValueError("ineligible archive")
        sources = layer.get("source_ids")
        if type(sources) is not list or not sources or any(type(s) is not str or not s.strip() for s in sources):
            raise ValueError("missing source identity")
        fetched, snapshot = _instant(layer.get("fetched_at")), _instant(layer.get("snapshot_at"))
        close = datetime.fromisoformat(day + "T15:00:00+08:00")
        if not close <= fetched <= snapshot <= stored <= now:
            raise ValueError("invalid archive timing")
    if ladder["source_ids"] != ["eastmoney_getTopicZTPool"] or not set(ladder["source_ids"]).issubset(env["source_ids"]):
        raise ValueError("unsupported membership source")
    if not (_instant(env["fetched_at"]) <= _instant(ladder["fetched_at"])
            <= _instant(ladder["snapshot_at"]) <= _instant(env["snapshot_at"])):
        raise ValueError("inconsistent section timing")
    health = ladder.get("data_health")
    if type(health) is not dict:
        raise ValueError("missing coverage")
    for field in ("transport_success", "parse_success", "required_field_present", "data_array_present", "trade_date_match"):
        if health.get(field) is not True:
            raise ValueError("incomplete coverage")
    for field in ("upstream_null", "unexplained_empty", "coverage_warning"):
        if health.get(field) is not False:
            raise ValueError("incomplete coverage")
    rows = ladder.get("board_semantics")
    if type(rows) is not list or not rows or len(rows) > 10000 or type(health.get("row_count")) is not int or health["row_count"] != len(rows):
        raise ValueError("member coverage mismatch")
    canonical_facts = env["sections"]["facts"].get("facts")
    if type(canonical_facts) is not dict:
        raise ValueError("missing canonical counts")
    canonical_count = canonical_facts.get("limit_up_count")
    # This member-navigation view is narrower than the composer's count tolerance:
    # any count disagreement makes absence unsafe to present as complete-list evidence.
    if type(canonical_count) is not int or canonical_count != len(rows):
        raise ValueError("canonical member count mismatch")
    if health.get("legal_zero") is not False:
        raise ValueError("invalid empty coverage")
    members = {}
    for row in rows:
        if type(row) is not dict:
            raise ValueError("invalid member")
        code = _identity(row.get("stock_code"))
        boards = row.get("boards")
        if code in members or type(boards) is not int or not 1 <= boards <= 10000:
            raise ValueError("duplicate or invalid member")
        # Validate stored derived semantics, but never use effective_height/labels for the join.
        expected = semantics.classify_board({"stock_code": row["stock_code"], "boards": boards, "zt_stat": row.get("zt_stat")})
        if row != expected:
            raise ValueError("invalid stored board semantics")
        members[code] = {"source_code": row["stock_code"], "boards": boards}
    tiers = Counter(row["boards"] for row in members.values() if row["boards"] >= 2)
    expected_metrics = {"max_boards": max((row["boards"] for row in members.values()), default=0),
                        "lianban_count": sum(tiers.values()),
                        "ladder": [{"boards": key, "count": tiers[key]} for key in sorted(tiers)]}
    # bool == int is not sufficient for evidence validation.
    canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if canonical(ladder.get("metrics")) != canonical(expected_metrics):
        raise ValueError("aggregate mismatch")
    evidence = {"trade_date": day, "source_ids": ladder["source_ids"],
                "fetched_at": ladder["fetched_at"], "snapshot_at": ladder["snapshot_at"],
                "stored_at": record["stored_at"], "row_count": len(rows),
                "envelope_sha256": hashlib.sha256(canonical(env).encode("utf-8")).hexdigest()}
    return members, evidence


def query_cohort_identity(trade_date):
    if type(trade_date) is not str or not _DATE.fullmatch(trade_date):
        raise ValueError("trade_date 必须为 YYYY-MM-DD")
    try:
        date.fromisoformat(trade_date)
    except ValueError:
        raise ValueError("trade_date 必须为有效日期") from None
    previous = trade_calendar.previous_trade_date(trade_date)
    result = {"schema_version": SCHEMA_VERSION, "trade_date": trade_date,
              "previous_trade_date": previous, "status": "unavailable", "reason_codes": [],
              "message": "缺少完整的两日名单归档，无法进行对照", "selection_mode": "CURRENT_STORED_POSTHOC",
              "point_in_time_claim": "NONE", "research_only": True, "projection": None, "evidence": None}
    if previous is None:
        result["reason_codes"] = ["CALENDAR_UNAVAILABLE"]
        result["message"] = "交易日历未确认相邻交易日，无法进行对照"
        return result
    try:
        records = store.load_final_fact_records_readonly((previous, trade_date))
        if any(day not in records for day in (previous, trade_date)):
            result["reason_codes"] = ["ARCHIVE_MISSING"]
            return result
        now = _now()
        old, old_evidence = _checked(records[previous], previous, now)
        current, current_evidence = _checked(records[trade_date], trade_date, now)
    except store.FactStoreBusyError:
        result["reason_codes"] = ["ARCHIVE_BUSY"]
        result["message"] = "归档有未落盘事务或读取期间发生变化，暂不读取；未触发写入或检查点"
        return result
    except (store.FactStoreError, ValueError, TypeError, KeyError, OverflowError):
        result["reason_codes"] = ["ARCHIVE_INELIGIBLE"]
        result["message"] = "两日归档的完整性、版本或时间未通过核验，结果未知"
        return result
    result.update(status="normal", message="已读取两日完整名单；仅作逐股身份查阅",
                  evidence={"previous": old_evidence, "current": current_evidence},
                  projection={"rows": [{"stock_code": code, "previous_source_code": old[code]["source_code"],
                                        "current_source_code": current[code]["source_code"] if code in current else None,
                                        "previous_boards": old[code]["boards"],
                                        "current_boards": current[code]["boards"] if code in current else None,
                                        "present_today": code in current} for code in sorted(old)]})
    return result
