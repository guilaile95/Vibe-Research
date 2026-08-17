"""Formal Hard Risk deterministic authority v0.1.

HR1 v0.1 has one supported formal authority: the existing Current Thesis
projection.  This module adapts that named domain result into the frozen
``HardRiskEvaluation`` contract; it never accepts a caller-declared Hard Risk
state, severity, or proof label.

The boundary is pure and Campaign-scoped:

* ``campaign_id`` is only the locator;
* backend Campaign ``security_code`` and ``strategy`` are authoritative;
* the Current Thesis envelope must match the complete Campaign identity and
  the literal caller-supplied UTC ``as_of``;
* terminal Current Thesis facts can confirm Hard Risk;
* no v0.1 input can produce ``CLEAR`` because no formal all-clear authority
  exists yet.

The module has no I/O, persistence, provider, AI, randomness, or wall-clock
dependency.  Future Hard Risk domains must add their own named deterministic
authority and adapter; this module does not expose a generic conclusion
registry or proof input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from hard_risk_contract import (
    POLICY_VERSION_V01 as CONTRACT_POLICY_VERSION,
    SCHEMA_VERSION as CONTRACT_SCHEMA_VERSION,
    HardRiskEvaluation,
    VALID_STRATEGIES,
)


SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION
POLICY_VERSION_V01 = CONTRACT_POLICY_VERSION
FORMAL_THESIS_PROJECTION_KEY = "formal_thesis_projection"

THESIS_PROJECTION_SCHEMA_VERSION = "formal_current_thesis.projection.v0.1"
THESIS_STATES = frozenset(
    {"STRENGTHENED", "STABLE", "WEAKENED", "DISPROVEN", "INVALIDATED", "UNKNOWN"}
)
TERMINAL_THESIS_STATES = frozenset({"DISPROVEN", "INVALIDATED"})

REASON_CAMPAIGN_LOCATOR_MISMATCH = "CAMPAIGN_LOCATOR_MISMATCH"
REASON_AUTHORITY_IDENTITY_INVALID = "AUTHORITY_IDENTITY_INVALID"
REASON_AUTHORITY_SCOPE_MISMATCH = "AUTHORITY_SCOPE_MISMATCH"
REASON_AUTHORITY_AS_OF_MISMATCH = "AUTHORITY_AS_OF_MISMATCH"
REASON_AUTHORITY_LOOKAHEAD = "AUTHORITY_LOOKAHEAD"
REASON_AUTHORITY_PROVENANCE_MISSING = "AUTHORITY_PROVENANCE_MISSING"
REASON_THESIS_PROJECTION_INVALID = "THESIS_PROJECTION_INVALID"
REASON_THESIS_NOT_READY = "THESIS_NOT_READY"
REASON_THESIS_AUTHORITY_NOT_AVAILABLE = "THESIS_AUTHORITY_NOT_AVAILABLE"
REASON_THESIS_PROJECTION_UNKNOWN = "THESIS_PROJECTION_UNKNOWN"
REASON_THESIS_HARD_RISK_NOT_PROVEN = "THESIS_HARD_RISK_NOT_PROVEN"
REASON_THESIS_TERMINAL_FLAG_CONFLICT = "THESIS_TERMINAL_FLAG_CONFLICT"
REASON_HARD_RISK_CONFIRMED = "HARD_RISK_CONFIRMED"
REASON_THESIS_CORE_FACT_DISPROVEN = "THESIS_CORE_FACT_DISPROVEN"
REASON_THESIS_CORE_FACT_INVALIDATED = "THESIS_CORE_FACT_INVALIDATED"

_SECURITY_CODE_RE = re.compile(r"^\d{6}$", re.ASCII)
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$", re.ASCII)
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)

_REASON_ORDER = (
    REASON_HARD_RISK_CONFIRMED,
    REASON_THESIS_CORE_FACT_DISPROVEN,
    REASON_THESIS_CORE_FACT_INVALIDATED,
    REASON_THESIS_HARD_RISK_NOT_PROVEN,
    REASON_THESIS_PROJECTION_UNKNOWN,
    REASON_THESIS_TERMINAL_FLAG_CONFLICT,
    REASON_THESIS_NOT_READY,
    REASON_THESIS_AUTHORITY_NOT_AVAILABLE,
    REASON_AUTHORITY_PROVENANCE_MISSING,
    REASON_AUTHORITY_SCOPE_MISMATCH,
    REASON_AUTHORITY_AS_OF_MISMATCH,
    REASON_AUTHORITY_LOOKAHEAD,
    REASON_THESIS_PROJECTION_INVALID,
    REASON_AUTHORITY_IDENTITY_INVALID,
    REASON_CAMPAIGN_LOCATOR_MISMATCH,
)
_REASON_RANK = {code: index for index, code in enumerate(_REASON_ORDER)}


class HardRiskRuntimeError(ValueError):
    """Top-level Campaign/as_of input is malformed."""


class _AuthorityScopeError(Exception):
    def __init__(self, reason: str, *, not_evaluated: bool = True) -> None:
        self.reason = reason
        self.not_evaluated = not_evaluated
        super().__init__(reason)


@dataclass(frozen=True)
class _Scope:
    security_code: str
    strategy: str
    campaign_id: str
    as_of: str
    as_of_dt: datetime


def _require_text(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise HardRiskRuntimeError(f"{field} must be a non-empty trimmed string")
    return value


def _require_security_code(value: object, field: str) -> str:
    code = _require_text(value, field)
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise HardRiskRuntimeError(f"{field} must be exactly six ASCII digits")
    return code


def _require_strategy(value: object, field: str) -> str:
    strategy = _require_text(value, field)
    if strategy not in VALID_STRATEGIES:
        raise HardRiskRuntimeError(
            f"{field} must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object, field: str) -> str:
    campaign_id = _require_text(value, field)
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise HardRiskRuntimeError(
            f"{field} must match campaign_<32 lowercase hex>"
        )
    return campaign_id


def _parse_utc(value: object, field: str) -> tuple[str, datetime]:
    text = _require_text(value, field)
    if _UTC_ZERO_OFFSET_RE.fullmatch(text) is None:
        raise HardRiskRuntimeError(
            f"{field} must be an explicit UTC zero-offset instant"
        )
    parse_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise HardRiskRuntimeError(f"{field} is not a valid UTC instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HardRiskRuntimeError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset().total_seconds() != 0:
        raise HardRiskRuntimeError(f"{field} must use UTC zero offset")
    return text, parsed.astimezone(timezone.utc)


def _ordered_codes(codes: Sequence[str]) -> tuple[str, ...]:
    unique = {code for code in codes if isinstance(code, str) and code}
    return tuple(
        sorted(unique, key=lambda code: (_REASON_RANK.get(code, 10_000), code))
    )


def _ordered_refs(refs: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(refs)))


def _require_authority_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise HardRiskRuntimeError(
            "formal_thesis_projection.authority_refs must be non-empty"
        )
    refs: list[str] = []
    for index, item in enumerate(value):
        refs.append(
            _require_text(
                item, f"formal_thesis_projection.authority_refs[{index}]"
            )
        )
    if len(refs) != len(set(refs)):
        raise HardRiskRuntimeError(
            "formal_thesis_projection.authority_refs must not contain duplicates"
        )
    return _ordered_refs(refs)


def _campaign_scope(
    *, campaign_id: object, campaign: object, as_of: object
) -> _Scope:
    if not isinstance(campaign, Mapping):
        raise HardRiskRuntimeError("campaign must be a Mapping")
    locator = _require_campaign_id(campaign_id, "campaign_id")
    record_campaign_id = _require_campaign_id(
        campaign.get("campaign_id"), "campaign.campaign_id"
    )
    security_code = _require_security_code(
        campaign.get("security_code"), "campaign.security_code"
    )
    strategy = _require_strategy(campaign.get("strategy"), "campaign.strategy")
    as_of_text, as_of_dt = _parse_utc(as_of, "as_of")
    if locator != record_campaign_id:
        raise HardRiskRuntimeError(REASON_CAMPAIGN_LOCATOR_MISMATCH)
    return _Scope(
        security_code=security_code,
        strategy=strategy,
        campaign_id=record_campaign_id,
        as_of=as_of_text,
        as_of_dt=as_of_dt,
    )


def _validate_envelope_scope(envelope: Mapping[str, Any], scope: _Scope) -> None:
    required = ("campaign_id", "security_code", "strategy", "as_of")
    if any(key not in envelope for key in required):
        raise _AuthorityScopeError(REASON_AUTHORITY_IDENTITY_INVALID)
    try:
        envelope_campaign_id = _require_campaign_id(
            envelope["campaign_id"], "formal_thesis_projection.campaign_id"
        )
        envelope_security_code = _require_security_code(
            envelope["security_code"], "formal_thesis_projection.security_code"
        )
        envelope_strategy = _require_strategy(
            envelope["strategy"], "formal_thesis_projection.strategy"
        )
        envelope_as_of, _ = _parse_utc(
            envelope["as_of"], "formal_thesis_projection.as_of"
        )
    except HardRiskRuntimeError as exc:
        raise _AuthorityScopeError(REASON_AUTHORITY_IDENTITY_INVALID) from exc

    if (
        envelope_campaign_id != scope.campaign_id
        or envelope_security_code != scope.security_code
        or envelope_strategy != scope.strategy
    ):
        raise _AuthorityScopeError(REASON_AUTHORITY_SCOPE_MISMATCH)
    if envelope_as_of != scope.as_of:
        raise _AuthorityScopeError(REASON_AUTHORITY_AS_OF_MISMATCH)

    for time_key in ("fact_time", "event_at", "effective_at"):
        if time_key not in envelope or envelope[time_key] is None:
            continue
        try:
            _, fact_dt = _parse_utc(
                envelope[time_key], f"formal_thesis_projection.{time_key}"
            )
        except HardRiskRuntimeError as exc:
            raise _AuthorityScopeError(REASON_AUTHORITY_LOOKAHEAD) from exc
        if fact_dt > scope.as_of_dt:
            raise _AuthorityScopeError(REASON_AUTHORITY_LOOKAHEAD)


def _projection_fact_times(projection: Mapping[str, Any]) -> tuple[object, ...]:
    times: list[object] = []
    latest_delta = projection.get("latest_delta")
    if isinstance(latest_delta, Mapping) and "confirmed_at" in latest_delta:
        times.append(latest_delta.get("confirmed_at"))
    deltas = projection.get("deltas")
    if isinstance(deltas, list):
        for delta in deltas:
            if isinstance(delta, Mapping) and "confirmed_at" in delta:
                times.append(delta.get("confirmed_at"))
    return tuple(times)


def _validate_projection_fact_times(
    projection: Mapping[str, Any], scope: _Scope
) -> None:
    for raw_time in _projection_fact_times(projection):
        if raw_time is None:
            continue
        try:
            _, fact_dt = _parse_utc(raw_time, "formal_thesis_projection.confirmed_at")
        except HardRiskRuntimeError as exc:
            raise _AuthorityScopeError(
                REASON_THESIS_PROJECTION_INVALID, not_evaluated=False
            ) from exc
        if fact_dt > scope.as_of_dt:
            raise _AuthorityScopeError(REASON_AUTHORITY_LOOKAHEAD)


def _result(
    scope: _Scope,
    *,
    state: str,
    evaluation: str,
    reasons: Sequence[str],
    refs: Sequence[str] = (),
) -> HardRiskEvaluation:
    return HardRiskEvaluation(
        security_code=scope.security_code,
        strategy=scope.strategy,
        campaign_id=scope.campaign_id,
        as_of=scope.as_of,
        hard_risk_state=state,
        hard_risk_evaluation=evaluation,
        reason_codes=_ordered_codes(reasons),
        authority_refs=_ordered_refs(refs),
    )


def _evaluate_formal_thesis_projection(
    *, envelope: object, scope: _Scope
) -> HardRiskEvaluation:
    if not isinstance(envelope, Mapping):
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(REASON_THESIS_PROJECTION_INVALID,),
        )

    try:
        _validate_envelope_scope(envelope, scope)
    except _AuthorityScopeError as exc:
        if exc.not_evaluated:
            return _result(
                scope,
                state="NOT_EVALUATED",
                evaluation="NOT_EVALUATED",
                reasons=(exc.reason,),
            )
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(exc.reason,),
        )

    try:
        refs = _require_authority_refs(envelope.get("authority_refs"))
    except HardRiskRuntimeError:
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(REASON_AUTHORITY_PROVENANCE_MISSING,),
        )

    projection = envelope.get("projection")
    if not isinstance(projection, Mapping):
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(REASON_THESIS_PROJECTION_INVALID,),
            refs=refs,
        )
    if projection.get("schema_version") != THESIS_PROJECTION_SCHEMA_VERSION:
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(REASON_THESIS_PROJECTION_INVALID,),
            refs=refs,
        )
    if projection.get("campaign_id") != scope.campaign_id:
        return _result(
            scope,
            state="NOT_EVALUATED",
            evaluation="NOT_EVALUATED",
            reasons=(REASON_AUTHORITY_SCOPE_MISMATCH,),
        )
    if projection.get("strategy") != scope.strategy:
        return _result(
            scope,
            state="NOT_EVALUATED",
            evaluation="NOT_EVALUATED",
            reasons=(REASON_AUTHORITY_SCOPE_MISMATCH,),
        )

    try:
        _validate_projection_fact_times(projection, scope)
    except _AuthorityScopeError as exc:
        if exc.not_evaluated:
            return _result(
                scope,
                state="NOT_EVALUATED",
                evaluation="NOT_EVALUATED",
                reasons=(exc.reason,),
            )
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(exc.reason,),
            refs=refs,
        )

    formal_status = projection.get("formal_status")
    if formal_status != "READY":
        return _result(
            scope,
            state="NOT_EVALUATED",
            evaluation="NOT_EVALUATED",
            reasons=(REASON_THESIS_NOT_READY,),
            refs=refs,
        )

    effective_state = projection.get("effective_state")
    if effective_state not in THESIS_STATES:
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(REASON_THESIS_PROJECTION_INVALID,),
            refs=refs,
        )

    expected_terminal = effective_state in TERMINAL_THESIS_STATES
    if type(projection.get("terminal")) is not bool:
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(REASON_THESIS_PROJECTION_INVALID,),
            refs=refs,
        )
    if projection["terminal"] is not expected_terminal:
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(REASON_THESIS_TERMINAL_FLAG_CONFLICT,),
            refs=refs,
        )

    if effective_state == "DISPROVEN":
        return _result(
            scope,
            state="CONFIRMED",
            evaluation="EVALUATED",
            reasons=(REASON_HARD_RISK_CONFIRMED, REASON_THESIS_CORE_FACT_DISPROVEN),
            refs=refs,
        )
    if effective_state == "INVALIDATED":
        return _result(
            scope,
            state="CONFIRMED",
            evaluation="EVALUATED",
            reasons=(REASON_HARD_RISK_CONFIRMED, REASON_THESIS_CORE_FACT_INVALIDATED),
            refs=refs,
        )
    if effective_state == "UNKNOWN":
        return _result(
            scope,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            reasons=(REASON_THESIS_PROJECTION_UNKNOWN,),
            refs=refs,
        )

    # A valid non-terminal Thesis is an evaluated observation, but it cannot
    # prove trading eligibility, solvency, authenticity, regulation, or data
    # integrity.  HR1 therefore remains fail-closed and does not emit CLEAR.
    return _result(
        scope,
        state="UNKNOWN",
        evaluation="UNKNOWN",
        reasons=(REASON_THESIS_HARD_RISK_NOT_PROVEN,),
        refs=refs,
    )


def evaluate_hard_risk(
    *,
    campaign_id: object,
    campaign: Mapping[str, Any],
    as_of: object,
    formal_thesis_projection: Mapping[str, Any] | None,
) -> HardRiskEvaluation:
    """Evaluate the named Current Thesis authority for one Campaign.

    ``campaign`` is the backend Campaign authority record.  ``campaign_id``
    only locates that record; its ``security_code`` and ``strategy`` are used
    for the output and all scope checks.

    ``formal_thesis_projection`` is either ``None`` or an explicit envelope:

    ``campaign_id`` / ``security_code`` / ``strategy`` / ``as_of``
        Exact Campaign scope and literal UTC evaluation time.

    ``authority_refs``
        Non-empty provenance from the Current Thesis authority.

    ``projection``
        Existing ``formal_current_thesis.projection.v0.1`` output.  Only its
        domain facts are interpreted; callers cannot supply Hard Risk labels.

    v0.1 has no formal all-clear authority, so this function never produces
    ``CLEAR``.  Missing authority returns ``NOT_EVALUATED``.  Valid non-terminal
    or ambiguous Thesis facts return ``UNKNOWN``.
    """
    scope = _campaign_scope(campaign_id=campaign_id, campaign=campaign, as_of=as_of)
    if formal_thesis_projection is None:
        return _result(
            scope,
            state="NOT_EVALUATED",
            evaluation="NOT_EVALUATED",
            reasons=(REASON_THESIS_AUTHORITY_NOT_AVAILABLE,),
        )
    return _evaluate_formal_thesis_projection(
        envelope=formal_thesis_projection,
        scope=scope,
    )


def evaluate_hard_risk_mapping(
    *,
    campaign_id: object,
    campaign: Mapping[str, Any],
    as_of: object,
    formal_thesis_projection: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a detached JSON/API mapping for runtime callers."""
    return evaluate_hard_risk(
        campaign_id=campaign_id,
        campaign=campaign,
        as_of=as_of,
        formal_thesis_projection=formal_thesis_projection,
    ).to_dict()


__all__ = [
    "FORMAL_THESIS_PROJECTION_KEY",
    "HardRiskRuntimeError",
    "POLICY_VERSION_V01",
    "SCHEMA_VERSION",
    "THESIS_PROJECTION_SCHEMA_VERSION",
    "evaluate_hard_risk",
    "evaluate_hard_risk_mapping",
]
