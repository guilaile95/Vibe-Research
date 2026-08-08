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
from datetime import datetime, timedelta, timezone
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


def _normalize_ledger_start(value: Any) -> str:
    """Validate ledger_start_at and normalize to UTC ISO 8601.

    接受 "YYYY-MM-DD"（按当日 00:00 北京时间作为市场日边界）或带时区的 ISO 8601 时间；
    非法格式 / 非法日历日期 / 缺失时区 → 拒绝（PositionValidationError）。
    """
    if not isinstance(value, str) or not value.strip():
        raise PositionValidationError("ledger_start_at 必须是非空字符串")
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            y, m, d = map(int, text.split("-"))
            dt = datetime(y, m, d, tzinfo=timezone(timedelta(hours=8)))
        except ValueError as exc:
            raise PositionValidationError("ledger_start_at 不是有效日历日期") from exc
    else:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PositionValidationError("ledger_start_at 不是合法 ISO 8601 时间") from exc
        if dt.tzinfo is None:
            raise PositionValidationError("ledger_start_at 必须包含时区信息")
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


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

    ledger_start_at = _normalize_ledger_start(payload.get("ledger_start_at"))
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

_CORRECTION_VOID_PREFIX = "cascade-void: "


def _cascade_void_corrections(
    db_path, target_event_type: str, target_event_id: str, reason: str
) -> int:
    """Void 目标事件时，级联 void 指向它的所有 CORRECTION 事件。

    保持 append-only（不删除记录，仅标记 voided_at），避免"孤儿修正"使整条账本
    derivation 永久 fail closed 且无恢复路径（P1-1）。
    """
    events = account_event_store.list_events(
        db_path, event_type=_EVENT_CORRECTION, include_voided=False
    )
    count = 0
    for ev in events:
        if (
            ev.get("target_event_id") == target_event_id
            and ev.get("target_event_type") == target_event_type
        ):
            account_event_store.void_event_atomic(
                db_path, ev["event_id"], _CORRECTION_VOID_PREFIX + reason
            )
            count += 1
    return count


def _prior_effective_values(
    db_path,
    target_event_type: str,
    target_event_id: str,
    base: dict[str, Any],
    keys: list[str],
) -> dict[str, Any]:
    """应用目标的所有先前 correction（按 created_at 升序）后，返回这些字段的有效当前值。

    连续 correction 的 before_payload 必须反映"应用之前所有 correction 之后"的值，
    而不是每次都从原始目标读取（保持 append-only，不修改旧 correction）。
    """
    events = account_event_store.list_events(db_path, event_type=_EVENT_CORRECTION)
    prior = [
        e for e in events
        if e.get("target_event_id") == target_event_id
        and e.get("target_event_type") == target_event_type
    ]
    prior.sort(key=lambda e: str(e.get("created_at") or ""))
    current = dict(base)
    for corr in prior:
        try:
            after = json.loads(corr["after_payload"])
        except (TypeError, ValueError) as exc:
            raise PositionValidationError("已有 correction 数据损坏") from exc
        if isinstance(after, dict):
            for k, v in after.items():
                current[k] = v
    return {k: current.get(k) for k in keys}


def void_trade_with_cascade(trade_id: str, reason: str) -> dict[str, Any]:
    """作废一笔交易并级联作废指向它的全部 CORRECTION 事件。

    与既有 trade_ledger_service.void_trade 行为兼容，但防止孤儿修正让账本
    derivation 永久 fail closed（P1-1）。返回 {'voided_trade': ..., 'cascade_voided': n}。
    """
    db_path = resolve_db_path()
    # 先级联（其自身幂等），再作废交易；交易不存在时抛既有异常
    voided = trade_ledger_service.void_trade(trade_id, reason)
    cascade = _cascade_void_corrections(db_path, "trade", trade_id, reason)
    return {"voided_trade": voided, "cascade_voided": cascade}


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

    reason = _optional_str(payload.get("reason"), "reason", max_len=_MAX_REASON_LEN)
    note = _optional_str(payload.get("note"), "note", max_len=_MAX_NOTE_LEN)

    db_path = resolve_db_path()

    # 确认目标状态是 correction engine 真正能够应用的状态，并据此决定允许字段
    if target_event_type == "trade":
        record = trade_ledger_store.get_record(db_path, target_event_id)
        if record is None:
            raise CorrectionTargetNotFoundError()
        if record.get("voided_at") is not None:
            raise PositionValidationError("目标交易已作废，禁止修正已作废记录")
        if (
            record.get("execution_status") == "not_executed"
            or (record.get("actual_quantity") or 0) <= 0
        ):
            raise PositionValidationError(
                "目标交易不在可修正状态（未成交/数量为 0 的交易不参与推导）"
            )
        allowed = _CORRECTION_TRADE_KEYS
        base: dict[str, Any] = record
    else:
        event = account_event_store.get_event(db_path, target_event_id)
        if event is None:
            raise CorrectionTargetNotFoundError()
        if event.get("voided_at") is not None:
            raise PositionValidationError("目标事件已作废，禁止修正已作废记录")
        target_type = event.get("event_type")
        if target_type == _EVENT_CORRECTION:
            raise PositionValidationError("不允许修正 CORRECTION 事件")
        if target_type == _EVENT_LEGACY_OPENING:
            allowed = _CORRECTION_EVENT_KEYS  # shares / cost_basis
        elif target_type == _EVENT_ACCOUNT_OPENING:
            allowed = frozenset({"opening_cash"})  # ledger_start_at 不可变（事实边界）
        else:
            raise PositionValidationError(f"不支持的修正目标事件类型: {target_type}")
        base = event

    unknown_after = set(after_payload.keys()) - allowed
    if unknown_after:
        raise PositionValidationError(
            f"after_payload 含非法字段: {', '.join(sorted(unknown_after))}"
        )

    # 校验修正后的值（白名单内字段的类型与范围）
    for key, value in after_payload.items():
        if key == "shares":
            _require_int(value, "shares", min_value=0)
        elif key == "cost_basis":
            _optional_number(value, "cost_basis")
        elif key == "opening_cash":
            _optional_number(value, "opening_cash")
        elif key == "actual_quantity":
            # 与契约一致：零数量交易不参与推导，修正不允许把数量改成 0（P2-3）
            _require_int(value, "actual_quantity", min_value=1)
        elif key in ("actual_price", "fee", "other_cost"):
            _require_number(value, key)

    # before = 应用所有先前 correction 后的有效当前值（append-only 链式，不读原始目标）
    before = _prior_effective_values(
        db_path, target_event_type, target_event_id, base, list(after_payload.keys())
    )

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

    # Ledger boundary：ACCOUNT_OPENING 定义 Vibe 接管起点；
    # 任何有效交易若 executed_at 早于边界 → fail closed，不得偷偷按 POST_VIBE 应用。
    ledger_start_ts: datetime | None = None
    if openings:
        raw_start = openings[0].get("ledger_start_at")
        if not isinstance(raw_start, str) or not raw_start:
            raise PositionDerivationError("ACCOUNT_OPENING 缺少 ledger_start_at")
        try:
            parsed_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PositionDerivationError("ACCOUNT_OPENING ledger_start_at 无法解析") from exc
        if parsed_start.tzinfo is None:
            raise PositionDerivationError("ACCOUNT_OPENING ledger_start_at 缺少时区信息")
        ledger_start_ts = parsed_start

    corrections = _load_corrections(events)

    events_by_key: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev["event_type"] in (_EVENT_LEGACY_OPENING, _EVENT_ACCOUNT_OPENING):
            events_by_key[f"account_event:{ev['event_id']}"] = dict(ev)
    for t in trades:
        if t["execution_status"] == "not_executed":
            continue
        if (t.get("actual_quantity") or 0) <= 0:
            continue
        if ledger_start_ts is not None:
            executed_raw = str(t.get("executed_at") or "")
            try:
                executed_ts = datetime.fromisoformat(executed_raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise PositionDerivationError(
                    f"交易时间无法解析: {t.get('code')}"
                ) from exc
            if executed_ts.tzinfo is None:
                raise PositionDerivationError(f"交易时间缺少时区: {t.get('code')}")
            if executed_ts < ledger_start_ts:
                raise PositionDerivationError(
                    f"交易时间早于 ledger 起点，账本推导失败: {t.get('code')}"
                )
        events_by_key[f"trade:{t['trade_id']}"] = dict(t)

    _apply_corrections(events_by_key, corrections)

    # Build chronological sequence: legacy openings (ledger boundary) FIRST, then trades.
    # Opening 事件语义是"Vibe 接管日边界"，必须先于所有 post-Vibe 交易应用；
    # 不能只按 created_at/executed_at 排序（开仓事件时间可能晚于测试/历史交易时间）。
    # 交易时间统一归一化为 UTC 纪元秒后再排序，避免混时区（+08:00/+00:00）格式导致的顺序错乱（P2-1）。
    sequence: list[tuple[int, float, str, dict[str, Any]]] = []
    for key, event in events_by_key.items():
        if key.startswith("account_event:"):
            raw_ts = str(event.get("created_at") or "")
            rank = 0
        else:
            raw_ts = str(event.get("executed_at") or event.get("created_at") or "")
            rank = 1
        if raw_ts:
            try:
                ts_value = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp()
            except ValueError as exc:
                raise PositionDerivationError("事件时间无法解析") from exc
        else:
            ts_value = 0.0
        sequence.append((rank, ts_value, key, event))
    sequence.sort(key=lambda item: (item[0], item[1], item[2]))

    states: dict[str, dict[str, Any]] = {}
    for rank, _ts, _key, event in sequence:
        if _key.startswith("account_event:"):
            if event["event_type"] != _EVENT_LEGACY_OPENING:
                continue  # ACCOUNT_OPENING 只提供 ledger 边界头，不参与持仓状态
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
            if st["shares"] == 0:
                # 空仓首次 BUY/ADD：建立已知成本（修复 UNKNOWN 永久化问题）
                st["cost_known"] = True
                st["cost"] = price * qty + fee + other
            elif st["cost_known"]:
                st["cost"] = st["cost"] + price * qty + fee + other
            # shares > 0 且原成本 UNKNOWN → ADD 后仍保持 UNKNOWN
            st["shares"] += qty
        elif operation in ("reduce", "sell"):
            if qty > st["shares"]:
                raise PositionDerivationError(
                    f"卖出数量超过可用持仓，账本推导失败: {code}"
                )
            if st["cost_known"] and st["shares"] > 0:
                avg = st["cost"] / st["shares"]
                # 与 performance_attribution 的扣减公式完全对齐（不中间 round），
                # 避免多次卖出后的浮点漂移导致 cost_basis 与归因不一致（P2-2）。
                st["cost"] = st["cost"] - avg * qty
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
        corrected_opening = events_by_key.get(f"account_event:{opening['event_id']}")
        if corrected_opening is not None:
            opening = corrected_opening
        ledger_start = {
            "ledger_start_at": opening.get("ledger_start_at"),
            "opening_cash": opening.get("opening_cash"),
            "pre_vibe_history": _HISTORY_UNKNOWN,
            "bootstrapped_at": opening.get("created_at"),
        }

    return {
        "derivation_status": "OK",
        "bootstrap_status": "BOOTSTRAPPED" if openings else "NOT_BOOTSTRAPPED",
        "canonical": bool(openings),
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
            # portfolio.json 成本按 4 位小数维护（portfolio.py）；对账比较统一用 4 位精度（P2-4）
            if round(float(ledger_shares), 2) != round(float(portfolio_shares or 0), 2):
                status = "MISMATCH"
                reason = "shares mismatch"
            elif not lp["cost_known"] or ledger_avg is None:
                status = "MISMATCH"
                reason = "ledger cost UNKNOWN"
            elif portfolio_cost is None or round(float(ledger_avg), 4) != round(float(portfolio_cost), 4):
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
        "bootstrap_status": derived["bootstrap_status"],
        "canonical": derived["canonical"],
        "as_of": _utc_now(),
        "items": items,
        "summary": summary,
        "limitations": derived["data_limitations"],
    }
