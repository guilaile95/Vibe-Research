"""投资逻辑与证据账本 SQLite 存储层（纯存储，不暴露 HTTP、不含业务逻辑）。

所有公开函数显式接收 db_path；不定义生产默认路径，避免 import 时写库。
使用标准库 sqlite3，无 ORM。不 import portfolio_advice_service、
portfolio_advice_policy、daily_review、chat 等现有模块。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = "evidence_thesis_ledger_v1"

_LOCK = threading.Lock()


class EvidenceLedgerCorruptedError(RuntimeError):
    """数据库损坏，已停止读写以避免覆盖。"""

    MESSAGE = "投资逻辑数据文件损坏，已停止读写以避免覆盖；请检查 evidence_thesis.db"

    def __init__(self):
        super().__init__(self.MESSAGE)


class EvidenceLedgerSchemaVersionError(Exception):
    """Schema version incompatible"""

    MESSAGE = "投资逻辑数据库版本不兼容，请升级客户端"

    def __init__(self):
        super().__init__(self.MESSAGE)


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_CREATE_SCHEMA_META = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_CREATE_EVIDENCE_RECORDS = """
CREATE TABLE IF NOT EXISTS evidence_records (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','theme')),
    subject_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('news','announcement','report','research_note','financial_filing','other')),
    claim TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_url TEXT,
    source_date TEXT,
    accessed_at TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('fact','inference','unknown')),
    confidence TEXT NOT NULL CHECK (confidence IN ('high','medium','low')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    deleted_at TEXT
)
"""

_CREATE_INVESTMENT_THESES = """
CREATE TABLE IF NOT EXISTS investment_theses (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','theme')),
    subject_id TEXT NOT NULL,
    market TEXT CHECK (market IN ('CN','HK','US','KR') OR market IS NULL),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','weakened','invalidated','archived')),
    core_claims TEXT NOT NULL,
    catalysts TEXT NOT NULL,
    risks TEXT NOT NULL,
    invalidation_conditions TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    current_revision INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_THESIS_REVISIONS = """
CREATE TABLE IF NOT EXISTS thesis_revisions (
    id TEXT PRIMARY KEY,
    thesis_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    change_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thesis_id) REFERENCES investment_theses(id),
    UNIQUE (thesis_id, revision_number)
)
"""

_CREATE_THESIS_EVIDENCE_LINKS = """
CREATE TABLE IF NOT EXISTS thesis_evidence_links (
    thesis_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    stance TEXT NOT NULL CHECK (stance IN ('support','oppose','neutral')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (thesis_id, evidence_id),
    FOREIGN KEY (thesis_id) REFERENCES investment_theses(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence_records(id)
)
"""

# 6 个额外索引（不含 thesis_evidence_links(thesis_id)，主键已覆盖前缀查询）
_IDX_EVIDENCE_SUBJECT = """
CREATE INDEX IF NOT EXISTS idx_evidence_subject
ON evidence_records(subject_type, subject_id) WHERE deleted = 0
"""
_IDX_EVIDENCE_CLASSIFICATION = """
CREATE INDEX IF NOT EXISTS idx_evidence_classification
ON evidence_records(classification) WHERE deleted = 0
"""
_IDX_THESIS_SUBJECT = """
CREATE INDEX IF NOT EXISTS idx_thesis_subject
ON investment_theses(subject_type, subject_id)
"""
_IDX_THESIS_STATUS = """
CREATE INDEX IF NOT EXISTS idx_thesis_status
ON investment_theses(status)
"""
_IDX_REVISIONS_THESIS = """
CREATE INDEX IF NOT EXISTS idx_revisions_thesis
ON thesis_revisions(thesis_id, revision_number)
"""
_IDX_LINKS_EVIDENCE = """
CREATE INDEX IF NOT EXISTS idx_links_evidence
ON thesis_evidence_links(evidence_id)
"""

_ALL_DDL = [
    _CREATE_SCHEMA_META,
    _CREATE_EVIDENCE_RECORDS,
    _CREATE_INVESTMENT_THESES,
    _CREATE_THESIS_REVISIONS,
    _CREATE_THESIS_EVIDENCE_LINKS,
    _IDX_EVIDENCE_SUBJECT,
    _IDX_EVIDENCE_CLASSIFICATION,
    _IDX_THESIS_SUBJECT,
    _IDX_THESIS_STATUS,
    _IDX_REVISIONS_THESIS,
    _IDX_LINKS_EVIDENCE,
]


# ---------------------------------------------------------------------------
# 时间工具
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    """UTC ISO 8601 微秒精度。"""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id() -> str:
    """32 字符十六进制 UUID v4。"""
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# 路径与连接
# ---------------------------------------------------------------------------

def _as_path(db_path: str | Path) -> str:
    if isinstance(db_path, Path):
        return str(db_path)
    if not isinstance(db_path, str):
        raise TypeError("db_path 必须是字符串或 Path")
    return db_path


def _ensure_parent_dir(db_path: str | Path) -> None:
    path = _as_path(db_path)
    if path == ":memory:":
        return
    parent = Path(path).parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _db_file_exists(db_path: str | Path) -> bool:
    try:
        return Path(_as_path(db_path)).is_file()
    except TypeError:
        return False


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """可写连接：每连接启用 foreign_keys + busy_timeout；初始化时设 WAL。"""
    path = _as_path(db_path)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _connect_wal_init(db_path: str | Path) -> sqlite3.Connection:
    """可写初始化连接：额外设置 journal_mode=WAL（持久化到数据库文件）。"""
    conn = _connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """只读连接：mode=ro；不修改 journal mode。文件不存在抛 FileNotFoundError。"""
    path = _as_path(db_path)
    if not Path(path).exists():
        raise FileNotFoundError(f"evidence_thesis db 不存在：{path}")
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, timeout=5, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Schema 初始化与版本管理
# ---------------------------------------------------------------------------

def _read_schema_version(conn: sqlite3.Connection) -> str | None:
    """读取 schema_meta 表中的 schema_version。"""
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return row["value"] if row else None


def _validate_and_prepare_schema(conn: sqlite3.Connection, is_write: bool) -> None:
    """统一 Schema 验证和准备入口。

    - 已存在 schema_meta 时先读版本，高于代码版本拒绝
    - 拒绝前不执行任何 DDL
    - 当前版本正常读写
    - 新建空数据库初始化为 v1
    - 非空数据库缺 schema_meta 时拒绝
    """
    # 检查是否已有 schema_meta 表
    has_schema_meta = _table_exists(conn, "schema_meta")

    if has_schema_meta:
        # 已有 schema_meta，先读版本再决定
        version = _read_schema_version(conn)
        if version is None:
            # schema_meta 表存在但无 schema_version 记录，视为损坏
            raise EvidenceLedgerCorruptedError()

        # 版本号比较：提取 v 后的数字
        def _extract_version_number(v: str) -> int:
            import re
            m = re.search(r'_v(\d+)$', v)
            return int(m.group(1)) if m else 0

        current_ver = _extract_version_number(SCHEMA_VERSION)
        db_ver = _extract_version_number(version)

        if db_ver > current_ver:
            # 数据库版本高于代码版本，拒绝打开
            raise EvidenceLedgerSchemaVersionError()
        elif db_ver < current_ver:
            # 数据库版本低于代码版本，需要迁移
            # 当前无旧版本迁移逻辑，明确拒绝
            raise EvidenceLedgerSchemaVersionError()
        # db_ver == current_ver: 正常继续
    else:
        # 没有 schema_meta 表
        # 检查是否是全新数据库（没有任何表）
        has_any_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' LIMIT 1"
        ).fetchone() is not None

        if has_any_table:
            # 非空数据库但没有 schema_meta，拒绝
            raise EvidenceLedgerCorruptedError()

        # 全新数据库，仅在写模式下执行 DDL
        if is_write:
            for ddl in _ALL_DDL:
                conn.execute(ddl)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )


def initialize_store(db_path: str | Path) -> None:
    """幂等初始化表、索引和 schema 版本。"""
    _ensure_parent_dir(db_path)
    conn = _connect_wal_init(db_path)
    try:
        with conn:
            _validate_and_prepare_schema(conn, is_write=True)
    finally:
        conn.close()


def integrity_check(db_path: str | Path) -> None:
    """执行 PRAGMA integrity_check；失败抛 EvidenceLedgerCorruptedError。"""
    if not _db_file_exists(db_path):
        return
    conn = _connect_readonly(db_path)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise EvidenceLedgerCorruptedError()
    except sqlite3.DatabaseError:
        raise EvidenceLedgerCorruptedError()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 备份（WAL 安全：使用 SQLite backup API）
# ---------------------------------------------------------------------------

def backup_database(db_path: str | Path) -> None:
    """使用 SQLite backup API 生成一致性备份；失败不回滚已提交业务写入。

    失败时清理临时文件，保留既有 .bak，并重新抛出异常供调用方记录日志。
    """
    path = _as_path(db_path)
    if path == ":memory:":
        return
    if not _db_file_exists(db_path):
        return
    bak_tmp = path + ".bak.tmp"
    bak_final = path + ".bak"
    try:
        if Path(bak_tmp).exists():
            Path(bak_tmp).unlink()
        src = _connect_readonly(db_path)
        dst = sqlite3.connect(bak_tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.replace(bak_tmp, bak_final)
    except Exception:
        # 清理临时文件，保留既有 .bak
        if Path(bak_tmp).exists():
            try:
                Path(bak_tmp).unlink()
            except OSError:
                pass
        # 重新抛出，供 write_transaction 记录安全日志
        raise


# ---------------------------------------------------------------------------
# 事务上下文管理器
# ---------------------------------------------------------------------------

class _Tx:
    """BEGIN IMMEDIATE 事务上下文；异常自动 ROLLBACK。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self._conn.rollback()
        else:
            self._conn.commit()


# ---------------------------------------------------------------------------
# 写操作辅助（带锁 + 损坏检测 + 备份）
# ---------------------------------------------------------------------------

def _open_for_write(db_path: str | Path) -> sqlite3.Connection:
    """打开可写连接：确保 schema 已初始化 + 损坏检测。"""
    _ensure_parent_dir(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            _validate_and_prepare_schema(conn, is_write=True)
        # 损坏检测
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            conn.close()
            raise EvidenceLedgerCorruptedError()
    except sqlite3.DatabaseError:
        conn.close()
        raise EvidenceLedgerCorruptedError()
    except (EvidenceLedgerSchemaVersionError, EvidenceLedgerCorruptedError):
        conn.close()
        raise
    return conn


def write_transaction(db_path: str | Path, fn) -> Any:
    """在写锁 + 事务内执行 fn(conn)；成功后触发一致性备份。

    fn 接收一个已开启 BEGIN IMMEDIATE 的 conn，返回业务结果。
    异常自动 ROLLBACK。备份失败不影响业务提交（仅记录安全日志）。
    连接在 finally 块中关闭，确保所有异常路径都正确释放资源。
    """
    with _LOCK:
        conn = _open_for_write(db_path)
        try:
            with _Tx(conn):
                result = fn(conn)
            # 事务提交成功后备份；失败不影响业务写入
            try:
                backup_database(db_path)
            except Exception as e:  # noqa: BLE001 — 备份失败不能影响业务
                _log_backup_failure(db_path, e)
            return result
        except (EvidenceLedgerCorruptedError, EvidenceLedgerSchemaVersionError):
            raise
        except sqlite3.DatabaseError:
            raise EvidenceLedgerCorruptedError()
        finally:
            conn.close()


def _log_backup_failure(db_path: str | Path, err: Exception) -> None:
    """记录备份失败（安全日志，不向调用方传播）。"""
    import logging
    logging.getLogger("evidence_thesis_store").warning(
        "evidence_thesis backup failed type=%s", type(err).__name__
    )


def read_transaction(db_path: str | Path, fn) -> Any:
    """只读执行 fn(conn)；文件/表缺失时由调用方处理。"""
    if not _db_file_exists(db_path):
        raise FileNotFoundError(f"evidence_thesis db 不存在：{db_path}")
    conn = _connect_readonly(db_path)
    try:
        _validate_and_prepare_schema(conn, is_write=False)
        return fn(conn)
    except (EvidenceLedgerCorruptedError, EvidenceLedgerSchemaVersionError):
        raise
    except sqlite3.DatabaseError:
        raise EvidenceLedgerCorruptedError()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 行转换
# ---------------------------------------------------------------------------

def _evidence_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "evidence_type": row["evidence_type"],
        "claim": row["claim"],
        "source_title": row["source_title"],
        "source_url": row["source_url"],
        "source_date": row["source_date"],
        "accessed_at": row["accessed_at"],
        "classification": row["classification"],
        "confidence": row["confidence"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted": int(row["deleted"]),
        "deleted_at": row["deleted_at"],
    }


def _thesis_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "market": row["market"],
        "title": row["title"],
        "summary": row["summary"],
        "status": row["status"],
        "core_claims": json.loads(row["core_claims"]),
        "catalysts": json.loads(row["catalysts"]),
        "risks": json.loads(row["risks"]),
        "invalidation_conditions": json.loads(row["invalidation_conditions"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "current_revision": int(row["current_revision"]),
    }


def _revision_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "thesis_id": row["thesis_id"],
        "revision_number": int(row["revision_number"]),
        "snapshot": json.loads(row["snapshot"]),
        "change_summary": row["change_summary"],
        "created_at": row["created_at"],
    }


def _link_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "thesis_id": row["thesis_id"],
        "evidence_id": row["evidence_id"],
        "stance": row["stance"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# EvidenceRecord CRUD 原语
# ---------------------------------------------------------------------------

def _insert_evidence(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """
        INSERT INTO evidence_records (
            id, subject_type, subject_id, evidence_type, claim,
            source_title, source_url, source_date, accessed_at,
            classification, confidence, created_at, updated_at, deleted, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
        """,
        (
            data["id"],
            data["subject_type"],
            data["subject_id"],
            data["evidence_type"],
            data["claim"],
            data["source_title"],
            data.get("source_url"),
            data.get("source_date"),
            data["accessed_at"],
            data["classification"],
            data["confidence"],
            data["created_at"],
            data["updated_at"],
        ),
    )


def _update_evidence(conn: sqlite3.Connection, evidence_id: str, data: dict) -> None:
    conn.execute(
        """
        UPDATE evidence_records SET
            evidence_type = ?, claim = ?, source_title = ?, source_url = ?,
            source_date = ?, accessed_at = ?, classification = ?, confidence = ?,
            updated_at = ?
        WHERE id = ? AND deleted = 0
        """,
        (
            data["evidence_type"],
            data["claim"],
            data["source_title"],
            data.get("source_url"),
            data.get("source_date"),
            data["accessed_at"],
            data["classification"],
            data["confidence"],
            data["updated_at"],
            evidence_id,
        ),
    )


def _soft_delete_evidence(conn: sqlite3.Connection, evidence_id: str, deleted_at: str) -> None:
    conn.execute(
        "UPDATE evidence_records SET deleted = 1, deleted_at = ? WHERE id = ? AND deleted = 0",
        (deleted_at, evidence_id),
    )


def _get_evidence_row(conn: sqlite3.Connection, evidence_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM evidence_records WHERE id = ?",
        (evidence_id,),
    ).fetchone()


def _list_evidence_rows(
    conn: sqlite3.Connection,
    subject_type: str | None = None,
    subject_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[sqlite3.Row]:
    where = "WHERE 1=1"
    params: list[Any] = []
    if not include_deleted:
        where += " AND deleted = 0"
    if subject_type is not None:
        where += " AND subject_type = ?"
        params.append(subject_type)
    if subject_id is not None:
        where += " AND subject_id = ?"
        params.append(subject_id)
    params.extend([limit, offset])
    return conn.execute(
        f"SELECT * FROM evidence_records {where} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()


def _count_evidence(
    conn: sqlite3.Connection,
    subject_type: str | None = None,
    subject_id: str | None = None,
    include_deleted: bool = False,
) -> int:
    where = "WHERE 1=1"
    params: list[Any] = []
    if not include_deleted:
        where += " AND deleted = 0"
    if subject_type is not None:
        where += " AND subject_type = ?"
        params.append(subject_type)
    if subject_id is not None:
        where += " AND subject_id = ?"
        params.append(subject_id)
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM evidence_records {where}", params
    ).fetchone()
    return int(row["c"])


# ---------------------------------------------------------------------------
# InvestmentThesis CRUD 原语
# ---------------------------------------------------------------------------

def _insert_thesis(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """
        INSERT INTO investment_theses (
            id, subject_type, subject_id, market, title, summary, status,
            core_claims, catalysts, risks, invalidation_conditions,
            created_at, updated_at, current_revision
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["id"],
            data["subject_type"],
            data["subject_id"],
            data.get("market"),
            data["title"],
            data["summary"],
            data["status"],
            json.dumps(data["core_claims"], ensure_ascii=False),
            json.dumps(data["catalysts"], ensure_ascii=False),
            json.dumps(data["risks"], ensure_ascii=False),
            json.dumps(data["invalidation_conditions"], ensure_ascii=False),
            data["created_at"],
            data["updated_at"],
            data["current_revision"],
        ),
    )


def _update_thesis_main(conn: sqlite3.Connection, thesis_id: str, data: dict) -> None:
    """更新 thesis 主表字段（不含 current_revision）。"""
    conn.execute(
        """
        UPDATE investment_theses SET
            title = ?, summary = ?, status = ?,
            core_claims = ?, catalysts = ?, risks = ?, invalidation_conditions = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            data["title"],
            data["summary"],
            data["status"],
            json.dumps(data["core_claims"], ensure_ascii=False),
            json.dumps(data["catalysts"], ensure_ascii=False),
            json.dumps(data["risks"], ensure_ascii=False),
            json.dumps(data["invalidation_conditions"], ensure_ascii=False),
            data["updated_at"],
            thesis_id,
        ),
    )


def _update_thesis_revision(conn: sqlite3.Connection, thesis_id: str, revision: int) -> None:
    conn.execute(
        "UPDATE investment_theses SET current_revision = ? WHERE id = ?",
        (revision, thesis_id),
    )


def _get_thesis_row(conn: sqlite3.Connection, thesis_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM investment_theses WHERE id = ?",
        (thesis_id,),
    ).fetchone()


def _list_thesis_rows(
    conn: sqlite3.Connection,
    subject_type: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    where = "WHERE 1=1"
    params: list[Any] = []
    if subject_type is not None:
        where += " AND subject_type = ?"
        params.append(subject_type)
    if subject_id is not None:
        where += " AND subject_id = ?"
        params.append(subject_id)
    if status is not None:
        where += " AND status = ?"
        params.append(status)
    params.extend([limit, offset])
    return conn.execute(
        f"SELECT * FROM investment_theses {where} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()


def _count_thesis(
    conn: sqlite3.Connection,
    subject_type: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
) -> int:
    where = "WHERE 1=1"
    params: list[Any] = []
    if subject_type is not None:
        where += " AND subject_type = ?"
        params.append(subject_type)
    if subject_id is not None:
        where += " AND subject_id = ?"
        params.append(subject_id)
    if status is not None:
        where += " AND status = ?"
        params.append(status)
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM investment_theses {where}", params
    ).fetchone()
    return int(row["c"])


# ---------------------------------------------------------------------------
# ThesisRevision 原语
# ---------------------------------------------------------------------------

def _insert_revision(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """
        INSERT INTO thesis_revisions (id, thesis_id, revision_number, snapshot, change_summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            data["id"],
            data["thesis_id"],
            data["revision_number"],
            json.dumps(data["snapshot"], ensure_ascii=False),
            data["change_summary"],
            data["created_at"],
        ),
    )


def _get_revision_row(conn: sqlite3.Connection, thesis_id: str, revision_number: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM thesis_revisions WHERE thesis_id = ? AND revision_number = ?",
        (thesis_id, revision_number),
    ).fetchone()


def _list_revision_rows(conn: sqlite3.Connection, thesis_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM thesis_revisions WHERE thesis_id = ? ORDER BY revision_number ASC",
        (thesis_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# ThesisEvidenceLink 原语
# ---------------------------------------------------------------------------

def _insert_link(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """
        INSERT INTO thesis_evidence_links (thesis_id, evidence_id, stance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            data["thesis_id"],
            data["evidence_id"],
            data["stance"],
            data["created_at"],
            data["updated_at"],
        ),
    )


def _update_link_stance(conn: sqlite3.Connection, thesis_id: str, evidence_id: str, stance: str, updated_at: str) -> None:
    conn.execute(
        "UPDATE thesis_evidence_links SET stance = ?, updated_at = ? WHERE thesis_id = ? AND evidence_id = ?",
        (stance, updated_at, thesis_id, evidence_id),
    )


def _delete_link(conn: sqlite3.Connection, thesis_id: str, evidence_id: str) -> None:
    conn.execute(
        "DELETE FROM thesis_evidence_links WHERE thesis_id = ? AND evidence_id = ?",
        (thesis_id, evidence_id),
    )


def _get_link_row(conn: sqlite3.Connection, thesis_id: str, evidence_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM thesis_evidence_links WHERE thesis_id = ? AND evidence_id = ?",
        (thesis_id, evidence_id),
    ).fetchone()


def _list_links_for_thesis(conn: sqlite3.Connection, thesis_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM thesis_evidence_links WHERE thesis_id = ? ORDER BY evidence_id",
        (thesis_id,),
    ).fetchall()


def _list_links_for_evidence(conn: sqlite3.Connection, evidence_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM thesis_evidence_links WHERE evidence_id = ?",
        (evidence_id,),
    ).fetchall()


def _list_thesis_ids_for_evidence(conn: sqlite3.Connection, evidence_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT thesis_id FROM thesis_evidence_links WHERE evidence_id = ?",
        (evidence_id,),
    ).fetchall()
    return [r["thesis_id"] for r in rows]


def _list_non_archived_thesis_ids_for_evidence(conn: sqlite3.Connection, evidence_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT t.id FROM thesis_evidence_links l
        JOIN investment_theses t ON t.id = l.thesis_id
        WHERE l.evidence_id = ? AND t.status != 'archived'
        """,
        (evidence_id,),
    ).fetchall()
    return [r["id"] for r in rows]
