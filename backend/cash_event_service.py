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
    """amount 必须 numeric / finite / > 0；归一化到 2dp 后仍必须 > 0（如 0.001 → 拒绝）。

    方向由 event_type 决定（禁止负号表达方向）；返回归一化后的金额用于落盘。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CashEventValidationError("amount 必须是数字")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise CashEventValidationError("amount 必须是有限数字")
    if number <= 0:
        raise CashEventValidationError("amount 必须大于 0（方向由 event_type 决定）")
    normalized = round(number, 2)
    # 归一化后再验证：0.001 → 0.00 → 拒绝，不得落盘 0.00 的"成功"事实
    if normalized <= 0:
        raise CashEventValidationError("amount 归一化到 2 位小数后必须大于 0")
    return normalized


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
    if event.get("event_type") not in CASH_EVENT_TYPES:
        return None
    # 持久化事实校验：损坏 → AccountEventCorruptedError（fail closed）
    account_event_store.validate_persisted_cash_event(event)
    return event


def cash_delta_for(event_type: str, amount: float) -> float:
    """按 event_type 计算现金增量（DEPOSIT/DIVIDEND 正，WITHDRAWAL/FEE/TAX 负）。"""
    return round(_CASH_DELTA[event_type] * float(amount), 2)
