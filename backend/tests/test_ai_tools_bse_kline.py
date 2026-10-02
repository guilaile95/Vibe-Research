"""BSE history must not be fabricated from Tencent's latest-bar response."""
import pytest
import requests

import ai_tools
import astock


@pytest.mark.parametrize("code", ["920982", "430047", "832000"])
def test_bse_history_is_unavailable_without_verified_qfq_source(monkeypatch, code):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("Tencent BSE request was made"))
    monkeypatch.setattr(astock, "kline", lambda *a, **kw: pytest.fail("Unadjusted BSE fallback was made"))
    result = ai_tools._kline({"code": code, "period": "day", "count": 20})
    assert result["status"] == "unavailable"
    assert result["adjustment"] == "qfq"
    assert result["fallback"]["reason"] == "unsupported_adjustment"
    assert "recent" not in result


def test_bse_unavailable_provider_does_not_return_latest_bar_as_history(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("Tencent BSE request was made"))
    monkeypatch.setattr(astock, "kline", lambda *a, **kw: [])
    result = ai_tools._kline({"code": "920982", "period": "day"})
    assert "error" in result
    assert "recent" not in result
