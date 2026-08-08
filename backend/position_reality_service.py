"""P0-S1A position reality service: bootstrap / correction / derivation / reconciliation.

建立可审计事实链：ACCOUNT_OPENING → LEGACY_POSITION_OPENING → post-Vibe BUY/ADD/REDUCE/SELL
→ CORRECTION → 确定性推导持仓 → 与 portfolio.json 对账。

原则：
- PRE-VIBE 历史未知就保持 UNKNOWN；
- LEGACY_POSITION_OPENING != BUY；
- 不根据当前成本价反推历史买入；
- 历史事件不得静默改写，修正使用显式 CORRECTION 事件；
- 推导失败 fail closed，不产出部分持仓；
- 本轮 ledger-derived position 是 candidate canonical fact chain，不替换 portfolio.json。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import account_event_store
import portfolio
import trade_ledger_service
import trade_ledger_store

_CODE_RE = re.compile(r"^[0-9]{6}$")

_EVENT_ACCOUNT_OPENING = "ACCOUNT_OPENING"
_EVENT_LEGACY_OPENING = "LEGACY_POSITION_OPENING"
_EVENT_CORRECTION = "CORRECTION"
_ORIGIN_PRE_VIBE = "PRE_VIBE"
_PROVENANCE_MANUAL = "MANUAL"
_HISTORY_UNKNOWN = "UNKNOWN"

_CORRECTION_TRADE_KEYS = frozenset({"actual_quantity", "actual_price", "fee", "other_cost"})
_CORRECTION_EVENT_KEYS = frozenset({"shares", "cost_basis"})

_MAX_REASON_LEN = 500
_MAX_NOTE_LEN = 2000
_MAX_START_LEN = 64
_MAX_NAME_LEN = 64


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PositionValidationError(ValueError):
    pass


class BootstrapAlreadyExistsError(RuntimeError):
    def __init__(self):
        super().__init__("账本已初始化，禁止重复 bootstrap")


class LedgerNotEmptyError(RuntimeError):
    def __init__(self):
        super().__init__("账本已存在 post-Vibe 交易记录，禁止 bootstrap")


class PositionDerivationError(RuntimeError):
    pass


class CorrectionTargetNotFoundError(LookupError):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def resolve_db_path():
    """Account events 与 trade_records 共用 trade_ledger.sqlite3。"""
    return trade_ledger_service.resolve_db_path()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _require_str(data: dict[str, Any], field: str, *, max_len: int | None = None) -> str:
    if field not in data or data[field] is None:
        raise PositionValidationError(f"{field} 必填")
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        raise PositionValidationError(f"{field} 必须是非空字符串")
    text = value.strip()
    if max_len is not None and len(text) > max_len:
        raise PositionValidationError(f"{field} 超过最大长度 {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PositionValidationError(f"{field} 必须是字符串或 null")
    text = value.strip()
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        raise PositionValidationError(f"{field} 超过最大长度 {max_len}")
    return text


def _require_int(value: Any, field: str, *, min_value: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PositionValidationError(f"{field} 必须是整数")
    if value < min_value:
        raise PositionValidationError(f"{field} 必须大于等于 {min_value}")
    return value


def _optional_int(value: Any, field: str, *, min_value: int = 0) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PositionValidationError(f"{field} 必须是整数或 null")
    if value < min_value:
        raise PositionValidationError(f"{field} 必须大于等于 {min_value}")
    return value


def _require_number(value: Any, field: str, *, min_value: float = 0.0) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PositionValidationError(f"{field} 必须是数字")
    number = float(value)
    if number != number or number == float("inf") or number == float("-inf"):
        raise PositionValidationError(f"{field} 必须是有限数字")
    if number < min_value:
        raise PositionValidationError(f"{field} 必须大于等于 {min_value}")
    return number


def _optional_number(value: Any, field: str, *, min_value: float = 0.0) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PositionValidationError(f"{field} 必须是数字或 null")
    number = float(value)
    if number != number or number == float("inf") or number == float("-inf"):
        raise PositionValidationError(f"{field} 必须是有限数字")
    if number < min_value:
        raise PositionValidationError(f"{field} 必须大于等于 {min_value}")
    return number


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_BOOTSTRAP_ALLOWED = frozenset({"ledger_start_at", "opening_cash", "positions", "note"})
_POSITION_ALLOWED = frozenset({"code", "name", "shares", "cost_basis"})


def _validate_bootstrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate bootstrap payload; return normalized dict. Pure, no side effects."""
    if not isinstance(payload, dict):
        raise PositionValidationError("请求体必须是对象")

    unknown = set(payload.keys()) - _BOOTSTRAP_ALLOWED
    if unknown:
        raise PositionValidationError(f"未知字段: {', '.join(sorted(unknown))}")

    ledger_start_at = _require_str(payload, "ledger_start_at", max_len=_MAX_START_LEN)
    opening_cash = _optional_number(payload.get("opening_cash"), "opening_cash")
    note = _optional_str(payload.get("note"), "note", max_len=_MAX_NOTE_LEN)

    positions_raw = payload.get("positions")
    if not isinstance(positions_raw, list):
        raise PositionValidationError("positions 必须是数组")

    seen_codes: set[str] = set()
    positions: list[dict[str, Any]] = []
    for idx, item in enumerate(positions_raw):
        if not isinstance(item, dict):
            raise PositionValidationError(f"positions[{idx}] 必须是对象")
        unknown_pos = set(item.keys()) - _POSITION_ALLOWED
        if unknown_pos:
            raise PositionValidationError(
                f"positions[{idx}] 未知字段: {', '.join(sorted(unknown_pos))}"
            )
        code = _require_str(item, "code", max_len=6)
        if not _CODE_RE.fullmatch(code):
            raise PositionValidationError(f"positions[{idx}].code 必须是 6 位数字股票代码")
        if code in seen_codes:
            raise PositionValidationError(f"positions 存在重复股票代码: {code}")
        seen_codes.add(code)
        name = _optional_str(item.get("name"), f"positions[{idx}].name", max_len=_MAX_NAME_LEN)
        shares = _require_int(item.get("shares"), f"positions[{idx}].shares")
        cost_basis = _optional_number(
            item.get("cost_basis"), f"positions[{idx}].cost_basis"
        )
        positions.append({"code": code, "name": name, "shares": shares, "cost_basis": cost_basis})

    return {
        "ledger_start_at": ledger_start_at,
        "opening_cash": opening_cash,
        "note": note,
        "positions": positions,
    }


def _build_opening_event(validated: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": _new_id("aev"),
        "event_type": _EVENT_ACCOUNT_OPENING,
        "code": None,
        "name": None,
        "shares": None,
        "cost_basis": None,
        "opening_cash": validated["opening_cash"],
        "ledger_start_at": validated["ledger_start_at"],
        "origin": None,
        "acquired_before_vibe": None,
        "historical_trades": _HISTORY_UNKNOWN,
        "provenance": _PROVENANCE_MANUAL,
        "target_event_id": None,
        "target_event_type": None,
        "before_payload": None,
        "after_payload": None,
        "reason": None,
        "note": validated["note"],
        "created_at": _utc_now(),
    }


def _build_position_event(position: dict[str, Any], opening_event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": _new_id("aev"),
        "event_type": _EVENT_LEGACY_OPENING,
        "code": position["code"],
        "name": position["name"],
        "shares": position["shares"],
        "cost_basis": position["cost_basis"],
        "opening_cash": None,
        "ledger_start_at": None,
        "origin": _ORIGIN_PRE_VIBE,
        "acquired_before_vibe": 1,
        "historical_trades": _HISTORY_UNKNOWN,
        "provenance": _PROVENANCE_MANUAL,
        "target_event_id": None,
        "target_event_type": None,
        "before_payload": None,
        "after_payload": None,
        "reason": None,
        "note": None,
        "created_at": opening_event["created_at"],
    }


def bootstrap_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate bootstrap payload and build events without writing anything."""
    validated = _validate_bootstrap_payload(payload)
    opening = _build_opening_event(validated)
    positions = [_build_position_event(p, opening) for p in validated["positions"]]
    return {
        "preview": True,
        "validation": "ok",
        "opening": opening,
        "positions": positions,
    }


def _bootstrap_precheck(conn) -> None:
    """In-transaction idempotency guard: no existing account events and no post-Vibe trades."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM account_events WHERE voided_at IS NULL"
    ).fetchone()
    if row and int(row["n"]) > 0:
        raise BootstrapAlreadyExistsError()
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("trade_records",),
    ).fetchone()
    if table is not None:
        trade_row = conn.execute(
            "SELECT COUNT(*) AS n FROM trade_records WHERE voided_at IS NULL"
        ).fetchone()
        if trade_row and int(trade_row["n"]) > 0:
            raise LedgerNotEmptyError()


def bootstrap_commit(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, guard (atomic) and persist ACCOUNT_OPENING + LEGACY_POSITION_OPENING events."""
    validated = _validate_bootstrap_payload(payload)
    opening = _build_opening_event(validated)
    positions = [_build_position_event(p, opening) for p in validated["positions"]]
    db_path = resolve_db_path()
    account_event_store.atomic_bootstrap(
        db_path, opening, positions, precheck=_bootstrap_precheck
    )
    return {"status": "BOOTSTRAPPED", "opening": opening, "positions": positions}


# ---------------------------------------------------------------------------
# Correction
# ---------------------------------------------------------------------------

_CORRECTION_ALLOWED = frozenset(
    {"target_event_id", "target_event_type", "after_payload", "reason", "note"}
)


def create_correction(payload: dict[str, Any]) -> dict[str, Any]:
    """Append-only correction event; never silent-overwrites history."""
    if not isinstance(payload, dict):
        raise PositionValidationError("请求体必须是对象")

    unknown = set(payload.keys()) - _CORRECTION_ALLOWED
    if unknown:
        raise PositionValidationError(f"未知字段: {', '.join(sorted(unknown))}")

    target_event_id = _require_str(payload, "target_event_id")
    target_event_type = _require_str(payload, "target_event_type")
    if target_event_type not in ("trade", "account_event"):
        raise PositionValidationError("target_event_type 必须是 trade 或 account_event")

    after_payload = payload.get("after_payload")
    if not isinstance(after_payload, dict) or not after_payload:
        raise PositionValidationError("after_payload 必须是非空对象")

    if target_event_type == "trade":
        allowed = _CORRECTION_TRADE_KEYS
    else:
        allowed = _CORRECTION_EVENT_KEYS
    unknown_after = set(after_payload.keys()) - allowed
    if unknown_after:
        raise PositionValidationError(
            f"after_payload 含非法字段: {', '.join(sorted(unknown_after))}"
        )

    reason = _optional_str(payload.get("reason"), "reason", max_len=_MAX_REASON_LEN)
    note = _optional_str(payload.get("note"), "note", max_len=_MAX_NOTE_LEN)

    # Validate corrected values and snapshot current values
    db_path = resolve_db_path()
    if target_event_type == "trade":
        record = trade_ledger_store.get_record(db_path, target_event_id)
        if record is None:
            raise CorrectionTargetNotFoundError()
        if record.get("voided_at") is not None:
            raise PositionValidationError("目标交易已作废，禁止修正已作废记录")
        before: dict[str, Any] = {}
        for key in after_payload:
            if key == "actual_quantity":
                _require_int(after_payload[key], "actual_quantity", min_value=0)
                before[key] = record.get("actual_quantity")
            elif key == "actual_price":
                _require_number(after_payload[key], "actual_price")
                before[key] = record.get("actual_price")
            elif key in ("fee", "other_cost"):
                _require_number(after_payload[key], key)
                before[key] = record.get(key)
    else:
        event = account_event_store.get_event(db_path, target_event_id)
        if event is None:
            raise CorrectionTargetNotFoundError()
        if event.get("voided_at") is not None:
            raise PositionValidationError("目标事件已作废，禁止修正已作废记录")
        before = {}
        for key in after_payload:
            if key == "shares":
                _require_int(after_payload[key], "shares", min_value=0)
                before[key] = event.get("shares")
            elif key == "cost_basis":
                _optional_number(after_payload[key], "cost_basis")
                before[key] = event.get("cost_basis")

    event_record = {
        "event_id": _new_id("aev"),
        "event_type": _EVENT_CORRECTION,
        "code": None,
        "name": None,
        "shares": None,
        "cost_basis": None,
        "opening_cash": None,
        "ledger_start_at": None,
        "origin": None,
        "acquired_before_vibe": None,
        "historical_trades": None,
        "provenance": _PROVENANCE_MANUAL,
        "target_event_id": target_event_id,
        "target_event_type": target_event_type,
        "before_payload": json.dumps(before, ensure_ascii=False, sort_keys=True),
        "after_payload": json.dumps(after_payload, ensure_ascii=False, sort_keys=True),
        "reason": reason,
        "note": note,
        "created_at": _utc_now(),
    }
    account_event_store.insert_event(db_path, event_record)
    return {"status": "CORRECTION_RECORDED", "event": event_record}


# ---------------------------------------------------------------------------
# Position derivation
# ---------------------------------------------------------------------------

_LIMITATION_COST_UNKNOWN = "存在持仓成本基础未知（UNKNOWN），保持 UNKNOWN，未合成成本基础"


def _load_corrections(
    events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Map target_key -> correction events (created_at ASC)."""
    corrections: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        if ev["event_type"] != _EVENT_CORRECTION:
            continue
        key = f"{ev['target_event_type']}:{ev['target_event_id']}"
        corrections.setdefault(key, []).append(ev)
    return corrections


def _apply_corrections(
    events_by_key: dict[str, dict[str, Any]],
    corrections: dict[str, list[dict[str, Any]]],
) -> None:
    for key, corrs in corrections.items():
        target = events_by_key.get(key)
        if target is None:
            raise PositionDerivationError(f"correction 目标不存在: {key}")
        for corr in corrs:
            try:
                after = json.loads(corr["after_payload"])
            except (TypeError, ValueError) as exc:
                raise PositionDerivationError("correction after_payload 损坏") from exc
            if not isinstance(after, dict):
                raise PositionDerivationError("correction after_payload 损坏")
            for field, value in after.items():
                target[field] = value


def derive_positions() -> dict[str, Any]:
    """Deterministic position derivation from account events + trades + corrections."""
    db_path = resolve_db_path()

    events = account_event_store.list_events(db_path)
    trades = trade_ledger_store.list_records(db_path, include_voided=False, limit=None)

    openings = [e for e in events if e["event_type"] == _EVENT_ACCOUNT_OPENING]
    if len(openings) > 1:
        raise PositionDerivationError("存在多个 ACCOUNT_OPENING 事件，账本不一致")

    corrections = _load_corrections(events)

    events_by_key: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev["event_type"] == _EVENT_LEGACY_OPENING:
            events_by_key[f"account_event:{ev['event_id']}"] = dict(ev)
    for t in trades:
        if t["execution_status"] == "not_executed":
            continue
        if (t.get("actual_quantity") or 0) <= 0:
            continue
        events_by_key[f"trade:{t['trade_id']}"] = dict(t)

    _apply_corrections(events_by_key, corrections)

    # Build chronological sequence: legacy openings (ledger boundary) FIRST, then trades.
    # Opening 事件语义是"Vibe 接管日边界"，必须先于所有 post-Vibe 交易应用；
    # 不能只按 created_at/executed_at 排序（开仓事件时间可能晚于测试/历史交易时间）。
    sequence: list[tuple[int, str, str, dict[str, Any]]] = []
    for key, event in events_by_key.items():
        if key.startswith("account_event:"):
            ts = str(event.get("created_at") or "")
            rank = 0
        else:
            ts = str(event.get("executed_at") or event.get("created_at") or "")
            rank = 1
        sequence.append((rank, ts, key, event))
    sequence.sort(key=lambda item: (item[0], item[1], item[2]))

    states: dict[str, dict[str, Any]] = {}
    for rank, _ts, _key, event in sequence:
        if _key.startswith("account_event:"):
            code = event["code"]
            if not code:
                raise PositionDerivationError("legacy opening 事件缺少 code")
            st = states.get(code)
            if st is None:
                st = {
                    "code": code,
                    "name": event.get("name") or code,
                    "shares": 0,
                    "cost": None,
                    "cost_known": False,
                    "has_opening": False,
                    "origin": set(),
                }
                states[code] = st
            if st["has_opening"]:
                raise PositionDerivationError(f"同一股票存在多个期初持仓事件: {code}")
            shares = int(event.get("shares") or 0)
            cost_basis = event.get("cost_basis")
            if shares < 0:
                raise PositionDerivationError(f"期初持仓数量为负: {code}")
            st["has_opening"] = True
            st["shares"] = shares
            st["cost_known"] = cost_basis is not None
            # cost_basis 语义 = 每股平均成本（对齐 portfolio.json 的 cost）；总成本 = 每股 × 数量
            st["cost"] = float(cost_basis) * shares if st["cost_known"] else None
            st["origin"].add(_ORIGIN_PRE_VIBE)
            if event.get("name"):
                st["name"] = event["name"]
            continue

        code = event["code"]
        st = states.get(code)
        if st is None:
            st = {
                "code": code,
                "name": event.get("name") or code,
                "shares": 0,
                "cost": None,
                "cost_known": False,
                "has_opening": False,
                "origin": set(),
            }
            states[code] = st
        if event.get("name"):
            st["name"] = event["name"]

        operation = event["operation"]
        qty = int(event.get("actual_quantity") or 0)
        if qty < 0:
            raise PositionDerivationError(f"交易数量为负: {code}")
        if qty == 0:
            continue
        price = float(event.get("actual_price") or 0.0)
        fee = float(event.get("fee") or 0.0)
        other = float(event.get("other_cost") or 0.0)

        st["origin"].add("POST_VIBE")
        if operation in ("buy", "add"):
            st["shares"] += qty
            if st["cost_known"]:
                st["cost"] = st["cost"] + price * qty + fee + other
            # cost_known False → cost 保持 None（UNKNOWN stays UNKNOWN）
        elif operation in ("reduce", "sell"):
            if qty > st["shares"]:
                raise PositionDerivationError(
                    f"卖出数量超过可用持仓，账本推导失败: {code}"
                )
            if st["cost_known"] and st["shares"] > 0:
                avg = st["cost"] / st["shares"]
                st["cost"] = round(st["cost"] - avg * qty, 2)
            st["shares"] -= qty
        else:
            raise PositionDerivationError(f"非法 operation: {operation}")

    limitations: list[str] = []
    positions: list[dict[str, Any]] = []
    for code in sorted(states):
        st = states[code]
        shares = int(st["shares"])
        cost_known = st["cost_known"] and shares > 0
        if st["cost_known"] and not cost_known:
            # shares 已归零，成本随清仓归零
            pass
        cost_basis: float | None
        avg_cost: float | None
        if shares <= 0:
            status = "CLOSED"
            cost_basis = 0.0
            avg_cost = None
        else:
            status = "OPEN"
            if st["cost_known"]:
                cost_basis = round(float(st["cost"]), 2)
                avg_cost = round(float(st["cost"]) / shares, 2)
            else:
                cost_basis = None
                avg_cost = None
                if _LIMITATION_COST_UNKNOWN not in limitations:
                    limitations.append(_LIMITATION_COST_UNKNOWN)
        if len(st["origin"]) == 1:
            origin = next(iter(st["origin"]))
        elif st["origin"]:
            origin = "MIXED"
        else:
            origin = _ORIGIN_PRE_VIBE
        positions.append({
            "code": code,
            "name": st["name"],
            "shares": shares,
            "cost_basis": cost_basis,
            "avg_cost": avg_cost,
            "status": status,
            "origin": origin,
            "cost_known": st["cost_known"],
        })

    ledger_start: dict[str, Any] | None = None
    if openings:
        opening = openings[0]
        ledger_start = {
            "ledger_start_at": opening.get("ledger_start_at"),
            "opening_cash": opening.get("opening_cash"),
            "pre_vibe_history": _HISTORY_UNKNOWN,
            "bootstrapped_at": opening.get("created_at"),
        }

    return {
        "derivation_status": "OK",
        "ledger_start": ledger_start,
        "positions": positions,
        "data_limitations": limitations,
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile_positions() -> dict[str, Any]:
    """Read-only reconciliation: ledger-derived OPEN positions vs portfolio.json holdings."""
    derived = derive_positions()
    snapshot = portfolio.get_portfolio_holdings_snapshot()
    portfolio_holdings = snapshot.get("holdings") or []
    portfolio_map: dict[str, dict[str, Any]] = {}
    for h in portfolio_holdings:
        code = h.get("code")
        if code:
            portfolio_map[str(code)] = h

    ledger_open = {
        p["code"]: p for p in derived["positions"] if p["status"] == "OPEN"
    }

    items: list[dict[str, Any]] = []
    for code in sorted(set(ledger_open) | set(portfolio_map)):
        lp = ledger_open.get(code)
        ph = portfolio_map.get(code)
        if lp is None:
            items.append({
                "code": code,
                "status": "MISSING_IN_LEDGER",
                "ledger_shares": 0,
                "ledger_cost": None,
                "portfolio_shares": ph.get("shares"),
                "portfolio_cost": ph.get("cost"),
                "reason": "ledger 无对应持仓（或已清仓）",
            })
        elif ph is None:
            items.append({
                "code": code,
                "status": "MISSING_IN_PORTFOLIO",
                "ledger_shares": lp["shares"],
                "ledger_cost": lp["avg_cost"],
                "portfolio_shares": None,
                "portfolio_cost": None,
                "reason": "portfolio 无对应持仓",
            })
        else:
            ledger_shares = lp["shares"]
            portfolio_shares = ph.get("shares")
            ledger_avg = lp["avg_cost"]
            portfolio_cost = ph.get("cost")
            if round(float(ledger_shares), 2) != round(float(portfolio_shares or 0), 2):
                status = "MISMATCH"
                reason = "shares mismatch"
            elif not lp["cost_known"] or ledger_avg is None:
                status = "MISMATCH"
                reason = "ledger cost UNKNOWN"
            elif portfolio_cost is None or round(float(ledger_avg), 2) != round(float(portfolio_cost), 2):
                status = "MISMATCH"
                reason = "cost mismatch"
            else:
                status = "MATCH"
                reason = None
            items.append({
                "code": code,
                "status": status,
                "ledger_shares": ledger_shares,
                "ledger_cost": ledger_avg,
                "portfolio_shares": portfolio_shares,
                "portfolio_cost": portfolio_cost,
                "reason": reason,
            })

    summary = {
        "match": sum(1 for i in items if i["status"] == "MATCH"),
        "mismatch": sum(1 for i in items if i["status"] == "MISMATCH"),
        "missing_in_ledger": sum(1 for i in items if i["status"] == "MISSING_IN_LEDGER"),
        "missing_in_portfolio": sum(1 for i in items if i["status"] == "MISSING_IN_PORTFOLIO"),
    }
    return {
        "derivation_status": "OK",
        "as_of": _utc_now(),
        "items": items,
        "summary": summary,
        "limitations": derived["data_limitations"],
    }
