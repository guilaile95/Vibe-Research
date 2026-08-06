"""BK-11 Slice 3a 短线事实快照 SQLite 存储层 v0.1。

只持久化调用方提供的已批准 envelope（v0.1 仅接受
``short-term-daily-facts-v0.1`` 日事实组合 envelope），按
``(trade_date, session)`` 键控保存 / 加载 / 列示。

设计约束：

- 非法或伪造 envelope 一律拒绝，失败关闭，不部分写入
- 读操作走只读连接，写操作走写连接 + WAL
- 数据库路径：显式参数 > ``VR_DATA_DIR``/short_term_facts.sqlite3
  > ``~/.vibe-research/short_term_facts.sqlite3``
- 不触碰 Blocker 2/3/6；不计算任何指标；不接入生产入口
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "short-term-fact-store-v0.1"
STORED_SCHEMA_VERSION = "short-term-daily-facts-v0.1"
_TABLE = "fact_snapshots"
_LOCK = threading.Lock()
_MAX_RECENT_TRADE_DATES = 366

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_SESSIONS = frozenset({
    "pre_open",
    "call_auction",
    "morning_session",
    "midday_break",
    "afternoon_session",
    "close_pending",
    "final",
    "unavailable",
})
_ALLOWED_STATUSES = frozenset({
    "normal",
    "partial",
    "unavailable",
    "invalid",
})

_ENVELOPE_FIELDS = frozenset({
    "schema_version",
    "trade_date",
    "session",
    "is_final",
    "source_ids",
    "fetched_at",
    "snapshot_at",
    "status",
    "reason_codes",
    "warnings",
    "limitations",
    "source_schema_version",
    "source_status",
    "source_reason_codes",
    "sections",
})


class FactStoreError(RuntimeError):
    """存储层基础异常。"""


class FactStoreInvalidEnvelopeError(FactStoreError):
    """envelope 合同非法：拒绝保存，不写入。"""

    MESSAGE = "invalid fact envelope; rejected without write"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


class FactStoreNotFoundError(FactStoreError, LookupError):
    """请求的记录不存在。"""


class FactStoreCorruptedError(FactStoreError):
    """数据库文件或已存 JSON 损坏。"""

    MESSAGE = "short-term fact store corrupted"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


def resolve_db_path(explicit_path: str | Path | None = None) -> Path:
    """解析数据库路径（显式参数 > VR_DATA_DIR > 默认目录）。"""
    if explicit_path:
        return Path(explicit_path)
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / "short_term_facts.sqlite3"
    return Path.home() / ".vibe-research" / "short_term_facts.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _get_write_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn


def _get_read_connection(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        init_db(db_path)
    uri = f"file:{db_path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.execute("PRAGMA query_only = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.DatabaseError as exc:
        raise FactStoreCorruptedError() from exc


def init_db(db_path: str | Path | None = None) -> None:
    """初始化 schema（幂等）。"""
    path = resolve_db_path(db_path)
    with _LOCK:
        try:
            conn = _get_write_connection(path)
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_meta (
                            key TEXT PRIMARY KEY,
                            value TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {_TABLE} (
                            trade_date TEXT NOT NULL,
                            session TEXT NOT NULL,
                            schema_version TEXT NOT NULL,
                            stored_at TEXT NOT NULL,
                            envelope_json TEXT NOT NULL,
                            PRIMARY KEY (trade_date, session)
                        )
                        """
                    )
                    conn.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS idx_fact_snapshots_date
                        ON {_TABLE} (trade_date)
                        """
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO schema_meta (key, value, updated_at)
                        VALUES (?, ?, ?)
                        """,
                        ("schema_version", SCHEMA_VERSION, _utc_now()),
                    )
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise FactStoreCorruptedError() from exc


def _is_strict_json_value(value: Any) -> bool:
    """严格 JSON 树：只接受精确内建类型，拒绝 NaN/Infinity。"""
    if value is None:
        return True
    if type(value) is bool:
        return True
    if type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is str:
        return True
    if type(value) is list:
        return all(_is_strict_json_value(item) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _is_strict_json_value(val)
            for key, val in value.items()
        )
    return False


def _validate_envelope(envelope: Any) -> Dict[str, Any]:
    """校验可存储的 daily-facts envelope；非法抛出
    FactStoreInvalidEnvelopeError（不写入任何内容）。"""
    if type(envelope) is not dict:
        raise FactStoreInvalidEnvelopeError()
    if envelope.get("schema_version") != STORED_SCHEMA_VERSION:
        raise FactStoreInvalidEnvelopeError()
    if set(envelope.keys()) != _ENVELOPE_FIELDS:
        raise FactStoreInvalidEnvelopeError()
    trade_date = envelope.get("trade_date")
    if type(trade_date) is not str or _TRADE_DATE_RE.match(trade_date) is None:
        raise FactStoreInvalidEnvelopeError()
    try:
        date.fromisoformat(trade_date)
    except ValueError:
        raise FactStoreInvalidEnvelopeError() from None
    session = envelope.get("session")
    if type(session) is not str or session not in _ALLOWED_SESSIONS:
        raise FactStoreInvalidEnvelopeError()
    status = envelope.get("status")
    if type(status) is not str or status not in _ALLOWED_STATUSES:
        raise FactStoreInvalidEnvelopeError()
    if type(envelope.get("is_final")) is not bool:
        raise FactStoreInvalidEnvelopeError()
    source_ids = envelope.get("source_ids")
    if type(source_ids) is not list or any(
            type(item) is not str for item in source_ids):
        raise FactStoreInvalidEnvelopeError()
    sections = envelope.get("sections")
    if type(sections) is not dict or set(sections.keys()) != {
            "facts", "ladder", "gap"}:
        raise FactStoreInvalidEnvelopeError()
    if not _is_strict_json_value(envelope):
        raise FactStoreInvalidEnvelopeError()
    return {
        "trade_date": trade_date,
        "session": session,
        "schema_version": envelope["schema_version"],
    }


def save_daily_facts(
    envelope: dict,
    db_path: str | Path | None = None,
) -> Dict[str, str]:
    """保存日事实 envelope（upsert：同 trade_date+session 覆盖）。

    非法 envelope 抛出 FactStoreInvalidEnvelopeError，不写入。
    返回记录元数据 {trade_date, session, schema_version, stored_at}。
    """
    key = _validate_envelope(envelope)
    envelope_json = json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    stored_at = _utc_now()
    path = resolve_db_path(db_path)
    init_db(path)
    with _LOCK:
        try:
            conn = _get_write_connection(path)
            try:
                with conn:
                    conn.execute(
                        f"""
                        INSERT OR REPLACE INTO {_TABLE}
                        (trade_date, session, schema_version, stored_at,
                         envelope_json)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (key["trade_date"], key["session"],
                         key["schema_version"], stored_at, envelope_json),
                    )
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise FactStoreCorruptedError() from exc
    return {
        "trade_date": key["trade_date"],
        "session": key["session"],
        "schema_version": key["schema_version"],
        "stored_at": stored_at,
    }


def load_daily_facts(
    trade_date: str,
    session: str | None = None,
    db_path: str | Path | None = None,
) -> Optional[Dict[str, Any]]:
    """按 trade_date（+可选 session）加载 envelope。

    session 省略时返回该日期 stored_at 最新的记录；不存在返回 None。
    """
    path = resolve_db_path(db_path)
    try:
        conn = _get_read_connection(path)
        try:
            if session is None:
                row = conn.execute(
                    f"""
                    SELECT envelope_json FROM {_TABLE}
                    WHERE trade_date = ?
                    ORDER BY stored_at DESC, session DESC
                    LIMIT 1
                    """,
                    (trade_date,),
                ).fetchone()
            else:
                row = conn.execute(
                    f"""
                    SELECT envelope_json FROM {_TABLE}
                    WHERE trade_date = ? AND session = ?
                    """,
                    (trade_date, session),
                ).fetchone()
            if row is None:
                return None
            try:
                envelope = json.loads(row["envelope_json"])
            except json.JSONDecodeError as exc:
                raise FactStoreCorruptedError() from exc
            return envelope
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise FactStoreCorruptedError() from exc


def list_trade_dates(db_path: str | Path | None = None) -> List[str]:
    """列出全部已存 trade_date（升序）。"""
    path = resolve_db_path(db_path)
    try:
        conn = _get_read_connection(path)
        try:
            rows = conn.execute(
                f"""
                SELECT DISTINCT trade_date FROM {_TABLE}
                ORDER BY trade_date ASC
                """
            ).fetchall()
            return [row["trade_date"] for row in rows]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise FactStoreCorruptedError() from exc


def list_snapshots(db_path: str | Path | None = None) -> List[Dict[str, str]]:
    """列出全部快照元数据（trade_date/session/schema_version/stored_at）。"""
    path = resolve_db_path(db_path)
    try:
        conn = _get_read_connection(path)
        try:
            rows = conn.execute(
                f"""
                SELECT trade_date, session, schema_version, stored_at
                FROM {_TABLE}
                ORDER BY trade_date ASC, session ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise FactStoreCorruptedError() from exc


def list_recent_snapshots(
    limit_trade_dates: int,
    db_path: str | Path | None = None,
) -> List[Dict[str, str]]:
    """有界列出最近 ``limit_trade_dates`` 个交易日的全部快照元数据。

    - ``limit_trade_dates`` 必须是严格 int（拒绝 bool），且满足
      0 < limit_trade_dates <= _MAX_RECENT_TRADE_DATES。
    - SQL 层使用 LIMIT 只读取最近 N 个不同 trade_date；不先查询全量再切片。
    - 返回这些交易日的全部 session 元数据，按 trade_date、session 升序。
    - 数据库不存在时返回空列表，不创建数据库文件。
    - 数据库损坏仍失败关闭（FactStoreCorruptedError），不泄漏路径或
      SQLite 异常文本。
    """
    if isinstance(limit_trade_dates, bool) or type(limit_trade_dates) is not int:
        raise ValueError("limit_trade_dates must be a strict int")
    if not (0 < limit_trade_dates <= _MAX_RECENT_TRADE_DATES):
        raise ValueError(
            f"limit_trade_dates must be in 1..{_MAX_RECENT_TRADE_DATES}"
        )

    path = resolve_db_path(db_path)
    if not path.exists():
        return []

    try:
        conn = _get_read_connection(path)
        try:
            rows = conn.execute(
                f"""
                WITH recent_dates AS (
                    SELECT DISTINCT trade_date
                    FROM {_TABLE}
                    ORDER BY trade_date DESC
                    LIMIT ?
                )
                SELECT trade_date, session, schema_version, stored_at
                FROM {_TABLE}
                WHERE trade_date IN (SELECT trade_date FROM recent_dates)
                ORDER BY trade_date ASC, session ASC
                """,
                (limit_trade_dates,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise FactStoreCorruptedError() from exc
