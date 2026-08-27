"""TR1-P0 trendradar 路由 API 离线测试（TestClient，零真实出网）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import trendradar_observation_adapter as obs
import trendradar_router

client = TestClient(app_module.app)


NEWS_MIN_DDL = [
    "CREATE TABLE platforms (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
    " is_active INTEGER DEFAULT 1)",
    """CREATE TABLE news_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, platform_id TEXT NOT NULL, rank INTEGER NOT NULL,
        url TEXT DEFAULT '', mobile_url TEXT DEFAULT '',
        first_crawl_time TEXT NOT NULL, last_crawl_time TEXT NOT NULL,
        crawl_count INTEGER DEFAULT 1)""",
    "CREATE TABLE rank_history (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " news_item_id INTEGER NOT NULL, rank INTEGER NOT NULL, crawl_time TEXT NOT NULL)",
    "CREATE TABLE crawl_records (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " crawl_time TEXT NOT NULL UNIQUE, total_items INTEGER DEFAULT 0)",
    "CREATE TABLE crawl_source_status (crawl_record_id INTEGER NOT NULL,"
    " platform_id TEXT NOT NULL, status TEXT NOT NULL,"
    " PRIMARY KEY (crawl_record_id, platform_id))",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("VIBE_TRENDRADAR_MCP_URL", raising=False)
    monkeypatch.delenv("VIBE_TRENDRADAR_OUTPUT_ROOT", raising=False)
    yield


@pytest.fixture
def news_root(tmp_path: Path) -> Path:
    target = tmp_path / "news" / "2026-08-27.db"
    target.parent.mkdir(parents=True)
    conn = sqlite3.connect(target)
    for statement in NEWS_MIN_DDL:
        conn.execute(statement)
    conn.execute("INSERT INTO platforms(id, name) VALUES ('weibo', '微博')")
    conn.execute(
        "INSERT INTO news_items(title, platform_id, rank, url, mobile_url,"
        " first_crawl_time, last_crawl_time)"
        " VALUES ('t1', 'weibo', 2, 'https://a', '',"
        " '2026-08-27 09:00:00', '2026-08-27 09:05:00')"
    )
    conn.execute(
        "INSERT INTO rank_history(news_item_id, rank, crawl_time)"
        " VALUES (1, 2, '2026-08-27 09:05:00')"
    )
    conn.commit()
    conn.close()
    return tmp_path


def _openapi_paths() -> set[str]:
    return set(client.get("/openapi.json").json()["paths"])


def test_routes_are_registered():
    paths = _openapi_paths()
    for expected in (
        "/api/trendradar/status",
        "/api/trendradar/tools",
        "/api/trendradar/observation/news/{date}",
        "/api/trendradar/observation/rss/{date}",
        "/api/trendradar/observation/news-ai-filter/{date}",
    ):
        assert expected in paths


def test_status_disabled_without_env():
    response = client.get("/api/trendradar/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DISABLED"
    assert body["gateway"]["enabled"] is False
    assert body["upstream"]["source_commit"]


def test_status_config_error_for_non_loopback(monkeypatch):
    monkeypatch.setenv("VIBE_TRENDRADAR_MCP_URL", "http://10.0.0.5:3333/mcp")
    body = client.get("/api/trendradar/status").json()
    assert body["status"] == "CONFIG_ERROR"
    assert "loopback" in body["error"]


def test_tools_disabled_returns_envelope():
    body = client.get("/api/trendradar/tools").json()
    assert body["status"] == "DISABLED"


def test_observation_news_disabled_without_root(news_root: Path):
    body = client.get("/api/trendradar/observation/news/2026-08-27").json()
    assert body["status"] == "DISABLED"


def test_observation_news_ok_with_server_side_root(
    monkeypatch, news_root: Path
):
    monkeypatch.setenv("VIBE_TRENDRADAR_OUTPUT_ROOT", str(news_root))
    body = client.get("/api/trendradar/observation/news/2026-08-27").json()
    assert body["status"] == "OK"
    assert body["observation"]["item_count"] == 1
    item = body["observation"]["items"][0]
    assert item["platform_name"] == "微博"
    assert item["rank_timeline"][0]["rank"] >= 2


def test_observation_not_found_passes_through(monkeypatch, news_root: Path):
    monkeypatch.setenv("VIBE_TRENDRADAR_OUTPUT_ROOT", str(news_root))
    body = client.get("/api/trendradar/observation/news/2000-01-01").json()
    assert body["status"] == "NOT_FOUND"


def test_observation_bad_date_is_422(monkeypatch, news_root: Path):
    monkeypatch.setenv("VIBE_TRENDRADAR_OUTPUT_ROOT", str(news_root))
    response = client.get("/api/trendradar/observation/news/not-a-date")
    assert response.status_code == 422


def test_client_never_supplies_filesystem_root():
    """root 只来自服务端 env：日期路径参数无法注入文件位置（adapter 强校验兜底）。"""
    with pytest.raises(ValueError):
        obs.resolve_db_path(".", "news", "..%2F..%2Fsecret")


def test_no_arbitrary_tool_call_endpoint_exists():
    forbidden = [
        p
        for p in _openapi_paths()
        if p.startswith("/api/trendradar")
        and any(word in p for word in ("call", "invoke", "exec"))
    ]
    assert forbidden == []


# ---------------------------------------------------------------------------
# P1 雷达控制台面
# ---------------------------------------------------------------------------


import trendradar_console as tr_console  # noqa: E402


def test_console_forbidden_tools_never_reachable():
    captured: dict[str, object] = {}

    class Spy:
        def __init__(self, config):
            pass

    def spy_factory(config):
        return Spy(config)

    def spy_gateway(name, arguments, **kwargs):
        captured["name"] = name
        envelope = {
            "status": "OK",
            "retrieved_at": "t",
            "upstream": {"repo": "x"},
            "result": {},
        }
        return envelope

    original = tr_console.gw.call_tool
    try:
        tr_console.gw.call_tool = spy_gateway  # type: ignore[assignment]
        for bad in ("send_notification", "get_notification_channels", "trigger_crawl",
                    "sync_from_remote", "read_article", "read_articles_batch",
                    "generate_summary_report", "analyze_data_insights"):
            result = tr_console.call_read_tool(bad, {}, transport_factory=spy_factory)
            assert result["status"] == "BAD_ARGUMENT", bad
            captured.clear()
    finally:
        tr_console.gw.call_tool = original  # type: ignore[assignment]


def test_console_excludes_notification_channel_tool():
    assert "get_notification_channels" not in tr_console.READ_TOOL_NAMES
    response = client.get("/api/trendradar/radar/channels")
    assert response.status_code == 404


def test_console_allows_only_declared_read_names(monkeypatch):
    seen: dict[str, tuple] = {}

    def fake_gateway(name, arguments, *, allowed_names, env=None,
                     transport_factory=None):
        seen["call"] = (name, arguments, allowed_names)
        return {"status": "OK", "retrieved_at": "t", "upstream": {},
                "result": {"ok": True}}

    monkeypatch.setattr(tr_console.gw, "call_tool", fake_gateway)
    result = tr_console.call_read_tool(
        "get_latest_news", {"limit": 5},
    )
    assert result["status"] == "OK"
    name, args, allowed = seen["call"]
    assert name == "get_latest_news" and args == {"limit": 5}
    assert "send_notification" not in allowed
    assert result["tool"] == "get_latest_news"
    assert result["authority_ref"].startswith("vibe:trendradar_console:")


def _radar_endpoint_env(monkeypatch):
    """路由层工厂注入点：monkeypatch console.call_read_tool 记录装配参数。"""
    calls: list[tuple[str, dict]] = []

    def fake_call(name, arguments, env=None, transport_factory=None):
        calls.append((name, arguments))
        return {"status": "DISABLED", "retrieved_at": "t", "upstream": {}}

    monkeypatch.setattr(tr_router_module(), "console", _FakeConsole(fake_call))
    return calls


class _FakeConsole:
    def __init__(self, fn):
        self._fn = fn

    def call_read_tool(self, name, arguments, env=None, transport_factory=None):
        return self._fn(name, arguments, env, transport_factory)

    def drop_none(self, args):
        return {k: v for k, v in args.items() if v is not None}


def tr_router_module():
    import trendradar_router as rr
    return rr


def test_radar_latest_assembles_args(monkeypatch):
    import trendradar_router as rr
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        rr, "console", _SimpleConsole(calls)
    )
    client.get("/api/trendradar/radar/latest?limit=7&platforms=weibo,baidu")
    assert calls == [
        ("get_latest_news", {"limit": 7, "platforms": ["weibo", "baidu"]})
    ]


class _SimpleConsole:
    def __init__(self, sink):
        self.sink = sink

    def call_read_tool(self, name, arguments, env=None, transport_factory=None):
        self.sink.append((name, arguments))
        return {"status": "DISABLED", "retrieved_at": "t", "upstream": {}}

    def drop_none(self, args):
        return {k: v for k, v in args.items() if v is not None}


def test_radar_hotlist_validates_date_and_routes_tool(monkeypatch):
    import trendradar_router as rr
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(rr, "console", _SimpleConsole(calls))

    bad = client.get("/api/trendradar/radar/hotlist/not-a-date")
    assert bad.status_code == 422

    ok = client.get("/api/trendradar/radar/hotlist/2026-08-27?limit=3")
    assert ok.status_code == 200
    assert calls[-1] == (
        "get_news_by_date",
        {"date_range": "2026-08-27", "limit": 3},
    )


def test_radar_search_passes_window_and_url_flag(monkeypatch):
    import trendradar_router as rr
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(rr, "console", _SimpleConsole(calls))

    client.get("/api/trendradar/radar/search?q=%E7%AE%97%E5%8A%9B&days_back=14")
    assert calls and calls[0][0] == "search_news"
    args = calls[0][1]
    assert args["query"] == "算力"
    assert args["include_url"] is True
    assert args["date_range"] == "最近14天"


def test_radar_group_registered_in_openapi():
    paths = _openapi_paths()
    for expected in (
        "/api/trendradar/radar/dates",
        "/api/trendradar/radar/latest",
        "/api/trendradar/radar/hotlist/{date}",
        "/api/trendradar/radar/rss-latest",
        "/api/trendradar/radar/search",
        "/api/trendradar/radar/trending",
        "/api/trendradar/radar/topic-trend",
        "/api/trendradar/radar/sentiment",
        "/api/trendradar/radar/aggregate",
        "/api/trendradar/radar/related",
        "/api/trendradar/radar/system-status",
        "/api/trendradar/radar/storage-status",
    ):
        assert expected in paths
    assert "/api/trendradar/radar/channels" not in paths
