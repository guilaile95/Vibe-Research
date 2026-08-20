"""Post-freeze Decision Process Review pure projection.

This module is a descriptive read model only.  It never scores a decision,
judges correctness, mutates a Frozen Decision, or reads a clock/storage.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

import decision_challenge_projection as challenge

SCHEMA_VERSION = "decision_process_review.v0.1"
STATES = ("BOUND", "NONE", "ERROR")
PROCESS_QUALITY_STATE = "NOT_EVALUATED"
PROCESS_QUALITY_REASON = "NO_PROCESS_QUALITY_AUTHORITY"


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def none_review() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "NONE",
        "challenge_id": None,
        "reason_codes": ["NO_PREFREEZE_CHALLENGE_BOUND"],
        "authority_refs": ["frozen_decision_store", "decision_process_review"],
    }


def error_review(reason: str = "PROCESS_REVIEW_UNAVAILABLE") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "ERROR",
        "challenge_id": None,
        "reason_codes": [reason],
        "authority_refs": ["frozen_decision_store", "decision_process_review"],
    }


def bound_review(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Project one already validated DCH1 packet without adding authority."""
    if not isinstance(packet, Mapping):
        raise ValueError("validated challenge packet must be a mapping")
    dimensions = packet.get("dimension_results")
    if not isinstance(dimensions, Mapping):
        raise ValueError("validated challenge dimensions are missing")
    projected: dict[str, dict[str, Any]] = {}
    for name in challenge.REQUIRED_DIMENSIONS:
        row = dimensions.get(name)
        if not isinstance(row, Mapping):
            raise ValueError(f"validated challenge dimension missing: {name}")
        projected[name] = {
            "status": row.get("status"),
            "text": row.get("text"),
        }
    refs = packet.get("authority_refs")
    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
        raise ValueError("validated challenge authority_refs are missing")
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "BOUND",
        "challenge_id": packet.get("challenge_id"),
        "finalized_at": packet.get("finalized_at"),
        "packet_state": packet.get("packet_state"),
        "challenge_evaluation": packet.get("challenge_evaluation"),
        "challenge_coverage_state": packet.get("challenge_coverage_state"),
        "dimensions": projected,
        "covered_dimensions": _copy(packet.get("covered_dimensions")),
        "unknown_dimensions": _copy(packet.get("unknown_dimensions")),
        "two_pass_state": packet.get("two_pass_state"),
        "two_pass_semantic_independence_verified": packet.get(
            "two_pass_semantic_independence_verified"
        ),
        "first_pass_ref": packet.get("first_pass_ref"),
        "first_pass_at": packet.get("first_pass_at"),
        "second_pass_ref": packet.get("second_pass_ref"),
        "second_pass_at": packet.get("second_pass_at"),
        "reason_codes": _copy(packet.get("reason_codes")),
        "authority_refs": _copy(refs),
        "process_quality": {
            "state": PROCESS_QUALITY_STATE,
            "reason_codes": [PROCESS_QUALITY_REASON],
        },
        "explainability": {
            "note": "CHALLENGE_COVERAGE_IS_NOT_DECISION_CORRECTNESS",
        },
    }


__all__ = [
    "PROCESS_QUALITY_REASON",
    "PROCESS_QUALITY_STATE",
    "SCHEMA_VERSION",
    "STATES",
    "bound_review",
    "error_review",
    "none_review",
]
