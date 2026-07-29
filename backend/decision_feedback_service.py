"""Decision feedback service layer: validation, advice/trade linking, store operations."""
from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

import ai_result_store
import decision_feedback_store as store
import review_history
import trade_ledger_service
import trade_ledger_store

_DB_ENV = "VIBE_RESEARCH_DECISION_FEEDBACK_DB"
_CODE_RE = re.compile(r"^[0-9]{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_NOTE_LEN = 2000
_MAX_REASON_LEN = 500

ADOPTION_STATUSES = frozenset(
    {"followed", "partially_followed", "not_followed", "not_applicable"}
)
OUTCOME_STATUSES = frozenset(
    {"better_than_expected", "as_expected", "worse_than_expected", "not_evaluated"}
)


class AdviceRefInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_date: str
    generated_at: str


class CreateFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    advice_ref: AdviceRefInput
    trade_id: str | None = None
    adoption_status: str
    outcome_status: str
    note: str | None = None


class VoidFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class DecisionFeedbackValidationError(ValueError):
    pass


DecisionFeedbackNotFoundError = store.DecisionFeedbackNotFoundError
DecisionFeedbackAlreadyVoidedError = store.DecisionFeedbackAlreadyVoidedError


class AdviceNotFoundError(LookupError):
    pass


class AdviceConflictError(RuntimeError):
    def __init__(self, message: str = "建议已发生变化，generated_at 不一致"):
        super().__init__(message)


class AdviceHoldingNotFoundError(LookupError):
    pass


class TradeNotFoundError(LookupError):
    pass


class TradeInvalidError(ValueError):
    pass


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    env_val = os.environ.get(_DB_ENV)
    if env_val and str(env_val).strip():
        return Path(str(env_val).strip())
    data_dir = os.environ.get("VR_DATA_DIR") or str(Path.home() / ".vibe-research")
    return Path(data_dir) / "decision_feedback.sqlite3"


def _verify_advice_ref(code: str, trade_date: str, generated_at: str) -> None:
    review_db = review_history.resolve_review_db_path()
    try:
        record = ai_result_store.get_result(review_db, "portfolio_advice", trade_date)
    except Exception as exc:
        raise store.DecisionFeedbackCorruptedError() from exc

    if record is None:
        raise AdviceNotFoundError("未找到对应交易日的持仓建议")

    if record.get("generated_at") != generated_at:
        raise AdviceConflictError("建议已发生变化，generated_at 不一致")

    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise DecisionFeedbackValidationError("建议 payload 格式错误")

    holdings = payload.get("holdings")
    if not isinstance(holdings, list):
        raise DecisionFeedbackValidationError("建议缺少 holdings")

    matched = None
    for h in holdings:
        if isinstance(h, dict) and h.get("code") == code:
            matched = h
            break
    if matched is None:
        raise AdviceHoldingNotFoundError("建议中未找到该股票代码")


def _verify_trade_id(
    trade_id: str,
    code: str,
    advice_trade_date: str,
    advice_generated_at: str,
) -> None:
    trade_db = trade_ledger_service.resolve_db_path()
    try:
        trade_record = trade_ledger_store.get_record(trade_db, trade_id)
    except trade_ledger_store.TradeLedgerCorruptedError as exc:
        raise store.DecisionFeedbackCorruptedError() from exc

    if trade_record is None:
        raise TradeNotFoundError("未找到关联的交易记录")

    if trade_record.get("code") != code:
        raise TradeInvalidError("交易记录的股票代码与反馈不一致")

    t_trade_date = trade_record.get("advice_trade_date")
    t_generated_at = trade_record.get("advice_generated_at")
    if not t_trade_date or not t_generated_at:
        raise TradeInvalidError("关联的交易无持仓建议信息，拒绝关联")

    if t_trade_date != advice_trade_date or t_generated_at != advice_generated_at:
        raise TradeInvalidError("交易记录的持仓建议关联与反馈不一致")


def _validate_date_str(val: Any, field_name: str) -> str:
    if not isinstance(val, str) or not _DATE_RE.fullmatch(val.strip()):
        raise DecisionFeedbackValidationError(f"{field_name} 必须是 YYYY-MM-DD")
    try:
        y, m, d = map(int, val.strip().split("-"))
        date(y, m, d)
    except ValueError:
        raise DecisionFeedbackValidationError(f"{field_name} 不是有效日历日期")
    return val.strip()


def create_feedback(
    data: dict[str, Any],
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DecisionFeedbackValidationError("请求数据必须是字典")

    try:
        validated = CreateFeedbackInput.model_validate(data)
    except ValidationError as exc:
        raise DecisionFeedbackValidationError(str(exc))

    code = validated.code.strip()
    if not _CODE_RE.fullmatch(code):
        raise DecisionFeedbackValidationError("code 必须为 6 位数字")

    advice_trade_date = _validate_date_str(validated.advice_ref.trade_date, "advice_trade_date")
    advice_generated_at = validated.advice_ref.generated_at.strip()
    if not advice_generated_at:
        raise DecisionFeedbackValidationError("advice_generated_at 必须是非空字符串")

    _verify_advice_ref(code, advice_trade_date, advice_generated_at)

    trade_id: str | None = None
    if validated.trade_id is not None:
        trade_id = validated.trade_id.strip()
        if not trade_id:
            raise DecisionFeedbackValidationError("trade_id 必须为非空字符串")
        _verify_trade_id(trade_id, code, advice_trade_date, advice_generated_at)

    if validated.adoption_status not in ADOPTION_STATUSES:
        raise DecisionFeedbackValidationError(
            f"adoption_status 必须是 {sorted(ADOPTION_STATUSES)} 之一"
        )

    if validated.outcome_status not in OUTCOME_STATUSES:
        raise DecisionFeedbackValidationError(
            f"outcome_status 必须是 {sorted(OUTCOME_STATUSES)} 之一"
        )

    note: str | None = None
    if validated.note is not None:
        stripped = validated.note.strip()
        if len(stripped) > _MAX_NOTE_LEN:
            raise DecisionFeedbackValidationError(
                f"note 长度不能超过 {_MAX_NOTE_LEN} 字符"
            )
        if stripped:
            note = stripped

    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    feedback_id = f"fb_{uuid.uuid4().hex}"

    record = {
        "feedback_id": feedback_id,
        "code": code,
        "advice_trade_date": advice_trade_date,
        "advice_generated_at": advice_generated_at,
        "trade_id": trade_id,
        "adoption_status": validated.adoption_status,
        "outcome_status": validated.outcome_status,
        "note": note,
        "created_at": now,
        "voided_at": None,
        "void_reason": None,
    }

    target_db = resolve_db_path(db_path)
    store.insert_record(target_db, record)
    return record


def get_feedback(
    feedback_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    target_db = resolve_db_path(db_path)
    return store.get_record(target_db, feedback_id)


def list_feedbacks(
    *,
    code: str | None = None,
    adoption_status: str | None = None,
    outcome_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_voided: bool = False,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    if code is not None:
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code.strip()):
            raise DecisionFeedbackValidationError("code 必须为 6 位数字")
        code = code.strip()

    if adoption_status is not None:
        if adoption_status not in ADOPTION_STATUSES:
            raise DecisionFeedbackValidationError("adoption_status 参数无效")

    if outcome_status is not None:
        if outcome_status not in OUTCOME_STATUSES:
            raise DecisionFeedbackValidationError("outcome_status 参数无效")

    if date_from is not None:
        date_from = _validate_date_str(date_from, "date_from")

    if date_to is not None:
        date_to = _validate_date_str(date_to, "date_to")

    if date_from and date_to and date_from > date_to:
        raise DecisionFeedbackValidationError("date_from 不能大于 date_to")

    target_db = resolve_db_path(db_path)
    return store.list_records(
        target_db,
        code=code,
        adoption_status=adoption_status,
        outcome_status=outcome_status,
        date_from=date_from,
        date_to=date_to,
        include_voided=include_voided,
        limit=limit,
        offset=offset,
    )


def void_feedback(
    feedback_id: str,
    data: dict[str, Any] | str | None = None,
    *,
    void_reason: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    reason: str | None = None
    if isinstance(data, dict):
        try:
            validated = VoidFeedbackInput.model_validate(data)
            reason = validated.reason
        except ValidationError as exc:
            raise DecisionFeedbackValidationError(str(exc))
    elif isinstance(data, str):
        reason = data
    elif void_reason is not None:
        reason = void_reason

    if reason is not None:
        if not isinstance(reason, str):
            raise DecisionFeedbackValidationError("reason 必须是字符串")
        stripped = reason.strip()
        if len(stripped) > _MAX_REASON_LEN:
            raise DecisionFeedbackValidationError(
                f"void_reason 长度不能超过 {_MAX_REASON_LEN} 字符"
            )
        reason = stripped if stripped else None

    target_db = resolve_db_path(db_path)
    return store.void_record(target_db, feedback_id, void_reason=reason)
