"""Conservative release-time admission, not a financial PIT storage platform.

The caller's trusted adapter must attest publication of the *exact version*.
An announcement date, report period or retrieval time cannot supply that fact.
No production authority is registered here: the existing financial shadow route
has no such evidence. Admission never establishes report-period applicability,
canonical quality, or availability in a previously frozen decision bundle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from data_contracts import (
    DataContractError, ProviderObservation, QualityStatus, _utc_timestamp,
)
from financial_indicator_shadow import DATASET_ID


# No current provider has verified exact-version publication authority. Only
# reviewed server-side adapter integration may populate this registry; neither
# a query argument nor provider payload can grant itself authority.
_TRUSTED_PUBLICATION_AUTHORITIES: frozenset[tuple[str, str, str]] = frozenset()


@dataclass(frozen=True)
class FinancialPublicationEvidence:
    """Trusted-adapter evidence bound to one immutable provider version.

    ``published_at`` means release of this payload/revision, not original filing
    release when the payload contains a later correction. Trust is supplied by
    server-side configuration; a source ref in an arbitrary payload is not trust.
    """
    authority_ref: str
    observation_id: str
    dataset_id: str
    provider_id: str
    provider_endpoint: str
    provider_symbol: str
    report_period: str
    source_payload_hash: str
    revision_id: str | None
    data_version: str | None
    published_at: str | None


@dataclass(frozen=True)
class FinancialTimeAdmission:
    status: Literal["CURRENT_VIEW", "UNKNOWN", "EXCLUDED", "TEMPORALLY_ADMISSIBLE"]
    reason_code: str


class FinancialAsOfUnavailable(DataContractError):
    def __init__(self, admissions: tuple[FinancialTimeAdmission, ...]):
        self.admissions = admissions
        reasons = ", ".join(sorted({item.reason_code for item in admissions}))
        super().__init__(f"financial as_of/PIT unavailable: {reasons}")


def evaluate_financial_time_admission(
    observation: ProviderObservation | None,
    *,
    provider_symbol: str,
    report_period: str,
    as_of: str | None,
    publication_evidence: FinancialPublicationEvidence | None = None,
) -> FinancialTimeAdmission:
    """Evaluate release-time eligibility without mutating evidence or storage.

    Cutoffs use the existing canonical UTC timestamp contract. Invalid/naive or
    offset timestamps are rejected, never lexically compared or silently guessed.
    Fetch/observation/effective times are deliberately not publication proxies.
    """
    def result(status, reason):
        return FinancialTimeAdmission(status, reason)

    if as_of is None:
        return result("CURRENT_VIEW", "HISTORICAL_CUTOFF_NOT_REQUESTED")
    try:
        _utc_timestamp(as_of, "as_of", required=True)
    except DataContractError:
        return result("UNKNOWN", "INVALID_AS_OF_TIMESTAMP")
    if observation is None:
        return result("UNKNOWN", "FINANCIAL_OBSERVATION_MISSING")
    if observation.dataset_id != DATASET_ID \
            or observation.provider_symbol != provider_symbol \
            or observation.report_period != report_period:
        return result("EXCLUDED", "FINANCIAL_SUBJECT_MISMATCH")
    if observation.quality_status is not QualityStatus.VALID:
        return result("UNKNOWN", "FINANCIAL_OBSERVATION_NOT_VALID")
    evidence = publication_evidence
    if evidence is None:
        return result("UNKNOWN", "AUTHORITATIVE_PUBLICATION_MISSING")
    authority_route = (
        evidence.authority_ref, observation.provider_id, observation.provider_endpoint,
    )
    if authority_route not in _TRUSTED_PUBLICATION_AUTHORITIES:
        return result("UNKNOWN", "PUBLICATION_AUTHORITY_NOT_TRUSTED")
    fields = (
        "observation_id", "dataset_id", "provider_id", "provider_endpoint",
        "provider_symbol", "report_period", "source_payload_hash", "revision_id", "data_version",
    )
    if any(getattr(evidence, field) != getattr(observation, field) for field in fields):
        return result("EXCLUDED", "PUBLICATION_VERSION_BINDING_MISMATCH")
    if evidence.published_at is None:
        return result("UNKNOWN", "AUTHORITATIVE_PUBLICATION_MISSING")
    try:
        _utc_timestamp(evidence.published_at, "published_at", required=True)
    except DataContractError:
        return result("UNKNOWN", "INVALID_PUBLICATION_TIMESTAMP")
    published = datetime.fromisoformat(evidence.published_at.replace("Z", "+00:00"))
    if observation.published_at is not None:
        observed_release = datetime.fromisoformat(
            observation.published_at.replace("Z", "+00:00"))
        if observed_release != published:
            return result("EXCLUDED", "PUBLICATION_TIMESTAMP_CONFLICT")
    if published > datetime.fromisoformat(as_of.replace("Z", "+00:00")):
        return result("EXCLUDED", "PUBLICATION_AFTER_AS_OF")
    return result("TEMPORALLY_ADMISSIBLE", "EXACT_VERSION_RELEASED_BY_AS_OF")
