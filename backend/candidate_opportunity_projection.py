"""Deterministic buy-side projection for a PRE-ENTRY Campaign.

The projection consumes the existing Decision draft views plus named runtime
authorities.  It does not persist a second Candidate, Thesis, Decision, or
portfolio model.  Incomplete valuation/account/position facts stay explicit
and narrow the existing Frozen Decision Action Envelope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

from frozen_decision_store import NEXT_BEST_ACTIONS


AUTHORITY_REF = "candidate_opportunity:projection:v0.1"
CAPITAL_ALLOCATION_AUTHORITY_REF = "portfolio_capital_allocation:projection:v0.1"
CAPITAL_ALLOCATION_SCHEMA_VERSION = "portfolio_capital_context.v0.1"
RISK_POLICY_VERSION = "candidate-risk-budget.v0.1"
OPPORTUNITY_POLICY_VERSION = "candidate-opportunity.v0.1"
DECISION_POLICY_VERSION = "candidate-decision.v0.1"
ANALYSIS_POLICY_VERSION = "candidate-analysis.v0.1"

BUY_ACTIONS = frozenset({"BUY NOW", "BUY SMALL", "SCALE IN"})
RISK_BUDGET_RATE = {"SHORT": 0.0075, "SWING": 0.01, "MEDIUM": 0.0125}
RISK_REWARD_GATE = {"SHORT": 1.5, "SWING": 2.0, "MEDIUM": 2.5}
CONFIDENCE_VALUES = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")
_CONFIDENCE_RANK = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
_EVALUATION_RANK = {"EVALUATED": 0, "UNKNOWN": 1, "NOT_EVALUATED": 2, "ERROR": 3}


@dataclass(frozen=True)
class CandidateOpportunityProjection:
    constraint_evaluation: str
    asset_view: Mapping[str, Any]
    trade_view: Mapping[str, Any]
    portfolio_view: Mapping[str, Any]
    next_best_action: str
    action_envelope: Mapping[str, Any]
    authority_fact: Mapping[str, Any]
    authority_refs: tuple[str, ...]


def _finite_positive(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _strings(value: object) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    result = [_text(item) for item in value]
    return [item for item in result if item is not None] if all(result) else None


def _source_time(value: object, as_of: datetime) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        if len(text) == 10:
            parsed_date = date.fromisoformat(text)
            return text if parsed_date <= as_of.date() else None
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return text if parsed.astimezone(timezone.utc) <= as_of else None


def _price_range(value: object) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    low = _finite_positive(value.get("low"))
    high = _finite_positive(value.get("high"))
    if low is None or high is None or high < low:
        return None
    return {"low": low, "high": high}


def _scenario(value: object, as_of: datetime) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    assumptions = _strings(value.get("assumptions"))
    inputs = value.get("inputs")
    source = _text(value.get("source"))
    data_at = _source_time(value.get("data_at"), as_of)
    price_range = _price_range(value.get("price_range"))
    horizon = _text(value.get("horizon"))
    changes = _strings(value.get("change_conditions"))
    if (
        assumptions is None
        or not isinstance(inputs, list)
        or not inputs
        or source is None
        or data_at is None
        or price_range is None
        or horizon is None
        or changes is None
    ):
        return None
    normalized_inputs: list[dict[str, Any]] = []
    for item in inputs:
        if not isinstance(item, Mapping):
            return None
        metric = _text(item.get("metric"))
        period = _text(item.get("period"))
        raw_value = item.get("value")
        if metric is None or period is None or isinstance(raw_value, (dict, list, bool)) or raw_value is None:
            return None
        if isinstance(raw_value, float) and not math.isfinite(raw_value):
            return None
        if not isinstance(raw_value, (str, int, float)):
            return None
        normalized_inputs.append({"metric": metric, "value": raw_value, "period": period})
    return {
        "assumptions": assumptions,
        "inputs": normalized_inputs,
        "source": source,
        "data_at": data_at,
        "price_range": price_range,
        "horizon": horizon,
        "change_conditions": changes,
    }


def _valuation(asset_view: Mapping[str, Any], as_of: datetime) -> tuple[str, dict[str, Any], list[str]]:
    raw = asset_view.get("candidate_valuation")
    if not isinstance(raw, Mapping):
        return "UNKNOWN", {}, ["CANDIDATE_VALUATION_MISSING"]
    cases: dict[str, Any] = {}
    reasons: list[str] = []
    for name in ("bear", "base", "bull"):
        case = _scenario(raw.get(name), as_of)
        if case is None:
            reasons.append(f"{name.upper()}_CASE_INCOMPLETE")
        else:
            cases[name] = case
    return ("READY", cases, []) if not reasons else ("UNKNOWN", {}, reasons)


def _position_state(
    snapshot: Mapping[str, Any] | None,
    security_code: str,
) -> tuple[str, str, list[str], list[dict[str, Any]]]:
    if snapshot is None:
        return "UNKNOWN", "NOT_EVALUATED", ["POSITION_AUTHORITY_NOT_WIRED"], []
    if snapshot.get("_candidate_read_error") is True:
        return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_ERROR"], []
    authority_state = snapshot.get("authority_state")
    if authority_state == "LEGACY":
        return "UNKNOWN", "UNKNOWN", ["POSITION_AUTHORITY_LEGACY"], []
    if authority_state != "CANONICAL":
        return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"], []
    holdings = snapshot.get("holdings")
    if not isinstance(holdings, list):
        return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"], []
    normalized: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    candidate_held = False
    for holding in holdings:
        if not isinstance(holding, Mapping) or not isinstance(holding.get("code"), str):
            return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"], []
        code = holding["code"]
        if code in seen_codes:
            return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"], []
        seen_codes.add(code)
        shares = _finite_nonnegative(holding.get("shares"))
        if shares is None:
            return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"], []
        if shares <= 0:
            continue
        normalized_holding: dict[str, Any] = {"code": code, "shares": shares}
        if "cost" in holding:
            cost = _finite_nonnegative(holding.get("cost"))
            if cost is None:
                return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"], []
            normalized_holding["cost"] = cost
        if "cost_known" in holding:
            if not isinstance(holding.get("cost_known"), bool):
                return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"], []
            normalized_holding["cost_known"] = holding["cost_known"]
        normalized.append(normalized_holding)
        candidate_held = candidate_held or code == security_code
    normalized.sort(key=lambda item: item["code"])
    if candidate_held:
        return "HELD", "EVALUATED", ["SECURITY_ALREADY_HELD"], normalized
    return "NOT_HELD", "EVALUATED", [], normalized


def _account_state(account: Mapping[str, Any] | None) -> tuple[str, str, float | None, float | None, list[str]]:
    if account is None:
        return "UNKNOWN", "NOT_EVALUATED", None, None, ["ACCOUNT_AUTHORITY_NOT_WIRED"]
    if account.get("_candidate_read_error") is True:
        return "UNKNOWN", "ERROR", None, None, ["ACCOUNT_AUTHORITY_ERROR"]
    cash = account.get("cash")
    current = cash.get("current_fact") if isinstance(cash, Mapping) else None
    nav = _finite_positive(account.get("settled_nav"))
    cash_value = _finite_nonnegative(current.get("value")) if isinstance(current, Mapping) else None
    if (
        not isinstance(current, Mapping)
        or current.get("status") != "AVAILABLE"
        or nav is None
        or cash_value is None
    ):
        return "UNKNOWN", "UNKNOWN", None, None, ["ACCOUNT_CAPACITY_UNKNOWN"]
    return "USABLE", "EVALUATED", nav, cash_value, []


def _confidence(asset_view: Mapping[str, Any]) -> tuple[dict[str, str], str, list[str]]:
    values = {
        key: asset_view.get(key) if asset_view.get(key) in CONFIDENCE_VALUES else "UNKNOWN"
        for key in (
            "data_quality",
            "evidence_confidence",
            "inference_confidence",
            "decision_confidence",
        )
    }
    if "UNKNOWN" in values.values():
        return values, "UNKNOWN", ["CONFIDENCE_INCOMPLETE"]
    ceiling = min(values.values(), key=lambda item: _CONFIDENCE_RANK[item])
    return values, ceiling, []


def _evidence_summary(value: object) -> tuple[dict[str, Any], str, list[str], tuple[str, ...]]:
    if not isinstance(value, list):
        return (
            {"status": "UNKNOWN", "total_count": 0},
            "ERROR",
            ["FORMAL_EVIDENCE_INVALID"],
            (),
        )
    evidence_by_id: dict[str, dict[str, Any]] = {}
    provenance_by_id: dict[str, list[str]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            return ({"status": "UNKNOWN", "total_count": 0}, "ERROR", ["FORMAL_EVIDENCE_INVALID"], ())
        evidence_id = _text(item.get("evidence_id"))
        stance = item.get("stance")
        classification = item.get("classification")
        confidence = item.get("confidence")
        provenance = item.get("provenance_refs", [])
        if (
            evidence_id is None
            or stance not in {"support", "oppose", "neutral"}
            or classification not in {"fact", "inference", "unknown"}
            or confidence not in {"high", "medium", "low"}
            or not isinstance(provenance, (list, tuple))
            or any(_text(ref) is None for ref in provenance)
        ):
            return ({"status": "UNKNOWN", "total_count": 0}, "ERROR", ["FORMAL_EVIDENCE_INVALID"], ())
        evidence_by_id[evidence_id] = dict(item)
        refs = provenance_by_id.setdefault(evidence_id, [])
        refs.extend(ref for ref in provenance if ref not in refs)

    refs = list(evidence_by_id)
    supporting_fact = 0
    opposing_high = 0
    counts = {
        "support": 0,
        "oppose": 0,
        "neutral": 0,
        "fact": 0,
        "inference": 0,
        "unknown": 0,
    }
    for evidence_id, item in evidence_by_id.items():
        stance = item.get("stance")
        classification = item.get("classification")
        confidence = item.get("confidence")
        counts[stance] += 1
        counts[classification] += 1
        if stance == "support" and classification == "fact":
            supporting_fact += 1
        if stance == "oppose" and confidence == "high":
            opposing_high += 1
    if opposing_high:
        status = "CONFLICT"
        reasons = ["FORMAL_EVIDENCE_OPPOSING_HIGH_CONFLICT"]
    elif supporting_fact == 0:
        status = "INSUFFICIENT"
        reasons = ["FORMAL_EVIDENCE_SUPPORTING_FACT_MISSING"]
    else:
        status = "SUFFICIENT"
        reasons = []
    return (
        {
            "status": status,
            "total_count": len(evidence_by_id),
            "supporting_count": counts["support"],
            "opposing_count": counts["oppose"],
            "neutral_count": counts["neutral"],
            "supporting_fact_count": supporting_fact,
            "opposing_high_count": opposing_high,
            "classification_counts": {
                "fact": counts["fact"],
                "inference": counts["inference"],
                "unknown": counts["unknown"],
            },
            "provenance": [
                {
                    "evidence_id": evidence_id,
                    "authority_refs": provenance_by_id[evidence_id],
                }
                for evidence_id in evidence_by_id
            ],
        },
        "EVALUATED",
        reasons,
        tuple(refs),
    )


def _action_partition(allowed: set[str]) -> tuple[list[str], list[str]]:
    return (
        [action for action in NEXT_BEST_ACTIONS if action in allowed],
        [action for action in NEXT_BEST_ACTIONS if action not in allowed],
    )


def _envelope(allowed: set[str], *, maintain: list[str], upgrade: list[str], downgrade: list[str], invalidation: list[str]) -> dict[str, Any]:
    allowed_actions, blocked_actions = _action_partition(allowed)
    return {
        "allowed_actions": allowed_actions,
        "blocked_actions": blocked_actions,
        "maintain_conditions": maintain,
        "upgrade_conditions": upgrade,
        "downgrade_conditions": downgrade,
        "invalidation_conditions": invalidation,
    }


def _account_identity(account: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(account, Mapping) or account.get("_candidate_read_error") is True:
        return None
    cash = account.get("cash")
    current = cash.get("current_fact") if isinstance(cash, Mapping) else None
    current = current if isinstance(current, Mapping) else {}
    return {
        "canonical": account.get("canonical") if isinstance(account.get("canonical"), bool) else None,
        "account_status": account.get("account_status"),
        "bootstrap_status": account.get("bootstrap_status"),
        "cash": {
            "status": current.get("status"),
            "value": current.get("value"),
            "source": current.get("source"),
            "updated_at": current.get("updated_at"),
            "temporal_status": current.get("temporal_status"),
        },
        "settled_nav": account.get("settled_nav"),
        "nav_temporal_state": account.get("nav_temporal_state"),
        "confidence": account.get("confidence"),
    }


def _strings_from(value: object) -> list[str]:
    return (
        [item for item in value if isinstance(item, str) and item]
        if isinstance(value, (list, tuple))
        else []
    )


def _account_positions_match(
    account: Mapping[str, Any] | None, holdings: list[dict[str, Any]]
) -> bool:
    if not isinstance(account, Mapping) or not isinstance(account.get("positions"), list):
        return False
    normalized: list[dict[str, Any]] = []
    for item in account["positions"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("code"), str):
            return False
        shares = _finite_nonnegative(item.get("shares"))
        if shares is None or shares <= 0:
            continue
        normalized.append({"code": item["code"], "shares": shares})
    normalized.sort(key=lambda item: item["code"])
    return normalized == [
        {"code": item["code"], "shares": item["shares"]}
        for item in holdings
    ]


def _review_is_due(value: object, as_of: datetime) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.astimezone(timezone.utc) <= as_of


def _replacement_reasons(item: Mapping[str, Any], as_of: datetime) -> list[str]:
    reasons: list[str] = []
    thesis_state = item.get("current_thesis_state")
    if thesis_state == "WEAKENED":
        reasons.append("INCUMBENT_THESIS_WEAKENED")
    elif thesis_state == "DISPROVEN":
        reasons.append("INCUMBENT_THESIS_DISPROVEN")
    elif thesis_state == "INVALIDATED":
        reasons.append("INCUMBENT_THESIS_INVALIDATED")
    if item.get("hard_risk_state") == "CONFIRMED":
        reasons.append("INCUMBENT_HARD_RISK_CONFIRMED")
    if item.get("material_change_state") in {"MATERIAL", "CRITICAL", "CONFIRMED"}:
        reasons.append("INCUMBENT_MATERIAL_CHANGE_CONFIRMED")
    if item.get("campaign_status") == "REDUCING":
        reasons.append("INCUMBENT_CAMPAIGN_REDUCING")
    sell_state = item.get("sell_state")
    if sell_state in {"THESIS_INVALIDATED", "WATCH_TO_REDUCE", "REDUCE", "EXIT"}:
        reasons.append("INCUMBENT_FORMAL_REVIEW_PRESSURE")
    frozen = item.get("last_frozen_decision")
    if isinstance(frozen, Mapping) and _review_is_due(frozen.get("review_by"), as_of):
        reasons.append("INCUMBENT_REVIEW_DUE")

    upstream = set(_strings_from(item.get("reason_codes")))
    for source, target in (
        ("THESIS_WEAKENED", "INCUMBENT_THESIS_WEAKENED"),
        ("THESIS_DISPROVEN", "INCUMBENT_THESIS_DISPROVEN"),
        ("THESIS_INVALIDATED", "INCUMBENT_THESIS_INVALIDATED"),
        ("HARD_RISK_CONFIRMED", "INCUMBENT_HARD_RISK_CONFIRMED"),
        ("MATERIAL_CHANGE_MATERIAL", "INCUMBENT_MATERIAL_CHANGE_CONFIRMED"),
        ("MATERIAL_CHANGE_CRITICAL", "INCUMBENT_MATERIAL_CHANGE_CONFIRMED"),
        ("REVIEW_BY_REACHED", "INCUMBENT_REVIEW_DUE"),
    ):
        if source in upstream:
            reasons.append(target)
    return list(dict.fromkeys(reasons))


def _incumbent_is_current(item: Mapping[str, Any], as_of: datetime) -> bool:
    frozen = item.get("last_frozen_decision")
    return (
        item.get("campaign_status") == "ACTIVE"
        and item.get("current_thesis_state") in {"STABLE", "STRENGTHENED"}
        and item.get("hard_risk_state") == "CLEAR"
        and item.get("material_change_state") == "NONE"
        and isinstance(frozen, Mapping)
        and isinstance(frozen.get("frozen_decision_ref"), str)
        and not _review_is_due(frozen.get("review_by"), as_of)
    )


def _portfolio_capital_context(
    *,
    as_of: datetime,
    account_state: str,
    account_reality: Mapping[str, Any] | None,
    cash: float | None,
    position_state: str,
    position_evaluation: str,
    holdings: list[dict[str, Any]],
    risk_cap: Mapping[str, Any],
    incumbent_context: Mapping[str, Any] | None,
    candidate_positive_action: bool,
) -> dict[str, Any]:
    account_canonical = (
        account_reality.get("canonical")
        if isinstance(account_reality, Mapping)
        and isinstance(account_reality.get("canonical"), bool)
        else None
    )
    required_capital = _finite_positive(risk_cap.get("risk_allowed_position_value"))
    account_positions_match = _account_positions_match(account_reality, holdings)
    if (
        account_state != "USABLE"
        or account_canonical is not True
        or not account_positions_match
        or cash is None
        or required_capital is None
    ):
        capital_state = "UNKNOWN"
        capital_reasons = [
            "ACCOUNT_POSITION_SNAPSHOT_MISMATCH"
            if account_canonical is True and not account_positions_match
            else "ACCOUNT_REALITY_UNKNOWN"
        ]
        confirmed_cash = None
    elif cash + 1e-9 < required_capital:
        capital_state = "CONSTRAINED"
        capital_reasons = ["CAPITAL_CONSTRAINED"]
        confirmed_cash = round(cash, 2)
    else:
        capital_state = "AVAILABLE"
        capital_reasons = []
        confirmed_cash = round(cash, 2)

    if position_evaluation != "EVALUATED":
        fit_state = "UNKNOWN"
        fit_reasons = ["POSITION_REALITY_UNKNOWN"]
    elif capital_state == "UNKNOWN":
        fit_state = "UNKNOWN"
        fit_reasons = ["ACCOUNT_REALITY_UNKNOWN"]
    elif position_state == "HELD":
        fit_state = "CONSTRAINED"
        fit_reasons = ["CANDIDATE_ALREADY_HELD"]
    elif capital_state == "CONSTRAINED":
        fit_state = "CONSTRAINED"
        fit_reasons = ["CAPITAL_CONSTRAINED"]
    elif holdings:
        fit_state = "UNKNOWN"
        fit_reasons = ["PORTFOLIO_EXPOSURE_NOT_PROVEN"]
    else:
        fit_state = "SUPPORTIVE"
        fit_reasons = []

    replacement_state = "UNKNOWN"
    replacement_reasons: list[str] = []
    replacement_candidates: list[dict[str, Any]] = []
    incumbent_snapshot: dict[str, Any] | None = None
    if capital_state == "AVAILABLE":
        replacement_state = "NOT_REQUIRED"
    elif (
        capital_state == "CONSTRAINED"
        and position_evaluation == "EVALUATED"
        and not candidate_positive_action
    ):
        replacement_state = "NOT_PROVEN"
        replacement_reasons = ["CANDIDATE_REPLACEMENT_ELIGIBILITY_NOT_PROVEN"]
    elif capital_state == "CONSTRAINED" and position_evaluation == "EVALUATED":
        if not holdings:
            replacement_state = "NOT_PROVEN"
            replacement_reasons = [
                "NO_INCUMBENT_CAPITAL_TO_REVIEW",
                "REPLACEMENT_SUPERIORITY_NOT_PROVEN",
            ]
        elif (
            isinstance(incumbent_context, Mapping)
            and incumbent_context.get("_candidate_read_error") is not True
            and incumbent_context.get("evaluation_status") == "EVALUATED"
            and incumbent_context.get("canonical") is True
            and isinstance(incumbent_context.get("campaign_items"), list)
            and isinstance(incumbent_context.get("holding_setup_items"), list)
        ):
            incumbent_snapshot = {
                "reason_codes": _strings_from(incumbent_context.get("reason_codes")),
                "holding_setup_items": list(incumbent_context["holding_setup_items"]),
                "campaign_items": list(incumbent_context["campaign_items"]),
            }
            campaign_items = incumbent_context["campaign_items"]
            for raw_item in campaign_items:
                if not isinstance(raw_item, Mapping):
                    replacement_reasons = ["INCUMBENT_AUTHORITY_INVALID"]
                    break
                item_reasons = _replacement_reasons(raw_item, as_of)
                if item_reasons:
                    replacement_candidates.append(
                        {
                            "security_code": raw_item.get("security_code"),
                            "campaign_id": raw_item.get("campaign_id"),
                            "strategy": raw_item.get("strategy"),
                            "reason_codes": item_reasons,
                        }
                    )
            if replacement_candidates:
                replacement_state = "WORTH_REVIEW"
                replacement_reasons = list(
                    dict.fromkeys(
                        reason
                        for item in replacement_candidates
                        for reason in item["reason_codes"]
                    )
                )
            elif (
                not replacement_reasons
                and not incumbent_context["holding_setup_items"]
                and campaign_items
                and all(
                    isinstance(item, Mapping) and _incumbent_is_current(item, as_of)
                    for item in campaign_items
                )
            ):
                replacement_state = "NOT_PROVEN"
                replacement_reasons = ["REPLACEMENT_SUPERIORITY_NOT_PROVEN"]
            else:
                replacement_reasons = replacement_reasons or ["INCUMBENT_AUTHORITY_UNKNOWN"]
        else:
            replacement_reasons = ["INCUMBENT_AUTHORITY_UNKNOWN"]
    elif capital_state == "UNKNOWN":
        replacement_reasons = ["ACCOUNT_REALITY_UNKNOWN"]
    else:
        replacement_reasons = ["POSITION_REALITY_UNKNOWN"]

    authority_refs = [
        CAPITAL_ALLOCATION_AUTHORITY_REF,
        "account_reality:current_account_reality",
        "position_reality:current_holdings_snapshot",
    ]
    if isinstance(incumbent_context, Mapping):
        authority_refs.extend(_strings_from(incumbent_context.get("authority_refs")))
    return {
        "schema_version": CAPITAL_ALLOCATION_SCHEMA_VERSION,
        "capital_availability": {
            "state": capital_state,
            "confirmed_cash": confirmed_cash,
            "required_capital": (
                round(required_capital, 2) if required_capital is not None else None
            ),
            "reason_codes": capital_reasons,
        },
        "portfolio_fit": {
            "state": fit_state,
            "existing_position_count": (
                len(holdings) if position_evaluation == "EVALUATED" else None
            ),
            "reason_codes": fit_reasons,
        },
        "replacement_review": {
            "state": replacement_state,
            "reason_codes": replacement_reasons,
            "candidates": replacement_candidates,
        },
        "position_sizing_status": risk_cap.get("status", "UNKNOWN"),
        "authority_snapshot": {
            "account": _account_identity(account_reality),
            "positions": holdings if position_evaluation == "EVALUATED" else None,
            "incumbents": incumbent_snapshot,
        },
        "authority_refs": list(dict.fromkeys(authority_refs)),
    }


def _narrow_for_capital(
    allowed: set[str], context: Mapping[str, Any]
) -> set[str]:
    capital = context["capital_availability"]["state"]
    fit = context["portfolio_fit"]["state"]
    replacement = context["replacement_review"]["state"]
    if capital == "UNKNOWN" or fit == "UNKNOWN" or replacement == "UNKNOWN":
        allowed -= BUY_ACTIONS
    elif capital == "CONSTRAINED" or fit == "CONSTRAINED":
        allowed -= {"BUY NOW", "SCALE IN"}
    return allowed or {"RESEARCH MORE"}


def project_candidate_opportunity(
    *,
    security_code: str,
    strategy: str,
    as_of: str,
    asset_view: Mapping[str, Any],
    trade_view: Mapping[str, Any],
    portfolio_view: Mapping[str, Any],
    hard_risk_state: str,
    hard_risk_evaluation: str,
    hard_risk_refs: tuple[str, ...],
    critical_data: Mapping[str, Any],
    evidence_links: object,
    position_snapshot: Mapping[str, Any] | None,
    account_reality: Mapping[str, Any] | None,
    incumbent_context: Mapping[str, Any] | None = None,
    model_proposed: bool = False,
) -> CandidateOpportunityProjection:
    """Return the existing Proposal fields narrowed for a PRE-ENTRY decision."""

    as_of_dt = datetime.fromisoformat(as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of)
    as_of_dt = as_of_dt.astimezone(timezone.utc)
    valuation_status, cases, valuation_reasons = _valuation(asset_view, as_of_dt)
    position_state, position_eval, position_reasons, holdings = _position_state(
        position_snapshot, security_code
    )
    account_state, account_eval, nav, cash, account_reasons = _account_state(account_reality)
    account_canonical = (
        account_reality.get("canonical")
        if isinstance(account_reality, Mapping)
        and isinstance(account_reality.get("canonical"), bool)
        else None
    )
    account_confidence = (
        account_reality.get("confidence")
        if isinstance(account_reality, Mapping)
        and account_reality.get("confidence") in {"HIGH", "MEDIUM", "LOW"}
        else "UNKNOWN"
    )
    confidence, confidence_ceiling, confidence_reasons = _confidence(asset_view)
    evidence, evidence_eval, evidence_reasons, evidence_refs = _evidence_summary(evidence_links)
    evidence_provenance_refs = tuple(
        ref
        for item in evidence.get("provenance", [])
        for ref in item.get("authority_refs", [])
    )

    critical_state = critical_data.get("critical_data_state")
    critical_eval = critical_data.get("critical_data_evaluation")
    reasons = [
        *valuation_reasons,
        *position_reasons,
        *account_reasons,
        *confidence_reasons,
        *evidence_reasons,
    ]
    if hard_risk_state != "CLEAR" or hard_risk_evaluation != "EVALUATED":
        reasons.append(f"HARD_RISK_{hard_risk_state or 'NOT_EVALUATED'}")
    if critical_state != "USABLE" or critical_eval != "EVALUATED":
        reasons.append(f"CRITICAL_DATA_{critical_state or 'UNKNOWN'}")
    if security_code.startswith(("4", "8", "92")):
        reasons.append("RESTRICTED_UNIVERSE_UNSUPPORTED")

    entry = _price_range(trade_view.get("entry_range"))
    invalidation = _finite_positive(trade_view.get("invalidation_price"))
    entry_ready = entry is not None and invalidation is not None and invalidation < entry["low"]
    risk_reward: dict[str, Any] = {"status": "UNKNOWN", "ratio": None}
    risk_cap: dict[str, Any] = {
        "status": "UNKNOWN",
        "risk_allowed_position_value": None,
        "max_position_value": None,
        "max_shares": None,
    }
    if not entry_ready:
        reasons.append("ENTRY_OR_INVALIDATION_INCOMPLETE")
        valuation_status = "UNKNOWN"
        cases = {}
    elif critical_state != "USABLE" or critical_eval != "EVALUATED":
        valuation_status = "UNKNOWN"
        cases = {}
        reasons.append("VALUATION_CRITICAL_DATA_UNUSABLE")
    elif valuation_status == "READY":
        entry_mid = (entry["low"] + entry["high"]) / 2
        base = cases["base"]["price_range"]
        base_mid = (base["low"] + base["high"]) / 2
        downside = entry_mid - invalidation
        ratio = (base_mid - entry_mid) / downside
        risk_reward = {
            "status": "AVAILABLE",
            "ratio": round(ratio, 4),
            "required_ratio": RISK_REWARD_GATE[strategy],
            "entry_mid": round(entry_mid, 4),
            "base_mid": round(base_mid, 4),
            "invalidation_price": invalidation,
        }
        if account_state == "USABLE" and nav is not None and cash is not None:
            distance = (entry["high"] - invalidation) / entry["high"]
            risk_budget = round(nav * RISK_BUDGET_RATE[strategy], 2)
            risk_allowed_value = risk_budget / distance
            value_cap = min(cash, risk_allowed_value)
            shares = math.floor(value_cap / entry["high"] / 100) * 100
            risk_cap = {
                "status": (
                    "AVAILABLE"
                    if account_canonical is True
                    else "AVAILABLE_CANDIDATE"
                    if account_canonical is False
                    else "AVAILABLE_CANONICALITY_UNKNOWN"
                ),
                "risk_budget_rate": RISK_BUDGET_RATE[strategy],
                "risk_budget_value": risk_budget,
                "settled_nav": round(nav, 2),
                "cash_cap": round(cash, 2),
                "risk_allowed_position_value": round(risk_allowed_value, 2),
                "max_position_value": round(min(value_cap, shares * entry["high"]), 2),
                "max_shares": shares,
            }

    evaluations = [
        hard_risk_evaluation,
        str(critical_eval),
        position_eval,
        account_eval,
        evidence_eval,
    ]
    if valuation_status != "READY" or confidence_ceiling == "UNKNOWN":
        evaluations.append("UNKNOWN")
    constraint_evaluation = max(evaluations, key=lambda item: _EVALUATION_RANK.get(item, 3))

    conservative = {"WAIT", "AVOID", "RESEARCH MORE"}
    stance = asset_view.get("stance")
    trade_stance = trade_view.get("stance")
    if hard_risk_state == "CONFIRMED" and hard_risk_evaluation == "EVALUATED":
        nba = "AVOID"
        allowed = conservative
    elif valuation_status != "READY" or not entry_ready or confidence_ceiling == "UNKNOWN":
        nba = "RESEARCH MORE"
        allowed = conservative
    elif evidence["status"] == "INSUFFICIENT":
        nba = "RESEARCH MORE"
        allowed = conservative
    elif evidence["status"] in {"CONFLICT", "UNKNOWN"}:
        nba = "WAIT"
        allowed = conservative
    elif (
        hard_risk_evaluation in {"ERROR", "NOT_EVALUATED"}
        or hard_risk_state == "NOT_EVALUATED"
        or hard_risk_state not in {"CLEAR", "UNKNOWN"}
        or critical_state != "USABLE"
        or critical_eval != "EVALUATED"
    ):
        nba = "RESEARCH MORE"
        allowed = conservative
    elif position_state != "NOT_HELD" or account_state != "USABLE" or "RESTRICTED_UNIVERSE_UNSUPPORTED" in reasons:
        nba = "WAIT"
        allowed = conservative
    elif stance == "OPPOSE" or trade_stance == "OPPOSE":
        nba = "AVOID"
        allowed = conservative
    elif (
        stance != "SUPPORT"
        or trade_stance != "SUPPORT"
        or risk_reward["status"] != "AVAILABLE"
        or risk_reward["ratio"] < RISK_REWARD_GATE[strategy]
    ):
        nba = "WAIT"
        allowed = conservative
    elif risk_cap.get("max_shares", 0) < 100:
        nba = "WAIT"
        allowed = conservative
        reasons.append("ACCOUNT_CAPACITY_BELOW_BOARD_LOT")
    elif (
        hard_risk_state == "UNKNOWN"
        or confidence_ceiling in {"LOW", "MEDIUM"}
    ):
        nba = "BUY SMALL"
        allowed = {"BUY SMALL", *conservative}
    elif trade_view.get("execution_style") == "SCALE_IN":
        nba = "SCALE IN"
        allowed = {"BUY SMALL", "SCALE IN", *conservative}
    else:
        nba = "BUY NOW"
        allowed = {"BUY NOW", "BUY SMALL", *conservative}

    capital_context = _portfolio_capital_context(
        as_of=as_of_dt,
        account_state=account_state,
        account_reality=account_reality,
        cash=cash,
        position_state=position_state,
        position_evaluation=position_eval,
        holdings=holdings,
        risk_cap=risk_cap,
        incumbent_context=incumbent_context,
        candidate_positive_action=bool(allowed & BUY_ACTIONS),
    )
    allowed = _narrow_for_capital(allowed, capital_context)
    if nba not in allowed:
        for fallback in ("BUY SMALL", "WAIT", "RESEARCH MORE", "AVOID"):
            if fallback in allowed:
                nba = fallback
                break
    capital_evaluation = (
        "UNKNOWN"
        if "UNKNOWN" in {
            capital_context["capital_availability"]["state"],
            capital_context["portfolio_fit"]["state"],
            capital_context["replacement_review"]["state"],
        }
        else "EVALUATED"
    )
    constraint_evaluation = max(
        (constraint_evaluation, capital_evaluation),
        key=lambda item: _EVALUATION_RANK.get(item, 3),
    )
    for dimension in (
        "capital_availability",
        "portfolio_fit",
        "replacement_review",
    ):
        reasons.extend(capital_context[dimension]["reason_codes"])

    analysis_metadata = {
        "model_provider": "UNAVAILABLE" if model_proposed else "NOT_APPLICABLE",
        "model_identifier": "UNAVAILABLE" if model_proposed else "NOT_APPLICABLE",
        "prompt_version": "campaign-ai-draft.v0.1" if model_proposed else "NOT_APPLICABLE",
        "analysis_policy_version": ANALYSIS_POLICY_VERSION,
    }
    normalized_asset: dict[str, Any] = {
        "view": "ASSET",
        "stance": stance if stance in {"SUPPORT", "WAIT", "OPPOSE"} else "WAIT",
    }
    if _text(asset_view.get("note")) is not None:
        normalized_asset["note"] = _text(asset_view.get("note"))
    normalized_asset.update(
        {
            "candidate_valuation": {"status": valuation_status, "cases": cases},
            **confidence,
            "analysis_metadata": analysis_metadata,
        }
    )
    normalized_trade: dict[str, Any] = {
        "view": "TRADE",
        "stance": trade_stance if trade_stance in {"SUPPORT", "WAIT", "OPPOSE"} else "WAIT",
        "risk_reward": risk_reward,
    }
    if _text(trade_view.get("note")) is not None:
        normalized_trade["note"] = _text(trade_view.get("note"))
    if entry_ready:
        normalized_trade.update(
            {
                "entry_range": entry,
                "invalidation_price": invalidation,
                "execution_style": (
                    "SCALE_IN"
                    if trade_view.get("execution_style") == "SCALE_IN"
                    else "ONE_TIME"
                ),
            }
        )
    normalized_portfolio: dict[str, Any] = {"view": "PORTFOLIO"}
    if _text(portfolio_view.get("constraint")) is not None:
        normalized_portfolio["constraint"] = _text(portfolio_view.get("constraint"))
    normalized_portfolio.update(
        {
            "position_state": position_state,
            "account_state": account_state,
            "account_canonical": account_canonical,
            "account_confidence": account_confidence,
            "risk_cap": risk_cap,
            "portfolio_capital_context": capital_context,
        }
    )

    critical_refs = critical_data.get("authority_refs")
    critical_refs = (
        tuple(item for item in critical_refs if isinstance(item, str) and item)
        if isinstance(critical_refs, (list, tuple))
        else ()
    )
    authority_refs = tuple(
        dict.fromkeys(
            (
                AUTHORITY_REF,
                CAPITAL_ALLOCATION_AUTHORITY_REF,
                "position_reality:current_holdings_snapshot",
                "account_reality:settled_nav_candidate",
                *capital_context["authority_refs"],
                *hard_risk_refs,
                *critical_refs,
                *(f"formal_evidence:{item}" for item in evidence_refs),
                *evidence_provenance_refs,
            )
        )
    )
    authority_fact = {
        "state": valuation_status,
        "evaluation": constraint_evaluation,
        "valuation_status": valuation_status,
        "position_state": position_state,
        "account_state": account_state,
        "account_canonical": account_canonical,
        "account_confidence": account_confidence,
        "hard_risk_state": hard_risk_state,
        "critical_data_state": critical_state,
        "confidence": confidence,
        "confidence_ceiling": confidence_ceiling,
        "evidence": evidence,
        "evidence_refs": list(evidence_refs),
        "risk_reward": risk_reward,
        "risk_cap": risk_cap,
        "reason_codes": list(dict.fromkeys(reasons)),
        "analysis_metadata": analysis_metadata,
        "risk_policy_version": RISK_POLICY_VERSION,
        "opportunity_policy_version": OPPORTUNITY_POLICY_VERSION,
        "decision_policy_version": DECISION_POLICY_VERSION,
        "authority_refs": list(authority_refs),
    }
    envelope = _envelope(
        allowed,
        maintain=[
            "PRE-ENTRY remains NOT_HELD until an attributed executed BUY",
            "named authorities remain applicable",
            "Account, Position, and relevant incumbent authority identities remain unchanged",
        ],
        upgrade=["resolve each listed Candidate reason before widening the Action Envelope"],
        downgrade=[
            "Hard Risk, Critical Data, confidence, valuation, account, position, or capital fit deteriorates"
        ],
        invalidation=[
            "entry/invalidation range or Bear/Base/Bull assumptions change",
            "Current Thesis changes",
            "Account, Position, or relevant incumbent authority identity changes",
        ],
    )
    return CandidateOpportunityProjection(
        constraint_evaluation=constraint_evaluation,
        asset_view=normalized_asset,
        trade_view=normalized_trade,
        portfolio_view=normalized_portfolio,
        next_best_action=nba,
        action_envelope=envelope,
        authority_fact=authority_fact,
        authority_refs=authority_refs,
    )


__all__ = [
    "ANALYSIS_POLICY_VERSION",
    "AUTHORITY_REF",
    "BUY_ACTIONS",
    "CAPITAL_ALLOCATION_AUTHORITY_REF",
    "CAPITAL_ALLOCATION_SCHEMA_VERSION",
    "CandidateOpportunityProjection",
    "DECISION_POLICY_VERSION",
    "OPPORTUNITY_POLICY_VERSION",
    "RISK_POLICY_VERSION",
    "RISK_REWARD_GATE",
    "project_candidate_opportunity",
]
