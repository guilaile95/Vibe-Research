"""Performance attribution SQLite storage (P2-4B)."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

_DB_ENV = "VIBE_RESEARCH_PERFORMANCE_ATTRIBUTION_DB"

_SNAPSHOTS_TABLE = "attribution_snapshots"
_POSITIONS_TABLE = "attribution_positions"

_CREATE_SNAPSHOTS_SQL = """
CREATE TABLE IF NOT EXISTS attribution_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    total_realized_pnl REAL NOT NULL,
    total_unrealized_pnl REAL,
    total_fees REAL NOT NULL,
    total_cost_basis REAL NOT NULL,
    position_count INTEGER NOT NULL,
    payload_json TEXT NOT NULL
)
"""

_CREATE_POSITIONS_SQL = """
CREATE TABLE IF NOT EXISTS attribution_positions (
    position_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    closed_quantity INTEGER NOT NULL,
    realized_pnl REAL NOT NULL,
    remaining_quantity INTEGER NOT NULL,
    avg_cost REAL,
    cost_basis REAL NOT NULL,
    total_fees REAL NOT NULL,
    unrealized_pnl REAL,
    created_at TEXT NOT NULL
)
"""

_CREATE_INDEX_POSITIONS = (
    "CREATE INDEX IF NOT EXISTS idx_attr_positions_snapshot "
    "ON attribution_positions (snapshot_id)"
)
_CREATE_INDEX_SNAPSHOTS = (
    "CREATE INDEX IF NOT EXISTS idx_attr_snapshots_date "
    "ON attribution_snapshots (as_of_date)"
)

_INSERT_SNAPSHOT_SQL = """
INSERT INTO attribution_snapshots (
    snapshot_id, as_of_date, created_at,
    total_realized_pnl, total_unrealized_pnl, total_fees,
    total_cost_basis, position_count, payload_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_POSITION_SQL = """
INSERT INTO attribution_positions (
    position_id, snapshot_id, code, name, closed_quantity, realized_pnl,
    remaining_quantity, avg_cost, cost_basis, total_fees, unrealized_pnl, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_SNAPSHOT_BY_ID = "SELECT * FROM attribution_snapshots WHERE snapshot_id = ?"
_SELECT_POSITIONS_BY_SNAPSHOT = (
    "SELECT * FROM attribution_positions WHERE snapshot_id = ? "
    "ORDER BY realized_pnl DESC, code ASC"
)


class PerformanceAttributionError(RuntimeError):
    pass


class PerformanceAttributionCorruptedError(PerformanceAttributionError):
    MESSAGE = "收益归因数据损坏，已停止读写"

    def __init__(self):
        super().__init__(self.MESSAGE)


class PerformanceAttributionNotFoundError(PerformanceAttributionError, LookupError):
    pass


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    env_val = os.environ.get(_DB_ENV)
    if env_val and str(env_val).strip():
        return Path(str(env_val).strip())
    data_dir = os.environ.get("VR_DATA_DIR") or str(Path.home() / ".vibe-research")
    return Path(data_dir) / "performance_attribution.sqlite3"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(db_path)), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    uri = f"{path.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, timeout=30.0, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SNAPSHOTS_SQL)
    conn.execute(_CREATE_POSITIONS_SQL)
    conn.execute(_CREATE_INDEX_POSITIONS)
    conn.execute(_CREATE_INDEX_SNAPSHOTS)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def save_snapshot(
    db_path: str | Path,
    snapshot: dict[str, Any],
    positions: list[dict[str, Any]],
) -> None:
    """Persist one snapshot + its positions in a single transaction."""
    with _LOCK:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = None
        try:
            conn = _connect(path)
            _ensure_tables(conn)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                _INSERT_SNAPSHOT_SQL,
                (
                    snapshot["snapshot_id"],
                    snapshot["as_of_date"],
                    snapshot["created_at"],
                    snapshot["total_realized_pnl"],
                    snapshot.get("total_unrealized_pnl"),
                    snapshot["total_fees"],
                    snapshot["total_cost_basis"],
                    snapshot["position_count"],
                    snapshot["payload_json"],
                ),
            )
            for pos in positions:
                conn.execute(
                    _INSERT_POSITION_SQL,
                    (
                        pos["position_id"],
                        pos["snapshot_id"],
                        pos["code"],
                        pos["name"],
                        pos["closed_quantity"],
                        pos["realized_pnl"],
                        pos["remaining_quantity"],
                        pos.get("avg_cost"),
                        pos["cost_basis"],
                        pos["total_fees"],
                        pos.get("unrealized_pnl"),
                        pos["created_at"],
                    ),
                )
            conn.execute("COMMIT")
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
            if conn:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
            raise PerformanceAttributionCorruptedError() from exc
        finally:
            if conn:
                conn.close()


def get_snapshot(db_path: str | Path, snapshot_id: str) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        with _connect_readonly(path) as conn:
            if not _table_exists(conn, _SNAPSHOTS_TABLE):
                return None
            row = conn.execute(_SELECT_SNAPSHOT_BY_ID, (snapshot_id,)).fetchone()
            if row is None:
                return None
            positions: list[dict[str, Any]] = []
            if _table_exists(conn, _POSITIONS_TABLE):
                positions = [
                    _row_to_dict(r)
                    for r in conn.execute(
                        _SELECT_POSITIONS_BY_SNAPSHOT, (snapshot_id,)
                    ).fetchall()
                ]
            return {"snapshot": _row_to_dict(row), "positions": positions}
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise PerformanceAttributionCorruptedError() from exc


def list_snapshots(
    db_path: str | Path,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.is_file():
        return []
    try:
        with _connect_readonly(path) as conn:
            if not _table_exists(conn, _SNAPSHOTS_TABLE):
                return []
            sql = "SELECT * FROM attribution_snapshots"
            clauses: list[str] = []
            params: list[Any] = []
            if date_from is not None:
                clauses.append("as_of_date >= ?")
                params.append(date_from)
            if date_to is not None:
                clauses.append("as_of_date <= ?")
                params.append(date_to)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at DESC, snapshot_id DESC"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            if offset:
                sql += " OFFSET ?"
                params.append(offset)
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_dict(r) for r in rows]
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise PerformanceAttributionCorruptedError() from exc
