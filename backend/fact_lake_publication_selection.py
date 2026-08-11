"""DS-L1-Q1 — canonical publication selection semantics core.

Pure selection semantics for choosing among multiple COMMITTED Fact Lake
canonical publications.  This module deliberately makes the distinction
explicit and reusable:

    LOCAL PUBLICATION ORDER
    != PROVIDER REVISION ORDER
    != SOURCE CHRONOLOGY
    != POINT-IN-TIME TRUTH.

``vintage_sequence`` is a local publication reservation/order sequence only.
It is NOT provider revision, source correction chronology, PIT revision,
as-of truth, or "most correct" fact.

Q1 is a pure selection semantics core.  No runtime integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Mapping

from data_contracts import (
    DatasetSpec,
    RevisionSemantics,
    TemporalSemantics,
)
from fact_lake_store import StoredCanonicalPublication


SELECTION_SCHEMA_VERSION = "fact-lake-publication-selection-v0.1"

COMMITTED_STATE = "COMMITTED"
_VALID_COMMIT_STATES = frozenset({"STAGING", "COMMITTED", "FAILED", "ABORTED"})


class PublicationSelectionMode(StrEnum):
    """Explicit selection modes; no ambiguous generic "latest"."""

    ALL = "all"
    PUBLICATION_ID = "publication_id"
    LOCAL_LATEST = "local_latest"


class PublicationSelectionBasis(StrEnum):
    """The explicit basis that produced the selection."""

    ALL_COMMITTED = "all_committed"
    EXACT_PUBLICATION_ID = "exact_publication_id"
    LOCAL_VINTAGE_SEQUENCE = "local_vintage_sequence"


class PublicationSelectionError(RuntimeError):
    """Base fail-closed selection error."""


class PublicationSelectionInputError(PublicationSelectionError):
    """Request or candidate input violated the strict contract."""


class PublicationSelectionNotFoundError(PublicationSelectionError):
    """PUBLICATION_ID matched no committed publication."""


class PublicationSelectionAmbiguousError(PublicationSelectionError):
    """Candidates were ambiguous under the frozen policy."""


class PublicationSelectionPitError(PublicationSelectionError):
    """as_of selection is unsupported or not implemented."""


@dataclass(frozen=True)
class PublicationSelectionRequest:
    """Strict request value object; no coercion, no unknown fields."""

    dataset_id: str
    canonical_key: str
    primary_temporal_field: TemporalSemantics
    primary_temporal_value: str
    mode: PublicationSelectionMode
    publication_id: str | None = None
    as_of: str | None = None

    def __post_init__(self) -> None:
        if type(self.dataset_id) is not str or not self.dataset_id.strip():
            raise PublicationSelectionInputError("dataset_id is required")
        if type(self.canonical_key) is not str or not self.canonical_key.strip():
            raise PublicationSelectionInputError("canonical_key is required")
        if not isinstance(self.primary_temporal_field, TemporalSemantics):
            raise PublicationSelectionInputError(
                "primary_temporal_field must be TemporalSemantics"
            )
        if type(self.primary_temporal_value) is not str \
                or not self.primary_temporal_value.strip():
            raise PublicationSelectionInputError(
                "primary_temporal_value is required"
            )
        if not isinstance(self.mode, PublicationSelectionMode):
            raise PublicationSelectionInputError("mode must be a selection mode")
        if self.mode is PublicationSelectionMode.PUBLICATION_ID:
            if type(self.publication_id) is not str \
                    or not self.publication_id.strip():
                raise PublicationSelectionInputError(
                    "PUBLICATION_ID mode requires publication_id"
                )
        else:
            if self.publication_id is not None:
                raise PublicationSelectionInputError(
                    "publication_id must be None outside PUBLICATION_ID mode"
                )
        if self.as_of is not None and type(self.as_of) is not str:
            raise PublicationSelectionInputError("as_of must be a string or null")


@dataclass(frozen=True)
class CanonicalPublicationSelection:
    """Deterministic immutable selection output."""

    schema_version: str
    dataset_id: str
    canonical_key: str
    primary_temporal_field: str
    primary_temporal_value: str
    selection_mode: str
    selection_basis: str
    selected_publication_ids: tuple[str, ...]
    selected_vintage_sequences: tuple[int, ...]
    dataset_contract_revisions: tuple[str, ...]
    normalizer_versions: tuple[str, ...]
    artifact_schema_versions: tuple[str, ...]
    revision_semantics: str
    provider_revision_claim: str
    point_in_time_claim: str

    def __post_init__(self) -> None:
        # from_dict verifies structural/semantic self-consistency of the
        # serialized selection itself; it does NOT re-run selection and
        # does NOT invent original candidate provenance.
        if self.schema_version != SELECTION_SCHEMA_VERSION:
            raise PublicationSelectionInputError(
                "schema_version must be "
                f"{SELECTION_SCHEMA_VERSION!r}"
            )
        if type(self.dataset_id) is not str or not self.dataset_id:
            raise PublicationSelectionInputError("dataset_id is required")
        if type(self.canonical_key) is not str or not self.canonical_key:
            raise PublicationSelectionInputError("canonical_key is required")
        if type(self.primary_temporal_field) is not str:
            raise PublicationSelectionInputError(
                "primary_temporal_field must be a TemporalSemantics value"
            )
        try:
            TemporalSemantics(self.primary_temporal_field)
        except (TypeError, ValueError) as exc:
            raise PublicationSelectionInputError(
                "primary_temporal_field must be a TemporalSemantics value"
            ) from exc
        if type(self.primary_temporal_value) is not str \
                or not self.primary_temporal_value:
            raise PublicationSelectionInputError(
                "primary_temporal_value is required"
            )
        if self.selection_mode not in {
            mode.value for mode in PublicationSelectionMode
        }:
            raise PublicationSelectionInputError("selection_mode is invalid")
        if self.selection_basis not in {
            basis.value for basis in PublicationSelectionBasis
        }:
            raise PublicationSelectionInputError("selection_basis is invalid")
        expected_basis = {
            PublicationSelectionMode.ALL.value:
                PublicationSelectionBasis.ALL_COMMITTED.value,
            PublicationSelectionMode.PUBLICATION_ID.value:
                PublicationSelectionBasis.EXACT_PUBLICATION_ID.value,
            PublicationSelectionMode.LOCAL_LATEST.value:
                PublicationSelectionBasis.LOCAL_VINTAGE_SEQUENCE.value,
        }[self.selection_mode]
        if self.selection_basis != expected_basis:
            raise PublicationSelectionInputError(
                "selection_basis does not match selection_mode"
            )
        if type(self.selected_publication_ids) is not tuple \
                or type(self.selected_vintage_sequences) is not tuple \
                or type(self.dataset_contract_revisions) is not tuple \
                or type(self.normalizer_versions) is not tuple \
                or type(self.artifact_schema_versions) is not tuple:
            raise PublicationSelectionInputError(
                "selection tuples must be tuples"
            )
        if len(self.selected_publication_ids) != len(
            self.selected_vintage_sequences
        ) or len(self.selected_publication_ids) != len(
            self.dataset_contract_revisions
        ) or len(self.selected_publication_ids) != len(
            self.normalizer_versions
        ) or len(self.selected_publication_ids) != len(
            self.artifact_schema_versions
        ):
            raise PublicationSelectionInputError(
                "selection metadata tuple lengths disagree"
            )
        count = len(self.selected_publication_ids)
        if self.selection_mode == PublicationSelectionMode.PUBLICATION_ID.value:
            if count != 1:
                raise PublicationSelectionInputError(
                    "PUBLICATION_ID selection must contain exactly one "
                    "publication"
                )
        elif self.selection_mode == PublicationSelectionMode.LOCAL_LATEST.value:
            if count > 1:
                raise PublicationSelectionInputError(
                    "LOCAL_LATEST selection must contain at most one "
                    "publication"
                )
        if self.selection_mode == PublicationSelectionMode.ALL.value:
            vintages = list(self.selected_vintage_sequences)
            if vintages != sorted(vintages):
                raise PublicationSelectionInputError(
                    "ALL selection vintages must be strictly ascending"
                )
            if len(set(vintages)) != len(vintages):
                raise PublicationSelectionInputError(
                    "ALL selection vintages must be unique"
                )
        if len(set(self.selected_publication_ids)) != len(
            self.selected_publication_ids
        ):
            raise PublicationSelectionInputError(
                "selected publication ids must be unique"
            )
        if len(set(self.selected_vintage_sequences)) != len(
            self.selected_vintage_sequences
        ):
            raise PublicationSelectionInputError(
                "selected vintage sequences must be unique"
            )
        for vintage in self.selected_vintage_sequences:
            if type(vintage) is not int or vintage < 1:
                raise PublicationSelectionInputError(
                    "vintage_sequence must be a positive integer"
                )
        for publication_id in self.selected_publication_ids:
            if type(publication_id) is not str or not publication_id:
                raise PublicationSelectionInputError(
                    "selected publication ids must be non-empty strings"
                )
        for metadata in (
            self.dataset_contract_revisions,
            self.normalizer_versions,
            self.artifact_schema_versions,
        ):
            for value in metadata:
                if type(value) is not str or not value:
                    raise PublicationSelectionInputError(
                        "selection metadata must be non-empty strings"
                    )
        if self.provider_revision_claim != "NONE":
            raise PublicationSelectionInputError(
                "provider_revision_claim must be NONE"
            )
        if self.point_in_time_claim != "NONE":
            raise PublicationSelectionInputError(
                "point_in_time_claim must be NONE"
            )
        try:
            RevisionSemantics(self.revision_semantics)
        except (TypeError, ValueError) as exc:
            raise PublicationSelectionInputError(
                "revision_semantics is invalid"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "canonical_key": self.canonical_key,
            "primary_temporal_field": self.primary_temporal_field,
            "primary_temporal_value": self.primary_temporal_value,
            "selection_mode": self.selection_mode,
            "selection_basis": self.selection_basis,
            "selected_publication_ids": list(self.selected_publication_ids),
            "selected_vintage_sequences": list(
                self.selected_vintage_sequences
            ),
            "dataset_contract_revisions": list(
                self.dataset_contract_revisions
            ),
            "normalizer_versions": list(self.normalizer_versions),
            "artifact_schema_versions": list(self.artifact_schema_versions),
            "revision_semantics": self.revision_semantics,
            "provider_revision_claim": self.provider_revision_claim,
            "point_in_time_claim": self.point_in_time_claim,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CanonicalPublicationSelection":
        if type(value) is not dict:
            raise PublicationSelectionInputError(
                "selection must be a JSON object"
            )
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            missing = sorted(expected - set(value))
            extra = sorted(set(value) - expected)
            raise PublicationSelectionInputError(
                f"selection fields mismatch: missing={missing}, extra={extra}"
            )
        for field in (
            "selected_publication_ids",
            "selected_vintage_sequences",
            "dataset_contract_revisions",
            "normalizer_versions",
            "artifact_schema_versions",
        ):
            if type(value[field]) is not list:
                raise PublicationSelectionInputError(
                    f"{field} must be a JSON array"
                )
        return cls(
            schema_version=value["schema_version"],
            dataset_id=value["dataset_id"],
            canonical_key=value["canonical_key"],
            primary_temporal_field=value["primary_temporal_field"],
            primary_temporal_value=value["primary_temporal_value"],
            selection_mode=value["selection_mode"],
            selection_basis=value["selection_basis"],
            selected_publication_ids=tuple(value["selected_publication_ids"]),
            selected_vintage_sequences=tuple(
                value["selected_vintage_sequences"]
            ),
            dataset_contract_revisions=tuple(
                value["dataset_contract_revisions"]
            ),
            normalizer_versions=tuple(value["normalizer_versions"]),
            artifact_schema_versions=tuple(
                value["artifact_schema_versions"]
            ),
            revision_semantics=value["revision_semantics"],
            provider_revision_claim=value["provider_revision_claim"],
            point_in_time_claim=value["point_in_time_claim"],
        )


def _validate_committed_candidate(
    request: PublicationSelectionRequest,
    candidate: StoredCanonicalPublication,
) -> None:
    if not isinstance(candidate, StoredCanonicalPublication):
        raise PublicationSelectionInputError(
            "candidate must be StoredCanonicalPublication"
        )
    if candidate.commit_state != COMMITTED_STATE:
        raise PublicationSelectionInputError(
            "selection core consumes committed publications only; "
            f"got {candidate.commit_state!r}"
        )
    if type(candidate.vintage_sequence) is not int \
            or candidate.vintage_sequence < 1:
        raise PublicationSelectionInputError(
            "vintage_sequence must be a positive integer"
        )
    if candidate.dataset_id != request.dataset_id:
        raise PublicationSelectionInputError(
            "candidate dataset_id does not match request"
        )
    if candidate.canonical_key != request.canonical_key:
        raise PublicationSelectionInputError(
            "candidate canonical_key does not match request"
        )
    if candidate.primary_temporal_field != request.primary_temporal_field.value \
            or candidate.primary_temporal_value \
                != request.primary_temporal_value:
        raise PublicationSelectionInputError(
            "candidate temporal coordinate does not match request"
        )
    if candidate.commit_state not in _VALID_COMMIT_STATES:
        raise PublicationSelectionInputError(
            "candidate commit_state is unknown"
        )


def select_canonical_publications(
    spec: DatasetSpec,
    request: PublicationSelectionRequest,
    candidates: tuple[StoredCanonicalPublication, ...],
) -> CanonicalPublicationSelection:
    """Select committed publications under the frozen Q1 semantics."""
    if not isinstance(spec, DatasetSpec):
        raise PublicationSelectionInputError("spec must be DatasetSpec")
    if not isinstance(request, PublicationSelectionRequest):
        raise PublicationSelectionInputError(
            "request must be PublicationSelectionRequest"
        )
    if type(candidates) is not tuple:
        raise PublicationSelectionInputError("candidates must be a tuple")
    if request.dataset_id != spec.dataset_id:
        raise PublicationSelectionInputError(
            "request dataset_id must match DatasetSpec"
        )

    if request.as_of is not None:
        if not spec.point_in_time_supported:
            raise PublicationSelectionPitError(
                "DATASET_PIT_UNSUPPORTED: as_of requested but dataset "
                "does not support point-in-time"
            )
        raise PublicationSelectionPitError(
            "SELECTION_PIT_NOT_IMPLEMENTED: Q1 v0.1 does not implement "
            "as-of reconstruction"
        )

    matching: list[StoredCanonicalPublication] = []
    for candidate in candidates:
        if candidate.dataset_id != request.dataset_id \
                or candidate.canonical_key != request.canonical_key \
                or candidate.primary_temporal_field \
                    != request.primary_temporal_field.value \
                or candidate.primary_temporal_value \
                    != request.primary_temporal_value:
            # Frozen policy: filter to the exact request coordinate, then
            # strictly validate every selected candidate.
            continue
        _validate_committed_candidate(request, candidate)
        matching.append(candidate)

    vintage_to_ids: dict[int, list[str]] = {}
    for candidate in matching:
        vintage_to_ids.setdefault(
            candidate.vintage_sequence, []
        ).append(candidate.publication_id)
    duplicate_vintages = sorted(
        vintage
        for vintage, ids in vintage_to_ids.items()
        if len(set(ids)) > 1
    )
    if duplicate_vintages:
        raise PublicationSelectionAmbiguousError(
            "duplicate vintage_sequence with different publication ids: "
            f"{duplicate_vintages}"
        )

    ordered = sorted(
        matching,
        key=lambda p: (
            p.vintage_sequence,
            p.publication_id,
        ),
    )

    if request.mode is PublicationSelectionMode.ALL:
        selected = ordered
        basis = PublicationSelectionBasis.ALL_COMMITTED
    elif request.mode is PublicationSelectionMode.PUBLICATION_ID:
        selected = [
            publication
            for publication in ordered
            if publication.publication_id == request.publication_id
        ]
        if not selected:
            raise PublicationSelectionNotFoundError(
                "publication_id matched no committed publication"
            )
        if len(selected) > 1:
            raise PublicationSelectionAmbiguousError(
                "publication_id matched multiple committed publications"
            )
        basis = PublicationSelectionBasis.EXACT_PUBLICATION_ID
    else:
        revisions = {p.dataset_contract_revision for p in ordered}
        if len(revisions) > 1:
            raise PublicationSelectionAmbiguousError(
                "CONTRACT_REVISION_AMBIGUOUS: LOCAL_LATEST requires one "
                "dataset_contract_revision per coordinate"
            )
        selected = ordered[-1:] if ordered else []
        basis = PublicationSelectionBasis.LOCAL_VINTAGE_SEQUENCE

    return CanonicalPublicationSelection(
        schema_version=SELECTION_SCHEMA_VERSION,
        dataset_id=request.dataset_id,
        canonical_key=request.canonical_key,
        primary_temporal_field=request.primary_temporal_field.value,
        primary_temporal_value=request.primary_temporal_value,
        selection_mode=request.mode.value,
        selection_basis=basis.value,
        selected_publication_ids=tuple(
            p.publication_id for p in selected
        ),
        selected_vintage_sequences=tuple(
            p.vintage_sequence for p in selected
        ),
        dataset_contract_revisions=tuple(
            p.dataset_contract_revision for p in selected
        ),
        normalizer_versions=tuple(
            p.normalizer_version for p in selected
        ),
        artifact_schema_versions=tuple(
            p.artifact_schema_version for p in selected
        ),
        revision_semantics=spec.revision_semantics.value,
        provider_revision_claim="NONE",
        point_in_time_claim="NONE",
    )


__all__ = [
    "SELECTION_SCHEMA_VERSION",
    "CanonicalPublicationSelection",
    "COMMITTED_STATE",
    "PublicationSelectionAmbiguousError",
    "PublicationSelectionBasis",
    "PublicationSelectionError",
    "PublicationSelectionInputError",
    "PublicationSelectionMode",
    "PublicationSelectionNotFoundError",
    "PublicationSelectionPitError",
    "PublicationSelectionRequest",
    "select_canonical_publications",
]
