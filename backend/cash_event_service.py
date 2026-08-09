"""P0-S1B-B: Manual Cash Event Ledger（append-only 手工现金事件）.

支持 5 类明确现金语义事件，持久化到现有 account_events 表（同 trade_ledger.sqlite3，
复用 account_event_store 存储层，不建第二套账户事件系统）：

    CASH_DEPOSIT     → +amount
    CASH_WITHDRAWAL  → -amount
    CASH_DIVIDEND    → +amount
    CASH_FEE         → -amount
    CASH_TAX         → -amount

方向由 event_type 决定，调用方只传正数 amount（positive / finite / > 0）。
事件为 durable、append-only、restart-safe、atomic、auditable、deterministic 事实；
本轮不做 correction/void（CASH_EVENT_CORRECTION = DEFERRED），不建第二套 correction engine。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import account_event_store
import position_reality_service
import trade_ledger_service
import trade_ledger_store

# cash event 类型白名单唯一来源 = account_event_store.CASH_EVENT_TYPES（DRY，不维护第二套）
CASH_EVENT_TYPES = account_event_store.CASH_EVENT_TYPES

# event_type → cash delta 方向（+入账 / -出账）
_CASH_DELTA = {
    "CASH_DEPOSIT": 1.0,
    "CASH_WITHDRAWAL": -1.0,
    "CASH_DIVIDEND": 1.0,
    "CASH_FEE": -1.0,
    "CASH_TAX": -1.0,
}

_PROVENANCE_MANUAL = "MANUAL"


class CashEventValidationError(ValueError):
    pass


class CashEventNotFoundError(LookupError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def resolve_db_path():
    """Cash events 与 account events 同库（trade_ledger.sqlite3）。"""
    return position_reality_service.resolve_db_path()


def _validate_amount(value: Any) -> float:
    """amount 归一化（DRY）：复用 account_event_store.normalize_cash_amount。

    RAW → numeric → finite → >0 → round 2dp → 归一化后仍必须 >0（0.001 → 拒绝）。
    方向由 event_type 决定（禁止负号表达方向）；返回归一化金额用于落盘。
    """
    try:
        return account_event_store.normalize_cash_amount(value)
    except ValueError as exc:
        raise CashEventValidationError(str(exc))


def create_cash_event(payload: dict[str, Any]) -> dict[str, Any]:
    """创建一条 durable cash event（append-only）。"""
    if not isinstance(payload, dict):
        raise CashEventValidationError("请求体必须是对象")
    allowed = {"event_type", "amount"}
    unknown = set(payload.keys()) - allowed
    if unknown:
        raise CashEventValidationError(f"未知字段: {', '.join(sorted(unknown))}")

    event_type = payload.get("event_type")
    if not isinstance(event_type, str) or event_type not in CASH_EVENT_TYPES:
        raise CashEventValidationError(
            f"event_type 必须是 {sorted(CASH_EVENT_TYPES)}"
        )
    amount = _validate_amount(payload.get("amount"))

    event_record = {
        "event_id": f"cev_{uuid.uuid4().hex}",
        "event_type": event_type,
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
        "target_event_id": None,
        "target_event_type": None,
        "before_payload": None,
        "after_payload": None,
        "reason": None,
        "note": None,
        "amount": amount,  # _validate_amount 已归一化 2dp
        "created_at": _utc_now(),
    }
    account_event_store.insert_event(resolve_db_path(), event_record)
    return event_record


def list_cash_events() -> list[dict[str, Any]]:
    """只读列出全部 active cash events（created_at ASC, rowid ASC）。

    对每条持久化行先做 event_type 完整性校验（未知类型 → fail closed，不得静默隐藏），
    再对 CASH_* 行执行事实校验：event_type ∈ 白名单、amount numeric/finite/>0
    （非 NULL/0/负）、provenance=MANUAL；损坏 → AccountEventCorruptedError。
    """
    events = account_event_store.list_events(resolve_db_path())
    cash_events = []
    for e in events:
        account_event_store.validate_event_type(e.get("event_type"))
        if e.get("event_type") in CASH_EVENT_TYPES:
            account_event_store.validate_persisted_cash_event(e)
            cash_events.append(e)
    return cash_events


def get_cash_event(event_id: str) -> dict[str, Any] | None:
    event = account_event_store.get_event(resolve_db_path(), event_id)
    if event is None:
        return None
    # 未知持久化 event_type 是数据损坏，不能被当作“非现金事件”静默映射成 404。
    # 已知的非现金类型仍保持 404 语义。
    account_event_store.validate_event_type(event.get("event_type"))
    if event.get("event_type") not in CASH_EVENT_TYPES:
        return None
    # 持久化事实校验：损坏 → AccountEventCorruptedError（fail closed）
    account_event_store.validate_persisted_cash_event(event)
    return event


def cash_delta_for(event_type: str, amount: float) -> float:
    """按 event_type 计算现金增量（DEPOSIT/DIVIDEND 正，WITHDRAWAL/FEE/TAX 负）。"""
    return round(_CASH_DELTA[event_type] * float(amount), 2)


def effective_cash_events() -> list[dict[str, Any]]:
    """应用 active CORRECTION 后的 effective cash events（用于 ledger cash candidate）。

    复用 position_reality_service.build_effective_events（同一 correction machinery，
    DRY Hard Gate：TRADE + ACCOUNT EVENT + CASH EVENT 共享同一 engine）。
    每行已通过持久化完整性校验（validate_effective_cash_events 内调用）。
    """
    db_path = resolve_db_path()
    events = account_event_store.list_events(db_path)
    trades = trade_ledger_store.list_records(db_path, include_voided=False, limit=None)
    effective = position_reality_service.build_effective_events(events, trades)
    out = []
    for key, ev in effective.items():
        if key.startswith("account_event:") and ev.get("event_type") in CASH_EVENT_TYPES:
            out.append(ev)
    return out


def correct_cash_event(event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """对 active CASH_* 事件追加 amount correction（复用现有 correction engine）。

    只允许修改 amount（方向永久由 event_type 决定）；target_event_type=account_event。
    before_payload / after_payload / chained / atomic 均由 position_reality_service.
    create_correction 处理（不建第二套 correction engine）。
    """
    if not isinstance(payload, dict):
        raise CashEventValidationError("请求体必须是对象")
    allowed = {"amount", "reason", "note"}
    unknown = set(payload.keys()) - allowed
    if unknown:
        raise CashEventValidationError(f"未知字段: {', '.join(sorted(unknown))}")
    # 归一化（与 create 同一规则）
    amount = _validate_amount(payload.get("amount"))
    # 校验目标是 active CASH_* 事件
    event = get_cash_event(event_id)
    if event is None:
        raise CashEventNotFoundError()
    # reason/note 为可选字段，但一旦出现必须是非空字符串；不能把非法输入
    # （例如数字、空字符串、全空白）静默清洗成 None。这样客户端错误保持在
    # 校验层并由 HTTP 路由明确返回 422，而不会伪装成合法的空元数据。
    for field in ("reason", "note"):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise CashEventValidationError(f"{field} 必须是非空字符串或 null")
    result = position_reality_service.create_correction({
        "target_event_id": event_id,
        "target_event_type": "account_event",
        "after_payload": {"amount": amount},
        "reason": payload.get("reason"),
        "note": payload.get("note"),
    })
    return result
