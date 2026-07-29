"""Performance attribution computation service (P2-4B).

按加权平均成本法从交易流水计算逐股实现盈亏与持仓成本；
未实现盈亏仅在调用方显式提供现价时计算（不发起任何网络请求）。
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import performance_attribution_store as store
import trade_ledger_service as trade_svc

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

NO_PRICE_LIMITATION = "未提供现价，未实现盈亏不可用"
OVERSELL_LIMITATION = "卖出数量超过可用持仓，已按可用数量计算"
NO_POSITION_LIMITATION = "存在无持仓成本基准的卖出记录，该笔实现盈亏未计入"

_SELECT_TRADES = """
SELECT code, name, operation, actual_price, actual_quantity,
       fee, other_cost, executed_at, created_at
  FROM trade_records
 WHERE voided_at IS NULL
   AND execution_status != 'not_executed'
   AND actual_quantity > 0
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _validate_date(val: str | None, field: str) -> str | None:
    if val is None:
        return None
    if not isinstance(val, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
        raise ValueError(f"非法 {field}，格式须为 YYYY-MM-DD")
    return val


def _load_trades(
    db_path: Path,
    date_from: str | None,
    date_to: str | None,
) -> list[dict[str, Any]]:
    if not db_path.is_file():
        return []
    sql = _SELECT_TRADES
    params: list[Any] = []
    if date_from is not None:
        sql += " AND date(COALESCE(executed_at, created_at)) >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND date(COALESCE(executed_at, created_at)) <= ?"
        params.append(date_to)
    sql += " ORDER BY COALESCE(executed_at, created_at) ASC, created_at ASC"
    try:
        path = db_path.resolve()
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", timeout=30.0, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("trade_records",),
            ).fetchone()
            if table is None:
                return []
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        return []


def compute_attribution(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    price_map: Mapping[str, float] | None = None,
    trade_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compute deterministic per-stock realized/unrealized PnL from trade ledger."""
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")

    db_path = Path(trade_svc.resolve_db_path(trade_db_path))
    trades = _load_trades(db_path, date_from, date_to)

    states: dict[str, dict[str, Any]] = {}
    for row in trades:
        code = str(row.get("code") or "")
        if not code:
            continue
        st = states.get(code)
        if st is None:
            st = {
                "code": code,
                "name": row.get("name") or code,
                "remaining_qty": 0,
                "total_cost": 0.0,
                "closed_quantity": 0,
                "realized_pnl": 0.0,
                "total_fees": 0.0,
                "limitations": [],
            }
            states[code] = st
        if row.get("name"):
            st["name"] = row["name"]

        qty = int(row.get("actual_quantity") or 0)
        price = float(row.get("actual_price") or 0.0)
        fee = float(row.get("fee") or 0.0)
        other = float(row.get("other_cost") or 0.0)
        st["total_fees"] += fee + other

        operation = row.get("operation")
        if operation in ("buy", "add"):
            st["remaining_qty"] += qty
            st["total_cost"] += price * qty + fee + other
        elif operation in ("reduce", "sell"):
            remaining = st["remaining_qty"]
            if remaining <= 0:
                if NO_POSITION_LIMITATION not in st["limitations"]:
                    st["limitations"].append(NO_POSITION_LIMITATION)
                continue
            avg_cost = st["total_cost"] / remaining
            sell_qty = min(qty, remaining)
            if qty > remaining and OVERSELL_LIMITATION not in st["limitations"]:
                st["limitations"].append(OVERSELL_LIMITATION)
            cost_removed = avg_cost * sell_qty
            proceeds = price * sell_qty - fee - other
            st["realized_pnl"] += proceeds - cost_removed
            st["remaining_qty"] = remaining - sell_qty
            st["total_cost"] -= cost_removed
            st["closed_quantity"] += sell_qty

    prices: dict[str, float] = {}
    if price_map:
        for key, val in price_map.items():
            try:
                prices[str(key)] = float(val)
            except (TypeError, ValueError):
                continue

    positions: list[dict[str, Any]] = []
    for st in states.values():
        remaining = int(st["remaining_qty"])
        total_cost = float(st["total_cost"])
        if remaining <= 0:
            remaining = max(remaining, 0)
            total_cost = 0.0 if remaining == 0 else total_cost
        avg_cost = (total_cost / remaining) if remaining > 0 else None
        unrealized: float | None = None
        price = prices.get(st["code"])
        if price is not None and remaining > 0 and avg_cost is not None:
            unrealized = round((price - avg_cost) * remaining, 2)
        positions.append(
            {
                "code": st["code"],
                "name": st["name"],
                "closed_quantity": int(st["closed_quantity"]),
                "realized_pnl": round(float(st["realized_pnl"]), 2),
                "remaining_quantity": remaining,
                "avg_cost": round(avg_cost, 2) if avg_cost is not None else None,
                "cost_basis": round(total_cost, 2),
                "total_fees": round(float(st["total_fees"]), 2),
                "unrealized_pnl": unrealized,
                "data_limitations": list(st["limitations"]),
            }
        )

    positions.sort(key=lambda p: p["code"])
    positions.sort(key=lambda p: p["realized_pnl"], reverse=True)

    unrealized_values = [
        p["unrealized_pnl"] for p in positions if p["unrealized_pnl"] is not None
    ]
    totals = {
        "total_realized_pnl": round(sum(p["realized_pnl"] for p in positions), 2),
        "total_unrealized_pnl": (
            round(sum(unrealized_values), 2) if unrealized_values else None
        ),
        "total_fees": round(sum(p["total_fees"] for p in positions), 2),
        "total_cost_basis": round(sum(p["cost_basis"] for p in positions), 2),
        "position_count": len(positions),
    }

    limitations: list[str] = []
    if not prices:
        limitations.append(NO_PRICE_LIMITATION)
    elif any(
        p["unrealized_pnl"] is None and p["remaining_quantity"] > 0 for p in positions
    ):
        limitations.append("部分持仓缺少现价，未实现盈亏不完整")

    return {
        "as_of_date": _today(),
        "date_from": date_from,
        "date_to": date_to,
        "positions": positions,
        "totals": totals,
        "data_limitations": limitations,
    }


def save_attribution_snapshot(
    result: dict[str, Any],
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Freeze a computed attribution result into the snapshot store."""
    path = store.resolve_db_path(db_path)
    snapshot_id = f"attr_{uuid4().hex}"
    now = _utc_now()
    totals = result.get("totals") or {}

    snapshot = {
        "snapshot_id": snapshot_id,
        "as_of_date": result.get("as_of_date") or _today(),
        "created_at": now,
        "total_realized_pnl": float(totals.get("total_realized_pnl") or 0.0),
        "total_unrealized_pnl": totals.get("total_unrealized_pnl"),
        "total_fees": float(totals.get("total_fees") or 0.0),
        "total_cost_basis": float(totals.get("total_cost_basis") or 0.0),
        "position_count": int(totals.get("position_count") or 0),
        "payload_json": json.dumps(result, ensure_ascii=False),
    }

    positions = []
    for pos in result.get("positions") or []:
        positions.append(
            {
                "position_id": f"attrpos_{uuid4().hex}",
                "snapshot_id": snapshot_id,
                "code": pos["code"],
                "name": pos["name"],
                "closed_quantity": int(pos["closed_quantity"]),
                "realized_pnl": float(pos["realized_pnl"]),
                "remaining_quantity": int(pos["remaining_quantity"]),
                "avg_cost": pos.get("avg_cost"),
                "cost_basis": float(pos["cost_basis"]),
                "total_fees": float(pos["total_fees"]),
                "unrealized_pnl": pos.get("unrealized_pnl"),
                "created_at": now,
            }
        )

    store.save_snapshot(path, snapshot, positions)
    return snapshot


def get_attribution_snapshot(
    snapshot_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    path = store.resolve_db_path(db_path)
    record = store.get_snapshot(path, snapshot_id)
    if record is None:
        return None
    snapshot = dict(record["snapshot"])
    payload_raw = snapshot.pop("payload_json", None)
    payload: Any = None
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
        except (TypeError, ValueError):
            payload = None
    snapshot["payload"] = payload
    return {"snapshot": snapshot, "positions": record["positions"]}


def list_attribution_snapshots(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")
    path = store.resolve_db_path(db_path)
    rows = store.list_snapshots(
        path, date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item.pop("payload_json", None)
        out.append(item)
    return out
