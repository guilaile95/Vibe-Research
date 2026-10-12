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
STORED_SCHEMA_VERSION_V02 = "short-term-daily-facts-v0.2"
_STORED_SCHEMA_VERSIONS = frozenset({
    STORED_SCHEMA_VERSION,
    STORED_SCHEMA_VERSION_V02,
})
_TABLE = "fact_snapshots"
_LOCK = threading.Lock()
_MAX_RECENT_TRADE_DATES = 366
_WINDOWS_STAT_CTIME = os.name == "nt"

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
    if envelope.get("schema_version") not in _STORED_SCHEMA_VERSIONS:
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


def _validate_v02_envelope(envelope: Any) -> Dict[str, str]:
    """校验可存储的 v0.2 daily-facts envelope（仅生产写入使用）。"""
    key = _validate_envelope(envelope)
    if key["schema_version"] != STORED_SCHEMA_VERSION_V02:
        raise FactStoreInvalidEnvelopeError(
            "monotonic save requires short-term-daily-facts-v0.2")
    if envelope.get("session") != "final" or envelope.get("is_final") is not True:
        raise FactStoreInvalidEnvelopeError("only final v0.2 envelopes are writable")
    if envelope.get("status") not in ("normal", "partial"):
        raise FactStoreInvalidEnvelopeError(
            "only normal/partial v0.2 envelopes are writable")
    return key


def save_daily_facts_monotonic(
    envelope: dict,
    db_path: str | Path | None = None,
) -> Dict[str, Any]:
    """质量单调写入 v0.2 daily facts（原子事务，并发不倒退）。

    规则：
    - 无记录：插入（saved）；
    - 相同内容：deduped；
    - existing partial + new normal：upgraded；
    - existing normal + new partial：blocked（不覆盖）；
    - existing normal + new normal 不同内容：blocked（不静默覆盖）；
    - existing partial + new partial 不同内容：blocked（不覆盖）；
    - existing v0.1 同 key：blocked（schema conflict，不覆盖）；
    - unavailable / invalid / 非 final：不写。

    失败不删除旧记录；数据库损坏失败关闭（FactStoreCorruptedError）。
    """
    key = _validate_v02_envelope(envelope)
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
                    row = conn.execute(
                        f"""
                        SELECT schema_version, envelope_json, stored_at
                        FROM {_TABLE}
                        WHERE trade_date = ? AND session = ?
                        """,
                        (key["trade_date"], key["session"]),
                    ).fetchone()
                    if row is None:
                        conn.execute(
                            f"""
                            INSERT INTO {_TABLE}
                            (trade_date, session, schema_version, stored_at,
                             envelope_json)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (key["trade_date"], key["session"],
                             key["schema_version"], stored_at, envelope_json),
                        )
                        return {
                            "saved": True,
                            "deduped": False,
                            "upgraded": False,
                            "blocked": False,
                            "reason_code": None,
                            "snapshot": {
                                "trade_date": key["trade_date"],
                                "session": key["session"],
                                "schema_version": key["schema_version"],
                                "stored_at": stored_at,
                            },
                        }

                    existing_version = row["schema_version"]
                    existing_json = row["envelope_json"]
                    new_status = envelope.get("status")

                    def _blocked(reason: str) -> Dict[str, Any]:
                        return {
                            "saved": False,
                            "deduped": False,
                            "upgraded": False,
                            "blocked": True,
                            "reason_code": reason,
                            "snapshot": {
                                "trade_date": key["trade_date"],
                                "session": key["session"],
                                "schema_version": existing_version,
                                "stored_at": row["stored_at"],
                            },
                        }

                    if existing_version != STORED_SCHEMA_VERSION_V02:
                        return _blocked("SCHEMA_CONFLICT_V01")
                    if existing_json == envelope_json:
                        return {
                            "saved": False,
                            "deduped": True,
                            "upgraded": False,
                            "blocked": False,
                            "reason_code": "DEDUPED",
                            "snapshot": {
                                "trade_date": key["trade_date"],
                                "session": key["session"],
                                "schema_version": existing_version,
                                "stored_at": row["stored_at"],
                            },
                        }
                    try:
                        existing_envelope = json.loads(existing_json)
                    except json.JSONDecodeError as exc:
                        raise FactStoreCorruptedError() from exc
                    existing_status = existing_envelope.get("status")
                    if existing_status == "normal":
                        return _blocked("NORMAL_CONFLICT")
                    if existing_status == "partial" and new_status == "normal":
                        conn.execute(
                            f"""
                            UPDATE {_TABLE}
                            SET schema_version = ?, stored_at = ?,
                                envelope_json = ?
                            WHERE trade_date = ? AND session = ?
                            """,
                            (key["schema_version"], stored_at, envelope_json,
                             key["trade_date"], key["session"]),
                        )
                        return {
                            "saved": True,
                            "deduped": False,
                            "upgraded": True,
                            "blocked": False,
                            "reason_code": "UPGRADED",
                            "snapshot": {
                                "trade_date": key["trade_date"],
                                "session": key["session"],
                                "schema_version": key["schema_version"],
                                "stored_at": stored_at,
                            },
                        }
                    return _blocked("PARTIAL_CONFLICT")
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise FactStoreCorruptedError() from exc


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


def load_final_fact_record(
    trade_date: str, db_path: str | Path | None = None,
) -> Optional[Dict[str, Any]]:
    """Read envelope and persistence time from one row, without creating a DB.

    Research as-of consumers need ``stored_at`` as well as source timestamps:
    a later backfill cannot become evidence known at an earlier observation.
    This additive reader never collects, promotes, or repairs facts.
    """
    record = load_final_fact_records_readonly((trade_date,), db_path).get(trade_date)
    if record is None:
        return None
    # Preserve the existing public return shape.
    return {"envelope": record["envelope"], "stored_at": record["stored_at"]}


class FactStoreBusyError(FactStoreError):
    """A stable checkpointed image is not available without modifying the store."""


def _archive_stat_fingerprint(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, getattr(value, "st_birthtime_ns", None))


def _archive_descriptor_matches_path(path_identity, descriptor_identity):
    # CPython 3.12 Windows path stat keeps legacy ctime=birthtime, while fstat
    # reports ChangeTime. Compare common identities across APIs, then track each
    # API's complete fingerprint independently before/after and across both reads.
    # Older runtimes without birthtime retain the original strict comparison.
    if (_WINDOWS_STAT_CTIME and path_identity[5] is not None
            and descriptor_identity[5] is not None):
        return (descriptor_identity[:4] == path_identity[:4]
                and descriptor_identity[5] == path_identity[5])
    return descriptor_identity == path_identity


def load_final_fact_records_readonly(
    trade_dates: tuple[str, ...], db_path: str | Path | None = None,
) -> Dict[str, Any]:
    """Read a bounded pair from one frozen DB image without SQLite source access.

    SQLite mode=ro may create WAL/SHM files. Instead read stable source bytes,
    refuse pending WAL/rollback journals, and deserialize into private memory.
    A fully checkpointed WAL-mode image retains header read/write versions 2;
    only the private copy changes these two bytes to 1 to disable journal lookup.
    This is not a checkpoint, migration, or source edit. The source DB SHA remains
    the hash of the unmodified on-disk bytes, distinct from envelope SHA.
    """
    import hashlib
    import stat

    if not 1 <= len(trade_dates) <= 2 or len(set(trade_dates)) != len(trade_dates):
        raise FactStoreInvalidEnvelopeError()
    for day in trade_dates:
        if type(day) is not str or _TRADE_DATE_RE.fullmatch(day) is None:
            raise FactStoreInvalidEnvelopeError()
        try:
            date.fromisoformat(day)
        except ValueError:
            raise FactStoreInvalidEnvelopeError() from None
    path = resolve_db_path(db_path)
    try:
        # Reject symlinked roots as well as the DB and sidecars.
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise FactStoreCorruptedError()
        if not path.exists():
            return {}

        def fingerprint():
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise FactStoreCorruptedError()
            source = path.stat()
            if not stat.S_ISREG(source.st_mode) or not 100 <= source.st_size <= 64 * 1024 * 1024:
                raise FactStoreCorruptedError()
            for suffix in ("-wal", "-journal", "-shm"):
                sidecar = Path(str(path) + suffix)
                if sidecar.is_symlink():
                    raise FactStoreCorruptedError()
                if sidecar.exists() and (not sidecar.is_file() or (suffix != "-shm" and sidecar.stat().st_size)):
                    raise FactStoreBusyError()
            return _archive_stat_fingerprint(source)

        before = fingerprint()
        descriptor_baseline = None
        def read_bounded():
            nonlocal descriptor_baseline
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise FactStoreCorruptedError()
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                identity = _archive_stat_fingerprint(opened)
                if not stat.S_ISREG(opened.st_mode) or not _archive_descriptor_matches_path(before, identity):
                    raise FactStoreBusyError()
                if descriptor_baseline is None:
                    descriptor_baseline = identity
                elif identity != descriptor_baseline:
                    raise FactStoreBusyError()
                value = stream.read(64 * 1024 * 1024 + 1)
                after_read = os.fstat(stream.fileno())
                if not stat.S_ISREG(after_read.st_mode) or _archive_stat_fingerprint(after_read) != descriptor_baseline:
                    raise FactStoreBusyError()
            if len(value) != before[2] or fingerprint() != before:
                raise FactStoreBusyError()
            return value
        blob = read_bounded()
        # Both reads have the same size and no-follow defenses.
        if read_bounded() != blob or fingerprint() != before:
            raise FactStoreBusyError()
        if blob[:16] != b"SQLite format 3\x00" or blob[18:20] not in (b"\x01\x01", b"\x02\x02"):
            raise FactStoreCorruptedError()
        page_size = int.from_bytes(blob[16:18], "big")
        page_size = 65536 if page_size == 1 else page_size
        pages = int.from_bytes(blob[28:32], "big")
        if (page_size < 512 or page_size > 65536 or page_size & (page_size - 1)
                or len(blob) % page_size or pages < 1 or pages > len(blob) // page_size):
            raise FactStoreCorruptedError()
        original_sha = hashlib.sha256(blob).hexdigest()
        image = blob[:18] + b"\x01\x01" + blob[20:]
        conn = sqlite3.connect(":memory:")
        try:
            conn.deserialize(image)
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            if conn.execute("SELECT type FROM sqlite_schema WHERE name='fact_snapshots'").fetchall() != [("table",)]:
                raise FactStoreCorruptedError()
            if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise FactStoreCorruptedError()
            placeholders = ",".join("?" for _ in trade_dates)
            rows = conn.execute(
                f"SELECT trade_date,envelope_json,stored_at FROM fact_snapshots WHERE session='final' AND trade_date IN ({placeholders})",
                trade_dates,
            ).fetchall()
        finally:
            conn.close()
        result = {}
        def strict_object(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError("duplicate JSON key")
                obj[key] = value
            return obj
        for day, raw, stored_at in rows:
            if day in result:
                raise FactStoreCorruptedError()
            envelope = json.loads(raw, object_pairs_hook=strict_object)
            _validate_envelope(envelope)
            if envelope["trade_date"] != day or envelope["session"] != "final":
                raise FactStoreCorruptedError()
            result[day] = {"envelope": envelope, "stored_at": stored_at, "database_sha256": original_sha}
        if fingerprint() != before:
            raise FactStoreBusyError()
        return result
    except FactStoreError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise FactStoreCorruptedError() from exc
