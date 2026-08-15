"""Formal Hard Risk deterministic authority v0.1.

This module is the pure composition boundary for HR1.  It consumes an already
resolved Campaign record and explicitly supplied authority envelopes; it does
not load Campaigns, call providers, read Data Health, interpret a score, or
consult an AI system.

The important boundary is deliberately narrow:

* ``campaign_id`` is only the locator.  ``campaign.security_code`` and
  ``campaign.strategy`` are the identity used in the result and in every
  authority-scope check.
* A ``CONFIRMED`` result requires a high-severity, positive-proof authority
  envelope.  The existing Current Thesis projection is adapted only when its
  terminal state is explicitly wrapped with the same scope and provenance.
* A ``CLEAR`` result requires an explicit positive proof covering every
  implemented HR1 check.  An empty result, usable data, a stable Thesis, or a
  low top-risk score is never such proof.
* Missing/unwired authority is ``NOT_EVALUATED``.  An authority that ran but
  cannot adjudicate is ``UNKNOWN``.  Invalid scope/time input is rejected from
  the candidate set and cannot produce a clean result.

The module is intentionally free of I/O, provider imports, persistence, AI,
randomness, and wall-clock reads.  ``as_of`` is supplied by the caller and is
the only temporal evaluation context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from hard_risk_contract import (
    HARD_RISK_STATES,
    LEGAL_STATE_EVALUATION_PAIRS,
    POLICY_VERSION_V01 as CONTRACT_POLICY_VERSION,
    SCHEMA_VERSION as CONTRACT_SCHEMA_VERSION,
    HardRiskEvaluation,
    VALID_STRATEGIES,
)


SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION
POLICY_VERSION_V01 = CONTRACT_POLICY_VERSION

# The proof envelope is an input boundary, not a new persisted schema.  It is
# intentionally strict about the fields that affect the HR result.
FORMAL_THESIS_PROJECTION_KEY = "formal_thesis_projection"
HARD_RISK_PROOFS_KEY = "hard_risk_proofs"

# These inputs are explicitly known to be non-authoritative for HR1.  They are
# accepted as context so callers cannot accidentally promote them by passing
# them through this function; they never participate in the reduction.
NON_AUTHORITY_INPUT_KEYS = frozenset(
    {
        "critical_data_projection",
        "data_health",
        "disclosures",
        "financials",
        "security_exchange",
        "trading_eligibility",
        "special_status",
        "top_risk",
    }
)
SUPPORTED_INPUT_KEYS = frozenset(
    {FORMAL_THESIS_PROJECTION_KEY, HARD_RISK_PROOFS_KEY}
)
ALLOWED_INPUT_KEYS = SUPPORTED_INPUT_KEYS | NON_AUTHORITY_INPUT_KEYS

ALL_IMPLEMENTED_HARD_RISK_CHECKS = "ALL_IMPLEMENTED_HARD_RISK_CHECKS"
THESIS_CHECK_ID = "formal_current_thesis"

REASON_CAMPAIGN_LOCATOR_MISMATCH = "CAMPAIGN_LOCATOR_MISMATCH"
REASON_CAMPAIGN_IDENTITY_INVALID = "CAMPAIGN_IDENTITY_INVALID"
REASON_AUTHORITY_IDENTITY_INVALID = "AUTHORITY_IDENTITY_INVALID"
REASON_AUTHORITY_IDENTITY_MISMATCH = "AUTHORITY_IDENTITY_MISMATCH"
REASON_AUTHORITY_AS_OF_INVALID = "AUTHORITY_AS_OF_INVALID"
REASON_AUTHORITY_AS_OF_MISMATCH = "AUTHORITY_AS_OF_MISMATCH"
REASON_AUTHORITY_LOOKAHEAD = "AUTHORITY_LOOKAHEAD"
REASON_AUTHORITY_PAYLOAD_INVALID = "AUTHORITY_PAYLOAD_INVALID"
REASON_AUTHORITY_PROOF_MISSING = "AUTHORITY_PROOF_MISSING"
REASON_AUTHORITY_PROOF_AMBIGUOUS = "AUTHORITY_PROOF_AMBIGUOUS"
REASON_AUTHORITY_NOT_EVALUATED = "AUTHORITY_NOT_EVALUATED"
REASON_AUTHORITY_ERROR = "AUTHORITY_ERROR"
REASON_HARD_RISK_PROOF_CONFLICT = "HARD_RISK_PROOF_CONFLICT"
REASON_NO_HARD_RISK_AUTHORITY = "NO_HARD_RISK_AUTHORITY"
REASON_NO_POSITIVE_HARD_RISK_PROOF = "NO_POSITIVE_HARD_RISK_PROOF"
REASON_CLEAR_POSITIVE_PROOF = "CLEAR_POSITIVE_PROOF"
REASON_CLEAR_PROOF_SCOPE_INCOMPLETE = "CLEAR_PROOF_SCOPE_INCOMPLETE"
REASON_HARD_RISK_CONFIRMED = "HARD_RISK_CONFIRMED"
REASON_THESIS_CORE_FACT_DISPROVEN = "THESIS_CORE_FACT_DISPROVEN"
REASON_THESIS_CORE_FACT_INVALIDATED = "THESIS_CORE_FACT_INVALIDATED"
REASON_THESIS_NOT_READY = "THESIS_NOT_READY"
REASON_THESIS_AMBIGUOUS = "THESIS_AMBIGUOUS"

TERMINAL_THESIS_STATES = frozenset({"DISPROVEN", "INVALIDATED"})
HIGH_SEVERITIES = frozenset({"HIGH", "CRITICAL"})

_SECURITY_CODE_RE = re.compile(r"^\d{6}$", re.ASCII)
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$", re.ASCII)
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)

# Stable reason order is part of the deterministic output contract.  Unknown
# caller-provided reason codes are appended in lexical order.
_REASON_ORDER = (
    REASON_HARD_RISK_CONFIRMED,
    REASON_THESIS_CORE_FACT_DISPROVEN,
    REASON_THESIS_CORE_FACT_INVALIDATED,
    REASON_CLEAR_POSITIVE_PROOF,
    REASON_HARD_RISK_PROOF_CONFLICT,
    REASON_AUTHORITY_PROOF_AMBIGUOUS,
    REASON_AUTHORITY_PROOF_MISSING,
    REASON_NO_POSITIVE_HARD_RISK_PROOF,
    REASON_AUTHORITY_ERROR,
    REASON_AUTHORITY_NOT_EVALUATED,
    REASON_THESIS_NOT_READY,
    REASON_AUTHORITY_IDENTITY_INVALID,
    REASON_AUTHORITY_IDENTITY_MISMATCH,
    REASON_AUTHORITY_AS_OF_INVALID,
    REASON_AUTHORITY_AS_OF_MISMATCH,
    REASON_AUTHORITY_LOOKAHEAD,
    REASON_AUTHORITY_PAYLOAD_INVALID,
    REASON_CLEAR_PROOF_SCOPE_INCOMPLETE,
    REASON_NO_HARD_RISK_AUTHORITY,
)
_REASON_RANK = {code: index for index, code in enumerate(_REASON_ORDER)}


class HardRiskRuntimeError(ValueError):
    """Top-level HR1 input is malformed and cannot form a valid result."""


@dataclass(frozen=True)
class _Scope:
    security_code: str
    strategy: str
    campaign_id: str
    as_of: str
    as_of_dt: datetime


@dataclass(frozen=True)
class _Assessment:
    """Detached normalized assessment used only inside the pure reducer."""

    check_id: str
    risk_type: str
    hard_risk_state: str
    hard_risk_evaluation: str
    positive_proof: bool
    severity: str | None
    coverage: tuple[str, ...]
    reason_codes: tuple[str, ...]
    authority_refs: tuple[str, ...]

    @property
    def signature(self) -> tuple[Any, ...]:
        return (
            self.check_id,
            self.risk_type,
            self.hard_risk_state,
            self.hard_risk_evaluation,
            self.positive_proof,
            self.severity,
            self.coverage,
            self.reason_codes,
            self.authority_refs,
        )


@dataclass
class _Reduction:
    assessments: list[_Assessment]
    unknown_reasons: list[str]
    not_evaluated_reasons: list[str]
    neutral_observed: bool = False
    supported_authority_observed: bool = False
    identity_or_time_rejection: bool = False
    payload_rejection: bool = False
    conflict: bool = False


def _require_text(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise HardRiskRuntimeError(f"{field} must be a non-empty trimmed string")
    return value


def _require_security_code(value: object, field: str = "security_code") -> str:
    code = _require_text(value, field)
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise HardRiskRuntimeError(f"{field} must be exactly six ASCII digits")
    return code


def _require_strategy(value: object, field: str = "strategy") -> str:
    strategy = _require_text(value, field)
    if strategy not in VALID_STRATEGIES:
        raise HardRiskRuntimeError(
            f"{field} must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object, field: str = "campaign_id") -> str:
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
    return tuple(sorted(unique, key=lambda code: (_REASON_RANK.get(code, 10_000), code)))


def _ordered_refs(refs: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(refs)))


def _require_string_sequence(
    value: object,
    field: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise HardRiskRuntimeError(f"{field} must be a list/tuple of strings")
    values: list[str] = []
    for item in value:
        values.append(_require_text(item, f"{field}[]"))
    if len(values) != len(set(values)):
        raise HardRiskRuntimeError(f"{field} must not contain duplicates")
    if required and not values:
        raise HardRiskRuntimeError(f"{field} must not be empty")
    return tuple(values)


def _require_scope(
    record: Mapping[str, Any],
    scope: _Scope,
    *,
    field: str,
) -> tuple[bool, str | None]:
    """Validate a fact envelope without trusting its identity fields."""
    for key in ("campaign_id", "security_code", "strategy", "as_of"):
        if key not in record:
            return False, REASON_AUTHORITY_IDENTITY_INVALID

    try:
        record_campaign_id = _require_campaign_id(
            record["campaign_id"], f"{field}.campaign_id"
        )
        record_security_code = _require_security_code(
            record["security_code"], f"{field}.security_code"
        )
        record_strategy = _require_strategy(record["strategy"], f"{field}.strategy")
        record_as_of, _ = _parse_utc(record["as_of"], f"{field}.as_of")
    except HardRiskRuntimeError:
        # A malformed authority envelope is not allowed to become a clean
        # result.  The caller receives a deterministic fail-closed state.
        return False, REASON_AUTHORITY_IDENTITY_INVALID

    if (
        record_campaign_id != scope.campaign_id
        or record_security_code != scope.security_code
        or record_strategy != scope.strategy
    ):
        return False, REASON_AUTHORITY_IDENTITY_MISMATCH
    if record_as_of != scope.as_of:
        return False, REASON_AUTHORITY_AS_OF_MISMATCH

    # Fact/event time is optional because some existing projections are
    # evaluated at an explicit snapshot without carrying a separate event
    # timestamp.  If supplied, it must not be later than that snapshot.
    for time_key in ("fact_time", "event_at", "effective_at"):
        if time_key not in record or record[time_key] is None:
            continue
        try:
            _, fact_dt = _parse_utc(record[time_key], f"{field}.{time_key}")
        except HardRiskRuntimeError:
            return False, REASON_AUTHORITY_LOOKAHEAD
        if fact_dt > scope.as_of_dt:
            return False, REASON_AUTHORITY_LOOKAHEAD
    return True, None


def _campaign_scope(
    *, campaign_id: object, campaign: object, as_of: object
) -> _Scope:
    if not isinstance(campaign, Mapping):
        raise HardRiskRuntimeError("campaign must be a Mapping")
    try:
        locator = _require_campaign_id(campaign_id, "campaign_id")
        record_campaign_id = _require_campaign_id(
            campaign.get("campaign_id"), "campaign.campaign_id"
        )
        security_code = _require_security_code(
            campaign.get("security_code"), "campaign.security_code"
        )
        strategy = _require_strategy(campaign.get("strategy"), "campaign.strategy")
        as_of_text, as_of_dt = _parse_utc(as_of, "as_of")
    except HardRiskRuntimeError:
        raise
    if locator != record_campaign_id:
        raise HardRiskRuntimeError(REASON_CAMPAIGN_LOCATOR_MISMATCH)
    return _Scope(
        security_code=security_code,
        strategy=strategy,
        campaign_id=record_campaign_id,
        as_of=as_of_text,
        as_of_dt=as_of_dt,
    )


def _record_common_fields(
    record: Mapping[str, Any], scope: _Scope, *, field: str
) -> tuple[str, str, str, bool, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Validate fields shared by an explicit Hard Risk proof record."""
    in_scope, reason = _require_scope(record, scope, field=field)
    if not in_scope:
        raise _ScopedRecordError(reason or REASON_AUTHORITY_IDENTITY_INVALID)

    check_id = _require_text(record.get("check_id"), f"{field}.check_id")
    risk_type = _require_text(record.get("risk_type"), f"{field}.risk_type")
    state = record.get("hard_risk_state")
    evaluation = record.get("hard_risk_evaluation")
    if state not in HARD_RISK_STATES:
        raise _PayloadRecordError(f"{field}.hard_risk_state")
    if not isinstance(evaluation, str) or (state, evaluation) not in LEGAL_STATE_EVALUATION_PAIRS:
        raise _PayloadRecordError(f"{field}.hard_risk_evaluation")

    positive_proof = record.get("positive_proof")
    if type(positive_proof) is not bool:
        raise _PayloadRecordError(f"{field}.positive_proof")

    required_refs = state in {"CLEAR", "CONFIRMED", "UNKNOWN"}
    required_reasons = state != "CLEAR"
    try:
        refs = _require_string_sequence(
            record.get("authority_refs"), f"{field}.authority_refs", required=required_refs
        )
        reasons = _require_string_sequence(
            record.get("reason_codes"), f"{field}.reason_codes", required=required_reasons
        )
    except HardRiskRuntimeError as exc:
        raise _PayloadRecordError(str(exc)) from exc

    coverage_value = record.get("coverage", ())
    if coverage_value is None:
        coverage_value = ()
    try:
        coverage = _require_string_sequence(
            coverage_value, f"{field}.coverage", required=False
        )
    except HardRiskRuntimeError as exc:
        raise _PayloadRecordError(str(exc)) from exc
    return (
        check_id,
        risk_type,
        state,
        positive_proof,
        _ordered_codes(reasons),
        _ordered_refs(refs),
        tuple(sorted(coverage)),
    )


class _ScopedRecordError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _PayloadRecordError(Exception):
    pass


def _parse_explicit_proof(
    record: object, scope: _Scope, *, index: int
) -> tuple[_Assessment | None, str | None, bool, bool]:
    """Return assessment, reason, is_scope_rejection, is_payload_rejection."""
    field = f"{HARD_RISK_PROOFS_KEY}[{index}]"
    if not isinstance(record, Mapping):
        return None, REASON_AUTHORITY_PAYLOAD_INVALID, False, True
    try:
        (
            check_id,
            risk_type,
            state,
            positive_proof,
            reasons,
            refs,
            coverage,
        ) = _record_common_fields(record, scope, field=field)
    except _ScopedRecordError as exc:
        return None, exc.reason, True, False
    except (_PayloadRecordError, HardRiskRuntimeError):
        return None, REASON_AUTHORITY_PAYLOAD_INVALID, False, True

    severity = record.get("severity")
    if severity is not None and type(severity) is not str:
        return None, REASON_AUTHORITY_PAYLOAD_INVALID, False, True
    if isinstance(severity, str) and severity != severity.strip():
        return None, REASON_AUTHORITY_PAYLOAD_INVALID, False, True

    evaluation = record["hard_risk_evaluation"]
    reasons_out = list(reasons)
    if state == "CONFIRMED":
        if severity not in HIGH_SEVERITIES or not positive_proof:
            reasons_out.extend(
                (REASON_AUTHORITY_PROOF_AMBIGUOUS, REASON_AUTHORITY_PROOF_MISSING)
            )
            state = "UNKNOWN"
            evaluation = "UNKNOWN"
        else:
            reasons_out.append(REASON_HARD_RISK_CONFIRMED)
    elif state == "CLEAR":
        if not positive_proof:
            reasons_out.append(REASON_AUTHORITY_PROOF_MISSING)
        if ALL_IMPLEMENTED_HARD_RISK_CHECKS not in coverage:
            reasons_out.append(REASON_CLEAR_PROOF_SCOPE_INCOMPLETE)
        if positive_proof and ALL_IMPLEMENTED_HARD_RISK_CHECKS in coverage:
            reasons_out.append(REASON_CLEAR_POSITIVE_PROOF)
        else:
            state = "UNKNOWN"
            evaluation = "UNKNOWN"
    elif state == "UNKNOWN":
        reasons_out.append(
            REASON_AUTHORITY_ERROR
            if record.get("hard_risk_evaluation") == "ERROR"
            else REASON_AUTHORITY_PROOF_AMBIGUOUS
        )
    else:
        reasons_out.append(REASON_AUTHORITY_NOT_EVALUATED)

    assessment = _Assessment(
        check_id=check_id,
        risk_type=risk_type,
        hard_risk_state=state,
        hard_risk_evaluation=evaluation,
        positive_proof=positive_proof,
        severity=severity,
        coverage=coverage,
        reason_codes=_ordered_codes(reasons_out),
        authority_refs=refs,
    )
    return assessment, None, False, False


def _projection_fact_times(projection: Mapping[str, Any]) -> tuple[object, ...]:
    times: list[object] = []
    latest = projection.get("latest_delta")
    if isinstance(latest, Mapping) and "confirmed_at" in latest:
        times.append(latest.get("confirmed_at"))
    deltas = projection.get("deltas")
    if isinstance(deltas, list):
        for delta in deltas:
            if isinstance(delta, Mapping) and "confirmed_at" in delta:
                times.append(delta.get("confirmed_at"))
    return tuple(times)


def _parse_formal_thesis_projection(
    envelope: object, scope: _Scope
) -> tuple[_Assessment | None, str | None, bool, bool, bool]:
    """Adapt the existing Current Thesis projection without reimplementing it.

    Return values are assessment, reason, scope_rejection, payload_rejection,
    neutral_observation.
    """
    if not isinstance(envelope, Mapping):
        return None, REASON_AUTHORITY_PAYLOAD_INVALID, False, True, False
    field = FORMAL_THESIS_PROJECTION_KEY
    in_scope, scope_reason = _require_scope(envelope, scope, field=field)
    if not in_scope:
        return None, scope_reason, True, False, False

    refs_value = envelope.get("authority_refs")
    try:
        refs = _require_string_sequence(
            refs_value, f"{field}.authority_refs", required=True
        )
    except HardRiskRuntimeError:
        return None, REASON_AUTHORITY_PROOF_MISSING, False, True, False

    projection = envelope.get("projection")
    if not isinstance(projection, Mapping):
        return None, REASON_AUTHORITY_PAYLOAD_INVALID, False, True, False
    if projection.get("schema_version") != "formal_current_thesis.projection.v0.1":
        return None, REASON_AUTHORITY_PAYLOAD_INVALID, False, True, False
    if projection.get("campaign_id") != scope.campaign_id:
        return None, REASON_AUTHORITY_IDENTITY_MISMATCH, True, False, False
    if projection.get("strategy") != scope.strategy:
        return None, REASON_AUTHORITY_IDENTITY_MISMATCH, True, False, False

    for raw_time in _projection_fact_times(projection):
        if raw_time is None:
            continue
        try:
            _, fact_dt = _parse_utc(raw_time, f"{field}.projection.confirmed_at")
        except HardRiskRuntimeError:
            return None, REASON_AUTHORITY_LOOKAHEAD, False, True, False
        if fact_dt > scope.as_of_dt:
            return None, REASON_AUTHORITY_LOOKAHEAD, True, False, False

    formal_status = projection.get("formal_status")
    if formal_status != "READY":
        return None, REASON_THESIS_NOT_READY, False, False, False

    effective_state = projection.get("effective_state")
    if effective_state in TERMINAL_THESIS_STATES:
        if projection.get("terminal") is not True:
            return None, REASON_THESIS_AMBIGUOUS, False, True, False
        reason = (
            REASON_THESIS_CORE_FACT_DISPROVEN
            if effective_state == "DISPROVEN"
            else REASON_THESIS_CORE_FACT_INVALIDATED
        )
        assessment = _Assessment(
            check_id=THESIS_CHECK_ID,
            risk_type="THESIS_CORE_FACT",
            hard_risk_state="CONFIRMED",
            hard_risk_evaluation="EVALUATED",
            positive_proof=True,
            severity="HIGH",
            coverage=(THESIS_CHECK_ID,),
            reason_codes=_ordered_codes((REASON_HARD_RISK_CONFIRMED, reason)),
            authority_refs=_ordered_refs(refs),
        )
        return assessment, None, False, False, False

    if effective_state in {"STABLE", "STRENGTHENED", "WEAKENED"}:
        # A non-terminal Thesis is a valid observation, but it is not proof
        # that every implemented Hard Risk check is clear.
        return None, REASON_NO_POSITIVE_HARD_RISK_PROOF, False, False, True
    if effective_state == "UNKNOWN":
        return None, REASON_THESIS_AMBIGUOUS, False, False, False
    return None, REASON_AUTHORITY_PAYLOAD_INVALID, False, True, False


def _register_assessment(
    reduction: _Reduction,
    seen_by_check: dict[str, tuple[Any, ...]],
    assessment: _Assessment,
) -> None:
    previous = seen_by_check.get(assessment.check_id)
    if previous is not None:
        if previous != assessment.signature:
            reduction.conflict = True
            reduction.unknown_reasons.append(REASON_HARD_RISK_PROOF_CONFLICT)
        return
    seen_by_check[assessment.check_id] = assessment.signature
    reduction.assessments.append(assessment)
    reduction.supported_authority_observed = True


def _apply_record_outcome(
    reduction: _Reduction,
    *,
    seen_by_check: dict[str, tuple[Any, ...]],
    assessment: _Assessment | None,
    reason: str | None,
    scope_rejection: bool,
    payload_rejection: bool,
    neutral: bool = False,
) -> None:
    if assessment is not None:
        _register_assessment(reduction, seen_by_check, assessment)
        return
    if neutral:
        reduction.supported_authority_observed = True
        reduction.neutral_observed = True
    if reason is not None:
        if scope_rejection:
            reduction.identity_or_time_rejection = True
            reduction.not_evaluated_reasons.append(reason)
        elif payload_rejection:
            reduction.payload_rejection = True
            reduction.unknown_reasons.append(reason)
        elif reason == REASON_THESIS_NOT_READY:
            reduction.not_evaluated_reasons.append(reason)
            reduction.supported_authority_observed = True
        elif reason == REASON_NO_POSITIVE_HARD_RISK_PROOF:
            reduction.unknown_reasons.append(reason)
            reduction.supported_authority_observed = True
        else:
            reduction.unknown_reasons.append(reason)
            reduction.supported_authority_observed = True


def _reduce(
    *, scope: _Scope, authoritative_facts: Mapping[str, Any]
) -> HardRiskEvaluation:
    reduction = _Reduction(assessments=[], unknown_reasons=[], not_evaluated_reasons=[])
    seen_by_check: dict[str, tuple[Any, ...]] = {}

    if FORMAL_THESIS_PROJECTION_KEY in authoritative_facts:
        result = _parse_formal_thesis_projection(
            authoritative_facts[FORMAL_THESIS_PROJECTION_KEY], scope
        )
        _apply_record_outcome(
            reduction,
            seen_by_check=seen_by_check,
            assessment=result[0],
            reason=result[1],
            scope_rejection=result[2],
            payload_rejection=result[3],
            neutral=result[4],
        )

    if HARD_RISK_PROOFS_KEY in authoritative_facts:
        proofs = authoritative_facts[HARD_RISK_PROOFS_KEY]
        if not isinstance(proofs, (list, tuple)):
            reduction.payload_rejection = True
            reduction.unknown_reasons.append(REASON_AUTHORITY_PAYLOAD_INVALID)
        elif not proofs:
            reduction.not_evaluated_reasons.append(REASON_AUTHORITY_NOT_EVALUATED)
        else:
            for index, proof in enumerate(proofs):
                result = _parse_explicit_proof(proof, scope, index=index)
                _apply_record_outcome(
                    reduction,
                    seen_by_check=seen_by_check,
                    assessment=result[0],
                    reason=result[1],
                    scope_rejection=result[2],
                    payload_rejection=result[3],
                )

    confirmed = [
        item
        for item in reduction.assessments
        if item.hard_risk_state == "CONFIRMED"
        and item.hard_risk_evaluation == "EVALUATED"
        and item.positive_proof
        and item.severity in HIGH_SEVERITIES
    ]
    clear = [
        item
        for item in reduction.assessments
        if item.hard_risk_state == "CLEAR"
        and item.hard_risk_evaluation == "EVALUATED"
        and item.positive_proof
        and ALL_IMPLEMENTED_HARD_RISK_CHECKS in item.coverage
    ]
    unknown_assessments = [
        item
        for item in reduction.assessments
        if item.hard_risk_state == "UNKNOWN"
    ]
    error_assessments = [
        item
        for item in unknown_assessments
        if item.hard_risk_evaluation == "ERROR"
    ]
    not_evaluated_assessments = [
        item
        for item in reduction.assessments
        if item.hard_risk_state == "NOT_EVALUATED"
    ]

    if confirmed and (clear or reduction.conflict):
        state = "UNKNOWN"
        evaluation = "UNKNOWN"
        reasons = [REASON_HARD_RISK_PROOF_CONFLICT]
        refs: list[str] = []
        for item in confirmed + clear:
            refs.extend(item.authority_refs)
    elif confirmed:
        state = "CONFIRMED"
        evaluation = "EVALUATED"
        reasons = [REASON_HARD_RISK_CONFIRMED]
        refs = []
        for item in confirmed:
            reasons.extend(item.reason_codes)
            refs.extend(item.authority_refs)
    elif clear and not (
        unknown_assessments
        or not_evaluated_assessments
        or reduction.unknown_reasons
        or reduction.not_evaluated_reasons
        or reduction.identity_or_time_rejection
        or reduction.payload_rejection
    ):
        state = "CLEAR"
        evaluation = "EVALUATED"
        reasons = [REASON_CLEAR_POSITIVE_PROOF]
        refs = []
        for item in clear:
            reasons.extend(item.reason_codes)
            refs.extend(item.authority_refs)
    elif (
        unknown_assessments
        or reduction.unknown_reasons
        or reduction.conflict
        or reduction.payload_rejection
        or reduction.neutral_observed
    ):
        state = "UNKNOWN"
        evaluation = "ERROR" if error_assessments else "UNKNOWN"
        reasons = [REASON_AUTHORITY_PROOF_AMBIGUOUS]
        refs = []
        for item in unknown_assessments:
            reasons.extend(item.reason_codes)
            refs.extend(item.authority_refs)
        reasons.extend(reduction.unknown_reasons)
    else:
        state = "NOT_EVALUATED"
        evaluation = "NOT_EVALUATED"
        reasons = [REASON_NO_HARD_RISK_AUTHORITY]
        refs = []
        if not reduction.supported_authority_observed:
            reasons.extend(reduction.not_evaluated_reasons)
        else:
            reasons.extend(reduction.not_evaluated_reasons)
            for item in not_evaluated_assessments:
                reasons.extend(item.reason_codes)
        if reduction.identity_or_time_rejection:
            reasons.extend(reduction.not_evaluated_reasons)

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


def evaluate_hard_risk(
    *,
    campaign_id: object,
    campaign: Mapping[str, Any],
    as_of: object,
    authoritative_facts: Mapping[str, Any],
) -> HardRiskEvaluation:
    """Evaluate one Campaign-scoped Formal Hard Risk result.

    ``campaign`` must be the backend Campaign authority record and contain
    ``campaign_id``, ``security_code`` and ``strategy``.  ``campaign_id`` is
    accepted separately only as the caller's locator; the output identity is
    always derived from the Campaign record.

    ``authoritative_facts`` may contain:

    ``formal_thesis_projection``
        An envelope around the existing ``formal_thesis_projection_core``
        result.  The envelope adds the exact Campaign scope, the explicit
        ``as_of`` and retained ``authority_refs``.

    ``hard_risk_proofs``
        A sequence of already normalized authority proof envelopes.  A
        ``CONFIRMED`` envelope must be ``EVALUATED``, high/critical severity,
        and ``positive_proof=True``.  A ``CLEAR`` envelope must additionally
        carry ``coverage=[ALL_IMPLEMENTED_HARD_RISK_CHECKS]``.  This is the
        composition boundary for future formal eligibility/financial/regulatory
        authorities; HR1 does not invent those missing fact classifiers.

    Other known keys (top risk, Critical Data, Data Health, disclosures,
    financials, exchange routing and raw eligibility/special-status facts) are
    deliberately non-authoritative and are ignored by the reducer.

    The returned :class:`HardRiskEvaluation` is frozen and directly satisfies
    ``backend/hard_risk_contract.py``.  Malformed top-level Campaign identity
    raises ``HardRiskRuntimeError`` because no valid contract result can carry
    an invalid identity.  Malformed or out-of-scope authority facts fail closed
    as ``UNKNOWN``/``NOT_EVALUATED`` and never as ``CLEAR``.
    """
    scope = _campaign_scope(campaign_id=campaign_id, campaign=campaign, as_of=as_of)
    if not isinstance(authoritative_facts, Mapping):
        raise HardRiskRuntimeError("authoritative_facts must be a Mapping")
    unknown_keys = set(authoritative_facts) - ALLOWED_INPUT_KEYS
    if unknown_keys:
        # Unknown input shapes are not silently promoted to authority.
        return HardRiskEvaluation(
            security_code=scope.security_code,
            strategy=scope.strategy,
            campaign_id=scope.campaign_id,
            as_of=scope.as_of,
            hard_risk_state="NOT_EVALUATED",
            hard_risk_evaluation="NOT_EVALUATED",
            reason_codes=_ordered_codes(
                (REASON_NO_HARD_RISK_AUTHORITY, REASON_AUTHORITY_PAYLOAD_INVALID)
            ),
            authority_refs=(),
        )
    return _reduce(scope=scope, authoritative_facts=authoritative_facts)


def evaluate_hard_risk_mapping(
    *,
    campaign_id: object,
    campaign: Mapping[str, Any],
    as_of: object,
    authoritative_facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a detached JSON/API mapping for runtime callers."""
    return evaluate_hard_risk(
        campaign_id=campaign_id,
        campaign=campaign,
        as_of=as_of,
        authoritative_facts=authoritative_facts,
    ).to_dict()


__all__ = [
    "ALL_IMPLEMENTED_HARD_RISK_CHECKS",
    "ALLOWED_INPUT_KEYS",
    "FORMAL_THESIS_PROJECTION_KEY",
    "HARD_RISK_PROOFS_KEY",
    "HardRiskRuntimeError",
    "NON_AUTHORITY_INPUT_KEYS",
    "POLICY_VERSION_V01",
    "SCHEMA_VERSION",
    "THESIS_CHECK_ID",
    "evaluate_hard_risk",
    "evaluate_hard_risk_mapping",
]
