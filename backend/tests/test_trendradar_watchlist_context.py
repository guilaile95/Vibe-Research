"""TrendRadar Watchlist attention context aggregation contract tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import trendradar_attention_context as attention
import trendradar_router
import trendradar_watchlist_context as watchlist

client = TestClient(app_module.app)


def _item(code: str, status: str = "OK", count: int = 1) -> dict:
    return {
        "status": status,
        "security": {"code": code, "company_name": f"测试股{code}"},
        "mapping": {
            "status": "MAPPED",
            "sector": None,
            "topics": [],
            "matched_terms": [code],
            "reasons": [],
            "errors": [],
        },
        "observation": {
            "window_days": 7,
            "window_semantics": "TrendRadar search_news date_range relative window",
            "items": [],
            "item_count": count,
            "rank_history_semantics": "missing means UNKNOWN",
        },
        "source_statuses": [],
    }


def test_build_preserves_authoritative_order_and_provenance():
    seen: list[str] = []

    def builder(code: str, **kwargs):
        seen.append(code)
        return _item(code)

    result = watchlist.build_watchlist_context(
        ["600519", "000001", "600519"],
        context_builder=builder,
    )

    assert result["status"] == "OK"
    assert result["watchlist"] == {"status": "valid", "codes": ["600519", "000001"], "count": 2}
    assert [item["security"]["code"] for item in result["items"]] == ["600519", "000001"]
    assert seen == ["600519", "000001"]
    assert result["authority_ref"] == watchlist.WATCHLIST_CONTEXT_AUTHORITY_REF
    assert result["usage_boundary"] == watchlist.USAGE_BOUNDARY


def test_build_isolates_one_code_failure_and_keeps_partial_truthful():
    def builder(code: str, **kwargs):
        if code == "000001":
            raise RuntimeError("proxy URL and secret must not escape")
        return _item(code)

    result = watchlist.build_watchlist_context(
        ["600519", "000001"],
        context_builder=builder,
    )

    assert result["status"] == attention.STATUS_PARTIAL
    failed = result["items"][1]
    assert failed["status"] == "UNAVAILABLE"
    assert failed["error"] == "TrendRadar 暂不可用"
    assert "proxy" not in str(result).lower()
    assert "secret" not in str(result).lower()


def test_build_rejects_invalid_codes():
    with pytest.raises(ValueError):
        watchlist.build_watchlist_context(["600519", "bad"])


def test_build_non_valid_watchlist_status_is_explicit_unavailable():
    result = watchlist.build_watchlist_context([], watchlist_status="corrupted")
    assert result["status"] == "UNAVAILABLE"
    assert result["watchlist"] == {"status": "corrupted", "codes": [], "count": 0}
    assert result["items"] == []


def test_all_failed_mixed_statuses_remain_unavailable():
    def builder(code: str, **kwargs):
        return _item(code, "TIMEOUT" if code == "600519" else "CONTRACT_MISMATCH")

    result = watchlist.build_watchlist_context(["600519", "000001"], context_builder=builder)
    assert result["status"] == "UNAVAILABLE"
    assert result["error"] == "TrendRadar 暂不可用"


def test_route_reads_backend_authoritative_watchlist(monkeypatch):
    monkeypatch.setattr(
        trendradar_router.watchlist_store,
        "get_watchlist_status",
        lambda: {
            "status": "valid",
            "data": {"codes": ["600519", "000001"], "updated_at": "t"},
            "etag": "e",
        },
    )
    calls: list[list[str]] = []

    def builder(codes, **kwargs):
        calls.append(codes)
        return {"status": "OK", "watchlist": {"codes": codes, "count": len(codes)}, "items": []}

    monkeypatch.setattr(trendradar_router.watchlist_context, "build_watchlist_context", builder)
    response = client.get("/api/trendradar/watchlist-context")
    assert response.status_code == 200
    assert response.json()["watchlist"]["codes"] == ["600519", "000001"]
    assert calls == [["600519", "000001"]]


def test_route_never_accepts_client_codes():
    response = client.get("/api/trendradar/watchlist-context?codes=000001")
    assert response.status_code == 200
    assert response.json().get("watchlist", {}).get("codes") != ["000001"]
