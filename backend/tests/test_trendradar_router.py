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
