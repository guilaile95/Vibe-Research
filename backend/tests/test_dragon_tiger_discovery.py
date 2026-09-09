from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import dragon_tiger_discovery as dtd
import technical_indicators_router


class _Response:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self):
        return self._payload


def _row(*, date: str, code: str = "000001", reason: str = "reason", net=123.0, trade_id: str | None = None, turnover=1.5):
    row = {
        "TRADE_DATE": date,
        "SECURITY_CODE": code,
        "SECURITY_NAME_ABBR": "测试标的",
        "EXPLANATION": reason,
        "BILLBOARD_NET_AMT": net,
        "TURNOVERRATE": turnover,
    }
    if trade_id is not None:
        row["TRADE_ID"] = trade_id
    return row


def _payload(rows: list[dict], *, count: int | None = None, pages: int | None = None, code=0, success=True):
    return {
        "code": code,
        "success": success,
        "message": "ok",
        "result": None if pages is None else {"count": count if count is not None else len(rows), "pages": pages, "data": rows},
    }


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr(dtd, "_fetched_at", lambda: "2026-09-09T00:00:00.000000Z")


def test_latest_source_date_and_exact_date_pages_are_bounded_and_security_free(monkeypatch):
    monkeypatch.setattr(dtd, "PAGE_SIZE", 2)
    monkeypatch.setattr(dtd, "MAX_PAGES", 2)
    monkeypatch.setattr(dtd, "MAX_ROWS", 4)
    latest_rows = [_row(date="2026-09-09", trade_id="latest-1"), _row(date="2026-09-09", trade_id="latest-2")]
    exact_p1 = [_row(date="2026-09-09", reason="reason-a", net=None, trade_id="a"), _row(date="2026-09-09", reason="reason-b", net=0, trade_id="b")]
    exact_p2 = [_row(date="2026-09-09", code="600001", reason="reason-c", trade_id="c")]
    calls = []

    def fake_get(_url, *, params, **_kwargs):
        calls.append(dict(params))
        if params["filter"] == "":
            return _Response(_payload(latest_rows, count=10, pages=5))
        if params["pageNumber"] == "1":
            return _Response(_payload(exact_p1, count=3, pages=2))
        return _Response(_payload(exact_p2, count=3, pages=2))

    monkeypatch.setattr(dtd.astock, "em_get", fake_get)
    result = dtd.build_dragon_tiger_discovery()

    assert result["status"] == "NORMAL"
    assert result["trade_date"] == "2026-09-09"
    assert result["completeness"]["status"] == "COMPLETE"
    assert result["pagination"] == {
        "page_size": 2,
        "max_pages": 2,
        "max_rows": 4,
        "fetched_pages": 2,
        "source_count": 3,
        "source_pages": 2,
        "returned_rows": 3,
        "truncated": False,
    }
    assert [row["billboard_net_amount"] for row in result["rows"]] == [None, 0.0, 123.0]
    assert len({row["source_record_identity"] for row in result["rows"]}) == 3
    assert len(calls) == 3
    assert all("SECURITY_CODE" not in call for call in calls)
    assert all("SECURITY_CODE" not in call["filter"] for call in calls)
    assert calls[0]["filter"] == ""
    assert calls[1]["filter"] == "(TRADE_DATE='2026-09-09')"


def test_cross_page_duplicate_identity_fails_closed_with_plausible_metadata(monkeypatch):
    monkeypatch.setattr(dtd, "PAGE_SIZE", 2)
    page_one = [
        _row(date="2026-09-09", reason="reason-a", trade_id="a"),
        _row(date="2026-09-09", reason="reason-b", trade_id="b"),
    ]
    page_two = [_row(date="2026-09-09", reason="reason-b", trade_id="b")]

    def fake_get(_url, *, params, **_kwargs):
        rows = page_one if params["pageNumber"] == "1" else page_two
        return _Response(_payload(rows, count=3, pages=2))

    monkeypatch.setattr(dtd.astock, "em_get", fake_get)
    result = dtd.build_dragon_tiger_discovery("2026-09-09")

    assert result["status"] == "UNAVAILABLE"
    assert result["completeness"]["status"] == "UNAVAILABLE"
    assert result["limitations"] == [dtd.SOURCE_PAGE_IDENTITY_OVERLAP]
    assert result["rows"] == []
    assert result["formal_state_write"]["performed"] is False


def test_explicit_date_skips_latest_resolution_and_retains_duplicate_reasons(monkeypatch):
    rows = [
        _row(date="2026-09-08", reason="reason-a", trade_id="a"),
        _row(date="2026-09-08", reason="reason-b", trade_id="b"),
    ]
    calls = []

    def fake_get(_url, *, params, **_kwargs):
        calls.append(dict(params))
        return _Response(_payload(rows, count=2, pages=1))

    monkeypatch.setattr(dtd.astock, "em_get", fake_get)
    result = dtd.build_dragon_tiger_discovery("2026-09-08")

    assert result["status"] == "NORMAL"
    assert result["trade_date"] == "2026-09-08"
    assert [row["reason"] for row in result["rows"]] == ["reason-a", "reason-b"]
    assert len(calls) == 1
    assert calls[0]["filter"] == "(TRADE_DATE='2026-09-08')"


def test_empty_code_is_distinct_from_provider_failure(monkeypatch):
    monkeypatch.setattr(
        dtd.astock,
        "em_get",
        lambda *_args, **_kwargs: _Response(_payload([], code=9201, success=False)),
    )
    empty = dtd.build_dragon_tiger_discovery("2026-09-06")
    assert empty["status"] == "EMPTY"
    assert empty["rows"] == []
    assert empty["limitations"] == ["NO_RECORD_FOR_TRADE_DATE"]

    monkeypatch.setattr(
        dtd.astock,
        "em_get",
        lambda *_args, **_kwargs: _Response(_payload([], code=9501, success=False)),
    )
    unavailable = dtd.build_dragon_tiger_discovery("2026-09-06")
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["limitations"] == ["SOURCE_UNAVAILABLE"]


def test_pagination_bound_is_explicitly_partial(monkeypatch):
    monkeypatch.setattr(dtd, "PAGE_SIZE", 2)
    monkeypatch.setattr(dtd, "MAX_PAGES", 1)
    monkeypatch.setattr(dtd, "MAX_ROWS", 2)
    calls = []

    def fake_get(_url, *, params, **_kwargs):
        calls.append(dict(params))
        return _Response(_payload([_row(date="2026-09-09", trade_id="a"), _row(date="2026-09-09", trade_id="b")], count=5, pages=3))

    monkeypatch.setattr(dtd.astock, "em_get", fake_get)
    result = dtd.build_dragon_tiger_discovery("2026-09-09")

    assert result["status"] == "PARTIAL"
    assert result["completeness"]["status"] == "TRUNCATED"
    assert result["completeness"]["truncated"] is True
    assert result["pagination"]["source_count"] == 5
    assert len(calls) == 1
    assert dtd.SOURCE_PAGE_IDENTITY_OVERLAP not in result["limitations"]


def test_truncated_pagination_exposes_identity_overlap_without_claiming_complete(monkeypatch):
    monkeypatch.setattr(dtd, "PAGE_SIZE", 2)
    monkeypatch.setattr(dtd, "MAX_PAGES", 2)
    monkeypatch.setattr(dtd, "MAX_ROWS", 4)
    page_one = [
        _row(date="2026-09-09", trade_id="a"),
        _row(date="2026-09-09", trade_id="b"),
    ]
    page_two = [
        _row(date="2026-09-09", reason="reason-b-again", trade_id="b"),
        _row(date="2026-09-09", trade_id="c"),
    ]

    def fake_get(_url, *, params, **_kwargs):
        rows = page_one if params["pageNumber"] == "1" else page_two
        return _Response(_payload(rows, count=5, pages=3))

    monkeypatch.setattr(dtd.astock, "em_get", fake_get)
    result = dtd.build_dragon_tiger_discovery("2026-09-09")

    assert result["status"] == "PARTIAL"
    assert result["completeness"]["status"] == "TRUNCATED"
    assert result["completeness"]["truncated"] is True
    assert dtd.SOURCE_PAGE_IDENTITY_OVERLAP in result["limitations"]
    assert len(result["rows"]) == 4


def test_market_route_wraps_read_only_envelope_and_existing_per_security_route_is_unchanged(monkeypatch):
    envelope = {
        "schema_version": dtd.SCHEMA_VERSION,
        "status": "EMPTY",
        "rows": [],
        "formal_state_write": {"performed": False, "scope": "read-only market discovery"},
    }
    monkeypatch.setattr(technical_indicators_router.dtd, "build_dragon_tiger_discovery", lambda trade_date: envelope)
    client = TestClient(app_module.app)
    response = client.get("/api/market/dragon-tiger?trade_date=2026-09-05")
    assert response.status_code == 200
    assert response.json()["data"] == envelope

    sentinel = {"records": [], "seats": {"buy": [], "sell": []}, "institution": {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}}
    monkeypatch.setattr(app_module.astock, "dragon_tiger_board", lambda code: sentinel)
    per_security = client.get("/api/dragon-tiger?code=600001")
    assert per_security.status_code == 200
    assert per_security.json()["data"] == sentinel


def test_invalid_trade_date_is_rejected():
    with pytest.raises(dtd.DragonTigerDiscoveryValidationError):
        dtd.normalize_trade_date("2026-9-5")
