"""Offline contracts for public announcement/news failure vs legitimate empty."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import astock
import data_health_event_store as health


UNSAFE = "ProxyError https://provider.invalid/?token=secret SQL SELECT traceback"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "_ANN_CACHE", app_module.TTLCache())
    return TestClient(app_module.app)


def assert_safe_error(response, status=502):
    assert response.status_code == status
    for internal in ("ProxyError", "https://", "provider.invalid", "secret", "SQL", "traceback"):
        assert internal not in response.text


@pytest.mark.parametrize("payload", [None, [], {}, {"data": None}, {"data": {}}, {"data": {"list": {}}}, {"data": {"list": [None]}}, {"data": {"list": [{}]}}, {"data": {"list": [{"title": 123}]}}])
def test_malformed_announcements_are_not_cached_or_recorded_healthy(client, monkeypatch, payload):
    class Response:
        status_code = 200

        def json(self):
            return payload

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(astock, "_em_session", lambda *_: Session())
    response = client.get("/api/announcements", params={"code": "000001"})
    assert_safe_error(response)
    assert app_module._ANN_CACHE.get("000001", 900) is app_module._CACHE_MISS
    event = health.load_events_readonly()["announcements"]
    assert event["last_success_at"] is None
    assert event["last_error_code"] == "SOURCE_UNAVAILABLE"


def test_announcement_provider_error_status_is_not_empty(client, monkeypatch):
    class Response:
        status_code = 503

        def json(self):
            return {"data": {"list": []}}

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(astock, "_em_session", lambda *_: Session())
    assert_safe_error(client.get("/api/announcements?code=000001"))
    assert app_module._ANN_CACHE.get("000001", 900) is app_module._CACHE_MISS


def test_announcement_failure_retry_and_successful_empty_cache(client, monkeypatch):
    calls = []

    def fetch(code, *, strict=False):
        calls.append((code, strict))
        if len(calls) == 1:
            raise RuntimeError(UNSAFE)
        return []

    monkeypatch.setattr(astock, "announcements", fetch)
    assert_safe_error(client.get("/api/announcements?code=000001"))
    assert health.load_events_readonly()["announcements"]["last_success_at"] is None
    assert client.get("/api/announcements?code=000001").json() == {"data": []}
    assert health.load_events_readonly()["announcements"]["last_success_at"] is not None
    assert client.get("/api/announcements?code=000001").json() == {"data": []}
    assert calls == [("000001", True), ("000001", True)]


def test_valid_announcement_adapter_response_and_empty_are_successful(client, monkeypatch):
    payload = {"data": {"list": [{"title": "Synthetic announcement", "notice_date": "2026-09-30", "art_code": "test", "columns": [{"column_name": "公告"}]}]}}

    class Response:
        status_code = 200

        def json(self):
            return payload

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(astock, "_em_session", lambda *_: Session())
    response = client.get("/api/announcements?code=000001")
    assert response.status_code == 200
    assert response.json()["data"][0]["title"] == "Synthetic announcement"
    payload["data"]["list"] = []
    assert client.get("/api/announcements?code=000002").json() == {"data": []}


@pytest.mark.parametrize("payload", [None, {}, [None], [{}], [{"新闻标题": 123}], [{"新闻标题": ""}], [{"新闻标题": "Valid", "发布时间": {}}]])
def test_malformed_news_cannot_be_successful_empty(client, monkeypatch, payload):
    monkeypatch.setattr(astock, "stock_news", lambda *_, **__: payload)
    assert_safe_error(client.get("/api/news?code=000001"))


@pytest.mark.parametrize("exception,status", [(RuntimeError, 502), (astock.DependencyMissing, 501)])
def test_news_error_details_are_safe_and_retry_recovers(client, monkeypatch, exception, status):
    def fail(*args, **kwargs):
        raise exception(UNSAFE)

    monkeypatch.setattr(astock, "stock_news", fail)
    response = client.get("/api/news?code=000001")
    assert_safe_error(response, status)
    if status == 501:
        assert "akshare" in response.text
    monkeypatch.setattr(astock, "stock_news", lambda *_, **__: [])
    assert client.get("/api/news?code=000001").json() == {"data": []}


def test_news_preserves_valid_optional_fields(client, monkeypatch):
    rows = [{"新闻标题": "Synthetic news", "发布时间": "2026-09-30 10:00", "新闻链接": "https://example.com/news"}]
    monkeypatch.setattr(astock, "stock_news", lambda *_, **__: rows)
    response = client.get("/api/news?code=000001")
    assert response.status_code == 200
    assert response.json() == {"data": rows}


@pytest.mark.parametrize("payload", [None, {}, "invalid", [None], [{}], [{"新闻标题": None}], [{"新闻标题": "Valid", "发布时间": 123}]])
def test_news_route_strict_adapter_rejects_malformed_provider(client, monkeypatch, payload):
    from types import SimpleNamespace

    monkeypatch.setattr(astock, "_akshare", lambda: SimpleNamespace(stock_news_em=lambda **_: payload))
    assert_safe_error(client.get("/api/news?code=000001"))
    with pytest.raises(ValueError):
        astock.stock_news("000001", strict=True)


@pytest.mark.parametrize("shape", ["missing-column", "missing-title", "malformed-date", "zero-columns"])
def test_news_route_rejects_malformed_dataframes(client, monkeypatch, shape):
    from types import SimpleNamespace
    import pandas as pd

    frames = {
        "missing-column": pd.DataFrame([{"unexpected": "field"}]),
        "missing-title": pd.DataFrame([{"新闻标题": None}]),
        "malformed-date": pd.DataFrame([{"新闻标题": "Valid", "发布时间": 123}]),
        "zero-columns": pd.DataFrame(index=[0]),
    }
    monkeypatch.setattr(astock, "_akshare", lambda: SimpleNamespace(stock_news_em=lambda **_: frames[shape]))
    assert_safe_error(client.get("/api/news?code=000001"))


@pytest.mark.parametrize("as_frame", [False, True])
def test_strict_news_true_empty_rows_and_limit_are_preserved(client, monkeypatch, as_frame):
    from types import SimpleNamespace
    import pandas as pd

    rows = []
    monkeypatch.setattr(astock, "_akshare", lambda: SimpleNamespace(stock_news_em=lambda **_: pd.DataFrame(rows) if as_frame else rows))
    assert client.get("/api/news?code=000001").json() == {"data": []}
    rows.extend([{"新闻标题": "First"}, {"新闻标题": "Second"}])
    assert client.get("/api/news?code=000001&limit=1").json() == {"data": [{"新闻标题": "First"}]}


def test_strict_news_missing_data_does_not_change_legacy_callers(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(astock, "_akshare", lambda: SimpleNamespace(stock_news_em=lambda **_: None))
    assert astock.stock_news("000001") == []
    with pytest.raises(ValueError, match="missing records"):
        astock.stock_news("000001", strict=True)
