"""Trade ledger service layer: validation, advice/thesis linking, computed fields."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ai_result_store
import evidence_thesis_service
import trade_ledger_store as store

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DB_ENV = "VIBE_RESEARCH_TRADE_LEDGER_DB"
_MAX_NOTE_LEN = 2000
_MAX_REASON_LEN = 500
_CODE_RE = re.compile(r"^[0-9]{6}$")
_OPERATIONS = frozenset({"buy", "add", "reduce", "sell"})
_EXECUTION_STATUSES = frozenset({"full", "partial", "not_executed"})
_ADVICE_SNAPSHOT_KEYS = frozenset({
    "action",
    "execution_quantity",
    "price_conditions",
    "execution_plan",
    "risk_conditions",
    "invalidation_conditions",
    "confidence",
})

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TradeValidationError(ValueError):
    pass


class TradeNotFoundError(LookupError):
    pass


class TradeAlreadyVoidedError(RuntimeError):
    def __init__(self):
        super().__init__("交易记录已作废")


class AdviceNotFoundError(LookupError):
    pass


class AdviceConflictError(RuntimeError):
    def __init__(self):
        super().__init__("建议已发生变化，generated_at 不一致")


class AdviceHoldingNotFoundError(LookupError):
    pass


class ThesisNotFoundError(LookupError):
    pass


class ThesisRevisionNotFoundError(LookupError):
    pass


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    env_val = os.environ.get(_DB_ENV)
    if env_val and str(env_val).strip():
        return Path(str(env_val).strip())
    data_dir = os.environ.get("VR_DATA_DIR") or str(Path.home() / ".vibe-research")
    return Path(data_dir) / "trade_ledger.sqlite3"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_str(value: Any, field: str, *, max_len: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TradeValidationError(f"{field} 必须是非空字符串")
    text = value.strip()
    if max_len is not None and len(text) > max_len:
        raise TradeValidationError(f"{field} 超过最大长度 {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TradeValidationError(f"{field} 必须是字符串或null")
    text = value.strip()
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        raise TradeValidationError(f"{field} 超过最大长度 {max_len}")
    return text


def _require_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TradeValidationError(f"{field} 必须是整数")
    return value


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise TradeValidationError(f"{field} 必须是整数或null")
    return value


def _require_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TradeValidationError(f"{field} 必须是数字")
    if value != value or value == float("inf") or value == float("-inf"):
        raise TradeValidationError(f"{field} 必须是有限数字")
    return float(value)


def _optional_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TradeValidationError(f"{field} 必须是数字或null")
    if value != value or value == float("inf") or value == float("-inf"):
        raise TradeValidationError(f"{field} 必须是有限数字")
    return float(value)


def _valid_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TradeValidationError(f"{field} 必须是合法时间")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TradeValidationError(f"{field} 不是合法时间") from exc
    return value.strip()


# ---------------------------------------------------------------------------
# Record validation
# ---------------------------------------------------------------------------


def validate_and_build_record(data: dict[str, Any]) -> dict[str, Any]:
    """Validate raw input and build a complete TradeRecord dict."""
    if not isinstance(data, dict):
        raise TradeValidationError("请求体必须是对象")

    # Reject unknown fields
    allowed = {
        "code", "name", "operation", "execution_status",
        "planned_price", "planned_quantity", "actual_price", "actual_quantity",
        "executed_at", "fee", "other_cost", "unexecuted_reason", "note",
        "advice_ref", "thesis_ref",
    }
    unknown = set(data.keys()) - allowed
    if unknown:
        raise TradeValidationError(f"未知字段: {" + ", ".join(sorted(unknown)) + "}")

    code = _require_str(data["code"], "code")
    if not _CODE_RE.fullmatch(code):
        raise TradeValidationError("code 必须是 6 位数字股票代码")

    name = _require_str(data["name"], "name", max_len=64)
    operation = _require_str(data["operation"], "operation")
    if operation not in _OPERATIONS:
        raise TradeValidationError(f"operation 必须是 {sorted(_OPERATIONS)}")

    execution_status = _require_str(data["execution_status"], "execution_status")
    if execution_status not in _EXECUTION_STATUSES:
        raise TradeValidationError(f"execution_status 必须是 {sorted(_EXECUTION_STATUSES)}")

    planned_price = _optional_number(data.get("planned_price"), "planned_price")
    planned_quantity = _optional_int(data.get("planned_quantity"), "planned_quantity")
    actual_price = _optional_number(data.get("actual_price"), "actual_price")
    actual_quantity = _optional_int(data.get("actual_quantity"), "actual_quantity") or 0
    executed_at = _optional_str(data.get("executed_at"), "executed_at")
    fee = _optional_number(data.get("fee"), "fee") or 0.0
    other_cost = _optional_number(data.get("other_cost"), "other_cost") or 0.0
    unexecuted_reason = _optional_str(data.get("unexecuted_reason"), "unexecuted_reason", max_len=_MAX_REASON_LEN)
    note = _optional_str(data.get("note"), "note", max_len=_MAX_NOTE_LEN)

    # --- Status-specific rules ---
    if execution_status == "full":
        if actual_price is None or actual_price <= 0:
            raise TradeValidationError("full 状态要求 actual_price > 0")
        if actual_quantity <= 0:
            raise TradeValidationError("full 状态要求 actual_quantity > 0")
        if planned_quantity is not None and actual_quantity != planned_quantity:
            raise TradeValidationError("full 状态要求 actual_quantity 等于 planned_quantity")
        if unexecuted_reason is not None:
            raise TradeValidationError("full 状态不允许填写 unexecuted_reason")

    elif execution_status == "partial":
        if planned_quantity is None or planned_quantity <= 0:
            raise TradeValidationError("partial 状态要求 planned_quantity > 0")
        if actual_price is None or actual_price <= 0:
            raise TradeValidationError("partial 状态要求 actual_price > 0")
        if actual_quantity <= 0 or actual_quantity >= planned_quantity:
            raise TradeValidationError("partial 状态要求 0 < actual_quantity < planned_quantity")
        if not unexecuted_reason:
            raise TradeValidationError("partial 状态必须填写 unexecuted_reason")

    elif execution_status == "not_executed":
        actual_price = None
        actual_quantity = 0
        executed_at = None
        if not unexecuted_reason:
            raise TradeValidationError("not_executed 状态必须填写 unexecuted_reason")
        fee = 0.0
        other_cost = 0.0

    # Common rules
    if planned_price is not None and planned_price <= 0:
        raise TradeValidationError("planned_price 必须大于 0")
    if planned_quantity is not None and planned_quantity <= 0:
        raise TradeValidationError("planned_quantity 必须大于 0")
    if actual_price is not None and actual_price <= 0:
        raise TradeValidationError("actual_price 必须大于 0")
    if actual_quantity < 0:
        raise TradeValidationError("actual_quantity 不能为负")
    if fee < 0:
        raise TradeValidationError("fee 不能为负")
    if other_cost < 0:
        raise TradeValidationError("other_cost 不能为负")

    # --- Advice reference ---
    advice_trade_date = None
    advice_generated_at = None
    advice_snapshot = None
    advice_ref = data.get("advice_ref")
    if advice_ref is not None:
        advice_trade_date, advice_generated_at, advice_snapshot = _resolve_advice_ref(
            advice_ref, code
        )

    # --- Thesis reference ---
    thesis_id = None
    thesis_revision = None
    thesis_ref = data.get("thesis_ref")
    if thesis_ref is not None:
        thesis_id, thesis_revision = _resolve_thesis_ref(thesis_ref)

    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")

    return {
        "trade_id": uuid.uuid4().hex,
        "code": code,
        "name": name,
        "operation": operation,
        "execution_status": execution_status,
        "planned_price": planned_price,
        "planned_quantity": planned_quantity,
        "actual_price": actual_price,
        "actual_quantity": actual_quantity,
        "executed_at": executed_at,
        "fee": fee,
        "other_cost": other_cost,
        "unexecuted_reason": unexecuted_reason,
        "note": note,
        "advice_trade_date": advice_trade_date,
        "advice_generated_at": advice_generated_at,
        "advice_snapshot": advice_snapshot,
        "thesis_id": thesis_id,
        "thesis_revision": thesis_revision,
        "created_at": now,
    }


# ---------------------------------------------------------------------------
# Advice reference resolution
# ---------------------------------------------------------------------------


def _resolve_advice_ref(advice_ref: Any, code: str) -> tuple[str, str, str]:
    if not isinstance(advice_ref, dict):
        raise TradeValidationError("advice_ref 必须是对象")
    trade_date = advice_ref.get("trade_date")
    generated_at = advice_ref.get("generated_at")
    if not trade_date or not isinstance(trade_date, str):
        raise TradeValidationError("advice_ref.trade_date 必须是 YYYY-MM-DD")
    if not generated_at or not isinstance(generated_at, str):
        raise TradeValidationError("advice_ref.generated_at 必须是时间戳")

    # Read portfolio_advice from ai_generated_results
    review_db = _resolve_review_db_path()
    record = ai_result_store.get_result(review_db, "portfolio_advice", trade_date)
    if record is None:
        raise AdviceNotFoundError()

    stored_generated_at = record.get("generated_at")
    if stored_generated_at != generated_at:
        raise AdviceConflictError()

    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise TradeValidationError("建议 payload 格式错误")

    holdings = payload.get("holdings")
    if not isinstance(holdings, list):
        raise TradeValidationError("建议缺少 holdings")

    matched = None
    for h in holdings:
        if isinstance(h, dict) and h.get("code") == code:
            matched = h
            break
    if matched is None:
        raise AdviceHoldingNotFoundError()

    snapshot = {}
    for key in _ADVICE_SNAPSHOT_KEYS:
        if key in matched:
            snapshot[key] = matched[key]

    return trade_date, generated_at, json.dumps(snapshot, ensure_ascii=False)


def _resolve_review_db_path() -> Path:
    """Resolve the ai_generated_results DB path (same as review_history)."""
    env_val = os.environ.get("VIBE_RESEARCH_REVIEW_DB")
    if env_val and str(env_val).strip():
        return Path(str(env_val).strip())
    data_dir = os.environ.get("VR_DATA_DIR") or str(Path.home() / ".vibe-research")
    return Path(data_dir) / "daily_reviews.sqlite3"


# ---------------------------------------------------------------------------
# Thesis reference resolution
# ---------------------------------------------------------------------------


def _resolve_thesis_ref(thesis_ref: Any) -> tuple[str, int]:
    if not isinstance(thesis_ref, dict):
        raise TradeValidationError("thesis_ref 必须是对象")
    thesis_id = thesis_ref.get("thesis_id")
    revision_number = thesis_ref.get("revision_number")
    if not thesis_id or not isinstance(thesis_id, str):
        raise TradeValidationError("thesis_ref.thesis_id 必须是非空字符串")
    if not isinstance(revision_number, int) or isinstance(revision_number, bool) or revision_number < 1:
        raise TradeValidationError("thesis_ref.revision_number 必须是正整数")

    db_path = evidence_thesis_service.resolve_db_path()
    revision = evidence_thesis_service.get_revision(db_path, thesis_id, revision_number)
    if revision is None:
        thesis = evidence_thesis_service.get_thesis(db_path, thesis_id)
        if thesis is None:
            raise ThesisNotFoundError()
        raise ThesisRevisionNotFoundError()

    return thesis_id, revision_number


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------


def compute_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Add computed fields to a record for API response."""
    operation = record["operation"]
    status = record["execution_status"]
    actual_price = record.get("actual_price") or 0
    actual_quantity = record.get("actual_quantity") or 0
    planned_price = record.get("planned_price")
    planned_quantity = record.get("planned_quantity")
    fee = record.get("fee") or 0
    other_cost = record.get("other_cost") or 0

    gross_amount = round(actual_price * actual_quantity, 2)

    if operation in ("buy", "add"):
        total_cost = round(gross_amount + fee + other_cost, 2)
        net_cash_flow = round(-total_cost, 2)
    elif operation in ("reduce", "sell"):
        total_cost = round(gross_amount - fee - other_cost, 2)
        net_cash_flow = round(total_cost, 2)
    else:
        total_cost = 0.0
        net_cash_flow = 0.0

    price_variance = None
    price_variance_pct = None
    if planned_price and actual_price and status != "not_executed":
        price_variance = round(actual_price - planned_price, 4)
        price_variance_pct = round(price_variance / planned_price * 100, 4)

    quantity_completion_pct = None
    if planned_quantity and planned_quantity > 0 and status != "not_executed":
        quantity_completion_pct = round(actual_quantity / planned_quantity * 100, 2)

    result = dict(record)
    result.update({
        "gross_amount": gross_amount,
        "total_cost": total_cost,
        "net_cash_flow": net_cash_flow,
        "price_variance": price_variance,
        "price_variance_pct": price_variance_pct,
        "quantity_completion_pct": quantity_completion_pct,
    })
    return result


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


def create_trade(data: dict[str, Any]) -> dict[str, Any]:
    record = validate_and_build_record(data)
    db_path = resolve_db_path()
    store.insert_record(db_path, record)
    return compute_fields(record)


def get_trade(trade_id: str) -> dict[str, Any] | None:
    db_path = resolve_db_path()
    record = store.get_record(db_path, trade_id)
    if record is None:
        return None
    return compute_fields(record)


def list_trades(
    *,
    code: str | None = None,
    operation: str | None = None,
    execution_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_voided: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    db_path = resolve_db_path()
    records = store.list_records(
        db_path,
        code=code,
        operation=operation,
        execution_status=execution_status,
        date_from=date_from,
        date_to=date_to,
        include_voided=include_voided,
        limit=limit,
        offset=offset,
    )
    return [compute_fields(r) for r in records]


def void_trade(trade_id: str, reason: str) -> dict[str, Any]:
    reason_clean = _require_str(reason, "reason", max_len=_MAX_REASON_LEN)
    db_path = resolve_db_path()
    record = store.get_record(db_path, trade_id)
    if record is None:
        raise TradeNotFoundError()
    if record.get("voided_at") is not None:
        raise TradeAlreadyVoidedError()
    store.void_record(db_path, trade_id, reason_clean)
    record["voided_at"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    record["void_reason"] = reason_clean
    return compute_fields(record)

