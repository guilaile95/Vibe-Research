"""Decision Challenge Coverage Authority v0.1 (P0-DC1).

Answers one question only:

> For a Security + Strategy + Campaign Formal Decision, if upstream already
> requires a Decision Challenge, are the required counter-evidence / challenge
> dimensions actually evaluated, and is Two-Pass Review structurally present?

```text
CHALLENGE COVERAGE
!=
DECISION CORRECTNESS
!=
DECISION APPROVAL
```

DC1 does not decide whether a decision is "important". It consumes an
explicit upstream ``challenge_requirement``.

DC1 does not select strongest evidence, generate pre-mortems, discover
invalidation facts, or prove that a second pass was semantically independent.

Identity is reused from the stable Frozen Decision contract:

```text
security_code = 6-digit A-share
strategy      = SHORT | SWING | MEDIUM
campaign_id   = campaign_<32 lowercase hex>
decision_id   = decision_<32 lowercase hex>
```

Regexes are copied (pure domain). This module does not import
frozen_decision_store / RA1 / EC1 / Sell / Risk Budget / Drawdown.

Pure domain: no I/O / SQLite / filesystem / env / network / FastAPI / AI /
wall clock / persistence.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Mapping

SCHEMA_VERSION = "decision_challenge.projection.v0.1"
AUTHORITY_REF = "dc:decision_challenge_projection:v0.1"

POLICY_VERSION_V01 = "dc.decision_challenge.v0.1"
POLICY_AUTHORITY_REF_V01 = "dc:decision_challenge_policy:v0.1"

VALID_STRATEGIES: tuple[str, ...] = ("SHORT", "SWING", "MEDIUM")

CHALLENGE_REQUIREMENTS: tuple[str, ...] = (
    "REQUIRED",
    "NOT_REQUIRED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

REQUIRED_DIMENSIONS: tuple[str, ...] = (
    "STRONGEST_SUPPORTING_EVIDENCE",
    "STRONGEST_OPPOSING_EVIDENCE",
    "PRE_MORTEM",
    "INVALIDATION_FACTS",
)

DIMENSION_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

PACKET_STATES: tuple[str, ...] = (
    "COMPLETE",
    "INCOMPLETE",
    "NOT_APPLICABLE",
)

CHALLENGE_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

TWO_PASS_STATES: tuple[str, ...] = (
    "VALID",
    "INCOMPLETE",
    "NOT_APPLICABLE",
)

_COVERED_DIMENSION_STATES = frozenset({"EVALUATED", "UNKNOWN"})

_POLICY_REGISTRY: dict[str, str] = {
    POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01,
}

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_DECISION_ID_RE = re.compile(r"^decision_[0-9a-f]{32}$")

_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)

_FORBIDDEN_ACTION_VOCAB: frozenset[str] = frozenset(
    {
        "BUY NOW",
        "BUY_SMALL",
        "BUY SMALL",
        "SCALE IN",
        "SCALE_IN",
        "WAIT",
        "HOLD",
        "WATCH TO REDUCE",
        "WATCH_TO_REDUCE",
        "REDUCE",
        "EXIT",
        "AVOID",
        "RESEARCH MORE",
        "RESEARCH_MORE",
    }
)

_REASON_BY_DIMENSION_STATE: dict[tuple[str, str], str] = {
    ("STRONGEST_SUPPORTING_EVIDENCE", "NOT_EVALUATED"): (
        "SUPPORTING_EVIDENCE_NOT_EVALUATED"
    ),
    ("STRONGEST_SUPPORTING_EVIDENCE", "ERROR"): "SUPPORTING_EVIDENCE_ERROR",
    ("STRONGEST_OPPOSING_EVIDENCE", "NOT_EVALUATED"): (
        "OPPOSING_EVIDENCE_NOT_EVALUATED"
    ),
    ("STRONGEST_OPPOSING_EVIDENCE", "ERROR"): "OPPOSING_EVIDENCE_ERROR",
    ("PRE_MORTEM", "NOT_EVALUATED"): "PRE_MORTEM_NOT_EVALUATED",
    ("PRE_MORTEM", "ERROR"): "PRE_MORTEM_ERROR",
    ("INVALIDATION_FACTS", "NOT_EVALUATED"): "INVALIDATION_FACTS_NOT_EVALUATED",
    ("INVALIDATION_FACTS", "ERROR"): "INVALIDATION_FACTS_ERROR",
}


class DecisionChallengeError(Exception):
    """Decision Challenge domain base error."""


class DecisionChallengeValidationError(DecisionChallengeError, ValueError):
    """Illegal caller input / contract violation → fail closed."""


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionChallengeValidationError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise DecisionChallengeValidationError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def _require_security_code(value: object) -> str:
    code = _require_nonempty_str(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise DecisionChallengeValidationError(
            "security_code must be a 6-digit A-share code"
        )
    return code


def _require_strategy(value: object) -> str:
    strategy = _require_nonempty_str(value, "strategy")
    if strategy not in VALID_STRATEGIES:
        raise DecisionChallengeValidationError(
            f"strategy must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object) -> str:
    campaign_id = _require_nonempty_str(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise DecisionChallengeValidationError(
            "campaign_id must match campaign_<32 lowercase hex>"
        )
    return campaign_id


def _require_decision_id(value: object) -> str:
    decision_id = _require_nonempty_str(value, "decision_id")
    if _DECISION_ID_RE.fullmatch(decision_id) is None:
        raise DecisionChallengeValidationError(
            "decision_id must match decision_<32 lowercase hex> "
            "(frozen_decision_store contract)"
        )
    return decision_id


def _parse_utc_instant(value: object, field: str) -> tuple[str, datetime]:
    raw = _require_nonempty_str(value, field)
    if not any(p.fullmatch(raw) for p in _AS_OF_UTC_FORMS):
        raise DecisionChallengeValidationError(
            f"{field} must be a UTC zero-offset instant "
            "(...Z or ...+00:00); wall clock is forbidden"
        )
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionChallengeValidationError(
            f"{field} is not a parseable UTC instant: {raw!r}"
        ) from exc
    if dt.tzinfo is None or dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise DecisionChallengeValidationError(
            f"{field} must be zero-offset UTC (Z or +00:00)"
        )
    return raw, dt


def _require_authority_refs(value: object, field: str) -> list[str]:
    if value is None:
        raise DecisionChallengeValidationError(f"{field} is required")
    if not isinstance(value, (list, tuple)):
        raise DecisionChallengeValidationError(
            f"{field} must be a list/tuple of strings"
        )
    if len(value) == 0:
        raise DecisionChallengeValidationError(
            f"{field} must be non-empty (naked self-asserted proof rejected; "
            "refs are provenance witnesses, not verified bindings)"
        )
    refs: list[str] = []
    for i, ref in enumerate(value):
        if not isinstance(ref, str) or not ref.strip() or ref != ref.strip():
            raise DecisionChallengeValidationError(
                f"{field}[{i}] must be a non-empty stripped string"
            )
        refs.append(ref)
    return refs


def _optional_authority_refs(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise DecisionChallengeValidationError(
            f"{field} must be a list/tuple of strings"
        )
    refs: list[str] = []
    for i, ref in enumerate(value):
        if not isinstance(ref, str) or not ref.strip() or ref != ref.strip():
            raise DecisionChallengeValidationError(
                f"{field}[{i}] must be a non-empty stripped string"
            )
        refs.append(ref)
    return refs


def _require_enum(value: object, field: str, allowed: tuple[str, ...]) -> str:
    text = _require_nonempty_str(value, field)
    if text not in allowed:
        raise DecisionChallengeValidationError(
            f"{field} must be one of {allowed}, got {text!r}"
        )
    return text


def _normalize_dimension_results(
    value: object, *, required: bool
) -> dict[str, dict[str, Any]]:
    if value is None:
        if required:
            raise DecisionChallengeValidationError("dimension_results is required")
        return {}
    if not isinstance(value, Mapping):
        raise DecisionChallengeValidationError("dimension_results must be a mapping")

    if required:
        missing = [d for d in REQUIRED_DIMENSIONS if d not in value]
        extra = [k for k in value.keys() if k not in REQUIRED_DIMENSIONS]
        if missing:
            raise DecisionChallengeValidationError(
                f"dimension_results missing required dimension(s): {missing}"
            )
        if extra:
            raise DecisionChallengeValidationError(
                f"dimension_results has unknown dimension(s): {sorted(extra)}"
            )

    out: dict[str, dict[str, Any]] = {}
    keys = REQUIRED_DIMENSIONS if required else tuple(
        k for k in REQUIRED_DIMENSIONS if k in value
    )
    for dim in keys:
        raw = value[dim]
        if not isinstance(raw, Mapping):
            raise DecisionChallengeValidationError(
                f"dimension_results[{dim}] must be a mapping"
            )
        evaluation = _require_enum(
            raw.get("evaluation"),
            f"dimension_results[{dim}].evaluation",
            DIMENSION_EVALUATIONS,
        )
        refs_field = f"dimension_results[{dim}].authority_refs"
        if evaluation in _COVERED_DIMENSION_STATES:
            refs = _require_authority_refs(raw.get("authority_refs"), refs_field)
        else:
            refs = _optional_authority_refs(raw.get("authority_refs"), refs_field)
        artifact_refs = _optional_authority_refs(
            raw.get("artifact_refs"),
            f"dimension_results[{dim}].artifact_refs",
        )
        out[dim] = {
            "evaluation": evaluation,
            "authority_refs": list(refs),
            "artifact_refs": list(artifact_refs),
        }
    return out


def _collect_two_pass(
    *,
    first_pass_ref: object,
    first_pass_at: object,
    second_pass_ref: object,
    second_pass_at: object,
    as_of_dt: datetime,
    required: bool,
) -> tuple[str, str | None, str | None, str | None, str | None, str | None]:
    fields = (first_pass_ref, first_pass_at, second_pass_ref, second_pass_at)
    any_present = any(f is not None and f != "" for f in fields)
    all_present = all(f is not None and f != "" for f in fields)

    if not required and not any_present:
        return "NOT_APPLICABLE", None, None, None, None, None

    if required and not all_present:
        first_s = (
            _require_nonempty_str(first_pass_ref, "first_pass_ref")
            if first_pass_ref not in (None, "")
            else None
        )
        second_s = (
            _require_nonempty_str(second_pass_ref, "second_pass_ref")
            if second_pass_ref not in (None, "")
            else None
        )
        return "INCOMPLETE", first_s, None, second_s, None, "TWO_PASS_INCOMPLETE"

    if any_present and not all_present:
        raise DecisionChallengeValidationError(
            "two-pass fields must be supplied together "
            "(first_pass_ref/at and second_pass_ref/at)"
        )

    first_s = _require_nonempty_str(first_pass_ref, "first_pass_ref")
    second_s = _require_nonempty_str(second_pass_ref, "second_pass_ref")
    if first_s == second_s:
        raise DecisionChallengeValidationError(
            "first_pass_ref must differ from second_pass_ref"
        )
    first_at_s, first_dt = _parse_utc_instant(first_pass_at, "first_pass_at")
    second_at_s, second_dt = _parse_utc_instant(second_pass_at, "second_pass_at")
    if second_dt < first_dt:
        raise DecisionChallengeValidationError(
            "second_pass_at must be >= first_pass_at"
        )
    if first_dt > as_of_dt or second_dt > as_of_dt:
        raise DecisionChallengeValidationError(
            "pass timestamps must be <= as_of (future review rejected)"
        )
    return "VALID", first_s, first_at_s, second_s, second_at_s, None


def project_decision_challenge(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    decision_id: str,
    as_of: str,
    policy_version: str,
    challenge_requirement: str,
    challenge_requirement_authority_refs: object,
    dimension_results: object = None,
    first_pass_ref: object = None,
    first_pass_at: object = None,
    second_pass_ref: object = None,
    second_pass_at: object = None,
) -> dict[str, Any]:
    """Project Decision Challenge coverage for one Formal Decision.

    ``challenge_requirement`` is an explicit upstream input. DC1 never infers
    REQUIRED from BUY/SELL vocabulary. ``policy_version`` is required
    (no default / latest / as_of selection).
    """
    sec = _require_security_code(security_code)
    strat = _require_strategy(strategy)
    camp = _require_campaign_id(campaign_id)
    dec = _require_decision_id(decision_id)
    as_of_s, as_of_dt = _parse_utc_instant(as_of, "as_of")
    version = _require_nonempty_str(policy_version, "policy_version")
    requirement = _require_enum(
        challenge_requirement, "challenge_requirement", CHALLENGE_REQUIREMENTS
    )
    req_refs = _require_authority_refs(
        challenge_requirement_authority_refs,
        "challenge_requirement_authority_refs",
    )

    reason_codes: list[str] = []
    policy_ref = _POLICY_REGISTRY.get(version)
    if policy_ref is None:
        reason_codes.append("POLICY_VERSION_NOT_AVAILABLE")

    packet_needed = requirement == "REQUIRED"
    dims = _normalize_dimension_results(dimension_results, required=packet_needed)
    two_pass_state, first_s, first_at_s, second_s, second_at_s, two_pass_reason = (
        _collect_two_pass(
            first_pass_ref=first_pass_ref,
            first_pass_at=first_pass_at,
            second_pass_ref=second_pass_ref,
            second_pass_at=second_pass_at,
            as_of_dt=as_of_dt,
            required=packet_needed,
        )
    )
    if two_pass_reason:
        reason_codes.append(two_pass_reason)

    covered: list[str] = []
    unknown_dims: list[str] = []
    incomplete_dims: list[str] = []
    error_dims: list[str] = []
    dim_out: dict[str, dict[str, Any]] = {}
    for dim in REQUIRED_DIMENSIONS:
        if dim not in dims:
            continue
        row = dims[dim]
        ev = row["evaluation"]
        dim_out[dim] = copy.deepcopy(row)
        if ev == "EVALUATED":
            covered.append(dim)
        elif ev == "UNKNOWN":
            covered.append(dim)
            unknown_dims.append(dim)
        elif ev == "NOT_EVALUATED":
            incomplete_dims.append(dim)
            reason_codes.append(_REASON_BY_DIMENSION_STATE[(dim, ev)])
        else:
            error_dims.append(dim)
            reason_codes.append(_REASON_BY_DIMENSION_STATE[(dim, ev)])

    # Requirement uncertainty must not collapse to NOT_APPLICABLE.
    if requirement == "NOT_REQUIRED" and policy_ref is not None:
        packet_state = "NOT_APPLICABLE"
        evaluation = "EVALUATED"
        reason_codes.append("CHALLENGE_NOT_REQUIRED")
    elif requirement == "UNKNOWN":
        packet_state = "INCOMPLETE"
        evaluation = "UNKNOWN"
        reason_codes.append("CHALLENGE_REQUIREMENT_UNKNOWN")
    elif requirement == "NOT_EVALUATED":
        packet_state = "INCOMPLETE"
        evaluation = "NOT_EVALUATED"
        reason_codes.append("CHALLENGE_REQUIREMENT_NOT_EVALUATED")
    elif requirement == "ERROR":
        packet_state = "INCOMPLETE"
        evaluation = "ERROR"
        reason_codes.append("CHALLENGE_REQUIREMENT_ERROR")
    elif policy_ref is None:
        packet_state = "INCOMPLETE"
        evaluation = "NOT_EVALUATED"
    elif error_dims:
        packet_state = "INCOMPLETE"
        evaluation = "ERROR"
    elif incomplete_dims or two_pass_state != "VALID":
        packet_state = "INCOMPLETE"
        evaluation = "NOT_EVALUATED"
        if two_pass_state != "VALID" and "TWO_PASS_INCOMPLETE" not in reason_codes:
            reason_codes.append("TWO_PASS_INCOMPLETE")
    elif unknown_dims:
        packet_state = "COMPLETE"
        evaluation = "UNKNOWN"
        reason_codes.append("CHALLENGE_PACKET_COVERED_WITH_UNKNOWN")
    else:
        packet_state = "COMPLETE"
        evaluation = "EVALUATED"
        reason_codes.append("CHALLENGE_PACKET_COMPLETE")

    # Stable unique reasons (preserve first-seen order).
    seen: set[str] = set()
    unique_reasons: list[str] = []
    for code in reason_codes:
        if code not in seen:
            seen.add(code)
            unique_reasons.append(code)

    authority_refs = [AUTHORITY_REF]
    if policy_ref is not None:
        authority_refs.append(policy_ref)
    for ref in req_refs:
        if ref not in authority_refs:
            authority_refs.append(ref)
    for dim in REQUIRED_DIMENSIONS:
        if dim not in dim_out:
            continue
        for ref in dim_out[dim]["authority_refs"] + dim_out[dim]["artifact_refs"]:
            if ref not in authority_refs:
                authority_refs.append(ref)
    for ref in (first_s, second_s):
        if ref and ref not in authority_refs:
            authority_refs.append(ref)

    result = {
        "schema_version": SCHEMA_VERSION,
        "authority_ref": AUTHORITY_REF,
        "policy_version": version,
        "policy_authority_ref": policy_ref,
        "security_code": sec,
        "strategy": strat,
        "campaign_id": camp,
        "decision_id": dec,
        "as_of": as_of_s,
        "challenge_requirement": requirement,
        "challenge_packet_state": packet_state,
        "challenge_evaluation": evaluation,
        "dimension_results": copy.deepcopy(dim_out),
        "covered_dimensions": list(covered),
        "unknown_dimensions": list(unknown_dims),
        "incomplete_dimensions": list(incomplete_dims) + list(error_dims),
        "two_pass_state": two_pass_state,
        "first_pass_ref": first_s,
        "first_pass_at": first_at_s,
        "second_pass_ref": second_s,
        "second_pass_at": second_at_s,
        "reason_codes": unique_reasons,
        "challenge_requirement_authority_refs": list(req_refs),
        "authority_refs": authority_refs,
        "explainability": {
            "why_this_state": (
                f"challenge_requirement={requirement}; "
                f"challenge_packet_state={packet_state}; "
                f"challenge_evaluation={evaluation}; "
                f"two_pass_state={two_pass_state}; "
                f"reasons={','.join(unique_reasons)}"
            ),
            "required_dimensions": list(REQUIRED_DIMENSIONS),
            "note": (
                "CHALLENGE_COVERAGE_NE_DECISION_CORRECTNESS; "
                "CHALLENGE_COVERAGE_NE_DECISION_APPROVAL; "
                "DC1_DECIDES_IMPORTANCE=NO; "
                "STRONGEST_EVIDENCE_SELECTION_OWNED_BY_DC1=NO; "
                "STRONGEST_SELECTION_BINDING_VERIFIED=NO; "
                "TWO_PASS_STRUCTURE_VERIFIED="
                f"{'YES' if two_pass_state == 'VALID' else 'NO'}; "
                "TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED=NO; "
                "UNKNOWN_EQUALS_POSITIVE_EVIDENCE=NO; "
                "UPSTREAM_AUTHORITY_BINDING_VERIFIED=NO"
            ),
        },
    }

    flat_values: list[str] = []
    for v in result.values():
        if isinstance(v, str):
            flat_values.append(v)
        elif isinstance(v, list):
            flat_values.extend(x for x in v if isinstance(x, str))
    for token in _FORBIDDEN_ACTION_VOCAB:
        if token in flat_values:
            raise DecisionChallengeValidationError(
                f"internal integrity: forbidden action token {token!r}"
            )

    return copy.deepcopy(result)
