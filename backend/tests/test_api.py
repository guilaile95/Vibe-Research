"""API 验证/契约测（FastAPI TestClient）。大多在校验层就返回，不联网、可靠。"""
import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


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


def test_chat_cli_not_installed_400(monkeypatch):
    # P0-SEC2：订阅接入默认被 HTTP 执行门拦截（未 opt-in → 403，fail-closed），
    # 不再泄露本机是否安装了某 CLI（gate 先于 detect_cli）。
    monkeypatch.setattr(app_module.cli_runtime, "VR_ENABLE_LOCAL_CLI", False)
    monkeypatch.setattr(app_module.cli_runtime, "VR_API_KEY", "")
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "hi"}],
        "llm": {"provider": "cli-qwen", "model": "qwen-code", "baseURL": "", "apiKey": ""},
    })
    assert r.status_code == 403
    assert "CLI" in r.json()["detail"] or "CLI" in r.text or "未启用" in r.text


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


def test_global_indices_use_requested_country_authority_order(monkeypatch):
    """全球市场卡片固定使用美国、香港、日本、韩国的五个代表指数。"""
    import gstock

    requested_secids = []

    def quote(secid, _fields):
        requested_secids.append(secid)
        return {"f43": 123456, "f59": 2, "f170": 25}

    monkeypatch.setattr(gstock, "_push2_stock_get", quote)

    rows = gstock.global_indices()

    assert requested_secids == ["100.NDX", "100.SPX", "100.HSI", "100.N225", "100.KS11"]
    assert [(row["key"], row["name"], row["region"]) for row in rows] == [
        ("ndx", "纳斯达克", "美国"),
        ("spx", "标普500", "美国"),
        ("hsi", "恒生指数", "香港"),
        ("nikkei225", "日经225", "日本"),
        ("kospi", "韩国KOSPI", "韩国"),
    ]
    assert all(row["price"] == 1234.56 and row["change_pct"] == 0.25 for row in rows)
