"""Read-only API contract for authoritative-watchlist anomaly observations."""

from fastapi.testclient import TestClient

import app as app_module


client = TestClient(app_module.app)


def test_watchlist_anomalies_reads_authoritative_codes_and_preserves_empty(monkeypatch):
    seen = []
    monkeypatch.setattr(app_module.watchlist_store, "load_watchlist", lambda: ["600519", "000001"])

    def fetch(codes):
        seen.append(codes)
        return {
            "provider_id": "hithink_financial_api",
            "provider_contract": "hithink-watchlist-anomalies-v0.1",
            "as_of_ms": 1787529600000,
            "unavailable_codes": [],
            "items": [],
        }

    monkeypatch.setattr(app_module.hithink, "fetch_watchlist_anomalies", fetch)
    response = client.get("/api/watchlist/anomalies")

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []
    assert seen == [["600519", "000001"]]


def test_watchlist_anomalies_keeps_provider_failure_distinct_from_empty(monkeypatch):
    monkeypatch.setattr(app_module.watchlist_store, "load_watchlist", lambda: ["600519"])

    def fail(_codes):
        raise app_module.hithink.HiThinkTransportError("provider-controlled detail")

    monkeypatch.setattr(app_module.hithink, "fetch_watchlist_anomalies", fail)
    response = client.get("/api/watchlist/anomalies")

    assert response.status_code == 502
    assert response.json()["detail"] == "HiThink 异动数据暂不可用"
    assert "provider-controlled" not in response.text


def test_watchlist_anomalies_reports_missing_provider_configuration(monkeypatch):
    monkeypatch.setattr(app_module.watchlist_store, "load_watchlist", lambda: ["600519"])

    def fail(_codes):
        raise app_module.hithink.HiThinkNotConfiguredError("credential detail")

    monkeypatch.setattr(app_module.hithink, "fetch_watchlist_anomalies", fail)
    response = client.get("/api/watchlist/anomalies")

    assert response.status_code == 503
    assert response.json()["detail"] == "HiThink 异动数据未配置"
    assert "credential detail" not in response.text
