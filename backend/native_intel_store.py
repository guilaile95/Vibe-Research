"""Native Intel 本地资讯数据层（NATIVE-INTEL1）。

Vibe 自有的 MIT 原生资讯持久化：source registry / fetch run / item / observation /
entity mapping。

时间语义严格区分（不得混用）：
- ``published_at``  来源声明的发布时间；来源未声明时为 NULL，**绝不用抓取时间伪造**。
- ``observed_at``   本次抓取实际观测到的时间。
- ``first_seen_at`` / ``last_seen_at``  跨 observation 聚合的首见 / 末见时间。

排名语义：只有 ``has_real_rank = 1`` 的来源才会写入 ``observations.rank``。
RSS 源没有真实排名，``rank`` 恒为 NULL，读取侧必须诚实报告 UNKNOWN，禁止补 0。

来源失败语义：单源失败写入 ``intel_source_runs(status='failed')`` 且不影响其他源；
``partial`` 与空列表是两种不同状态，失败绝不能退化成「无数据」。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

SCHEMA_VERSION = "native_intel.v1"
DB_FILENAME = "native_intel.sqlite3"

# fetch run 状态
RUN_STATUS_RUNNING = "running"
ANALYSIS_STATE_CLASSIFIED = "CLASSIFIED"
ANALYSIS_STATE_NOT_RELEVANT = "NOT_RELEVANT"
ANALYSIS_STATE_ERROR = "ERROR"

RUN_STATUS_OK = "ok"
RUN_STATUS_PARTIAL = "partial"
RUN_STATUS_FAILED = "failed"
RUN_STATUSES = (RUN_STATUS_RUNNING, RUN_STATUS_OK, RUN_STATUS_PARTIAL, RUN_STATUS_FAILED)

# 单源在一次 run 内的状态
SOURCE_RUN_OK = "ok"
SOURCE_RUN_EMPTY = "empty"
SOURCE_RUN_FAILED = "failed"
SOURCE_RUN_STATUSES = (SOURCE_RUN_OK, SOURCE_RUN_EMPTY, SOURCE_RUN_FAILED)

# 失败归类；detail 只存异常类名，绝不存 URL / 消息正文（可能含查询串与凭证）
ERROR_KIND_NETWORK = "network"
ERROR_KIND_TIMEOUT = "timeout"
ERROR_KIND_HTTP = "http"
ERROR_KIND_PARSE = "parse"
ERROR_KIND_UNKNOWN = "unknown"
ERROR_KINDS = (
    ERROR_KIND_NETWORK,
    ERROR_KIND_TIMEOUT,
    ERROR_KIND_HTTP,
    ERROR_KIND_PARSE,
    ERROR_KIND_UNKNOWN,
)

# 实体词类型
TERM_SECURITY_CODE = "security_code"
TERM_COMPANY_NAME = "company_name"
TERM_INDUSTRY = "industry"
TERM_CONCEPT = "concept"
TERM_KINDS = (TERM_SECURITY_CODE, TERM_COMPANY_NAME, TERM_INDUSTRY, TERM_CONCEPT)


class NativeIntelStoreError(RuntimeError):
    """本地资讯持久化不可用。"""

    MESSAGE = "本地资讯数据存储不可用，无法读写"

    def __init__(self):
        super().__init__(self.MESSAGE)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS intel_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    hint TEXT NOT NULL,
    url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    has_real_rank INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    origin TEXT NOT NULL DEFAULT 'system',
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    re_enabled_at TEXT,
    re_enabled_after_run_id TEXT
);

CREATE TABLE IF NOT EXISTS intel_fetch_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    trigger TEXT NOT NULL,
    source_total INTEGER NOT NULL DEFAULT 0,
    source_ok INTEGER NOT NULL DEFAULT 0,
    source_failed INTEGER NOT NULL DEFAULT 0,
    item_seen INTEGER NOT NULL DEFAULT 0,
    item_new INTEGER NOT NULL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS intel_source_runs (
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    error_kind TEXT,
    error_detail TEXT,
    duration_ms INTEGER,
    PRIMARY KEY (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS intel_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL UNIQUE,
    canonical_url TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL,
    summary TEXT,
    source_id TEXT NOT NULL,
    hint TEXT NOT NULL,
    published_at TEXT,
    published_ts INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    observation_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_observations (
    obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    rank INTEGER,
    observed_title TEXT NOT NULL,
    published_at TEXT,
    UNIQUE (run_id, source_id, item_id)
);

CREATE TABLE IF NOT EXISTS intel_security_directory (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_entity_terms (
    term TEXT NOT NULL,
    term_kind TEXT NOT NULL,
    security_code TEXT,
    source_ref TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (term, term_kind, security_code)
);

CREATE TABLE IF NOT EXISTS intel_item_entities (
    item_id INTEGER NOT NULL,
    term_kind TEXT NOT NULL,
    term TEXT NOT NULL,
    security_code TEXT,
    matched_in TEXT NOT NULL,
    PRIMARY KEY (item_id, term_kind, term, security_code)
);

CREATE TABLE IF NOT EXISTS intel_filter_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'keyword',
    interests_text TEXT NOT NULL DEFAULT '',
    min_score REAL NOT NULL DEFAULT 0.7,
    keyword_rules_json TEXT NOT NULL DEFAULT '{}',
    tags_json TEXT NOT NULL DEFAULT '[]',
    profile_fingerprint TEXT NOT NULL DEFAULT '',
    reclassify_threshold REAL NOT NULL DEFAULT 0.6,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_item_classifications (
    item_id INTEGER NOT NULL,
    profile_id TEXT NOT NULL,
    profile_fingerprint TEXT NOT NULL,
    primary_tag TEXT NOT NULL,
    relevance_score REAL NOT NULL,
    classified_at TEXT NOT NULL,
    provider_identity TEXT,
    PRIMARY KEY (item_id, profile_id, profile_fingerprint)
);

CREATE TABLE IF NOT EXISTS intel_item_filter_analysis (
    item_id INTEGER NOT NULL,
    profile_id TEXT NOT NULL,
    profile_fingerprint TEXT NOT NULL,
    analysis_state TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    provider_identity TEXT,
    error_kind TEXT,
    PRIMARY KEY (item_id, profile_id, profile_fingerprint)
);
"""

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_intel_items_hint_seen ON intel_items (hint, last_seen_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intel_items_source ON intel_items (source_id, last_seen_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intel_items_published ON intel_items (published_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intel_obs_item ON intel_observations (item_id, observed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intel_obs_run ON intel_observations (run_id)",
    "CREATE INDEX IF NOT EXISTS idx_intel_source_runs_src ON intel_source_runs (source_id, run_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intel_item_entities_code ON intel_item_entities (security_code, item_id)",
    "CREATE INDEX IF NOT EXISTS idx_intel_entity_terms_code ON intel_entity_terms (security_code)",
    "CREATE INDEX IF NOT EXISTS idx_intel_classifications_lookup ON intel_item_classifications (profile_id, profile_fingerprint, relevance_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intel_classifications_tag ON intel_item_classifications (profile_id, profile_fingerprint, primary_tag)",
    "CREATE INDEX IF NOT EXISTS idx_intel_classifications_item ON intel_item_classifications (item_id)",
    "CREATE INDEX IF NOT EXISTS idx_intel_analysis_lookup ON intel_item_filter_analysis (profile_id, profile_fingerprint, analysis_state)",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_default_db_path() -> Path:
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    base = Path(env_dir) if env_dir else Path.home() / ".vibe-research"
    return base / DB_FILENAME


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize_store(db_path: str | Path | None = None) -> None:
    path = Path(db_path) if db_path else get_default_db_path()
    with _LOCK:
        try:
            with _connect(path) as conn:
                conn.executescript(_SCHEMA_SQL)
                _migrate_schema(conn)
                for sql in _INDEX_SQL:
                    conn.execute(sql)
                conn.execute(
                    "INSERT INTO intel_meta (key, value) VALUES ('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (SCHEMA_VERSION,),
                )
                conn.commit()
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Upgrade the uncommitted NATIVE-INTEL1 draft without losing local observations."""
    directory_columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(intel_security_directory)")
    }
    if "industry" not in directory_columns:
        conn.execute("ALTER TABLE intel_security_directory ADD COLUMN industry TEXT")

    source_columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(intel_sources)")
    }
    if "origin" not in source_columns:
        # TREND-PARITY Wave 1：系统 seed 源 origin=system，用户自建源 origin=user；
        # 删除权限只看 origin，已有库存量行全部视为系统源。
        conn.execute("ALTER TABLE intel_sources ADD COLUMN origin TEXT NOT NULL DEFAULT 'system'")
    if "deleted_at" not in source_columns:
        conn.execute("ALTER TABLE intel_sources ADD COLUMN deleted_at TEXT")
    if "re_enabled_at" not in source_columns:
        conn.execute("ALTER TABLE intel_sources ADD COLUMN re_enabled_at TEXT")
    if "re_enabled_after_run_id" not in source_columns:
        conn.execute("ALTER TABLE intel_sources ADD COLUMN re_enabled_after_run_id TEXT")

    item_entity_pk = [
        str(row["name"])
        for row in sorted(
            conn.execute("PRAGMA table_info(intel_item_entities)").fetchall(),
            key=lambda row: int(row["pk"] or 0),
        )
        if row["pk"]
    ]
    expected_pk = ["item_id", "term_kind", "term", "security_code"]
    if item_entity_pk == expected_pk:
        return

    conn.execute("ALTER TABLE intel_item_entities RENAME TO intel_item_entities_legacy")
    conn.execute(
        """
        CREATE TABLE intel_item_entities (
            item_id INTEGER NOT NULL,
            term_kind TEXT NOT NULL,
            term TEXT NOT NULL,
            security_code TEXT,
            matched_in TEXT NOT NULL,
            PRIMARY KEY (item_id, term_kind, term, security_code)
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO intel_item_entities
            (item_id, term_kind, term, security_code, matched_in)
        SELECT item_id, term_kind, term, security_code, matched_in
        FROM intel_item_entities_legacy
        """
    )
    conn.execute("DROP TABLE intel_item_entities_legacy")


# ---------------------------------------------------------------------------
# source registry
# ---------------------------------------------------------------------------


def upsert_sources(
    sources: list[dict[str, Any]],
    db_path: str | Path | None = None,
) -> int:
    """写入 / 更新来源注册表；返回注册表内来源总数。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    now = utc_now_iso()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    for src in sources:
                        conn.execute(
                            """
                            INSERT INTO intel_sources
                                (source_id, name, hint, url, source_type, has_real_rank, enabled, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                            ON CONFLICT(source_id) DO UPDATE SET
                                name = excluded.name,
                                hint = excluded.hint,
                                url = excluded.url,
                                source_type = excluded.source_type,
                                has_real_rank = excluded.has_real_rank,
                                updated_at = excluded.updated_at
                            """,
                            (
                                src["source_id"],
                                src["name"],
                                src["hint"],
                                src["url"],
                                src.get("source_type", "rss"),
                                1 if src.get("has_real_rank") else 0,
                                now,
                            ),
                        )
                return int(
                    conn.execute("SELECT COUNT(*) AS n FROM intel_sources").fetchone()["n"]
                )
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def list_sources(
    db_path: str | Path | None = None,
    *,
    enabled_only: bool = True,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    sql = "SELECT * FROM intel_sources WHERE 1=1"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    if enabled_only:
        sql += " AND enabled = 1"
    sql += " ORDER BY hint, name"
    with _LOCK:
        try:
            with _connect(path) as conn:
                return [dict(row) for row in conn.execute(sql).fetchall()]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


class SourceAlreadyExistsError(NativeIntelStoreError):
    """来源冲突（同名或同 URL 的活跃自建源已存在）。"""


class SourceNotFoundError(NativeIntelStoreError):
    """来源不存在。"""


class SystemSourceDeleteBlocked(NativeIntelStoreError):
    """系统来源禁止删除（fail closed；允许停用）。"""


def get_source(
    source_id: str,
    db_path: str | Path | None = None,
    *,
    include_deleted: bool = False,
) -> dict[str, Any] | None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    sql = "SELECT * FROM intel_sources WHERE source_id = ?"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(sql, (source_id,)).fetchone()
                return dict(row) if row else None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def insert_user_source(
    *,
    source_id: str,
    name: str,
    url: str,
    hint: str,
    enabled: bool = True,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """新增用户自建 RSS 源（origin=user）；source_id 或活跃 (name, url) 冲突时拒绝。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    now = utc_now_iso()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    exists = conn.execute(
                        """
                        SELECT 1 FROM intel_sources
                        WHERE source_id = ? OR ((name = ? OR url = ?) AND deleted_at IS NULL)
                        """,
                        (source_id, name, url),
                    ).fetchone()
                    if exists:
                        raise SourceAlreadyExistsError()
                    conn.execute(
                        """
                        INSERT INTO intel_sources
                            (source_id, name, hint, url, source_type, has_real_rank,
                             enabled, origin, updated_at)
                        VALUES (?, ?, ?, ?, 'rss', 0, ?, 'user', ?)
                        """,
                        (source_id, name, hint, url, 1 if enabled else 0, now),
                    )
                row = conn.execute(
                    "SELECT * FROM intel_sources WHERE source_id = ?", (source_id,)
                ).fetchone()
                return dict(row)
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def update_source(
    source_id: str,
    *,
    enabled: bool | None = None,
    name: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """更新来源；``enabled`` 系统源与用户源均可，``name`` 仅用户源可改。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    current = conn.execute(
                        "SELECT enabled, deleted_at FROM intel_sources WHERE source_id = ?",
                        (source_id,),
                    ).fetchone()
                    if current is None or current["deleted_at"] is not None:
                        return None
                    was_enabled = bool(current["enabled"])
                    assignments: list[str] = []
                    args: list[Any] = []
                    if enabled is not None:
                        assignments.append("enabled = ?")
                        args.append(1 if enabled else 0)
                        if enabled and not was_enabled:
                            assignments.append("re_enabled_at = ?")
                            args.append(utc_now_iso())
                            last_run = conn.execute(
                                "SELECT run_id FROM intel_source_runs WHERE source_id = ? ORDER BY rowid DESC LIMIT 1",
                                (source_id,),
                            ).fetchone()
                            assignments.append("re_enabled_after_run_id = ?")
                            args.append(str(last_run["run_id"]) if last_run else "__NONE__")
                        elif not enabled:
                            assignments.append("re_enabled_at = NULL")
                            assignments.append("re_enabled_after_run_id = NULL")
                    if name is not None:
                        assignments.append("name = ?")
                        args.append(name)
                    if not assignments:
                        row = conn.execute(
                            "SELECT * FROM intel_sources WHERE source_id = ?", (source_id,)
                        ).fetchone()
                        return dict(row) if row else None
                    assignments.append("updated_at = ?")
                    args.append(utc_now_iso())
                    args.append(source_id)
                    cursor = conn.execute(
                        f"UPDATE intel_sources SET {', '.join(assignments)} WHERE source_id = ?",
                        tuple(args),
                    )
                    if cursor.rowcount == 0:
                        return None
                row = conn.execute(
                    "SELECT * FROM intel_sources WHERE source_id = ?", (source_id,)
                ).fetchone()
                return dict(row) if row else None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def delete_user_source(source_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    """删除用户源（软删除保留历史 provenance）；系统源删除请求 fail closed（可停用，不可删除）。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    now = utc_now_iso()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    row = conn.execute(
                        "SELECT * FROM intel_sources WHERE source_id = ?", (source_id,)
                    ).fetchone()
                    if row is None or row["deleted_at"] is not None:
                        raise SourceNotFoundError()
                    if str(row["origin"]) != "user":
                        raise SystemSourceDeleteBlocked()
                    conn.execute(
                        """
                        UPDATE intel_sources
                        SET deleted_at = ?, enabled = 0, updated_at = ?
                        WHERE source_id = ?
                        """,
                        (now, now, source_id),
                    )
                    return dict(row)
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def any_source_has_real_rank(db_path: str | Path | None = None) -> bool:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    "SELECT 1 FROM intel_sources WHERE has_real_rank = 1 AND enabled = 1 LIMIT 1"
                ).fetchone()
                return row is not None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def list_hotlist_items(
    db_path: str | Path | None = None,
    *,
    limit: int = 60,
) -> list[dict[str, Any]]:
    """热榜板面基础行：全部 hotlist 来源的条目（不含排名状态，读取侧另行推导）。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    """
                    SELECT i.*, s.name AS source_name, s.source_type, s.has_real_rank
                    FROM intel_items i
                    JOIN intel_sources s ON s.source_id = i.source_id
                    WHERE s.source_type = 'hotlist'
                    ORDER BY i.last_seen_at DESC, i.item_id DESC
                    LIMIT ?
                    """,
                    (max(1, min(int(limit), 200)),),
                ).fetchall()
                return [_item_row(row) for row in rows]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def list_item_entities(
    item_ids: list[int],
    db_path: str | Path | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """批量读取条目的实体映射；返回 ``{item_id: [entity]}``。"""
    if not item_ids:
        return {}
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    placeholders = ",".join("?" for _ in item_ids)
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    f"""
                    SELECT item_id, term_kind, term, security_code
                    FROM intel_item_entities
                    WHERE item_id IN ({placeholders})
                    """,
                    tuple(int(i) for i in item_ids),
                ).fetchall()
                out: dict[int, list[dict[str, Any]]] = {}
                for row in rows:
                    out.setdefault(int(row["item_id"]), []).append(
                        {
                            "term_kind": row["term_kind"],
                            "term": row["term"],
                            "security_code": row["security_code"],
                        }
                    )
                return out
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def latest_source_run(
    source_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """某来源最近一次 fetch run 中的单源结果（ok/empty/failed）。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    """
                    SELECT run_id, status, error_kind FROM intel_source_runs
                    WHERE source_id = ?
                    ORDER BY rowid DESC
                    LIMIT 1
                    """,
                    (source_id,),
                ).fetchone()
                return dict(row) if row else None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


# 排名轨迹状态：只在读取侧推导，绝不写回 items/observations（不造第二份 authority）。
ITEM_STATE_ON_LIST = "ON_LIST"
ITEM_STATE_OFF_LIST = "OFF_LIST"
ITEM_STATE_UNKNOWN = "UNKNOWN"
ITEM_STATE_DISABLED = "DISABLED"
ITEM_STATE_STALE = "STALE"
ITEM_STATE_NO_RANK_SEMANTICS = "NO_RANK_SEMANTICS"
STALE_AFTER_HOURS = 6


def get_item_rank_state(
    item_id: int,
    db_path: str | Path | None = None,
    *,
    stale_after_hours: int = STALE_AFTER_HOURS,
) -> dict[str, Any]:
    """推导条目的当前排名状态（Wave 1 off-list / disabled 语义的唯一权威读法）。

    - 无排名语义来源（RSS）→ NO_RANK_SEMANTICS，rank 恒 None；
    - 来源已停用 / 已删除（enabled=false 或 deleted_at 非空）→ DISABLED；保留末次 rank 供审计，但不当实时在榜；
    - 来源重新启用后尚未完成新一次成功抓取 → UNKNOWN，绝不拿旧 run 伪造在榜；
    - 最近一次「来源级 run」失败（或尚无 run）→ UNKNOWN：失败绝不当掉榜；
    - 该 run 抓取成功且条目未出现 → OFF_LIST（不写 rank=0，rank 保持最后真实值）；
    - 该 run 抓取成功且条目出现 → ON_LIST，rank 为该 run 观测到的真实排名；
    - 排名身份以 SOURCE + ITEM 严格隔离，绝不跨平台串联历史；
    - ``previous_rank`` / ``rank_delta`` 取相邻两次真实观测（delta 正数 = 排名上升）。
    """
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                item = conn.execute(
                    """
                    SELECT i.item_id, i.source_id, i.first_seen_at, i.last_seen_at,
                           i.observation_count, s.has_real_rank, s.source_type,
                           s.name AS source_name, s.enabled, s.deleted_at, s.re_enabled_at,
                           s.re_enabled_after_run_id
                    FROM intel_items i
                    LEFT JOIN intel_sources s ON s.source_id = i.source_id
                    WHERE i.item_id = ?
                    """,
                    (item_id,),
                ).fetchone()
                if item is None:
                    return {}
                has_real_rank = bool(item["has_real_rank"])
                source_id = str(item["source_id"])
                # 严格按 (item_id, source_id) 双重限定，杜绝跨平台 rank 污染
                observations = [
                    {"observed_at": r["observed_at"], "rank": int(r["rank"])}
                    for r in conn.execute(
                        """
                        SELECT observed_at, rank FROM intel_observations
                        WHERE item_id = ? AND source_id = ? AND rank IS NOT NULL
                        ORDER BY observed_at ASC, obs_id ASC
                        """,
                        (item_id, source_id),
                    ).fetchall()
                ]
                result: dict[str, Any] = {
                    "item_id": int(item["item_id"]),
                    "source_id": source_id,
                    "source_name": item["source_name"],
                    "source_type": item["source_type"],
                    "has_real_rank": has_real_rank,
                    "first_seen_at": item["first_seen_at"],
                    "last_seen_at": item["last_seen_at"],
                    "observation_count": int(item["observation_count"] or 0),
                    "observations": observations,
                }

                last_run_row = conn.execute(
                    """
                    SELECT sr.run_id, sr.status, sr.error_kind, r.started_at
                    FROM intel_source_runs sr
                    JOIN intel_fetch_runs r ON r.run_id = sr.run_id
                    WHERE sr.source_id = ?
                    ORDER BY sr.rowid DESC
                    LIMIT 1
                    """,
                    (source_id,),
                ).fetchone()
                last_run = dict(last_run_row) if last_run_row else None
                result["last_run_id"] = last_run["run_id"] if last_run else None

                # 1. 停用 / 删除：状态必须显式降级为 DISABLED，绝不伪装为 ON_LIST / OFF_LIST
                is_disabled = (
                    item["enabled"] is None
                    or not bool(item["enabled"])
                    or item["deleted_at"] is not None
                )
                if is_disabled:
                    result["current_state"] = ITEM_STATE_DISABLED
                    result["current_rank"] = observations[-1]["rank"] if observations else None
                    result["previous_rank"] = (
                        observations[-2]["rank"] if len(observations) >= 2 else None
                    )
                    result["rank_delta"] = (
                        result["previous_rank"] - result["current_rank"]
                        if result["current_rank"] is not None and result["previous_rank"] is not None
                        else None
                    )
                    return result

                if not has_real_rank:
                    result["current_state"] = ITEM_STATE_NO_RANK_SEMANTICS
                    result["current_rank"] = None
                    result["previous_rank"] = None
                    result["rank_delta"] = None
                    result["last_run_id"] = None
                    return result

                # 2. 重新启用：在新的成功抓取发生前，必须保持 UNKNOWN，不得由旧 run 恢复为 ON_LIST
                re_after = item["re_enabled_after_run_id"]
                if re_after is not None:
                    if last_run is None or last_run["run_id"] == re_after:
                        result["current_state"] = ITEM_STATE_UNKNOWN
                        result["current_rank"] = observations[-1]["rank"] if observations else None
                        result["previous_rank"] = (
                            observations[-2]["rank"] if len(observations) >= 2 else None
                        )
                        result["rank_delta"] = (
                            result["previous_rank"] - result["current_rank"]
                            if result["current_rank"] is not None and result["previous_rank"] is not None
                            else None
                        )
                        return result

                last_successful = (
                    last_run is not None
                    and last_run["status"] in (SOURCE_RUN_OK, SOURCE_RUN_EMPTY)
                )
                if not last_successful:
                    # 从未抓取成功，或最近一次失败：现状未知，保留最后真实排名
                    result["current_state"] = ITEM_STATE_UNKNOWN
                    result["current_rank"] = observations[-1]["rank"] if observations else None
                    result["previous_rank"] = (
                        observations[-2]["rank"] if len(observations) >= 2 else None
                    )
                    result["rank_delta"] = (
                        result["previous_rank"] - result["current_rank"]
                        if result["current_rank"] is not None and result["previous_rank"] is not None
                        else None
                    )
                    return result

                # 3. 数据时效（Freshness / Stale 检查）：超过时效窗口的数据必须标记为 STALE，不得伪造实时在榜
                is_stale = False
                if last_run and last_run.get("started_at"):
                    try:
                        started_dt = datetime.fromisoformat(
                            str(last_run["started_at"]).replace("Z", "+00:00")
                        )
                        if datetime.now(timezone.utc) - started_dt > timedelta(hours=stale_after_hours):
                            is_stale = True
                    except ValueError:
                        is_stale = True

                if is_stale:
                    result["current_state"] = ITEM_STATE_STALE
                    result["current_rank"] = observations[-1]["rank"] if observations else None
                    result["previous_rank"] = (
                        observations[-2]["rank"] if len(observations) >= 2 else None
                    )
                    result["rank_delta"] = (
                        result["previous_rank"] - result["current_rank"]
                        if result["current_rank"] is not None and result["previous_rank"] is not None
                        else None
                    )
                    return result

                present = False
                if last_run is not None:
                    seen = conn.execute(
                        "SELECT 1 FROM intel_observations WHERE item_id = ? AND source_id = ? AND run_id = ?",
                        (item_id, source_id, last_run["run_id"]),
                    ).fetchone()
                    present = seen is not None
                current_rank = None
                if present and last_run is not None:
                    row = conn.execute(
                        """
                        SELECT rank FROM intel_observations
                        WHERE item_id = ? AND source_id = ? AND run_id = ? AND rank IS NOT NULL
                        ORDER BY observed_at DESC, obs_id DESC LIMIT 1
                        """,
                        (item_id, source_id, last_run["run_id"]),
                    ).fetchone()
                    current_rank = int(row["rank"]) if row and row["rank"] is not None else None
                previous_rank = observations[-2]["rank"] if len(observations) >= 2 else None
                if current_rank is None:
                    current_rank = observations[-1]["rank"] if observations else None
                    previous_rank = observations[-2]["rank"] if len(observations) >= 2 else None
                result["current_state"] = ITEM_STATE_ON_LIST if present else ITEM_STATE_OFF_LIST
                result["current_rank"] = current_rank
                result["previous_rank"] = previous_rank
                result["rank_delta"] = (
                    previous_rank - current_rank
                    if current_rank is not None and previous_rank is not None
                    else None
                )
                return result
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


# ---------------------------------------------------------------------------
# fetch run 生命周期
# ---------------------------------------------------------------------------


def start_run(
    run_id: str,
    trigger: str,
    source_total: int,
    db_path: str | Path | None = None,
    *,
    started_at: str | None = None,
) -> None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO intel_fetch_runs
                            (run_id, started_at, status, trigger, source_total)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (run_id, started_at or utc_now_iso(), RUN_STATUS_RUNNING, trigger, source_total),
                    )
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def finish_run(
    run_id: str,
    *,
    status: str,
    source_ok: int,
    source_failed: int,
    item_seen: int,
    item_new: int,
    note: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    path = Path(db_path) if db_path else get_default_db_path()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    conn.execute(
                        """
                        UPDATE intel_fetch_runs
                        SET finished_at = ?, status = ?, source_ok = ?, source_failed = ?,
                            item_seen = ?, item_new = ?, note = ?
                        WHERE run_id = ?
                        """,
                        (
                            utc_now_iso(),
                            status if status in RUN_STATUSES else RUN_STATUS_FAILED,
                            source_ok,
                            source_failed,
                            item_seen,
                            item_new,
                            note,
                            run_id,
                        ),
                    )
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def record_source_run(
    run_id: str,
    source_id: str,
    *,
    status: str,
    item_count: int = 0,
    error_kind: str | None = None,
    error_detail: str | None = None,
    duration_ms: int | None = None,
    db_path: str | Path | None = None,
) -> None:
    path = Path(db_path) if db_path else get_default_db_path()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO intel_source_runs
                            (run_id, source_id, status, item_count, error_kind, error_detail, duration_ms)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(run_id, source_id) DO UPDATE SET
                            status = excluded.status,
                            item_count = excluded.item_count,
                            error_kind = excluded.error_kind,
                            error_detail = excluded.error_detail,
                            duration_ms = excluded.duration_ms
                        """,
                        (
                            run_id,
                            source_id,
                            status if status in SOURCE_RUN_STATUSES else SOURCE_RUN_FAILED,
                            item_count,
                            error_kind if error_kind in ERROR_KINDS else None,
                            error_detail,
                            duration_ms,
                        ),
                    )
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_run(
    run_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    "SELECT * FROM intel_fetch_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                return dict(row) if row else None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_latest_run(
    db_path: str | Path | None = None,
    *,
    statuses: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    """最近一次 run；``statuses`` 非空时只在该集合内取最近一次（用于取最近成功 run）。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    sql = "SELECT * FROM intel_fetch_runs"
    args: tuple[Any, ...] = ()
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        sql += f" WHERE status IN ({placeholders})"
        args = statuses
    sql += " ORDER BY started_at DESC, run_id DESC LIMIT 1"
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(sql, args).fetchone()
                return dict(row) if row else None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_source_runs(
    run_id: str,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    """
                    SELECT sr.*, s.name, s.hint, s.url, s.source_type, s.has_real_rank
                    FROM intel_source_runs sr
                    LEFT JOIN intel_sources s ON s.source_id = sr.source_id
                    WHERE sr.run_id = ?
                    ORDER BY s.hint, s.name
                    """,
                    (run_id,),
                ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_source_health(
    db_path: str | Path | None = None,
    *,
    limit_runs: int = 5,
) -> list[dict[str, Any]]:
    """每个来源最近若干次 run 的健康状况，用于 status 面板诚实展示失败来源。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                sources = conn.execute(
                    "SELECT * FROM intel_sources ORDER BY hint, name"
                ).fetchall()
                out: list[dict[str, Any]] = []
                for src in sources:
                    rows = conn.execute(
                        """
                        SELECT sr.status, sr.item_count, sr.error_kind, sr.duration_ms, r.started_at
                        FROM intel_source_runs sr
                        JOIN intel_fetch_runs r ON r.run_id = sr.run_id
                        WHERE sr.source_id = ?
                        ORDER BY r.started_at DESC
                        LIMIT ?
                        """,
                        (src["source_id"], limit_runs),
                    ).fetchall()
                    statuses = [r["status"] for r in rows]
                    last = rows[0] if rows else None
                    out.append(
                        {
                            "source_id": src["source_id"],
                            "name": src["name"],
                            "hint": src["hint"],
                            "source_type": src["source_type"],
                            "has_real_rank": bool(src["has_real_rank"]),
                            "enabled": bool(src["enabled"]),
                            "run_count": len(rows),
                            "last_status": last["status"] if last else "unknown",
                            "last_item_count": last["item_count"] if last else 0,
                            "last_error_kind": last["error_kind"] if last else None,
                            "last_observed_at": last["started_at"] if last else None,
                            "consecutive_failures": _count_leading(statuses, SOURCE_RUN_FAILED),
                            "recent_statuses": statuses,
                        }
                    )
                return out
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def _count_leading(values: list[str], target: str) -> int:
    count = 0
    for value in values:
        if value == target:
            count += 1
        else:
            break
    return count


def recover_stale_runs(db_path: str | Path | None = None) -> int:
    """重启恢复：把上次进程留下的 ``running`` run 标记为 failed。

    返回被回收的 run 数。绝不能让一个半途中断的 run 继续被当作成功证据。
    """
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    cursor = conn.execute(
                        """
                        UPDATE intel_fetch_runs
                        SET status = ?, finished_at = ?, note = ?
                        WHERE status = ?
                        """,
                        (
                            RUN_STATUS_FAILED,
                            utc_now_iso(),
                            "interrupted_by_process_restart",
                            RUN_STATUS_RUNNING,
                        ),
                    )
                    return int(cursor.rowcount or 0)
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


# ---------------------------------------------------------------------------
# items / observations
# ---------------------------------------------------------------------------


def upsert_observation(
    run_id: str,
    source_id: str,
    item: dict[str, Any],
    *,
    observed_at: str,
    has_real_rank: bool = False,
    db_path: str | Path | None = None,
) -> tuple[int, bool]:
    """写入一次观测；返回 ``(item_id, is_new_item)``。

    去重键由调用方给出 ``item_key``（URL 归一化优先，回退标题归一化）。
    ``rank`` 仅当来源真正有排名时写入，否则强制为 None —— 禁止补 0 伪造 off-list。
    """
    path = Path(db_path) if db_path else get_default_db_path()
    rank = item.get("rank") if has_real_rank else None
    if rank is not None and not isinstance(rank, int):
        rank = None
    published_at = item.get("published_at")
    published_ts = int(item.get("published_ts") or 0)
    title = str(item.get("title") or "")
    summary = item.get("summary") or ""

    item_key = str(item.get("item_key") or "")
    # 热榜条目排名身份严格以 SOURCE + ITEM 绑定，杜绝跨平台 rank 污染
    if has_real_rank or source_id.startswith("hotlist-"):
        if not item_key.startswith(f"{source_id}:"):
            item_key = f"{source_id}:{item_key}"

    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    row = conn.execute(
                        "SELECT item_id, observation_count FROM intel_items WHERE item_key = ?",
                        (item_key,),
                    ).fetchone()
                    if row is None:
                        cursor = conn.execute(
                            """
                            INSERT INTO intel_items
                                (item_key, canonical_url, url, title, title_key, summary,
                                 source_id, hint, published_at, published_ts,
                                 first_seen_at, last_seen_at, observation_count, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                            """,
                            (
                                item_key,
                                item.get("canonical_url") or item.get("url") or "",
                                item.get("url") or item.get("canonical_url") or "",
                                title,
                                item["title_key"],
                                summary,
                                source_id,
                                item.get("hint") or "",
                                published_at,
                                published_ts,
                                observed_at,
                                observed_at,
                                utc_now_iso(),
                            ),
                        )
                        item_id = int(cursor.lastrowid)
                        is_new = True
                    else:
                        item_id = int(row["item_id"])
                        is_new = False
                        conn.execute(
                            """
                            UPDATE intel_items
                            SET last_seen_at = ?,
                                observation_count = observation_count + 1,
                                published_at = COALESCE(?, published_at),
                                published_ts = CASE WHEN published_ts = 0 THEN ? ELSE published_ts END,
                                summary = CASE WHEN (summary IS NULL OR summary = '') AND ? != ''
                                               THEN ? ELSE summary END
                            WHERE item_id = ?
                            """,
                            (
                                observed_at,
                                published_at,
                                published_ts,
                                summary,
                                summary,
                                item_id,
                            ),
                        )

                    conn.execute(
                        """
                        INSERT INTO intel_observations
                            (run_id, item_id, source_id, observed_at, rank, observed_title, published_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(run_id, source_id, item_id) DO UPDATE SET
                            observed_at = excluded.observed_at,
                            rank = excluded.rank,
                            observed_title = excluded.observed_title,
                            published_at = excluded.published_at
                        """,
                        (run_id, item_id, source_id, observed_at, rank, title, published_at),
                    )
                    return item_id, is_new
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def query_items(
    db_path: str | Path | None = None,
    *,
    hint: str | None = None,
    source_id: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    search: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
    order_by: str = "last_seen",
) -> tuple[list[dict[str, Any]], int]:
    """统一条目查询；返回 ``(rows, total)``。

    ``order_by`` 取值：``last_seen`` / ``first_seen`` / ``published``。
    ``published`` 排序时 ``published_ts = 0``（来源未声明时间）的行排在最后，
    不把「未知发布时间」混进「最新发布」。
    """
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    clauses: list[str] = []
    args: list[Any] = []
    if hint:
        clauses.append("i.hint = ?")
        args.append(hint)
    if source_id:
        observation_clauses = ["o.item_id = i.item_id", "o.source_id = ?"]
        observation_args: list[Any] = [source_id]
        if since:
            observation_clauses.append("o.observed_at >= ?")
            observation_args.append(since)
        if until:
            observation_clauses.append("o.observed_at <= ?")
            observation_args.append(until)
        clauses.append(
            "EXISTS (SELECT 1 FROM intel_observations o "
            f"WHERE {' AND '.join(observation_clauses)})"
        )
        args.extend(observation_args)
    if since and not source_id:
        clauses.append("i.last_seen_at >= ?")
        args.append(since)
    if until and not source_id:
        clauses.append("i.last_seen_at <= ?")
        args.append(until)
    for term in include or []:
        if term:
            clauses.append("(i.title LIKE ? OR i.summary LIKE ?)")
            args.extend([f"%{term}%", f"%{term}%"])
    for term in exclude or []:
        if term:
            clauses.append("(i.title NOT LIKE ? AND COALESCE(i.summary, '') NOT LIKE ?)")
            args.extend([f"%{term}%", f"%{term}%"])
    if search:
        clauses.append("(i.title LIKE ? OR i.summary LIKE ?)")
        args.extend([f"%{search}%", f"%{search}%"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    order_sql = {
        "first_seen": "i.first_seen_at DESC",
        "published": "(i.published_ts = 0) ASC, i.published_ts DESC",
    }.get(order_by, "i.last_seen_at DESC")

    with _LOCK:
        try:
            with _connect(path) as conn:
                total = int(
                    conn.execute(
                        f"SELECT COUNT(*) AS n FROM intel_items i{where}", tuple(args)
                    ).fetchone()["n"]
                )
                rows = conn.execute(
                    f"""
                    SELECT i.*, s.name AS source_name, s.source_type, s.has_real_rank,
                           (
                               SELECT o.rank
                               FROM intel_observations o
                               WHERE o.item_id = i.item_id AND o.rank IS NOT NULL
                               ORDER BY o.observed_at DESC, o.obs_id DESC
                               LIMIT 1
                           ) AS rank
                    FROM intel_items i
                    LEFT JOIN intel_sources s ON s.source_id = i.source_id
                    {where}
                    ORDER BY {order_sql}, i.item_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    tuple([*args, max(1, min(int(limit), 500)), max(0, int(offset))]),
                ).fetchall()
                return [_item_row(row) for row in rows], total
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def _item_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "item_id": row["item_id"],
        "item_key": row["item_key"],
        "title": row["title"],
        "title_key": row["title_key"],
        "summary": row["summary"],
        "url": row["url"],
        "canonical_url": row["canonical_url"],
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "source_type": row["source_type"],
        "hint": row["hint"],
        "published_at": row["published_at"],
        "published_ts": row["published_ts"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "observation_count": row["observation_count"],
        "created_at": row["created_at"],
        "has_real_rank": bool(row["has_real_rank"]) if row["has_real_rank"] is not None else False,
        # 仅暴露已有真实 observation；RSS 没有排名时保持 None。
        "rank": row["rank"] if "rank" in row.keys() else None,
    }


def get_item_rank_history(
    item_id: int,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """某条目的排名历史；只返回真实存在过的 rank（NULL 不入列）。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    """
                    SELECT observed_at, rank FROM intel_observations
                    WHERE item_id = ? AND rank IS NOT NULL
                    ORDER BY observed_at ASC
                    """,
                    (item_id,),
                ).fetchall()
                return [
                    {"observed_at": r["observed_at"], "rank": r["rank"]}
                    for r in rows
                ]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


# ---------------------------------------------------------------------------
# 实体目录与映射
# ---------------------------------------------------------------------------


def upsert_security_directory(
    rows: list[dict[str, str]],
    db_path: str | Path | None = None,
) -> int:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    now = utc_now_iso()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    for row in rows:
                        code = str(row.get("code") or "").strip()
                        name = str(row.get("name") or "").strip()
                        industry = str(row.get("industry") or "").strip() or None
                        if not code or not name:
                            continue
                        conn.execute(
                            """
                            INSERT INTO intel_security_directory (code, name, industry, updated_at)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(code) DO UPDATE SET
                                name = excluded.name,
                                industry = COALESCE(excluded.industry, intel_security_directory.industry),
                                updated_at = excluded.updated_at
                            """,
                            (code, name, industry, now),
                        )
                return int(
                    conn.execute("SELECT COUNT(*) AS n FROM intel_security_directory").fetchone()["n"]
                )
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_security_directory_size(db_path: str | Path | None = None) -> int:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                return int(
                    conn.execute("SELECT COUNT(*) AS n FROM intel_security_directory").fetchone()["n"]
                )
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_security_name(
    code: str,
    db_path: str | Path | None = None,
) -> str | None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    "SELECT name FROM intel_security_directory WHERE code = ?", (code,)
                ).fetchone()
                return row["name"] if row else None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_security_industry(
    code: str,
    db_path: str | Path | None = None,
) -> str | None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    "SELECT industry FROM intel_security_directory WHERE code = ?", (code,)
                ).fetchone()
                return row["industry"] if row and row["industry"] else None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def search_directory(
    query: str,
    db_path: str | Path | None = None,
    *,
    limit: int = 20,
) -> list[dict[str, str]]:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    """
                    SELECT code, name FROM intel_security_directory
                    WHERE code LIKE ? OR name LIKE ?
                    ORDER BY code LIMIT ?
                    """,
                    (f"{query}%", f"%{query}%", max(1, min(int(limit), 100))),
                ).fetchall()
                return [{"code": r["code"], "name": r["name"]} for r in rows]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def replace_entity_terms(
    security_code: str | None,
    terms: list[dict[str, str]],
    db_path: str | Path | None = None,
) -> int:
    """替换某证券（或全局，security_code=None）登记的全部实体词，返回写入条数。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    now = utc_now_iso()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    if security_code is None:
                        conn.execute(
                            "DELETE FROM intel_entity_terms WHERE security_code IS NULL"
                        )
                        conn.execute(
                            "DELETE FROM intel_item_entities WHERE security_code IS NULL"
                        )
                    else:
                        conn.execute(
                            "DELETE FROM intel_entity_terms WHERE security_code = ?",
                            (security_code,),
                        )
                        conn.execute(
                            "DELETE FROM intel_item_entities WHERE security_code = ?",
                            (security_code,),
                        )
                    count = 0
                    for term in terms:
                        value = str(term.get("term") or "").strip()
                        kind = term.get("term_kind")
                        if not value or kind not in TERM_KINDS:
                            continue
                        conn.execute(
                            """
                            INSERT INTO intel_entity_terms (term, term_kind, security_code, source_ref, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(term, term_kind, security_code) DO UPDATE SET
                                source_ref = excluded.source_ref, updated_at = excluded.updated_at
                            """,
                            (value, kind, security_code, term.get("source_ref") or "unknown", now),
                        )
                        count += 1
                return count
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def list_entity_terms(
    db_path: str | Path | None = None,
    *,
    security_code: str | None = None,
    term_kinds: tuple[str, ...] | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    clauses: list[str] = []
    args: list[Any] = []
    if security_code is not None:
        clauses.append("security_code = ?")
        args.append(security_code)
    if term_kinds:
        placeholders = ",".join("?" for _ in term_kinds)
        clauses.append(f"term_kind IN ({placeholders})")
        args.extend(term_kinds)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    f"SELECT * FROM intel_entity_terms{where} ORDER BY term_kind, term LIMIT ?",
                    tuple([*args, max(1, int(limit))]),
                ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def link_item_entities(
    item_id: int,
    matches: list[dict[str, Any]],
    db_path: str | Path | None = None,
) -> None:
    path = Path(db_path) if db_path else get_default_db_path()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    for match in matches:
                        conn.execute(
                            """
                            INSERT INTO intel_item_entities (item_id, term_kind, term, security_code, matched_in)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(item_id, term_kind, term, security_code) DO UPDATE SET
                                matched_in = CASE
                                    WHEN intel_item_entities.matched_in = 'title' THEN 'title'
                                    ELSE excluded.matched_in
                                END
                            """,
                            (
                                item_id,
                                match["term_kind"],
                                match["term"],
                                match.get("security_code"),
                                match.get("matched_in") or "title",
                            ),
                        )
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def query_items_by_security(
    code: str,
    db_path: str | Path | None = None,
    *,
    limit: int = 30,
    window_hours: int | None = None,
) -> list[dict[str, Any]]:
    """取映射到某证券代码的所有条目（按末见时间倒序）。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    clauses = ["e.security_code = ?"]
    args: list[Any] = [code]
    if window_hours:
        from datetime import timedelta

        since_dt = datetime.now(timezone.utc) - timedelta(hours=int(window_hours))
        clauses.append("i.last_seen_at >= ?")
        args.append(since_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    args.append(max(1, min(int(limit), 200)))
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT i.*, s.name AS source_name, s.source_type, s.has_real_rank
                    FROM intel_item_entities e
                    JOIN intel_items i ON i.item_id = e.item_id
                    LEFT JOIN intel_sources s ON s.source_id = i.source_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY i.last_seen_at DESC
                    LIMIT ?
                    """,
                    tuple(args),
                ).fetchall()
                return [_item_row(row) for row in rows]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_security_mention_stats(
    codes: list[str],
    db_path: str | Path | None = None,
    *,
    window_hours: int | None = None,
) -> dict[str, dict[str, Any]]:
    """批量统计每个代码的 mentions / source_count / first_seen / last_seen。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    if not codes:
        return {}
    placeholders = ",".join("?" for _ in codes)
    args: list[Any] = list(codes)
    window_clause = ""
    if window_hours:
        from datetime import timedelta

        since_dt = datetime.now(timezone.utc) - timedelta(hours=int(window_hours))
        window_clause = " AND o.observed_at >= ?"
        args.append(since_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    f"""
                    SELECT e.security_code AS code,
                           COUNT(DISTINCT i.item_id) AS mention_count,
                           COUNT(DISTINCT o.source_id) AS source_count,
                           MIN(i.first_seen_at) AS first_seen_at,
                           MAX(i.last_seen_at) AS last_seen_at
                    FROM intel_item_entities e
                    JOIN intel_items i ON i.item_id = e.item_id
                    JOIN intel_observations o ON o.item_id = i.item_id
                    WHERE e.security_code IN ({placeholders}){window_clause}
                    GROUP BY e.security_code
                    """,
                    tuple(args),
                ).fetchall()
                result: dict[str, dict[str, Any]] = {}
                for code in codes:
                    result[code] = {
                        "code": code,
                        "mention_count": 0,
                        "source_count": 0,
                        "first_seen_at": None,
                        "last_seen_at": None,
                    }
                for row in rows:
                    result[row["code"]] = {
                        "code": row["code"],
                        "mention_count": int(row["mention_count"] or 0),
                        "source_count": int(row["source_count"] or 0),
                        "first_seen_at": row["first_seen_at"],
                        "last_seen_at": row["last_seen_at"],
                    }
                return result
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def count_items(db_path: str | Path | None = None) -> int:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                return int(conn.execute("SELECT COUNT(*) AS n FROM intel_items").fetchone()["n"])
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_meta(key: str, db_path: str | Path | None = None) -> str | None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    "SELECT value FROM intel_meta WHERE key = ?", (key,)
                ).fetchone()
                return row["value"] if row else None
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def set_meta(key: str, value: str, db_path: str | Path | None = None) -> None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO intel_meta (key, value) VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        """,
                        (key, value),
                    )
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def export_state(db_path: str | Path | None = None) -> dict[str, Any]:
    """测试与诊断用：导出库内关键状态。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        with _connect(path) as conn:
            return {
                "sources": [dict(r) for r in conn.execute("SELECT * FROM intel_sources ORDER BY source_id")],
                "runs": [dict(r) for r in conn.execute("SELECT * FROM intel_fetch_runs ORDER BY started_at")],
                "source_runs": [dict(r) for r in conn.execute("SELECT * FROM intel_source_runs ORDER BY run_id, source_id")],
                "items": [dict(r) for r in conn.execute("SELECT * FROM intel_items ORDER BY item_id")],
                "observations": [dict(r) for r in conn.execute("SELECT * FROM intel_observations ORDER BY obs_id")],
                "directory": [dict(r) for r in conn.execute("SELECT * FROM intel_security_directory ORDER BY code")],
                "entity_terms": [dict(r) for r in conn.execute("SELECT * FROM intel_entity_terms ORDER BY term_kind, term")],
                "item_entities": [dict(r) for r in conn.execute("SELECT * FROM intel_item_entities ORDER BY item_id")],
            }


def to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# TREND-PARITY Wave 2：个人兴趣与关键词过滤持久化
# ---------------------------------------------------------------------------


def get_filter_profile(
    profile_id: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    "SELECT * FROM intel_filter_profiles WHERE profile_id = ?",
                    (profile_id,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "profile_id": row["profile_id"],
                    "name": row["name"],
                    "method": row["method"],
                    "interests_text": row["interests_text"],
                    "min_score": float(row["min_score"]),
                    "keyword_rules": json.loads(row["keyword_rules_json"] or "{}"),
                    "tags": json.loads(row["tags_json"] or "[]"),
                    "profile_fingerprint": row["profile_fingerprint"],
                    "reclassify_threshold": float(row["reclassify_threshold"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def upsert_filter_profile(
    profile_data: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    data = dict(profile_data or {})
    data.update(kwargs)
    profile_id = str(data.get("profile_id") or "default").strip()
    name = str(data.get("name") or "默认筛选偏好").strip()
    method = str(data.get("method") or "keyword").strip()
    interests_text = str(data.get("interests_text") or "").strip()
    min_score = float(data.get("min_score") if data.get("min_score") is not None else 0.7)
    min_score = max(0.0, min(1.0, min_score))
    reclassify_threshold = float(
        data.get("reclassify_threshold") if data.get("reclassify_threshold") is not None else 0.6
    )
    reclassify_threshold = max(0.0, min(1.0, reclassify_threshold))

    keyword_rules = data.get("keyword_rules") or {}
    keyword_rules_json = json.dumps(keyword_rules, ensure_ascii=False, sort_keys=True)
    tags = data.get("tags") or []
    tags_json = json.dumps(tags, ensure_ascii=False)
    profile_fingerprint = str(data.get("profile_fingerprint") or "").strip()

    now = utc_now_iso()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    existing = conn.execute(
                        "SELECT created_at FROM intel_filter_profiles WHERE profile_id = ?",
                        (profile_id,),
                    ).fetchone()
                    created_at = existing["created_at"] if existing else now
                    conn.execute(
                        """
                        INSERT INTO intel_filter_profiles (
                            profile_id, name, method, interests_text, min_score,
                            keyword_rules_json, tags_json, profile_fingerprint,
                            reclassify_threshold, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(profile_id) DO UPDATE SET
                            name = excluded.name,
                            method = excluded.method,
                            interests_text = excluded.interests_text,
                            min_score = excluded.min_score,
                            keyword_rules_json = excluded.keyword_rules_json,
                            tags_json = excluded.tags_json,
                            profile_fingerprint = excluded.profile_fingerprint,
                            reclassify_threshold = excluded.reclassify_threshold,
                            updated_at = excluded.updated_at
                        """,
                        (
                            profile_id,
                            name,
                            method,
                            interests_text,
                            min_score,
                            keyword_rules_json,
                            tags_json,
                            profile_fingerprint,
                            reclassify_threshold,
                            created_at,
                            now,
                        ),
                    )
                return {
                    "profile_id": profile_id,
                    "name": name,
                    "method": method,
                    "interests_text": interests_text,
                    "min_score": min_score,
                    "keyword_rules": keyword_rules,
                    "tags": tags,
                    "profile_fingerprint": profile_fingerprint,
                    "reclassify_threshold": reclassify_threshold,
                    "created_at": created_at,
                    "updated_at": now,
                }
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_item_classifications(
    profile_id: str,
    profile_fingerprint: str,
    item_ids: list[int] | None = None,
    min_score: float | None = None,
    tag: str | None = None,
    db_path: str | Path | None = None,
) -> dict[int, dict[str, Any]]:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    clauses = ["profile_id = ?", "profile_fingerprint = ?"]
    args: list[Any] = [profile_id, profile_fingerprint]
    if item_ids is not None:
        if not item_ids:
            return {}
        placeholders = ",".join("?" for _ in item_ids)
        clauses.append(f"item_id IN ({placeholders})")
        args.extend([int(i) for i in item_ids])
    if min_score is not None:
        clauses.append("relevance_score >= ?")
        args.append(float(min_score))
    if tag:
        clauses.append("primary_tag = ?")
        args.append(tag)

    where = " WHERE " + " AND ".join(clauses)
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    f"SELECT item_id, primary_tag, relevance_score, classified_at, provider_identity "
                    f"FROM intel_item_classifications{where}",
                    tuple(args),
                ).fetchall()
                out: dict[int, dict[str, Any]] = {}
                for r in rows:
                    out[int(r["item_id"])] = {
                        "primary_tag": r["primary_tag"],
                        "relevance_score": float(r["relevance_score"]),
                        "classified_at": r["classified_at"],
                        "provider_identity": r["provider_identity"],
                    }
                return out
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def save_item_classifications(
    classifications: list[dict[str, Any]],
    db_path: str | Path | None = None,
) -> int:
    if not classifications:
        return 0
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    now = utc_now_iso()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO intel_item_classifications (
                            item_id, profile_id, profile_fingerprint,
                            primary_tag, relevance_score, classified_at, provider_identity
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                int(c["item_id"]),
                                str(c["profile_id"]),
                                str(c["profile_fingerprint"]),
                                str(c["primary_tag"]),
                                float(c["relevance_score"]),
                                str(c.get("classified_at") or now),
                                c.get("provider_identity"),
                            )
                            for c in classifications
                        ],
                    )
                return len(classifications)
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def list_recent_items_for_filter(
    db_path: str | Path | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    """
                    SELECT item_id, title, summary, source_id, url, canonical_url,
                           first_seen_at, last_seen_at, published_at
                    FROM intel_items
                    ORDER BY last_seen_at DESC, item_id DESC
                    LIMIT ?
                    """,
                    (max(1, min(int(limit), 500)),),
                ).fetchall()
                return [
                    {
                        "item_id": int(r["item_id"]),
                        "title": r["title"],
                        "summary": r["summary"],
                        "source_id": r["source_id"],
                        "url": r["url"],
                        "canonical_url": r["canonical_url"],
                        "first_seen_at": r["first_seen_at"],
                        "last_seen_at": r["last_seen_at"],
                        "published_at": r["published_at"],
                    }
                    for r in rows
                ]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e

def record_item_analyses(
    analyses: list[dict[str, Any]],
    db_path: str | Path | None = None,
) -> int:
    """批量记录条目分析状态（CLASSIFIED / NOT_RELEVANT / ERROR）。"""
    if not analyses:
        return 0
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    now = utc_now_iso()
    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO intel_item_filter_analysis (
                            item_id, profile_id, profile_fingerprint,
                            analysis_state, analyzed_at, provider_identity, error_kind
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                int(a["item_id"]),
                                str(a["profile_id"]),
                                str(a["profile_fingerprint"]),
                                str(a["analysis_state"]),
                                str(a.get("analyzed_at") or now),
                                a.get("provider_identity"),
                                a.get("error_kind"),
                            )
                            for a in analyses
                        ],
                    )
                return len(analyses)
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def get_item_analyses(
    profile_id: str,
    profile_fingerprint: str,
    item_ids: list[int] | None = None,
    db_path: str | Path | None = None,
) -> dict[int, dict[str, Any]]:
    """获取指定 profile 与 fingerprint 下的条目分析状态字典。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    clauses = ["profile_id = ?", "profile_fingerprint = ?"]
    args: list[Any] = [profile_id, profile_fingerprint]
    if item_ids:
        placeholders = ",".join("?" for _ in item_ids)
        clauses.append(f"item_id IN ({placeholders})")
        args.extend(item_ids)

    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    f"""
                    SELECT item_id, profile_id, profile_fingerprint,
                           analysis_state, analyzed_at, provider_identity, error_kind
                    FROM intel_item_filter_analysis
                    WHERE {' AND '.join(clauses)}
                    """,
                    tuple(args),
                ).fetchall()
                return {
                    int(r["item_id"]): {
                        "item_id": int(r["item_id"]),
                        "profile_id": r["profile_id"],
                        "profile_fingerprint": r["profile_fingerprint"],
                        "analysis_state": r["analysis_state"],
                        "analyzed_at": r["analyzed_at"],
                        "provider_identity": r["provider_identity"],
                        "error_kind": r["error_kind"],
                    }
                    for r in rows
                }
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def carry_forward_analysis_and_classifications(
    profile_id: str,
    old_fingerprint: str,
    new_fingerprint: str,
    kept_tags: list[str],
    carry_forward_not_relevant: bool = False,
    carry_not_relevant: bool | None = None,
    db_path: str | Path | None = None,
) -> tuple[int, int]:
    if carry_not_relevant is not None:
        carry_forward_not_relevant = carry_not_relevant
    """增量继承：将仍有效保留标签下的分类结果与分析状态顺延到新 fingerprint。"""
    if not kept_tags and not carry_forward_not_relevant:
        return 0, 0
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    now = utc_now_iso()

    carried_cls = 0
    carried_ana = 0

    with _LOCK:
        try:
            with _connect(path) as conn:
                with conn:
                    # 1. 顺延保留标签的分类
                    if kept_tags:
                        placeholders = ",".join("?" for _ in kept_tags)
                        cur_cls = conn.execute(
                            f"""
                            INSERT OR REPLACE INTO intel_item_classifications (
                                item_id, profile_id, profile_fingerprint,
                                primary_tag, relevance_score, classified_at, provider_identity
                            )
                            SELECT item_id, profile_id, ?, primary_tag, relevance_score, ?, provider_identity
                            FROM intel_item_classifications
                            WHERE profile_id = ? AND profile_fingerprint = ? AND primary_tag IN ({placeholders})
                            """,
                            [new_fingerprint, now, profile_id, old_fingerprint, *kept_tags],
                        )
                        carried_cls = cur_cls.rowcount

                        # 顺延这些分类条目的 CLASSIFIED 分析状态
                        cur_ana = conn.execute(
                            f"""
                            INSERT OR REPLACE INTO intel_item_filter_analysis (
                                item_id, profile_id, profile_fingerprint,
                                analysis_state, analyzed_at, provider_identity, error_kind
                            )
                            SELECT c.item_id, c.profile_id, ?, 'CLASSIFIED', ?, c.provider_identity, NULL
                            FROM intel_item_classifications c
                            WHERE c.profile_id = ? AND c.profile_fingerprint = ? AND c.primary_tag IN ({placeholders})
                            """,
                            [new_fingerprint, now, profile_id, old_fingerprint, *kept_tags],
                        )
                        carried_ana += cur_ana.rowcount

                    # 2. 如果未新增任何标签（纯删减标签），历史 NOT_RELEVANT 仍然不相关，可安全继承
                    if carry_forward_not_relevant:
                        cur_nr = conn.execute(
                            """
                            INSERT OR REPLACE INTO intel_item_filter_analysis (
                                item_id, profile_id, profile_fingerprint,
                                analysis_state, analyzed_at, provider_identity, error_kind
                            )
                            SELECT item_id, profile_id, ?, 'NOT_RELEVANT', ?, provider_identity, error_kind
                            FROM intel_item_filter_analysis
                            WHERE profile_id = ? AND profile_fingerprint = ? AND analysis_state = 'NOT_RELEVANT'
                            """,
                            [new_fingerprint, now, profile_id, old_fingerprint],
                        )
                        carried_ana += cur_nr.rowcount

                return carried_cls, carried_ana
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e


def list_all_recent_items_with_sources(
    db_path: str | Path | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """获取最近条目（含热榜与 RSS 全源），附带来源元数据（source_name, source_type 等）。"""
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)
    with _LOCK:
        try:
            with _connect(path) as conn:
                rows = conn.execute(
                    """
                    SELECT i.item_id, i.title, i.summary, i.source_id, i.url, i.canonical_url,
                           i.hint, i.published_at, i.first_seen_at, i.last_seen_at, i.observation_count,
                           s.name AS source_name, s.source_type, s.has_real_rank, s.enabled AS source_enabled
                    FROM intel_items i
                    LEFT JOIN intel_sources s ON s.source_id = i.source_id
                    ORDER BY i.last_seen_at DESC, i.item_id DESC
                    LIMIT ?
                    """,
                    (max(1, min(int(limit), 500)),),
                ).fetchall()
                return [
                    {
                        "item_id": int(r["item_id"]),
                        "title": r["title"],
                        "summary": r["summary"],
                        "source_id": r["source_id"],
                        "url": r["url"],
                        "canonical_url": r["canonical_url"],
                        "hint": r["hint"],
                        "published_at": r["published_at"],
                        "first_seen_at": r["first_seen_at"],
                        "last_seen_at": r["last_seen_at"],
                        "observation_count": int(r["observation_count"] or 1),
                        "source_name": r["source_name"],
                        "source_type": r["source_type"],
                        "has_real_rank": bool(r["has_real_rank"]),
                        "source_enabled": bool(r["source_enabled"]),
                    }
                    for r in rows
                ]
        except sqlite3.DatabaseError as e:
            raise NativeIntelStoreError() from e
