"""Pure dataset coverage semantics for Fact Lake publications.

The core accepts explicit sessions and observed business dates only.  It does
not read a calendar, a clock, storage, or a provider.  A dense dataset may
advance only through a contiguous session prefix; sparse datasets never infer a
daily gap from an absent observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Iterable, Mapping

from data_contracts import CoverageMode

SCHEMA_VERSION = "fact_lake_coverage.v0.1"


class CoverageValidationError(ValueError):
    """Raised when explicit coverage evidence violates its input contract."""


class CoverageState(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


REASON_COVERAGE_INTERIOR_GAP = "COVERAGE_INTERIOR_GAP"
REASON_COVERAGE_EXPECTED_NOT_REACHED = "COVERAGE_EXPECTED_NOT_REACHED"
REASON_COVERAGE_UNKNOWN = "COVERAGE_UNKNOWN"


def _date(value: Any, field: str) -> str:
    if type(value) is not str:
        raise CoverageValidationError(f"{field} must be an ISO calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CoverageValidationError(
            f"{field} must be an ISO calendar date") from exc
    if parsed.isoformat() != value:
        raise CoverageValidationError(f"{field} must be canonical")
    return value


def _ordered_sessions(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise CoverageValidationError("sessions must be an iterable of dates")
    try:
        sessions = tuple(_date(value, "session") for value in values)
    except TypeError as exc:
        raise CoverageValidationError("sessions must be an iterable of dates") from exc
    if not sessions:
        raise CoverageValidationError("sessions must not be empty")
    if any(left >= right for left, right in zip(sessions, sessions[1:])):
        raise CoverageValidationError("sessions must be strictly ascending")
    return sessions


def _observed_dates(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise CoverageValidationError("observed_dates must be an iterable of dates")
    try:
        result = frozenset(_date(value, "observed_date") for value in values)
    except TypeError as exc:
        raise CoverageValidationError(
            "observed_dates must be an iterable of dates") from exc
    return result


@dataclass(frozen=True)
class CoverageAssessment:
    dataset_id: str
    coverage_mode: CoverageMode
    safe_watermark: str | None
    state: CoverageState
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.dataset_id) is not str or not self.dataset_id.strip():
            raise CoverageValidationError("dataset_id must be a non-empty string")
        if not isinstance(self.coverage_mode, CoverageMode):
            raise CoverageValidationError("coverage_mode must be CoverageMode")
        if self.safe_watermark is not None:
            _date(self.safe_watermark, "safe_watermark")
        if not isinstance(self.state, CoverageState):
            raise CoverageValidationError("state must be CoverageState")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code.strip() for code in self.reason_codes
        ):
            raise CoverageValidationError("reason_codes must be a tuple of non-empty strings")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise CoverageValidationError("reason_codes must not contain duplicates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": self.dataset_id,
            "coverage_mode": self.coverage_mode.value,
            "safe_watermark": self.safe_watermark,
            "state": self.state.value,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageAssessment":
        if not isinstance(data, Mapping):
            raise CoverageValidationError("assessment must be a mapping")
        expected = {
            "schema_version", "dataset_id", "coverage_mode", "safe_watermark",
            "state", "reason_codes",
        }
        if set(data) != expected:
            raise CoverageValidationError("assessment fields do not match schema")
        if data["schema_version"] != SCHEMA_VERSION:
            raise CoverageValidationError("unsupported coverage schema version")
        reasons = data["reason_codes"]
        if type(reasons) is not list or any(type(code) is not str for code in reasons):
            raise CoverageValidationError("reason_codes must be a string list")
        return cls(
            dataset_id=data["dataset_id"],
            coverage_mode=CoverageMode(data["coverage_mode"]),
            safe_watermark=data["safe_watermark"],
            state=CoverageState(data["state"]),
            reason_codes=tuple(reasons),
        )


def assess_coverage(
    *,
    dataset_id: str,
    coverage_mode: CoverageMode,
    sessions: Iterable[str],
    observed_dates: Iterable[str],
    expected_through: str | None = None,
) -> CoverageAssessment:
    """Assess explicit coverage without inferring provider or runtime state.

    ``sessions`` is the bounded session sequence supplied by the caller.  For
    ``SESSION_DENSE`` the watermark is the last date in the initial contiguous
    observed prefix.  For ``SPARSE`` no missing daily record is a gap; without
    an explicit boundary the result is ``NOT_APPLICABLE``.
    """
    if type(dataset_id) is not str or not dataset_id.strip():
        raise CoverageValidationError("dataset_id must be a non-empty string")
    if not isinstance(coverage_mode, CoverageMode):
        raise CoverageValidationError("coverage_mode must be CoverageMode")
    ordered = _ordered_sessions(sessions)
    observed = _observed_dates(observed_dates)
    expected = _date(expected_through, "expected_through") if expected_through is not None else None
    if expected is not None and expected not in ordered:
        raise CoverageValidationError("expected_through must be one of sessions")
    bounded = ordered if expected is None else tuple(
        session for session in ordered if session <= expected
    )
    if not bounded:
        raise CoverageValidationError("coverage boundary must include a session")

    if coverage_mode is CoverageMode.SPARSE:
        if expected is None:
            return CoverageAssessment(
                dataset_id=dataset_id,
                coverage_mode=coverage_mode,
                safe_watermark=None,
                state=CoverageState.NOT_APPLICABLE,
            )
        if expected in observed:
            return CoverageAssessment(
                dataset_id=dataset_id,
                coverage_mode=coverage_mode,
                safe_watermark=expected,
                state=CoverageState.COMPLETE,
            )
        return CoverageAssessment(
            dataset_id=dataset_id,
            coverage_mode=coverage_mode,
            safe_watermark=None,
            state=CoverageState.UNKNOWN,
            reason_codes=(REASON_COVERAGE_UNKNOWN,),
        )

    observed_bounded = observed.intersection(bounded)
    prefix: list[str] = []
    for session in bounded:
        if session not in observed_bounded:
            break
        prefix.append(session)
    watermark = prefix[-1] if prefix else None
    if len(prefix) == len(bounded):
        return CoverageAssessment(
            dataset_id=dataset_id,
            coverage_mode=coverage_mode,
            safe_watermark=watermark,
            state=CoverageState.COMPLETE,
        )
    reason = (
        REASON_COVERAGE_INTERIOR_GAP
        if prefix and observed_bounded - set(prefix)
        else REASON_COVERAGE_EXPECTED_NOT_REACHED
    )
    return CoverageAssessment(
        dataset_id=dataset_id,
        coverage_mode=coverage_mode,
        safe_watermark=watermark,
        state=CoverageState.PARTIAL,
        reason_codes=(reason,),
    )


__all__ = [
    "SCHEMA_VERSION",
    "CoverageAssessment",
    "CoverageState",
    "CoverageValidationError",
    "REASON_COVERAGE_EXPECTED_NOT_REACHED",
    "REASON_COVERAGE_INTERIOR_GAP",
    "REASON_COVERAGE_UNKNOWN",
    "assess_coverage",
]
