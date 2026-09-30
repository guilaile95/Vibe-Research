"""Offline regressions for quote validity, observation identity and dated breadth."""
import csv
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app
import astock
import data_health_event_store as events
import discovery_service as discovery
import market
import research_data_plane as rdp


def _quote(*, code="600519", price="10", change="1", stamp="20260930150000", identity=None):
    values = ["0"] * 55
    values[1], values[2], values[3] = "Synthetic QA", identity or code, price
    values[30], values[32] = stamp, change
    return f'v_{astock.get_prefix(code)}{code}="' + "~".join(values) + '";'


@pytest.fixture
def health(monkeypatch):
    calls = []
    for kind in ("success", "partial", "failure"):
        monkeypatch.setattr(events, "record_" + kind, lambda *a, _kind=kind, **kw: calls.append((_kind, a)))
    return calls


@pytest.mark.parametrize("price", ["", "-", "NaN", "Infinity", "-Infinity", "0", "-10"])
def test_invalid_quote_never_records_success(monkeypatch, health, price):
    monkeypatch.setattr(astock, "_fetch_gtimg", lambda _: _quote(price=price))
    response = TestClient(app.app).get("/api/quote?codes=600519")
    assert response.status_code == 200
    assert response.json() == {"data": {}, "status": "unavailable"}
    assert health == [("failure", ("quotes", "SOURCE_UNAVAILABLE"))]


@pytest.mark.parametrize("change", ["", "-", "NaN", "Infinity"])
def test_optional_unknown_is_null_not_zero(change):
    quote = astock._parse_gtimg(_quote(change=change))["600519"]
    assert quote["change_pct"] is None
    assert quote["price"] == 10
    assert quote["data_time"] == "2026-09-30T15:00:00+08:00"
    assert quote["trade_date"] == "2026-09-30"
    assert astock._parse_gtimg(_quote(change="0"))["600519"]["change_pct"] == 0


def test_quote_identity_mismatch_is_rejected():
    assert astock._parse_gtimg(_quote(identity="000001")) == {}


def test_mixed_batch_and_old_source_time_are_partial(monkeypatch, health):
    monkeypatch.setattr(astock, "_fetch_gtimg", lambda _: _quote(stamp="20240102150000") + _quote(code="000001", price="NaN"))
    response = TestClient(app.app).get("/api/quote?codes=600519,000001")
    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert list(response.json()["data"]) == ["600519"]
    assert response.json()["data"]["600519"]["trade_date"] == "2024-01-02"
    assert health == [("partial", ("quotes",))]


def test_quote_public_error_does_not_expose_provider_details(monkeypatch, health):
    def broken(_):
        raise RuntimeError("ProxyError https://provider.invalid?token=SYNTHETIC_SECRET")
    monkeypatch.setattr(astock, "_fetch_gtimg", broken)
    response = TestClient(app.app).get("/api/quote?codes=600519")
    assert response.status_code == 502
    assert response.json() == {"detail": "行情源暂不可用"}
    assert health == [("failure", ("quotes", "SOURCE_UNAVAILABLE"))]


def test_bse_routing_preserves_bshares_and_etfs(monkeypatch):
    calls = []
    monkeypatch.setattr(astock, "_fetch_gtimg", lambda codes: calls.append(codes) or "")
    astock.tencent_quote(["920000", "430047", "832000", "600519", "900001", "510300", "159915"])
    assert calls == [["bj920000", "bj430047", "bj832000", "sh600519", "sh900001", "sh510300", "sz159915"]]


def test_cached_observation_is_isolated_and_survives_open_boundary(monkeypatch):
    clock = SimpleNamespace(seconds=1000., instant=datetime(2026, 9, 30, 1, 29, tzinfo=timezone.utc))
    monkeypatch.setattr(market, "time", SimpleNamespace(time=lambda: clock.seconds))
    monkeypatch.setattr(market, "datetime", SimpleNamespace(now=lambda tz: clock.instant.astimezone(tz)))
    monkeypatch.setattr(market, "_CACHE", {})
    source = [{"code": "600519", "name": "Synthetic QA", "price": 10., "change_pct": 1., "amount": 10000., "turnover_pct": 1.}]
    calls = []
    monkeypatch.setattr(astock, "a_share_snapshot", lambda: calls.append(1) or source)
    providers = discovery.DiscoveryProviders(
        market_snapshot=market.get_a_share_snapshot_observation,
        full_market=lambda: {"status": "normal", "as_of": "2026-09-29", "rows": [{"code": "600519", "latest_date": "2026-09-29"}]},
        financials=lambda _: {}, announcements=lambda _: [],
        native_intel=lambda _: {"status": "unavailable", "stats": {}, "terms": []})
    first = discovery.run_discovery(providers=providers, now=clock.instant)
    breadth = market.get_market_breadth()
    copy = market.get_a_share_snapshot_observation()
    copy["rows"][0]["price"] = 999
    copy["observed_at"] = "corrupted"
    source[0]["price"] = 888
    clock.seconds += 120
    clock.instant += timedelta(minutes=2)
    second = discovery.run_discovery(providers=providers, now=clock.instant)
    assert first["as_of"] == second["as_of"] == "2026-09-29"
    assert first["fetched_at"] == second["fetched_at"] == "2026-09-30T01:29:00+00:00"
    assert market.get_market_breadth()["fetched_at"] == breadth["fetched_at"] == "2026-09-30 09:29:00"
    assert market.get_a_share_snapshot()[0]["price"] == 10
    assert calls == [1]
    assert next(x for x in second["datasets"] if x["dataset_id"] == "research_data_plane.full_market")["status"] == "normal"


def test_plain_snapshot_list_does_not_invent_observation_time():
    providers = discovery.DiscoveryProviders(
        market_snapshot=lambda: [{"code": "600519", "name": "Synthetic QA", "price": 10}],
        full_market=lambda: {"status": "unavailable", "rows": []}, financials=lambda _: {},
        announcements=lambda _: [], native_intel=lambda _: {"status": "unavailable", "stats": {}, "terms": []})
    result = discovery.run_discovery(providers=providers, now=datetime(2026, 9, 30, 2, tzinfo=timezone.utc))
    assert result["as_of"] is None
    assert result["fetched_at"] is None
    assert result["status"] == "partial"


def test_breadth_excludes_stale_rows_but_retains_last_observation(tmp_path):
    source = tmp_path / "bars.csv"
    with source.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "trade_date", "open", "high", "low", "close", "volume"])
        for code, start, up in [("600519", date(2026, 8, 1), False), ("000001", date(2026, 1, 1), True)]:
            for i in range(65):
                close = 100 + i if up else 200 - i
                writer.writerow([code, (start + timedelta(days=i)).isoformat(), close, close + 1, close - 1, close, 1000])
    rdp.import_csv(source, root=tmp_path / "rdp")
    result = rdp.query_full_market(root=tmp_path / "rdp")
    assert result["status"] == "partial"
    assert result["as_of"] == "2026-10-04"
    stale = next(row for row in result["rows"] if row["code"] == "000001")
    assert stale["latest_date"] == "2026-03-06"
    assert stale["ma20"] is not None
    assert stale["status"] == "stale"
    assert set(stale["metric_status"].values()) == {"STALE"}
    for metric in ("ma20", "ma60"):
        assert result["breadth"][metric]["breadth"] == 0
        assert result["breadth"][metric]["evaluable_count"] == 1
        assert result["breadth"][metric]["stale_count"] == 1
        assert result["breadth"][metric]["current_count"] == 1


def test_current_valid_quote_records_success_after_json_validation(monkeypatch, health):
    monkeypatch.setattr(app, "datetime", SimpleNamespace(now=lambda tz: datetime(2026, 9, 30, 8, tzinfo=tz)))
    monkeypatch.setattr(astock, "_fetch_gtimg", lambda _: _quote())
    response = TestClient(app.app).get("/api/quote?codes=600519")
    assert response.status_code == 200
    assert response.json()["status"] == "normal"
    assert health == [("success", ("quotes",))]


def test_board_cache_preserves_fetch_timestamp(monkeypatch):
    clock = SimpleNamespace(instant=datetime(2026, 9, 30, 10, tzinfo=market.BEIJING))
    monkeypatch.setattr(market, "datetime", SimpleNamespace(now=lambda tz: clock.instant))
    monkeypatch.setattr(market, "_CACHE", {})
    monkeypatch.setattr(astock, "board_ranking", lambda *a, **kw: {"total": 1, "ranked_count": 1, "unknown_count": 0, "top": [], "bottom": []})
    first = market.get_board_ranking()
    clock.instant += timedelta(minutes=4)
    assert market.get_board_ranking()["fetched_at"] == first["fetched_at"] == "2026-09-30 10:00:00"
