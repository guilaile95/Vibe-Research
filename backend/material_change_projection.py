"""Material Change authority v0.1 (P0-DC1).

This module is the deterministic boundary between EC1 temporal facts and the
later Decision Proposal.  EC1 remains the sole authority for whether evidence
is after a Frozen Decision; this module is the only place that may interpret
named Current Thesis / Hard Risk facts as a review-worthy material change.

The public input surface deliberately has no ``material_change_state``,
``severity`` or ``positive_proof`` argument.  A caller cannot manufacture a
material conclusion by wrapping a self-declared label in a generic envelope.

Pure-domain boundary:

* no database, filesystem, network, provider, FastAPI, AI, randomness, or
  wall-clock access;
* ``campaign_id`` is an identity locator only; identity facts are checked on
  every named authority result;
* ``NEW_AFTER_DECISION`` is never material by itself;
* ``UNKNOWN``, ``NOT_EVALUATED`` and ``ERROR`` remain distinct.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from decision_evidence_delta_projection import (
    DecisionEvidenceDelta,
    NEW_AFTER_DECISION,
    OUT_OF_SCOPE,
    PREEXISTING_AT_DECISION,
    SCHEMA_VERSION as EVIDENCE_DELTA_SCHEMA_VERSION,
    UNKNOWN_TEMPORAL_RELATION,
)
from hard_risk_contract import HardRiskEvaluation


SCHEMA_VERSION = "material_change.projection.v0.1"
AUTHORITY_REF = "material_change:projection:v0.1"
EVIDENCE_DELTA_AUTHORITY_REF = "decision_evidence_delta:projection:v0.1"
CURRENT_THESIS_AUTHORITY_REF = "formal_current_thesis.projection.v0.1"

MATERIAL_CHANGE_STATES: tuple[str, ...] = (
    "NONE",
    "CONFIRMED",
    "UNKNOWN",
    "NOT_EVALUATED",
)
EVALUATION_STATES: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
THESIS_STATES: tuple[str, ...] = (
    "STRENGTHENED",
    "STABLE",
    "WEAKENED",
    "DISPROVEN",
    "INVALIDATED",
    "UNKNOWN",
)
TERMINAL_THESIS_STATES = frozenset({"DISPROVEN", "INVALIDATED"})
VALID_STRATEGIES = ("SHORT", "SWING", "MEDIUM")

NO_EVIDENCE = "NO_EVIDENCE"

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_THESIS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DECISION_ID_RE = re.compile(r"^decision_[0-9a-f]{32}$")
_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)


class MaterialChangeError(ValueError):
    """Base class for Material Change contract failures."""


class MaterialChangeValidationError(MaterialChangeError):
    """Malformed or semantically mismatched named authority input."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise MaterialChangeValidationError(
            f"{field} must be a non-empty trimmed string"
        )
    return value


def _require_security_code(value: object, field: str = "security_code") -> str:
    code = _require_text(value, field)
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise MaterialChangeValidationError(f"{field} must be exactly 6 digits")
    return code


def _require_strategy(value: object, field: str = "strategy") -> str:
    strategy = _require_text(value, field)
    if strategy not in VALID_STRATEGIES:
        raise MaterialChangeValidationError(
            f"{field} must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object, field: str = "campaign_id") -> str:
    campaign_id = _require_text(value, field)
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise MaterialChangeValidationError(
            f"{field} must match campaign_<32 lowercase hex>"
        )
    return campaign_id


def _parse_utc(value: object, field: str) -> tuple[str, datetime]:
    text = _require_text(value, field)
    if not any(pattern.fullmatch(text) for pattern in _AS_OF_UTC_FORMS):
        raise MaterialChangeValidationError(
            f"{field} must be an explicit UTC zero-offset instant"
        )
    parse_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise MaterialChangeValidationError(
            f"{field} is not a valid UTC instant"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MaterialChangeValidationError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset().total_seconds() != 0:
        raise MaterialChangeValidationError(f"{field} must use UTC zero offset")
    return text, parsed.astimezone(timezone.utc)


def _ordered_refs(refs: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(refs, (tuple, list)) or not refs:
        raise MaterialChangeValidationError(
            "authority_refs must be a non-empty tuple/list of strings"
        )
    cleaned = []
    for index, ref in enumerate(refs):
        value = _require_text(ref, f"authority_refs[{index}]")
        cleaned.append(value)
    if len(cleaned) != len(set(cleaned)):
        raise MaterialChangeValidationError("authority_refs must not contain duplicates")
    return tuple(sorted(cleaned))


@dataclass(frozen=True)
class CurrentThesisAuthority:
    """Exact envelope around the existing Current Thesis projection.

    The envelope is a named source contract, not a generic conclusion input:
    the projection supplies ``effective_state`` and its own identity.  This
    wrapper is intentionally reusable by Sell Engine and Proposal so those
    consumers do not each invent a second Thesis parser.
    """

    security_code: str
    strategy: str
    campaign_id: str
    as_of: str
    authority_refs: tuple[str, ...]
    projection: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_security_code(self.security_code)
        _require_strategy(self.strategy)
        _require_campaign_id(self.campaign_id)
        _parse_utc(self.as_of, "as_of")
        if type(self.authority_refs) is not tuple:
            raise MaterialChangeValidationError(
                "CurrentThesisAuthority.authority_refs must be a tuple"
            )
        object.__setattr__(self, "authority_refs", _ordered_refs(self.authority_refs))
        if not isinstance(self.projection, Mapping):
            raise MaterialChangeValidationError(
                "CurrentThesisAuthority.projection must be a Mapping"
            )
        object.__setattr__(self, "projection", copy.deepcopy(dict(self.projection)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "as_of": self.as_of,
            "authority_refs": list(self.authority_refs),
            "projection": copy.deepcopy(dict(self.projection)),
        }


def current_thesis_authority_from_mapping(
    value: Mapping[str, Any],
) -> CurrentThesisAuthority:
    """Adapt the existing HR1 Current Thesis envelope without re-projecting it."""

    if not isinstance(value, Mapping):
        raise MaterialChangeValidationError(
            "current thesis authority must be a Mapping"
        )
    required = {
        "campaign_id",
        "security_code",
        "strategy",
        "as_of",
        "authority_refs",
        "projection",
    }
    optional = {"fact_time", "event_at", "effective_at"}
    keys = set(value)
    missing = required - keys
    extra = keys - required - optional
    if missing or extra:
        raise MaterialChangeValidationError(
            "current thesis authority fields must be the named projection "
            f"envelope; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return CurrentThesisAuthority(
        security_code=value["security_code"],
        strategy=value["strategy"],
        campaign_id=value["campaign_id"],
        as_of=value["as_of"],
        authority_refs=tuple(value["authority_refs"]),
        projection=value["projection"],
    )


@dataclass(frozen=True)
class MaterialChangeProjection:
    """Detached, deterministic Material Change result."""

    schema_version: str
    authority_ref: str
    security_code: str
    strategy: str
    campaign_id: str
    decision_id: str
    decision_boundary_at: str
    as_of: str
    material_change_state: str
    material_change_evaluation: str
    thesis_id: str | None
    thesis_state: str | None
    evidence_relation: str
    materiality_basis: str
    reason_codes: tuple[str, ...]
    uncertainties: tuple[str, ...]
    authority_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise MaterialChangeValidationError("unsupported Material Change schema")
        if self.authority_ref != AUTHORITY_REF:
            raise MaterialChangeValidationError("invalid Material Change authority_ref")
        _require_security_code(self.security_code)
        _require_strategy(self.strategy)
        _require_campaign_id(self.campaign_id)
        if _DECISION_ID_RE.fullmatch(self.decision_id) is None:
            raise MaterialChangeValidationError("decision_id must match decision_<32 hex>")
        _, boundary_dt = _parse_utc(self.decision_boundary_at, "decision_boundary_at")
        _, as_of_dt = _parse_utc(self.as_of, "as_of")
        if as_of_dt < boundary_dt:
            raise MaterialChangeValidationError(
                "as_of cannot be before decision_boundary_at"
            )
        legal_pairs = {
            "NONE": {"EVALUATED"},
            "CONFIRMED": {"EVALUATED"},
            "UNKNOWN": {"UNKNOWN", "ERROR"},
            "NOT_EVALUATED": {"NOT_EVALUATED"},
        }
        if self.material_change_state not in MATERIAL_CHANGE_STATES:
            raise MaterialChangeValidationError("invalid material_change_state")
        if self.material_change_evaluation not in EVALUATION_STATES:
            raise MaterialChangeValidationError("invalid material_change_evaluation")
        if self.material_change_evaluation not in legal_pairs[self.material_change_state]:
            raise MaterialChangeValidationError(
                "illegal Material Change state/evaluation pair"
            )
        if self.thesis_id is not None and _THESIS_ID_RE.fullmatch(self.thesis_id) is None:
            raise MaterialChangeValidationError("thesis_id must be 32 lowercase hex")
        if self.thesis_state is not None and self.thesis_state not in THESIS_STATES:
            raise MaterialChangeValidationError("invalid thesis_state")
        if self.evidence_relation not in {
            NEW_AFTER_DECISION,
            PREEXISTING_AT_DECISION,
            UNKNOWN_TEMPORAL_RELATION,
            OUT_OF_SCOPE,
            NO_EVIDENCE,
        }:
            raise MaterialChangeValidationError("invalid evidence_relation")
        _require_text(self.materiality_basis, "materiality_basis")
        object.__setattr__(self, "reason_codes", _ordered_refs(self.reason_codes))
        object.__setattr__(self, "uncertainties", _ordered_refs(self.uncertainties) if self.uncertainties else ())
        object.__setattr__(self, "authority_refs", _ordered_refs(self.authority_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority_ref": self.authority_ref,
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "decision_id": self.decision_id,
            "decision_boundary_at": self.decision_boundary_at,
            "as_of": self.as_of,
            "material_change_state": self.material_change_state,
            "material_change_evaluation": self.material_change_evaluation,
            "thesis_id": self.thesis_id,
            "thesis_state": self.thesis_state,
            "evidence_relation": self.evidence_relation,
            "materiality_basis": self.materiality_basis,
            "reason_codes": list(self.reason_codes),
            "uncertainties": list(self.uncertainties),
            "authority_refs": list(self.authority_refs),
        }


def material_change_projection_from_mapping(
    value: Mapping[str, Any],
) -> MaterialChangeProjection:
    """Strict adapter for a JSON result produced by this module."""

    if not isinstance(value, Mapping):
        raise MaterialChangeValidationError("Material Change result must be a Mapping")
    expected = {
        "schema_version",
        "authority_ref",
        "security_code",
        "strategy",
        "campaign_id",
        "decision_id",
        "decision_boundary_at",
        "as_of",
        "material_change_state",
        "material_change_evaluation",
        "thesis_id",
        "thesis_state",
        "evidence_relation",
        "materiality_basis",
        "reason_codes",
        "uncertainties",
        "authority_refs",
    }
    if set(value) != expected:
        raise MaterialChangeValidationError(
            f"Material Change result fields must exactly equal {sorted(expected)}"
        )
    return MaterialChangeProjection(
        schema_version=value["schema_version"],
        authority_ref=value["authority_ref"],
        security_code=value["security_code"],
        strategy=value["strategy"],
        campaign_id=value["campaign_id"],
        decision_id=value["decision_id"],
        decision_boundary_at=value["decision_boundary_at"],
        as_of=value["as_of"],
        material_change_state=value["material_change_state"],
        material_change_evaluation=value["material_change_evaluation"],
        thesis_id=value["thesis_id"],
        thesis_state=value["thesis_state"],
        evidence_relation=value["evidence_relation"],
        materiality_basis=value["materiality_basis"],
        reason_codes=tuple(value["reason_codes"]),
        uncertainties=tuple(value["uncertainties"]),
        authority_refs=tuple(value["authority_refs"]),
    )


@dataclass(frozen=True)
class _ThesisFact:
    evaluation: str
    state: str | None
    thesis_id: str | None
    delta_after_decision: bool | None
    reason_codes: tuple[str, ...]
    authority_refs: tuple[str, ...]


def _validate_evidence_delta(
    delta: DecisionEvidenceDelta,
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of_dt: datetime,
) -> tuple[str, datetime]:
    if not isinstance(delta, DecisionEvidenceDelta):
        raise MaterialChangeValidationError(
            "decision_evidence_delta must be the named DecisionEvidenceDelta result"
        )
    if delta.schema_version != EVIDENCE_DELTA_SCHEMA_VERSION:
        raise MaterialChangeValidationError("unsupported DecisionEvidenceDelta schema")
    if (
        delta.security_code != security_code
        or delta.strategy != strategy
        or delta.campaign_id != campaign_id
    ):
        raise MaterialChangeValidationError(
            "DecisionEvidenceDelta identity does not match Material Change scope"
        )
    if _DECISION_ID_RE.fullmatch(delta.decision_id) is None:
        raise MaterialChangeValidationError("DecisionEvidenceDelta decision_id is invalid")
    _, boundary_dt = _parse_utc(
        delta.decision_boundary_at, "decision_boundary_at"
    )
    if as_of_dt < boundary_dt:
        raise MaterialChangeValidationError(
            "as_of cannot be before DecisionEvidenceDelta boundary"
        )
    buckets = (
        delta.new_evidence,
        delta.preexisting_evidence,
        delta.unknown_temporal_evidence,
        delta.out_of_scope_evidence,
    )
    if any(type(bucket) is not tuple for bucket in buckets):
        raise MaterialChangeValidationError(
            "DecisionEvidenceDelta buckets must be tuples"
        )
    ids = [item for bucket in buckets for item in bucket]
    if any(not isinstance(item, str) or not item for item in ids):
        raise MaterialChangeValidationError(
            "DecisionEvidenceDelta buckets must contain non-empty ids"
        )
    if len(ids) != len(set(ids)):
        raise MaterialChangeValidationError(
            "DecisionEvidenceDelta evidence buckets must be disjoint"
        )
    if type(delta.has_new_evidence) is not bool:
        raise MaterialChangeValidationError("DecisionEvidenceDelta.has_new_evidence must be bool")
    if delta.has_new_evidence is not bool(delta.new_evidence):
        raise MaterialChangeValidationError(
            "DecisionEvidenceDelta.has_new_evidence is inconsistent"
        )
    if type(delta.temporal_coverage_complete) is not bool:
        raise MaterialChangeValidationError(
            "DecisionEvidenceDelta.temporal_coverage_complete must be bool"
        )
    if delta.temporal_coverage_complete != (not bool(delta.unknown_temporal_evidence)):
        raise MaterialChangeValidationError(
            "DecisionEvidenceDelta.temporal_coverage_complete is inconsistent"
        )
    return delta.decision_boundary_at, boundary_dt


def _read_thesis_fact(
    authority: CurrentThesisAuthority | None,
    *,
    decision_boundary_dt: datetime,
    as_of_dt: datetime,
) -> _ThesisFact:
    if authority is None:
        return _ThesisFact(
            evaluation="NOT_EVALUATED",
            state=None,
            thesis_id=None,
            delta_after_decision=None,
            reason_codes=("THESIS_AUTHORITY_NOT_AVAILABLE",),
            authority_refs=(),
        )

    projection = dict(authority.projection)
    if projection.get("campaign_id") != authority.campaign_id:
        raise MaterialChangeValidationError(
            "Current Thesis projection campaign_id does not match its envelope"
        )
    if projection.get("strategy") not in (None, authority.strategy):
        raise MaterialChangeValidationError(
            "Current Thesis projection strategy does not match its envelope"
        )
    thesis_id = projection.get("thesis_id")
    if not isinstance(thesis_id, str) or _THESIS_ID_RE.fullmatch(thesis_id) is None:
        raise MaterialChangeValidationError("Current Thesis projection thesis_id is invalid")

    if projection.get("formal_status") != "READY":
        return _ThesisFact(
            evaluation="NOT_EVALUATED",
            state=None,
            thesis_id=thesis_id,
            delta_after_decision=None,
            reason_codes=("THESIS_NOT_READY",),
            authority_refs=authority.authority_refs,
        )

    if projection.get("schema_version") != CURRENT_THESIS_AUTHORITY_REF:
        raise MaterialChangeValidationError(
            "Current Thesis projection schema is not the named authority schema"
        )
    state = projection.get("effective_state")
    if state not in THESIS_STATES:
        raise MaterialChangeValidationError("Current Thesis effective_state is invalid")
    terminal = projection.get("terminal")
    if type(terminal) is not bool or terminal != (state in TERMINAL_THESIS_STATES):
        raise MaterialChangeValidationError(
            "Current Thesis terminal flag conflicts with effective_state"
        )
    frozen_revision = projection.get("original", {}).get("revision")
    if (
        not isinstance(frozen_revision, int)
        or isinstance(frozen_revision, bool)
        or frozen_revision < 1
    ):
        raise MaterialChangeValidationError(
            "Current Thesis projection original.revision is invalid"
        )

    latest_delta = projection.get("latest_delta")
    if latest_delta is not None and not isinstance(latest_delta, Mapping):
        raise MaterialChangeValidationError("Current Thesis latest_delta must be a Mapping")
    if latest_delta is None:
        if state != "STABLE":
            raise MaterialChangeValidationError(
                "non-STABLE Current Thesis must expose latest_delta"
            )
        return _ThesisFact(
            evaluation="EVALUATED",
            state=state,
            thesis_id=thesis_id,
            delta_after_decision=False,
            reason_codes=("THESIS_STABLE_NO_DELTA",),
            authority_refs=authority.authority_refs,
        )

    if latest_delta.get("delta_state") != state:
        raise MaterialChangeValidationError(
            "Current Thesis latest_delta does not match effective_state"
        )
    confirmed_at = latest_delta.get("confirmed_at")
    if confirmed_at is None:
        delta_after_decision = None
    else:
        _, confirmed_dt = _parse_utc(confirmed_at, "Current Thesis latest_delta.confirmed_at")
        if confirmed_dt > as_of_dt:
            raise MaterialChangeValidationError(
                "Current Thesis latest_delta.confirmed_at is a lookahead"
            )
        delta_after_decision = confirmed_dt > decision_boundary_dt

    return _ThesisFact(
        evaluation="UNKNOWN" if state == "UNKNOWN" else "EVALUATED",
        state=state,
        thesis_id=thesis_id,
        delta_after_decision=delta_after_decision,
        reason_codes=(f"THESIS_{state}",),
        authority_refs=authority.authority_refs,
    )


def _build_result(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    decision_id: str,
    decision_boundary_at: str,
    as_of: str,
    state: str,
    evaluation: str,
    thesis_id: str | None,
    thesis_state: str | None,
    evidence_relation: str,
    materiality_basis: str,
    reason_codes: tuple[str, ...],
    uncertainties: tuple[str, ...],
    authority_refs: tuple[str, ...],
) -> MaterialChangeProjection:
    def unique(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value for value in values if value))

    return MaterialChangeProjection(
        schema_version=SCHEMA_VERSION,
        authority_ref=AUTHORITY_REF,
        security_code=security_code,
        strategy=strategy,
        campaign_id=campaign_id,
        decision_id=decision_id,
        decision_boundary_at=decision_boundary_at,
        as_of=as_of,
        material_change_state=state,
        material_change_evaluation=evaluation,
        thesis_id=thesis_id,
        thesis_state=thesis_state,
        evidence_relation=evidence_relation,
        materiality_basis=materiality_basis,
        reason_codes=unique(reason_codes),
        uncertainties=unique(uncertainties),
        authority_refs=unique(authority_refs),
    )


def project_material_change(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    decision_evidence_delta: DecisionEvidenceDelta,
    current_thesis_authority: CurrentThesisAuthority | None,
    hard_risk_evaluation: HardRiskEvaluation | None,
) -> MaterialChangeProjection:
    """Project Material Change from named, already-evaluated domain facts.

    ``NEW_AFTER_DECISION`` is only a temporal fact.  A material conclusion is
    confirmed by a named Current Thesis semantic delta (WEAKENED or terminal)
    or by a validated Hard Risk ``CONFIRMED`` result.  A new evidence bucket
    without either source remains ``UNKNOWN``.  A pre-existing evidence bucket
    cannot create a decision-after change.
    """

    security = _require_security_code(security_code)
    strategy_value = _require_strategy(strategy)
    campaign = _require_campaign_id(campaign_id)
    as_of_text, as_of_dt = _parse_utc(as_of, "as_of")
    boundary_at, boundary_dt = _validate_evidence_delta(
        decision_evidence_delta,
        security_code=security,
        strategy=strategy_value,
        campaign_id=campaign,
        as_of_dt=as_of_dt,
    )
    if current_thesis_authority is not None and not isinstance(
        current_thesis_authority, CurrentThesisAuthority
    ):
        raise MaterialChangeValidationError(
            "current_thesis_authority must be CurrentThesisAuthority or None"
        )
    if hard_risk_evaluation is not None and not isinstance(
        hard_risk_evaluation, HardRiskEvaluation
    ):
        raise MaterialChangeValidationError(
            "hard_risk_evaluation must be HardRiskEvaluation or None"
        )

    if current_thesis_authority is not None:
        if (
            current_thesis_authority.security_code != security
            or current_thesis_authority.strategy != strategy_value
            or current_thesis_authority.campaign_id != campaign
            or current_thesis_authority.as_of != as_of_text
        ):
            raise MaterialChangeValidationError(
                "Current Thesis authority identity/as_of mismatch"
            )
    if hard_risk_evaluation is not None:
        if (
            hard_risk_evaluation.security_code != security
            or hard_risk_evaluation.strategy != strategy_value
            or hard_risk_evaluation.campaign_id != campaign
            or hard_risk_evaluation.as_of != as_of_text
        ):
            raise MaterialChangeValidationError(
                "Hard Risk identity/as_of mismatch"
            )

    evidence = decision_evidence_delta
    if evidence.unknown_temporal_evidence:
        relation = UNKNOWN_TEMPORAL_RELATION
    elif evidence.new_evidence:
        relation = NEW_AFTER_DECISION
    elif evidence.preexisting_evidence:
        relation = PREEXISTING_AT_DECISION
    elif evidence.out_of_scope_evidence:
        relation = OUT_OF_SCOPE
    else:
        relation = NO_EVIDENCE

    thesis = _read_thesis_fact(
        current_thesis_authority,
        decision_boundary_dt=boundary_dt,
        as_of_dt=as_of_dt,
    )
    thesis_id = thesis.thesis_id
    thesis_state = thesis.state

    authority_refs = [
        AUTHORITY_REF,
        EVIDENCE_DELTA_AUTHORITY_REF,
        *thesis.authority_refs,
    ]
    if hard_risk_evaluation is not None:
        authority_refs.extend(hard_risk_evaluation.authority_refs)

    # Preserve ERROR as the highest-fidelity evaluation state.  An integrity
    # error in a named authority must not be hidden by a separate EC1
    # UNKNOWN_TEMPORAL_RELATION result.
    if hard_risk_evaluation is not None and hard_risk_evaluation.hard_risk_evaluation == "ERROR":
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="UNKNOWN",
            evaluation="ERROR",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="HARD_RISK_AUTHORITY_ERROR",
            reason_codes=("HARD_RISK_AUTHORITY_ERROR",),
            uncertainties=("HARD_RISK_AUTHORITY_ERROR",),
            authority_refs=tuple(authority_refs),
        )

    if thesis.evaluation == "ERROR":
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="UNKNOWN",
            evaluation="ERROR",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="THESIS_AUTHORITY_ERROR",
            reason_codes=("THESIS_AUTHORITY_ERROR",),
            uncertainties=("THESIS_AUTHORITY_ERROR",),
            authority_refs=tuple(authority_refs),
        )

    # The temporal authority is deliberately fail-closed.  Even a new bucket
    # cannot be called material when another scope-valid item has unknown time
    # semantics; the separate Hard Risk / Thesis result remains available to
    # its own consumers.
    if relation == UNKNOWN_TEMPORAL_RELATION:
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="EC1_TEMPORAL_RELATION_UNKNOWN",
            reason_codes=("EC1_UNKNOWN_TEMPORAL_RELATION",),
            uncertainties=("UNKNOWN_TEMPORAL_RELATION",),
            authority_refs=tuple(authority_refs),
        )

    thesis_delta_without_new_temporal_support = (
        thesis.evaluation == "EVALUATED"
        and thesis.delta_after_decision is True
        and thesis.state in (*TERMINAL_THESIS_STATES, "WEAKENED")
        and relation != NEW_AFTER_DECISION
    )
    if thesis_delta_without_new_temporal_support:
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="THESIS_DELTA_WITHOUT_NEW_EC1_RELATION",
            reason_codes=("THESIS_DELTA_TEMPORAL_CONFLICT",),
            uncertainties=("THESIS_DELTA_TEMPORAL_CONFLICT",),
            authority_refs=tuple(authority_refs),
        )

    thesis_material = (
        thesis.evaluation == "EVALUATED"
        and thesis.delta_after_decision is True
        and thesis.state in (*TERMINAL_THESIS_STATES, "WEAKENED")
        and relation == NEW_AFTER_DECISION
    )
    if thesis_material:
        if thesis.state == "WEAKENED":
            reason = "THESIS_WEAKENED_AFTER_DECISION"
            basis = "THESIS_WEAKENED"
        else:
            reason = f"THESIS_{thesis.state}_AFTER_DECISION"
            basis = "THESIS_TERMINAL"
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="CONFIRMED",
            evaluation="EVALUATED",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis=basis,
            reason_codes=(reason,),
            uncertainties=(),
            authority_refs=tuple(authority_refs),
        )

    # Hard Risk is an independent RA1 authority.  It may create review
    # pressure and uncertainty for downstream consumers, but it cannot prove
    # that a thesis change became material after the decision boundary.  That
    # conclusion requires the independent thesis semantic delta plus EC1's
    # NEW_AFTER_DECISION relation above.
    if hard_risk_evaluation is not None and hard_risk_evaluation.hard_risk_state == "CONFIRMED":
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="HARD_RISK_CONFIRMED_WITHOUT_AFTER_DECISION_PROOF",
            reason_codes=("HARD_RISK_CONFIRMED_WITHOUT_AFTER_DECISION_PROOF",),
            uncertainties=("MATERIAL_CHANGE_AFTER_DECISION_PROOF_MISSING",),
            authority_refs=tuple(authority_refs),
        )

    if thesis.state == "UNKNOWN":
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="THESIS_STATE_UNKNOWN",
            reason_codes=("THESIS_UNKNOWN",),
            uncertainties=("THESIS_UNKNOWN",),
            authority_refs=tuple(authority_refs),
        )

    if hard_risk_evaluation is not None and hard_risk_evaluation.hard_risk_state == "UNKNOWN":
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="HARD_RISK_UNKNOWN",
            reason_codes=("HARD_RISK_UNKNOWN",),
            uncertainties=("HARD_RISK_UNKNOWN",),
            authority_refs=tuple(authority_refs),
        )

    # A new temporal fact without a semantic authority is deliberately not
    # promoted.  This is the key EC1 boundary.
    if relation == NEW_AFTER_DECISION:
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="UNKNOWN",
            evaluation="UNKNOWN",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="NO_MATERIALITY_AUTHORITY",
            reason_codes=("NEW_EVIDENCE_WITHOUT_MATERIALITY_AUTHORITY",),
            uncertainties=("MATERIALITY_AUTHORITY_MISSING",),
            authority_refs=tuple(authority_refs),
        )

    if (
        thesis.evaluation == "EVALUATED"
        and thesis.state in {"STABLE", "STRENGTHENED", "WEAKENED"}
        and hard_risk_evaluation is not None
        and hard_risk_evaluation.hard_risk_state == "CLEAR"
        and hard_risk_evaluation.hard_risk_evaluation == "EVALUATED"
    ):
        return _build_result(
            security_code=security,
            strategy=strategy_value,
            campaign_id=campaign,
            decision_id=evidence.decision_id,
            decision_boundary_at=boundary_at,
            as_of=as_of_text,
            state="NONE",
            evaluation="EVALUATED",
            thesis_id=thesis_id,
            thesis_state=thesis_state,
            evidence_relation=relation,
            materiality_basis="NO_NAMED_MATERIAL_CHANGE_FACT",
            reason_codes=("NO_CONFIRMED_MATERIAL_CHANGE",),
            uncertainties=(),
            authority_refs=tuple(authority_refs),
        )

    return _build_result(
        security_code=security,
        strategy=strategy_value,
        campaign_id=campaign,
        decision_id=evidence.decision_id,
        decision_boundary_at=boundary_at,
        as_of=as_of_text,
        state="NOT_EVALUATED",
        evaluation="NOT_EVALUATED",
        thesis_id=thesis_id,
        thesis_state=thesis_state,
        evidence_relation=relation,
        materiality_basis="MATERIALITY_AUTHORITY_NOT_EVALUATED",
        reason_codes=("MATERIALITY_AUTHORITY_NOT_EVALUATED",),
        uncertainties=("MATERIALITY_AUTHORITY_NOT_EVALUATED",),
        authority_refs=tuple(authority_refs),
    )


__all__ = [
    "AUTHORITY_REF",
    "CURRENT_THESIS_AUTHORITY_REF",
    "CurrentThesisAuthority",
    "EVALUATION_STATES",
    "MaterialChangeError",
    "MaterialChangeProjection",
    "MaterialChangeValidationError",
    "MATERIAL_CHANGE_STATES",
    "SCHEMA_VERSION",
    "THESIS_STATES",
    "current_thesis_authority_from_mapping",
    "material_change_projection_from_mapping",
    "project_material_change",
]
