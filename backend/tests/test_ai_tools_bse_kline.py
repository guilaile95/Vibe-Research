"""BSE history must not be fabricated from Tencent's latest-bar response."""
import pytest
import requests

import ai_tools
import astock


@pytest.mark.parametrize("code", ["920982", "430047", "832000"])
def test_bse_history_uses_existing_qualified_fallback(monkeypatch, code):
    monkeypatch.setattr(
        requests, "get", lambda *a, **kw: pytest.fail("Tencent BSE request was made")
    )
    rows = [{"date": "2026-09-24", "close": 20.0},
            {"date": "2026-09-25", "close": 21.0}]

    def fallback(symbol, category, offset):
        assert (symbol, category, offset) == (code, 4, 20)
        return rows

    monkeypatch.setattr(astock, "kline", fallback)
    result = ai_tools._kline({"code": code, "period": "day", "count": 20})
    assert [(row["date"], row["close"]) for row in result["recent"]] == [
        ("2026-09-24", 20.0), ("2026-09-25", 21.0)
    ]
    assert result["summary"]["bars"] == 2


def test_bse_unavailable_provider_does_not_return_latest_bar_as_history(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **kw: pytest.fail("Tencent BSE request was made")
    )
    monkeypatch.setattr(astock, "kline", lambda *a, **kw: [])
    result = ai_tools._kline({"code": "920982", "period": "day"})
    assert "error" in result
    assert "recent" not in result
