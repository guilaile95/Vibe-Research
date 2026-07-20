"""每日复盘历史快照 SQLite 存储（纯存储层，不自动保存、不暴露 HTTP）。

所有公开函数显式接收 db_path；不定义生产默认路径，避免 import 时写库。
使用标准库 sqlite3，无 ORM。
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BEIJING = timezone(timedelta(hours=8))

_ALLOWED_STATUS = frozenset({"normal", "partial", "unavailable"})
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS daily_review_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    data_cutoff TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('normal', 'partial', 'unavailable')),
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (trade_date, payload_hash)
)
"""

_CREATE_IDX_TRADE = """
CREATE INDEX IF NOT EXISTS idx_daily_review_snapshots_trade_date
ON daily_review_snapshots(trade_date)
"""

_CREATE_IDX_GEN = """
CREATE INDEX IF NOT EXISTS idx_daily_review_snapshots_generated_at
ON daily_review_snapshots(generated_at)
"""


def _now_beijing_str() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _as_path(db_path: str | Path) -> str:
    if isinstance(db_path, Path):
        return str(db_path)
    if not isinstance(db_path, str):
        raise TypeError("db_path 必须是字符串或Path")
    return db_path


def _ensure_parent_dir(db_path: str | Path) -> None:
    """文件型路径确保父目录存在；:memory: 跳过。"""
    path = _as_path(db_path)
    if path == ":memory:":
        return
    parent = Path(path).parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = _as_path(db_path)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """在当前连接上幂等建表/索引（:memory: 必须与读写同连接）。"""
    conn.execute(_CREATE_TABLE)
    conn.execute(_CREATE_IDX_TRADE)
    conn.execute(_CREATE_IDX_GEN)


def initialize_review_store(db_path: str | Path) -> None:
    """幂等初始化表与索引。:memory: 不创建目录。"""
    _ensure_parent_dir(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            _ensure_schema(conn)
    finally:
        conn.close()


def _validate_trade_date(trade_date: Any) -> str:
    if not isinstance(trade_date, str) or not trade_date:
        raise ValueError("trade_date 必须是非空字符串且格式为YYYY-MM-DD")
    if not _DATE_RE.match(trade_date):
        raise ValueError("trade_date 必须是非空字符串且格式为YYYY-MM-DD")
    try:
        y, m, d = map(int, trade_date.split("-"))
        date(y, m, d)
    except ValueError as e:
        raise ValueError(f"trade_date 不是有效日期：{trade_date}") from e
    return trade_date


def _validate_generated_at(generated_at: Any) -> str:
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("generated_at 必须是非空字符串且格式为YYYY-MM-DD HH:MM:SS")
    if not _DATETIME_RE.match(generated_at):
        raise ValueError("generated_at 必须是非空字符串且格式为YYYY-MM-DD HH:MM:SS")
    try:
        datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        raise ValueError(f"generated_at 不是有效时间：{generated_at}") from e
    return generated_at


def _validate_schema_version(schema_version: Any) -> str:
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise ValueError("schema_version 必须是非空字符串")
    return schema_version


def _validate_status(status: Any) -> str:
    if not isinstance(status, str) or status not in _ALLOWED_STATUS:
        raise ValueError("status 必须是 normal、partial 或 unavailable")
    return status


def _validate_data_cutoff(data_cutoff: Any) -> str | None:
    if data_cutoff is None:
        return None
    if not isinstance(data_cutoff, str):
        raise TypeError("data_cutoff 必须是字符串或None")
    return data_cutoff


def _canonical_json(obj: Any) -> str:
    try:
        return json.dumps(
            obj,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as e:
        raise ValueError(f"review 无法序列化为JSON：{e}") from e


def _payload_hash(review: dict) -> str:
    """对忽略 generated_at 的深拷贝计算 SHA-256。"""
    for_hash = copy.deepcopy(review)
    for_hash.pop("generated_at", None)
    blob = _canonical_json(for_hash).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _row_to_meta(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "trade_date": row["trade_date"],
        "schema_version": row["schema_version"],
        "generated_at": row["generated_at"],
        "data_cutoff": row["data_cutoff"],
        "status": row["status"],
        "payload_hash": row["payload_hash"],
        "created_at": row["created_at"],
    }


def _row_to_full(row: sqlite3.Row) -> dict:
    meta = _row_to_meta(row)
    meta["review"] = json.loads(row["payload_json"])
    return meta


def save_daily_review_snapshot(
    review: dict,
    db_path: str | Path,
) -> dict:
    """保存结构化每日复盘快照；同 trade_date+内容哈希去重。

    不修改传入的 review。仅 generated_at 变化不产生新记录。
    """
    if not isinstance(review, dict):
        raise TypeError("review 必须是字典")

    schema_version = _validate_schema_version(review.get("schema_version"))
    trade_date = _validate_trade_date(review.get("trade_date"))
    generated_at = _validate_generated_at(review.get("generated_at"))
    status = _validate_status(review.get("status"))
    data_cutoff = _validate_data_cutoff(review.get("data_cutoff"))

    # 序列化完整 review（含 generated_at）；哈希忽略 generated_at
    payload_json = _canonical_json(review)
    payload_hash = _payload_hash(review)
    created_at = _now_beijing_str()

    _ensure_parent_dir(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            _ensure_schema(conn)
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO daily_review_snapshots (
                    trade_date, schema_version, generated_at, data_cutoff,
                    status, payload_json, payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_date,
                    schema_version,
                    generated_at,
                    data_cutoff,
                    status,
                    payload_json,
                    payload_hash,
                    created_at,
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                snap_id = int(cur.lastrowid)
            else:
                row = conn.execute(
                    """
                    SELECT id, trade_date, schema_version, generated_at,
                           data_cutoff, status, payload_hash, created_at
                    FROM daily_review_snapshots
                    WHERE trade_date = ? AND payload_hash = ?
                    """,
                    (trade_date, payload_hash),
                ).fetchone()
                if row is None:
                    raise RuntimeError(
                        "去重冲突后未找到已有快照记录"
                    )
                return {
                    "id": int(row["id"]),
                    "inserted": False,
                    "trade_date": row["trade_date"],
                    "schema_version": row["schema_version"],
                    "generated_at": row["generated_at"],
                    "status": row["status"],
                    "payload_hash": row["payload_hash"],
                    "created_at": row["created_at"],
                }

            row = conn.execute(
                """
                SELECT id, trade_date, schema_version, generated_at,
                       data_cutoff, status, payload_hash, created_at
                FROM daily_review_snapshots WHERE id = ?
                """,
                (snap_id,),
            ).fetchone()
            return {
                "id": int(row["id"]),
                "inserted": True,
                "trade_date": row["trade_date"],
                "schema_version": row["schema_version"],
                "generated_at": row["generated_at"],
                "status": row["status"],
                "payload_hash": row["payload_hash"],
                "created_at": row["created_at"],
            }
    finally:
        conn.close()


def get_daily_review_snapshot(
    snapshot_id: int,
    db_path: str | Path,
) -> dict | None:
    """按主键读取完整快照；不存在返回 None。"""
    if not isinstance(snapshot_id, int) or isinstance(snapshot_id, bool):
        raise ValueError("snapshot_id 必须是正整数")
    if snapshot_id < 1:
        raise ValueError("snapshot_id 必须是正整数")

    _ensure_parent_dir(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT id, trade_date, schema_version, generated_at, data_cutoff,
                   status, payload_json, payload_hash, created_at
            FROM daily_review_snapshots WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_full(row)
    finally:
        conn.close()


def get_latest_daily_review_snapshot(
    db_path: str | Path,
    trade_date: str | None = None,
) -> dict | None:
    """读取最新快照；可按交易日过滤。无记录返回 None。"""
    _ensure_parent_dir(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            _ensure_schema(conn)
        if trade_date is not None:
            td = _validate_trade_date(trade_date)
            row = conn.execute(
                """
                SELECT id, trade_date, schema_version, generated_at, data_cutoff,
                       status, payload_json, payload_hash, created_at
                FROM daily_review_snapshots
                WHERE trade_date = ?
                ORDER BY generated_at DESC, id DESC
                LIMIT 1
                """,
                (td,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id, trade_date, schema_version, generated_at, data_cutoff,
                       status, payload_json, payload_hash, created_at
                FROM daily_review_snapshots
                ORDER BY trade_date DESC, generated_at DESC, id DESC
                LIMIT 1
                """,
            ).fetchone()
        if row is None:
            return None
        return _row_to_full(row)
    finally:
        conn.close()


def list_daily_review_snapshots(
    db_path: str | Path,
    trade_date: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> list[dict]:
    """列表元数据（不含完整 review）。"""
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 100):
        raise ValueError("limit 必须是 1 到 100 的整数")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset 必须是 >= 0 的整数")

    _ensure_parent_dir(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            _ensure_schema(conn)
        if trade_date is not None:
            td = _validate_trade_date(trade_date)
            rows = conn.execute(
                """
                SELECT id, trade_date, schema_version, generated_at, data_cutoff,
                       status, payload_hash, created_at
                FROM daily_review_snapshots
                WHERE trade_date = ?
                ORDER BY trade_date DESC, generated_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (td, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, trade_date, schema_version, generated_at, data_cutoff,
                       status, payload_hash, created_at
                FROM daily_review_snapshots
                ORDER BY trade_date DESC, generated_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [_row_to_meta(r) for r in rows]
    finally:
        conn.close()
