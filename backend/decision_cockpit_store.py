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
- draft 永不是 current（``is_current=0``）；仅 ``freeze_plan`` 将 draft 提升为
  frozen + current，并在同一事务 supersede 旧 frozen。同日可多 draft、仅一个
  current frozen。
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
        raw_value_json TEXT,
        context_json TEXT,
        counter_evidence_json TEXT,
        data_status TEXT,
        rule_version TEXT,
        evidence_refs_json TEXT,
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


# 信号表扩展列（写路径幂等迁移；GET 只读绝不调用）
_SIGNAL_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("raw_value_json", "TEXT"),
    ("context_json", "TEXT"),
    ("counter_evidence_json", "TEXT"),
    ("data_status", "TEXT"),
    ("rule_version", "TEXT"),
    ("evidence_refs_json", "TEXT"),
)


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _migrate_signals_schema(conn: sqlite3.Connection) -> None:
    """写路径幂等补齐 decision_signals 扩展列。"""
    if not _table_exists(conn, "decision_signals"):
        return
    existing = _column_names(conn, "decision_signals")
    for col, col_type in _SIGNAL_EXTRA_COLUMNS:
        if col not in existing:
            conn.execute(
                f"ALTER TABLE decision_signals ADD COLUMN {col} {col_type}"
            )


def initialize_decision_tables(db_path: Any) -> None:
    """幂等建三张表与索引（写路径）。"""
    _ensure_parent_dir(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            for stmt in _DECISION_TABLES:
                conn.execute(stmt)
            _migrate_signals_schema(conn)
    finally:
        conn.close()


def _initialize_if_missing(db_path: Any) -> None:
    """写路径：文件不存在则建表；存在则幂等补列。GET 不得调用。"""
    if not _db_file_exists(db_path):
        initialize_decision_tables(db_path)
        return
    conn = _connect(db_path)
    try:
        with conn:
            if not _table_exists(conn, "tomorrow_plans"):
                for stmt in _DECISION_TABLES:
                    conn.execute(stmt)
            elif not _table_exists(conn, "decision_signals"):
                for stmt in _DECISION_TABLES:
                    conn.execute(stmt)
            _migrate_signals_schema(conn)
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
    evidence_refs: list[str] | None = None,
    raw_value: Any = None,
    context: dict | None = None,
    counter_evidence: list | None = None,
    data_status: str | None = None,
    rule_version: str | None = None,
) -> dict:
    """按 (plan_id, candidate_code, dimension, label) 唯一覆盖式更新信号。

    ``evidence_refs`` / ``evidence_paths`` 均指向真实 evidence_path
    （如 ``kline/{code}``）；优先使用 evidence_refs。
    """
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
    refs = list(evidence_refs if evidence_refs is not None else (evidence_paths or []))
    if not all(isinstance(p, str) and p for p in refs):
        raise ValueError("evidence_refs 必须是非空字符串列表")
    if data_status is not None and data_status not in (
        "normal", "partial", "unavailable", "unknown",
    ):
        raise ValueError("data_status 非法")
    evidence_json = _canonical_json(refs)
    raw_value_json = _canonical_json(raw_value) if raw_value is not None else None
    context_json = _canonical_json(context) if context is not None else None
    counter_json = (
        _canonical_json(counter_evidence) if counter_evidence is not None else None
    )
    computed_at = _now()

    _initialize_if_missing(db_path)
    conn = _connect(db_path)
    try:
        with conn:
            _migrate_signals_schema(conn)
            conn.execute(
                """
                INSERT INTO decision_signals
                    (plan_id, candidate_code, dimension, label, assessment,
                     confidence, evidence_paths_json, computed_at,
                     raw_value_json, context_json, counter_evidence_json,
                     data_status, rule_version, evidence_refs_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id, candidate_code, dimension, label)
                DO UPDATE SET
                    assessment = excluded.assessment,
                    confidence = excluded.confidence,
                    evidence_paths_json = excluded.evidence_paths_json,
                    computed_at = excluded.computed_at,
                    raw_value_json = excluded.raw_value_json,
                    context_json = excluded.context_json,
                    counter_evidence_json = excluded.counter_evidence_json,
                    data_status = excluded.data_status,
                    rule_version = excluded.rule_version,
                    evidence_refs_json = excluded.evidence_refs_json
                """,
                (
                    plan_id, candidate_code, dimension, label, assessment,
                    confidence, evidence_json, computed_at,
                    raw_value_json, context_json, counter_json,
                    data_status, rule_version, evidence_json,
                ),
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
        "evidence_paths": refs,
        "evidence_refs": refs,
        "raw_value": raw_value,
        "context": context,
        "counter_evidence": counter_evidence,
        "data_status": data_status,
        "rule_version": rule_version,
        "computed_at": computed_at,
    }


def _safe_json_load(text: Any, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return default


def get_signals_for_plan(db_path: Any, plan_id: str) -> list[dict]:
    """读取指定 plan_id 的全部信号（只读，不迁移 schema）。"""
    if not _db_file_exists(db_path):
        return []
    conn = _connect_readonly(db_path)
    try:
        if not _table_exists(conn, "decision_signals"):
            return []
        cols = _column_names(conn, "decision_signals")
        extra = [
            c for c, _ in _SIGNAL_EXTRA_COLUMNS if c in cols
        ]
        base = (
            "plan_id, candidate_code, dimension, label, assessment, "
            "confidence, evidence_paths_json, computed_at"
        )
        select = base + ((", " + ", ".join(extra)) if extra else "")
        rows = conn.execute(
            f"""
            SELECT {select}
            FROM decision_signals WHERE plan_id = ?
            ORDER BY candidate_code, dimension, label
            """,
            (plan_id,),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            paths = _safe_json_load(r["evidence_paths_json"], [])
            refs = paths
            if "evidence_refs_json" in cols and r["evidence_refs_json"]:
                refs = _safe_json_load(r["evidence_refs_json"], paths)
            item = {
                "plan_id": r["plan_id"],
                "candidate_code": r["candidate_code"],
                "dimension": r["dimension"],
                "label": r["label"],
                "assessment": r["assessment"],
                "confidence": r["confidence"],
                "evidence_paths": paths if isinstance(paths, list) else [],
                "evidence_refs": refs if isinstance(refs, list) else [],
                "computed_at": r["computed_at"],
            }
            if "raw_value_json" in cols:
                item["raw_value"] = _safe_json_load(r["raw_value_json"])
            if "context_json" in cols:
                item["context"] = _safe_json_load(r["context_json"])
            if "counter_evidence_json" in cols:
                item["counter_evidence"] = _safe_json_load(r["counter_evidence_json"], [])
            if "data_status" in cols:
                item["data_status"] = r["data_status"]
            if "rule_version" in cols:
                item["rule_version"] = r["rule_version"]
            out.append(item)
        return out
    finally:
        conn.close()


def evidence_exists(db_path: Any, evidence_path: str) -> bool:
    """只读：evidence_path 是否已有记录。"""
    if not _db_file_exists(db_path):
        return False
    conn = _connect_readonly(db_path)
    try:
        if not _table_exists(conn, "decision_evidence"):
            return False
        row = conn.execute(
            "SELECT 1 FROM decision_evidence WHERE evidence_path = ?",
            (evidence_path,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def count_plans(db_path: Any) -> int:
    """只读：tomorrow_plans 行数（E2E 状态接口用）。"""
    if not _db_file_exists(db_path):
        return 0
    conn = _connect_readonly(db_path)
    try:
        if not _table_exists(conn, "tomorrow_plans"):
            return 0
        return int(conn.execute("SELECT COUNT(*) FROM tomorrow_plans").fetchone()[0])
    finally:
        conn.close()


def count_signals(db_path: Any) -> int:
    """只读：decision_signals 行数（E2E 状态接口用）。"""
    if not _db_file_exists(db_path):
        return 0
    conn = _connect_readonly(db_path)
    try:
        if not _table_exists(conn, "decision_signals"):
            return 0
        return int(conn.execute("SELECT COUNT(*) FROM decision_signals").fetchone()[0])
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
    generated_at: str | None = None,
) -> dict:
    """新建一个 draft 版本的明日计划（同一 trade_date 下一个 version）。

    draft 永不是 current（``is_current=0``），因此：

    - 生成 draft 不会 supersede 同交易日已有的 frozen；
    - 同日允许存在多个 draft；
    - 只有 ``freeze_plan`` 才会把某个 draft 提升为 current frozen，并在同一事务
      内把旧 frozen 降为 superseded。
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
        with conn:
            ver_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM tomorrow_plans "
                "WHERE trade_date = ?",
                (trade_date,),
            ).fetchone()
            version = int(ver_row[0])
            cur = conn.execute(
                """
                INSERT INTO tomorrow_plans
                    (trade_date, version, is_current, status, generated_at,
                     input_fingerprint, payload_hash, payload_json, created_at,
                     updated_at)
                VALUES (?, ?, 0, 'draft', ?, ?, ?, ?, ?, ?)
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
        "is_current": 0,
        "status": "draft",
        "generated_at": generated_at,
        "input_fingerprint": input_fingerprint,
        "payload_hash": payload_hash,
    }


def freeze_plan(db_path: Any, plan_id: int, *, expected_version: int) -> dict:
    """冻结指定 draft：status draft → frozen，并设为该 trade_date 唯一 current。

    同一事务内：
    - 校验 plan 仍为 draft 且 version 匹配（乐观锁）；
    - 将该 trade_date 上既有 ``is_current=1`` 行置 0 且 status=superseded；
    - 将目标 draft 升为 frozen + is_current=1。

    因此同日可有多个 draft，但至多一个 current frozen；生成 draft 不会
    抢占已 frozen 的 current。
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
                "SELECT id, trade_date, version, status, is_current "
                "FROM tomorrow_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                raise TomorrowPlanConflictError("计划不存在")
            if int(row["version"]) != expected_version:
                raise TomorrowPlanConflictError("版本已变更，请刷新后重试")
            if row["status"] != "draft":
                raise TomorrowPlanConflictError(
                    f"仅 draft 可冻结，当前状态：{row['status']}"
                )
            trade_date = row["trade_date"]
            # 先让出 current（partial unique index 要求至多一个 is_current=1）
            conn.execute(
                """
                UPDATE tomorrow_plans
                   SET is_current = 0,
                       status = CASE WHEN status = 'frozen' THEN 'superseded'
                                     ELSE status END,
                       updated_at = ?
                 WHERE trade_date = ? AND is_current = 1 AND id != ?
                """,
                (now, trade_date, plan_id),
            )
            cur = conn.execute(
                """
                UPDATE tomorrow_plans
                   SET status = 'frozen', is_current = 1, updated_at = ?
                 WHERE id = ? AND version = ? AND status = 'draft'
                """,
                (now, plan_id, expected_version),
            )
            if cur.rowcount != 1:
                raise TomorrowPlanConflictError("冻结失败：状态已变更，请刷新后重试")
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
