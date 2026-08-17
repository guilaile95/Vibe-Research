"""P0-DCH1 runtime: finalize / read / commit-bind a Challenge packet.

Reuses the existing Decision Proposal authority path.  Does not create a
second Proposal fingerprint or alter NBA / envelope / HR / Material / CCD.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import decision_challenge_projection as domain
import decision_challenge_store as store
import decision_commit_runtime as commit_runtime


class DecisionChallengeRuntimeError(RuntimeError):
    """Challenge runtime base error."""


class DecisionChallengeInputError(DecisionChallengeRuntimeError, ValueError):
    """Malformed finalize / bind input."""


class DecisionChallengeStaleError(DecisionChallengeRuntimeError):
    """Proposal fingerprint or Thesis identity no longer matches."""


class DecisionChallengeNotFoundError(DecisionChallengeRuntimeError, LookupError):
    """Challenge packet does not exist."""


class DecisionChallengeBindError(DecisionChallengeRuntimeError, ValueError):
    """Challenge cannot be bound to this commit."""


class DecisionChallengeConfirmationRequiredError(DecisionChallengeRuntimeError):
    """Explicit user confirmation is required before finalize."""


class DecisionChallengeReplayConflictError(DecisionChallengeRuntimeError):
    """A different packet already exists for this proposal fingerprint."""


@dataclass(frozen=True)
class ChallengePorts:
    preview: Callable[..., Mapping[str, Any]] = commit_runtime.preview_decision_proposal
    append: Callable[..., Mapping[str, Any]] = store.append_challenge
    reader: Callable[..., Mapping[str, Any] | None] = store.get_challenge
    fingerprint_reader: Callable[..., Mapping[str, Any] | None] = (
        store.get_challenge_by_fingerprint
    )
    clock: Callable[[], str] = commit_runtime.utc_now_iso
    new_id: Callable[[], str] = lambda: f"decision_challenge_{uuid.uuid4().hex}"


PRODUCTION_PORTS = ChallengePorts()


def _require_confirmed(payload: Mapping[str, Any]) -> None:
    if payload.get("user_confirmed") is not True:
        raise DecisionChallengeConfirmationRequiredError(
            "explicit user confirmation is required"
        )


def _draft_from_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    proposal = preview.get("proposal")
    fields = preview.get("commit_fields")
    if not isinstance(proposal, Mapping) or not isinstance(fields, Mapping):
        raise DecisionChallengeRuntimeError("proposal preview is incomplete")
    return {
        "asset_view": copy.deepcopy(proposal.get("asset_view")),
        "trade_view": copy.deepcopy(proposal.get("trade_view")),
        "portfolio_view": copy.deepcopy(proposal.get("portfolio_view")),
        "review_by": fields.get("review_by"),
        "key_assumptions": copy.deepcopy(fields.get("key_assumptions")),
        "event_invalidation_conditions": copy.deepcopy(
            fields.get("event_invalidation_conditions")
        ),
        "strategy_horizon": fields.get("strategy_horizon"),
    }


def _preview_identity(preview: Mapping[str, Any]) -> dict[str, Any]:
    proposal = preview.get("proposal")
    if not isinstance(proposal, Mapping):
        raise DecisionChallengeRuntimeError("proposal preview is missing")
    fingerprint = preview.get("proposal_fingerprint")
    return {
        "security_code": proposal.get("security_code"),
        "strategy": proposal.get("strategy"),
        "campaign_id": proposal.get("campaign_id"),
        "thesis_id": proposal.get("thesis_id"),
        "thesis_revision": proposal.get("thesis_revision"),
        "proposal_fingerprint": fingerprint,
        "proposal_as_of": proposal.get("as_of"),
        "next_best_action": proposal.get("next_best_action"),
        "action_envelope": copy.deepcopy(proposal.get("action_envelope")),
        "authority_evaluations": copy.deepcopy(preview.get("authority_evaluations")),
    }


def finalize_decision_challenge(
    campaign_id: str,
    payload: Mapping[str, Any],
    *,
    ports: ChallengePorts = PRODUCTION_PORTS,
    preview_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Revalidate the exact preview, then persist one immutable packet."""

    if not isinstance(payload, Mapping):
        raise DecisionChallengeInputError("finalize payload must be a JSON object")
    allowed = {
        "expected_proposal_fingerprint",
        "as_of",
        "user_confirmed",
        "dimensions",
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
        raise DecisionChallengeInputError(f"unknown finalize field: {sorted(extra)}")
    domain_forbidden = set(payload) & {
        "evaluation",
        "authority_refs",
        "artifact_refs",
        "security_code",
        "strategy",
        "thesis_id",
        "thesis_revision",
        "challenge_id",
        "first_pass_ref",
        "first_pass_at",
        "second_pass_ref",
        "second_pass_at",
        "decision_quality",
        "packet_state",
        "challenge_evaluation",
    }
    if domain_forbidden:
        raise DecisionChallengeInputError(
            "caller must not submit evaluation, authority, or identity fields"
        )
    _require_confirmed(payload)
    try:
        expected = domain.require_fingerprint(
            payload.get("expected_proposal_fingerprint"),
            "expected_proposal_fingerprint",
        )
        as_of, _ = domain.parse_utc_instant(payload.get("as_of"), "as_of")
        user_dimensions = domain.normalize_user_dimensions(payload.get("dimensions"))
    except domain.DecisionChallengeValidationError as exc:
        raise DecisionChallengeInputError(str(exc)) from exc

    draft_keys = (
        "asset_view",
        "trade_view",
        "portfolio_view",
        "review_by",
        "key_assumptions",
        "event_invalidation_conditions",
        "strategy_horizon",
    )
    if preview_override is None and not all(key in payload for key in draft_keys):
        raise DecisionChallengeInputError(
            "finalize requires the same user draft used for preview"
        )
    try:
        preview = preview_override or ports.preview(
            campaign_id,
            {key: payload[key] for key in draft_keys},
            as_of=as_of,
        )
    except commit_runtime.ProposalStaleError as exc:
        raise DecisionChallengeStaleError("proposal fingerprint mismatch") from exc
    except commit_runtime.CurrentThesisUnavailableError as exc:
        raise DecisionChallengeStaleError("Current Thesis is not applicable") from exc
    except commit_runtime.DecisionCommitInputError as exc:
        raise DecisionChallengeInputError(str(exc)) from exc
    except commit_runtime.DecisionCommitRuntimeError as exc:
        raise DecisionChallengeRuntimeError("proposal authority is unavailable") from exc

    identity = _preview_identity(preview)
    if identity["campaign_id"] != campaign_id:
        raise DecisionChallengeRuntimeError("preview Campaign identity mismatch")
    if identity["proposal_fingerprint"] != expected:
        raise DecisionChallengeStaleError("proposal fingerprint mismatch; re-preview required")
    if identity["proposal_as_of"] != as_of:
        raise DecisionChallengeStaleError("proposal as_of mismatch; re-preview required")

    existing = ports.fingerprint_reader(expected)
    finalized_at = (
        existing["finalized_at"]
        if isinstance(existing, Mapping)
        else ports.clock()
    )
    challenge_id = (
        existing["challenge_id"]
        if isinstance(existing, Mapping)
        else ports.new_id()
    )
    try:
        packet = domain.project_challenge_packet(
            challenge_id=challenge_id,
            security_code=identity["security_code"],
            strategy=identity["strategy"],
            campaign_id=identity["campaign_id"],
            thesis_id=identity["thesis_id"],
            thesis_revision=identity["thesis_revision"],
            proposal_fingerprint=identity["proposal_fingerprint"],
            proposal_as_of=identity["proposal_as_of"],
            finalized_at=finalized_at,
            user_dimensions=user_dimensions,
        )
    except domain.DecisionChallengeValidationError as exc:
        raise DecisionChallengeInputError(str(exc)) from exc

    try:
        stored = ports.append(packet)
    except store.DecisionChallengeConflictError as exc:
        raise DecisionChallengeReplayConflictError(str(exc)) from exc
    return {
        "schema_version": domain.SCHEMA_VERSION,
        "challenge": copy.deepcopy(dict(stored)),
        "proposal_fingerprint": identity["proposal_fingerprint"],
        "proposal_as_of": identity["proposal_as_of"],
        "next_best_action": identity["next_best_action"],
        "action_envelope": identity["action_envelope"],
        "authority_evaluations": identity["authority_evaluations"],
        "decision_quality": domain.DECISION_QUALITY,
        "re_read_required": True,
    }


def get_decision_challenge(
    challenge_id: str,
    *,
    ports: ChallengePorts = PRODUCTION_PORTS,
) -> dict[str, Any]:
    try:
        cid = domain.require_challenge_id(challenge_id)
    except domain.DecisionChallengeValidationError as exc:
        raise DecisionChallengeInputError(str(exc)) from exc
    packet = ports.reader(cid)
    if packet is None:
        raise DecisionChallengeNotFoundError("Decision Challenge does not exist")
    return {
        "schema_version": domain.SCHEMA_VERSION,
        "challenge": copy.deepcopy(dict(packet)),
        "decision_quality": domain.DECISION_QUALITY,
    }


def get_decision_challenge_for_proposal(
    campaign_id: str,
    proposal_fingerprint: str,
    *,
    ports: ChallengePorts = PRODUCTION_PORTS,
) -> dict[str, Any]:
    try:
        campaign = commit_runtime._require_campaign_id(campaign_id)
        fingerprint = domain.require_fingerprint(proposal_fingerprint)
    except (domain.DecisionChallengeValidationError, commit_runtime.DecisionCommitInputError) as exc:
        raise DecisionChallengeInputError(str(exc)) from exc
    packet = ports.fingerprint_reader(fingerprint)
    if packet is None:
        raise DecisionChallengeNotFoundError("Decision Challenge does not exist")
    if packet.get("campaign_id") != campaign:
        raise DecisionChallengeNotFoundError("Decision Challenge does not exist")
    return {
        "schema_version": domain.SCHEMA_VERSION,
        "challenge": copy.deepcopy(dict(packet)),
        "decision_quality": domain.DECISION_QUALITY,
    }


def verify_challenge_for_commit(
    *,
    challenge_id: object,
    campaign: Mapping[str, Any],
    proposal: Mapping[str, Any],
    fingerprint: str,
    as_of: str,
    ports: ChallengePorts | None = None,
) -> dict[str, Any]:
    """Load and bind-check a packet before any Frozen Decision write."""

    active_ports = ports or PRODUCTION_PORTS
    try:
        cid = domain.require_challenge_id(challenge_id)
    except domain.DecisionChallengeValidationError as exc:
        raise DecisionChallengeBindError(str(exc)) from exc
    try:
        packet = active_ports.reader(cid)
    except store.DecisionChallengeStoreCorruptedError as exc:
        raise DecisionChallengeBindError("challenge packet is corrupt") from exc
    if packet is None:
        raise DecisionChallengeBindError("challenge packet does not exist")
    try:
        validated = domain.challenge_packet_from_mapping(packet)
    except domain.DecisionChallengeValidationError as exc:
        raise DecisionChallengeBindError("challenge packet failed validation") from exc
    if validated["campaign_id"] != campaign.get("campaign_id"):
        raise DecisionChallengeBindError("challenge Campaign identity mismatch")
    if validated["security_code"] != campaign.get("security_code"):
        raise DecisionChallengeBindError("challenge security_code mismatch")
    if validated["strategy"] != campaign.get("strategy"):
        raise DecisionChallengeBindError("challenge strategy mismatch")
    if validated["thesis_id"] != proposal.get("thesis_id"):
        raise DecisionChallengeBindError("challenge Thesis identity mismatch")
    if validated["thesis_revision"] != proposal.get("thesis_revision"):
        raise DecisionChallengeBindError("challenge Thesis revision mismatch")
    if validated["proposal_fingerprint"] != fingerprint:
        raise DecisionChallengeBindError("challenge proposal fingerprint mismatch")
    if validated["proposal_as_of"] != as_of:
        raise DecisionChallengeBindError("challenge proposal as_of mismatch")
    if validated["packet_state"] != "COMPLETE":
        raise DecisionChallengeBindError("challenge packet is not finalized")
    if validated["two_pass_state"] != "VALID":
        raise DecisionChallengeBindError("challenge two-pass structure is incomplete")
    first_at = datetime.fromisoformat(validated["first_pass_at"].replace("Z", "+00:00"))
    second_at = datetime.fromisoformat(validated["second_pass_at"].replace("Z", "+00:00"))
    if second_at < first_at:
        raise DecisionChallengeBindError("challenge two-pass ordering is invalid")
    if validated["decision_quality"] != domain.DECISION_QUALITY:
        raise DecisionChallengeBindError("challenge must not carry a quality grade")
    return validated


__all__ = [
    "ChallengePorts",
    "DecisionChallengeBindError",
    "DecisionChallengeConfirmationRequiredError",
    "DecisionChallengeInputError",
    "DecisionChallengeNotFoundError",
    "DecisionChallengeReplayConflictError",
    "DecisionChallengeRuntimeError",
    "DecisionChallengeStaleError",
    "PRODUCTION_PORTS",
    "finalize_decision_challenge",
    "get_decision_challenge",
    "get_decision_challenge_for_proposal",
    "verify_challenge_for_commit",
]
