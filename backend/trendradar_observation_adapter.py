"""TrendRadar 只读观察适配器（TR1-P0）。

MCP 查询层无法忠实暴露精确的当日 rank 时间线/首末抓取/crawl 状态，本模块
是对 sidecar 自有 SQLite 的窄观察边界（见 #228 冻结边界）：

- 输入仅限显式配置 root 下的 ``news/YYYY-MM-DD.db`` / ``rss/YYYY-MM-DD.db``；
- 以 SQLite URI ``mode=ro`` 打开，绝不创建/迁移/写入上游 DB 与任何 journal 产物
  （认证库为 rollback-journal 模式；实测字节级零突变，见 ops/trendradar）；
- 读前校验表列契约，drift → CONTRACT_MISMATCH fail-closed；
- 缺日期/缺库 → 真实 NOT_FOUND，绝不伪装 empty-normal；
- 无任意 SQL 面；输出归一化 observation 模型，永不是 Canonical Fact /
  Decision authority。

契约事实来源：pinned 上游 commit 的 storage DDL + 实产认证库 schema 复核，
本模块为 Vibe-owned 独立实现，不含上游代码。
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVATION_AUTHORITY_REF = "vibe:trendradar_observation:v0.1"

STATUS_OK = "OK"
STATUS_DISABLED = "DISABLED"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
STATUS_BAD_ARGUMENT = "BAD_ARGUMENT"

_DB_KINDS = ("news", "rss")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# pinned 上游 schema 契约：表 -> 必须存在的列（允许超集）。
# 原则：本模块 SELECT 到的每一列都必须列入契约，schema 漂移在读前 fail-closed。
_REQUIRED_NEWS_SCHEMA: dict[str, tuple[str, ...]] = {
    "platforms": ("id", "name", "is_active"),
    "news_items": (
        "id",
        "title",
        "platform_id",
        "rank",
        "url",
        "mobile_url",
        "first_crawl_time",
        "last_crawl_time",
        "crawl_count",
    ),
    "rank_history": ("id", "news_item_id", "rank", "crawl_time"),
    "crawl_records": ("id", "crawl_time", "total_items"),
    "crawl_source_status": ("crawl_record_id", "platform_id", "status"),
}
_REQUIRED_RSS_SCHEMA: dict[str, tuple[str, ...]] = {
    "rss_feeds": (
        "id",
        "name",
        "is_active",
        "last_fetch_time",
        "last_fetch_status",
        "item_count",
    ),
    "rss_items": (
        "id",
        "title",
        "feed_id",
        "url",
        "guid",
        "published_at",
        "summary",
        "author",
        "first_crawl_time",
        "last_crawl_time",
        "crawl_count",
    ),
    "rss_crawl_records": ("id", "crawl_time", "total_items"),
    "rss_crawl_status": ("crawl_record_id", "feed_id", "status", "error_message"),
}

# 上游语义：rank_history.rank == 0 表示“脱榜”（off-list）观察记录。
OFF_LIST_RANK = 0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(status: str, date: str, kind: str, error: str | None = None) \
        -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "status": status,
        "source_date": date,
        "kind": kind,
        "retrieved_at": utc_now_iso(),
        "authority_ref": OBSERVATION_AUTHORITY_REF,
        "usage_boundary": "observation_only_not_an_investment_authority",
    }
    if error is not None:
        envelope["error"] = error
    return envelope


def disabled_envelope(date: str, kind: str) -> dict[str, Any]:
    """显式 DISABLED 态（观察输出根目录未配置）。"""
    return _envelope(
        STATUS_DISABLED, date, kind, "TrendRadar output root is not configured"
    )


def resolve_db_path(output_root: str | Path, kind: str, date: str) -> Path:
    """构造并收紧路径：root/news|rss/YYYY-MM-DD.db，防穿越。

    resolve 已消除 ``..`` 段与相对路径；随后强制要求 db 目录就是
    ``<resolved_root>/<kind>``，任何符号链接逃逸出 root 都直接拒绝。
    """
    if type(date) is not str or _DATE_RE.fullmatch(date) is None:
        raise ValueError("date must match YYYY-MM-DD")
    if kind not in _DB_KINDS:
        raise ValueError(f"kind must be one of {_DB_KINDS}")
    resolved_root = Path(output_root).resolve()
    expected_dir = resolved_root / kind
    db_path = (expected_dir / f"{date}.db").resolve()
    if db_path.parent != expected_dir:
        raise ValueError("resolved path escapes the configured output root")
    return db_path


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """mode=ro 打开既有 DB；文件缺失直接失败，绝不创建。"""
    uri = f"{db_path.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.execute("PRAGMA query_only = ON")  # 连接级保险丝；不落任何持久状态
    return conn


def _validate_contract(
    conn: sqlite3.Connection, required: dict[str, tuple[str, ...]]
) -> list[str]:
    problems: list[str] = []
    existing_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for table, columns in required.items():
        if table not in existing_tables:
            problems.append(f"missing table {table!r}")
            continue
        actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column in columns:
            if column not in actual:
                problems.append(f"missing column {table}.{column}")
    return sorted(problems)


def observe_news(output_root: str | Path, date: str) -> dict[str, Any]:
    """读取某日 hotlist 库的完整 observation 视图（原始行、零策略过滤）。"""
    try:
        db_path = resolve_db_path(output_root, "news", date)
    except ValueError as exc:
        return _envelope(STATUS_BAD_ARGUMENT, date, "news", str(exc))
    if not db_path.is_file():
        return _envelope(STATUS_NOT_FOUND, date, "news")
    try:
        conn = _connect_readonly(db_path)
    except sqlite3.Error as exc:
        return _envelope(STATUS_UNAVAILABLE, date, "news", str(exc))
    try:
        problems = _validate_contract(conn, _REQUIRED_NEWS_SCHEMA)
        if problems:
            return _envelope(
                STATUS_CONTRACT_MISMATCH,
                date,
                "news",
                "; ".join(problems),
            )
        platforms = [
            {"id": r[0], "name": r[1], "is_active": bool(r[2])}
            for r in conn.execute(
                "SELECT id, name, is_active FROM platforms ORDER BY id"
            )
        ]
        platform_names = {p["id"]: p["name"] for p in platforms}

        items: list[dict[str, Any]] = []
        item_ids: list[int] = []
        news_rows = conn.execute(
            """
            SELECT id, title, platform_id, rank, url, mobile_url,
                   first_crawl_time, last_crawl_time, crawl_count
            FROM news_items ORDER BY platform_id, rank, id
            """
        ).fetchall()
        history_rows: dict[int, list[dict[str, Any]]] = {}
        ranks_by_item: dict[int, list[int]] = {}
        if news_rows:
            item_ids = [row[0] for row in news_rows]
            placeholders = ",".join("?" * len(item_ids))
            for news_id, rank, crawl_time in conn.execute(
                f"""
                SELECT news_item_id, rank, crawl_time FROM rank_history
                WHERE news_item_id IN ({placeholders})
                ORDER BY news_item_id, crawl_time, id
                """,
                item_ids,
            ):
                entry: dict[str, Any] = {
                    "crawl_time": crawl_time,
                    "rank": int(rank),
                    "off_list": int(rank) == OFF_LIST_RANK,
                }
                history_rows.setdefault(int(news_id), []).append(entry)
                observed = ranks_by_item.setdefault(int(news_id), [])
                if int(rank) != OFF_LIST_RANK and int(rank) not in observed:
                    observed.append(int(rank))
        for row in news_rows:
            news_id, title, platform_id, rank, url, mobile_url, first_at, last_at, count = row
            items.append(
                {
                    "id": int(news_id),
                    "title": title,
                    "platform_id": platform_id,
                    "platform_name": platform_names.get(platform_id, platform_id),
                    "rank": int(rank),
                    "url": url or "",
                    "mobile_url": mobile_url or "",
                    "first_crawl_time": first_at,
                    "last_crawl_time": last_at,
                    "crawl_count": int(count),
                    "observed_ranks": ranks_by_item.get(news_id, []),
                    "rank_timeline": history_rows.get(news_id, []),
                }
            )

        batches = [
            {"crawl_time": r[0], "total_items": int(r[1])}
            for r in conn.execute(
                "SELECT crawl_time, total_items FROM crawl_records ORDER BY crawl_time"
            )
        ]
        source_status = [
            {
                "platform_id": r[0],
                "status": r[1],
                "failed_at": r[2],
            }
            for r in conn.execute(
                """
                SELECT css.platform_id, css.status, cr.crawl_time
                FROM crawl_source_status css
                JOIN crawl_records cr ON css.crawl_record_id = cr.id
                ORDER BY cr.crawl_time, css.platform_id
                """
            )
        ]

        envelope = _envelope(STATUS_OK, date, "news")
        envelope["observation"] = {
            "platforms": platforms,
            "items": items,
            "item_count": len(items),
            "crawl_batches": batches,
            "source_status": source_status,
        }
        return envelope
    except sqlite3.Error as exc:
        return _envelope(STATUS_UNAVAILABLE, date, "news", str(exc))
    finally:
        conn.close()


def observe_news_ai_filter(
    output_root: str | Path, date: str
) -> dict[str, Any]:
    """AI-filter provenance 元数据（hotlist 源）；schema 已实证。"""
    try:
        db_path = resolve_db_path(output_root, "news", date)
    except ValueError as exc:
        return _envelope(STATUS_BAD_ARGUMENT, date, "news_ai_filter", str(exc))
    if not db_path.is_file():
        return _envelope(STATUS_NOT_FOUND, date, "news_ai_filter")
    try:
        conn = _connect_readonly(db_path)
    except sqlite3.Error as exc:
        return _envelope(STATUS_UNAVAILABLE, date, "news_ai_filter", str(exc))
    required = dict(_REQUIRED_NEWS_SCHEMA)
    required.update(
        {
            "ai_filter_tags": (
                "id",
                "tag",
                "status",
                "version",
                "interests_file",
            ),
            "ai_filter_results": (
                "news_item_id",
                "source_type",
                "tag_id",
                "relevance_score",
                "status",
            ),
            "ai_filter_analyzed_news": (
                "news_item_id",
                "source_type",
                "matched",
            ),
        }
    )
    try:
        problems = _validate_contract(conn, required)
        if problems:
            return _envelope(
                STATUS_CONTRACT_MISMATCH,
                date,
                "news_ai_filter",
                "; ".join(problems),
            )
        tags = conn.execute(
            """
            SELECT t.id, t.tag, t.version, t.interests_file
            FROM ai_filter_tags t WHERE t.status = 'active'
            """
        ).fetchall()
        tag_meta = {row[0]: {"tag": row[1], "version": row[2], "interests_file": row[3]} for row in tags}
        matches: dict[int, list[dict[str, Any]]] = {}
        for news_id, tag_id, score in conn.execute(
            """
            SELECT news_item_id, tag_id, relevance_score
            FROM ai_filter_results
            WHERE source_type = 'hotlist' AND status = 'active'
            ORDER BY news_item_id, tag_id
            """
        ):
            meta = tag_meta.get(tag_id)
            matches.setdefault(int(news_id), []).append(
                {
                    "tag": meta["tag"] if meta else f"tag:{tag_id}",
                    "relevance_score": float(score or 0.0),
                    "tag_version": meta["version"] if meta else None,
                }
            )
        analyzed = conn.execute(
            """
            SELECT news_item_id, matched FROM ai_filter_analyzed_news
            WHERE source_type = 'hotlist'
            """
        ).fetchall()
        analyzed_flag = {int(r[0]): bool(r[1]) for r in analyzed}
        envelope = _envelope(STATUS_OK, date, "news_ai_filter")
        envelope["observation"] = {
            "tags_active": [meta for meta in tag_meta.values()],
            "matches": [
                {"news_item_id": k, "matched_tags": v} for k, v in matches.items()
            ],
            "analyzed_news_count": len(analyzed_flag),
            "matched_news_count": sum(1 for v in analyzed_flag.values() if v),
        }
        return envelope
    except sqlite3.Error as exc:
        return _envelope(STATUS_UNAVAILABLE, date, "news_ai_filter", str(exc))
    finally:
        conn.close()


def observe_rss(output_root: str | Path, date: str) -> dict[str, Any]:
    """读取某日 RSS 库的 observation 视图。"""
    try:
        db_path = resolve_db_path(output_root, "rss", date)
    except ValueError as exc:
        return _envelope(STATUS_BAD_ARGUMENT, date, "rss", str(exc))
    if not db_path.is_file():
        return _envelope(STATUS_NOT_FOUND, date, "rss")
    try:
        conn = _connect_readonly(db_path)
    except sqlite3.Error as exc:
        return _envelope(STATUS_UNAVAILABLE, date, "rss", str(exc))
    try:
        problems = _validate_contract(conn, _REQUIRED_RSS_SCHEMA)
        if problems:
            return _envelope(
                STATUS_CONTRACT_MISMATCH,
                date,
                "rss",
                "; ".join(problems),
            )
        feeds = [
            {
                "id": r[0],
                "name": r[1],
                "is_active": bool(r[2]),
                "last_fetch_time": r[3],
                "last_fetch_status": r[4],
                "item_count": int(r[5]),
            }
            for r in conn.execute(
                """
                SELECT id, name, is_active, last_fetch_time, last_fetch_status,
                       item_count
                FROM rss_feeds ORDER BY id
                """
            )
        ]
        items = [
            {
                "id": int(r[0]),
                "title": r[1],
                "feed_id": r[2],
                "url": r[3],
                "guid": r[4] or "",
                "published_at": r[5],
                "summary": r[6],
                "author": r[7],
                "first_crawl_time": r[8],
                "last_crawl_time": r[9],
                "crawl_count": int(r[10]),
            }
            for r in conn.execute(
                """
                SELECT id, title, feed_id, url, guid, published_at, summary,
                       author, first_crawl_time, last_crawl_time, crawl_count
                FROM rss_items ORDER BY feed_id, id
                """
            )
        ]
        batches = [
            {"crawl_time": r[0], "total_items": int(r[1])}
            for r in conn.execute(
                "SELECT crawl_time, total_items FROM rss_crawl_records "
                "ORDER BY crawl_time"
            )
        ]
        fetch_status = [
            {
                "feed_id": r[0],
                "status": r[1],
                "error_message": r[2] or "",
                "fetched_at": r[3],
            }
            for r in conn.execute(
                """
                SELECT s.feed_id, s.status, s.error_message, c.crawl_time
                FROM rss_crawl_status s
                JOIN rss_crawl_records c ON s.crawl_record_id = c.id
                ORDER BY c.crawl_time, s.feed_id
                """
            )
        ]
        envelope = _envelope(STATUS_OK, date, "rss")
        envelope["observation"] = {
            "feeds": feeds,
            "items": items,
            "item_count": len(items),
            "crawl_batches": batches,
            "fetch_status": fetch_status,
        }
        return envelope
    except sqlite3.Error as exc:
        return _envelope(STATUS_UNAVAILABLE, date, "rss", str(exc))
    finally:
        conn.close()
