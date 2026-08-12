"""Sell Engine Projection Core v0.1 (P0-SE1).

Answers one question only:

> For a real holding Campaign, given already-normalized Thesis / Hard Risk /
> Expectation / R/R / Catalyst / Portfolio / Opportunity Cost / Technical
> conclusions, what is the current sell-side state and why?

```text
Sell Engine
=
deterministic sell-side semantic authority
```

Not a BUY engine, Hard Risk engine, Thesis engine, price predictor,
technical trading system, portfolio optimizer, or AI recommender.

First principles (product law):

- LOSS != SELL REASON
- PROFIT != HOLD REASON
- MARKET / TECHNICAL WEAKNESS != AUTOMATIC EXIT
- ONE TECHNICAL INDICATOR != SELL
- NEW EVIDENCE / MATERIAL CHANGE != SELL
- HARD RISK != COMPLETE SELL ENGINE
- AI != SELL AUTHORITY
- NO SELL SIGNAL != PROVEN HOLD

Pure domain boundary:

- no I/O, SQLite, filesystem, env, network, FastAPI, AI, wall clock
- no imports of thesis / hard-risk / portfolio_advice / cockpit / DI / CCD
- consumes only explicit normalized dimension inputs
- as_of is required and never reads wall clock
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "sell_engine.projection.v0.1"
AUTHORITY_REF = "sell_engine:projection:v0.1"

# ---------------------------------------------------------------------------
# Domain sell states (action semantics)
# ---------------------------------------------------------------------------

SELL_STATES: tuple[str, ...] = (
    "HOLD",
    "WATCH_TO_REDUCE",
    "REDUCE",
    "EXIT",
    "THESIS_INVALIDATED",
)

# Evaluation completeness axis (separate from domain sell state).
SELL_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

VALID_STRATEGIES: tuple[str, ...] = ("SHORT", "SWING", "MEDIUM")

# North Star sell reason categories (primary / supporting).
REASON_CATEGORIES: tuple[str, ...] = (
    "THESIS_INVALIDATION",
    "RISK_EXIT",
    "EXPECTATION_PRICE_IN",
    "RISK_REWARD_DETERIORATION",
    "CATALYST_FAILURE",
    "PORTFOLIO_REBALANCE",
    "OPPORTUNITY_COST",
    "TECHNICAL_EXECUTION",
)

# Primary-reason precedence among confirmed sell pressures.
# Only freezes necessary order: thesis terminal > hard risk > remaining.
_PRIMARY_PRECEDENCE: tuple[str, ...] = (
    "THESIS_INVALIDATION",
    "RISK_EXIT",
    "CATALYST_FAILURE",
    "RISK_REWARD_DETERIORATION",
    "EXPECTATION_PRICE_IN",
    "PORTFOLIO_REBALANCE",
    "OPPORTUNITY_COST",
    "TECHNICAL_EXECUTION",
)

# Domain pressure ranks for non-terminal aggregation.
_STATE_RANK: dict[str, int] = {
    "HOLD": 0,
    "WATCH_TO_REDUCE": 1,
    "REDUCE": 2,
    "EXIT": 3,
    "THESIS_INVALIDATED": 4,
}

# Evaluation severity for aggregation (ERROR > NOT_EVALUATED > UNKNOWN > EVALUATED).
_EVAL_RANK: dict[str, int] = {
    "EVALUATED": 0,
    "UNKNOWN": 1,
    "NOT_EVALUATED": 2,
    "ERROR": 3,
}

# Thesis input states (consume Formal Current Thesis effective_state vocabulary).
THESIS_INPUT_STATES: tuple[str, ...] = (
    "STABLE",
    "STRENGTHENED",
    "WEAKENED",
    "DISPROVEN",
    "INVALIDATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
    "NOT_READY",
)

HARD_RISK_INPUT_STATES: tuple[str, ...] = (
    "CLEAR",
    "CONFIRMED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

# Shared pressure vocabulary for most sell dimensions.
PRESSURE_INPUT_STATES: tuple[str, ...] = (
    "NONE",
    "WATCH",
    "REDUCE",
    "EXIT",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
    "NOT_APPLICABLE",
)

# Catalyst keeps failure semantics distinct from "not yet happened".
CATALYST_INPUT_STATES: tuple[str, ...] = (
    "NONE",
    "FAILED",
    "NOT_YET",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
    "NOT_APPLICABLE",
)

# Dimension keys (stable order for explainability).
_DIMENSIONS: tuple[str, ...] = (
    "thesis",
    "hard_risk",
    "expectation_price_in",
    "risk_reward",
    "catalyst",
    "portfolio_rebalance",
    "opportunity_cost",
    "technical_execution",
)

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")

_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)


class SellEngineError(Exception):
    """Sell Engine domain base error."""


class SellEngineValidationError(SellEngineError, ValueError):
    """Illegal caller input / contract violation → fail closed."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SellEngineValidationError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise SellEngineValidationError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def _require_security_code(value: object) -> str:
    code = _require_nonempty_str(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise SellEngineValidationError(
            "security_code must be a 6-digit A-share code"
        )
    return code


def _require_strategy(value: object) -> str:
    strategy = _require_nonempty_str(value, "strategy")
    if strategy not in VALID_STRATEGIES:
        raise SellEngineValidationError(
            f"strategy must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object) -> str:
    campaign_id = _require_nonempty_str(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise SellEngineValidationError(
            "campaign_id must match campaign_<32 lowercase hex>"
        )
    return campaign_id


def _require_as_of(value: object) -> str:
    as_of = _require_nonempty_str(value, "as_of")
    if not any(p.fullmatch(as_of) for p in _AS_OF_UTC_FORMS):
        raise SellEngineValidationError(
            "as_of must be a UTC zero-offset instant "
            "(...Z or ...+00:00); wall clock is forbidden"
        )
    # Parse only to reject impossible calendar values; never use wall clock.
    try:
        dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SellEngineValidationError(
            f"as_of is not a parseable UTC instant: {as_of!r}"
        ) from exc
    if dt.tzinfo is None or dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise SellEngineValidationError(
            "as_of must be zero-offset UTC (Z or +00:00)"
        )
    return as_of


def _require_dim(
    value: object,
    field: str,
    allowed_states: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SellEngineValidationError(f"{field} must be a mapping")
    state = value.get("state")
    if not isinstance(state, str) or state not in allowed_states:
        raise SellEngineValidationError(
            f"{field}.state must be one of {allowed_states}, got {state!r}"
        )
    refs_raw = value.get("authority_refs", ())
    if refs_raw is None:
        refs_raw = ()
    if not isinstance(refs_raw, (list, tuple)):
        raise SellEngineValidationError(
            f"{field}.authority_refs must be a list/tuple of strings"
        )
    refs: list[str] = []
    for i, ref in enumerate(refs_raw):
        if not isinstance(ref, str) or not ref.strip() or ref != ref.strip():
            raise SellEngineValidationError(
                f"{field}.authority_refs[{i}] must be a non-empty stripped string"
            )
        refs.append(ref)
    # Reject unknown keys that would smuggle PnL / price / AI payloads.
    allowed_keys = {"state", "authority_refs"}
    extra = set(value.keys()) - allowed_keys
    if extra:
        raise SellEngineValidationError(
            f"{field} has unsupported keys {sorted(extra)}; "
            "Sell Engine consumes normalized state only "
            "(no pnl/price/ai payload)"
        )
    return {"state": state, "authority_refs": list(refs)}


def _pressure_to_sell_state(pressure: str) -> str | None:
    if pressure == "WATCH":
        return "WATCH_TO_REDUCE"
    if pressure == "REDUCE":
        return "REDUCE"
    if pressure == "EXIT":
        return "EXIT"
    return None


def _max_state(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if _STATE_RANK[a] >= _STATE_RANK[b] else b


def _max_eval(a: str, b: str) -> str:
    return a if _EVAL_RANK[a] >= _EVAL_RANK[b] else b


def _eval_from_incomplete_state(state: str) -> str | None:
    if state == "ERROR":
        return "ERROR"
    if state == "NOT_EVALUATED":
        return "NOT_EVALUATED"
    if state == "UNKNOWN":
        return "UNKNOWN"
    return None


# ---------------------------------------------------------------------------
# Dimension interpretation
# ---------------------------------------------------------------------------


def _interpret_thesis(
    dim: Mapping[str, Any],
) -> dict[str, Any]:
    state = dim["state"]
    incomplete = _eval_from_incomplete_state(state)
    if state == "NOT_READY":
        incomplete = "NOT_EVALUATED"
    if incomplete is not None:
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"THESIS_{incomplete}"],
            "opposing": [],
            "uncertainties": [f"THESIS_{incomplete}"],
            "evaluation": incomplete,
            "terminal": False,
        }
    if state in ("DISPROVEN", "INVALIDATED"):
        return {
            "pressure_state": "THESIS_INVALIDATED",
            "category": "THESIS_INVALIDATION",
            "reason_codes": [f"THESIS_{state}"],
            "opposing": [],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "terminal": True,
        }
    if state == "WEAKENED":
        return {
            "pressure_state": "WATCH_TO_REDUCE",
            "category": "THESIS_INVALIDATION",
            "reason_codes": ["THESIS_WEAKENED"],
            "opposing": [],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "terminal": False,
        }
    # STABLE / STRENGTHENED → no sell pressure; positive for HOLD proof.
    return {
        "pressure_state": None,
        "category": None,
        "reason_codes": [f"THESIS_{state}_NO_SELL_PRESSURE"],
        "opposing": [f"THESIS_{state}"],
        "uncertainties": [],
        "evaluation": "EVALUATED",
        "terminal": False,
        "hold_ok": True,
    }


def _interpret_hard_risk(dim: Mapping[str, Any]) -> dict[str, Any]:
    state = dim["state"]
    incomplete = _eval_from_incomplete_state(state)
    if incomplete is not None:
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"HARD_RISK_{incomplete}"],
            "opposing": [],
            "uncertainties": [f"HARD_RISK_{incomplete}"],
            "evaluation": incomplete,
            "terminal": False,
        }
    if state == "CONFIRMED":
        return {
            "pressure_state": "EXIT",
            "category": "RISK_EXIT",
            "reason_codes": ["HARD_RISK_CONFIRMED"],
            "opposing": [],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "terminal": False,
            "hard_exit": True,
        }
    # CLEAR
    return {
        "pressure_state": None,
        "category": None,
        "reason_codes": ["HARD_RISK_CLEAR"],
        "opposing": ["HARD_RISK_CLEAR"],
        "uncertainties": [],
        "evaluation": "EVALUATED",
        "terminal": False,
        "hold_ok": True,
    }


def _interpret_pressure_dim(
    dim: Mapping[str, Any],
    *,
    category: str,
    prefix: str,
    allow_exit: bool,
    allow_not_applicable: bool,
    strategy: str,
) -> dict[str, Any]:
    state = dim["state"]
    if state == "NOT_APPLICABLE":
        if not allow_not_applicable:
            raise SellEngineValidationError(
                f"{prefix.lower()} state NOT_APPLICABLE is not allowed "
                f"for strategy={strategy}"
            )
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"{prefix}_NOT_APPLICABLE"],
            "opposing": [f"{prefix}_NOT_APPLICABLE"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "terminal": False,
            "hold_ok": True,
            "applicable": False,
        }
    incomplete = _eval_from_incomplete_state(state)
    if incomplete is not None:
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"{prefix}_{incomplete}"],
            "opposing": [],
            "uncertainties": [f"{prefix}_{incomplete}"],
            "evaluation": incomplete,
            "terminal": False,
            "applicable": True,
        }
    if state == "NONE":
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"{prefix}_NONE"],
            "opposing": [f"{prefix}_NONE"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "terminal": False,
            "hold_ok": True,
            "applicable": True,
        }
    if state == "EXIT" and not allow_exit:
        # Dimension forbids EXIT alone → cap at REDUCE.
        pressure = "REDUCE"
        code = f"{prefix}_EXIT_CAPPED_TO_REDUCE"
    else:
        pressure = _pressure_to_sell_state(state)
        code = f"{prefix}_{state}"
    return {
        "pressure_state": pressure,
        "category": category,
        "reason_codes": [code],
        "opposing": [],
        "uncertainties": [],
        "evaluation": "EVALUATED",
        "terminal": False,
        "applicable": True,
    }


def _interpret_catalyst(
    dim: Mapping[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    state = dim["state"]
    if state == "NOT_APPLICABLE":
        # MEDIUM may declare catalyst not required; SHORT/SWING may not hide
        # missing catalyst behind NOT_APPLICABLE.
        if strategy == "MEDIUM":
            return {
                "pressure_state": None,
                "category": None,
                "reason_codes": ["CATALYST_NOT_APPLICABLE"],
                "opposing": ["CATALYST_NOT_APPLICABLE"],
                "uncertainties": [],
                "evaluation": "EVALUATED",
                "terminal": False,
                "hold_ok": True,
                "applicable": False,
            }
        raise SellEngineValidationError(
            "catalyst.state NOT_APPLICABLE is only valid for MEDIUM"
        )
    incomplete = _eval_from_incomplete_state(state)
    if incomplete is not None:
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"CATALYST_{incomplete}"],
            "opposing": [],
            "uncertainties": [f"CATALYST_{incomplete}"],
            "evaluation": incomplete,
            "terminal": False,
            "applicable": True,
        }
    if state in ("NONE", "NOT_YET"):
        # NOT_YET is not failure; NONE is clear. Both are HOLD-ok when required.
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"CATALYST_{state}"],
            "opposing": [f"CATALYST_{state}"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "terminal": False,
            "hold_ok": True,
            "applicable": True,
        }
    # FAILED → sell pressure. Not automatic full EXIT; REDUCE is the v0.1 floor.
    # SHORT may escalate to EXIT (execution-horizon catalyst miss is material).
    pressure = "EXIT" if strategy == "SHORT" else "REDUCE"
    return {
        "pressure_state": pressure,
        "category": "CATALYST_FAILURE",
        "reason_codes": ["CATALYST_FAILED"],
        "opposing": [],
        "uncertainties": [],
        "evaluation": "EVALUATED",
        "terminal": False,
        "applicable": True,
    }


def _interpret_technical(
    dim: Mapping[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    """Technical is a market-behavior sensor, not truth layer.

    - SHORT: may contribute up to REDUCE (not thesis invalidation)
    - SWING: timing gate → WATCH or REDUCE
    - MEDIUM: alone cannot EXIT / THESIS_INVALIDATED; cap at WATCH
    """
    state = dim["state"]
    if state == "NOT_APPLICABLE":
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": ["TECHNICAL_NOT_APPLICABLE"],
            "opposing": ["TECHNICAL_NOT_APPLICABLE"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "terminal": False,
            "hold_ok": True,
            "applicable": False,
        }
    incomplete = _eval_from_incomplete_state(state)
    if incomplete is not None:
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"TECHNICAL_{incomplete}"],
            "opposing": [],
            "uncertainties": [f"TECHNICAL_{incomplete}"],
            "evaluation": incomplete,
            "terminal": False,
            "applicable": True,
        }
    if state == "NONE":
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": ["TECHNICAL_NONE"],
            "opposing": ["TECHNICAL_NONE"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "terminal": False,
            "hold_ok": True,
            "applicable": True,
        }

    # Map raw pressure then strategy-cap.
    raw = state  # WATCH | REDUCE | EXIT
    if strategy == "MEDIUM":
        # Medium: technical may only affect timing/scale, never alone exit.
        capped = "WATCH"
        code = f"TECHNICAL_{raw}_CAPPED_MEDIUM_WATCH"
    elif strategy == "SWING":
        if raw == "EXIT":
            capped = "REDUCE"
            code = "TECHNICAL_EXIT_CAPPED_SWING_REDUCE"
        else:
            capped = raw
            code = f"TECHNICAL_{raw}"
    else:  # SHORT
        if raw == "EXIT":
            capped = "REDUCE"
            code = "TECHNICAL_EXIT_CAPPED_SHORT_REDUCE"
        else:
            capped = raw
            code = f"TECHNICAL_{raw}"

    return {
        "pressure_state": _pressure_to_sell_state(capped)
        if capped in ("WATCH", "REDUCE", "EXIT")
        else None,
        "category": "TECHNICAL_EXECUTION",
        "reason_codes": [code],
        "opposing": [],
        "uncertainties": [],
        "evaluation": "EVALUATED",
        "terminal": False,
        "applicable": True,
    }


def _interpret_opportunity_cost(
    dim: Mapping[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    """Opportunity cost respects Replacement Hurdle + NO-TRADE ZONE.

    v0.1 never lets opportunity cost alone produce EXIT.
    """
    return _interpret_pressure_dim(
        dim,
        category="OPPORTUNITY_COST",
        prefix="OPPORTUNITY_COST",
        allow_exit=False,
        allow_not_applicable=False,
        strategy=strategy,
    )


def _interpret_risk_reward(
    dim: Mapping[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    """R/R below threshold is not mechanical EXIT."""
    return _interpret_pressure_dim(
        dim,
        category="RISK_REWARD_DETERIORATION",
        prefix="RISK_REWARD",
        allow_exit=False,
        allow_not_applicable=False,
        strategy=strategy,
    )


def _pick_primary(categories: list[str]) -> str | None:
    if not categories:
        return None
    for cat in _PRIMARY_PRECEDENCE:
        if cat in categories:
            return cat
    return categories[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def project_sell_engine(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    thesis: Mapping[str, Any],
    hard_risk: Mapping[str, Any],
    expectation_price_in: Mapping[str, Any],
    risk_reward: Mapping[str, Any],
    catalyst: Mapping[str, Any],
    portfolio_rebalance: Mapping[str, Any],
    opportunity_cost: Mapping[str, Any],
    technical_execution: Mapping[str, Any],
) -> dict[str, Any]:
    """Project Campaign-scoped sell-side state from normalized inputs.

    Returns a detached dict. Never mutates inputs. Never reads wall clock.
    """
    sec = _require_security_code(security_code)
    strat = _require_strategy(strategy)
    camp = _require_campaign_id(campaign_id)
    as_of_s = _require_as_of(as_of)

    thesis_i = _require_dim(thesis, "thesis", THESIS_INPUT_STATES)
    risk_i = _require_dim(hard_risk, "hard_risk", HARD_RISK_INPUT_STATES)
    exp_i = _require_dim(
        expectation_price_in, "expectation_price_in", PRESSURE_INPUT_STATES
    )
    rr_i = _require_dim(risk_reward, "risk_reward", PRESSURE_INPUT_STATES)
    cat_i = _require_dim(catalyst, "catalyst", CATALYST_INPUT_STATES)
    port_i = _require_dim(
        portfolio_rebalance, "portfolio_rebalance", PRESSURE_INPUT_STATES
    )
    opp_i = _require_dim(
        opportunity_cost, "opportunity_cost", PRESSURE_INPUT_STATES
    )
    tech_i = _require_dim(
        technical_execution, "technical_execution", PRESSURE_INPUT_STATES
    )

    # Reject NOT_APPLICABLE on dimensions that are always baseline-required.
    for label, dim in (
        ("expectation_price_in", exp_i),
        ("risk_reward", rr_i),
        ("portfolio_rebalance", port_i),
        ("opportunity_cost", opp_i),
    ):
        if dim["state"] == "NOT_APPLICABLE":
            raise SellEngineValidationError(
                f"{label}.state NOT_APPLICABLE is not valid in sell engine v0.1"
            )

    interpretations: dict[str, dict[str, Any]] = {
        "thesis": _interpret_thesis(thesis_i),
        "hard_risk": _interpret_hard_risk(risk_i),
        "expectation_price_in": _interpret_pressure_dim(
            exp_i,
            category="EXPECTATION_PRICE_IN",
            prefix="EXPECTATION_PRICE_IN",
            allow_exit=True,
            allow_not_applicable=False,
            strategy=strat,
        ),
        "risk_reward": _interpret_risk_reward(rr_i, strategy=strat),
        "catalyst": _interpret_catalyst(cat_i, strategy=strat),
        "portfolio_rebalance": _interpret_pressure_dim(
            port_i,
            category="PORTFOLIO_REBALANCE",
            prefix="PORTFOLIO_REBALANCE",
            allow_exit=True,
            allow_not_applicable=False,
            strategy=strat,
        ),
        "opportunity_cost": _interpret_opportunity_cost(opp_i, strategy=strat),
        "technical_execution": _interpret_technical(tech_i, strategy=strat),
    }

    # MEDIUM technical-only cannot produce EXIT/THESIS_INVALIDATED — already
    # capped inside interpreter. Additional guard: if the ONLY pressure
    # category is TECHNICAL_EXECUTION on MEDIUM, force cap at WATCH_TO_REDUCE.
    # (Already capped per-signal; keep for multi-code same category.)

    sell_state: str | None = None
    categories_present: list[str] = []
    reason_codes: list[str] = []
    supporting: list[str] = []
    opposing: list[str] = []
    uncertainties: list[str] = []
    evaluation = "EVALUATED"
    hold_positive_dims: list[str] = []
    required_incomplete = False

    for key in _DIMENSIONS:
        inter = interpretations[key]
        for code in inter.get("reason_codes", []):
            if code not in reason_codes:
                reason_codes.append(code)
        for code in inter.get("opposing", []):
            if code not in opposing:
                opposing.append(code)
        for code in inter.get("uncertainties", []):
            if code not in uncertainties:
                uncertainties.append(code)
        evaluation = _max_eval(evaluation, inter["evaluation"])
        if inter.get("hold_ok"):
            hold_positive_dims.append(key)
        if inter["evaluation"] != "EVALUATED" and inter.get("applicable", True):
            # Applicable incomplete dimension blocks HOLD positive proof.
            required_incomplete = True
        cat = inter.get("category")
        pressure = inter.get("pressure_state")
        if cat and pressure is not None:
            if cat not in categories_present:
                categories_present.append(cat)
            if cat not in supporting:
                supporting.append(cat)
            sell_state = _max_state(sell_state, pressure)

    # Forced terminal / hard exit already reflected via pressure_state.

    primary_reason = _pick_primary(categories_present)

    # HOLD positive proof: all applicable required dimensions evaluated clear,
    # no sell pressure, evaluation fully EVALUATED.
    hold_positive_proof = False
    if sell_state is None and not required_incomplete and evaluation == "EVALUATED":
        # Required dimensions for HOLD:
        # thesis + hard_risk + expectation + risk_reward + portfolio + opportunity
        # + catalyst (unless NOT_APPLICABLE on MEDIUM)
        # + technical (NONE or NOT_APPLICABLE)
        required_keys = [
            "thesis",
            "hard_risk",
            "expectation_price_in",
            "risk_reward",
            "portfolio_rebalance",
            "opportunity_cost",
            "catalyst",
            "technical_execution",
        ]
        hold_positive_proof = all(
            interpretations[k].get("hold_ok") for k in required_keys
        )
        if hold_positive_proof:
            sell_state = "HOLD"
            if "HOLD_POSITIVE_PROOF" not in reason_codes:
                reason_codes.append("HOLD_POSITIVE_PROOF")

    # Incomplete without any confirmed sell pressure → must not emit HOLD.
    if sell_state is None:
        # Domain state cannot be asserted as HOLD; leave null and surface eval.
        sell_state_out: str | None = None
    else:
        sell_state_out = sell_state

    # Supporting reasons = all pressure categories; primary is one of them.
    # Keep supporting as full cumulative set (primary is not removed).
    if primary_reason and primary_reason not in supporting:
        supporting.insert(0, primary_reason)

    # Authority refs: own + all input refs (deterministic order by dimension).
    authority_refs: list[str] = [AUTHORITY_REF]
    for key, dim in (
        ("thesis", thesis_i),
        ("hard_risk", risk_i),
        ("expectation_price_in", exp_i),
        ("risk_reward", rr_i),
        ("catalyst", cat_i),
        ("portfolio_rebalance", port_i),
        ("opportunity_cost", opp_i),
        ("technical_execution", tech_i),
    ):
        for ref in dim["authority_refs"]:
            if ref not in authority_refs:
                authority_refs.append(ref)

    dimension_views: dict[str, Any] = {}
    for key in _DIMENSIONS:
        inter = interpretations[key]
        dimension_views[key] = {
            "input_state": {
                "thesis": thesis_i,
                "hard_risk": risk_i,
                "expectation_price_in": exp_i,
                "risk_reward": rr_i,
                "catalyst": cat_i,
                "portfolio_rebalance": port_i,
                "opportunity_cost": opp_i,
                "technical_execution": tech_i,
            }[key]["state"],
            "pressure_state": inter.get("pressure_state"),
            "category": inter.get("category"),
            "evaluation": inter["evaluation"],
            "reason_codes": list(inter.get("reason_codes", [])),
        }

    result = {
        "schema_version": SCHEMA_VERSION,
        "authority_ref": AUTHORITY_REF,
        "security_code": sec,
        "strategy": strat,
        "campaign_id": camp,
        "as_of": as_of_s,
        "sell_state": sell_state_out,
        "sell_evaluation": evaluation,
        "primary_reason": primary_reason,
        "reason_codes": list(reason_codes),
        "supporting_reasons": list(supporting),
        "opposing_reasons": list(opposing),
        "uncertainties": list(uncertainties),
        "hold_positive_proof": hold_positive_proof,
        "authority_refs": list(authority_refs),
        "dimensions": dimension_views,
    }
    # Detach nested structures from any caller-owned input aliases.
    return copy.deepcopy(result)
