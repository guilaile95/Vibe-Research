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
_ACTIONS = frozenset({"add", "hold", "reduce", "sell", "watch", "avoid"})
_CONFIDENCES = frozenset({"high", "medium", "low"})
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


class TradeNotFoundError(store.TradeNotFoundError):
    pass


class TradeAlreadyVoidedError(store.TradeAlreadyVoidedError):
    pass


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


def _require_str(data: dict[str, Any], field: str, *, max_len: int | None = None) -> str:
    if field not in data or data[field] is None:
        raise TradeValidationError(f"{field} 必填")
    value = data[field]
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
        raise TradeValidationError(f"{field} 必须是字符串或 null")
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
        raise TradeValidationError(f"{field} 必须是整数或 null")
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
        raise TradeValidationError(f"{field} 必须是数字或 null")
    if value != value or value == float("inf") or value == float("-inf"):
        raise TradeValidationError(f"{field} 必须是有限数字")
    return float(value)


def _parse_and_format_utc_executed_at(value: Any) -> str:
    """Parse executed_at ISO string, require timezone, and convert to UTC ISO string."""
    if not isinstance(value, str) or not value.strip():
        raise TradeValidationError("executed_at 必须是非空字符串")
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TradeValidationError("executed_at 不是合法 ISO 8601 时间") from exc
    if dt.tzinfo is None:
        raise TradeValidationError("executed_at 必须包含时区信息")
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.isoformat(timespec="microseconds")


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
        raise TradeValidationError(f"未知字段: {', '.join(sorted(unknown))}")

    code = _require_str(data, "code")
    if not _CODE_RE.fullmatch(code):
        raise TradeValidationError("code 必须是 6 位数字股票代码")

    name = _require_str(data, "name", max_len=64)
    operation = _require_str(data, "operation")
    if operation not in _OPERATIONS:
        raise TradeValidationError(f"operation 必须是 {sorted(_OPERATIONS)}")

    execution_status = _require_str(data, "execution_status")
    if execution_status not in _EXECUTION_STATUSES:
        raise TradeValidationError(f"execution_status 必须是 {sorted(_EXECUTION_STATUSES)}")

    planned_price = _optional_number(data.get("planned_price"), "planned_price")
    planned_quantity = _optional_int(data.get("planned_quantity"), "planned_quantity")
    actual_price = _optional_number(data.get("actual_price"), "actual_price")
    actual_quantity = _optional_int(data.get("actual_quantity"), "actual_quantity") or 0
    fee = _optional_number(data.get("fee"), "fee") or 0.0
    other_cost = _optional_number(data.get("other_cost"), "other_cost") or 0.0
    unexecuted_reason = _optional_str(data.get("unexecuted_reason"), "unexecuted_reason", max_len=_MAX_REASON_LEN)
    note = _optional_str(data.get("note"), "note", max_len=_MAX_NOTE_LEN)

    # Status-specific executed_at and numeric rules
    if execution_status in ("full", "partial"):
        if "executed_at" not in data or data["executed_at"] is None:
            raise TradeValidationError("full 和 partial 状态要求 executed_at 必填")
        executed_at = _parse_and_format_utc_executed_at(data["executed_at"])
    else:
        executed_at = None

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

    # Common bounds
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

    # Advice reference
    advice_trade_date = None
    advice_generated_at = None
    advice_snapshot = None
    advice_ref = data.get("advice_ref")
    if advice_ref is not None:
        advice_trade_date, advice_generated_at, advice_snapshot = _resolve_advice_ref(
            advice_ref, code
        )

    # Thesis reference
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

    allowed = {"trade_date", "generated_at"}
    unknown = set(advice_ref.keys()) - allowed
    if unknown:
        raise TradeValidationError(f"advice_ref 含有未知字段: {', '.join(sorted(unknown))}")

    trade_date = advice_ref.get("trade_date")
    generated_at = advice_ref.get("generated_at")
    if not trade_date or not isinstance(trade_date, str) or not re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", trade_date):
        raise TradeValidationError("advice_ref.trade_date 必须是 YYYY-MM-DD")
    if not generated_at or not isinstance(generated_at, str) or not generated_at.strip():
        raise TradeValidationError("advice_ref.generated_at 必须是非空字符串")

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

    if payload.get("trade_date") != trade_date or payload.get("generated_at") != generated_at:
        raise AdviceConflictError()

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

    # Verify and extract exact 7 fields
    snapshot = _validate_and_extract_advice_snapshot(matched)

    snapshot_json = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return trade_date, generated_at, snapshot_json


def _validate_and_extract_advice_snapshot(holding: dict[str, Any]) -> dict[str, Any]:
    missing = _ADVICE_SNAPSHOT_KEYS - set(holding.keys())
    if missing:
        raise TradeValidationError(f"建议持仓缺少必需字段: {', '.join(sorted(missing))}")

    action = holding["action"]
    if action not in _ACTIONS:
        raise TradeValidationError(f"建议 action 非法: {action}")

    execution_quantity = holding["execution_quantity"]
    if execution_quantity is not None:
        if not isinstance(execution_quantity, int) or isinstance(execution_quantity, bool) or execution_quantity <= 0:
            raise TradeValidationError("建议 execution_quantity 必须是正整数或 null")

    def _str_list(val: Any, name: str) -> list[str]:
        if not isinstance(val, list):
            raise TradeValidationError(f"建议 {name} 必须是数组")
        output = []
        for item in val:
            if not isinstance(item, str):
                raise TradeValidationError(f"建议 {name} 必须包含字符串")
            output.append(item)
        return output

    price_conditions = _str_list(holding["price_conditions"], "price_conditions")
    execution_plan = _str_list(holding["execution_plan"], "execution_plan")
    risk_conditions = _str_list(holding["risk_conditions"], "risk_conditions")
    invalidation_conditions = _str_list(holding["invalidation_conditions"], "invalidation_conditions")

    confidence = holding["confidence"]
    if confidence not in _CONFIDENCES:
        raise TradeValidationError(f"建议 confidence 非法: {confidence}")

    return {
        "action": action,
        "execution_quantity": execution_quantity,
        "price_conditions": price_conditions,
        "execution_plan": execution_plan,
        "risk_conditions": risk_conditions,
        "invalidation_conditions": invalidation_conditions,
        "confidence": confidence,
    }


def _resolve_review_db_path() -> Path:
    """Resolve the ai_generated_results DB path."""
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

    allowed = {"thesis_id", "revision_number"}
    unknown = set(thesis_ref.keys()) - allowed
    if unknown:
        raise TradeValidationError(f"thesis_ref 含有未知字段: {', '.join(sorted(unknown))}")

    thesis_id = thesis_ref.get("thesis_id")
    revision_number = thesis_ref.get("revision_number")
    if not thesis_id or not isinstance(thesis_id, str) or not thesis_id.strip():
        raise TradeValidationError("thesis_ref.thesis_id 必须是非空字符串")
    if not isinstance(revision_number, int) or isinstance(revision_number, bool) or revision_number < 1:
        raise TradeValidationError("thesis_ref.revision_number 必须是正整数")

    db_path = evidence_thesis_service.resolve_db_path()
    revision = evidence_thesis_service.get_revision(db_path, thesis_id.strip(), revision_number)
    if revision is None:
        thesis = evidence_thesis_service.get_thesis(db_path, thesis_id.strip())
        if thesis is None:
            raise ThesisNotFoundError()
        raise ThesisRevisionNotFoundError()

    return thesis_id.strip(), revision_number


# ---------------------------------------------------------------------------
# Computed fields & Snapshot deserialization
# ---------------------------------------------------------------------------


def compute_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Add computed fields to a record and parse advice_snapshot JSON."""
    operation = record["operation"]
    status = record["execution_status"]
    actual_price = record.get("actual_price") or 0.0
    actual_quantity = record.get("actual_quantity") or 0
    planned_price = record.get("planned_price")
    planned_quantity = record.get("planned_quantity")
    fee = record.get("fee") or 0.0
    other_cost = record.get("other_cost") or 0.0

    gross_amount = round(actual_price * actual_quantity, 2)
    total_cost = round(fee + other_cost, 2)

    if operation in ("buy", "add"):
        net_cash_flow = round(-(gross_amount + total_cost), 2)
    elif operation in ("reduce", "sell"):
        net_cash_flow = round(gross_amount - total_cost, 2)
    else:
        gross_amount = 0.0
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

    raw_snapshot = record.get("advice_snapshot")
    deserialized_snapshot = None
    if raw_snapshot is not None:
        if isinstance(raw_snapshot, dict):
            deserialized_snapshot = raw_snapshot
        elif isinstance(raw_snapshot, str):
            try:
                parsed = json.loads(raw_snapshot)
                if not isinstance(parsed, dict):
                    raise store.TradeLedgerCorruptedError()
                deserialized_snapshot = parsed
            except (json.JSONDecodeError, ValueError) as exc:
                raise store.TradeLedgerCorruptedError() from exc
        else:
            raise store.TradeLedgerCorruptedError()

    result = dict(record)
    result.update({
        "gross_amount": gross_amount,
        "total_cost": total_cost,
        "net_cash_flow": net_cash_flow,
        "price_variance": price_variance,
        "price_variance_pct": price_variance_pct,
        "quantity_completion_pct": quantity_completion_pct,
        "advice_snapshot": deserialized_snapshot,
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
    if not isinstance(reason, str) or not reason.strip():
        raise TradeValidationError("reason 必填且必须是非空字符串")
    reason_clean = reason.strip()
    if len(reason_clean) > _MAX_REASON_LEN:
        raise TradeValidationError(f"reason 超过最大长度 {_MAX_REASON_LEN}")

    db_path = resolve_db_path()
    updated_record = store.void_record_atomic(db_path, trade_id, reason_clean)
    return compute_fields(updated_record)
