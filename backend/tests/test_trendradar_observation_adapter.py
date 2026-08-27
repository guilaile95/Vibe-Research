"""TR1-P0 TrendRadar 只读观察适配器离线测试。

fixture 库由测试自己按已认证的观察契约建在 tmp 目录（零上游代码导入）；
只读打开的字节级零突变（含 mtime）在每个读取用例断言。
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

import trendradar_observation_adapter as obs


NEWS_DDL = [
    """
    CREATE TABLE platforms (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, is_active INTEGER DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE news_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, platform_id TEXT NOT NULL, rank INTEGER NOT NULL,
        url TEXT DEFAULT '', mobile_url TEXT DEFAULT '',
        first_crawl_time TEXT NOT NULL, last_crawl_time TEXT NOT NULL,
        crawl_count INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE rank_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_item_id INTEGER NOT NULL, rank INTEGER NOT NULL,
        crawl_time TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE crawl_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        crawl_time TEXT NOT NULL UNIQUE, total_items INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE crawl_source_status (
        crawl_record_id INTEGER NOT NULL, platform_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success', 'failed')),
        PRIMARY KEY (crawl_record_id, platform_id)
    )
    """,
]

RSS_DDL = [
    """
    CREATE TABLE rss_feeds (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, feed_url TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1, last_fetch_time TEXT,
        last_fetch_status TEXT, item_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE rss_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, feed_id TEXT NOT NULL, url TEXT NOT NULL,
        guid TEXT DEFAULT '', published_at TEXT, summary TEXT, author TEXT,
        first_crawl_time TEXT NOT NULL, last_crawl_time TEXT NOT NULL,
        crawl_count INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE rss_crawl_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        crawl_time TEXT NOT NULL UNIQUE, total_items INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE rss_crawl_status (
        crawl_record_id INTEGER NOT NULL, feed_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success', 'failed')),
        error_message TEXT,
        PRIMARY KEY (crawl_record_id, feed_id)
    )
    """,
]

AI_FILTER_DDL = [
    """
    CREATE TABLE ai_filter_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag TEXT NOT NULL, description TEXT DEFAULT '',
        priority INTEGER NOT NULL DEFAULT 9999,
        status TEXT DEFAULT 'active', deprecated_at TEXT,
        version INTEGER NOT NULL, prompt_hash TEXT NOT NULL,
        interests_file TEXT NOT NULL DEFAULT 'ai_interests.txt',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE ai_filter_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_item_id INTEGER NOT NULL, source_type TEXT NOT NULL DEFAULT 'hotlist',
        tag_id INTEGER NOT NULL, relevance_score REAL DEFAULT 0,
        status TEXT DEFAULT 'active', deprecated_at TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(news_item_id, source_type, tag_id)
    )
    """,
    """
    CREATE TABLE ai_filter_analyzed_news (
        news_item_id INTEGER NOT NULL, source_type TEXT NOT NULL DEFAULT 'hotlist',
        interests_file TEXT NOT NULL DEFAULT 'ai_interests.txt',
        prompt_hash TEXT NOT NULL, matched INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        PRIMARY KEY (news_item_id, source_type, interests_file)
    )
    """,
]


def _dir_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            snapshot[str(path.relative_to(root))] = (
                len(data),
                path.stat().st_mtime_ns,
                hashlib.sha256(data).hexdigest(),
            )
    return snapshot


def _build_db(
    root: Path, kind: str, date: str, ddl: list[str], seed=None
) -> Path:
    target = root / kind / f"{date}.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    for statement in ddl:
        conn.execute(statement)
    if seed is not None:
        seed(conn)
    conn.commit()
    conn.close()
    return target


def _seed_news(conn):
    conn.execute("INSERT INTO platforms(id, name) VALUES ('weibo', '微博')")
    conn.execute("INSERT INTO platforms(id, name) VALUES ('baidu', '百度热搜')")
    cursor = conn.execute(
        "INSERT INTO news_items(title, platform_id, rank, url, mobile_url,"
        " first_crawl_time, last_crawl_time, crawl_count)"
        " VALUES ('头条A', 'weibo', 3, 'https://a', '',"
        " '2026-08-27 09:00:00', '2026-08-27 09:30:00', 3)"
    )
    item_a = cursor.lastrowid
    cursor_b = conn.execute(
        "INSERT INTO news_items(title, platform_id, rank, url, mobile_url,"
        " first_crawl_time, last_crawl_time, crawl_count)"
        " VALUES ('热点B', 'baidu', 1, 'https://b', '',"
        " '2026-08-27 09:10:00', '2026-08-27 09:40:00', 2)"
    )
    item_b = cursor_b.lastrowid
    # A：上榜→脱榜→回榜（rank=0 观察语义）
    for rank, ts in ((1, "2026-08-27 09:00:00"), (0, "2026-08-27 09:20:00"),
                     (3, "2026-08-27 09:30:00")):
        conn.execute(
            "INSERT INTO rank_history(news_item_id, rank, crawl_time)"
            f" VALUES ({item_a}, {rank}, '{ts}')"
        )
    for rank, ts in ((2, "2026-08-27 09:10:00"),):
        conn.execute(
            "INSERT INTO rank_history(news_item_id, rank, crawl_time)"
            f" VALUES ({item_b}, {rank}, '{ts}')"
        )
    rec = conn.execute(
        "INSERT INTO crawl_records(crawl_time, total_items)"
        " VALUES ('2026-08-27 09:28:44', 90)"
    ).lastrowid
    conn.execute(
        "INSERT INTO crawl_source_status(crawl_record_id, platform_id, status)"
        f" VALUES ({rec}, 'weibo', 'success')"
    )
    rec2 = conn.execute(
        "INSERT INTO crawl_records(crawl_time, total_items)"
        " VALUES ('2026-08-27 09:45:01', 88)"
    ).lastrowid
    conn.execute(
        "INSERT INTO crawl_source_status(crawl_record_id, platform_id, status)"
        f" VALUES ({rec2}, 'baidu', 'failed')"
    )


def _seed_rss(conn):
    conn.execute(
        "INSERT INTO rss_feeds(id, name, is_active, last_fetch_time,"
        " last_fetch_status, item_count)"
        " VALUES ('hacker-news', 'Hacker News', 1,"
        " '2026-08-27 10:00:00', 'success', 20)"
    )
    conn.execute(
        "INSERT INTO rss_items(title, feed_id, url, guid, published_at,"
        " summary, author, first_crawl_time, last_crawl_time, crawl_count)"
        " VALUES ('Post X', 'hacker-news', 'https://x', 'guid-x',"
        " '2026-08-26T22:00:00Z', 'sum', 'author',"
        " '2026-08-27 10:00:00', '2026-08-27 11:00:00', 2)"
    )
    rec = conn.execute(
        "INSERT INTO rss_crawl_records(crawl_time, total_items)"
        " VALUES ('2026-08-27 10:00:00', 20)"
    ).lastrowid
    conn.execute(
        "INSERT INTO rss_crawl_status(crawl_record_id, feed_id, status,"
        " error_message)" f" VALUES ({rec}, 'hacker-news', 'success', '')"
    )


@pytest.fixture
def news_root(tmp_path: Path) -> Path:
    _build_db(tmp_path, "news", "2026-08-27", NEWS_DDL, _seed_news)
    return tmp_path


def _assert_zero_mutation(root: Path, before: dict, after: dict) -> None:
    assert after == before, "read-only observation mutated sidecar files"


# ---------------------------------------------------------------------------
# news 观察
# ---------------------------------------------------------------------------


def test_observe_news_ok_normalized_model(news_root: Path):
    before = _dir_snapshot(news_root)
    result = obs.observe_news(news_root, "2026-08-27")
    assert result["status"] == "OK"
    observation = result["observation"]
    assert observation["item_count"] == 2
    weibo_item = next(i for i in observation["items"] if i["platform_id"] == "weibo")
    assert weibo_item["platform_name"] == "微博"
    assert weibo_item["rank"] == 3
    assert weibo_item["observed_ranks"] == [1, 3]
    timeline = weibo_item["rank_timeline"]
    assert [e["off_list"] for e in timeline] == [False, True, False]
    assert timeline[1]["rank"] == 0
    assert timeline[0]["crawl_time"] == "2026-08-27 09:00:00"
    failed = [s for s in observation["source_status"] if s["status"] == "failed"]
    assert failed and failed[0]["platform_id"] == "baidu"
    _assert_zero_mutation(news_root, before, _dir_snapshot(news_root))


def test_read_only_open_never_creates_artifacts(news_root: Path):
    """目录级产物检查：不产生 -wal/-shm/journal 或任何新文件。"""
    names_before = {p.name for p in news_root.rglob("*")}
    result = obs.observe_news(news_root, "2026-08-27")
    assert result["status"] == "OK"
    names_after = {p.name for p in news_root.rglob("*")}
    assert names_after == names_before


def test_missing_date_is_truthful_not_found(news_root: Path):
    result = obs.observe_news(news_root, "2026-08-26")
    assert result["status"] == "NOT_FOUND"


def test_unrooted_empty_root_not_found(tmp_path: Path):
    result = obs.observe_news(tmp_path, "2026-08-27")
    assert result["status"] == "NOT_FOUND"


def test_contract_mismatch_on_schema_drift(tmp_path: Path):
    """缺列/缺表都必须 CONTRACT_MISMATCH，绝不静默降级。"""
    _build_db(tmp_path, "news", "2030-01-01", NEWS_DDL, _seed_news)

    def drop_url_column(db_path: Path) -> None:
        tmp_copy = db_path.with_name("mutant.db")
        conn = sqlite3.connect(tmp_copy)
        for statement in NEWS_DDL:
            conn.execute(statement)
        conn.execute("ALTER TABLE news_items RENAME COLUMN url TO url_old")
        conn.commit()
        conn.close()
        tmp_copy.replace(db_path)  # Windows 上允许覆盖既有目标

    # 日期目录里的契约漂移库（schema 缺 news_items.url）
    drop_url_column(obs.resolve_db_path(tmp_path, "news", "2030-01-01"))
    result = obs.observe_news(tmp_path, "2030-01-01")
    assert result["status"] == "CONTRACT_MISMATCH"
    assert "missing column" in result["error"]

    # 缺整张表同样 fail-closed
    missing_table_root = tmp_path / "no-rank-tables"
    (missing_table_root / "news").mkdir(parents=True)
    conn = sqlite3.connect(
        missing_table_root / "news" / "2030-01-02.db"
    )
    for statement in NEWS_DDL:
        if "rank_history" not in statement:
            conn.execute(statement)
    conn.commit()
    conn.close()
    result = obs.observe_news(missing_table_root, "2030-01-02")
    assert result["status"] == "CONTRACT_MISMATCH"
    assert "missing table 'rank_history'" in result["error"]


def test_bad_arguments_rejected_fail_closed(news_root: Path):
    assert obs.observe_news(news_root, "../etc/passwd")["status"] == "BAD_ARGUMENT"
    assert obs.observe_news(news_root, "20260827")["status"] == "BAD_ARGUMENT"
    with pytest.raises(ValueError):
        obs.resolve_db_path(news_root, "else", "2026-08-27")


def test_resolve_path_allows_only_contract_locations(news_root: Path):
    path = obs.resolve_db_path(news_root, "news", "2026-08-27")
    assert path == (news_root.resolve() / "news" / "2026-08-27.db")
    traversal = obs.resolve_db_path(news_root / ".." / "..", "news", "2026-08-27")
    assert traversal.parent.name == "news"


# ---------------------------------------------------------------------------
# rss / ai-filter 观察
# ---------------------------------------------------------------------------


@pytest.fixture
def rss_root(tmp_path: Path) -> Path:
    _build_db(tmp_path, "rss", "2026-08-27", RSS_DDL, _seed_rss)
    return tmp_path


def test_observe_rss_ok(rss_root: Path):
    before = _dir_snapshot(rss_root)
    result = obs.observe_rss(rss_root, "2026-08-27")
    assert result["status"] == "OK"
    observation = result["observation"]
    assert observation["item_count"] == 1
    assert observation["feeds"][0]["id"] == "hacker-news"
    assert observation["fetch_status"][0]["feed_id"] == "hacker-news"
    _assert_zero_mutation(rss_root, before, _dir_snapshot(rss_root))


def test_observe_rss_missing_date(rss_root: Path):
    assert obs.observe_rss(rss_root, "2025-01-01")["status"] == "NOT_FOUND"


def test_ai_filter_provenance_requires_full_contract(news_root: Path):
    result = obs.observe_news_ai_filter(news_root, "2026-08-27")
    assert result["status"] == "CONTRACT_MISMATCH"


def test_ai_filter_provenance_active_matches(tmp_path: Path):
    def seed(conn):
        conn.execute(
            "INSERT INTO ai_filter_tags(tag, version, prompt_hash, created_at)"
            " VALUES ('AI/大模型', 1, 'f:md5', 'x')"
        )
        conn.execute(
            "INSERT INTO news_items(title, platform_id, rank, url, mobile_url,"
            " first_crawl_time, last_crawl_time, crawl_count)"
            " VALUES ('t', 'w', 1, '', '', '2026-08-27 09:00:00',"
            " '2026-08-27 09:00:00', 1)"
        )
        conn.execute(
            "INSERT INTO ai_filter_results(news_item_id, source_type, tag_id,"
            " relevance_score, created_at) VALUES (1, 'hotlist', 1, 0.9, 'x')"
        )
        conn.execute(
            "INSERT INTO ai_filter_results(news_item_id, source_type, tag_id,"
            " relevance_score, created_at) VALUES (1, 'rss', 1, 0.9, 'x')"
        )
        conn.execute(
            "INSERT INTO ai_filter_analyzed_news(news_item_id, matched,"
            " prompt_hash, created_at) VALUES (1, 1, 'f:md5', 'x')"
        )

    _build_db(tmp_path, "news", "2026-08-27", NEWS_DDL + AI_FILTER_DDL, seed)
    result = obs.observe_news_ai_filter(tmp_path, "2026-08-27")
    assert result["status"] == "OK"
    matches = result["observation"]["matches"]
    assert len(matches) == 1 and matches[0]["matched_tags"][0]["tag"] == "AI/大模型"
    assert result["observation"]["matched_news_count"] == 1


def test_envelopes_declare_non_authority_boundary(news_root: Path):
    result = obs.observe_news(news_root, "2026-08-27")
    assert result["authority_ref"].startswith("vibe:trendradar_observation:")
    assert result["usage_boundary"] == "observation_only_not_an_investment_authority"
