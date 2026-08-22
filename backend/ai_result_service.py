"""Validation, save, fingerprint and recovery rules for generated AI results."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping

import ai_result_store
import daily_review
import daily_review_cache
import portfolio
import position_reality_service
import review_history


DAILY_REVIEW_AI = "daily_review_ai"
PORTFOLIO_ADVICE = "portfolio_advice"
ALLOWED_RESULT_TYPES = frozenset({DAILY_REVIEW_AI, PORTFOLIO_ADVICE})
PORTFOLIO_STALE_MESSAGE = "持仓已发生变化，该建议基于生成时的持仓，可能已经过期。"
BEIJING = timezone(timedelta(hours=8))

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


class AiResultCorruptedError(RuntimeError):
    """A stored record no longer matches its result-type contract."""

    def __init__(self):
        super().__init__("已保存的 AI 结果数据损坏，无法读取")


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


def _now_beijing_timestamp() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


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
        # 接受正整数或等价正整数值 float（如 1000.0），规范化后再指纹
        if isinstance(shares, bool):
            raise AiResultValidationError("持仓数量必须是正整数")
        if isinstance(shares, int):
            if shares <= 0:
                raise AiResultValidationError("持仓数量必须是正整数")
            shares_i = shares
        elif isinstance(shares, float) and math.isfinite(shares) and shares > 0 and shares == int(shares):
            shares_i = int(shares)
        else:
            raise AiResultValidationError("持仓数量必须是正整数")
        shares = shares_i
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


def _current_portfolio_holdings_snapshot() -> dict[str, Any]:
    """Read the current holdings from the active authority without fallback."""
    authority_state, derived_positions = position_reality_service.read_holding_authority()
    if authority_state == "CANONICAL":
        return portfolio.get_portfolio_holdings_snapshot(
            derived_positions=derived_positions
        )
    return portfolio.get_portfolio_holdings_snapshot()


def _require_exact_object(
    value: Any,
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AiResultValidationError(f"{field} 必须是对象")
    allowed = required | (optional or set())
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise AiResultValidationError(f"{field} 字段不完整或包含未知字段")
    return value


def _finite_number(value: Any, field: str, *, allow_none: bool = False) -> float | int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AiResultValidationError(f"{field} 必须是有限数字")
    return value


def _nonnegative_int(value: Any, field: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AiResultValidationError(f"{field} 必须是有效整数")
    return value


def _positive_whole_number(value: Any, field: str) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or not float(value).is_integer()
    ):
        raise AiResultValidationError(f"{field} 必须是正整数值")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AiResultValidationError(f"{field} 必须是字符串数组")
    return value


def _validate_portfolio_authoritative_payload(
    payload: dict[str, Any],
    *,
    trade_date: str,
    generated_at: str,
) -> None:
    top_required = {
        "schema_version",
        "generated_at",
        "trade_date",
        "market_status",
        "portfolio_summary",
        "account_action",
        "holdings",
        "warnings",
        "data_limitations",
    }
    _require_exact_object(payload, "payload", top_required, {"account_funding", "execution_policy"})
    if payload["schema_version"] != "portfolio-advice-v0.1":
        raise AiResultValidationError("portfolio payload schema 不匹配")
    if payload["trade_date"] != trade_date:
        raise AiResultValidationError("portfolio payload trade_date 不匹配")
    if _valid_timestamp(payload["generated_at"], "generated_at") != generated_at:
        raise AiResultValidationError("portfolio payload generated_at 不匹配")
    _nonempty_string(payload["market_status"], "market_status")

    summary = _require_exact_object(
        payload["portfolio_summary"],
        "portfolio_summary",
        {"holding_count", "market_value", "cost", "pnl", "pnl_pct"},
    )
    _nonnegative_int(summary["holding_count"], "portfolio_summary.holding_count")
    _finite_number(summary["market_value"], "portfolio_summary.market_value", allow_none=True)
    _finite_number(summary["cost"], "portfolio_summary.cost")
    _finite_number(summary["pnl"], "portfolio_summary.pnl", allow_none=True)
    _finite_number(summary["pnl_pct"], "portfolio_summary.pnl_pct", allow_none=True)

    account_action = _require_exact_object(
        payload["account_action"],
        "account_action",
        {"action", "reason", "confidence"},
    )
    if account_action["action"] not in {
        "hold",
        "reduce_risk",
        "selective_add",
        "defensive",
    }:
        raise AiResultValidationError("account_action.action 非法")
    if not isinstance(account_action["reason"], str):
        raise AiResultValidationError("account_action.reason 必须是字符串")
    if account_action["confidence"] not in {"high", "medium", "low"}:
        raise AiResultValidationError("account_action.confidence 非法")

    holdings = payload["holdings"]
    if not isinstance(holdings, list):
        raise AiResultValidationError("holdings 必须是数组")
    holding_required = {
        "code",
        "name",
        "shares",
        "cost_price",
        "current_price",
        "market_value",
        "pnl_amount",
        "pnl_pct",
        "holding_weight_pct",
        "action",
        "execution_size_pct_of_holding",
        "execution_quantity",
        "trigger_conditions",
        "price_conditions",
        "execution_plan",
        "risk_conditions",
        "invalidation_conditions",
        "confidence",
        "data_limitations",
    }
    for index, holding_value in enumerate(holdings):
        prefix = f"holdings[{index}]"
        holding = _require_exact_object(
            holding_value,
            prefix,
            holding_required,
            {"estimated_amount", "account_metrics", "sellable_quantity_advisory"},
        )
        if not isinstance(holding["code"], str) or not re.fullmatch(r"\d{6}", holding["code"]):
            raise AiResultValidationError(f"{prefix}.code 非法")
        _nonempty_string(holding["name"], f"{prefix}.name")
        _positive_whole_number(holding["shares"], f"{prefix}.shares")
        _finite_number(holding["cost_price"], f"{prefix}.cost_price")
        for field in (
            "current_price",
            "market_value",
            "pnl_amount",
            "pnl_pct",
            "holding_weight_pct",
            "execution_size_pct_of_holding",
        ):
            _finite_number(holding[field], f"{prefix}.{field}", allow_none=True)
        if holding["action"] not in {"add", "hold", "reduce", "sell", "watch", "avoid"}:
            raise AiResultValidationError(f"{prefix}.action 非法")
        execution_quantity = holding["execution_quantity"]
        if execution_quantity is not None:
            _nonnegative_int(execution_quantity, f"{prefix}.execution_quantity", positive=True)
        if "sellable_quantity_advisory" in holding:
            advisory = holding["sellable_quantity_advisory"]
            if advisory is not None:
                _nonnegative_int(
                    advisory,
                    f"{prefix}.sellable_quantity_advisory",
                    positive=True,
                )
        if "estimated_amount" in holding:
            _finite_number(
                holding["estimated_amount"],
                f"{prefix}.estimated_amount",
                allow_none=True,
            )
        for field in (
            "trigger_conditions",
            "price_conditions",
            "execution_plan",
            "risk_conditions",
            "invalidation_conditions",
            "data_limitations",
        ):
            _string_list(holding[field], f"{prefix}.{field}")
        if holding["confidence"] not in {"high", "medium", "low"}:
            raise AiResultValidationError(f"{prefix}.confidence 非法")
        if "account_metrics" in holding and holding["account_metrics"] is not None:
            metrics = _require_exact_object(
                holding["account_metrics"],
                f"{prefix}.account_metrics",
                {"market_value", "account_weight_pct"},
            )
            _finite_number(
                metrics["market_value"],
                f"{prefix}.account_metrics.market_value",
                allow_none=True,
            )
            _finite_number(
                metrics["account_weight_pct"],
                f"{prefix}.account_metrics.account_weight_pct",
                allow_none=True,
            )
    if summary["holding_count"] != len(holdings):
        raise AiResultValidationError("portfolio_summary.holding_count 与 holdings 不一致")

    _string_list(payload["warnings"], "warnings")
    _string_list(payload["data_limitations"], "data_limitations")
    if "execution_policy" in payload:
        policy = _require_exact_object(
            payload["execution_policy"],
            "execution_policy",
            {"status", "reason_code"},
        )
        if policy["status"] not in {"default", "configured", "corrupted"}:
            raise AiResultValidationError("execution_policy.status 非法")
        if policy["reason_code"] is not None and not isinstance(policy["reason_code"], str):
            raise AiResultValidationError("execution_policy.reason_code 必须是字符串或 null")
        if policy["status"] == "corrupted" and policy["reason_code"] != "ACCOUNT_EXECUTION_POLICY_CORRUPTED":
            raise AiResultValidationError("execution_policy.reason_code 与 corrupted 状态不匹配")
        if policy["status"] != "corrupted" and policy["reason_code"] is not None:
            raise AiResultValidationError("execution_policy.reason_code 仅 corrupted 状态可用")
    if "account_funding" in payload and payload["account_funding"] is not None:
        funding = _require_exact_object(
            payload["account_funding"],
            "account_funding",
            {
                "configured",
                "total_assets",
                "available_cash",
                "available_cash_pct",
                "updated_at",
                "tracked_stock_market_value",
                "tracked_stock_weight_pct",
                "quote_coverage",
            },
            {"status", "reason_code"},
        )
        if not isinstance(funding["configured"], bool):
            raise AiResultValidationError("account_funding.configured 必须是布尔值")
        if "status" in funding and funding["status"] not in {"valid", "not_configured", "corrupted"}:
            raise AiResultValidationError("account_funding.status 非法")
        if "reason_code" in funding and funding["reason_code"] is not None and not isinstance(funding["reason_code"], str):
            raise AiResultValidationError("account_funding.reason_code 必须是字符串或 null")
        for field in (
            "total_assets",
            "available_cash",
            "available_cash_pct",
            "tracked_stock_market_value",
            "tracked_stock_weight_pct",
        ):
            _finite_number(funding[field], f"account_funding.{field}", allow_none=True)
        if funding["updated_at"] is not None:
            _valid_timestamp(funding["updated_at"], "account_funding.updated_at")
        coverage = _require_exact_object(
            funding["quote_coverage"],
            "account_funding.quote_coverage",
            {"valid_holdings", "total_holdings", "complete"},
        )
        _nonnegative_int(coverage["valid_holdings"], "quote_coverage.valid_holdings")
        _nonnegative_int(coverage["total_holdings"], "quote_coverage.total_holdings")
        if not isinstance(coverage["complete"], bool):
            raise AiResultValidationError("quote_coverage.complete 必须是布尔值")


def save_daily_review_ai(
    review: Any,
    markdown: Any,
    cfg: Any,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise AiResultValidationError("review 必须是对象")
    _, trade_date = validate_result_identity(DAILY_REVIEW_AI, review.get("trade_date"))
    source_generated_at = _valid_timestamp(review.get("generated_at"), "source_review_generated_at")
    cutoff = _valid_timestamp(review.get("data_cutoff"), "source_data_cutoff", allow_none=True)
    generated_at = _now_beijing_timestamp()
    markdown_text = _nonempty_string(markdown, "markdown")
    provider, model = validate_model_info(
        _config_value(cfg, "provider", ""), _config_value(cfg, "model")
    )
    payload = _validate_payload(
        {
            "markdown": markdown_text,
            "source_review_generated_at": source_generated_at,
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
    return ai_result_store.upsert_result(
        review_history.resolve_review_db_path(),
        record,
        should_cancel=should_cancel,
    )


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
    prepared_fingerprint = compute_portfolio_fingerprint(_portfolio_holdings(portfolio_data))
    if input_fingerprint is None:
        fingerprint = prepared_fingerprint
    elif not isinstance(input_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", input_fingerprint
    ):
        raise AiResultValidationError("input_fingerprint 格式不合法")
    elif input_fingerprint != prepared_fingerprint:
        raise AiResultValidationError("生成期间持仓快照发生变化")
    else:
        fingerprint = input_fingerprint

    # Canonical holdings may change while the model is running. Re-read the
    # active authority immediately before validation/upsert so an old Advice
    # can never be persisted as current after a ledger mutation. Legacy keeps
    # its established caller-provided snapshot contract.
    authority_state, derived_positions = position_reality_service.read_holding_authority()
    if authority_state == "CANONICAL":
        current_portfolio = portfolio.get_portfolio_holdings_snapshot(
            derived_positions=derived_positions
        )
        current_fingerprint = compute_portfolio_fingerprint(
            _portfolio_holdings(current_portfolio)
        )
        if current_fingerprint != fingerprint:
            raise AiResultValidationError("生成期间持仓快照发生变化")
        fingerprint = current_fingerprint
    payload = _validate_payload(advice_payload)
    payload_trade_date = payload.get("trade_date")
    if payload_trade_date is not None and payload_trade_date != trade_date:
        raise AiResultValidationError("建议交易日与来源复盘不一致")
    generated_at = _valid_timestamp(payload.get("generated_at"), "generated_at")
    _validate_portfolio_authoritative_payload(
        payload,
        trade_date=trade_date,
        generated_at=generated_at,
    )
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


def _validate_restored_record(record: Any, expected_type: str) -> None:
    """Validate persisted data without exposing the damaged field or value."""
    try:
        if not isinstance(record, dict) or record.get("result_type") != expected_type:
            raise AiResultValidationError("result_type mismatch")
        expected_schema = {
            DAILY_REVIEW_AI: "daily_review_ai.v1",
            PORTFOLIO_ADVICE: "portfolio_advice.v1",
        }[expected_type]
        if record.get("schema_version") != expected_schema:
            raise AiResultValidationError("schema_version mismatch")
        _, trade_date = validate_result_identity(expected_type, record.get("trade_date"))
        generated_at = _valid_timestamp(record.get("generated_at"), "generated_at")
        _nonempty_string(record.get("model_provider"), "model_provider")
        _nonempty_string(record.get("model_name"), "model_name")
        payload = _validate_payload(record.get("payload"))

        if expected_type == DAILY_REVIEW_AI:
            if set(payload) != {
                "markdown",
                "source_review_generated_at",
                "source_data_cutoff",
            }:
                raise AiResultValidationError("daily review payload fields mismatch")
            _nonempty_string(payload.get("markdown"), "markdown")
            _valid_timestamp(
                payload.get("source_review_generated_at"),
                "source_review_generated_at",
            )
            _valid_timestamp(
                payload.get("source_data_cutoff"),
                "source_data_cutoff",
                allow_none=True,
            )
            if record.get("input_fingerprint") is not None:
                raise AiResultValidationError("daily review metadata mismatch")
            return

        _validate_portfolio_authoritative_payload(
            payload,
            trade_date=trade_date,
            generated_at=generated_at,
        )
        fingerprint = record.get("input_fingerprint")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise AiResultValidationError("portfolio fingerprint mismatch")
    except (AiResultValidationError, KeyError, TypeError, ValueError):
        raise AiResultCorruptedError() from None


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
    _validate_restored_record(record, result_type)
    stale = False
    if result_type == PORTFOLIO_ADVICE:
        if current_portfolio is None:
            current_portfolio = _current_portfolio_holdings_snapshot()
        current_fingerprint = compute_portfolio_fingerprint(
            _portfolio_holdings(current_portfolio)
        )
        stale = current_fingerprint != record.get("input_fingerprint")
    return _safe_api_result(record, stale=stale)
