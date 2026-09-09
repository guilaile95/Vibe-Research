"""Read-only current portfolio risk context.

This module composes existing Position Reality, Portfolio, Account Reality,
Candidate Risk Budget, and Eastmoney current-industry facts.  It deliberately
does not create a new authority, risk score, recommendation, NAV history, or
stress model.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

import account_reality_service
import candidate_opportunity_projection as candidate_projection
import position_reality_service
import sector_industry_context


SCHEMA_VERSION = "portfolio_risk_context.v0.1"
CLASSIFICATION_PROVIDER = "EASTMONEY_INDUSTRY_CURRENT"
MEMBERSHIP_SEMANTICS = "CURRENT_MEMBERSHIP_SNAPSHOT"
UNKNOWN_INDUSTRY = "UNKNOWN_INDUSTRY"
DRAWDOWN_STATUS = "UNAVAILABLE_NO_OFFICIAL_NAV_HISTORY"
STRESS_TEST_STATUS = "DEFERRED_NO_ACCEPTED_SCENARIO_CONTRACT"

PortfolioReader = Callable[[], dict[str, Any]]
AccountReader = Callable[[], dict[str, Any]]
IndustryReader = Callable[[], dict[str, str]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _nonnegative_number(value: Any) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number >= 0 else None


def _positive_number(value: Any) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return _round(numerator / denominator * 100)


def _fact_status(fact: Mapping[str, Any] | None, *, nonnegative: bool) -> str:
    if not isinstance(fact, Mapping):
        return "UNAVAILABLE"
    value = _nonnegative_number(fact.get("value")) if nonnegative else _positive_number(fact.get("value"))
    if fact.get("authority_state") == "CANONICAL" and value is not None:
        return "CANONICAL"
    if fact.get("status") in {"STALE", "CORRUPTED", "UNKNOWN"}:
        return str(fact["status"])
    return "NONCANONICAL"


def _base_writes() -> dict[str, int]:
    return {
        "formal_state": 0,
        "account": 0,
        "position": 0,
        "trade": 0,
        "portfolio": 0,
    }


def _empty_concentration(reason_code: str, status: str = "UNKNOWN") -> dict[str, Any]:
    return {
        "status": status,
        "evaluable": False,
        "reason_code": reason_code,
        "semantics": "TRANSPARENT_ONLY",
        "denominator_market_value": 0.0,
        "top1_pct": None,
        "top3_pct": None,
        "top5_pct": None,
        "holdings_ranked": [],
        "limitations": ["只有完整可靠行情且 tracked stock market value > 0 时才计算集中度。"],
    }


def _position_unavailable(fetched_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "UNAVAILABLE",
        "as_of": fetched_at,
        "fetched_at": fetched_at,
        "holding_count": 0,
        "position_authority_state": "UNAVAILABLE",
        "securities": [],
        "position_context": {
            "status": "UNAVAILABLE",
            "authority_state": "UNAVAILABLE",
            "holding_count": 0,
            "reason_code": "POSITION_REALITY_UNAVAILABLE",
        },
        "quote_coverage": {
            "status": "UNAVAILABLE",
            "usable_holdings": 0,
            "total_holdings": 0,
            "complete": False,
            "usable_market_value": None,
        },
        "account_fact_status": {
            "status": "UNAVAILABLE",
            "total_assets": {"status": "UNAVAILABLE", "value": None},
            "cash": {"status": "UNAVAILABLE", "value": None},
            "confirmation_id": None,
            "reason_code": "POSITION_REALITY_UNAVAILABLE",
        },
        "security_concentration": _empty_concentration("POSITION_REALITY_UNAVAILABLE"),
        "account_exposure": {
            "status": "UNAVAILABLE",
            "denominator": {
                "value": None,
                "source": "CONFIRMED_CURRENT_TOTAL_ASSETS_ONLY",
                "authority_state": "UNAVAILABLE",
                "semantics": "CURRENT_MIXED_TIME_NOT_OFFICIAL_SETTLED_NAV",
            },
            "tracked_stock_market_value": None,
            "tracked_stock_account_pct": None,
            "limitations": ["Position Reality 不可用，未读取或推断任何持仓。"],
        },
        "cash_buffer": {
            "status": "UNAVAILABLE",
            "value": None,
            "ratio_pct": None,
            "reason_code": "POSITION_REALITY_UNAVAILABLE",
            "semantics": "SAME_CONFIRMATION_CURRENT_FACTS_ONLY",
        },
        "industry_exposure": {
            "status": "UNAVAILABLE",
            "provider": CLASSIFICATION_PROVIDER,
            "membership_semantics": MEMBERSHIP_SEMANTICS,
            "denominator_market_value": None,
            "items": [],
            "reason_code": "POSITION_REALITY_UNAVAILABLE",
        },
        "industry_coverage": {
            "status": "UNAVAILABLE",
            "total_holdings": 0,
            "quote_usable_holdings": 0,
            "industry_classified_holdings": 0,
            "unknown_industry_holdings": 0,
            "coverage_ratio": None,
            "provider": CLASSIFICATION_PROVIDER,
            "membership_semantics": MEMBERSHIP_SEMANTICS,
            "reason_code": "POSITION_REALITY_UNAVAILABLE",
        },
        "single_trade_risk_budget_capability": _risk_capability(),
        "portfolio_aggregated_risk_budget": _portfolio_risk_not_evaluated(),
        "drawdown": _drawdown_gap(),
        "stress_test": _stress_gap(),
        "limitations": [
            "Position Reality 当前不可用，组合事实未形成。",
            "当前结果不是风险评分、投资建议或正式 NAV。",
        ],
        "writes": _base_writes(),
    }


def _risk_capability() -> dict[str, Any]:
    rates = dict(candidate_projection.RISK_BUDGET_RATE)
    return {
        "status": "IMPLEMENTED_IN_PRE_ENTRY_CANDIDATE_FLOW",
        "policy_version": candidate_projection.RISK_POLICY_VERSION,
        "rates": rates,
        "rates_pct": {key: _round(value * 100) for key, value in rates.items()},
        "source": "candidate_opportunity_projection",
        "semantics": "SINGLE_TRADE_RISK_BUDGET",
    }


def _portfolio_risk_not_evaluated() -> dict[str, Any]:
    return {
        "status": "NOT_EVALUATED",
        "reason_code": "UNIVERSAL_ACTIVE_HOLDING_RISK_INPUT_NOT_AVAILABLE",
        "semantics": "NO_PORTFOLIO_AGGREGATED_RISK_BUDGET",
    }


def _drawdown_gap() -> dict[str, Any]:
    return {
        "status": DRAWDOWN_STATUS,
        "nav_authority": "SETTLED_NAV_CANDIDATE",
        "nav_canonical": False,
        "message": "当前没有足够的正式 NAV 历史，不能可靠计算账户回撤。",
    }


def _stress_gap() -> dict[str, Any]:
    return {
        "status": STRESS_TEST_STATUS,
        "message": "尚未定义经过确认的组合压力情景，因此不输出压力损失估计。",
    }


def _account_sections(account: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float | None, float | None]:
    total_section = account.get("account_total_assets") if isinstance(account, Mapping) else None
    cash_section = account.get("cash") if isinstance(account, Mapping) else None
    total_fact = total_section.get("current_fact") if isinstance(total_section, Mapping) else None
    cash_fact = cash_section.get("current_fact") if isinstance(cash_section, Mapping) else None
    raw_total_value = _positive_number(total_fact.get("value")) if isinstance(total_fact, Mapping) else None
    raw_cash_value = _nonnegative_number(cash_fact.get("value")) if isinstance(cash_fact, Mapping) else None
    total_status = _fact_status(total_fact, nonnegative=False)
    cash_status = _fact_status(cash_fact, nonnegative=True)
    total_value = raw_total_value if total_status == "CANONICAL" else None
    cash_value = raw_cash_value if cash_status == "CANONICAL" else None
    total = {
        "status": total_status,
        "value": total_value if total_status == "CANONICAL" else None,
        "confirmation_id": total_fact.get("confirmation_id") if isinstance(total_fact, Mapping) else None,
        "reason_code": total_fact.get("reason_code") if isinstance(total_fact, Mapping) else "TOTAL_ASSETS_UNAVAILABLE",
    }
    cash = {
        "status": cash_status,
        "value": cash_value if cash_status == "CANONICAL" else None,
        "confirmation_id": cash_fact.get("confirmation_id") if isinstance(cash_fact, Mapping) else None,
        "reason_code": cash_fact.get("reason_code") if isinstance(cash_fact, Mapping) else "CASH_UNAVAILABLE",
    }
    if total_status == "CANONICAL" and cash_status == "CANONICAL":
        fact_status = "CANONICAL"
    elif total_status != "UNAVAILABLE" or cash_status != "UNAVAILABLE":
        fact_status = "PARTIAL"
    else:
        fact_status = "UNAVAILABLE"
    account_facts = {
        "status": fact_status,
        "total_assets": total,
        "cash": cash,
        "aggregate_canonical": bool(account.get("canonical")) if isinstance(account, Mapping) else False,
        "confirmation_id": total.get("confirmation_id") if total.get("confirmation_id") == cash.get("confirmation_id") else None,
    }
    return account_facts, total, cash, total_value, cash_value


def _build_concentration(securities: list[dict[str, Any]], *, total_holdings: int, complete: bool, denominator: float) -> dict[str, Any]:
    ranked = sorted(
        [item for item in securities if item["market_value"] is not None],
        key=lambda item: (-float(item["market_value"]), item["code"]),
    )
    if not total_holdings:
        return _empty_concentration("NO_ACTIVE_HOLDINGS")
    if not complete:
        return {
            **_empty_concentration("NOT_FULLY_EVALUABLE", status="PARTIAL"),
            "denominator_market_value": _round(denominator),
            "holdings_ranked": [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "market_value": item["market_value"],
                    "weight_in_tracked_stock_pct": None,
                }
                for item in ranked
            ],
        }
    if denominator <= 0:
        return {
            **_empty_concentration("ZERO_TRACKED_MARKET_VALUE"),
            "holdings_ranked": [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "market_value": item["market_value"],
                    "weight_in_tracked_stock_pct": None,
                }
                for item in ranked
            ],
        }
    for item in ranked:
        item["weight_in_tracked_stock_pct"] = _pct(float(item["market_value"]), denominator)
    return {
        "status": "COMPLETE",
        "evaluable": True,
        "reason_code": None,
        "semantics": "TRANSPARENT_ONLY",
        "denominator_market_value": _round(denominator),
        "top1_pct": _pct(sum(float(item["market_value"]) for item in ranked[:1]), denominator),
        "top3_pct": _pct(sum(float(item["market_value"]) for item in ranked[:3]), denominator),
        "top5_pct": _pct(sum(float(item["market_value"]) for item in ranked[:5]), denominator),
        "holdings_ranked": ranked,
        "limitations": ["集中度仅为 tracked stock market value 的透明比例，不生成风险等级或建议。"],
    }


def _build_industry(
    securities: list[dict[str, Any]],
    *,
    total_holdings: int,
    complete: bool,
    industry_reader: IndustryReader,
) -> tuple[dict[str, Any], dict[str, Any]]:
    usable = [item for item in securities if item["market_value"] is not None]
    denominator = sum(float(item["market_value"]) for item in usable)
    base_coverage = {
        "total_holdings": total_holdings,
        "quote_usable_holdings": len(usable),
        "industry_classified_holdings": 0,
        "unknown_industry_holdings": 0,
        "coverage_ratio": None,
        "provider": CLASSIFICATION_PROVIDER,
        "membership_semantics": MEMBERSHIP_SEMANTICS,
        "reason_code": None,
    }
    if not total_holdings:
        return (
            {
                "status": "EMPTY",
                "provider": CLASSIFICATION_PROVIDER,
                "membership_semantics": MEMBERSHIP_SEMANTICS,
                "denominator_market_value": 0.0,
                "items": [],
                "reason_code": "NO_ACTIVE_HOLDINGS",
            },
            {**base_coverage, "status": "EMPTY", "reason_code": "NO_ACTIVE_HOLDINGS"},
        )
    if not usable:
        return (
            {
                "status": "UNAVAILABLE",
                "provider": CLASSIFICATION_PROVIDER,
                "membership_semantics": MEMBERSHIP_SEMANTICS,
                "denominator_market_value": None,
                "items": [],
                "reason_code": "NO_QUOTE_USABLE_HOLDINGS",
            },
            {**base_coverage, "status": "UNAVAILABLE", "reason_code": "NO_QUOTE_USABLE_HOLDINGS"},
        )
    try:
        classification = industry_reader()
        if not isinstance(classification, Mapping):
            raise TypeError("invalid industry classification")
    except Exception:
        for item in usable:
            item["industry"] = None
            item["industry_status"] = "UNAVAILABLE"
        return (
            {
                "status": "UNAVAILABLE",
                "provider": CLASSIFICATION_PROVIDER,
                "membership_semantics": MEMBERSHIP_SEMANTICS,
                "denominator_market_value": _round(denominator),
                "items": [],
                "reason_code": "EASTMONEY_CURRENT_INDUSTRY_UNAVAILABLE",
            },
            {
                **base_coverage,
                "status": "UNAVAILABLE",
                "unknown_industry_holdings": len(usable),
                "reason_code": "EASTMONEY_CURRENT_INDUSTRY_UNAVAILABLE",
            },
        )

    groups: dict[str, list[dict[str, Any]]] = {}
    classified_count = 0
    unknown_count = 0
    for item in usable:
        raw_industry = classification.get(item["code"])
        industry = str(raw_industry).strip() if isinstance(raw_industry, str) and raw_industry.strip() else UNKNOWN_INDUSTRY
        # The reused sector helper names a missing current field ``UNKNOWN``;
        # this read model uses the explicit bucket required by its contract.
        if industry == "UNKNOWN":
            industry = UNKNOWN_INDUSTRY
        if industry == UNKNOWN_INDUSTRY:
            unknown_count += 1
            item["industry_status"] = "UNKNOWN"
        else:
            classified_count += 1
            item["industry_status"] = "CLASSIFIED"
        item["industry"] = industry
        groups.setdefault(industry, []).append(item)
    coverage_ratio = classified_count / len(usable) if usable else None
    industry_items = []
    for industry, members in sorted(groups.items(), key=lambda pair: (-sum(float(x["market_value"]) for x in pair[1]), pair[0])):
        market_value = sum(float(member["market_value"]) for member in members)
        industry_items.append(
            {
                "industry": industry,
                "securities": [member["code"] for member in sorted(members, key=lambda x: x["code"])],
                "market_value": _round(market_value),
                "weight_in_tracked_stock_pct": _pct(market_value, denominator),
                "member_count": len(members),
            }
        )
    status = "PARTIAL" if (not complete or unknown_count) else "AVAILABLE"
    coverage_status = "PARTIAL" if (not complete or unknown_count) else "AVAILABLE"
    return (
        {
            "status": status,
            "provider": CLASSIFICATION_PROVIDER,
            "membership_semantics": MEMBERSHIP_SEMANTICS,
            "denominator_market_value": _round(denominator),
            "items": industry_items,
            "reason_code": "UNKNOWN_INDUSTRY_PRESENT" if unknown_count else None,
            "limitations": [
                "行业为 Eastmoney 当前分类，仅表示当前快照 membership。",
                "缺失分类保留为 UNKNOWN_INDUSTRY，不按已分类子集重新归一化。",
            ],
        },
        {
            **base_coverage,
            "status": coverage_status,
            "industry_classified_holdings": classified_count,
            "unknown_industry_holdings": unknown_count,
            "coverage_ratio": _round(coverage_ratio),
            "reason_code": "UNKNOWN_INDUSTRY_PRESENT" if unknown_count else None,
        },
    )


def build_portfolio_risk_context(
    *,
    portfolio_reader: PortfolioReader | None = None,
    account_reader: AccountReader | None = None,
    industry_reader: IndustryReader | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Build the bounded read model without performing any writes."""
    timestamp = fetched_at or _utc_now()
    read_portfolio = portfolio_reader or (lambda: position_reality_service.read_portfolio_authority(include_metadata=True))
    read_account = account_reader or account_reality_service.get_account_reality
    read_industry = industry_reader or sector_industry_context.read_current_industry_classification

    try:
        portfolio = read_portfolio()
    except Exception:
        return _position_unavailable(timestamp)
    if not isinstance(portfolio, Mapping):
        return _position_unavailable(timestamp)

    raw_holdings = portfolio.get("holdings")
    holdings = raw_holdings if isinstance(raw_holdings, list) else []
    authority_state = str(portfolio.get("authority_state") or "UNKNOWN")
    securities: list[dict[str, Any]] = []
    for raw in holdings:
        if not isinstance(raw, Mapping):
            continue
        code = str(raw.get("code") or "").strip()
        if not code:
            continue
        market_value = _nonnegative_number(raw.get("market_value"))
        securities.append(
            {
                "code": code,
                "name": str(raw.get("name") or code),
                "shares": raw.get("shares"),
                "market_value": _round(market_value),
                "quote_status": "AVAILABLE" if market_value is not None else "UNAVAILABLE",
                "weight_in_tracked_stock_pct": None,
                "account_exposure_pct": None,
                "industry": None,
                "industry_status": "PENDING",
            }
        )
    total_holdings = len(securities)
    usable = [item for item in securities if item["market_value"] is not None]
    usable_count = len(usable)
    complete = total_holdings > 0 and usable_count == total_holdings
    quote_status = "EMPTY" if total_holdings == 0 else "COMPLETE" if complete else "PARTIAL" if usable_count else "UNAVAILABLE"
    tracked_market_value = sum(float(item["market_value"]) for item in usable)
    quote_coverage = {
        "status": quote_status,
        "usable_holdings": usable_count,
        "total_holdings": total_holdings,
        "complete": complete,
        "usable_market_value": _round(tracked_market_value) if usable else None,
        "source": "CURRENT_PORTFOLIO_QUOTE_COVERAGE",
    }

    try:
        account = read_account()
        if not isinstance(account, Mapping):
            raise TypeError("invalid account reality")
    except Exception:
        account = None
    account_facts, total_fact, cash_fact, total_assets, cash_value = _account_sections(account)
    account_exposure_status = "UNAVAILABLE" if total_assets is None else "PARTIAL" if not complete else "AVAILABLE"
    for item in usable:
        item["account_exposure_pct"] = _pct(float(item["market_value"]), total_assets)
        if complete and tracked_market_value > 0:
            item["weight_in_tracked_stock_pct"] = _pct(float(item["market_value"]), tracked_market_value)
    account_exposure = {
        "status": account_exposure_status,
        "denominator": {
            "value": _round(total_assets),
            "source": "CONFIRMED_CURRENT_TOTAL_ASSETS_ONLY",
            "authority_state": total_fact["status"],
            "semantics": "CURRENT_MIXED_TIME_NOT_OFFICIAL_SETTLED_NAV",
        },
        "tracked_stock_market_value": _round(tracked_market_value) if usable else 0.0 if not total_holdings else None,
        "tracked_stock_account_pct": _pct(tracked_market_value, total_assets),
        "known_security_count": usable_count,
        "limitations": [
            "账户分母只使用 confirmed current Total Assets；不得解读为 Official Settled NAV exposure。",
            *(["行情不完整，未将已知股票重新归一化为完整组合。"] if not complete and total_holdings else []),
        ],
    }

    same_confirmation = (
        total_fact["status"] == "CANONICAL"
        and cash_fact["status"] == "CANONICAL"
        and isinstance(total_fact.get("confirmation_id"), str)
        and bool(total_fact.get("confirmation_id"))
        and total_fact.get("confirmation_id") == cash_fact.get("confirmation_id")
        and total_assets is not None
        and cash_value is not None
    )
    cash_buffer = {
        "status": "AVAILABLE" if same_confirmation else "UNAVAILABLE",
        "value": _round(cash_value) if same_confirmation else None,
        "ratio_pct": _pct(cash_value, total_assets) if same_confirmation else None,
        "confirmation_id": cash_fact.get("confirmation_id") if same_confirmation else None,
        "reason_code": None if same_confirmation else "CASH_TOTAL_ASSETS_CONFIRMATION_NOT_MATCHED",
        "semantics": "SAME_CONFIRMATION_CURRENT_FACTS_ONLY",
    }
    industry_exposure, industry_coverage = _build_industry(
        securities,
        total_holdings=total_holdings,
        complete=complete,
        industry_reader=read_industry,
    )
    concentration = _build_concentration(
        securities,
        total_holdings=total_holdings,
        complete=complete,
        denominator=tracked_market_value,
    )

    if authority_state == "CANONICAL":
        position_status = "NORMAL"
    elif authority_state == "LEGACY":
        position_status = "LEGACY"
    else:
        position_status = authority_state
    position_context = {
        "status": position_status,
        "authority_state": authority_state,
        "holding_count": total_holdings,
        "source": "POSITION_REALITY_AND_CURRENT_PORTFOLIO",
        "limitations": ["持仓 universe 只来自当前 Position/Portfolio authority。"],
    }

    partial_inputs = (
        quote_status in {"PARTIAL", "UNAVAILABLE"}
        or account_facts["status"] != "CANONICAL"
        or authority_state not in {"CANONICAL", "LEGACY"}
        or cash_buffer["status"] != "AVAILABLE"
        or industry_exposure["status"] == "UNAVAILABLE"
    )
    overall_status = "PARTIAL" if partial_inputs else "NORMAL"
    limitations = [
        "当前组合风险概览只表达透明事实，不生成黑箱风险评分或投资建议。",
        "当前行业是 Eastmoney 当前快照；历史 membership validity 未证明。",
        "正式账户回撤与组合压力测试在本 v0.1 明确不可用/延期。",
    ]
    if concentration["status"] == "PARTIAL":
        limitations.append("行情覆盖不完整，集中度标记为 NOT_FULLY_EVALUABLE。")
    if industry_exposure["status"] == "UNAVAILABLE":
        limitations.append("行业数据源失败时仅降级行业区块，其他组合事实仍保留。")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall_status,
        "as_of": timestamp,
        "fetched_at": timestamp,
        "holding_count": total_holdings,
        "position_authority_state": authority_state,
        "securities": securities,
        "position_context": position_context,
        "quote_coverage": quote_coverage,
        "account_fact_status": account_facts,
        "security_concentration": concentration,
        "account_exposure": account_exposure,
        "cash_buffer": cash_buffer,
        "industry_exposure": industry_exposure,
        "industry_coverage": industry_coverage,
        "single_trade_risk_budget_capability": _risk_capability(),
        "portfolio_aggregated_risk_budget": _portfolio_risk_not_evaluated(),
        "drawdown": _drawdown_gap(),
        "stress_test": _stress_gap(),
        "limitations": limitations,
        "writes": _base_writes(),
    }


__all__ = [
    "CLASSIFICATION_PROVIDER",
    "DRAWDOWN_STATUS",
    "MEMBERSHIP_SEMANTICS",
    "SCHEMA_VERSION",
    "STRESS_TEST_STATUS",
    "UNKNOWN_INDUSTRY",
    "build_portfolio_risk_context",
]
