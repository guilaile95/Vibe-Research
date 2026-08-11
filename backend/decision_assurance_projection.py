"""Decision Assurance Coverage Core v0.1 (P0-RA1) — pure domain only.

Answers one question only:

> For this Campaign, were the required decision dimensions actually evaluated?

Does NOT answer safety, Hard Risk, Material Change, recommendation generation,
or Inbox visible state.

```text
COVERAGE != SAFETY
UNKNOWN != NOT_EVALUATED
ERROR != UNKNOWN
```

Temporal contract (R1):

```text
as_of must be an explicit UTC zero-offset instant string.
All five evaluation statuses must be normalized by the caller
AS OF that same supplied as_of (not "ever ran historically").
```

RA1 does not compute freshness/TTL. Callers must not map stale domain results
to EVALUATED unless temporally applicable to as_of.

Pure domain boundary:
- no I/O, SQLite, filesystem, env, network, HTTP frameworks, AI, wall clock
- no imports of thesis / decision / risk / health / cockpit / advice authorities
- consumes only explicit normalized evaluation status inputs
- parsing supplied UTC as_of is allowed; never read wall clock
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone

SCHEMA_VERSION = "decision_assurance.coverage.v0.1"

REQUIRED_DIMENSIONS: tuple[str, ...] = (
    "FORMAL_THESIS",
    "FORMAL_DECISION",
    "HARD_RISK",
    "MATERIAL_CHANGE",
    "CRITICAL_DATA",
)

EVALUATION_STATES: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

# Completed evaluation path (coverage may still be complete):
# EVALUATED = authority ran and produced a legal domain result (any severity)
# UNKNOWN   = authority ran but could not adjudicate
_COMPLETED_STATES = frozenset({"EVALUATED", "UNKNOWN"})

# Incomplete evaluation path:
# NOT_EVALUATED = never ran / not wired / missing capability
# ERROR         = integrity/corruption/unexpected failure on evaluation path
_INCOMPLETE_STATES = frozenset({"NOT_EVALUATED", "ERROR"})

VALID_STRATEGIES = ("SHORT", "SWING", "MEDIUM")

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")

# Strict allowlist of UTC zero-offset instant forms only (no non-zero offsets,
# no naive local times, no date-only, no silent timezone conversion).
# Accepted:
#   2026-08-12T00:00:00Z
#   2026-08-12T00:00:00.000000Z   (1..6 fractional digits)
#   2026-08-12T00:00:00+00:00
#   2026-08-12T00:00:00.000000+00:00
_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)

_INPUT_KEY_BY_DIMENSION: dict[str, str] = {
    "FORMAL_THESIS": "formal_thesis_evaluation",
    "FORMAL_DECISION": "formal_decision_evaluation",
    "HARD_RISK": "hard_risk_evaluation",
    "MATERIAL_CHANGE": "material_change_evaluation",
    "CRITICAL_DATA": "critical_data_evaluation",
}


class DecisionAssuranceError(Exception):
    """Decision Assurance domain base error."""


class AssuranceIntegrityError(DecisionAssuranceError):
    """Illegal input / contract violation → fail closed."""


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssuranceIntegrityError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise AssuranceIntegrityError(f"{field} must not have leading/trailing whitespace")
    return value


def _require_security_code(value: object) -> str:
    code = _require_nonempty_str(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise AssuranceIntegrityError(
            "security_code must be a 6-digit A-share code"
        )
    return code


def _require_strategy(value: object) -> str:
    strategy = _require_nonempty_str(value, "strategy")
    if strategy not in VALID_STRATEGIES:
        raise AssuranceIntegrityError(
            f"strategy must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object) -> str:
    campaign_id = _require_nonempty_str(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise AssuranceIntegrityError(
            "campaign_id must match campaign_<32 lowercase hex>"
        )
    return campaign_id


def _require_as_of(value: object) -> str:
    """Strict UTC zero-offset instant; preserve exact accepted string.

    Does not convert non-UTC offsets. Does not invent wall-clock time.
    """
    as_of = _require_nonempty_str(value, "as_of")
    if not any(pattern.fullmatch(as_of) for pattern in _AS_OF_UTC_FORMS):
        raise AssuranceIntegrityError(
            "as_of must be a canonical UTC zero-offset instant "
            "(...Z or ...+00:00); non-zero offsets and naive times are rejected"
        )
    # Parse-validate calendar components; Z is not accepted by fromisoformat
    # until Python 3.11 in all forms — normalize only for parse, keep original.
    parse_text = as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise AssuranceIntegrityError(
            f"as_of is not a deterministically parseable UTC instant: {as_of!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise AssuranceIntegrityError("as_of must be timezone-aware UTC")
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise AssuranceIntegrityError("as_of must use UTC zero offset only")
    # Round-trip sanity: equivalent instant in UTC.
    _ = parsed.astimezone(timezone.utc)
    return as_of


def _require_evaluation_state(value: object, field: str) -> str:
    if not isinstance(value, str) or value not in EVALUATION_STATES:
        raise AssuranceIntegrityError(
            f"{field} must be one of {EVALUATION_STATES}, got {value!r}"
        )
    return value


def _collect_dimension_states(payload: dict) -> dict[str, str]:
    """Require all five keys; fail closed on missing/extra/duplicate semantics."""
    if type(payload) is not dict:
        raise AssuranceIntegrityError("evaluation payload must be a dict")

    expected_keys = set(_INPUT_KEY_BY_DIMENSION.values())
    actual_keys = set(payload.keys())
    missing = expected_keys - actual_keys
    if missing:
        raise AssuranceIntegrityError(
            f"missing required evaluation field(s): {sorted(missing)}"
        )
    extra = actual_keys - expected_keys
    if extra:
        raise AssuranceIntegrityError(
            f"unknown evaluation field(s): {sorted(extra)}"
        )

    states: dict[str, str] = {}
    for dimension, key in _INPUT_KEY_BY_DIMENSION.items():
        states[dimension] = _require_evaluation_state(payload[key], key)
    return states


def project_decision_assurance(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    formal_thesis_evaluation: str,
    formal_decision_evaluation: str,
    hard_risk_evaluation: str,
    material_change_evaluation: str,
    critical_data_evaluation: str,
    as_of: str,
) -> dict:
    """Project evaluation coverage for one Security + Strategy + Campaign unit.

    Pure function of explicit normalized evaluation statuses.
    Does not interpret domain safety of EVALUATED results.

    Caller contract: each evaluation status must already be normalized as
    applicable **as of** the supplied ``as_of`` instant (same temporal context
    for all five dimensions). Historical "once ran" results must not be mapped
    to EVALUATED unless still temporally applicable at ``as_of``.
    """
    sec = _require_security_code(security_code)
    strat = _require_strategy(strategy)
    camp = _require_campaign_id(campaign_id)
    as_of_value = _require_as_of(as_of)

    states = _collect_dimension_states(
        {
            "formal_thesis_evaluation": formal_thesis_evaluation,
            "formal_decision_evaluation": formal_decision_evaluation,
            "hard_risk_evaluation": hard_risk_evaluation,
            "material_change_evaluation": material_change_evaluation,
            "critical_data_evaluation": critical_data_evaluation,
        }
    )

    evaluated: list[str] = []
    unknown: list[str] = []
    not_evaluated: list[str] = []
    errors: list[str] = []

    # Stable order = REQUIRED_DIMENSIONS order (not input key order).
    for dimension in REQUIRED_DIMENSIONS:
        state = states[dimension]
        if state == "EVALUATED":
            evaluated.append(dimension)
        elif state == "UNKNOWN":
            unknown.append(dimension)
        elif state == "NOT_EVALUATED":
            not_evaluated.append(dimension)
        else:
            # ERROR
            errors.append(dimension)

    # Coverage complete iff every required dimension completed evaluation
    # (EVALUATED or UNKNOWN). ERROR and NOT_EVALUATED are incomplete.
    coverage_complete = (
        len(not_evaluated) == 0
        and len(errors) == 0
        and (len(evaluated) + len(unknown)) == len(REQUIRED_DIMENSIONS)
    )

    # Defensive invariant: complete means only completed states.
    if coverage_complete:
        for dimension in REQUIRED_DIMENSIONS:
            if states[dimension] not in _COMPLETED_STATES:
                raise AssuranceIntegrityError(
                    "internal coverage invariant violated"
                )
    else:
        # incomplete must have at least one incomplete state
        if not (not_evaluated or errors):
            # should be unreachable given definitions
            raise AssuranceIntegrityError(
                "internal incompleteness invariant violated"
            )

    # Detached lists/tuples — no shared mutables with inputs (inputs are strs).
    evaluated_out = list(evaluated)
    unknown_out = list(unknown)
    not_evaluated_out = list(not_evaluated)
    errors_out = list(errors)
    required_out = list(REQUIRED_DIMENSIONS)

    coverage_summary = {
        "required_count": len(REQUIRED_DIMENSIONS),
        "evaluated_count": len(evaluated_out),
        "unknown_count": len(unknown_out),
        "not_evaluated_count": len(not_evaluated_out),
        "error_count": len(errors_out),
        "completed_count": len(evaluated_out) + len(unknown_out),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "security_code": sec,
        "strategy": strat,
        "campaign_id": camp,
        "as_of": as_of_value,
        "required_dimensions": required_out,
        "evaluated_dimensions": evaluated_out,
        "unknown_dimensions": unknown_out,
        "not_evaluated_dimensions": not_evaluated_out,
        "error_dimensions": errors_out,
        "coverage_complete": coverage_complete,
        "coverage_summary": copy.deepcopy(coverage_summary),
        "dimension_states": {
            dimension: states[dimension] for dimension in REQUIRED_DIMENSIONS
        },
    }


__all__ = [
    "SCHEMA_VERSION",
    "REQUIRED_DIMENSIONS",
    "EVALUATION_STATES",
    "VALID_STRATEGIES",
    "DecisionAssuranceError",
    "AssuranceIntegrityError",
    "project_decision_assurance",
]
