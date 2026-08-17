"""P0-DCH1 Decision Challenge packet domain (pure, zero I/O).

Absorbs the safe vocabulary and coverage reducer from Draft PR #114 and
hardens it: callers submit only explicit user review status/text.  Dimension
evaluation, packet state, coverage, two-pass refs/times, and authority refs
are server-derived.

    CHALLENGE COVERAGE != DECISION CORRECTNESS != DECISION APPROVAL
    PROFIT/LOSS != CHALLENGE QUALITY
    TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED = NO
    DECISION_QUALITY = NOT_EVALUATED
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Mapping

SCHEMA_VERSION = "decision_challenge.packet.v0.1"
POLICY_VERSION = "dch.decision_challenge.v0.1"
AUTHORITY_REF = "dch:decision_challenge_projection:v0.1"

REQUIRED_DIMENSIONS: tuple[str, ...] = (
    "STRONGEST_SUPPORTING_EVIDENCE",
    "STRONGEST_OPPOSING_EVIDENCE",
    "PRE_MORTEM",
    "INVALIDATION_FACTS",
)

USER_STATUSES: tuple[str, ...] = ("ANSWERED", "UNKNOWN")
DIMENSION_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
PACKET_STATES: tuple[str, ...] = ("COMPLETE", "INCOMPLETE")
CHALLENGE_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
TWO_PASS_STATES: tuple[str, ...] = ("VALID", "INCOMPLETE")
DECISION_QUALITY = "NOT_EVALUATED"
TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED = "NO"

PROPOSAL_SOURCE_PREFIX = "decision_proposal:"
CHALLENGE_SOURCE_PREFIX = "decision_challenge:"

_COVERED_EVALUATIONS = frozenset({"EVALUATED", "UNKNOWN"})
_USER_DIMENSION_KEYS = frozenset({"status", "text"})
_CALLER_FORBIDDEN_KEYS = frozenset(
    {
        "evaluation",
        "authority_refs",
        "artifact_refs",
        "challenge_packet_state",
        "challenge_coverage_state",
        "challenge_evaluation",
        "packet_state",
        "security_code",
        "strategy",
        "campaign_id",
        "thesis_id",
        "thesis_revision",
        "decision_id",
        "first_pass_ref",
        "first_pass_at",
        "second_pass_ref",
        "second_pass_at",
        "challenge_id",
        "decision_quality",
        "process_quality",
        "packet_hash",
        "finalized_at",
    }
)

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_THESIS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_CHALLENGE_ID_RE = re.compile(r"^decision_challenge_[0-9a-f]{32}$")
_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

_PACKET_KEYS = (
    "schema_version",
    "policy_version",
    "authority_ref",
    "challenge_id",
    "security_code",
    "strategy",
    "campaign_id",
    "thesis_id",
    "thesis_revision",
    "proposal_fingerprint",
    "proposal_as_of",
    "finalized_at",
    "packet_state",
    "challenge_evaluation",
    "challenge_coverage_state",
    "decision_quality",
    "two_pass_semantic_independence_verified",
    "dimension_results",
    "covered_dimensions",
    "unknown_dimensions",
    "incomplete_dimensions",
    "two_pass_state",
    "first_pass_ref",
    "first_pass_at",
    "second_pass_ref",
    "second_pass_at",
    "reason_codes",
    "authority_refs",
    "packet_hash",
    "explainability",
)


class DecisionChallengeError(Exception):
    """Decision Challenge domain base error."""


class DecisionChallengeValidationError(DecisionChallengeError, ValueError):
    """Illegal caller input or contract violation — fail closed."""


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionChallengeValidationError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise DecisionChallengeValidationError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def require_challenge_id(value: object) -> str:
    challenge_id = _require_nonempty_str(value, "challenge_id")
    if _CHALLENGE_ID_RE.fullmatch(challenge_id) is None:
        raise DecisionChallengeValidationError(
            "challenge_id must match decision_challenge_<32 lowercase hex>"
        )
    return challenge_id


def require_fingerprint(value: object, field: str = "proposal_fingerprint") -> str:
    fingerprint = _require_nonempty_str(value, field)
    if _FINGERPRINT_RE.fullmatch(fingerprint) is None:
        raise DecisionChallengeValidationError(f"{field} is invalid")
    return fingerprint


def parse_utc_instant(value: object, field: str) -> tuple[str, datetime]:
    raw = _require_nonempty_str(value, field)
    if _UTC_RE.fullmatch(raw) is None:
        raise DecisionChallengeValidationError(
            f"{field} must be a UTC zero-offset instant"
        )
    try:
        parsed = datetime.fromisoformat(
            raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        )
    except ValueError as exc:
        raise DecisionChallengeValidationError(
            f"{field} is not a parsable UTC instant"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DecisionChallengeValidationError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset().total_seconds() != 0:
        raise DecisionChallengeValidationError(f"{field} must use UTC zero offset")
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return canonical, parsed.astimezone(parsed.tzinfo)


def _require_identity(
    *,
    security_code: object,
    strategy: object,
    campaign_id: object,
    thesis_id: object,
    thesis_revision: object,
) -> dict[str, Any]:
    code = _require_nonempty_str(security_code, "security_code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise DecisionChallengeValidationError(
            "security_code must be a 6-digit A-share code"
        )
    strat = _require_nonempty_str(strategy, "strategy")
    if strat not in {"SHORT", "SWING", "MEDIUM"}:
        raise DecisionChallengeValidationError("strategy is invalid")
    campaign = _require_nonempty_str(campaign_id, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(campaign) is None:
        raise DecisionChallengeValidationError("campaign_id is invalid")
    thesis = _require_nonempty_str(thesis_id, "thesis_id")
    if _THESIS_ID_RE.fullmatch(thesis) is None:
        raise DecisionChallengeValidationError("thesis_id is invalid")
    if isinstance(thesis_revision, bool) or not isinstance(thesis_revision, int):
        raise DecisionChallengeValidationError("thesis_revision must be a positive int")
    if thesis_revision <= 0:
        raise DecisionChallengeValidationError("thesis_revision must be a positive int")
    return {
        "security_code": code,
        "strategy": strat,
        "campaign_id": campaign,
        "thesis_id": thesis,
        "thesis_revision": thesis_revision,
    }


def _reject_caller_declared(mapping: Mapping[str, Any], *, where: str) -> None:
    forbidden = sorted(set(mapping) & _CALLER_FORBIDDEN_KEYS)
    extra_eval = [
        key
        for key in mapping
        if key.endswith("_evaluation") or key.endswith("_authority_refs")
    ]
    if forbidden or extra_eval:
        raise DecisionChallengeValidationError(
            f"{where} must not declare evaluation or authority fields"
        )


def normalize_user_dimensions(raw: object) -> dict[str, dict[str, str]]:
    """Accept only explicit user status/text for the four required dimensions."""

    if not isinstance(raw, Mapping):
        raise DecisionChallengeValidationError("dimensions must be a JSON object")
    extra = set(raw) - set(REQUIRED_DIMENSIONS)
    if extra:
        raise DecisionChallengeValidationError(
            f"unknown challenge dimension: {sorted(extra)}"
        )
    missing = [name for name in REQUIRED_DIMENSIONS if name not in raw]
    if missing:
        raise DecisionChallengeValidationError(
            f"challenge is missing dimensions: {missing}"
        )
    normalized: dict[str, dict[str, str]] = {}
    for name in REQUIRED_DIMENSIONS:
        row = raw[name]
        if not isinstance(row, Mapping):
            raise DecisionChallengeValidationError(
                f"{name} must be a JSON object of status/text"
            )
        _reject_caller_declared(row, where=name)
        unknown_keys = set(row) - _USER_DIMENSION_KEYS
        if unknown_keys:
            raise DecisionChallengeValidationError(
                f"{name} has unknown fields: {sorted(unknown_keys)}"
            )
        status = row.get("status")
        if status not in USER_STATUSES:
            raise DecisionChallengeValidationError(
                f"{name}.status must be ANSWERED or UNKNOWN"
            )
        text_raw = row.get("text", "")
        if text_raw is None:
            text_raw = ""
        if not isinstance(text_raw, str):
            raise DecisionChallengeValidationError(f"{name}.text must be a string")
        text = text_raw.strip()
        if status == "ANSWERED" and not text:
            raise DecisionChallengeValidationError(
                f"{name} ANSWERED requires non-empty text"
            )
        normalized[name] = {"status": status, "text": text}
    return normalized


def _evaluation_for_status(status: str) -> str:
    if status == "ANSWERED":
        return "EVALUATED"
    if status == "UNKNOWN":
        return "UNKNOWN"
    return "NOT_EVALUATED"


def derive_dimension_results(
    *,
    challenge_id: str,
    user_dimensions: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_DIMENSIONS:
        row = user_dimensions[name]
        evaluation = _evaluation_for_status(row["status"])
        results[name] = {
            "dimension": name,
            "status": row["status"],
            "text": row["text"],
            "evaluation": evaluation,
            "authority_refs": [f"{CHALLENGE_SOURCE_PREFIX}{challenge_id}:{name}"],
            "positive_evidence": evaluation == "EVALUATED",
        }
    return results


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def reduce_coverage(
    dimension_results: Mapping[str, Mapping[str, Any]],
    *,
    two_pass_state: str,
) -> dict[str, Any]:
    """#114 coverage reducer, restricted to server-derived evaluations."""

    covered: list[str] = []
    unknown: list[str] = []
    incomplete: list[str] = []
    errors: list[str] = []
    reasons: list[str] = []
    for name in REQUIRED_DIMENSIONS:
        evaluation = dimension_results[name]["evaluation"]
        if evaluation == "EVALUATED":
            covered.append(name)
        elif evaluation == "UNKNOWN":
            covered.append(name)
            unknown.append(name)
        elif evaluation == "NOT_EVALUATED":
            incomplete.append(name)
            reasons.append(f"{name}_NOT_EVALUATED")
        else:
            errors.append(name)
            reasons.append(f"{name}_ERROR")

    if errors:
        packet_state = "INCOMPLETE"
        evaluation = "ERROR"
    elif incomplete or two_pass_state != "VALID":
        packet_state = "INCOMPLETE"
        evaluation = "NOT_EVALUATED"
        if two_pass_state != "VALID":
            reasons.append("TWO_PASS_INCOMPLETE")
    elif unknown:
        packet_state = "COMPLETE"
        evaluation = "UNKNOWN"
        reasons.append("CHALLENGE_PACKET_COVERED_WITH_UNKNOWN")
    else:
        packet_state = "COMPLETE"
        evaluation = "EVALUATED"
        reasons.append("CHALLENGE_PACKET_COMPLETE")

    return {
        "packet_state": packet_state,
        "challenge_evaluation": evaluation,
        "challenge_coverage_state": packet_state,
        "covered_dimensions": covered,
        "unknown_dimensions": unknown,
        "incomplete_dimensions": incomplete + errors,
        "reason_codes": _unique(reasons),
    }


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def compute_packet_hash(packet: Mapping[str, Any]) -> str:
    payload = {key: copy.deepcopy(packet.get(key)) for key in _PACKET_KEYS if key != "packet_hash"}
    encoded = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_challenge_packet(
    *,
    challenge_id: object,
    security_code: object,
    strategy: object,
    campaign_id: object,
    thesis_id: object,
    thesis_revision: object,
    proposal_fingerprint: object,
    proposal_as_of: object,
    finalized_at: object,
    user_dimensions: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Build one immutable finalized packet from server-owned facts + user text."""

    cid = require_challenge_id(challenge_id)
    identity = _require_identity(
        security_code=security_code,
        strategy=strategy,
        campaign_id=campaign_id,
        thesis_id=thesis_id,
        thesis_revision=thesis_revision,
    )
    fingerprint = require_fingerprint(proposal_fingerprint)
    first_pass_at, first_dt = parse_utc_instant(proposal_as_of, "proposal_as_of")
    second_pass_at, second_dt = parse_utc_instant(finalized_at, "finalized_at")
    if second_dt < first_dt:
        raise DecisionChallengeValidationError(
            "second_pass_at must be greater than or equal to first_pass_at"
        )

    dimensions = normalize_user_dimensions(user_dimensions)
    dimension_results = derive_dimension_results(
        challenge_id=cid, user_dimensions=dimensions
    )
    first_pass_ref = f"{PROPOSAL_SOURCE_PREFIX}{fingerprint}"
    second_pass_ref = f"{CHALLENGE_SOURCE_PREFIX}{cid}"
    two_pass_state = "VALID"
    coverage = reduce_coverage(dimension_results, two_pass_state=two_pass_state)
    if coverage["packet_state"] != "COMPLETE":
        raise DecisionChallengeValidationError(
            "finalized challenge packet must be COMPLETE"
        )

    authority_refs = [
        AUTHORITY_REF,
        second_pass_ref,
        first_pass_ref,
    ]
    for name in REQUIRED_DIMENSIONS:
        authority_refs.extend(dimension_results[name]["authority_refs"])

    packet = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "authority_ref": AUTHORITY_REF,
        "challenge_id": cid,
        **identity,
        "proposal_fingerprint": fingerprint,
        "proposal_as_of": first_pass_at,
        "finalized_at": second_pass_at,
        "packet_state": coverage["packet_state"],
        "challenge_evaluation": coverage["challenge_evaluation"],
        "challenge_coverage_state": coverage["challenge_coverage_state"],
        "decision_quality": DECISION_QUALITY,
        "two_pass_semantic_independence_verified": TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED,
        "dimension_results": dimension_results,
        "covered_dimensions": coverage["covered_dimensions"],
        "unknown_dimensions": coverage["unknown_dimensions"],
        "incomplete_dimensions": coverage["incomplete_dimensions"],
        "two_pass_state": two_pass_state,
        "first_pass_ref": first_pass_ref,
        "first_pass_at": first_pass_at,
        "second_pass_ref": second_pass_ref,
        "second_pass_at": second_pass_at,
        "reason_codes": coverage["reason_codes"],
        "authority_refs": _unique(authority_refs),
        "explainability": {
            "why_this_state": (
                f"challenge_packet_state={coverage['packet_state']}; "
                f"challenge_evaluation={coverage['challenge_evaluation']}; "
                f"two_pass_state={two_pass_state}; "
                f"reasons={','.join(coverage['reason_codes'])}"
            ),
            "required_dimensions": list(REQUIRED_DIMENSIONS),
            "note": (
                "CHALLENGE_COVERAGE_NE_DECISION_CORRECTNESS; "
                "CHALLENGE_COVERAGE_NE_DECISION_APPROVAL; "
                "UNKNOWN_EQUALS_POSITIVE_EVIDENCE=NO; "
                "TWO_PASS_STRUCTURE_VERIFIED=YES; "
                "TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED=NO; "
                "DECISION_QUALITY=NOT_EVALUATED; "
                "CALLER_DECLARED_AUTHORITY=NO"
            ),
        },
    }
    packet["packet_hash"] = compute_packet_hash(packet)
    return copy.deepcopy(packet)


def semantic_replay_payload(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Identity + user responses + first pass — excludes server id/time/hash."""

    dimensions = {}
    results = packet.get("dimension_results")
    if not isinstance(results, Mapping):
        raise DecisionChallengeValidationError("dimension_results is invalid")
    for name in REQUIRED_DIMENSIONS:
        row = results.get(name)
        if not isinstance(row, Mapping):
            raise DecisionChallengeValidationError(f"{name} is missing from packet")
        dimensions[name] = {
            "status": row.get("status"),
            "text": row.get("text"),
        }
    return {
        "security_code": packet.get("security_code"),
        "strategy": packet.get("strategy"),
        "campaign_id": packet.get("campaign_id"),
        "thesis_id": packet.get("thesis_id"),
        "thesis_revision": packet.get("thesis_revision"),
        "proposal_fingerprint": packet.get("proposal_fingerprint"),
        "proposal_as_of": packet.get("proposal_as_of"),
        "first_pass_ref": packet.get("first_pass_ref"),
        "first_pass_at": packet.get("first_pass_at"),
        "dimensions": dimensions,
    }


def challenge_packet_from_mapping(value: object) -> dict[str, Any]:
    """Hydrate and re-validate one stored packet. Fail closed on drift."""

    if not isinstance(value, Mapping):
        raise DecisionChallengeValidationError("challenge packet must be a JSON object")
    extra = set(value) - set(_PACKET_KEYS)
    if extra:
        raise DecisionChallengeValidationError(
            f"challenge packet has unknown fields: {sorted(extra)}"
        )
    missing = [key for key in _PACKET_KEYS if key not in value]
    if missing:
        raise DecisionChallengeValidationError(
            f"challenge packet is missing fields: {missing}"
        )
    if value.get("schema_version") != SCHEMA_VERSION:
        raise DecisionChallengeValidationError("challenge packet schema_version mismatch")
    if value.get("decision_quality") != DECISION_QUALITY:
        raise DecisionChallengeValidationError("decision_quality must stay NOT_EVALUATED")
    if value.get("two_pass_semantic_independence_verified") != "NO":
        raise DecisionChallengeValidationError(
            "semantic independence must remain unverified"
        )
    user_dimensions = {}
    results = value.get("dimension_results")
    if not isinstance(results, Mapping):
        raise DecisionChallengeValidationError("dimension_results is invalid")
    for name in REQUIRED_DIMENSIONS:
        row = results.get(name)
        if not isinstance(row, Mapping):
            raise DecisionChallengeValidationError(f"{name} is missing")
        user_dimensions[name] = {
            "status": row.get("status"),
            "text": row.get("text", ""),
        }
    rebuilt = project_challenge_packet(
        challenge_id=value.get("challenge_id"),
        security_code=value.get("security_code"),
        strategy=value.get("strategy"),
        campaign_id=value.get("campaign_id"),
        thesis_id=value.get("thesis_id"),
        thesis_revision=value.get("thesis_revision"),
        proposal_fingerprint=value.get("proposal_fingerprint"),
        proposal_as_of=value.get("proposal_as_of"),
        finalized_at=value.get("finalized_at"),
        user_dimensions=user_dimensions,
    )
    stored_hash = value.get("packet_hash")
    if not isinstance(stored_hash, str) or not _HASH_RE.fullmatch(stored_hash):
        raise DecisionChallengeValidationError("packet_hash is invalid")
    if stored_hash != rebuilt["packet_hash"]:
        raise DecisionChallengeValidationError("packet_hash does not match packet")
    if stored_hash != compute_packet_hash(value):
        raise DecisionChallengeValidationError("stored packet_hash is inconsistent")
    return copy.deepcopy(rebuilt)


__all__ = [
    "AUTHORITY_REF",
    "CHALLENGE_EVALUATIONS",
    "CHALLENGE_SOURCE_PREFIX",
    "DECISION_QUALITY",
    "DIMENSION_EVALUATIONS",
    "DecisionChallengeError",
    "DecisionChallengeValidationError",
    "PACKET_STATES",
    "POLICY_VERSION",
    "PROPOSAL_SOURCE_PREFIX",
    "REQUIRED_DIMENSIONS",
    "SCHEMA_VERSION",
    "TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED",
    "TWO_PASS_STATES",
    "USER_STATUSES",
    "challenge_packet_from_mapping",
    "compute_packet_hash",
    "derive_dimension_results",
    "normalize_user_dimensions",
    "parse_utc_instant",
    "project_challenge_packet",
    "reduce_coverage",
    "require_challenge_id",
    "require_fingerprint",
    "semantic_replay_payload",
]
