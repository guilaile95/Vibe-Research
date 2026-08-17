"""Performance attribution computation service (P2-4B / P0-PA1).

按加权平均成本法从交易流水计算逐股实现盈亏与持仓成本；
未实现盈亏仅在调用方显式提供现价时计算（不发起任何网络请求）。

P0-PA1：计算结果携带精确输入来源证明（provenance）——

- 每个 position 暴露 ``input_trade_ids``：该证券实际处理的精确 Trade Ledger 行
- 结果顶层暴露 ``selected_trade_ids``：全部选中行的精确集（计算顺序）
- ``computation_fingerprint``：确定性 SHA-256，绑定算法版本 / 日期范围 /
  精确选中交易集 / 证券范围 / 价格输入；不含文件系统路径、环境、墙钟
- ``authority_version``：显式权威契约（下游消费者不得信任任意 source 字符串）

来源证明由计算权威自身生成，绝不允许调用方事后自报交易绑定。
"""
from __future__ import annotations

import hashlib
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
# Trade Ledger 权威 trade_id：32 位小写 hex，无前缀（trade_ledger_service 生成）
_TRADE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# 显式权威版本契约（P0-PA1）
AUTHORITY_VERSION = "performance_attribution.v2-provenance.v0.1"
_ALGORITHM = "weighted_avg_cost"

NO_PRICE_LIMITATION = "未提供现价，未实现盈亏不可用"
OVERSELL_LIMITATION = "卖出数量超过可用持仓，已按可用数量计算"
NO_POSITION_LIMITATION = "存在无持仓成本基准的卖出记录，该笔实现盈亏未计入"

_SELECT_TRADES = """
SELECT trade_id, code, name, operation, actual_price, actual_quantity,
       fee, other_cost, executed_at, created_at
  FROM trade_records
 WHERE voided_at IS NULL
   AND execution_status != 'not_executed'
   AND actual_quantity > 0
"""


class PerformanceAttributionProvenanceError(ValueError):
    """来源证明失败：选中行缺少/含非法 trade_id（fail closed）。

    来源与指标必须一致：绝不静默跳过 ID 却使用该行参与数值计算。
    """


def _deterministic_json(value: Any) -> str:
    """项目确定性 canonical JSON（stdlib）：排序键、紧凑、UTF-8、禁 NaN。

    不声明完整 RFC 8785 合规；用于 computation fingerprint 的稳定序列化。
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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


def _validate_trade_id(value: Any, row_index: int) -> str:
    """按 Trade Ledger 权威校验 trade_id；缺失/非法 → fail closed。"""
    if not isinstance(value, str) or not _TRADE_ID_RE.fullmatch(value):
        raise PerformanceAttributionProvenanceError(
            f"计算候选行 #{row_index} trade_id 缺失或非法"
            f"（Trade Ledger 权威要求 32 位小写 hex 无前缀）：{value!r}"
        )
    return value


def _load_trades(
    db_path: Path,
    date_from: str | None,
    date_to: str | None,
    trade_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """读取计算投影（精确输入行集）。

    合法空状态（既有产品语义，保留）：
    - 交易流水 DB 文件不存在
    - trade_records 表不存在

    一旦 trade_records 存在：任何读取/查询失败（缺列、SQLite 损坏、
    查询失败）→ PerformanceAttributionProvenanceError（fail closed）。

    "无法证明输入集" 绝不降级为 "已证明空输入集"。
    """
    if not db_path.is_file():
        return []
    requested_ids: set[str] | None = None
    if trade_ids is not None:
        requested_ids = set()
        if not trade_ids:
            return []
        for index, trade_id in enumerate(trade_ids):
            requested_ids.add(_validate_trade_id(trade_id, index))
        if len(requested_ids) != len(trade_ids):
            raise PerformanceAttributionProvenanceError(
                "精确交易集含重复 trade_id，拒绝计算"
            )

    sql = _SELECT_TRADES
    params: list[Any] = []
    if requested_ids is not None:
        placeholders = ",".join("?" for _ in requested_ids)
        sql += f" AND trade_id IN ({placeholders})"
        params.extend(sorted(requested_ids))
    if date_from is not None:
        sql += " AND date(COALESCE(executed_at, created_at)) >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND date(COALESCE(executed_at, created_at)) <= ?"
        params.append(date_to)
    # 全序确定性（P0-PA1-R1）：等时间戳由 trade_id 决胜（唯一账本身份）
    sql += (
        " ORDER BY COALESCE(executed_at, created_at) ASC,"
        " created_at ASC, trade_id ASC"
    )
    path = db_path.resolve()
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", timeout=30.0, uri=True)
    except sqlite3.DatabaseError as exc:
        raise PerformanceAttributionProvenanceError(
            f"无法打开交易流水库（只读）：{exc}"
        ) from exc
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("trade_records",),
        ).fetchone()
        if table is None:
            return []  # 既有产品语义：表缺失 = 有效空状态
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.DatabaseError as exc:
        raise PerformanceAttributionProvenanceError(
            f"交易流水读取失败，无法证明精确输入集：{exc}"
        ) from exc
    finally:
        conn.close()
    # 来源证明：选中行必须全部携带合法 trade_id（fail closed，不静默跳行）
    validated_rows = [
        {**row, "trade_id": _validate_trade_id(row.get("trade_id"), index)}
        for index, row in enumerate(rows)
    ]
    if requested_ids is not None and {
        row["trade_id"] for row in validated_rows
    } != requested_ids:
        raise PerformanceAttributionProvenanceError(
            "精确交易集无法由 Trade Ledger 完整证明"
        )
    return validated_rows


def _computation_fingerprint(
    *,
    date_from: str | None,
    date_to: str | None,
    selected_trade_ids: list[str],
    security_codes: list[str],
    price_inputs: Mapping[str, float],
) -> str:
    """确定性 SHA-256 计算身份：绑定算法/权威版本、日期范围、精确选中
    交易集、证券范围、价格输入。

    显式排除：文件系统路径、DB 路径、环境变量、墙钟创建时间。
    同 DB 快照 + 同参数 → 同 fingerprint。
    """
    payload = {
        "authority_version": AUTHORITY_VERSION,
        "algorithm": _ALGORITHM,
        "date_from": date_from,
        "date_to": date_to,
        "selected_trade_ids": selected_trade_ids,
        "security_codes": security_codes,
        "price_inputs": {code: price_inputs[code] for code in sorted(price_inputs)},
    }
    return hashlib.sha256(_deterministic_json(payload).encode("utf-8")).hexdigest()


def _compute_attribution_from_trades(
    *,
    trades: list[dict[str, Any]],
    date_from: str | None = None,
    date_to: str | None = None,
    price_map: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Compute the existing PA1 algorithm over an already proven exact row set."""
    selected_trade_ids = [row["trade_id"] for row in trades]

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
                # 精确输入来源：该证券按计算行顺序处理过的全部 trade_id
                "input_trade_ids": [],
            }
            states[code] = st
        st["input_trade_ids"].append(row["trade_id"])
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
                # 精确输入来源：该证券实际处理的行（计算顺序，含 oversell /
                # no-position 等仅记录 limitation 的行；不宣称超过算法支持的强度）
                "input_trade_ids": list(st["input_trade_ids"]),
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

    fingerprint = _computation_fingerprint(
        date_from=date_from,
        date_to=date_to,
        selected_trade_ids=selected_trade_ids,
        security_codes=sorted(p["code"] for p in positions),
        price_inputs=prices,
    )

    return {
        "as_of_date": _today(),
        "date_from": date_from,
        "date_to": date_to,
        "authority_version": AUTHORITY_VERSION,
        "selected_trade_ids": selected_trade_ids,
        "selected_trade_count": len(selected_trade_ids),
        "computation_fingerprint": fingerprint,
        "positions": positions,
        "totals": totals,
        "data_limitations": limitations,
    }


def compute_attribution(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    price_map: Mapping[str, float] | None = None,
    trade_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compute the legacy PA1 result over its normal ledger selection."""
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")
    db_path = Path(trade_svc.resolve_db_path(trade_db_path))
    trades = _load_trades(db_path, date_from, date_to)
    return _compute_attribution_from_trades(
        trades=trades,
        date_from=date_from,
        date_to=date_to,
        price_map=price_map,
    )


def compute_attribution_for_trade_ids(
    trade_ids: list[str] | tuple[str, ...],
    *,
    price_map: Mapping[str, float] | None = None,
    trade_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Reuse PA1 accounting over an exact, caller-proven Trade Ledger set.

    OL1 calls this only after TAR1 attribution and current Trade Ledger rows
    have been independently validated.  The helper refuses missing, voided,
    not-executed, or duplicate IDs instead of silently shrinking the set.
    """
    if not isinstance(trade_ids, (list, tuple)):
        raise PerformanceAttributionProvenanceError(
            "精确交易集必须是 list 或 tuple"
        )
    db_path = Path(trade_svc.resolve_db_path(trade_db_path))
    trades = _load_trades(db_path, None, None, list(trade_ids))
    return _compute_attribution_from_trades(
        trades=trades,
        date_from=None,
        date_to=None,
        price_map=price_map,
    )


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
