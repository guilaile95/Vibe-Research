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


def _prior_effective_values_on_connection(
    conn,
    target_event_type: str,
    target_event_id: str,
    base: dict[str, Any],
    keys: list[str],
) -> dict[str, Any]:
    """在同一事务连接上，应用 target 的全部 active prior corrections 后返回字段有效值。

    与 _prior_effective_values 语义一致，但读取走调用方持有的 connection（不另开连接、
    不另开事务），保证 target 重读、prior 读取、before 计算、insert 同事务（R6 原子化）。
    顺序 = list_corrections_on_connection（created_at ASC, rowid ASC）。
    """
    prior = account_event_store.list_corrections_on_connection(
        conn, target_event_type, target_event_id
    )
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


def create_correction(payload: dict[str, Any]) -> dict[str, Any]:
    """Append-only correction event; never silent-overwrites history.

    R6 原子化：静态请求校验（payload shape / reason-note 长度 / after_payload 值类型范围）
    在事务外；涉及数据库状态的步骤（target 重新读取 + 状态校验 + 白名单判定 + prior
    corrections 读取 + before_payload 计算 + insert）全部位于同一个
    BEGIN IMMEDIATE ... COMMIT 事务内，任何异常整体 ROLLBACK。
    消除与 void_trade_with_cascade / 并发 create_correction 之间的 TOCTOU 窗口。
    """
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

    # 值类型/范围盲校验（不依赖 DB；白名单键校验依赖 target 状态，在事务内执行）
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
        elif key == "amount":
            # cash 事件修正：复用与 create_cash_event 完全相同的归一化规则（DRY）
            try:
                account_event_store.normalize_cash_amount(value)
            except ValueError as exc:
                raise PositionValidationError(str(exc))
        # 其他键：是否合法取决于 target 类型，由事务内白名单校验决定

    db_path = resolve_db_path()
    # 旧 account_events 表惰性迁移必须在开事务前完成（事务内嵌套 BEGIN 会失败，P0-S1B-B P1）
    account_event_store.ensure_migrated(db_path)
    conn = trade_ledger_store.open_write_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")

        # ---- 事务内：target 重新读取与状态校验（与 insert 同事务，杜绝 TOCTOU）----
        if target_event_type == "trade":
            trade_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("trade_records",),
            ).fetchone()
            if trade_table is None:
                raise CorrectionTargetNotFoundError()
            record = trade_ledger_store.get_record_on_connection(conn, target_event_id)
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
            base: dict[str, Any] = dict(record)
        else:
            if not account_event_store.table_exists_on_connection(conn, "account_events"):
                raise CorrectionTargetNotFoundError()
            event = account_event_store.get_event_on_connection(conn, target_event_id)
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
            elif target_type in account_event_store.CASH_EVENT_TYPES:
                allowed = frozenset({"amount"})  # cash 事件只允许修正 amount（方向由 event_type 决定）
            else:
                raise PositionValidationError(f"不支持的修正目标事件类型: {target_type}")
            base = dict(event)

        # ---- 事务内：白名单键校验（allowed 依赖 target 状态，必须在同事务内判定）----
        unknown_after = set(after_payload.keys()) - allowed
        if unknown_after:
            raise PositionValidationError(
                f"after_payload 含非法字段: {', '.join(sorted(unknown_after))}"
            )

        # ---- 事务内：prior corrections 读取 + before_payload 计算（同一 connection）----
        before = _prior_effective_values_on_connection(
            conn, target_event_type, target_event_id, base, list(after_payload.keys())
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
        # ---- 事务内：insert（不 commit；与 target 校验同事务）----
        account_event_store.insert_event_on_connection(conn, event_record)
        conn.commit()
        return {"status": "CORRECTION_RECORDED", "event": event_record}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def void_trade_with_cascade(trade_id: str, reason: str) -> dict[str, Any]:
    """原子作废交易 + 级联作废指向它的全部 CORRECTION 事件（同一 SQLite 事务）。

    account_events 与 trade_records 同库（trade_ledger.sqlite3），因此 trade void 与
    correction cascade void 必须在同一个 COMMIT 中完成，任何一步失败整体 ROLLBACK，
    不允许存在只完成一半的状态（P1-1 真原子）。

    状态语义：
    - active trade：BEGIN IMMEDIATE → 校验 trade → 级联 void corrections → void trade → COMMIT；
      任一步失败 ROLLBACK（无半完成状态）。
    - missing trade：不修改任何 correction；404 且数据库零副作用。
    - already-voided trade + active orphan corrections：同一事务清理孤儿 correction，
      返回 ALREADY_VOIDED_RECOVERED（HTTP 200）；不出现"改了库还返回 409"。
    - already-voided trade + 无 orphan correction：TradeAlreadyVoidedError（409），零副作用。
    - reason 校验在任何事务/副作用之前。
    """
    if not isinstance(reason, str) or not reason.strip():
        raise PositionValidationError("reason 必填且必须是非空字符串")
    reason_clean = reason.strip()
    if len(reason_clean) > _MAX_REASON_LEN:
        raise PositionValidationError(f"reason 超过最大长度 {_MAX_REASON_LEN}")

    db_path = resolve_db_path()
    # 旧 account_events 表惰性迁移必须在开事务前完成（事务内嵌套 BEGIN 会失败，P0-S1B-B P1）
    account_event_store.ensure_migrated(db_path)
    conn = trade_ledger_store.open_write_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # trade 表不存在 → 视为交易缺失（404，零副作用，不建表）
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("trade_records",),
        ).fetchone()
        if table is None:
            raise trade_ledger_store.TradeNotFoundError()
        rec = trade_ledger_store.get_record_on_connection(conn, trade_id)
        if rec is None:
            raise trade_ledger_store.TradeNotFoundError()

        now = _utc_now()
        if rec.get("voided_at") is not None:
            # 已作废：同一事务内清理孤儿 correction 并返回恢复状态
            orphan = 0
            if account_event_store.table_exists_on_connection(conn, "account_events"):
                orphan = account_event_store.count_active_corrections_on_connection(
                    conn, "trade", trade_id
                )
            if orphan > 0:
                account_event_store.void_corrections_on_connection(
                    conn, "trade", trade_id, now, _CORRECTION_VOID_PREFIX + reason_clean
                )
                conn.commit()
                return {
                    "status": "ALREADY_VOIDED_RECOVERED",
                    "voided_trade": None,
                    "cascade_voided": orphan,
                }
            raise trade_ledger_store.TradeAlreadyVoidedError()

        # active trade：级联 corrections + void trade 同一事务提交
        cascade = 0
        if account_event_store.table_exists_on_connection(conn, "account_events"):
            cascade = account_event_store.void_corrections_on_connection(
                conn, "trade", trade_id, now, _CORRECTION_VOID_PREFIX + reason_clean
            )
        voided = trade_ledger_store.void_trade_on_connection(
            conn, trade_id, now, reason_clean
        )
        conn.commit()
        return {"status": "VOIDED", "voided_trade": voided, "cascade_voided": cascade}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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


def build_effective_events(
    events: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    *,
    ledger_start_ts: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """read-only helper：应用 active corrections 后的 effective events map。

    key 约定：account events → "account_event:{id}"，trades → "trade:{id}"。

    - 排除 voided（由调用方以 include_voided=False 传入）与 not_executed / 零数量交易；
    - 应用全部 active CORRECTION（voided correction 由调用方读取时排除）；
    - chained corrections 按 S1A 同一确定性顺序（created_at ASC）应用；
    - ledger_start_ts 非 None 时对交易做边界校验（早于起点 → fail closed）；
    - 持久化 event_type 必须属于已知集合（ACCOUNT_OPENING / LEGACY_POSITION_OPENING /
      CORRECTION / CASH_*）；未知类型（BOGUS 等）→ fail closed，不得静默忽略
      （account_events 已移除 DB CHECK，读路径必须补回事实完整性边界）。

    供 derive_positions() 与 ledger_cash_candidate 共用同一 correction semantics（DRY），
    确保 Position effective facts 与 Cash effective facts 完全一致。
    """
    corrections = _load_corrections(events)
    events_by_key: dict[str, dict[str, Any]] = {}
    for ev in events:
        etype = ev.get("event_type")
        account_event_store.validate_event_type(etype)
        if etype in (_EVENT_LEGACY_OPENING, _EVENT_ACCOUNT_OPENING):
            events_by_key[f"account_event:{ev['event_id']}"] = dict(ev)
        elif etype in account_event_store.CASH_EVENT_TYPES:
            # cash 事件纳入 effective map，使针对它的 active CORRECTION 能应用（P0-S1B-C）
            account_event_store.validate_persisted_cash_event(ev)
            events_by_key[f"account_event:{ev['event_id']}"] = dict(ev)
        # CORRECTION 由 _load_corrections 处理
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
    # CASH_* effective facts + 针对 CASH_* 的 correction payload 完整性（P0-S1B-C 读路径 fail closed）
    account_event_store.validate_effective_cash_events(events_by_key, corrections)
    return events_by_key


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

    # events_by_key 构建 + active corrections 应用：与 ledger_cash_candidate 共用
    # build_effective_events helper（DRY），保证 Position / Cash 基于同一 effective facts。
    events_by_key = build_effective_events(
        events, trades, ledger_start_ts=ledger_start_ts
    )

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
                # per-share avg cost 保留 4 位小数（portfolio.json 成本正式支持 4 位小数）；
                # reconciliation 使用同一 canonical 4dp avg cost，不在此前损失精度（P1-2）。
                avg_cost = round(float(st["cost"]) / shares, 4)
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
            # portfolio.json 成本按 4 位小数维护；ledger avg_cost 已是 canonical 4dp（P1-2），
            # 直接同精度比较，避免在此前/此处额外损失精度。
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
