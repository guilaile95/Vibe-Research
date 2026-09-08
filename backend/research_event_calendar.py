"""Bounded, read-only research event calendar projection.

This module deliberately composes the existing Campaign, Research Continuity,
and StockData contracts.  It is a view over provider observations, not a new
event authority: no event is persisted and no formal research state is
mutated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import astock
import campaign_service
import research_continuity_service


SCHEMA_VERSION = "research_event_calendar.v0.1"
MAX_UNIQUE_SECURITIES = 20
DEFAULT_PAST_DAYS = 14
DEFAULT_FUTURE_DAYS = 90
MAX_PAST_DAYS = 90
MAX_FUTURE_DAYS = 180

ACTIVE_RESEARCH_CAMPAIGN_STATUSES = frozenset(
    {"RESEARCHING", "PRE-ENTRY", "ACTIVE", "REDUCING"}
)
EVENT_TYPES = (
    "PERIODIC_REPORT",
    "LOCKUP_EXPIRY",
    "DIVIDEND_BONUS",
    "ANNOUNCEMENT",
)

_SOURCE_NAMES = {
    "PERIODIC_REPORT": "eastmoney:RPT_PUBLIC_BS_APPOIN",
    "LOCKUP_EXPIRY": "eastmoney:RPT_LIFT_STAGE",
    "DIVIDEND_BONUS": "eastmoney:RPT_SHAREBONUS_DET",
    "ANNOUNCEMENT": "eastmoney:np-anotice-stock",
}
_CATALYST_LIMITATION = "NO_EXPLICIT_EVENT_CATALYST_LINK"
_PERIODIC_LIMITATIONS = (
    "APPOINTMENT_DATE_IS_NOT_A_COMPANY_GUARANTEE",
    "ACTUAL_DISCLOSURE_IS_NOT_AN_EXPECTATION_JUDGEMENT",
    _CATALYST_LIMITATION,
)
_COMMON_LIMITATIONS = (_CATALYST_LIMITATION,)


class ResearchEventCalendarError(RuntimeError):
    """Stable service error boundary for unexpected read failures."""


class ResearchEventCalendarValidationError(ValueError):
    """Caller supplied a date or event-type range outside the v0.1 contract."""


def _fetched_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _json_value(value: Any) -> Any:
    """Keep provider values intact while making the projection JSON-safe."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _identity(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _event_id(identity: Any) -> str:
    digest = hashlib.sha256(_identity(identity).encode("utf-8")).hexdigest()[:24]
    return f"event_{digest}"


def _normalise_event_types(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not values:
        return EVENT_TYPES
    expanded: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ResearchEventCalendarValidationError("event_types 参数无效")
        expanded.extend(part.strip().upper() for part in value.split(",") if part.strip())
    selected = tuple(dict.fromkeys(expanded))
    invalid = sorted(set(selected) - set(EVENT_TYPES))
    if invalid or not selected:
        raise ResearchEventCalendarValidationError("event_types 参数无效")
    return tuple(event_type for event_type in EVENT_TYPES if event_type in selected)


def resolve_window(
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    today: date | None = None,
) -> tuple[date, date, date]:
    """Resolve a bounded calendar-day window; return ``(as_of, from, to)``."""
    as_of = today or _today()
    if not isinstance(as_of, date):
        raise ResearchEventCalendarValidationError("as_of 无效")
    try:
        start = _parse_date(date_from) if date_from else as_of - timedelta(days=DEFAULT_PAST_DAYS)
        end = _parse_date(date_to) if date_to else as_of + timedelta(days=DEFAULT_FUTURE_DAYS)
    except (TypeError, ValueError):
        raise ResearchEventCalendarValidationError("日期参数无效") from None
    if start is None or end is None:
        raise ResearchEventCalendarValidationError("日期参数无效")
    if start > end:
        raise ResearchEventCalendarValidationError("date_from 不能晚于 date_to")
    if start < as_of - timedelta(days=MAX_PAST_DAYS):
        raise ResearchEventCalendarValidationError("date_from 超出最大回溯范围")
    if end > as_of + timedelta(days=MAX_FUTURE_DAYS):
        raise ResearchEventCalendarValidationError("date_to 超出最大前瞻范围")
    return as_of, start, end


def _in_window(event_date: date | None, start: date, end: date) -> bool:
    return event_date is None or start <= event_date <= end


def _active_campaigns(campaign_ids: list[str] | None) -> list[dict[str, Any]]:
    try:
        records = campaign_service.list_campaigns()
    except Exception as exc:  # noqa: BLE001 - router redacts the stable error
        raise ResearchEventCalendarError("Campaign read unavailable") from exc
    if not isinstance(records, list) or any(not isinstance(item, Mapping) for item in records):
        raise ResearchEventCalendarError("Campaign read returned an invalid shape")
    requested = set(campaign_ids or [])
    selected = [
        dict(item)
        for item in records
        if item.get("status") in ACTIVE_RESEARCH_CAMPAIGN_STATUSES
        and (not requested or item.get("campaign_id") in requested)
    ]
    return sorted(
        selected,
        key=lambda item: (
            str(item.get("security_code") or ""),
            str(item.get("created_at") or ""),
            str(item.get("campaign_id") or ""),
        ),
    )


def _group_campaigns(campaigns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for campaign in campaigns:
        code = campaign.get("security_code")
        campaign_id = campaign.get("campaign_id")
        if not isinstance(code, str) or not code or not isinstance(campaign_id, str) or not campaign_id:
            raise ResearchEventCalendarError("Campaign identity is invalid")
        entry = grouped.setdefault(
            code,
            {"security_code": code, "security_name": None, "campaign_ids": []},
        )
        if campaign_id not in entry["campaign_ids"]:
            entry["campaign_ids"].append(campaign_id)
    result = list(grouped.values())
    for entry in result:
        entry["campaign_ids"].sort()
    return result


def _base_event(
    *,
    security: Mapping[str, Any],
    event_type: str,
    event_date: date | None,
    state: str,
    title: str,
    details: Mapping[str, Any],
    source: str,
    source_record_identity: str,
    fetched_at: str,
    limitations: tuple[str, ...] = _COMMON_LIMITATIONS,
) -> dict[str, Any]:
    identity = {
        "source": source,
        "security_code": security["security_code"],
        "event_type": event_type,
        "record": source_record_identity,
    }
    return {
        "event_id": _event_id(identity),
        "security_code": security["security_code"],
        "security_name": security.get("security_name"),
        "campaign_ids": list(security["campaign_ids"]),
        "event_type": event_type,
        "event_date": event_date.isoformat() if event_date else None,
        "date_semantics": "DATE_ONLY" if event_date else "UNKNOWN",
        "state": state,
        "title": title,
        "details": {key: _json_value(value) for key, value in details.items()},
        "source": source,
        "source_record_identity": source_record_identity,
        "fetched_at": fetched_at,
        "limitations": list(dict.fromkeys(limitations)),
    }


def _add_event(
    events: dict[str, dict[str, Any]], event: dict[str, Any], start: date, end: date,
) -> None:
    event_date = _parse_date(event.get("event_date"))
    if not _in_window(event_date, start, end):
        return
    events.setdefault(event["event_id"], event)


def _periodic_events(
    security: Mapping[str, Any], calendar: Mapping[str, Any], fetched_at: str,
    start: date, end: date,
) -> list[dict[str, Any]]:
    state = str(calendar.get("state") or "ERROR")
    events: list[dict[str, Any]] = []
    next_record = calendar.get("next")
    if isinstance(next_record, Mapping):
        appointment = _parse_date(next_record.get("appointment_date"))
        if appointment:
            if state == "DELAYED_SIGNAL":
                title = "预约披露日已过，尚未见实际披露"
            elif state == "EXPECTED":
                title = "预计披露日（不是公司保证日期）"
            else:
                title = "定期报告披露日"
            event = _base_event(
                security=security,
                event_type="PERIODIC_REPORT",
                event_date=appointment,
                state=state,
                title=title,
                details={
                    "report_date": next_record.get("report_date"),
                    "appointment_date": next_record.get("appointment_date"),
                    "actual_date": next_record.get("actual_date"),
                    "semantics": "预约披露日不是公司保证日期；预约日已过不等同于违规；实际披露不代表符合预期",
                },
                source=_SOURCE_NAMES["PERIODIC_REPORT"],
                source_record_identity=(
                    f"report:{next_record.get('report_date')}|appointment:{next_record.get('appointment_date')}|"
                    f"actual:{next_record.get('actual_date')}|next"
                ),
                fetched_at=fetched_at,
                limitations=_PERIODIC_LIMITATIONS,
            )
            if _in_window(appointment, start, end):
                events.append(event)
    latest_actual = calendar.get("latest_actual")
    if isinstance(latest_actual, Mapping):
        actual = _parse_date(latest_actual.get("actual_date"))
        if actual and _in_window(actual, start, end):
            events.append(
                _base_event(
                    security=security,
                    event_type="PERIODIC_REPORT",
                    event_date=actual,
                    state="CONFIRMED",
                    title="定期报告已实际披露",
                    details={
                        "report_date": latest_actual.get("report_date"),
                        "appointment_date": latest_actual.get("appointment_date"),
                        "actual_date": latest_actual.get("actual_date"),
                        "semantics": "实际披露是已观察到的公开事件，不代表符合预期",
                    },
                    source=_SOURCE_NAMES["PERIODIC_REPORT"],
                    source_record_identity=(
                        f"report:{latest_actual.get('report_date')}|appointment:{latest_actual.get('appointment_date')}|"
                        f"actual:{latest_actual.get('actual_date')}|actual"
                    ),
                    fetched_at=fetched_at,
                    limitations=_PERIODIC_LIMITATIONS,
                )
            )
    return events


def _lockup_events(
    security: Mapping[str, Any], value: Any, fetched_at: str, start: date, end: date,
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(value, Mapping) or not isinstance(value.get("history"), list) or not isinstance(value.get("upcoming"), list):
        raise ValueError("lockup provider returned an invalid shape")
    rows = list(value["history"]) + list(value["upcoming"])
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("lockup provider returned a malformed row")
        event_date = _parse_date(row.get("date"))
        identity = _identity({
            "date": row.get("date"), "type": row.get("type"), "shares": row.get("shares"),
            "able_shares": row.get("able_shares"), "ratio": row.get("ratio"),
        })
        if identity in seen:
            continue
        seen.add(identity)
        state = "UNKNOWN" if event_date is None else ("UPCOMING" if event_date > _today() else "HISTORY")
        event = _base_event(
            security=security,
            event_type="LOCKUP_EXPIRY",
            event_date=event_date,
            state=state,
            title="限售股解禁" if state != "UNKNOWN" else "限售股解禁记录（日期未知）",
            details={
                "type": row.get("type"),
                "shares": row.get("shares"),
                "able_shares": row.get("able_shares"),
                "ratio": row.get("ratio"),
                "semantics": "仅展示 provider 解禁事实，不推断抛压或价格影响",
            },
            source=_SOURCE_NAMES["LOCKUP_EXPIRY"],
            source_record_identity=f"RPT_LIFT_STAGE:{identity}",
            fetched_at=fetched_at,
            limitations=("PROVIDER_FACT_ONLY", _CATALYST_LIMITATION),
        )
        if _in_window(event_date, start, end):
            events.append(event)
    return events, "NORMAL" if rows else "NO_RECORD"


def _dividend_events(
    security: Mapping[str, Any], value: Any, fetched_at: str, start: date, end: date,
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(value, list):
        raise ValueError("dividend provider returned an invalid shape")
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    as_of = _today()
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError("dividend provider returned a malformed row")
        event_date = _parse_date(row.get("date"))
        identity = _identity({
            "date": row.get("date"), "bonus_rmb": row.get("bonus_rmb"),
            "transfer_ratio": row.get("transfer_ratio"), "bonus_ratio": row.get("bonus_ratio"),
            "plan": row.get("plan"),
        })
        if identity in seen:
            continue
        seen.add(identity)
        plan = row.get("plan")
        has_provider_status = isinstance(plan, str) and bool(plan.strip())
        if event_date is None:
            state = "UNKNOWN"
            title = "分红记录（日期未知）"
            limitations = ("PROVIDER_DATE_UNKNOWN", "PROVIDER_DATE_STATUS_ONLY", _CATALYST_LIMITATION)
        elif event_date > as_of and has_provider_status:
            state = "UPCOMING"
            title = "分红计划（provider 日期与状态）"
            limitations = ("PROVIDER_DATE_STATUS_ONLY", _CATALYST_LIMITATION)
        elif event_date > as_of:
            state = "OBSERVED"
            title = "分红记录（未满足 upcoming 状态条件）"
            limitations = (
                "FUTURE_DATE_WITHOUT_PROVIDER_STATUS_NOT_PROMOTED",
                "PROVIDER_DATE_STATUS_ONLY",
                _CATALYST_LIMITATION,
            )
        else:
            state = "HISTORY"
            title = "历史分红记录"
            limitations = ("PROVIDER_DATE_STATUS_ONLY", _CATALYST_LIMITATION)
        event = _base_event(
            security=security,
            event_type="DIVIDEND_BONUS",
            event_date=event_date,
            state=state,
            title=title,
            details={
                "provider_status": plan,
                "ex_dividend_date": row.get("date"),
                "bonus_rmb": row.get("bonus_rmb"),
                "transfer_ratio": row.get("transfer_ratio"),
                "bonus_ratio": row.get("bonus_ratio"),
                "semantics": "分红字段仅保留 provider 日期与状态，不推断 BUY/SELL",
            },
            source=_SOURCE_NAMES["DIVIDEND_BONUS"],
            source_record_identity=f"RPT_SHAREBONUS_DET:{identity}",
            fetched_at=fetched_at,
            limitations=limitations,
        )
        if _in_window(event_date, start, end):
            events.append(event)
    return events, "NORMAL" if value else "NO_RECORD"


def _announcement_events(
    security: Mapping[str, Any], value: Any, fetched_at: str, start: date, end: date,
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(value, list):
        raise ValueError("announcement provider returned an invalid shape")
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError("announcement provider returned a malformed row")
        event_date = _parse_date(row.get("date"))
        identity = _identity({
            "date": row.get("date"), "title": row.get("title"),
            "type": row.get("type"), "url": row.get("url"),
        })
        if identity in seen:
            continue
        seen.add(identity)
        # Announcements are observed publications, never future predictions.
        if event_date is not None and event_date > _today():
            continue
        title = row.get("title") if isinstance(row.get("title"), str) and row.get("title") else "公告"
        event = _base_event(
            security=security,
            event_type="ANNOUNCEMENT",
            event_date=event_date,
            state="CONFIRMED" if event_date else "UNKNOWN",
            title=title,
            details={
                "type": row.get("type"),
                "url": row.get("url"),
                "notice_at": row.get("notice_at"),
                "semantics": "已观察到的公开公告 publication event，不做 NLP 重要性判断",
            },
            source=_SOURCE_NAMES["ANNOUNCEMENT"],
            source_record_identity=f"np-anotice-stock:{identity}",
            fetched_at=fetched_at,
            limitations=("OBSERVED_PUBLICATION_ONLY", _CATALYST_LIMITATION),
        )
        if _in_window(event_date, start, end):
            events.append(event)
    return events, "NORMAL" if value else "NO_RECORD"


def _source_summary(event_type: str, security_statuses: list[dict[str, Any]]) -> dict[str, Any]:
    failures = sum(1 for item in security_statuses if item["status"] == "ERROR")
    unavailable = sum(1 for item in security_statuses if item["status"] == "UNAVAILABLE")
    no_records = sum(1 for item in security_statuses if item["status"] == "NO_RECORD")
    successes = len(security_statuses) - failures - unavailable
    if not security_statuses:
        status = "NOT_REQUESTED"
    elif failures + unavailable == len(security_statuses):
        status = "UNAVAILABLE"
    elif failures or unavailable:
        status = "PARTIAL"
    else:
        status = "NORMAL"
    return {
        "event_type": event_type,
        "source": _SOURCE_NAMES[event_type],
        "status": status,
        "security_count": len(security_statuses),
        "success_count": successes,
        "failure_count": failures,
        "unavailable_count": unavailable,
        "no_record_count": no_records,
        "security_statuses": security_statuses,
        "limitations": list(_COMMON_LIMITATIONS),
    }


def build_research_event_calendar(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    event_types: list[str] | None = None,
    campaign_ids: list[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Build the bounded projection without creating or mutating any record."""
    as_of, start, end = resolve_window(date_from, date_to, today=today)
    selected_types = _normalise_event_types(event_types)
    campaigns = _active_campaigns(campaign_ids)
    securities = _group_campaigns(campaigns)
    fetched_at = _fetched_at()
    universe = {
        "kind": "ACTIVE_RESEARCH_CAMPAIGNS",
        "status": "NORMAL" if securities else "EMPTY",
        "campaign_count": len(campaigns),
        "unique_security_count": len(securities),
        "max_unique_securities": MAX_UNIQUE_SECURITIES,
        "securities": securities,
    }
    writes = {
        "campaign": 0,
        "thesis": 0,
        "evidence": 0,
        "decision": 0,
        "trade": 0,
        "account": 0,
    }
    if len(securities) > MAX_UNIQUE_SECURITIES:
        universe["status"] = "OVER_LIMIT"
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "UNAVAILABLE",
            "as_of": as_of.isoformat(),
            "fetched_at": fetched_at,
            "window": {"date_from": start.isoformat(), "date_to": end.isoformat(), "semantics": "CALENDAR_DAYS"},
            "universe": universe,
            "events": [],
            "sources": [],
            "limitations": ["ACTIVE_RESEARCH_CAMPAIGN_UNIVERSE_EXCEEDS_BOUND", _CATALYST_LIMITATION],
            "writes": writes,
        }

    if not securities:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "NORMAL",
            "as_of": as_of.isoformat(),
            "fetched_at": fetched_at,
            "window": {"date_from": start.isoformat(), "date_to": end.isoformat(), "semantics": "CALENDAR_DAYS"},
            "universe": universe,
            "events": [],
            "sources": [],
            "limitations": [_CATALYST_LIMITATION],
            "writes": writes,
        }

    events: dict[str, dict[str, Any]] = {}
    source_summaries: list[dict[str, Any]] = []
    for event_type in selected_types:
        security_statuses: list[dict[str, Any]] = []
        for security in securities:
            code = security["security_code"]
            try:
                if event_type == "PERIODIC_REPORT":
                    calendar = research_continuity_service._calendar(code, fetched_at)
                    if not isinstance(calendar, Mapping):
                        raise ValueError("periodic report returned an invalid shape")
                    source_state = str(calendar.get("state") or "ERROR")
                    if source_state == "ERROR":
                        security_statuses.append({"security_code": code, "status": "ERROR", "reason": "PROVIDER_FAILURE"})
                    elif source_state == "UNAVAILABLE":
                        security_statuses.append({"security_code": code, "status": "UNAVAILABLE", "reason": "SOURCE_UNAVAILABLE"})
                    elif source_state == "NO_RECORD":
                        security_statuses.append({"security_code": code, "status": "NO_RECORD", "reason": "NO_RECORD"})
                    else:
                        for event in _periodic_events(security, calendar, fetched_at, start, end):
                            events.setdefault(event["event_id"], event)
                        security_statuses.append({"security_code": code, "status": "NORMAL", "state": source_state})
                elif event_type == "LOCKUP_EXPIRY":
                    rows, source_state = _lockup_events(
                        security, astock.lockup_expiry(
                            code, trade_date=as_of.isoformat(), forward_days=MAX_FUTURE_DAYS, strict=True,
                        ),
                        fetched_at, start, end,
                    )
                    for event in rows:
                        events.setdefault(event["event_id"], event)
                    security_statuses.append({"security_code": code, "status": source_state})
                elif event_type == "DIVIDEND_BONUS":
                    rows, source_state = _dividend_events(
                        security, astock.dividend_history(code, strict=True), fetched_at, start, end,
                    )
                    for event in rows:
                        events.setdefault(event["event_id"], event)
                    security_statuses.append({"security_code": code, "status": source_state})
                else:
                    rows, source_state = _announcement_events(
                        security, astock.announcements(code, strict=True), fetched_at, start, end,
                    )
                    for event in rows:
                        events.setdefault(event["event_id"], event)
                    security_statuses.append({"security_code": code, "status": source_state})
            except Exception as exc:  # noqa: BLE001 - one source/security must not erase other observations
                security_statuses.append({
                    "security_code": code,
                    "status": "ERROR",
                    "reason": "PROVIDER_FAILURE",
                    "error_type": type(exc).__name__,
                })
        source_summaries.append(_source_summary(event_type, security_statuses))

    source_failures = sum(item["failure_count"] + item["unavailable_count"] for item in source_summaries)
    total_calls = sum(item["security_count"] for item in source_summaries)
    if total_calls and source_failures == total_calls:
        status = "UNAVAILABLE"
    elif source_failures:
        status = "PARTIAL"
    else:
        status = "NORMAL"
    ordered_events = sorted(
        events.values(),
        key=lambda item: (
            item["event_date"] is None,
            item["event_date"] or "9999-12-31",
            item["security_code"],
            item["event_type"],
            item["event_id"],
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "as_of": as_of.isoformat(),
        "fetched_at": fetched_at,
        "window": {"date_from": start.isoformat(), "date_to": end.isoformat(), "semantics": "CALENDAR_DAYS"},
        "universe": universe,
        "events": ordered_events,
        "sources": source_summaries,
        "limitations": [_CATALYST_LIMITATION],
        "writes": writes,
    }


__all__ = [
    "ACTIVE_RESEARCH_CAMPAIGN_STATUSES",
    "EVENT_TYPES",
    "MAX_UNIQUE_SECURITIES",
    "ResearchEventCalendarError",
    "ResearchEventCalendarValidationError",
    "build_research_event_calendar",
    "resolve_window",
]
