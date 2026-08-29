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


def _position_state(snapshot: Mapping[str, Any] | None, security_code: str) -> tuple[str, str, list[str]]:
    if snapshot is None:
        return "UNKNOWN", "NOT_EVALUATED", ["POSITION_AUTHORITY_NOT_WIRED"]
    if snapshot.get("_candidate_read_error") is True:
        return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_ERROR"]
    authority_state = snapshot.get("authority_state")
    if authority_state == "LEGACY":
        return "UNKNOWN", "UNKNOWN", ["POSITION_AUTHORITY_LEGACY"]
    if authority_state != "CANONICAL":
        return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"]
    holdings = snapshot.get("holdings")
    if not isinstance(holdings, list):
        return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"]
    for holding in holdings:
        if not isinstance(holding, Mapping) or not isinstance(holding.get("code"), str):
            return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"]
        shares = _finite_nonnegative(holding.get("shares"))
        if shares is None:
            return "UNKNOWN", "ERROR", ["POSITION_AUTHORITY_INVALID"]
        if holding["code"] == security_code and shares > 0:
            return "HELD", "EVALUATED", ["SECURITY_ALREADY_HELD"]
    return "NOT_HELD", "EVALUATED", []


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
    model_proposed: bool = False,
) -> CandidateOpportunityProjection:
    """Return the existing Proposal fields narrowed for a PRE-ENTRY decision."""

    as_of_dt = datetime.fromisoformat(as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of)
    as_of_dt = as_of_dt.astimezone(timezone.utc)
    valuation_status, cases, valuation_reasons = _valuation(asset_view, as_of_dt)
    position_state, position_eval, position_reasons = _position_state(position_snapshot, security_code)
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
    risk_cap: dict[str, Any] = {"status": "UNKNOWN", "max_position_value": None, "max_shares": None}
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
            value_cap = min(cash, risk_budget / distance)
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
                "position_reality:current_holdings_snapshot",
                "account_reality:settled_nav_candidate",
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
        maintain=["PRE-ENTRY remains NOT_HELD until an attributed executed BUY", "named authorities remain applicable"],
        upgrade=["resolve each listed Candidate reason before widening the Action Envelope"],
        downgrade=["Hard Risk, Critical Data, confidence, valuation, account, or position authority deteriorates"],
        invalidation=["entry/invalidation range or Bear/Base/Bull assumptions change", "Current Thesis changes"],
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
    "CandidateOpportunityProjection",
    "DECISION_POLICY_VERSION",
    "OPPORTUNITY_POLICY_VERSION",
    "RISK_POLICY_VERSION",
    "RISK_REWARD_GATE",
    "project_candidate_opportunity",
]
