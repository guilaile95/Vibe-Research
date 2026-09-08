from __future__ import annotations

from datetime import date

import pytest

import astock
import campaign_service
import research_continuity_service
import research_event_calendar as calendar
import research_event_calendar_router


AS_OF = date(2026, 9, 9)


def _campaign(code: str, suffix: str, status: str = "ACTIVE") -> dict:
    return {
        "campaign_id": f"campaign_{suffix * 32}"[:41],
        "security_code": code,
        "strategy": "SWING",
        "status": status,
        "created_at": "2026-01-01T00:00:00.000000Z",
    }


def _calendar(state: str, *, appointment: str | None = None, actual: str | None = None) -> dict:
    record = {
        "report_date": "2026-06-30",
        "appointment_date": appointment,
        "actual_date": actual,
    }
    return {
        "state": state,
        "next": record if appointment else None,
        "latest_actual": {**record, "semantics": "CONFIRMED"} if actual else None,
        "fetched_at": "2026-09-09T00:00:00.000000Z",
        "source": "eastmoney:RPT_PUBLIC_BS_APPOIN",
    }


@pytest.fixture(autouse=True)
def freeze_calendar(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(calendar, "_today", lambda: AS_OF)
    monkeypatch.setattr(calendar, "_fetched_at", lambda: "2026-09-09T00:00:00.000000Z")


def _base(monkeypatch: pytest.MonkeyPatch, campaigns: list[dict]) -> None:
    monkeypatch.setattr(campaign_service, "list_campaigns", lambda **_: campaigns)
    monkeypatch.setattr(research_continuity_service, "_calendar", lambda code, fetched_at: _calendar("NO_RECORD"))
    monkeypatch.setattr(astock, "lockup_expiry", lambda code, **_: {"history": [], "upcoming": []})
    monkeypatch.setattr(astock, "dividend_history", lambda code, **_: [])
    monkeypatch.setattr(astock, "announcements", lambda code, **_: [])


def _events(result: dict, event_type: str | None = None) -> list[dict]:
    return [item for item in result["events"] if event_type is None or item["event_type"] == event_type]


def test_active_campaign_universe_dedups_security_and_retains_campaign_ids(monkeypatch):
    campaigns = [_campaign("600001", "a"), _campaign("600001", "b"), _campaign("000002", "c"), _campaign("600003", "d", "CLOSED")]
    _base(monkeypatch, campaigns)
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    assert result["universe"]["unique_security_count"] == 2
    assert result["universe"]["campaign_count"] == 3
    assert result["universe"]["securities"][1]["campaign_ids"] == [campaigns[0]["campaign_id"], campaigns[1]["campaign_id"]]


def test_unique_security_bound_fails_closed_without_provider_calls(monkeypatch):
    campaigns = [_campaign(f"{index:06d}", f"{index:02x}") for index in range(1, 22)]
    _base(monkeypatch, campaigns)
    calls = []
    monkeypatch.setattr(astock, "announcements", lambda code, **_: calls.append(code) or [])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    assert result["status"] == "UNAVAILABLE"
    assert result["universe"]["status"] == "OVER_LIMIT"
    assert result["events"] == []
    assert calls == []


def test_disclosure_expected_is_projected_with_preserved_semantics(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(research_continuity_service, "_calendar", lambda code, fetched_at: _calendar("EXPECTED", appointment="2026-09-20"))
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["PERIODIC_REPORT"])
    event = _events(result, "PERIODIC_REPORT")[0]
    assert event["state"] == "EXPECTED"
    assert event["date_semantics"] == "DATE_ONLY"
    assert "不是公司保证日期" in event["title"]
    assert "APPOINTMENT_DATE_IS_NOT_A_COMPANY_GUARANTEE" in event["limitations"]


def test_disclosure_confirmed_is_observed_actual_event(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(research_continuity_service, "_calendar", lambda code, fetched_at: _calendar("CONFIRMED", actual="2026-09-08"))
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["PERIODIC_REPORT"])
    event = _events(result, "PERIODIC_REPORT")[0]
    assert event["state"] == "CONFIRMED"
    assert event["event_date"] == "2026-09-08"
    assert "不代表符合预期" in event["details"]["semantics"]


def test_disclosure_delayed_is_not_rendered_as_violation(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(research_continuity_service, "_calendar", lambda code, fetched_at: _calendar("DELAYED_SIGNAL", appointment="2026-09-01"))
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["PERIODIC_REPORT"])
    event = _events(result, "PERIODIC_REPORT")[0]
    assert event["state"] == "DELAYED_SIGNAL"
    assert "尚未见实际披露" in event["title"]
    assert "违规" not in event["title"]


def test_disclosure_provider_failure_is_error_not_no_record(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(research_continuity_service, "_calendar", lambda code, fetched_at: (_ for _ in ()).throw(RuntimeError("down")))
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["PERIODIC_REPORT"])
    source = result["sources"][0]
    assert result["status"] == "UNAVAILABLE"
    assert source["security_statuses"][0]["status"] == "ERROR"
    assert source["security_statuses"][0]["reason"] == "PROVIDER_FAILURE"


def test_future_lockup_is_upcoming_and_provider_fact_only(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "lockup_expiry", lambda code, **_: {
        "history": [], "upcoming": [{"date": "2026-09-20", "type": "首发原股东", "shares": 0, "able_shares": None, "ratio": 0}],
    })
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["LOCKUP_EXPIRY"])
    event = _events(result, "LOCKUP_EXPIRY")[0]
    assert event["state"] == "UPCOMING"
    assert event["details"]["shares"] == 0
    assert event["details"]["able_shares"] is None
    assert "PROVIDER_FACT_ONLY" in event["limitations"]


def test_past_lockup_is_history_not_upcoming(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "lockup_expiry", lambda code, **_: {
        "history": [{"date": "2026-09-01", "type": "定增", "shares": 10, "able_shares": 8, "ratio": 1}],
        "upcoming": [],
    })
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["LOCKUP_EXPIRY"])
    assert _events(result, "LOCKUP_EXPIRY")[0]["state"] == "HISTORY"


def test_future_dividend_requires_provider_status_for_upcoming(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "dividend_history", lambda code, **_: [
        {"date": "2026-09-20", "bonus_rmb": 1, "transfer_ratio": 0, "bonus_ratio": 0, "plan": "实施"},
        {"date": "2026-09-21", "bonus_rmb": 1, "transfer_ratio": 0, "bonus_ratio": 0, "plan": ""},
    ])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["DIVIDEND_BONUS"])
    states = {item["event_date"]: item["state"] for item in _events(result, "DIVIDEND_BONUS")}
    assert states == {"2026-09-20": "UPCOMING", "2026-09-21": "OBSERVED"}


def test_dividend_history_remains_history(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "dividend_history", lambda code, **_: [{
        "date": "2026-09-01", "bonus_rmb": 0, "transfer_ratio": 0, "bonus_ratio": None, "plan": "已实施",
    }])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["DIVIDEND_BONUS"])
    event = _events(result, "DIVIDEND_BONUS")[0]
    assert event["state"] == "HISTORY"
    assert event["details"]["bonus_rmb"] == 0


def test_recent_announcement_is_observed_publication(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "announcements", lambda code, **_: [{
        "date": "2026-09-08", "notice_at": "2026-09-08 10:00:00", "title": "一条很长的公告标题",
        "type": "定期报告", "url": "https://example.test/a",
    }])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    event = _events(result, "ANNOUNCEMENT")[0]
    assert event["state"] == "CONFIRMED"
    assert event["details"]["url"].startswith("https://")
    assert "OBSERVED_PUBLICATION_ONLY" in event["limitations"]


def test_future_announcement_is_not_promoted_to_calendar_prediction(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "announcements", lambda code, **_: [{
        "date": "2026-09-20", "title": "future", "type": "公告", "url": "https://example.test/f",
    }])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    assert _events(result, "ANNOUNCEMENT") == []


def test_announcement_without_date_fails_closed_as_source_error(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "announcements", lambda code, **_: [{
        "date": "", "title": "unknown date", "type": "公告", "url": "",
    }])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    assert _events(result, "ANNOUNCEMENT") == []
    assert result["status"] == "UNAVAILABLE"
    assert result["sources"][0]["security_statuses"][0]["status"] == "ERROR"


def test_one_source_failure_does_not_erase_other_source(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a"), _campaign("000002", "b")])
    monkeypatch.setattr(research_continuity_service, "_calendar", lambda code, fetched_at: _calendar("EXPECTED", appointment="2026-09-20"))
    monkeypatch.setattr(astock, "lockup_expiry", lambda code, **_: (_ for _ in ()).throw(RuntimeError("lockup down")) if code == "000002" else {"history": [], "upcoming": []})
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["PERIODIC_REPORT", "LOCKUP_EXPIRY"])
    assert result["status"] == "PARTIAL"
    assert len(_events(result, "PERIODIC_REPORT")) == 2
    lockup = next(item for item in result["sources"] if item["event_type"] == "LOCKUP_EXPIRY")
    assert lockup["status"] == "PARTIAL"


def test_event_order_is_deterministic(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a"), _campaign("000002", "b")])
    monkeypatch.setattr(astock, "announcements", lambda code, **_: [{"date": "2026-09-08", "title": code, "type": "公告", "url": ""}])
    first = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    second = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    assert first["events"] == second["events"]


def test_duplicate_provider_records_are_source_deduped(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    row = {"date": "2026-09-08", "title": "same", "type": "公告", "url": "https://example.test/a"}
    monkeypatch.setattr(astock, "announcements", lambda code, **_: [row, dict(row)])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    assert len(_events(result, "ANNOUNCEMENT")) == 1


def test_stockdata_adapter_strict_reads_keep_failure_distinct_from_empty(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(astock, "em_get", unavailable)
    assert astock.dividend_history("600001") == []
    with pytest.raises(RuntimeError, match="provider down"):
        astock.dividend_history("600001", strict=True)
    with pytest.raises(RuntimeError, match="provider down"):
        astock.lockup_expiry("600001", trade_date=AS_OF.isoformat(), strict=True)


def test_unknown_date_is_explicit_not_none_event_silence(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "dividend_history", lambda code, **_: [{
        "date": "", "bonus_rmb": None, "transfer_ratio": 0, "bonus_ratio": None, "plan": None,
    }])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["DIVIDEND_BONUS"])
    event = _events(result, "DIVIDEND_BONUS")[0]
    assert event["state"] == "UNKNOWN"
    assert event["event_date"] is None
    assert event["date_semantics"] == "UNKNOWN"
    assert event["details"]["bonus_rmb"] is None


def test_date_window_is_calendar_days_and_bounded(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    monkeypatch.setattr(astock, "announcements", lambda code, **_: [
        {"date": "2026-09-01", "title": "inside", "type": "公告", "url": ""},
        {"date": "2026-08-31", "title": "outside", "type": "公告", "url": ""},
    ])
    result = calendar.build_research_event_calendar(
        today=AS_OF, date_from="2026-09-01", date_to="2026-09-08", event_types=["ANNOUNCEMENT"],
    )
    assert [item["title"] for item in _events(result, "ANNOUNCEMENT")] == ["inside"]
    with pytest.raises(calendar.ResearchEventCalendarValidationError):
        calendar.build_research_event_calendar(today=AS_OF, date_from="2026-06-01")


def test_no_formal_state_writes_are_reported_as_zero(monkeypatch):
    _base(monkeypatch, [_campaign("600001", "a")])
    result = calendar.build_research_event_calendar(today=AS_OF, event_types=["ANNOUNCEMENT"])
    assert result["writes"] == {"campaign": 0, "thesis": 0, "evidence": 0, "decision": 0, "trade": 0, "account": 0}
    route = next(item for item in research_event_calendar_router.router.routes if item.path == "/api/research-events")
    assert route.methods == {"GET"}
