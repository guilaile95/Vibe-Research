"""Campaign Critical Data Usability Projection Core v0.1 (P0-CCD1).

Answers one question only:

> Given an explicitly resolved required dependency set for
> Security + Strategy + Campaign, and normalized per-dependency
> evaluation results applicable at the same as_of, what is this
> Campaign's Critical Data usability?

```text
dataset/source health facts
  → campaign-specific required dependency evaluation
  → campaign-level decision usability
```

Not a second Data Health system.

Ownership boundary:

- OWNS: resolved dependency set + normalized dependency results
  → critical_data_state + critical_data_evaluation + reasons
- DOES NOT OWN: which dependencies a strategy should require,
  strategy templates, thesis/campaign/frozen persistence,
  provider/Fact Lake health collection, DI precedence, RA1 coverage,
  Hard Risk, Material Change.

Dependency definition authority is upstream / not yet implemented.
CCD1 therefore requires an explicit normalized dependency-set input and
MUST NOT infer required dependencies from strategy, thesis, holdings, or
available datasets.

Pure domain boundary:
- no I/O, SQLite, filesystem, env, network, FastAPI, AI, wall clock
- no imports of data_health / fact_lake_health / portfolio_advice /
  decision_cockpit / thesis / frozen decision authorities
- consumes only explicit normalized inputs
- parsing supplied UTC as_of is allowed; never read wall clock
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "campaign_critical_data.projection.v0.1"

# ---------------------------------------------------------------------------
# Enumerations (string values; comparisons use ==, never ``is``)
# ---------------------------------------------------------------------------

DEPENDENCY_SET_STATES: tuple[str, ...] = (
    "RESOLVED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

DEPENDENCY_RESULT_STATES: tuple[str, ...] = (
    "USABLE",
    "BLOCKED",
    "STALE",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

CRITICAL_DATA_STATES: tuple[str, ...] = (
    "USABLE",
    "BLOCKED",
    "UNKNOWN",
    "STALE",
)

CRITICAL_DATA_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

VALID_STRATEGIES: tuple[str, ...] = ("SHORT", "SWING", "MEDIUM")

# Cumulative reason codes (deterministic order defined by REASON_ORDER).
REASON_DEPENDENCY_SET_UNKNOWN = "DEPENDENCY_SET_UNKNOWN"
REASON_DEPENDENCY_SET_NOT_EVALUATED = "DEPENDENCY_SET_NOT_EVALUATED"
REASON_DEPENDENCY_SET_ERROR = "DEPENDENCY_SET_ERROR"
REASON_DEPENDENCY_SET_AUTHORITATIVELY_EMPTY = (
    "DEPENDENCY_SET_AUTHORITATIVELY_EMPTY"
)
REASON_DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
REASON_DEPENDENCY_STALE = "DEPENDENCY_STALE"
REASON_DEPENDENCY_UNKNOWN = "DEPENDENCY_UNKNOWN"
REASON_DEPENDENCY_NOT_EVALUATED = "DEPENDENCY_NOT_EVALUATED"
REASON_DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
REASON_ALL_DEPENDENCIES_USABLE = "ALL_DEPENDENCIES_USABLE"

REASON_CODES: tuple[str, ...] = (
    REASON_DEPENDENCY_SET_ERROR,
    REASON_DEPENDENCY_SET_NOT_EVALUATED,
    REASON_DEPENDENCY_SET_UNKNOWN,
    REASON_DEPENDENCY_SET_AUTHORITATIVELY_EMPTY,
    REASON_DEPENDENCY_BLOCKED,
    REASON_DEPENDENCY_STALE,
    REASON_DEPENDENCY_UNKNOWN,
    REASON_DEPENDENCY_NOT_EVALUATED,
    REASON_DEPENDENCY_ERROR,
    REASON_ALL_DEPENDENCIES_USABLE,
)

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")

# Strict allowlist of UTC zero-offset instant forms only.
_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)

# Domain-state severity for RESOLVED sets (DI-facing).
# BLOCKED > STALE > UNKNOWN > USABLE
_DOMAIN_SEVERITY: dict[str, int] = {
    "BLOCKED": 3,
    "STALE": 2,
    "UNKNOWN": 1,
    "USABLE": 0,
}

# Evaluation-path severity (RA1-facing).
# ERROR > NOT_EVALUATED > UNKNOWN > EVALUATED
_EVAL_SEVERITY: dict[str, int] = {
    "ERROR": 3,
    "NOT_EVALUATED": 2,
    "UNKNOWN": 1,
    "EVALUATED": 0,
}

# Map a dependency result state into the DI domain state axis.
# NOT_EVALUATED / ERROR collapse to UNKNOWN for DI (not new DI states).
_RESULT_TO_DOMAIN: dict[str, str] = {
    "USABLE": "USABLE",
    "BLOCKED": "BLOCKED",
    "STALE": "STALE",
    "UNKNOWN": "UNKNOWN",
    "NOT_EVALUATED": "UNKNOWN",
    "ERROR": "UNKNOWN",
}

# Map a dependency result state into the RA1 evaluation axis.
_RESULT_TO_EVAL: dict[str, str] = {
    "USABLE": "EVALUATED",
    "BLOCKED": "EVALUATED",
    "STALE": "EVALUATED",
    "UNKNOWN": "UNKNOWN",
    "NOT_EVALUATED": "NOT_EVALUATED",
    "ERROR": "ERROR",
}

_RESULT_REASON: dict[str, str] = {
    "BLOCKED": REASON_DEPENDENCY_BLOCKED,
    "STALE": REASON_DEPENDENCY_STALE,
    "UNKNOWN": REASON_DEPENDENCY_UNKNOWN,
    "NOT_EVALUATED": REASON_DEPENDENCY_NOT_EVALUATED,
    "ERROR": REASON_DEPENDENCY_ERROR,
}


class CampaignCriticalDataError(Exception):
    """Campaign Critical Data domain base error."""


class CriticalDataIntegrityError(CampaignCriticalDataError):
    """Illegal input / contract violation → fail closed."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CriticalDataIntegrityError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise CriticalDataIntegrityError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def _require_security_code(value: object) -> str:
    code = _require_nonempty_str(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise CriticalDataIntegrityError(
            "security_code must be a 6-digit A-share code"
        )
    return code


def _require_strategy(value: object) -> str:
    strategy = _require_nonempty_str(value, "strategy")
    if strategy not in VALID_STRATEGIES:
        raise CriticalDataIntegrityError(
            f"strategy must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object) -> str:
    campaign_id = _require_nonempty_str(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise CriticalDataIntegrityError(
            "campaign_id must match campaign_<32 lowercase hex>"
        )
    return campaign_id


def _require_as_of(value: object, field: str = "as_of") -> str:
    """Strict UTC zero-offset instant; preserve exact accepted string.

    Does not convert non-UTC offsets. Does not invent wall-clock time.
    """
    as_of = _require_nonempty_str(value, field)
    if not any(pattern.fullmatch(as_of) for pattern in _AS_OF_UTC_FORMS):
        raise CriticalDataIntegrityError(
            f"{field} must be a canonical UTC zero-offset instant "
            "(...Z or ...+00:00); non-zero offsets and naive times are rejected"
        )
    parse_text = as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise CriticalDataIntegrityError(
            f"{field} is not a deterministically parseable UTC instant: {as_of!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise CriticalDataIntegrityError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise CriticalDataIntegrityError(
            f"{field} must use UTC zero offset only"
        )
    _ = parsed.astimezone(timezone.utc)
    return as_of


def _require_enum(value: object, field: str, allowed: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise CriticalDataIntegrityError(
            f"{field} must be one of {tuple(allowed)}, got {value!r}"
        )
    return value


def _require_authority_refs(value: object, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise CriticalDataIntegrityError(
            f"{field} must be a list/tuple of non-empty strings"
        )
    refs: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise CriticalDataIntegrityError(
                f"{field}[{index}] must be a non-empty trimmed string"
            )
        refs.append(item)
    return refs


def _require_dependency_id(value: object, field: str) -> str:
    return _require_nonempty_str(value, field)


def _normalize_required_ids(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise CriticalDataIntegrityError(
            "required_dependency_ids must be a list/tuple of dependency ids"
        )
    ids: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        dep_id = _require_dependency_id(
            item, f"required_dependency_ids[{index}]"
        )
        if dep_id in seen:
            raise CriticalDataIntegrityError(
                f"duplicate required dependency id: {dep_id!r}"
            )
        seen.add(dep_id)
        ids.append(dep_id)
    return ids


def _normalize_dependency_results(
    value: object,
    *,
    expected_as_of: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise CriticalDataIntegrityError(
            "dependency_results must be a list/tuple"
        )

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if type(item) is not dict and not isinstance(item, Mapping):
            raise CriticalDataIntegrityError(
                f"dependency_results[{index}] must be a mapping"
            )
        record = dict(item)
        expected_keys = {
            "dependency_id",
            "state",
            "as_of",
            "authority_refs",
        }
        actual_keys = set(record.keys())
        missing = expected_keys - actual_keys
        if missing:
            raise CriticalDataIntegrityError(
                f"dependency_results[{index}] missing field(s): "
                f"{sorted(missing)}"
            )
        extra = actual_keys - expected_keys
        if extra:
            raise CriticalDataIntegrityError(
                f"dependency_results[{index}] unknown field(s): "
                f"{sorted(extra)}"
            )

        dep_id = _require_dependency_id(
            record["dependency_id"],
            f"dependency_results[{index}].dependency_id",
        )
        if dep_id in seen_ids:
            raise CriticalDataIntegrityError(
                f"duplicate dependency_id in dependency_results: {dep_id!r}"
            )
        seen_ids.add(dep_id)

        state = _require_enum(
            record["state"],
            f"dependency_results[{index}].state",
            DEPENDENCY_RESULT_STATES,
        )
        result_as_of = _require_as_of(
            record["as_of"],
            f"dependency_results[{index}].as_of",
        )
        if result_as_of != expected_as_of:
            raise CriticalDataIntegrityError(
                f"dependency_results[{index}].as_of must equal top-level as_of "
                f"({expected_as_of!r}); got {result_as_of!r}"
            )
        refs = _require_authority_refs(
            record["authority_refs"],
            f"dependency_results[{index}].authority_refs",
        )

        results.append(
            {
                "dependency_id": dep_id,
                "state": state,
                "as_of": result_as_of,
                "authority_refs": list(refs),
            }
        )
    return results


def _exact_cover(
    required_ids: Sequence[str],
    results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Require exact cover of required IDs; order by required_ids order."""
    required_set = set(required_ids)
    result_ids = [item["dependency_id"] for item in results]
    result_set = set(result_ids)

    missing = required_set - result_set
    if missing:
        raise CriticalDataIntegrityError(
            f"missing dependency result(s) for required id(s): "
            f"{sorted(missing)}"
        )
    extra = result_set - required_set
    if extra:
        raise CriticalDataIntegrityError(
            f"extra dependency result(s) not in required set: "
            f"{sorted(extra)}"
        )
    if len(result_ids) != len(required_ids):
        # Defensive: duplicates already rejected, but keep invariant explicit.
        raise CriticalDataIntegrityError(
            "dependency_results count must equal required_dependency_ids count"
        )

    by_id = {item["dependency_id"]: item for item in results}
    ordered: list[dict[str, Any]] = []
    for dep_id in required_ids:
        item = by_id[dep_id]
        ordered.append(
            {
                "dependency_id": item["dependency_id"],
                "state": item["state"],
                "as_of": item["as_of"],
                "authority_refs": list(item["authority_refs"]),
            }
        )
    return ordered


def _max_domain_state(states: Sequence[str]) -> str:
    best = "USABLE"
    best_rank = _DOMAIN_SEVERITY["USABLE"]
    for state in states:
        rank = _DOMAIN_SEVERITY[state]
        if rank > best_rank:
            best = state
            best_rank = rank
    return best


def _max_eval_state(states: Sequence[str]) -> str:
    best = "EVALUATED"
    best_rank = _EVAL_SEVERITY["EVALUATED"]
    for state in states:
        rank = _EVAL_SEVERITY[state]
        if rank > best_rank:
            best = state
            best_rank = rank
    return best


def _append_unique(target: list[str], code: str) -> None:
    if code not in target:
        target.append(code)


def _order_reasons(codes: Sequence[str]) -> list[str]:
    rank = {code: index for index, code in enumerate(REASON_CODES)}
    # Stable: known codes by REASON_CODES order; unknowns (should not occur)
    # keep relative order after knowns.
    known = [code for code in REASON_CODES if code in codes]
    unknown = [code for code in codes if code not in rank]
    return known + unknown


# ---------------------------------------------------------------------------
# Projection authority
# ---------------------------------------------------------------------------

def project_campaign_critical_data(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    dependency_set_state: str,
    dependency_set_authority_refs: Sequence[str],
    required_dependency_ids: Sequence[str],
    dependency_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Project Campaign Critical Data usability from explicit inputs.

    Pure function of normalized dependency-set state and per-dependency
    results. Does not invent investment requirements. Does not read wall
    clock. Does not import health / thesis / inbox authorities.
    """
    sec = _require_security_code(security_code)
    strat = _require_strategy(strategy)
    camp = _require_campaign_id(campaign_id)
    as_of_value = _require_as_of(as_of, "as_of")
    set_state = _require_enum(
        dependency_set_state,
        "dependency_set_state",
        DEPENDENCY_SET_STATES,
    )
    set_refs = _require_authority_refs(
        dependency_set_authority_refs,
        "dependency_set_authority_refs",
    )
    required_ids = _normalize_required_ids(required_dependency_ids)
    raw_results = _normalize_dependency_results(
        dependency_results,
        expected_as_of=as_of_value,
    )

    reasons: list[str] = []
    authority_refs: list[str] = list(set_refs)
    ordered_results: list[dict[str, Any]]

    # --- dependency set not RESOLVED ---------------------------------------
    if set_state != "RESOLVED":
        # Non-resolved sets must not smuggle a fabricated dependency list.
        # Empty required/results is the only legal shape (no exact cover of
        # an invented set). Any non-empty list is integrity failure.
        if required_ids:
            raise CriticalDataIntegrityError(
                "required_dependency_ids must be empty when "
                "dependency_set_state is not RESOLVED"
            )
        if raw_results:
            raise CriticalDataIntegrityError(
                "dependency_results must be empty when "
                "dependency_set_state is not RESOLVED"
            )
        ordered_results = []

        if set_state == "ERROR":
            critical_data_state = "UNKNOWN"
            critical_data_evaluation = "ERROR"
            _append_unique(reasons, REASON_DEPENDENCY_SET_ERROR)
        elif set_state == "NOT_EVALUATED":
            critical_data_state = "UNKNOWN"
            critical_data_evaluation = "NOT_EVALUATED"
            _append_unique(reasons, REASON_DEPENDENCY_SET_NOT_EVALUATED)
        else:
            # UNKNOWN
            critical_data_state = "UNKNOWN"
            critical_data_evaluation = "UNKNOWN"
            _append_unique(reasons, REASON_DEPENDENCY_SET_UNKNOWN)

        return _build_output(
            security_code=sec,
            strategy=strat,
            campaign_id=camp,
            as_of=as_of_value,
            dependency_set_state=set_state,
            dependency_set_authority_refs=set_refs,
            required_dependency_ids=required_ids,
            dependency_results=ordered_results,
            critical_data_state=critical_data_state,
            critical_data_evaluation=critical_data_evaluation,
            reason_codes=reasons,
            authority_refs=authority_refs,
        )

    # --- RESOLVED ----------------------------------------------------------
    # RESOLVED always requires provenance: dependency definition authority
    # must be cited for empty and non-empty required sets alike.
    if not set_refs:
        raise CriticalDataIntegrityError(
            "dependency_set_state RESOLVED requires non-empty "
            "dependency_set_authority_refs"
        )

    # Authoritative empty set (no silent clean).
    if not required_ids:
        if raw_results:
            raise CriticalDataIntegrityError(
                "dependency_results must be empty when required set is empty"
            )
        ordered_results = []
        _append_unique(reasons, REASON_DEPENDENCY_SET_AUTHORITATIVELY_EMPTY)
        return _build_output(
            security_code=sec,
            strategy=strat,
            campaign_id=camp,
            as_of=as_of_value,
            dependency_set_state=set_state,
            dependency_set_authority_refs=set_refs,
            required_dependency_ids=required_ids,
            dependency_results=ordered_results,
            critical_data_state="USABLE",
            critical_data_evaluation="EVALUATED",
            reason_codes=reasons,
            authority_refs=authority_refs,
        )

    ordered_results = _exact_cover(required_ids, raw_results)

    domain_states: list[str] = []
    eval_states: list[str] = []
    for item in ordered_results:
        state = item["state"]
        domain_states.append(_RESULT_TO_DOMAIN[state])
        eval_states.append(_RESULT_TO_EVAL[state])
        reason = _RESULT_REASON.get(state)
        if reason is not None:
            _append_unique(reasons, reason)
        for ref in item["authority_refs"]:
            if ref not in authority_refs:
                authority_refs.append(ref)

    critical_data_state = _max_domain_state(domain_states)
    critical_data_evaluation = _max_eval_state(eval_states)

    if critical_data_state == "USABLE" and critical_data_evaluation == "EVALUATED":
        _append_unique(reasons, REASON_ALL_DEPENDENCIES_USABLE)

    return _build_output(
        security_code=sec,
        strategy=strat,
        campaign_id=camp,
        as_of=as_of_value,
        dependency_set_state=set_state,
        dependency_set_authority_refs=set_refs,
        required_dependency_ids=required_ids,
        dependency_results=ordered_results,
        critical_data_state=critical_data_state,
        critical_data_evaluation=critical_data_evaluation,
        reason_codes=reasons,
        authority_refs=authority_refs,
    )


def _build_output(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    dependency_set_state: str,
    dependency_set_authority_refs: Sequence[str],
    required_dependency_ids: Sequence[str],
    dependency_results: Sequence[Mapping[str, Any]],
    critical_data_state: str,
    critical_data_evaluation: str,
    reason_codes: Sequence[str],
    authority_refs: Sequence[str],
) -> dict[str, Any]:
    # Defensive enum checks on produced domain values.
    if critical_data_state not in CRITICAL_DATA_STATES:
        raise CriticalDataIntegrityError(
            f"internal critical_data_state invalid: {critical_data_state!r}"
        )
    if critical_data_evaluation not in CRITICAL_DATA_EVALUATIONS:
        raise CriticalDataIntegrityError(
            "internal critical_data_evaluation invalid: "
            f"{critical_data_evaluation!r}"
        )

    ordered_reasons = _order_reasons(reason_codes)

    # Fully detached structures (no shared mutables with inputs).
    results_out = [
        {
            "dependency_id": item["dependency_id"],
            "state": item["state"],
            "as_of": item["as_of"],
            "authority_refs": list(item["authority_refs"]),
        }
        for item in dependency_results
    ]
    set_refs_out = list(dependency_set_authority_refs)
    required_out = list(required_dependency_ids)
    reasons_out = list(ordered_reasons)
    refs_out = list(authority_refs)

    return {
        "schema_version": SCHEMA_VERSION,
        "security_code": security_code,
        "strategy": strategy,
        "campaign_id": campaign_id,
        "as_of": as_of,
        "dependency_set_state": dependency_set_state,
        "dependency_set_authority_refs": set_refs_out,
        "required_dependency_ids": required_out,
        "dependency_results": results_out,
        "critical_data_state": critical_data_state,
        "critical_data_evaluation": critical_data_evaluation,
        "reason_codes": reasons_out,
        "authority_refs": refs_out,
    }


__all__ = [
    "SCHEMA_VERSION",
    "DEPENDENCY_SET_STATES",
    "DEPENDENCY_RESULT_STATES",
    "CRITICAL_DATA_STATES",
    "CRITICAL_DATA_EVALUATIONS",
    "VALID_STRATEGIES",
    "REASON_CODES",
    "REASON_DEPENDENCY_SET_UNKNOWN",
    "REASON_DEPENDENCY_SET_NOT_EVALUATED",
    "REASON_DEPENDENCY_SET_ERROR",
    "REASON_DEPENDENCY_SET_AUTHORITATIVELY_EMPTY",
    "REASON_DEPENDENCY_BLOCKED",
    "REASON_DEPENDENCY_STALE",
    "REASON_DEPENDENCY_UNKNOWN",
    "REASON_DEPENDENCY_NOT_EVALUATED",
    "REASON_DEPENDENCY_ERROR",
    "REASON_ALL_DEPENDENCIES_USABLE",
    "CampaignCriticalDataError",
    "CriticalDataIntegrityError",
    "project_campaign_critical_data",
]
