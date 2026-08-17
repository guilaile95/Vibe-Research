"""P0-DC1 Decision Commit vertical runtime.

This module is the small I/O adapter around the already-approved deterministic
authorities.  It deliberately does not create a second Thesis, Frozen Decision,
Material Change, Sell Engine, or Decision Inbox authority.

The public request surface is campaign_id + user draft fields.  Campaign
security_code / strategy and Current Thesis identity / revision are always
re-read from the backend.  Every authority in one preview receives the same
literal UTC ``as_of`` string.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import campaign_service
import decision_assurance_projection as assurance
import decision_evidence_delta_projection as evidence_delta
import decision_proposal_projection as proposal_projection
import decision_trace_store
import formal_thesis_projection
import frozen_decision_service
import hard_risk_contract as hard_risk_contract
import hard_risk_current_thesis_adapter as thesis_hr_adapter
import hard_risk_runtime as hard_risk_runtime
import material_change_projection as material_projection
import sell_engine_projection as sell_projection


SCHEMA_VERSION = "decision_commit_runtime.v0.1"
FINGERPRINT_SCHEMA_VERSION = "decision_proposal.fingerprint.v0.1"
PROPOSAL_SOURCE_PREFIX = "decision_proposal:"
NO_PRIOR_DECISION_BOUNDARY = "NO_PRIOR_DECISION_BOUNDARY"

# These are backend policy constants.  They are intentionally not accepted
# from the browser and are copied into the existing Frozen Decision contract.
RISK_POLICY_VERSION = "hard-risk-runtime.v0.1"
OPPORTUNITY_POLICY_VERSION = "sell-engine-runtime.v0.1"
DECISION_POLICY_VERSION = "decision-commit-runtime.v0.1"
BEHAVIOR_MODEL_VERSION = "deterministic-only.v0.1"

_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_CAMPAIGN_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_THESIS_RE = re.compile(r"^[0-9a-f]{32}$")
_DECISION_RE = re.compile(r"^decision_[0-9a-f]{32}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class DecisionCommitRuntimeError(RuntimeError):
    """Base runtime error; routers map this to a stable 500 response."""


class DecisionCommitInputError(DecisionCommitRuntimeError, ValueError):
    """Malformed user draft or invalid snapshot token."""


class CurrentThesisUnavailableError(DecisionCommitRuntimeError):
    """The Campaign has no applicable, authority-valid Current Thesis."""


class ProposalStaleError(DecisionCommitRuntimeError):
    """The server-owned proposal fingerprint no longer matches the request."""


class CommitConfirmationRequiredError(DecisionCommitRuntimeError):
    """The explicit user confirmation gate was not satisfied."""


class FrozenDecisionIntegrityError(DecisionCommitRuntimeError):
    """The existing Frozen Decision read-back is not applicable to the scope."""


def utc_now_iso() -> str:
    """Return one canonical, zero-offset UTC instant for a runtime snapshot."""

    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not _UTC_RE.fullmatch(value):
        raise DecisionCommitInputError(f"{field} must be an explicit UTC instant")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise DecisionCommitInputError(f"{field} is not a valid UTC instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DecisionCommitInputError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset().total_seconds() != 0:
        raise DecisionCommitInputError(f"{field} must use UTC zero offset")
    return parsed.astimezone(timezone.utc)


def _canonical_utc(value: object, field: str) -> str:
    return _parse_utc(value, field).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _require_campaign_id(value: object) -> str:
    if not isinstance(value, str) or not _CAMPAIGN_RE.fullmatch(value):
        raise DecisionCommitInputError("campaign_id is invalid")
    return value


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionCommitInputError(f"{field} must be a JSON object")
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DecisionCommitInputError(f"{field} is not JSON-safe") from exc
    return value


def _require_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise DecisionCommitInputError(f"{field} must be a JSON array")
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DecisionCommitInputError(f"{field} is not JSON-safe") from exc
    return copy.deepcopy(value)


def _require_fingerprint(value: object) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_RE.fullmatch(value):
        raise DecisionCommitInputError("expected_proposal_fingerprint is invalid")
    return value


def _assert_identity(
    record: Mapping[str, Any], campaign: Mapping[str, Any], *, label: str
) -> None:
    expected = {
        "campaign_id": campaign["campaign_id"],
        "security_code": campaign["security_code"],
        "strategy": campaign["strategy"],
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise FrozenDecisionIntegrityError(f"{label} identity mismatch")


def _latest_frozen(
    decisions: Sequence[Mapping[str, Any]], campaign: Mapping[str, Any], as_of: str
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    cutoff = _parse_utc(as_of, "as_of")
    latest: Mapping[str, Any] | None = None
    latest_time: datetime | None = None
    for raw in decisions:
        if not isinstance(raw, Mapping):
            raise FrozenDecisionIntegrityError("frozen decision reader returned invalid data")
        _assert_identity(raw, campaign, label="Frozen Decision")
        committed_at = raw.get("committed_at")
        if not isinstance(committed_at, str):
            raise FrozenDecisionIntegrityError("Frozen Decision committed_at is missing")
        committed_time = _parse_utc(committed_at, "frozen decision committed_at")
        if committed_time > cutoff:
            continue
        if latest_time is None or committed_time > latest_time:
            latest = raw
            latest_time = committed_time
    if latest is None:
        return None, None
    decision_id = latest.get("decision_id")
    review_by = latest.get("review_by")
    next_best_action = latest.get("next_best_action")
    if (
        not isinstance(decision_id, str)
        or not _DECISION_RE.fullmatch(decision_id)
        or not isinstance(review_by, str)
        or not isinstance(next_best_action, str)
    ):
        raise FrozenDecisionIntegrityError("Frozen Decision shape is invalid")
    return latest, {
        "decision_id": decision_id,
        "committed_at": latest["committed_at"],
        "review_by": review_by,
        "previous_next_best_action": next_best_action,
    }


def _canonical_current_thesis_projection(
    raw: Mapping[str, Any], campaign: Mapping[str, Any]
) -> dict[str, Any]:
    """Adapt the existing #73 I/O payload to the C projection shape.

    The underlying data is still the single projection returned by
    ``formal_thesis_projection.project_current_thesis``.  This function only
    restores fields that the HTTP adapter intentionally omits.
    """

    if raw.get("campaign_id") != campaign["campaign_id"]:
        raise CurrentThesisUnavailableError("Current Thesis Campaign identity mismatch")
    thesis_id = raw.get("thesis_id")
    if not isinstance(thesis_id, str) or not _THESIS_RE.fullmatch(thesis_id):
        raise CurrentThesisUnavailableError("Current Thesis thesis_id is unavailable")
    binding = raw.get("binding")
    if not isinstance(binding, Mapping):
        raise CurrentThesisUnavailableError("Current Thesis binding is unavailable")
    if binding.get("campaign_strategy_at_bind") != campaign["strategy"]:
        raise CurrentThesisUnavailableError("Current Thesis strategy mismatch")

    formal_status = raw.get("formal_status")
    ready = raw.get("ready")
    if formal_status == "READY" and ready is not True:
        raise CurrentThesisUnavailableError("Current Thesis readiness is inconsistent")
    if formal_status != "READY":
        return {
            "schema_version": material_projection.CURRENT_THESIS_AUTHORITY_REF,
            "campaign_id": campaign["campaign_id"],
            "thesis_id": thesis_id,
            "formal_status": formal_status,
            "ready": False,
            "binding": copy.deepcopy(dict(binding)),
            "effective_state": raw.get("effective_state"),
            "terminal": False,
        }

    frozen_revision = raw.get("frozen_revision")
    if (
        isinstance(frozen_revision, bool)
        or not isinstance(frozen_revision, int)
        or frozen_revision <= 0
    ):
        raise CurrentThesisUnavailableError("Current Thesis frozen_revision is invalid")

    original_snapshot = raw.get("original_snapshot")
    if not isinstance(original_snapshot, Mapping):
        raise CurrentThesisUnavailableError("Current Thesis Original snapshot is unavailable")

    source_deltas = raw.get("deltas")
    if not isinstance(source_deltas, list):
        raise CurrentThesisUnavailableError("Current Thesis delta chain is unavailable")
    deltas: list[dict[str, Any]] = []
    for source in source_deltas:
        if not isinstance(source, Mapping):
            raise CurrentThesisUnavailableError("Current Thesis delta chain is invalid")
        deltas.append(
            {
                "delta_id": source.get("delta_id"),
                "delta_sequence": source.get("delta_sequence"),
                "delta_state": source.get("delta_state"),
                "reason": source.get("reason"),
                "confirmed_at": source.get("confirmed_at"),
                "evidence_snapshots": copy.deepcopy(
                    source.get("evidence_snapshots", source.get("evidence_links", []))
                ),
            }
        )
    deltas.sort(key=lambda item: item.get("delta_sequence", 0))
    latest_delta = copy.deepcopy(deltas[-1]) if deltas else None
    effective_state = raw.get("effective_state", "STABLE")
    return {
        "schema_version": material_projection.CURRENT_THESIS_AUTHORITY_REF,
        "campaign_id": campaign["campaign_id"],
        "thesis_id": thesis_id,
        "formal_status": "READY",
        "ready": True,
        "binding": copy.deepcopy(dict(binding)),
        "binding_audit": copy.deepcopy(dict(binding)),
        "frozen_revision": frozen_revision,
        "original": {
            "revision": frozen_revision,
            "snapshot": copy.deepcopy(dict(original_snapshot)),
        },
        "original_snapshot": copy.deepcopy(dict(original_snapshot)),
        "strategy": campaign["strategy"],
        "effective_state": effective_state,
        "latest_delta": latest_delta,
        "terminal": effective_state in {"DISPROVEN", "INVALIDATED"},
        "deltas": deltas,
    }


def _validate_subject_authority(
    canonical: Mapping[str, Any], campaign: Mapping[str, Any]
) -> None:
    """Validate the real Formal Original subject/strategy facts.

    Formal freeze snapshots carry the original aggregate under ``thesis`` and
    also expose flat fields in newer revisions.  Missing subject facts are not
    guessed from campaign_id; they fail closed.
    """

    original = canonical.get("original", {}).get("snapshot")
    if not isinstance(original, Mapping):
        raise CurrentThesisUnavailableError("Formal Original subject authority is missing")
    subject = original.get("thesis") if isinstance(original.get("thesis"), Mapping) else original
    if subject.get("subject_type") != "stock":
        raise CurrentThesisUnavailableError("Formal Thesis subject_type is not stock")
    if subject.get("subject_id") != campaign["security_code"]:
        raise CurrentThesisUnavailableError("Formal Thesis subject_id does not match Campaign")
    thesis_strategy = subject.get("strategy", original.get("strategy"))
    if thesis_strategy not in (None, campaign["strategy"]):
        raise CurrentThesisUnavailableError("Formal Thesis strategy does not match Campaign")


def _current_thesis_authority(
    raw: Mapping[str, Any] | None,
    campaign: Mapping[str, Any],
    as_of: str,
) -> tuple[dict[str, Any] | None, material_projection.CurrentThesisAuthority | None, str, list[str]]:
    """Return canonical projection, C authority, same-as-of evaluation, reasons."""

    if raw is None:
        return None, None, "NOT_EVALUATED", ["CURRENT_THESIS_MISSING"]
    canonical = _canonical_current_thesis_projection(raw, campaign)
    if canonical.get("formal_status") != "READY":
        return canonical, None, "NOT_EVALUATED", ["CURRENT_THESIS_NOT_READY"]

    _validate_subject_authority(canonical, campaign)
    binding = canonical.get("binding")
    if not isinstance(binding, Mapping):
        raise CurrentThesisUnavailableError("Current Thesis binding is missing")
    bound_at = binding.get("bound_at")
    if not isinstance(bound_at, str):
        return canonical, None, "NOT_EVALUATED", ["CURRENT_THESIS_BOUND_TIME_MISSING"]
    as_of_dt = _parse_utc(as_of, "as_of")
    if _parse_utc(bound_at, "Current Thesis bound_at") > as_of_dt:
        return canonical, None, "NOT_EVALUATED", ["CURRENT_THESIS_LOOKAHEAD"]
    for delta in canonical.get("deltas", []):
        confirmed_at = delta.get("confirmed_at")
        if not isinstance(confirmed_at, str):
            return canonical, None, "NOT_EVALUATED", ["CURRENT_THESIS_DELTA_TIME_MISSING"]
        if _parse_utc(confirmed_at, "Current Thesis confirmed_at") > as_of_dt:
            return canonical, None, "NOT_EVALUATED", ["CURRENT_THESIS_LOOKAHEAD"]

    thesis_id = canonical["thesis_id"]
    revision = canonical["original"]["revision"]
    refs = (f"current_thesis:{campaign['campaign_id']}:{thesis_id}:v{revision}",)
    authority = material_projection.current_thesis_authority_from_mapping(
        {
            "campaign_id": campaign["campaign_id"],
            "security_code": campaign["security_code"],
            "strategy": campaign["strategy"],
            "as_of": as_of,
            "authority_refs": list(refs),
            "projection": canonical,
        }
    )
    return canonical, authority, "EVALUATED", []


def _hard_risk_for_snapshot(
    campaign: Mapping[str, Any],
    as_of: str,
    raw_current_thesis: Mapping[str, Any] | None,
) -> hard_risk_contract.HardRiskEvaluation:
    envelope = thesis_hr_adapter.build_current_thesis_envelope(
        campaign=campaign,
        as_of=as_of,
        current_thesis_projection=(
            _canonical_current_thesis_projection(raw_current_thesis, campaign)
            if raw_current_thesis is not None
            else None
        ),
    )
    result = hard_risk_runtime.evaluate_hard_risk_mapping(
        campaign_id=campaign["campaign_id"],
        campaign=campaign,
        as_of=as_of,
        formal_thesis_projection=envelope,
    )
    return hard_risk_contract.hard_risk_evaluation_from_mapping(result)


def _default_evidence_reader(
    campaign: Mapping[str, Any],
) -> tuple[evidence_delta.NormalizedEvidenceItem, ...]:
    """Read only already-archived evidence when available.

    The legacy trace store has no authoritative ``effective_at`` column.  Such
    rows therefore remain UNKNOWN temporal facts; ``observed_at`` is never used
    as an effective time.  Missing trace storage is an empty candidate set and
    never creates a write as part of a Preview/Inbox read.
    """

    path = decision_trace_store.resolve_decision_trace_db_path()
    if not Path(path).exists():
        return ()
    try:
        result = decision_trace_store.list_evidence_items(
            code=campaign["security_code"], db_path=path, limit=10000
        )
    except Exception as exc:  # noqa: BLE001 - fail closed at caller boundary
        raise DecisionCommitRuntimeError("decision evidence unavailable") from exc
    items: list[evidence_delta.NormalizedEvidenceItem] = []

    def _retrieved_at(raw_value: object) -> str | None:
        if not isinstance(raw_value, str):
            return None
        try:
            return _canonical_utc(raw_value, "retrieved_at")
        except DecisionCommitInputError:
            # The legacy trace timestamp is metadata only.  If it is not the
            # strict EC1 UTC form, retain UNKNOWN rather than coercing it.
            return None

    for raw in result.get("items", []):
        if not isinstance(raw, Mapping):
            raise DecisionCommitRuntimeError("decision evidence record is invalid")
        raw_id = raw.get("evidence_id")
        if not isinstance(raw_id, str) or not raw_id:
            raise DecisionCommitRuntimeError("decision evidence id is missing")
        # EC1's evidence id is a 32-hex value.  The legacy trace id is retained
        # only through this deterministic adapter; no conclusion is inferred.
        evidence_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:32]
        scope_id = raw.get("code") or campaign["security_code"]
        scope_kind = evidence_delta.SCOPE_SECURITY
        if not isinstance(scope_id, str):
            raise DecisionCommitRuntimeError("decision evidence scope is invalid")
        items.append(
            evidence_delta.NormalizedEvidenceItem(
                evidence_id=evidence_id,
                scope_kind=scope_kind,
                scope_id=scope_id,
                effective_at=None,
                retrieved_at=_retrieved_at(raw.get("observed_at") or raw.get("created_at")),
                time_semantics=evidence_delta.TIME_SEMANTICS_UNKNOWN,
                authority_refs=("decision_trace_store:evidence_items",),
            )
        )
    return tuple(items)


def _formal_decision_evaluation(
    frozen: Mapping[str, Any] | None,
    campaign: Mapping[str, Any],
    current_thesis: material_projection.CurrentThesisAuthority | None,
    thesis_evaluation: str,
    as_of: str,
) -> dict[str, Any]:
    if frozen is None:
        return {
            "evaluation": "NOT_EVALUATED",
            "reason_codes": ["NO_COMMITTED_DECISION"],
            "decision_id": None,
            "authority_refs": ["frozen_decision_service", "frozen_decision_store"],
        }
    try:
        _assert_identity(frozen, campaign, label="Frozen Decision")
    except FrozenDecisionIntegrityError:
        return {
            "evaluation": "ERROR",
            "reason_codes": ["FROZEN_DECISION_IDENTITY_MISMATCH"],
            "decision_id": frozen.get("decision_id"),
            "authority_refs": ["frozen_decision_service", "frozen_decision_store"],
        }
    committed_at = frozen.get("committed_at")
    if not isinstance(committed_at, str):
        return {
            "evaluation": "ERROR",
            "reason_codes": ["FROZEN_DECISION_COMMITTED_AT_MISSING"],
            "decision_id": frozen.get("decision_id"),
            "authority_refs": ["frozen_decision_service", "frozen_decision_store"],
        }
    if _parse_utc(committed_at, "Frozen Decision committed_at") > _parse_utc(as_of, "as_of"):
        return {
            "evaluation": "NOT_EVALUATED",
            "reason_codes": ["COMMITTED_AFTER_AS_OF"],
            "decision_id": frozen.get("decision_id"),
            "authority_refs": ["frozen_decision_service", "frozen_decision_store"],
        }
    if thesis_evaluation != "EVALUATED" or current_thesis is None:
        return {
            "evaluation": "NOT_EVALUATED",
            "reason_codes": ["CURRENT_THESIS_NOT_APPLICABLE"],
            "decision_id": frozen.get("decision_id"),
            "authority_refs": ["frozen_decision_service", "frozen_decision_store"],
        }
    if (
        frozen.get("thesis_id") != current_thesis.projection.get("thesis_id")
        or frozen.get("thesis_revision") != current_thesis.projection.get("original", {}).get("revision")
    ):
        return {
            "evaluation": "ERROR",
            "reason_codes": ["FROZEN_DECISION_THESIS_REVISION_MISMATCH"],
            "decision_id": frozen.get("decision_id"),
            "authority_refs": ["frozen_decision_service", "frozen_decision_store"],
        }
    return {
        "evaluation": "EVALUATED",
        "reason_codes": ["FROZEN_DECISION_APPLICABLE"],
        "decision_id": frozen.get("decision_id"),
        "committed_at": committed_at,
        "authority_refs": ["frozen_decision_service", "frozen_decision_store"],
    }


@dataclass(frozen=True)
class AuthorityEvaluations:
    current_thesis_projection: Mapping[str, Any] | None
    current_thesis_authority: material_projection.CurrentThesisAuthority | None
    formal_thesis_evaluation: str
    formal_thesis_reason_codes: tuple[str, ...]
    hard_risk: hard_risk_contract.HardRiskEvaluation
    material_change: material_projection.MaterialChangeProjection | None
    material_change_evaluation: str
    material_change_reason_codes: tuple[str, ...]
    sell_engine: sell_projection.SellEngineProjection
    formal_decision: Mapping[str, Any]
    latest_frozen_raw: Mapping[str, Any] | None
    latest_frozen: Mapping[str, Any] | None
    decision_assurance: Mapping[str, Any]


def evaluate_authorities(
    *,
    campaign: Mapping[str, Any],
    as_of: str,
    current_thesis_projection: Mapping[str, Any] | None,
    frozen_decisions: Sequence[Mapping[str, Any]],
    critical_data_evaluation: str = "NOT_EVALUATED",
    evidence_reader: Callable[[Mapping[str, Any]], Sequence[evidence_delta.NormalizedEvidenceItem]] = _default_evidence_reader,
    hard_risk: hard_risk_contract.HardRiskEvaluation | None = None,
) -> AuthorityEvaluations:
    """Evaluate all DC1 authorities from one already-read Thesis projection."""

    canonical, current_authority, thesis_eval, thesis_reasons = _current_thesis_authority(
        current_thesis_projection, campaign, as_of
    )
    hard = hard_risk or _hard_risk_for_snapshot(campaign, as_of, canonical)
    latest_raw, latest = _latest_frozen(frozen_decisions, campaign, as_of)

    material: material_projection.MaterialChangeProjection | None = None
    material_eval = "NOT_EVALUATED"
    material_reasons: tuple[str, ...] = (NO_PRIOR_DECISION_BOUNDARY,)
    if latest_raw is not None:
        decision_id = latest_raw.get("decision_id")
        boundary_at = latest_raw.get("committed_at")
        if not isinstance(decision_id, str) or not _DECISION_RE.fullmatch(decision_id):
            raise FrozenDecisionIntegrityError("Frozen Decision decision_id is invalid")
        if not isinstance(boundary_at, str):
            raise FrozenDecisionIntegrityError("Frozen Decision boundary is invalid")
        evidence_items = tuple(evidence_reader(campaign))
        delta = evidence_delta.project_decision_evidence_delta(
            context=evidence_delta.DecisionContext(
                security_code=campaign["security_code"],
                strategy=campaign["strategy"],
                campaign_id=campaign["campaign_id"],
                decision_id=decision_id,
                decision_boundary_at=_canonical_utc(boundary_at, "decision_boundary_at"),
            ),
            evidence_items=evidence_items,
        )
        try:
            material = material_projection.project_material_change(
                security_code=campaign["security_code"],
                strategy=campaign["strategy"],
                campaign_id=campaign["campaign_id"],
                as_of=as_of,
                decision_evidence_delta=delta,
                current_thesis_authority=current_authority,
                hard_risk_evaluation=hard,
            )
        except material_projection.MaterialChangeError as exc:
            raise DecisionCommitRuntimeError("Material Change evaluation failed") from exc
        material_eval = material.material_change_evaluation
        material_reasons = material.reason_codes

    sell = sell_projection.project_sell_engine(
        security_code=campaign["security_code"],
        strategy=campaign["strategy"],
        campaign_id=campaign["campaign_id"],
        as_of=as_of,
        current_thesis_authority=current_authority,
        hard_risk_evaluation=hard,
        material_change=material,
    )
    formal_decision = _formal_decision_evaluation(
        latest_raw,
        campaign,
        current_authority,
        thesis_eval,
        as_of,
    )
    decision_assurance = assurance.project_decision_assurance(
        security_code=campaign["security_code"],
        strategy=campaign["strategy"],
        campaign_id=campaign["campaign_id"],
        formal_thesis_evaluation=thesis_eval,
        formal_decision_evaluation=formal_decision["evaluation"],
        hard_risk_evaluation=hard.hard_risk_evaluation,
        material_change_evaluation=material_eval,
        critical_data_evaluation=critical_data_evaluation,
        as_of=as_of,
    )
    return AuthorityEvaluations(
        current_thesis_projection=canonical,
        current_thesis_authority=current_authority,
        formal_thesis_evaluation=thesis_eval,
        formal_thesis_reason_codes=tuple(thesis_reasons),
        hard_risk=hard,
        material_change=material,
        material_change_evaluation=material_eval,
        material_change_reason_codes=tuple(material_reasons),
        sell_engine=sell,
        formal_decision=formal_decision,
        latest_frozen_raw=latest_raw,
        latest_frozen=latest,
        decision_assurance=decision_assurance,
    )


@dataclass(frozen=True)
class RuntimePorts:
    campaign_reader: Callable[[str], Mapping[str, Any]] = campaign_service.get_campaign
    thesis_reader: Callable[[str], Mapping[str, Any]] = formal_thesis_projection.project_current_thesis
    frozen_reader: Callable[..., list[Mapping[str, Any]]] = frozen_decision_service.list_decisions
    evidence_reader: Callable[[Mapping[str, Any]], Sequence[evidence_delta.NormalizedEvidenceItem]] = _default_evidence_reader
    freeze_writer: Callable[[Mapping[str, Any]], Mapping[str, Any]] = frozen_decision_service.freeze_decision
    decision_reader: Callable[[str], Mapping[str, Any] | None] = frozen_decision_service.get_decision


PRODUCTION_PORTS = RuntimePorts()
_COMMIT_LOCK = threading.Lock()


def _read_campaign(ports: RuntimePorts, campaign_id: str) -> Mapping[str, Any]:
    campaign = ports.campaign_reader(campaign_id)
    if not isinstance(campaign, Mapping):
        raise DecisionCommitRuntimeError("Campaign authority is unavailable")
    if campaign.get("campaign_id") != campaign_id:
        raise DecisionCommitRuntimeError("Campaign authority identity mismatch")
    if not isinstance(campaign.get("security_code"), str) or not isinstance(
        campaign.get("strategy"), str
    ):
        raise DecisionCommitRuntimeError("Campaign authority is incomplete")
    return copy.deepcopy(dict(campaign))


def _read_thesis_once(
    ports: RuntimePorts, campaign_id: str
) -> Mapping[str, Any] | None:
    try:
        value = ports.thesis_reader(campaign_id)
    except campaign_service.ThesisBindingNotFoundError:
        return None
    except (
        formal_thesis_projection.CurrentThesisProjectionError,
        campaign_service.CampaignThesisStrategyConflictError,
    ) as exc:
        raise CurrentThesisUnavailableError("Current Thesis projection is unavailable") from exc
    if not isinstance(value, Mapping):
        raise CurrentThesisUnavailableError("Current Thesis projection is invalid")
    return copy.deepcopy(dict(value))


def _read_frozen(ports: RuntimePorts, campaign: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = ports.frozen_reader(campaign_id=campaign["campaign_id"], limit=10000, offset=0)
    if not isinstance(values, list):
        raise FrozenDecisionIntegrityError("Frozen Decision reader must return a list")
    normalized: list[Mapping[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise FrozenDecisionIntegrityError("Frozen Decision reader returned invalid data")
        normalized.append(copy.deepcopy(dict(value)))
    return normalized


def _validate_draft_inputs(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "asset_view",
        "trade_view",
        "portfolio_view",
        "review_by",
        "key_assumptions",
        "event_invalidation_conditions",
        "strategy_horizon",
    }
    extra = set(payload) - allowed
    if extra:
        raise DecisionCommitInputError(f"unknown proposal input: {sorted(extra)}")
    required = allowed
    missing = required - set(payload)
    if missing:
        raise DecisionCommitInputError(f"proposal input is missing: {sorted(missing)}")
    drafts = {
        "asset_view": dict(_require_mapping(payload["asset_view"], "asset_view")),
        "trade_view": dict(_require_mapping(payload["trade_view"], "trade_view")),
        "portfolio_view": dict(_require_mapping(payload["portfolio_view"], "portfolio_view")),
        "review_by": _canonical_utc(payload["review_by"], "review_by"),
        "key_assumptions": _require_list(payload["key_assumptions"], "key_assumptions"),
        "event_invalidation_conditions": _require_list(
            payload["event_invalidation_conditions"], "event_invalidation_conditions"
        ),
        "strategy_horizon": payload["strategy_horizon"],
    }
    if not isinstance(drafts["strategy_horizon"], str) or not drafts["strategy_horizon"].strip():
        raise DecisionCommitInputError("strategy_horizon must be a non-empty string")
    return drafts


def _build_proposal(
    *,
    campaign: Mapping[str, Any],
    as_of: str,
    raw_thesis: Mapping[str, Any] | None,
    frozen: Sequence[Mapping[str, Any]],
    drafts: Mapping[str, Any],
    ports: RuntimePorts,
    evidence_reader: Callable[[Mapping[str, Any]], Sequence[evidence_delta.NormalizedEvidenceItem]] | None = None,
) -> tuple[proposal_projection.DecisionProposal, AuthorityEvaluations]:
    # ``raw_thesis`` is passed in, never read by this function.  This is the
    # single-read guarantee for Current Thesis inside one snapshot.
    authorities = evaluate_authorities(
        campaign=campaign,
        as_of=as_of,
        current_thesis_projection=raw_thesis,
        frozen_decisions=frozen,
        evidence_reader=evidence_reader or ports.evidence_reader,
    )
    if (
        authorities.formal_thesis_evaluation != "EVALUATED"
        or authorities.current_thesis_authority is None
        or authorities.current_thesis_projection is None
    ):
        raise CurrentThesisUnavailableError("Current Thesis is not applicable at this as_of")
    thesis_id = authorities.current_thesis_projection["thesis_id"]
    thesis_revision = authorities.current_thesis_projection["original"]["revision"]
    result = proposal_projection.project_decision_proposal(
        security_code=campaign["security_code"],
        strategy=campaign["strategy"],
        campaign_id=campaign["campaign_id"],
        thesis_id=thesis_id,
        thesis_revision=thesis_revision,
        as_of=as_of,
        asset_view=drafts["asset_view"],
        trade_view=drafts["trade_view"],
        portfolio_view=drafts["portfolio_view"],
        current_thesis_authority=authorities.current_thesis_authority,
        hard_risk_evaluation=authorities.hard_risk,
        material_change=authorities.material_change,
        sell_engine=authorities.sell_engine,
    )
    return result, authorities


def _fingerprint(
    *, proposal: proposal_projection.DecisionProposal, drafts: Mapping[str, Any]
) -> str:
    """Hash every relevant proposal fact, exact identity, and literal as_of."""

    content = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "proposal": proposal.to_dict(),
        "commit_fields": {
            "review_by": drafts["review_by"],
            "key_assumptions": copy.deepcopy(drafts["key_assumptions"]),
            "event_invalidation_conditions": copy.deepcopy(
                drafts["event_invalidation_conditions"]
            ),
            "strategy_horizon": drafts["strategy_horizon"],
        },
    }
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _preview_response(
    proposal: proposal_projection.DecisionProposal,
    authorities: AuthorityEvaluations,
    drafts: Mapping[str, Any],
    fingerprint: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal": proposal.to_dict(),
        "proposal_fingerprint": fingerprint,
        "commit_fields": {
            "review_by": drafts["review_by"],
            "key_assumptions": copy.deepcopy(drafts["key_assumptions"]),
            "event_invalidation_conditions": copy.deepcopy(
                drafts["event_invalidation_conditions"]
            ),
            "strategy_horizon": drafts["strategy_horizon"],
        },
        "authority_evaluations": {
            "formal_thesis": {
                "evaluation": authorities.formal_thesis_evaluation,
                "reason_codes": list(authorities.formal_thesis_reason_codes),
            },
            "formal_decision": copy.deepcopy(dict(authorities.formal_decision)),
            "hard_risk": authorities.hard_risk.to_dict(),
            "material_change": (
                authorities.material_change.to_dict()
                if authorities.material_change is not None
                else {
                    "state": "NOT_EVALUATED",
                    "evaluation": "NOT_EVALUATED",
                    "reason_codes": [NO_PRIOR_DECISION_BOUNDARY],
                }
            ),
            "sell_engine": authorities.sell_engine.to_dict(),
        },
        "decision_assurance": copy.deepcopy(dict(authorities.decision_assurance)),
        "commit_requirements": {
            "user_confirmed": True,
            "expected_proposal_fingerprint": fingerprint,
        },
    }


def preview_decision_proposal(
    campaign_id: str,
    payload: Mapping[str, Any],
    *,
    ports: RuntimePorts = PRODUCTION_PORTS,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Read/compute an uncommitted Proposal; never writes Frozen storage."""

    campaign_key = _require_campaign_id(campaign_id)
    drafts = _validate_draft_inputs(payload)
    snapshot_as_of = utc_now_iso() if as_of is None else as_of
    if not isinstance(snapshot_as_of, str):
        raise DecisionCommitInputError("as_of must be a string")
    if snapshot_as_of != _canonical_utc(snapshot_as_of, "as_of"):
        raise DecisionCommitInputError("as_of must be canonical UTC")
    campaign = _read_campaign(ports, campaign_key)
    raw_thesis = _read_thesis_once(ports, campaign_key)
    frozen = _read_frozen(ports, campaign)
    result, authorities = _build_proposal(
        campaign=campaign,
        as_of=snapshot_as_of,
        raw_thesis=raw_thesis,
        frozen=frozen,
        drafts=drafts,
        ports=ports,
    )
    fingerprint = _fingerprint(proposal=result, drafts=drafts)
    return _preview_response(result, authorities, drafts, fingerprint)


def _freeze_payload(
    proposal: proposal_projection.DecisionProposal,
    authorities: AuthorityEvaluations,
    drafts: Mapping[str, Any],
    fingerprint: str,
) -> dict[str, Any]:
    source_refs = [
        f"{PROPOSAL_SOURCE_PREFIX}{fingerprint}",
        *proposal.authority_refs,
    ]
    return {
        "security_code": proposal.security_code,
        "strategy": proposal.strategy,
        "campaign_id": proposal.campaign_id,
        "thesis_id": proposal.thesis_id,
        "thesis_revision": proposal.thesis_revision,
        "asset_view": copy.deepcopy(dict(proposal.asset_view)),
        "trade_view": copy.deepcopy(dict(proposal.trade_view)),
        "portfolio_view": copy.deepcopy(dict(proposal.portfolio_view)),
        "next_best_action": proposal.next_best_action,
        "action_envelope": copy.deepcopy(dict(proposal.action_envelope)),
        "maintain_conditions": list(proposal.maintain_conditions),
        "upgrade_conditions": list(proposal.upgrade_conditions),
        "downgrade_conditions": list(proposal.downgrade_conditions),
        "invalidation_conditions": list(proposal.invalidation_conditions),
        "strategy_horizon": drafts["strategy_horizon"],
        "review_by": drafts["review_by"],
        "key_assumptions": copy.deepcopy(drafts["key_assumptions"]),
        "event_invalidation_conditions": copy.deepcopy(
            drafts["event_invalidation_conditions"]
        ),
        "risk_policy_version": RISK_POLICY_VERSION,
        "opportunity_policy_version": OPPORTUNITY_POLICY_VERSION,
        "decision_policy_version": DECISION_POLICY_VERSION,
        "behavior_model_version": BEHAVIOR_MODEL_VERSION,
        "risk_refs": list(authorities.hard_risk.authority_refs),
        "source_refs": list(dict.fromkeys(source_refs)),
        "user_confirmed": True,
    }


def _validate_committed_readback(
    frozen: Mapping[str, Any],
    proposal: proposal_projection.DecisionProposal,
    campaign: Mapping[str, Any],
    fingerprint: str,
) -> None:
    _assert_identity(frozen, campaign, label="Frozen Decision")
    if frozen.get("thesis_id") != proposal.thesis_id or frozen.get("thesis_revision") != proposal.thesis_revision:
        raise FrozenDecisionIntegrityError("Frozen Decision Thesis identity mismatch")
    refs = frozen.get("source_refs")
    marker = f"{PROPOSAL_SOURCE_PREFIX}{fingerprint}"
    if not isinstance(refs, list) or marker not in refs:
        raise FrozenDecisionIntegrityError("Frozen Decision proposal provenance is missing")


def commit_decision_proposal(
    campaign_id: str,
    payload: Mapping[str, Any],
    *,
    ports: RuntimePorts = PRODUCTION_PORTS,
) -> dict[str, Any]:
    """Revalidate and explicitly commit one proposal through the existing service."""

    campaign_key = _require_campaign_id(campaign_id)
    if not isinstance(payload, Mapping):
        raise DecisionCommitInputError("commit payload must be a JSON object")
    allowed = {
        "as_of",
        "expected_proposal_fingerprint",
        "user_confirmed",
        "asset_view",
        "trade_view",
        "portfolio_view",
        "review_by",
        "key_assumptions",
        "event_invalidation_conditions",
        "strategy_horizon",
    }
    extra = set(payload) - allowed
    if extra:
        raise DecisionCommitInputError(f"unknown commit field: {sorted(extra)}")
    if payload.get("user_confirmed") is not True:
        raise CommitConfirmationRequiredError("explicit user confirmation is required")
    expected = _require_fingerprint(payload.get("expected_proposal_fingerprint"))
    as_of = payload.get("as_of")
    if not isinstance(as_of, str) or as_of != _canonical_utc(as_of, "as_of"):
        raise DecisionCommitInputError("commit as_of must be the exact canonical preview instant")
    drafts = _validate_draft_inputs(
        {key: payload.get(key) for key in (
            "asset_view",
            "trade_view",
            "portfolio_view",
            "review_by",
            "key_assumptions",
            "event_invalidation_conditions",
            "strategy_horizon",
        )}
    )

    with _COMMIT_LOCK:
        campaign = _read_campaign(ports, campaign_key)
        raw_thesis = _read_thesis_once(ports, campaign_key)
        frozen = _read_frozen(ports, campaign)
        evidence_cache: tuple[evidence_delta.NormalizedEvidenceItem, ...] | None = None

        def snapshot_evidence_reader(
            scope: Mapping[str, Any],
        ) -> tuple[evidence_delta.NormalizedEvidenceItem, ...]:
            nonlocal evidence_cache
            if evidence_cache is None:
                evidence_cache = tuple(ports.evidence_reader(scope))
            return evidence_cache

        result, authorities = _build_proposal(
            campaign=campaign,
            as_of=as_of,
            raw_thesis=raw_thesis,
            frozen=frozen,
            drafts=drafts,
            ports=ports,
            evidence_reader=snapshot_evidence_reader,
        )
        fingerprint = _fingerprint(proposal=result, drafts=drafts)
        marker = f"{PROPOSAL_SOURCE_PREFIX}{fingerprint}"
        expected_marker = f"{PROPOSAL_SOURCE_PREFIX}{expected}"
        existing_index: int | None = None
        existing: Mapping[str, Any] | None = None
        for index, item in enumerate(frozen):
            if (
                isinstance(item.get("source_refs"), list)
                and expected_marker in item["source_refs"]
            ):
                if existing is not None:
                    raise FrozenDecisionIntegrityError(
                        "Frozen Decision proposal provenance is duplicated"
                    )
                existing_index = index
                existing = item
        if fingerprint != expected and existing is None:
            raise ProposalStaleError("proposal fingerprint mismatch; re-preview required")
        if existing is not None:
            # A replay may observe the newly written Frozen Decision at the
            # exact supplied as_of.  Recompute the original proposal with that
            # one record excluded, so the marker is an idempotency key only
            # when Campaign, Thesis, evidence, drafts, and the exact as_of all
            # still reproduce the original server-owned fingerprint.
            assert existing_index is not None  # established with existing
            replay_frozen = [
                *frozen[:existing_index],
                *frozen[existing_index + 1 :],
            ]
            replay_result, _replay_authorities = _build_proposal(
                campaign=campaign,
                as_of=as_of,
                raw_thesis=raw_thesis,
                frozen=replay_frozen,
                drafts=drafts,
                ports=ports,
                evidence_reader=snapshot_evidence_reader,
            )
            if _fingerprint(proposal=replay_result, drafts=drafts) != expected:
                raise ProposalStaleError(
                    "proposal authority graph changed; re-preview required"
                )
            if (
                existing.get("thesis_id") != result.thesis_id
                or existing.get("thesis_revision") != result.thesis_revision
            ):
                raise ProposalStaleError("proposal Thesis identity changed; re-preview required")
            fingerprint = expected
            marker = expected_marker
        idempotent = existing is not None
        if existing is None:
            frozen_payload = _freeze_payload(result, authorities, drafts, fingerprint)
            stored = ports.freeze_writer(frozen_payload)
        else:
            stored = existing

        decision_id = stored.get("decision_id") if isinstance(stored, Mapping) else None
        if not isinstance(decision_id, str) or not _DECISION_RE.fullmatch(decision_id):
            raise FrozenDecisionIntegrityError("Frozen Decision commit did not return a valid id")
        reread = ports.decision_reader(decision_id)
        if not isinstance(reread, Mapping):
            raise FrozenDecisionIntegrityError("Frozen Decision read-back is missing")
        _validate_committed_readback(reread, result, campaign, fingerprint)
        formal_decision = _formal_decision_evaluation(
            reread,
            campaign,
            authorities.current_thesis_authority,
            authorities.formal_thesis_evaluation,
            as_of,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "proposal_fingerprint": fingerprint,
            "idempotent": idempotent,
            "committed": copy.deepcopy(dict(reread)),
            "formal_decision": formal_decision,
            "decision_assurance": copy.deepcopy(dict(authorities.decision_assurance)),
            "re_read_required": True,
        }


def get_committed_decision(
    campaign_id: str,
    decision_id: str,
    *,
    ports: RuntimePorts = PRODUCTION_PORTS,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Read a committed decision again, then evaluate Formal Decision for now."""

    campaign_key = _require_campaign_id(campaign_id)
    if not isinstance(decision_id, str) or not _DECISION_RE.fullmatch(decision_id):
        raise DecisionCommitInputError("decision_id is invalid")
    snapshot_as_of = utc_now_iso() if as_of is None else as_of
    if snapshot_as_of != _canonical_utc(snapshot_as_of, "as_of"):
        raise DecisionCommitInputError("as_of must be canonical UTC")
    campaign = _read_campaign(ports, campaign_key)
    reread = ports.decision_reader(decision_id)
    if not isinstance(reread, Mapping):
        raise FrozenDecisionIntegrityError("Frozen Decision does not exist")
    _assert_identity(reread, campaign, label="Frozen Decision")
    raw_thesis = _read_thesis_once(ports, campaign_key)
    frozen = _read_frozen(ports, campaign)
    authorities = evaluate_authorities(
        campaign=campaign,
        as_of=snapshot_as_of,
        current_thesis_projection=raw_thesis,
        frozen_decisions=frozen,
        evidence_reader=ports.evidence_reader,
    )
    if authorities.latest_frozen_raw is None or authorities.latest_frozen_raw.get("decision_id") != decision_id:
        # A record that is real but not the current applicable boundary is not
        # silently treated as Formal Decision authority for this response.
        formal_decision = {
            "evaluation": "NOT_EVALUATED",
            "reason_codes": ["DECISION_NOT_LATEST_APPLICABLE"],
            "decision_id": decision_id,
            "authority_refs": ["frozen_decision_service", "frozen_decision_store"],
        }
    else:
        formal_decision = authorities.formal_decision
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": snapshot_as_of,
        "committed": copy.deepcopy(dict(reread)),
        "formal_thesis": {
            "evaluation": authorities.formal_thesis_evaluation,
            "reason_codes": list(authorities.formal_thesis_reason_codes),
        },
        "formal_decision": copy.deepcopy(dict(formal_decision)),
        "hard_risk": authorities.hard_risk.to_dict(),
        "material_change": (
            authorities.material_change.to_dict()
            if authorities.material_change is not None
            else {
                "state": "NOT_EVALUATED",
                "evaluation": "NOT_EVALUATED",
                "reason_codes": [NO_PRIOR_DECISION_BOUNDARY],
            }
        ),
        "sell_engine": authorities.sell_engine.to_dict(),
        "decision_assurance": copy.deepcopy(dict(authorities.decision_assurance)),
    }


__all__ = [
    "AuthorityEvaluations",
    "BEHAVIOR_MODEL_VERSION",
    "CommitConfirmationRequiredError",
    "CurrentThesisUnavailableError",
    "DecisionCommitInputError",
    "DecisionCommitRuntimeError",
    "FrozenDecisionIntegrityError",
    "NO_PRIOR_DECISION_BOUNDARY",
    "OPPORTUNITY_POLICY_VERSION",
    "PROPOSAL_SOURCE_PREFIX",
    "ProposalStaleError",
    "PRODUCTION_PORTS",
    "RISK_POLICY_VERSION",
    "RuntimePorts",
    "SCHEMA_VERSION",
    "DECISION_POLICY_VERSION",
    "evaluate_authorities",
    "commit_decision_proposal",
    "get_committed_decision",
    "preview_decision_proposal",
    "utc_now_iso",
]
