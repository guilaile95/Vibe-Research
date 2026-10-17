"""Offline source-to-sink acceptance for the legacy four-pool observation path."""
from __future__ import annotations

import copy
import socket
from datetime import datetime, timezone

import pytest

import ai_tools
import astock
import daily_review
import market
import trade_calendar
from decision_cockpit_signals import evaluate_market_short

ROW = {"c": "600001", "n": "Fixture", "lbc": 2, "p": 10000,
       "zdp": 10, "amount": 1000, "ltsz": 2000, "hybk": "Fixture"}
AS_OF = "2026-10-09T07:10:00+00:00"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    def blocked(*args, **kwargs):
        raise AssertionError("Network forbidden in pool acceptance")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(market, "_CACHE", {})
    monkeypatch.setattr(daily_review, "_review_cache", {})
    monkeypatch.setattr(astock, "em_get", blocked)


@pytest.fixture
def review_clock(monkeypatch):
    """Keep review session checks and cache insertion timestamps on one fixture clock."""
    class Clock(datetime):
        current = datetime.fromisoformat(AS_OF)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz or timezone.utc)

    monkeypatch.setattr(daily_review, "datetime", Clock)
    monkeypatch.setattr(daily_review.time, "time", lambda: Clock.current.timestamp())
    return Clock


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return copy.deepcopy(self.payload)


def payload(*, date="20261009", pool=None, reported_date=True):
    data = {"qdate": date, "pool": [copy.deepcopy(ROW)] if pool is None else pool}
    if reported_date:
        data["trade_date"] = date
    return {"rc": 0, "data": data}


def install(monkeypatch, fn):
    calls = []
    def get(url, params, **kwargs):
        ep = url.rsplit("/", 1)[-1]
        calls.append((ep, params["date"]))
        out = fn(ep, params["date"])
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, Response) else Response(out)
    monkeypatch.setattr(astock, "em_get", get)
    return calls


def fetch():
    return astock.em_zt_topic_observation("getTopicZTPool", "20261009", as_of=AS_OF)


@pytest.mark.parametrize("raw,reason", [
    ({"rc": 102, "data": None}, "BUSINESS_STATUS_UNAVAILABLE"),
    ({"rc": True, "data": {}}, "BUSINESS_STATUS_UNAVAILABLE"),
    ({"rc": "0", "data": {}}, "BUSINESS_STATUS_UNAVAILABLE"),
    ({"data": {}}, "BUSINESS_STATUS_UNAVAILABLE"),
    ({"rc": 0, "data": None}, "DATA_UNAVAILABLE"),
    ({"rc": 0, "data": {}}, "POOL_UNAVAILABLE"),
    ({"rc": 0, "data": {"pool": None}}, "POOL_UNAVAILABLE"),
    ({"rc": 0, "data": {"pool": "wrong"}}, "INVALID_POOL"),
    ({"rc": 0, "data": {"pool": [None]}}, "INVALID_POOL_ROW"),
    (payload(pool=[ROW, ROW]), "DUPLICATE_POOL_ROW"),
    (payload(pool=[{**ROW, "lbc": True}]), "INVALID_BOARD_COUNT"),
    (payload(date="20261008"), "SOURCE_SESSION_UNAVAILABLE"),
    (payload(date="20260230"), "INVALID_PROVIDER_DATE"),
    (Response(payload(), 503), "HTTP_ERROR"),
    (Response(ValueError("secret parse URL")), "PARSE_ERROR"),
    (TimeoutError("secret transport URL"), "TRANSPORT_ERROR"),
])
def test_failures_are_unknown(monkeypatch, raw, reason):
    install(monkeypatch, lambda *args: raw)
    out = fetch()
    assert out["status"] == "unavailable"
    assert out["count"] is None and out["rows"] == []
    assert out["reason_codes"] == [reason]
    assert "secret" not in str(out)


def test_business_date_conflict_and_null_dates(monkeypatch):
    raw = payload()
    raw["date"] = "2026-09-30"
    install(monkeypatch, lambda *args: raw)
    assert fetch()["reason_codes"] == ["BUSINESS_DATE_MISMATCH"]
    raw = payload(reported_date=False)
    raw["data"]["trade_date"] = None
    assert fetch()["date_verified"] is False


@pytest.mark.parametrize("endpoint", ["getTopicZTPool", "getTopicZBPool", "getTopicDTPool", "getYesterdayZTPool"])
def test_explicit_empty_is_observed_not_zero(monkeypatch, endpoint):
    calls = install(monkeypatch, lambda *args: payload(pool=[]))
    out = astock.em_zt_topic_observation(endpoint, "20261009", as_of=AS_OF)
    assert out["observed_empty"] is True
    assert out["observed_row_count"] == 0
    assert out["count"] is None and out["status"] == "partial"
    assert out["completeness_verified"] is False
    assert len(calls) == 1


def test_historical_qdate_is_not_business_date(monkeypatch):
    install(monkeypatch, lambda *args: payload(reported_date=False))
    out = astock.em_zt_topic_observation("getTopicZTPool", "20260930", as_of=AS_OF)
    assert out["count"] == 1 and out["status"] == "partial"
    assert out["provider_latest_trade_date"] == "2026-10-09"
    assert out["source_business_date"] is None
    assert out["requested_trade_date"] == "2026-09-30"
    assert out["date_basis"] == "requested_session_inferred"


@pytest.mark.parametrize("instant,session", [
    ("2026-10-10T04:00:00Z", "20261009"),
    ("2026-10-01T04:00:00Z", "20260930"),
    ("2026-10-12T01:10:00Z", "20261009"),
    ("2026-10-12T01:25:00Z", "20261009"),
    ("2026-10-12T01:29:59Z", "20261009"),
    ("2026-10-12T01:30:00Z", "20261012"),
])
def test_calendar_resolves_before_fetch(monkeypatch, instant, session):
    calls = install(monkeypatch, lambda ep, d: payload(date=d))
    out = market._emotion(instant)
    assert len(calls) == 4 and {d for _, d in calls} == {session}
    assert out["date"].replace("-", "") == session
    assert out["as_of"] == instant
    assert out["status"] == "partial"
    assert out["source_business_date"] is None and out["date_verified"] is False


@pytest.mark.parametrize("want,instant", [
    ("20261010", "2026-10-10T04:00:00Z"),
    ("20261001", "2026-10-01T04:00:00Z"),
    ("20261012", "2026-10-12T01:29:59Z"),
])
def test_direct_observation_cannot_bypass_calendar(monkeypatch, want, instant):
    out = astock.em_zt_topic_observation("getTopicZTPool", want, as_of=instant)
    assert out["status"] == "unavailable"
    assert out["fetched_at"] is None


def test_calendar_unavailable_no_fetch(monkeypatch):
    monkeypatch.setattr(trade_calendar, "_load_calendar", lambda: None)
    out = market._emotion(AS_OF)
    assert out["status"] == "unavailable" and out["zt_count"] is None
    assert out["date"] == ""


def test_empty_today_never_rolls_back(monkeypatch):
    calls = install(monkeypatch, lambda ep, d: payload(pool=[] if d == "20261009" else [ROW]))
    out = market._emotion(AS_OF)
    assert out["date"] == "2026-10-09" and out["zt_count"] is None
    assert out["lianban_count"] is None and out["seal_rate"] is None
    assert out["status"] == "partial" and out["pool_observations"]["zt"]["observed_empty"]
    assert {d for _, d in calls} == {"20261009"}


@pytest.mark.parametrize("failed,null_metrics,kept_metrics", [
    ("getTopicDTPool", ["dt_count"], ["zt_count", "seal_rate", "break_rate", "promotion_rate"]),
    ("getTopicZBPool", ["zb_count", "seal_rate", "break_rate"], ["zt_count", "dt_count", "promotion_rate"]),
    ("getYesterdayZTPool", ["yzt_count", "promotion_rate"], ["zt_count", "dt_count", "seal_rate"]),
    ("getTopicZTPool", ["zt_count", "max_boards", "lianban_count", "seal_rate", "break_rate", "promotion_rate"], ["dt_count", "zb_count", "yzt_count"]),
])
def test_only_dependent_metrics_become_unknown(monkeypatch, failed, null_metrics, kept_metrics):
    install(monkeypatch, lambda ep, d: {"rc": 102, "data": None} if ep == failed else payload())
    out = market._emotion(AS_OF)
    assert out["status"] == "partial"
    for key in null_metrics:
        assert out[key] is None, key
    for key in kept_metrics:
        assert out[key] is not None, key
    if failed == "getTopicZTPool":
        assert out["lianban_stocks"] == []


def test_source_to_review_overview_api_ai_and_cockpit(monkeypatch):
    from test_daily_review import _install_all_ok, _breadth_env
    from app import market_emotion
    install(monkeypatch, lambda ep, d: payload(reported_date=False) if ep == "getTopicZTPool" else {"rc": 102, "data": None})
    out = market._emotion(AS_OF)
    _install_all_ok(monkeypatch)
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: out)
    breadth = _breadth_env(trade_date="2026-10-09")
    monkeypatch.setattr(market, "get_market_breadth", lambda: breadth)
    review = daily_review._build_daily_review()
    assert review["short_term_emotion"]["status"] == "partial"
    data = review["short_term_emotion"]["data"]
    assert data["zt_count"] == 1 and data["dt_count"] is None
    assert data["seal_rate"] is None and data["date_verified"] is False
    assert review["trade_date"] == "2026-10-09"  # breadth, not inferred emotion
    assert market._sentiment()["status"] == "partial"
    assert market._sentiment()["emotion_provenance"]["date_basis"] == "requested_session_inferred"
    assert market_emotion()["data"] == out
    assert ai_tools._market({"scope": "emotion"}) == out
    assert evaluate_market_short(breadth, out)["status"] == "partial"
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env())
    assert daily_review._build_daily_review()["trade_date"] is None


def test_metadata_only_unavailable_is_not_healthy(monkeypatch):
    from test_daily_review import _install_all_ok, _breadth_env
    _install_all_ok(monkeypatch)
    out = {"status": "unavailable", "warnings": ["不可用"], "zt_count": None, "date": "2026-10-09"}
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: out)
    assert daily_review._build_daily_review()["short_term_emotion"]["status"] == "unavailable"
    assert market._sentiment()["status"] == "partial"
    summary = evaluate_market_short(_breadth_env(), out)
    assert summary["status"] == "partial" and summary["data"]["emotion"] is None


def test_cockpit_does_not_extract_unavailable_lianban(monkeypatch):
    import decision_cockpit_service as svc
    monkeypatch.setattr(svc.watchlist_store, "load_watchlist", lambda: [])
    monkeypatch.setattr(svc, "_get_sector_codes", lambda: [])
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: {"status": "unavailable", "lianban_stocks": [ROW]})
    monkeypatch.setattr(market, "get_market_breadth", lambda: {})
    monkeypatch.setattr(market, "get_turnover_top", lambda: {})
    assert svc._get_candidate_pool_inputs(holdings=[])["lianban"] == []


def test_legacy_saved_projection_and_zero_remain_compatible(monkeypatch):
    from test_daily_review import _install_all_ok, _emotion, _breadth_env
    _install_all_ok(monkeypatch)
    old = _emotion(zt=0)
    original = copy.deepcopy(old)
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: old)
    review = daily_review._build_daily_review()
    assert review["short_term_emotion"]["status"] == "normal"
    assert review["short_term_emotion"]["data"]["zt_count"] == 0
    assert review["trade_date"] == old["date"]
    assert evaluate_market_short(_breadth_env(), old)["status"] == "normal"
    assert old == original


def test_legacy_list_api_unchanged(monkeypatch):
    install(monkeypatch, lambda *args: payload())
    assert astock.em_zt_topic_pool("getTopicZTPool", "20261009") == [ROW]
    install(monkeypatch, lambda *args: TimeoutError())
    assert astock.em_zt_topic_pool("getTopicZTPool", "20261009") == []


def test_cache_retry_and_overview_session_boundary(monkeypatch):
    from test_daily_review import _breadth_env
    class Clock(datetime):
        current = datetime.fromisoformat("2026-10-12T01:29:59+00:00")
        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz or timezone.utc)
    monkeypatch.setattr(market, "datetime", Clock)
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env())
    monkeypatch.setattr(market, "_sectors", lambda: [{"name": "Fixture"}])
    calls = install(monkeypatch, lambda ep, d: payload(date=d))
    assert market.get_overview()["sentiment"]["date"] == "2026-10-09"
    market.get_overview()
    assert len(calls) == 4
    Clock.current = datetime.fromisoformat("2026-10-12T01:30:00+00:00")
    assert market.get_overview()["sentiment"]["date"] == "2026-10-12"
    assert len(calls) == 8
    market._CACHE.clear()
    calls = install(monkeypatch, lambda *args: {"rc": 102, "data": None})
    assert market.get_overview()["sentiment"]["status"] == "partial"
    assert market.get_overview()["sentiment"]["status"] == "partial"
    assert len(calls) == 8  # neither outer overview nor inner failure cached


def test_reported_date_does_not_grant_provider_authority(monkeypatch):
    install(monkeypatch, lambda *args: payload())
    out = fetch()
    assert out["provider_reported_dates"] == ["2026-10-09"]
    assert out["source_business_date"] is None and out["date_verified"] is False
    assert out["status"] == "partial"


def test_failure_provenance_survives_review_envelope(monkeypatch):
    from test_daily_review import _install_all_ok
    install(monkeypatch, lambda *args: Response(payload(), 503))
    out = market._emotion(AS_OF)
    _install_all_ok(monkeypatch)
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: out)
    emotion = daily_review._build_daily_review()["short_term_emotion"]
    assert emotion["data"] is None and emotion["status"] == "unavailable"
    provenance = emotion["provenance"]
    assert provenance["as_of"] == AS_OF
    assert provenance["pool_observations"]["zt"]["http_status"] == 503
    assert provenance["pool_observations"]["zt"]["reason_codes"] == ["HTTP_ERROR"]


def _old_and_qualified_reviews(monkeypatch):
    from test_daily_review import _install_all_ok
    install(monkeypatch, lambda ep, d: payload())
    observation = market._emotion(AS_OF)
    _install_all_ok(monkeypatch)
    old = daily_review._build_daily_review()
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: observation)
    new = daily_review._build_daily_review()
    return old, new


def test_qualified_refresh_replaces_legacy_normal_memory_and_latest_only(monkeypatch, tmp_path, review_clock):
    import daily_review_cache as cache
    import time
    old, new = _old_and_qualified_reviews(monkeypatch)
    assert old["status"] == "normal" and new["status"] == "partial"
    # Sentinel models an existing saved-history file: latest refresh never touches it.
    history = tmp_path / "daily_reviews.sqlite3"
    history.write_bytes(b"immutable historical sentinel")
    assert cache.save_latest_review(old, saved_at=old["generated_at"])
    daily_review._review_cache[daily_review._REVIEW_CACHE_KEY] = (time.time(), copy.deepcopy(old))
    assert daily_review._should_replace_memory(new)
    assert daily_review._refresh_accepts_result(new) == (True, "qualified_pool_provenance_update")
    monkeypatch.setattr(daily_review, "_build_daily_review", lambda: copy.deepcopy(new))
    result = daily_review.refresh_daily_review_for_display()
    assert result["data"]["status"] == "partial"
    assert result["data"]["short_term_emotion"]["data"]["date_verified"] is False
    assert cache.load_latest_review()[0] == result["data"]
    assert daily_review._cached_review() == result["data"]
    assert history.read_bytes() == b"immutable historical sentinel"


@pytest.mark.parametrize("degradation", ["empty", "failed_pool", "missing_pool", "other_partial", "malformed_health", "unavailable", "unsupported_date", "dishonest_health", "empty_flag", "count_mismatch"])
def test_real_degradation_cannot_use_qualification_exception(monkeypatch, degradation):
    import daily_review_cache as cache
    old, new = _old_and_qualified_reviews(monkeypatch)
    provenance = new["short_term_emotion"]["provenance"]
    if degradation == "empty":
        provenance["pool_observations"]["dt"].update(count=None, reason_codes=["OBSERVED_EMPTY_UNVERIFIED"])
    elif degradation == "failed_pool":
        provenance["pool_observations"]["dt"].update(count=None, status="unavailable", reason_codes=["TRANSPORT_ERROR"])
    elif degradation == "missing_pool":
        del provenance["pool_observations"]["dt"]
    elif degradation == "other_partial":
        new["data_health"]["components"]["breadth"] = "partial"
    elif degradation == "malformed_health":
        new["data_health"] = {"components": []}
    elif degradation == "unavailable":
        new["data_health"]["components"]["emotion"] = "unavailable"
    elif degradation == "dishonest_health":
        new["market_environment"]["breadth"]["status"] = "partial"
    elif degradation == "empty_flag":
        provenance["pool_observations"]["dt"]["observed_empty"] = True
    elif degradation == "count_mismatch":
        new["short_term_emotion"]["data"]["dt_count"] = None
    else:
        provenance.update(date="2030-01-01", as_of="2030-01-01T07:00:00Z")
    assert not cache.qualified_pool_replaces_normal(new, old)
    assert not cache.should_persist_review(new, old)


def test_current_verified_normal_is_preserved_but_prior_session_can_refresh(monkeypatch):
    import daily_review_cache as cache
    import time
    old, new = _old_and_qualified_reviews(monkeypatch)
    old["short_term_emotion"]["provenance"].update(date="2026-10-09", source_business_date="2026-10-09", date_verified=True)
    assert not cache.should_persist_review(new, old)
    assert cache.save_latest_review(old, saved_at=old["generated_at"])
    daily_review._review_cache[daily_review._REVIEW_CACHE_KEY] = (time.time(), copy.deepcopy(old))
    assert not daily_review._should_replace_memory(new)
    assert daily_review._refresh_accepts_result(new)[0] is False
    daily_review._review_cache.clear()
    assert not daily_review._should_replace_memory(new)  # disk-only current verified normal also protected
    old["short_term_emotion"]["provenance"].update(date="2026-09-30", source_business_date="2026-09-30")
    assert cache.qualified_pool_replaces_normal(new, old)


@pytest.mark.parametrize("legacy", [False, True])
def test_review_cache_crossing_0930_is_stale_and_read_only_does_not_write(monkeypatch, legacy, review_clock):
    import daily_review_cache as cache
    import push2_guard
    from pathlib import Path
    old, qualified = _old_and_qualified_reviews(monkeypatch)
    value = old if legacy else qualified
    Clock = review_clock
    Clock.current = datetime.fromisoformat("2026-10-12T01:29:59+00:00")
    assert cache.save_latest_review(value, saved_at=value["generated_at"])
    daily_review._review_cache[daily_review._REVIEW_CACHE_KEY] = (Clock.current.timestamp(), copy.deepcopy(value))
    assert daily_review._cached_review() is not None
    before_memory = copy.deepcopy(daily_review._review_cache)
    path = Path(cache.cache_path())
    before_disk = path.read_bytes()
    Clock.current = datetime.fromisoformat("2026-10-12T01:30:00+00:00")
    # A one-second-old package is rejected by the session boundary, not its TTL.
    assert Clock.current.timestamp() - before_memory[daily_review._REVIEW_CACHE_KEY][0] == 1
    assert daily_review._REVIEW_TTL > 1
    with push2_guard.read_only():
        assert daily_review._cached_review() is None
        assert daily_review._cached_review_age_seconds() is None
    assert daily_review._review_cache == before_memory
    assert path.read_bytes() == before_disk
    monkeypatch.setattr(daily_review, "_kick_background_refresh", lambda: False)
    display = daily_review.get_daily_review_for_display()
    assert display["cache_meta"]["stale"] is True
    assert display["cache_meta"]["source"] == "persisted"
    assert path.read_bytes() == before_disk


def test_qualified_partial_overview_remains_read_only_reusable(monkeypatch):
    import push2_guard
    from test_daily_review import _breadth_env
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(AS_OF).astimezone(tz or timezone.utc)
    monkeypatch.setattr(market, "datetime", Clock)
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env())
    monkeypatch.setattr(market, "_sectors", lambda: [{"name": "Fixture"}])
    calls = install(monkeypatch, lambda ep, d: payload())
    original = market.get_overview()
    assert original["sentiment"]["status"] == "partial"
    assert len(calls) == 4
    before_cache = copy.deepcopy(market._CACHE)
    with push2_guard.read_only():
        cached = market.get_overview()
    assert cached == original
    assert cached["sentiment"]["status"] == "partial"
    assert len(calls) == 4 and market._CACHE == before_cache
    # A real breadth degradation must never be cached by the qualification exception.
    market._CACHE.clear()
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env(status="partial"))
    assert market.get_overview()["sentiment"]["status"] == "partial"
    assert "overview" not in market._CACHE


@pytest.fixture(autouse=True)
def _source_mocked_assembly(monkeypatch):
    # These tests inject provider results in this process. Production collection
    # is verified separately with disposable synthetic workers.
    import daily_review as _review
    monkeypatch.setattr(_review, "_build_daily_review",
        lambda: _review._assemble_daily_review(None, _test_provider_calls=True))
