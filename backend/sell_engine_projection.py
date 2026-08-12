"""Sell Engine Projection Core v0.1 (P0-SE1 / R1).

Answers one question only:

> For a real holding Campaign, given already-normalized sell-side dimension
> conclusions (Thesis terminality + normalized sell pressures), what is the
> current sell-side state and why?

```text
Sell Engine
=
normalized sell-pressure composition authority
```

Not a BUY engine, Hard Risk engine, Thesis engine, price predictor,
technical trading system, portfolio optimizer, or AI recommender.

R1 authority boundary:

- Consumes normalized sell pressure; does not invent action severity from
  raw upstream domain facts (except Product-Authority thesis terminal map).
- Formal Thesis DISPROVEN / INVALIDATED → THESIS_INVALIDATED only.
- WEAKENED != THESIS_INVALIDATION and does not auto-create WATCH/REDUCE/EXIT.
- Hard Risk raw CONFIRMED is not an input; RISK_EXIT is normalized pressure.
- Does not own which dimensions are applicable to a Campaign.
- HOLD requires authority-backed positive proof on applicable dimensions.
- Primary reason must drive the final sell_state (no forged semantic ladder).

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

SELL_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

VALID_STRATEGIES: tuple[str, ...] = ("SHORT", "SWING", "MEDIUM")

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

# Display-only order for co-driver tie-break (NOT semantic investment priority).
_DISPLAY_TIE_BREAK_ORDER: tuple[str, ...] = (
    "THESIS_INVALIDATION",
    "RISK_EXIT",
    "EXPECTATION_PRICE_IN",
    "RISK_REWARD_DETERIORATION",
    "CATALYST_FAILURE",
    "PORTFOLIO_REBALANCE",
    "OPPORTUNITY_COST",
    "TECHNICAL_EXECUTION",
)

_STATE_RANK: dict[str, int] = {
    "HOLD": 0,
    "WATCH_TO_REDUCE": 1,
    "REDUCE": 2,
    "EXIT": 3,
    "THESIS_INVALIDATED": 4,
}

_EVAL_RANK: dict[str, int] = {
    "EVALUATED": 0,
    "UNKNOWN": 1,
    "NOT_EVALUATED": 2,
    "ERROR": 3,
}

# Thesis: Formal Current Thesis vocabulary. Only terminal map is product-frozen.
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

# Normalized sell-pressure dimensions (including RISK_EXIT consequence).
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

# Catalyst: same pressure composition + NOT_YET (not failure) + NOT_APPLICABLE.
CATALYST_INPUT_STATES: tuple[str, ...] = (
    "NONE",
    "NOT_YET",
    "WATCH",
    "REDUCE",
    "EXIT",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
    "NOT_APPLICABLE",
)

_DIMENSIONS: tuple[str, ...] = (
    "thesis",
    "risk_exit",
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

# States that assert positive semantic proof and therefore require provenance.
_INCOMPLETE_STATES = frozenset({"UNKNOWN", "NOT_EVALUATED", "ERROR", "NOT_READY"})


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

    allowed_keys = {"state", "authority_refs"}
    extra = set(value.keys()) - allowed_keys
    if extra:
        raise SellEngineValidationError(
            f"{field} has unsupported keys {sorted(extra)}; "
            "Sell Engine consumes normalized state only "
            "(no pnl/price/ai payload)"
        )

    # P1 provenance: positive semantic assertions require upstream refs.
    # Incomplete honesty states may omit refs.
    if state not in _INCOMPLETE_STATES and not refs:
        raise SellEngineValidationError(
            f"{field}.authority_refs must be non-empty for evaluated "
            f"semantic state {state!r} (caller self-asserted proof forbidden)"
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
    if state in ("NOT_EVALUATED", "NOT_READY"):
        return "NOT_EVALUATED"
    if state == "UNKNOWN":
        return "UNKNOWN"
    return None


# ---------------------------------------------------------------------------
# Dimension interpretation — composition only, no invented severity
# ---------------------------------------------------------------------------


def _interpret_thesis(dim: Mapping[str, Any]) -> dict[str, Any]:
    state = dim["state"]
    incomplete = _eval_from_incomplete_state(state)
    if incomplete is not None:
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"THESIS_{incomplete}"],
            "opposing": [],
            "uncertainties": [f"THESIS_{incomplete}"],
            "evaluation": incomplete,
            "applicable": True,
            "hold_ok": False,
            "blocks_hold": True,
        }
    if state in ("DISPROVEN", "INVALIDATED"):
        # Sole Product-Authority action transform.
        return {
            "pressure_state": "THESIS_INVALIDATED",
            "category": "THESIS_INVALIDATION",
            "reason_codes": [f"THESIS_{state}"],
            "opposing": [],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "applicable": True,
            "hold_ok": False,
            "blocks_hold": True,
        }
    if state == "WEAKENED":
        # WEAKENED != THESIS_INVALIDATION; no automatic WATCH/REDUCE/EXIT.
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": ["THESIS_WEAKENED"],
            "opposing": [],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "applicable": True,
            "hold_ok": False,
            "blocks_hold": True,
        }
    # STABLE / STRENGTHENED — no sell pressure; HOLD-positive when proven.
    return {
        "pressure_state": None,
        "category": None,
        "reason_codes": [f"THESIS_{state}_NO_SELL_PRESSURE"],
        "opposing": [f"THESIS_{state}"],
        "uncertainties": [],
        "evaluation": "EVALUATED",
        "applicable": True,
        "hold_ok": True,
        "blocks_hold": False,
    }


def _interpret_pressure_dim(
    dim: Mapping[str, Any],
    *,
    category: str,
    prefix: str,
) -> dict[str, Any]:
    state = dim["state"]
    if state == "NOT_APPLICABLE":
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"{prefix}_NOT_APPLICABLE"],
            "opposing": [f"{prefix}_NOT_APPLICABLE"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "applicable": False,
            "hold_ok": True,
            "blocks_hold": False,
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
            "applicable": True,
            "hold_ok": False,
            "blocks_hold": True,
        }
    if state == "NONE":
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"{prefix}_NONE"],
            "opposing": [f"{prefix}_NONE"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "applicable": True,
            "hold_ok": True,
            "blocks_hold": False,
        }
    # WATCH / REDUCE / EXIT — pass through without silent downgrade.
    pressure = _pressure_to_sell_state(state)
    return {
        "pressure_state": pressure,
        "category": category,
        "reason_codes": [f"{prefix}_{state}"],
        "opposing": [],
        "uncertainties": [],
        "evaluation": "EVALUATED",
        "applicable": True,
        "hold_ok": False,
        "blocks_hold": False,
    }


def _interpret_catalyst(dim: Mapping[str, Any]) -> dict[str, Any]:
    state = dim["state"]
    if state == "NOT_APPLICABLE":
        # Applicability is upstream-owned for any strategy.
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": ["CATALYST_NOT_APPLICABLE"],
            "opposing": ["CATALYST_NOT_APPLICABLE"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "applicable": False,
            "hold_ok": True,
            "blocks_hold": False,
        }
    incomplete = _eval_from_incomplete_state(state)
    if incomplete is not None:
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"CATALYST_{incomplete}"],
            "opposing": [],
            "uncertainties": [f"CATALYST_{incomplete}"],
            "evaluation": incomplete,
            "applicable": True,
            "hold_ok": False,
            "blocks_hold": True,
        }
    if state in ("NONE", "NOT_YET"):
        # NOT_YET is not failure; neither invents sell pressure.
        return {
            "pressure_state": None,
            "category": None,
            "reason_codes": [f"CATALYST_{state}"],
            "opposing": [f"CATALYST_{state}"],
            "uncertainties": [],
            "evaluation": "EVALUATED",
            "applicable": True,
            "hold_ok": True,
            "blocks_hold": False,
        }
    pressure = _pressure_to_sell_state(state)
    return {
        "pressure_state": pressure,
        "category": "CATALYST_FAILURE",
        "reason_codes": [f"CATALYST_{state}"],
        "opposing": [],
        "uncertainties": [],
        "evaluation": "EVALUATED",
        "applicable": True,
        "hold_ok": False,
        "blocks_hold": False,
    }


def _pick_primary_for_state(
    drivers: list[str],
) -> tuple[str | None, str | None, list[str]]:
    """Primary must come from reasons that drive final sell_state.

    Multiple co-drivers: display tie-break only, explicitly non-semantic.
    """
    if not drivers:
        return None, None, []
    # Preserve first-seen order for co_driving list, unique.
    ordered: list[str] = []
    for d in drivers:
        if d not in ordered:
            ordered.append(d)
    if len(ordered) == 1:
        return ordered[0], "SOLE_DRIVER", ordered
    # Display tie-break by fixed category order — not investment priority.
    for cat in _DISPLAY_TIE_BREAK_ORDER:
        if cat in ordered:
            return cat, "DISPLAY_TIE_BREAK_NOT_SEMANTIC_PRIORITY", ordered
    return ordered[0], "DISPLAY_TIE_BREAK_NOT_SEMANTIC_PRIORITY", ordered


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
    risk_exit: Mapping[str, Any],
    expectation_price_in: Mapping[str, Any],
    risk_reward: Mapping[str, Any],
    catalyst: Mapping[str, Any],
    portfolio_rebalance: Mapping[str, Any],
    opportunity_cost: Mapping[str, Any],
    technical_execution: Mapping[str, Any],
) -> dict[str, Any]:
    """Project Campaign-scoped sell-side state from normalized inputs.

    ``risk_exit`` is the normalized sell-pressure / consequence input owned by
    future Hard Risk / Action Envelope authority — not raw hard-risk state.

    Returns a detached dict. Never mutates inputs. Never reads wall clock.
    """
    sec = _require_security_code(security_code)
    strat = _require_strategy(strategy)
    camp = _require_campaign_id(campaign_id)
    as_of_s = _require_as_of(as_of)

    thesis_i = _require_dim(thesis, "thesis", THESIS_INPUT_STATES)
    risk_i = _require_dim(risk_exit, "risk_exit", PRESSURE_INPUT_STATES)
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

    interpretations: dict[str, dict[str, Any]] = {
        "thesis": _interpret_thesis(thesis_i),
        "risk_exit": _interpret_pressure_dim(
            risk_i, category="RISK_EXIT", prefix="RISK_EXIT"
        ),
        "expectation_price_in": _interpret_pressure_dim(
            exp_i,
            category="EXPECTATION_PRICE_IN",
            prefix="EXPECTATION_PRICE_IN",
        ),
        "risk_reward": _interpret_pressure_dim(
            rr_i,
            category="RISK_REWARD_DETERIORATION",
            prefix="RISK_REWARD",
        ),
        "catalyst": _interpret_catalyst(cat_i),
        "portfolio_rebalance": _interpret_pressure_dim(
            port_i,
            category="PORTFOLIO_REBALANCE",
            prefix="PORTFOLIO_REBALANCE",
        ),
        "opportunity_cost": _interpret_pressure_dim(
            opp_i,
            category="OPPORTUNITY_COST",
            prefix="OPPORTUNITY_COST",
        ),
        "technical_execution": _interpret_pressure_dim(
            tech_i,
            category="TECHNICAL_EXECUTION",
            prefix="TECHNICAL",
        ),
    }

    sell_state: str | None = None
    reason_codes: list[str] = []
    supporting: list[str] = []
    opposing: list[str] = []
    uncertainties: list[str] = []
    evaluation = "EVALUATED"
    # Drivers: (category, pressure_state) that contribute sell pressure.
    pressure_drivers: list[tuple[str, str]] = []

    hold_blocked = False
    all_hold_ok = True

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

        if inter.get("blocks_hold"):
            hold_blocked = True
            all_hold_ok = False
        elif not inter.get("hold_ok"):
            # Pressure dimensions with active pressure are not hold_ok.
            all_hold_ok = False

        cat = inter.get("category")
        pressure = inter.get("pressure_state")
        if cat and pressure is not None:
            if cat not in supporting:
                supporting.append(cat)
            pressure_drivers.append((cat, pressure))
            sell_state = _max_state(sell_state, pressure)

    # Final sell_state first; primary from drivers of that state only.
    final_state = sell_state
    drivers_for_final: list[str] = []
    if final_state is not None:
        for cat, pressure in pressure_drivers:
            if pressure == final_state:
                drivers_for_final.append(cat)

    primary_reason, primary_selection, co_driving = _pick_primary_for_state(
        drivers_for_final
    )

    # HOLD positive proof: every provided dimension is either
    # authority-backed clean applicable, or authority-backed NOT_APPLICABLE;
    # no unresolved applicable dimension; no sell pressure.
    hold_positive_proof = False
    if (
        final_state is None
        and not hold_blocked
        and all_hold_ok
        and evaluation == "EVALUATED"
    ):
        hold_positive_proof = all(
            interpretations[k].get("hold_ok") for k in _DIMENSIONS
        )
        if hold_positive_proof:
            final_state = "HOLD"
            if "HOLD_POSITIVE_PROOF" not in reason_codes:
                reason_codes.append("HOLD_POSITIVE_PROOF")

    if primary_reason and primary_reason not in supporting:
        supporting.insert(0, primary_reason)

    authority_refs: list[str] = [AUTHORITY_REF]
    input_dims = {
        "thesis": thesis_i,
        "risk_exit": risk_i,
        "expectation_price_in": exp_i,
        "risk_reward": rr_i,
        "catalyst": cat_i,
        "portfolio_rebalance": port_i,
        "opportunity_cost": opp_i,
        "technical_execution": tech_i,
    }
    for key in _DIMENSIONS:
        for ref in input_dims[key]["authority_refs"]:
            if ref not in authority_refs:
                authority_refs.append(ref)

    dimension_views: dict[str, Any] = {}
    for key in _DIMENSIONS:
        inter = interpretations[key]
        dimension_views[key] = {
            "input_state": input_dims[key]["state"],
            "pressure_state": inter.get("pressure_state"),
            "category": inter.get("category"),
            "evaluation": inter["evaluation"],
            "applicable": inter.get("applicable"),
            "reason_codes": list(inter.get("reason_codes", [])),
        }

    result = {
        "schema_version": SCHEMA_VERSION,
        "authority_ref": AUTHORITY_REF,
        "security_code": sec,
        "strategy": strat,
        "campaign_id": camp,
        "as_of": as_of_s,
        "sell_state": final_state,
        "sell_evaluation": evaluation,
        "primary_reason": primary_reason,
        "primary_reason_selection": primary_selection,
        "co_driving_reasons": list(co_driving),
        "reason_codes": list(reason_codes),
        "supporting_reasons": list(supporting),
        "opposing_reasons": list(opposing),
        "uncertainties": list(uncertainties),
        "hold_positive_proof": hold_positive_proof,
        "authority_refs": list(authority_refs),
        "dimensions": dimension_views,
    }
    return copy.deepcopy(result)
