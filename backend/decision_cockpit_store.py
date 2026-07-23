"""明日决策驾驶舱持久层：证据、信号、明日计划三张表。

存储位置跟随共享复盘 SQLite（review_history.resolve_review_db_path()），与每日复
盘同源、同只读连接约定。本模块只提供确定性 SQL/JSON，业务规则在
``decision_cockpit_service`` 与 ``decision_cockpit_signals``。

主要约束：
- 每个候选代码的证据按 ``evidence_path`` 唯一；同一路径再次观测只更新
  ``observed_at`` 与 ``payload_hash``（UPSERT）。
- 信号按 ``(plan_id, candidate_code, dimension, label)`` 唯一；覆盖式更新。
- 明日计划按 ``(trade_date, version)`` 唯一；每 ``trade_date`` 至多一个
  ``is_current=1``（partial unique index 强约束）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

BEIJING = timezone(timedelta(hours=8))

_SCHEMA_VERSION = "decision-cockpit.v1"

_DECISION_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS decision_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evidence_path TEXT NOT NULL UNIQUE,
        observed_at TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_decision_evidence_path
    ON decision_evidence(evidence_path)
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id TEXT NOT NULL,
        candidate_code TEXT NOT NULL,
        dimension TEXT NOT NULL,
        label TEXT NOT NULL,
        assessment TEXT NOT NULL,
        confidence REAL,
        evidence_paths_json TEXT NOT NULL,
        computed_at TEXT NOT NULL,
        UNIQUE (plan_id, candidate_code, dimension, label)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_decision_signals_plan
    ON decision_signals(plan_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS tomorrow_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date TEXT NOT NULL,
        version INTEGER NOT NULL,
        is_current INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL
            CHECK (status IN ('draft', 'frozen', 'superseded')),
        generated_at TEXT NOT NULL,
        input_fingerprint TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (trade_date, version)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_tomorrow_plans_current
    ON tomorrow_plans(trade_date, is_current) WHERE is_current = 1
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tomorrow_plans_trade_date
    ON tomorrow_plans(trade_date, version DESC)
    """,
)


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _as_path(db_path: Any) -> str:
    if isinstance(db_path, Path):
        return str(db_path)
    if not isinstance(db_path, str):
        raise TypeError("db_path 必须是字符串或 Path")
    return db_path


def _ensure_parent_dir(db_path: str) -> None:
    if db_path == ":memory:":
        return
    parent = Path(db_path).parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _connect(db_path: Any) -> sqlite3.Connection:
    conn = sqlite3.connect(_as_path(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _connect_readonly(db_path: Any) -> sqlite3.Connection:
    path = _as_path(db_path)
    if not Path(path).exists():
        raise FileNotFoundError(f"review db 不存在：{path}")
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


def _db_file_exists(db_path: Any) -> bool:
    try:
        return Path(_as_path(db_path)).is_file()
    except TypeError:
        return False


def _canonical_json(obj: Any) -> str:
    try:
        return json.dumps(
            obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as e:
        raise ValueError(f"对象无法序列化为 JSON：{e}") from e


def _payload_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def initialize_decision_tables(db_path: Any) -> None:
    """幂等建三张表与索引。"""
    _ensure_parent_dir(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            for stmt in _DECISION_TABLES:
                conn.execute(stmt)
    finally:
        conn.close()


def _initialize_if_missing(db_path: Any) -> None:
    """文件存在但表未建时补建；文件不存在时创建目录+表。"""
    if not _db_file_exists(db_path):
        initialize_decision_tables(db_path)
        return
    conn = _connect(db_path)
    try:
        if not _table_exists(conn, "tomorrow_plans"):
            with conn:
                for stmt in _DECISION_TABLES:
                    conn.execute(stmt)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 证据（decision_evidence）
# ---------------------------------------------------------------------------


def upsert_evidence(db_path: Any, evidence_path: str, payload: dict) -> dict:
    """按 evidence_path 幂等写入证据（同路径再次观测覆盖）。

    Returns ``{"id", "evidence_path", "observed_at", "payload_hash", "created"}``
    """
    if not isinstance(evidence_path, str) or not evidence_path.strip():
        raise ValueError("evidence_path 必须是非空字符串")
    if not isinstance(payload, dict):
        raise TypeError("evidence payload 必须是字典")
    observed_at = _now()
    payload_json = _canonical_json(payload)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    created_at = observed_at

    _initialize_if_missing(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            existing = conn.execute(
                "SELECT id FROM decision_evidence WHERE evidence_path = ?",
                (evidence_path,),
            ).fetchone()
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO decision_evidence
                        (evidence_path, observed_at, payload_hash, payload_json,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (evidence_path, observed_at, payload_hash, payload_json,
                     created_at, created_at),
                )
                return {
                    "id": int(cur.lastrowid),
                    "evidence_path": evidence_path,
                    "observed_at": observed_at,
                    "payload_hash": payload_hash,
                    "created": True,
                }
            cur = conn.execute(
                """
                UPDATE decision_evidence
                   SET observed_at = ?, payload_hash = ?, payload_json = ?,
                       updated_at = ?
                 WHERE evidence_path = ?
                """,
                (observed_at, payload_hash, payload_json, observed_at, evidence_path),
            )
            row = conn.execute(
                "SELECT id, created_at FROM decision_evidence WHERE evidence_path = ?",
                (evidence_path,),
            ).fetchone()
            return {
                "id": int(row["id"]),
                "evidence_path": evidence_path,
                "observed_at": observed_at,
                "payload_hash": payload_hash,
                "created": False,
                "created_at": row["created_at"],
            }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 信号（decision_signals）
# ---------------------------------------------------------------------------


def _validate_assessment(assessment: Any) -> str:
    if assessment not in ("strong", "medium", "weak", "unknown"):
        raise ValueError("assessment 必须是 strong/medium/weak/unknown")
    return assessment


def upsert_signal(
    db_path: Any,
    *,
    plan_id: str,
    candidate_code: str,
    dimension: str,
    label: str,
    assessment: str,
    confidence: float | None = None,
    evidence_paths: list[str] | None = None,
) -> dict:
    """按 (plan_id, candidate_code, dimension, label) 唯一覆盖式更新信号。"""
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise ValueError("plan_id 必须是非空字符串")
    if not isinstance(candidate_code, str) or len(candidate_code) != 6:
        raise ValueError("candidate_code 必须是 6 位字符串")
    if not isinstance(dimension, str) or not dimension.strip():
        raise ValueError("dimension 必须是非空字符串")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label 必须是非空字符串")
    assessment = _validate_assessment(assessment)
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("confidence 必须是数字或 None")
        if not (0.0 <= float(confidence) <= 1.0):
            raise ValueError("confidence 必须在 [0, 1] 区间")
        confidence = round(float(confidence), 4)
    paths = list(evidence_paths or [])
    if not all(isinstance(p, str) and p for p in paths):
        raise ValueError("evidence_paths 必须是非空字符串列表")
    evidence_json = _canonical_json(paths)
    computed_at = _now()

    _initialize_if_missing(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO decision_signals
                    (plan_id, candidate_code, dimension, label, assessment,
                     confidence, evidence_paths_json, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id, candidate_code, dimension, label)
                DO UPDATE SET
                    assessment = excluded.assessment,
                    confidence = excluded.confidence,
                    evidence_paths_json = excluded.evidence_paths_json,
                    computed_at = excluded.computed_at
                """,
                (plan_id, candidate_code, dimension, label, assessment,
                 confidence, evidence_json, computed_at),
            )
    finally:
        conn.close()
    return {
        "plan_id": plan_id,
        "candidate_code": candidate_code,
        "dimension": dimension,
        "label": label,
        "assessment": assessment,
        "confidence": confidence,
        "evidence_paths": paths,
        "computed_at": computed_at,
    }


def get_signals_for_plan(db_path: Any, plan_id: str) -> list[dict]:
    """读取指定 plan_id 的全部信号（只读）。"""
    if not _db_file_exists(db_path):
        return []
    conn = _connect_readonly(db_path)
    try:
        if not _table_exists(conn, "decision_signals"):
            return []
        rows = conn.execute(
            """
            SELECT plan_id, candidate_code, dimension, label, assessment,
                   confidence, evidence_paths_json, computed_at
            FROM decision_signals WHERE plan_id = ?
            ORDER BY candidate_code, dimension, label
            """,
            (plan_id,),
        ).fetchall()
        return [
            {
                "plan_id": r["plan_id"],
                "candidate_code": r["candidate_code"],
                "dimension": r["dimension"],
                "label": r["label"],
                "assessment": r["assessment"],
                "confidence": r["confidence"],
                "evidence_paths": json.loads(r["evidence_paths_json"]),
                "computed_at": r["computed_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 明日计划（tomorrow_plans）
# ---------------------------------------------------------------------------


class TomorrowPlanConflictError(ValueError):
    """版本/is_current 约束冲突或 expected_version 乐观锁未命中。"""


def _next_version(db_path: Any, trade_date: str) -> int:
    """该 trade_date 的下一个 version（只读查询；外层已持事务）。"""
    conn = _connect(db_path)
    try:
        if not _db_file_exists(db_path) or not _table_exists(conn, "tomorrow_plans"):
            return 1
        row = conn.execute(
            "SELECT MAX(version) AS v FROM tomorrow_plans WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        return (int(row["v"]) if row["v"] else 0) + 1
    finally:
        conn.close()


def create_plan(
    db_path: Any,
    *,
    trade_date: str,
    payload: dict,
    expected_version: int | None = None,
    generated_at: str | None = None,
) -> dict:
    """新建一个 draft 版本的明日计划（同一 trade_date 下一个 version）。

    - ``expected_version`` 乐观锁：若不为 None，必须等于当前最新版本号，
      否则抛 ``TomorrowPlanConflictError``（防并发写入产生两个 current）。
    - 新 plan ``is_current=1``；同 trade_date 旧 current 在同一事务内被置 0
      （由 partial unique index 双重保证至多一个 current）。
    """
    if not isinstance(payload, dict):
        raise TypeError("plan payload 必须是字典")
    if generated_at is None:
        generated_at = _now()
    input_fingerprint = _payload_hash(payload)
    payload_json = _canonical_json(payload)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    now = _now()

    _initialize_if_missing(db_path)
    conn = _connect(db_path)
    try:
        if expected_version is not None:
            cur = conn.execute(
                "SELECT MAX(version) AS v FROM tomorrow_plans WHERE trade_date = ?",
                (trade_date,),
            ).fetchone()
            current_v = int(cur["v"]) if cur["v"] else 0
            if current_v != expected_version:
                raise TomorrowPlanConflictError(
                    f"版本已变更：期望 {expected_version}，实际 {current_v}"
                )
        ver_row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM tomorrow_plans "
            "WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        version = int(ver_row["v"])

        with conn:
            # 先把该交易日所有 current 置 0，再写入新的 current=1
            conn.execute(
                "UPDATE tomorrow_plans SET is_current = 0, status = 'superseded', "
                "updated_at = ? WHERE trade_date = ? AND is_current = 1",
                (now, trade_date),
            )
            cur = conn.execute(
                """
                INSERT INTO tomorrow_plans
                    (trade_date, version, is_current, status, generated_at,
                     input_fingerprint, payload_hash, payload_json, created_at,
                     updated_at)
                VALUES (?, ?, 1, 'draft', ?, ?, ?, ?, ?, ?)
                """,
                (trade_date, version, generated_at, input_fingerprint,
                 payload_hash, payload_json, now, now),
            )
            plan_id = int(cur.lastrowid)
    finally:
        conn.close()
    return {
        "id": plan_id,
        "trade_date": trade_date,
        "version": version,
        "is_current": 1,
        "status": "draft",
        "generated_at": generated_at,
        "input_fingerprint": input_fingerprint,
        "payload_hash": payload_hash,
    }


def freeze_plan(db_path: Any, plan_id: int, *, expected_version: int) -> dict:
    """冻结指定计划：status='draft' → 'frozen'，仅当版本号未变。

    冻结后该版本仍 ``is_current=1``；新 create_plan 会把它 supersed为
    ``superseded``。
    """
    if not isinstance(plan_id, int) or isinstance(plan_id, bool) or plan_id < 1:
        raise ValueError("plan_id 必须是正整数")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise ValueError("expected_version 必须是整数")
    now = _now()
    if not _db_file_exists(db_path):
        raise TomorrowPlanConflictError("计划不存在")
    conn = _connect(db_path)
    try:
        if not _table_exists(conn, "tomorrow_plans"):
            raise TomorrowPlanConflictError("计划不存在")
        with conn:
            row = conn.execute(
                "SELECT id, version, status FROM tomorrow_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                raise TomorrowPlanConflictError("计划不存在")
            if int(row["version"]) != expected_version:
                raise TomorrowPlanConflictError("版本已变更，请刷新后重试")
            if row["status"] != "draft":
                raise TomorrowPlanConflictError(f"仅 draft 可冻结，当前状态：{row['status']}")
            conn.execute(
                """
                UPDATE tomorrow_plans
                   SET status = 'frozen', updated_at = ?
                 WHERE id = ? AND version = ? AND status = 'draft'
                """,
                (now, plan_id, expected_version),
            )
    finally:
        conn.close()
    return get_plan(db_path, plan_id)


def get_plan(db_path: Any, plan_id: int) -> dict | None:
    """按主键读取单个计划（含 payload，只读）。"""
    if not isinstance(plan_id, int) or isinstance(plan_id, bool) or plan_id < 1:
        raise ValueError("plan_id 必须是正整数")
    if not _db_file_exists(db_path):
        return None
    conn = _connect_readonly(db_path)
    try:
        if not _table_exists(conn, "tomorrow_plans"):
            return None
        row = conn.execute(
            """
            SELECT id, trade_date, version, is_current, status, generated_at,
                   input_fingerprint, payload_hash, payload_json, created_at,
                   updated_at
            FROM tomorrow_plans WHERE id = ?
            """,
            (plan_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_plan(row)
    finally:
        conn.close()


def get_current_plan(db_path: Any, trade_date: str) -> dict | None:
    """读取指定 trade_date 的 current 计划（只读）。"""
    if not _db_file_exists(db_path):
        return None
    conn = _connect_readonly(db_path)
    try:
        if not _table_exists(conn, "tomorrow_plans"):
            return None
        row = conn.execute(
            """
            SELECT id, trade_date, version, is_current, status, generated_at,
                   input_fingerprint, payload_hash, payload_json, created_at,
                   updated_at
            FROM tomorrow_plans
            WHERE trade_date = ? AND is_current = 1
            """,
            (trade_date,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_plan(row)
    finally:
        conn.close()


def list_plans(
    db_path: Any,
    trade_date: str | None = None,
    *,
    limit: int = 30,
    offset: int = 0,
) -> list[dict]:
    """列计划元数据（不含 payload，只读）。"""
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 100):
        raise ValueError("limit 必须是 1..100")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset 必须 >= 0")
    if not _db_file_exists(db_path):
        return []
    conn = _connect_readonly(db_path)
    try:
        if not _table_exists(conn, "tomorrow_plans"):
            return []
        if trade_date is not None:
            rows = conn.execute(
                """
                SELECT id, trade_date, version, is_current, status, generated_at,
                       input_fingerprint, payload_hash, created_at, updated_at
                FROM tomorrow_plans WHERE trade_date = ?
                ORDER BY version DESC LIMIT ? OFFSET ?
                """,
                (trade_date, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, trade_date, version, is_current, status, generated_at,
                       input_fingerprint, payload_hash, created_at, updated_at
                FROM tomorrow_plans
                ORDER BY trade_date DESC, version DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [_row_to_meta(r) for r in rows]
    finally:
        conn.close()


def _row_to_meta(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "trade_date": row["trade_date"],
        "version": int(row["version"]),
        "is_current": int(row["is_current"]),
        "status": row["status"],
        "generated_at": row["generated_at"],
        "input_fingerprint": row["input_fingerprint"],
        "payload_hash": row["payload_hash"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_plan(row: sqlite3.Row) -> dict:
    d = _row_to_meta(row)
    d["payload"] = json.loads(row["payload_json"])
    return d
