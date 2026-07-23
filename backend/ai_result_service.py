"""Validation, save, fingerprint and recovery rules for generated AI results."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any, Mapping

import ai_result_store
import daily_review
import daily_review_cache
import portfolio
import review_history


DAILY_REVIEW_AI = "daily_review_ai"
PORTFOLIO_ADVICE = "portfolio_advice"
ALLOWED_RESULT_TYPES = frozenset({DAILY_REVIEW_AI, PORTFOLIO_ADVICE})
PORTFOLIO_STALE_MESSAGE = "持仓已发生变化，该建议基于生成时的持仓，可能已经过期。"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SENSITIVE_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "authorization",
        "baseurl",
        "base_url",
        "prompt",
        "messages",
        "model_context",
        "raw_response",
        "traceback",
        "sql",
        "local_path",
        "file_path",
    }
)


class AiResultValidationError(ValueError):
    """Business input is not safe or complete enough to persist."""


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AiResultValidationError(f"{field} 必须是非空字符串")
    return value.strip()


def _valid_timestamp(value: Any, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    text = _nonempty_string(value, field)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AiResultValidationError(f"{field} 不是合法时间") from exc
    return text


def validate_result_identity(result_type: Any, trade_date: Any) -> tuple[str, str]:
    if result_type not in ALLOWED_RESULT_TYPES:
        raise AiResultValidationError("不支持的 AI 结果类型")
    if not isinstance(trade_date, str) or not _DATE_RE.fullmatch(trade_date):
        raise AiResultValidationError("trade_date 必须是 YYYY-MM-DD")
    try:
        y, m, d = map(int, trade_date.split("-"))
        date(y, m, d)
    except ValueError as exc:
        raise AiResultValidationError("trade_date 不是有效日期") from exc
    return result_type, trade_date


def normalize_provider(provider: Any) -> str:
    if provider is None:
        return "api-compatible"
    if not isinstance(provider, str):
        raise AiResultValidationError("model_provider 必须是字符串")
    value = provider.strip()
    return value or "api-compatible"


def validate_model_info(provider: Any, model_name: Any) -> tuple[str, str]:
    return normalize_provider(provider), _nonempty_string(model_name, "model_name")


def _config_value(cfg: Any, key: str, default: Any = None) -> Any:
    if isinstance(cfg, Mapping):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def _assert_safe_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in _SENSITIVE_KEYS:
                raise AiResultValidationError("payload 包含不允许持久化的敏感字段")
            _assert_safe_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_safe_payload(child)


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise AiResultValidationError("payload 必须是非空对象")
    _assert_safe_payload(payload)
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AiResultValidationError("payload 无法安全序列化") from exc
    return copy.deepcopy(payload)


def compute_portfolio_fingerprint(holdings: Any) -> str:
    if not isinstance(holdings, list):
        raise AiResultValidationError("holdings 必须是数组")
    canonical: list[dict[str, Any]] = []
    seen: set[str] = set()
    for holding in holdings:
        if not isinstance(holding, dict):
            raise AiResultValidationError("持仓记录必须是对象")
        code = holding.get("code")
        shares = holding.get("shares")
        cost = holding.get("cost")
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
            raise AiResultValidationError("持仓代码必须是六位字符串")
        if code in seen:
            raise AiResultValidationError("持仓代码不能重复")
        seen.add(code)
        if isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0:
            raise AiResultValidationError("持仓数量必须是正整数")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost):
            raise AiResultValidationError("持仓成本必须是有限数字")
        canonical.append({"code": code, "shares": shares, "cost": cost})
    canonical.sort(key=lambda item: item["code"])
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portfolio_holdings(portfolio_data: Any) -> list[dict[str, Any]]:
    if not isinstance(portfolio_data, dict) or not isinstance(portfolio_data.get("holdings"), list):
        raise AiResultValidationError("portfolio 缺少 holdings")
    return portfolio_data["holdings"]


def save_daily_review_ai(review: Any, markdown: Any, cfg: Any) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise AiResultValidationError("review 必须是对象")
    _, trade_date = validate_result_identity(DAILY_REVIEW_AI, review.get("trade_date"))
    generated_at = _valid_timestamp(review.get("generated_at"), "source_review_generated_at")
    cutoff = _valid_timestamp(review.get("data_cutoff"), "source_data_cutoff", allow_none=True)
    markdown_text = _nonempty_string(markdown, "markdown")
    provider, model = validate_model_info(
        _config_value(cfg, "provider", ""), _config_value(cfg, "model")
    )
    payload = _validate_payload(
        {
            "markdown": markdown_text,
            "source_review_generated_at": generated_at,
            "source_data_cutoff": cutoff,
        }
    )
    record = {
        "result_type": DAILY_REVIEW_AI,
        "trade_date": trade_date,
        "schema_version": "daily_review_ai.v1",
        "payload": payload,
        "generated_at": generated_at,
        "model_provider": provider,
        "model_name": model,
        "input_fingerprint": None,
    }
    return ai_result_store.upsert_result(review_history.resolve_review_db_path(), record)


def save_portfolio_advice(
    portfolio_data: Any,
    review: Any,
    advice_payload: Any,
    cfg: Any,
    *,
    input_fingerprint: str | None = None,
) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise AiResultValidationError("review 必须是对象")
    _, trade_date = validate_result_identity(PORTFOLIO_ADVICE, review.get("trade_date"))
    computed_fingerprint = compute_portfolio_fingerprint(_portfolio_holdings(portfolio_data))
    if input_fingerprint is None:
        fingerprint = computed_fingerprint
    elif not isinstance(input_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", input_fingerprint
    ):
        raise AiResultValidationError("input_fingerprint 格式不合法")
    elif input_fingerprint != computed_fingerprint:
        raise AiResultValidationError("生成期间持仓快照发生变化")
    else:
        fingerprint = input_fingerprint
    payload = _validate_payload(advice_payload)
    payload_trade_date = payload.get("trade_date")
    if payload_trade_date is not None and payload_trade_date != trade_date:
        raise AiResultValidationError("建议交易日与来源复盘不一致")
    generated_at = _valid_timestamp(payload.get("generated_at"), "generated_at")
    provider, model = validate_model_info(
        _config_value(cfg, "provider", ""), _config_value(cfg, "model")
    )
    record = {
        "result_type": PORTFOLIO_ADVICE,
        "trade_date": trade_date,
        "schema_version": "portfolio_advice.v1",
        "payload": payload,
        "generated_at": generated_at,
        "model_provider": provider,
        "model_name": model,
        "input_fingerprint": fingerprint,
    }
    return ai_result_store.upsert_result(review_history.resolve_review_db_path(), record)


def _cached_display_trade_date() -> str | None:
    cached = daily_review._cached_review()  # read-only; never starts aggregation
    if cached is None:
        cached, _saved_at = daily_review_cache.load_latest_review()
    if not isinstance(cached, dict):
        return None
    value = cached.get("trade_date")
    try:
        return validate_result_identity(DAILY_REVIEW_AI, value)[1]
    except AiResultValidationError:
        return None


def _safe_api_result(record: dict[str, Any], *, stale: bool) -> dict[str, Any]:
    result = {
        "result_type": record["result_type"],
        "trade_date": record["trade_date"],
        "schema_version": record["schema_version"],
        "payload": copy.deepcopy(record["payload"]),
        "generated_at": record["generated_at"],
        "model_provider": record["model_provider"],
        "model_name": record["model_name"],
        "stale": stale,
    }
    if stale:
        result["stale_message"] = PORTFOLIO_STALE_MESSAGE
    return result


def get_ai_result(
    result_type: Any,
    *,
    trade_date: Any = None,
    current_portfolio: Any = None,
) -> dict[str, Any] | None:
    if result_type not in ALLOWED_RESULT_TYPES:
        raise AiResultValidationError("不支持的 AI 结果类型")
    db_path = review_history.resolve_review_db_path()
    if trade_date is not None:
        _, exact_date = validate_result_identity(result_type, trade_date)
        record = ai_result_store.get_result(db_path, result_type, exact_date)
    else:
        cached_date = _cached_display_trade_date()
        if cached_date is not None:
            record = ai_result_store.get_result(db_path, result_type, cached_date)
        else:
            record = ai_result_store.get_latest_result(db_path, result_type)
    if record is None:
        return None
    stale = False
    if result_type == PORTFOLIO_ADVICE:
        if current_portfolio is None:
            current_portfolio = portfolio.get_portfolio()
        current_fingerprint = compute_portfolio_fingerprint(
            _portfolio_holdings(current_portfolio)
        )
        stale = current_fingerprint != record.get("input_fingerprint")
    return _safe_api_result(record, stale=stale)
