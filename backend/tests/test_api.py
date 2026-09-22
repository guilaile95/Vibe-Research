"""API 验证/契约测（FastAPI TestClient）。大多在校验层就返回，不联网、可靠。"""
import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.parametrize("failure_stage,exception,status", [
    ("snapshot", RuntimeError, 200),
    ("projection", RuntimeError, 502),
    ("projection", ValueError, 400),
])
def test_market_cloud_public_errors_do_not_expose_provider_details(
    monkeypatch, failure_stage, exception, status,
):
    """真实 UI 曾把 provider 异常中的请求 URL 原样展示；覆盖信封和 HTTP 错误。"""
    raw = "ProxyError: https://provider.invalid/quote?token=private-token SQL traceback"

    def fail(*args, **kwargs):
        raise exception(raw)

    target = "get_a_share_snapshot" if failure_stage == "snapshot" else "get_market_cloud"
    monkeypatch.setattr(app_module.market, target, fail)
    response = client.get("/api/market/cloud")
    assert response.status_code == status
    assert "市场热力" in response.text or "市场范围或周期无效" in response.text
    for internal in ("ProxyError", "https://", "provider.invalid", "private-token", "SQL", "traceback"):
        assert internal not in response.text
    if failure_stage == "snapshot":
        envelope = response.json()["data"]
        assert envelope["status"] == "unavailable"
        assert envelope["data"] is None


@pytest.mark.parametrize("query", ["scope=unsupported", "period=unsupported"])
def test_market_cloud_invalid_selection_remains_400(query):
    assert client.get(f"/api/market/cloud?{query}").status_code == 400


@pytest.mark.parametrize("path", [
    "/api/quote?codes=abc",
    "/api/valuation?code=12",
    "/api/margin?code=notcode",
    "/api/holders?code=1234567",
    "/api/announcements?code=",
])
def test_bad_code_400(path):
    assert client.get(path).status_code == 400


def test_industry_top_range():
    assert client.get("/api/industry?top=2").status_code == 422   # ge=5
    assert client.get("/api/industry?top=999").status_code == 422  # le=50


def test_chat_empty_messages_400():
    r = client.post("/api/chat", json={"messages": [], "llm": {"model": "x", "baseURL": "http://x", "apiKey": "k"}})
    assert r.status_code == 400


def test_chat_api_missing_key_400():
    # API 接入缺 baseURL/apiKey → 400（在开流前拦下）
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "hi"}],
        "llm": {"provider": "deepseek", "model": "deepseek-chat", "baseURL": "", "apiKey": ""},
    })
    assert r.status_code == 400


def test_chat_rejects_legacy_cli_provider():
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "hi"}],
        "llm": {"provider": "cli-qwen", "model": "qwen-code", "baseURL": "", "apiKey": ""},
    })
    assert r.status_code == 400
    assert "仅支持 Codex" in r.json()["detail"]


def test_global_stock_404(monkeypatch):
    """无法解析的美股/港股代码 → 404（不 500、不崩）。"""
    import gstock
    monkeypatch.setattr(gstock, "us_hk_stock", lambda q: {})
    assert client.get("/api/global/stock?symbol=ZZZZ").status_code == 404


def test_gstock_quote_full_null_shape():
    """行情取不到时 `_quote_from({})` 仍返回完整 null 形状（契合 GlobalQuote 类型），不是空 dict。"""
    import gstock
    q = gstock._quote_from({})
    assert set(q) == {"code", "name", "price", "open", "high", "low", "prev_close", "amount", "mcap", "change_pct"}
    assert all(v is None for v in q.values())
