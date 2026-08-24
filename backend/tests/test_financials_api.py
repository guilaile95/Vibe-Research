from fastapi.testclient import TestClient

import app as app_module


client = TestClient(app_module.app)


def test_financials_api_explicitly_requests_health_enrichment(monkeypatch):
    calls = []

    def financials(code: str, *, include_health: bool = False):
        calls.append((code, include_health))
        return {
            "period": "2025-12-31",
            "period_end": "2025-12-31",
            "report_date": None,
            "revenue": "100亿",
            "net_profit": "20亿",
            "history": [],
            "data_quality": {"status": "normal"},
        }

    monkeypatch.setattr(app_module.astock, "financials", financials)
    response = client.get("/api/financials?code=600520")

    assert response.status_code == 200
    assert response.json()["data"]["report_date"] is None
    assert calls == [("600520", True)]
