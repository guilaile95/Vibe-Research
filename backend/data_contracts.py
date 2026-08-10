"""Pure contracts for dataset-level canonical data governance.

This module deliberately contains no provider, storage, or runtime integration.
Provider responses remain observations until a :class:`DatasetSpec` explicitly
permits canonicalization.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, TypeAlias


JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]
_UNSET = object()


class DataContractError(ValueError):
    """Raised when a data-governance contract would be violated."""


class FetchSemantics(StrEnum):
    BY_DATE = "by_date"
    SNAPSHOT = "snapshot"


class HistoryMode(StrEnum):
    BY_DATE = "by_date"
    SNAPSHOT_WITH_BACKFILL = "snapshot_with_backfill"
    SNAPSHOT_ONLY = "snapshot_only"


class ProviderRole(StrEnum):
    CANONICAL = "canonical"
    VERIFIER = "verifier"
    FALLBACK = "fallback"
    HISTORICAL_BACKFILL = "historical_backfill"


class QualityStatus(StrEnum):
    VALID = "valid"
    DEGRADED = "degraded"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class RevisionSemantics(StrEnum):
    UNKNOWN = "unknown"
    IMMUTABLE = "immutable"
    VERSIONED = "versioned"
    RESTATABLE = "restatable"


class AdjustmentSemantics(StrEnum):
    UNKNOWN = "unknown"
    UNADJUSTED = "unadjusted"
    FORWARD_ADJUSTED = "forward_adjusted"
    BACKWARD_ADJUSTED = "backward_adjusted"
    NOT_APPLICABLE = "not_applicable"


class ReconciliationStatus(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    SOURCE_UNAVAILABLE = "source_unavailable"
    TEMPORAL_INCOMPARABLE = "temporal_incomparable"


class TemporalSemantics(StrEnum):
    """Names of the distinct temporal meanings used by the contracts."""

    EFFECTIVE_AT = "effective_at"
    PUBLISHED_AT = "published_at"
    OBSERVED_AT = "observed_at"
    FETCHED_AT = "fetched_at"
    TRADE_DATE = "trade_date"
    REPORT_PERIOD = "report_period"


TEMPORAL_SEMANTICS_DEFINITIONS: Mapping[TemporalSemantics, str] = {
    TemporalSemantics.EFFECTIVE_AT:
        "Economic or business time/period to which the value applies.",
    TemporalSemantics.PUBLISHED_AT:
        "Time at which the originating source officially released the value.",
    TemporalSemantics.OBSERVED_AT:
        "Time represented by the provider as the observation time.",
    TemporalSemantics.FETCHED_AT:
        "Time at which Vibe-Research retrieved the provider response.",
    TemporalSemantics.TRADE_DATE:
        "Exchange trading date explicitly bound by the source contract.",
    TemporalSemantics.REPORT_PERIOD:
        "Accounting or reporting period explicitly stated by the source.",
}

_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


def _non_empty(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise DataContractError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty(value, field)


def _utc_timestamp(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise DataContractError(f"{field} must be a canonical UTC timestamp")
        return None
    if type(value) is not str or _UTC_RE.fullmatch(value) is None:
        raise DataContractError(f"{field} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataContractError(
            f"{field} must be a canonical UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise DataContractError(f"{field} must be a canonical UTC timestamp")
    return value


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _date_only(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise DataContractError(f"{field} must be an ISO calendar date")
        return None
    if type(value) is not str:
        raise DataContractError(f"{field} must be an ISO calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DataContractError(f"{field} must be an ISO calendar date") from exc
    if parsed.isoformat() != value:
        raise DataContractError(f"{field} must be an ISO calendar date")
    return value


def _reason_codes(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise DataContractError("reason_codes must be a list or tuple")
    result: list[str] = []
    for code in value:
        result.append(_non_empty(code, "reason_code"))
    if len(result) != len(set(result)):
        raise DataContractError("reason_codes must not contain duplicates")
    return tuple(result)


def _json_safe(value: Any, field: str = "payload") -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise DataContractError(f"{field} contains a non-finite float")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _json_safe(item, f"{field}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise DataContractError(f"{field} contains a non-string key")
            _json_safe(item, f"{field}.{key}")
        return
    raise DataContractError(f"{field} is not JSON-safe")


def _exact(data: Mapping[str, Any], expected: set[str], kind: str) -> None:
    if type(data) is not dict:
        raise DataContractError(f"{kind} must be a JSON object")
    actual = set(data)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DataContractError(
            f"{kind} fields mismatch: missing={missing}, extra={extra}")


def _json_array(data: Mapping[str, Any], field: str) -> list[Any]:
    value = data[field]
    if type(value) is not list:
        raise DataContractError(f"{field} must be a JSON array")
    return value


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class ProviderObservation:
    observation_id: str
    dataset_id: str
    provider_id: str
    provider_endpoint: str
    provider_symbol: str
    request_fingerprint: str
    source_payload_hash: str
    normalizer_version: str
    payload: JSONValue
    fetch_semantics: FetchSemantics
    history_mode: HistoryMode
    fetched_at: str
    effective_at: str | None = None
    published_at: str | None = None
    observed_at: str | None = None
    trade_date: str | None = None
    report_period: str | None = None
    revision_id: str | None = None
    data_version: str | None = None
    revision_semantics: RevisionSemantics = RevisionSemantics.UNKNOWN
    adjustment_semantics: AdjustmentSemantics = AdjustmentSemantics.UNKNOWN
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "observation_id", "dataset_id", "provider_id",
            "provider_endpoint", "provider_symbol", "request_fingerprint",
            "source_payload_hash", "normalizer_version",
        ):
            _non_empty(getattr(self, field), field)
        _utc_timestamp(self.fetched_at, "fetched_at", required=True)
        for field in ("effective_at", "published_at", "observed_at"):
            _utc_timestamp(getattr(self, field), field)
        _date_only(self.trade_date, "trade_date")
        for field in (
            "report_period", "revision_id", "data_version",
        ):
            _optional_text(getattr(self, field), field)
        if not isinstance(self.fetch_semantics, FetchSemantics):
            raise DataContractError("fetch_semantics must be FetchSemantics")
        if not isinstance(self.history_mode, HistoryMode):
            raise DataContractError("history_mode must be HistoryMode")
        if not isinstance(self.quality_status, QualityStatus):
            raise DataContractError("quality_status must be QualityStatus")
        if not isinstance(self.revision_semantics, RevisionSemantics):
            raise DataContractError(
                "revision_semantics must be RevisionSemantics")
        if not isinstance(self.adjustment_semantics, AdjustmentSemantics):
            raise DataContractError(
                "adjustment_semantics must be AdjustmentSemantics")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        if self.quality_status is not QualityStatus.VALID \
                and not self.reason_codes:
            raise DataContractError(
                "non-valid quality_status requires at least one reason_code")
        _json_safe(self.payload)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "observation_id": self.observation_id,
            "dataset_id": self.dataset_id,
            "provider_id": self.provider_id,
            "provider_endpoint": self.provider_endpoint,
            "provider_symbol": self.provider_symbol,
            "request_fingerprint": self.request_fingerprint,
            "source_payload_hash": self.source_payload_hash,
            "normalizer_version": self.normalizer_version,
            "payload": self.payload,
            "fetch_semantics": self.fetch_semantics.value,
            "history_mode": self.history_mode.value,
            "effective_at": self.effective_at,
            "published_at": self.published_at,
            "observed_at": self.observed_at,
            "fetched_at": self.fetched_at,
            "trade_date": self.trade_date,
            "report_period": self.report_period,
            "revision_id": self.revision_id,
            "data_version": self.data_version,
            "revision_semantics": self.revision_semantics.value,
            "adjustment_semantics": self.adjustment_semantics.value,
            "quality_status": self.quality_status.value,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderObservation":
        expected = set(cls.__dataclass_fields__)
        _exact(data, expected, "ProviderObservation")
        return cls(
            **{
                **data,
                "fetch_semantics": FetchSemantics(data["fetch_semantics"]),
                "history_mode": HistoryMode(data["history_mode"]),
                "revision_semantics": RevisionSemantics(
                    data["revision_semantics"]),
                "adjustment_semantics": AdjustmentSemantics(
                    data["adjustment_semantics"]),
                "quality_status": QualityStatus(data["quality_status"]),
                "reason_codes": tuple(_json_array(data, "reason_codes")),
            }
        )


@dataclass(frozen=True)
class ProviderRoute:
    route_id: str
    provider_id: str
    provider_endpoint: str
    role: ProviderRole
    semantic_contract_id: str
    equivalent_to_route_id: str | None = None
    automatic_routing_allowed: bool = False
    retired_at: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.route_id, "route_id")
        _non_empty(self.provider_id, "provider_id")
        _non_empty(self.provider_endpoint, "provider_endpoint")
        _non_empty(self.semantic_contract_id, "semantic_contract_id")
        _optional_text(
            self.equivalent_to_route_id, "equivalent_to_route_id")
        _utc_timestamp(self.retired_at, "retired_at")
        if not isinstance(self.role, ProviderRole):
            raise DataContractError("role must be ProviderRole")
        if type(self.automatic_routing_allowed) is not bool:
            raise DataContractError("automatic_routing_allowed must be bool")
        if self.role is not ProviderRole.FALLBACK:
            if self.equivalent_to_route_id is not None:
                raise DataContractError(
                    "only fallback routes may declare semantic equivalence")
            if self.automatic_routing_allowed:
                raise DataContractError(
                    "automatic routing is only permitted for explicit fallback")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "route_id": self.route_id,
            "provider_id": self.provider_id,
            "provider_endpoint": self.provider_endpoint,
            "role": self.role.value,
            "semantic_contract_id": self.semantic_contract_id,
            "equivalent_to_route_id": self.equivalent_to_route_id,
            "automatic_routing_allowed": self.automatic_routing_allowed,
            "retired_at": self.retired_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderRoute":
        _exact(data, set(cls.__dataclass_fields__), "ProviderRoute")
        return cls(**{**data, "role": ProviderRole(data["role"])})


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    fetch_semantics: FetchSemantics
    history_mode: HistoryMode
    routes: tuple[ProviderRoute, ...]
    governance_revision_id: str
    history_floor: str | None = None
    history_horizon: str | None = None
    point_in_time_supported: bool = False
    revision_semantics: RevisionSemantics = RevisionSemantics.UNKNOWN
    adjustment_semantics: AdjustmentSemantics = AdjustmentSemantics.UNKNOWN
    survivorship_semantics: str | None = None
    source_retired_at: str | None = None
    max_staleness_seconds: int | None = None

    def __post_init__(self) -> None:
        _non_empty(self.dataset_id, "dataset_id")
        _non_empty(self.governance_revision_id, "governance_revision_id")
        if not isinstance(self.fetch_semantics, FetchSemantics):
            raise DataContractError("fetch_semantics must be FetchSemantics")
        if not isinstance(self.history_mode, HistoryMode):
            raise DataContractError("history_mode must be HistoryMode")
        if type(self.routes) is not tuple or not self.routes:
            raise DataContractError("routes must be a non-empty tuple")
        if any(not isinstance(route, ProviderRoute) for route in self.routes):
            raise DataContractError("routes must contain ProviderRoute values")
        if type(self.point_in_time_supported) is not bool:
            raise DataContractError("point_in_time_supported must be bool")
        _date_only(self.history_floor, "history_floor")
        _date_only(self.history_horizon, "history_horizon")
        _optional_text(self.survivorship_semantics, "survivorship_semantics")
        _utc_timestamp(self.source_retired_at, "source_retired_at")
        if not isinstance(self.revision_semantics, RevisionSemantics):
            raise DataContractError(
                "revision_semantics must be RevisionSemantics")
        if not isinstance(self.adjustment_semantics, AdjustmentSemantics):
            raise DataContractError(
                "adjustment_semantics must be AdjustmentSemantics")
        if self.max_staleness_seconds is not None and (
            type(self.max_staleness_seconds) is not int
            or self.max_staleness_seconds < 0
        ):
            raise DataContractError(
                "max_staleness_seconds must be a non-negative int or null")
        if self.history_floor is not None and self.history_horizon is not None \
                and self.history_floor > self.history_horizon:
            raise DataContractError("history_floor must not exceed history_horizon")
        if self.point_in_time_supported and (
            self.revision_semantics is RevisionSemantics.UNKNOWN
            or self.survivorship_semantics is None
            or self.survivorship_semantics.strip().lower() == "unknown"
        ):
            raise DataContractError(
                "point-in-time datasets require revision and survivorship semantics")

        ids = [route.route_id for route in self.routes]
        if len(ids) != len(set(ids)):
            raise DataContractError("route_id values must be unique")
        route_keys = [
            (route.provider_id, route.provider_endpoint) for route in self.routes
        ]
        if len(route_keys) != len(set(route_keys)):
            raise DataContractError(
                "provider_id/provider_endpoint route identities must be unique")
        canonical = [r for r in self.routes if r.role is ProviderRole.CANONICAL]
        if len(canonical) != 1:
            raise DataContractError("dataset requires exactly one canonical route")
        canonical_route = canonical[0]
        by_id = {route.route_id: route for route in self.routes}
        for route in self.routes:
            if route.role is ProviderRole.FALLBACK:
                if route.equivalent_to_route_id != canonical_route.route_id:
                    raise DataContractError(
                        "fallback must explicitly target the canonical route")
                if route.semantic_contract_id != canonical_route.semantic_contract_id:
                    raise DataContractError(
                        "fallback must be semantically equivalent to canonical")
                if route.equivalent_to_route_id not in by_id:
                    raise DataContractError("fallback equivalence target is unknown")

        backfills = [
            r for r in self.routes
            if r.role is ProviderRole.HISTORICAL_BACKFILL
        ]
        if self.history_mode is HistoryMode.SNAPSHOT_ONLY:
            if backfills or self.history_floor is not None:
                raise DataContractError(
                    "snapshot_only cannot declare historical backfill/history_floor")
            if self.fetch_semantics is not FetchSemantics.SNAPSHOT:
                raise DataContractError(
                    "snapshot_only requires snapshot fetch semantics")
        if backfills and self.history_mode is not HistoryMode.SNAPSHOT_WITH_BACKFILL:
            raise DataContractError(
                "historical_backfill requires snapshot_with_backfill")
        if self.history_mode is HistoryMode.SNAPSHOT_WITH_BACKFILL and not backfills:
            raise DataContractError(
                "snapshot_with_backfill requires a historical_backfill route")
        if self.history_mode is HistoryMode.BY_DATE \
                and self.fetch_semantics is not FetchSemantics.BY_DATE:
            raise DataContractError("by_date history requires by_date fetch semantics")

    @property
    def canonical_route(self) -> ProviderRoute:
        return next(
            route for route in self.routes
            if route.role is ProviderRole.CANONICAL)

    def route_for(
        self,
        provider_id: str,
        provider_endpoint: str,
    ) -> ProviderRoute:
        for route in self.routes:
            if route.provider_id == provider_id \
                    and route.provider_endpoint == provider_endpoint:
                return route
        raise DataContractError(
            f"provider route {provider_id!r}/{provider_endpoint!r} is not "
            f"configured for {self.dataset_id!r}")

    def canonical_route_for(
        self,
        provider_id: str,
        provider_endpoint: str,
    ) -> ProviderRoute:
        route = self.route_for(provider_id, provider_endpoint)
        if route.role not in (ProviderRole.CANONICAL, ProviderRole.FALLBACK):
            raise DataContractError(
                "verifier/backfill observations cannot become canonical facts")
        if route.role is ProviderRole.FALLBACK \
                and not route.automatic_routing_allowed:
            raise DataContractError(
                "fallback canonicalization requires explicit automatic routing")
        return route

    def assert_snapshot_history_not_fabricated(
        self,
        observation_effective_at: str | None,
        requested_effective_at: str | None,
    ) -> None:
        if (
            self.history_mode is HistoryMode.SNAPSHOT_ONLY
            and requested_effective_at != observation_effective_at
        ):
            raise DataContractError(
                "snapshot_only observations cannot fabricate historical truth")

    def assert_as_of_allowed(
        self,
        observation: ProviderObservation,
        as_of: str | None,
    ) -> None:
        if as_of is None:
            return
        _utc_timestamp(as_of, "as_of", required=True)
        if not self.point_in_time_supported:
            raise DataContractError("dataset does not support point-in-time queries")
        if _parse_utc(as_of) < _parse_utc(observation.fetched_at):
            raise DataContractError(
                "observation was unavailable at requested as_of")

    def validate_fact(self, fact: "CanonicalFact") -> None:
        if not isinstance(fact, CanonicalFact):
            raise DataContractError("fact must be CanonicalFact")
        if fact.dataset_id != self.dataset_id:
            raise DataContractError("fact dataset does not match DatasetSpec")
        if fact.dataset_contract_revision != self.governance_revision_id:
            raise DataContractError(
                "fact dataset contract revision does not match DatasetSpec")
        if fact.revision_semantics is not self.revision_semantics:
            raise DataContractError(
                "fact revision semantics do not match DatasetSpec")
        if fact.adjustment_semantics is not self.adjustment_semantics:
            raise DataContractError(
                "fact adjustment semantics do not match DatasetSpec")
        canonical_routes: list[ProviderRoute] = []
        for link in fact.provenance_chain:
            if link.dataset_id != self.dataset_id:
                raise DataContractError(
                    "provenance dataset does not match DatasetSpec")
            route = self.route_for(
                link.provider_id, link.provider_endpoint)
            if link.provider_id == fact.canonical_source:
                canonical_routes.append(
                    self.canonical_route_for(
                        link.provider_id, link.provider_endpoint))
        if len(canonical_routes) != 1:
            raise DataContractError(
                "canonical source must resolve to exactly one provenance route")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "dataset_id": self.dataset_id,
            "fetch_semantics": self.fetch_semantics.value,
            "history_mode": self.history_mode.value,
            "routes": [route.to_dict() for route in self.routes],
            "governance_revision_id": self.governance_revision_id,
            "history_floor": self.history_floor,
            "history_horizon": self.history_horizon,
            "point_in_time_supported": self.point_in_time_supported,
            "revision_semantics": self.revision_semantics.value,
            "adjustment_semantics": self.adjustment_semantics.value,
            "survivorship_semantics": self.survivorship_semantics,
            "source_retired_at": self.source_retired_at,
            "max_staleness_seconds": self.max_staleness_seconds,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DatasetSpec":
        _exact(data, set(cls.__dataclass_fields__), "DatasetSpec")
        return cls(**{
            **data,
            "fetch_semantics": FetchSemantics(data["fetch_semantics"]),
            "history_mode": HistoryMode(data["history_mode"]),
            "revision_semantics": RevisionSemantics(
                data["revision_semantics"]),
            "adjustment_semantics": AdjustmentSemantics(
                data["adjustment_semantics"]),
            "routes": tuple(
                ProviderRoute.from_dict(route)
                for route in _json_array(data, "routes")
            ),
        })


@dataclass(frozen=True)
class ProvenanceLink:
    observation_id: str
    dataset_id: str
    provider_id: str
    provider_endpoint: str
    source_payload_hash: str
    normalizer_version: str

    def __post_init__(self) -> None:
        for field in (
            "observation_id", "dataset_id", "provider_id",
            "provider_endpoint", "source_payload_hash", "normalizer_version",
        ):
            _non_empty(getattr(self, field), field)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "observation_id": self.observation_id,
            "dataset_id": self.dataset_id,
            "provider_id": self.provider_id,
            "provider_endpoint": self.provider_endpoint,
            "source_payload_hash": self.source_payload_hash,
            "normalizer_version": self.normalizer_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceLink":
        _exact(data, set(cls.__dataclass_fields__), "ProvenanceLink")
        return cls(**data)


@dataclass(frozen=True)
class CanonicalFact:
    fact_id: str
    dataset_id: str
    canonical_key: str
    canonical_payload: JSONValue
    canonical_source: str
    dataset_contract_revision: str
    revision_semantics: RevisionSemantics
    adjustment_semantics: AdjustmentSemantics
    source_observation_ids: tuple[str, ...]
    provenance_chain: tuple[ProvenanceLink, ...]
    effective_at: str | None = None
    published_at: str | None = None
    observed_at: str | None = None
    revision_id: str | None = None
    data_version: str | None = None
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    reconciliation_status: ReconciliationStatus = ReconciliationStatus.UNKNOWN
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "fact_id", "dataset_id", "canonical_key", "canonical_source",
            "dataset_contract_revision",
        ):
            _non_empty(getattr(self, field), field)
        for field in (
            "effective_at", "published_at", "observed_at",
        ):
            _utc_timestamp(getattr(self, field), field)
        for field in ("revision_id", "data_version"):
            _optional_text(getattr(self, field), field)
        if type(self.source_observation_ids) is not tuple \
                or not self.source_observation_ids:
            raise DataContractError(
                "source_observation_ids must be a non-empty tuple")
        for observation_id in self.source_observation_ids:
            _non_empty(observation_id, "source_observation_id")
        if len(set(self.source_observation_ids)) != len(
                self.source_observation_ids):
            raise DataContractError("source_observation_ids must be unique")
        if type(self.provenance_chain) is not tuple \
                or not self.provenance_chain:
            raise DataContractError("provenance_chain must be non-empty")
        if any(not isinstance(link, ProvenanceLink)
               for link in self.provenance_chain):
            raise DataContractError(
                "provenance_chain must contain ProvenanceLink values")
        provenance_ids = tuple(link.observation_id
                               for link in self.provenance_chain)
        if provenance_ids != self.source_observation_ids:
            raise DataContractError(
                "provenance_chain must exactly match source_observation_ids")
        if self.canonical_source not in {
                link.provider_id for link in self.provenance_chain}:
            raise DataContractError(
                "canonical_source must appear in provenance_chain")
        if not isinstance(self.quality_status, QualityStatus):
            raise DataContractError("quality_status must be QualityStatus")
        if not isinstance(self.reconciliation_status, ReconciliationStatus):
            raise DataContractError(
                "reconciliation_status must be ReconciliationStatus")
        if not isinstance(self.revision_semantics, RevisionSemantics):
            raise DataContractError(
                "revision_semantics must be RevisionSemantics")
        if not isinstance(self.adjustment_semantics, AdjustmentSemantics):
            raise DataContractError(
                "adjustment_semantics must be AdjustmentSemantics")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        if self.quality_status is not QualityStatus.VALID \
                and not self.reason_codes:
            raise DataContractError(
                "non-valid quality_status requires at least one reason_code")
        _json_safe(self.canonical_payload, "canonical_payload")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "fact_id": self.fact_id,
            "dataset_id": self.dataset_id,
            "canonical_key": self.canonical_key,
            "canonical_payload": self.canonical_payload,
            "canonical_source": self.canonical_source,
            "dataset_contract_revision": self.dataset_contract_revision,
            "revision_semantics": self.revision_semantics.value,
            "adjustment_semantics": self.adjustment_semantics.value,
            "source_observation_ids": list(self.source_observation_ids),
            "provenance_chain": [link.to_dict() for link in self.provenance_chain],
            "effective_at": self.effective_at,
            "published_at": self.published_at,
            "observed_at": self.observed_at,
            "revision_id": self.revision_id,
            "data_version": self.data_version,
            "quality_status": self.quality_status.value,
            "reconciliation_status": self.reconciliation_status.value,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalFact":
        _exact(data, set(cls.__dataclass_fields__), "CanonicalFact")
        return cls(
            **{
                **data,
                "source_observation_ids": tuple(
                    _json_array(data, "source_observation_ids")),
                "provenance_chain": tuple(
                    ProvenanceLink.from_dict(item)
                    for item in _json_array(data, "provenance_chain")
                ),
                "revision_semantics": RevisionSemantics(
                    data["revision_semantics"]),
                "adjustment_semantics": AdjustmentSemantics(
                    data["adjustment_semantics"]),
                "quality_status": QualityStatus(data["quality_status"]),
                "reconciliation_status": ReconciliationStatus(
                    data["reconciliation_status"]),
                "reason_codes": tuple(_json_array(data, "reason_codes")),
            }
        )


@dataclass(frozen=True)
class ReconciliationResult:
    status: ReconciliationStatus
    comparison_policy_id: str
    comparison_policy_version: str
    comparison_evidence: JSONValue
    left_observation_id: str | None
    right_observation_id: str | None
    left_value: JSONValue
    right_value: JSONValue
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReconciliationStatus):
            raise DataContractError("status must be ReconciliationStatus")
        _non_empty(self.comparison_policy_id, "comparison_policy_id")
        _non_empty(self.comparison_policy_version, "comparison_policy_version")
        _json_safe(self.comparison_evidence, "comparison_evidence")
        _optional_text(self.left_observation_id, "left_observation_id")
        _optional_text(self.right_observation_id, "right_observation_id")
        _json_safe(self.left_value, "left_value")
        _json_safe(self.right_value, "right_value")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "status": self.status.value,
            "comparison_policy_id": self.comparison_policy_id,
            "comparison_policy_version": self.comparison_policy_version,
            "comparison_evidence": self.comparison_evidence,
            "left_observation_id": self.left_observation_id,
            "right_observation_id": self.right_observation_id,
            "left_value": self.left_value,
            "right_value": self.right_value,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReconciliationResult":
        _exact(data, set(cls.__dataclass_fields__), "ReconciliationResult")
        return cls(**{
            **data,
            "status": ReconciliationStatus(data["status"]),
            "reason_codes": tuple(_json_array(data, "reason_codes")),
        })


def canonicalize_observation(
    spec: DatasetSpec,
    observation: ProviderObservation,
    *,
    fact_id: str,
    canonical_key: str,
    canonical_payload: JSONValue | object = _UNSET,
    requested_effective_at: str | None | object = _UNSET,
    as_of: str | None = None,
    reconciliation_status: ReconciliationStatus = ReconciliationStatus.UNKNOWN,
    reason_codes: tuple[str, ...] = (),
) -> CanonicalFact:
    """Create a fact only through the dataset's explicit canonical route."""
    if observation.dataset_id != spec.dataset_id:
        raise DataContractError("observation dataset does not match DatasetSpec")
    if observation.fetch_semantics is not spec.fetch_semantics \
            or observation.history_mode is not spec.history_mode:
        raise DataContractError("observation temporal contract does not match DatasetSpec")
    if observation.revision_semantics is not spec.revision_semantics:
        raise DataContractError(
            "observation revision semantics do not match DatasetSpec")
    if observation.adjustment_semantics is not spec.adjustment_semantics:
        raise DataContractError(
            "observation adjustment semantics do not match DatasetSpec")
    route = spec.canonical_route_for(
        observation.provider_id, observation.provider_endpoint)
    if spec.source_retired_at is not None and _parse_utc(
            observation.fetched_at) > _parse_utc(spec.source_retired_at):
        raise DataContractError(
            "observation was fetched after dataset source retirement")
    if route.retired_at is not None and _parse_utc(
            observation.fetched_at) > _parse_utc(route.retired_at):
        raise DataContractError(
            "observation was fetched after provider route retirement")
    effective_at = (
        observation.effective_at
        if requested_effective_at is _UNSET
        else requested_effective_at
    )
    if effective_at is not None and type(effective_at) is not str:
        raise DataContractError("requested_effective_at must be a string or null")
    _utc_timestamp(effective_at, "requested_effective_at")
    spec.assert_snapshot_history_not_fabricated(
        observation.effective_at, effective_at)
    spec.assert_as_of_allowed(observation, as_of)
    if observation.quality_status is QualityStatus.INVALID:
        raise DataContractError("invalid observations cannot become canonical facts")
    payload = observation.payload if canonical_payload is _UNSET else canonical_payload
    _json_safe(payload, "canonical_payload")
    link = ProvenanceLink(
        observation_id=observation.observation_id,
        dataset_id=observation.dataset_id,
        provider_id=observation.provider_id,
        provider_endpoint=observation.provider_endpoint,
        source_payload_hash=observation.source_payload_hash,
        normalizer_version=observation.normalizer_version,
    )
    fact = CanonicalFact(
        fact_id=fact_id,
        dataset_id=spec.dataset_id,
        canonical_key=canonical_key,
        canonical_payload=payload,
        canonical_source=observation.provider_id,
        dataset_contract_revision=spec.governance_revision_id,
        revision_semantics=spec.revision_semantics,
        adjustment_semantics=spec.adjustment_semantics,
        source_observation_ids=(observation.observation_id,),
        provenance_chain=(link,),
        effective_at=effective_at,
        published_at=observation.published_at,
        observed_at=observation.observed_at,
        revision_id=observation.revision_id,
        data_version=observation.data_version,
        quality_status=observation.quality_status,
        reconciliation_status=reconciliation_status,
        reason_codes=_dedupe(observation.reason_codes + reason_codes),
    )
    spec.validate_fact(fact)
    return fact


def _temporal_status(
    left: ProviderObservation,
    right: ProviderObservation,
) -> tuple[ReconciliationStatus | None, tuple[str, ...]]:
    if left.dataset_id != right.dataset_id:
        return (
            ReconciliationStatus.TEMPORAL_INCOMPARABLE,
            ("DATASET_ID_MISMATCH",),
        )
    comparable = False
    for field in ("effective_at", "trade_date", "report_period"):
        left_value = getattr(left, field)
        right_value = getattr(right, field)
        if left_value is None and right_value is None:
            continue
        if left_value is None or right_value is None:
            return (
                ReconciliationStatus.TEMPORAL_INCOMPARABLE,
                (f"{field.upper()}_AVAILABILITY_MISMATCH",),
            )
        comparable = True
        if left_value != right_value:
            return (
                ReconciliationStatus.TEMPORAL_INCOMPARABLE,
                (f"{field.upper()}_MISMATCH",),
            )
    for field in ("revision_id", "data_version", "adjustment_semantics"):
        if getattr(left, field) != getattr(right, field):
            return (
                ReconciliationStatus.TEMPORAL_INCOMPARABLE,
                (f"{field.upper()}_MISMATCH",),
            )
    if not comparable:
        return ReconciliationStatus.UNKNOWN, ("TEMPORAL_BASIS_UNKNOWN",)
    return None, ()


def reconcile_pair(
    left: ProviderObservation | None,
    right: ProviderObservation | None,
    *,
    comparison_policy_id: str = "exact-pairwise",
    comparison_policy_version: str = "v1",
) -> ReconciliationResult:
    """Deterministically compare two observations without selecting a winner."""
    if left is None or right is None:
        available = left if left is not None else right
        inherited = available.reason_codes if available is not None else ()
        return ReconciliationResult(
            status=ReconciliationStatus.SOURCE_UNAVAILABLE,
            comparison_policy_id=comparison_policy_id,
            comparison_policy_version=comparison_policy_version,
            comparison_evidence={"basis": "source_availability"},
            left_observation_id=left.observation_id if left else None,
            right_observation_id=right.observation_id if right else None,
            left_value=left.payload if left else None,
            right_value=right.payload if right else None,
            reason_codes=_dedupe(inherited + ("SOURCE_UNAVAILABLE",)),
        )

    inherited = _dedupe(left.reason_codes + right.reason_codes)
    temporal_status, temporal_reasons = _temporal_status(left, right)
    if temporal_status is not None:
        return ReconciliationResult(
            status=temporal_status,
            comparison_policy_id=comparison_policy_id,
            comparison_policy_version=comparison_policy_version,
            comparison_evidence={
                "basis": "temporal_and_vintage_contract",
                "left": {
                    "effective_at": left.effective_at,
                    "trade_date": left.trade_date,
                    "report_period": left.report_period,
                    "revision_id": left.revision_id,
                    "data_version": left.data_version,
                    "adjustment_semantics": left.adjustment_semantics.value,
                },
                "right": {
                    "effective_at": right.effective_at,
                    "trade_date": right.trade_date,
                    "report_period": right.report_period,
                    "revision_id": right.revision_id,
                    "data_version": right.data_version,
                    "adjustment_semantics": right.adjustment_semantics.value,
                },
            },
            left_observation_id=left.observation_id,
            right_observation_id=right.observation_id,
            left_value=left.payload,
            right_value=right.payload,
            reason_codes=_dedupe(inherited + temporal_reasons),
        )

    left_value = left.payload
    right_value = right.payload
    status: ReconciliationStatus
    reasons: tuple[str, ...]
    untrusted = {
        QualityStatus.INVALID,
        QualityStatus.UNKNOWN,
    }
    left_untrusted = left.quality_status in untrusted
    right_untrusted = right.quality_status in untrusted
    if left_untrusted or right_untrusted:
        if left_untrusted and right_untrusted:
            status = ReconciliationStatus.UNKNOWN
            reasons = ("BOTH_SOURCE_QUALITY_UNTRUSTED",)
        else:
            status = ReconciliationStatus.PARTIAL
            reasons = ("SOURCE_QUALITY_UNTRUSTED",)
    elif QualityStatus.DEGRADED in {
        left.quality_status,
        right.quality_status,
    }:
        status = ReconciliationStatus.PARTIAL
        reasons = ("SOURCE_QUALITY_DEGRADED",)
    elif left_value is None and right_value is None:
        status = ReconciliationStatus.UNKNOWN
        reasons = ("BOTH_VALUES_UNKNOWN",)
    elif left_value == right_value:
        status = ReconciliationStatus.MATCH
        reasons = ("VALUES_MATCH",)
    elif type(left_value) is dict and type(right_value) is dict:
        common = set(left_value) & set(right_value)
        if not common:
            status = ReconciliationStatus.UNKNOWN
            reasons = ("NO_COMPARABLE_FIELDS",)
        elif all(left_value[key] == right_value[key] for key in common) \
                and set(left_value) != set(right_value):
            status = ReconciliationStatus.PARTIAL
            reasons = ("COMPARABLE_FIELDS_MATCH_PARTIAL_COVERAGE",)
        else:
            status = ReconciliationStatus.MISMATCH
            reasons = ("VALUES_MISMATCH",)
    elif left_value is None or right_value is None:
        status = ReconciliationStatus.UNKNOWN
        reasons = ("VALUE_UNKNOWN",)
    else:
        status = ReconciliationStatus.MISMATCH
        reasons = ("VALUES_MISMATCH",)

    return ReconciliationResult(
        status=status,
        comparison_policy_id=comparison_policy_id,
        comparison_policy_version=comparison_policy_version,
        comparison_evidence={
            "basis": "exact_json_value",
            "left_quality": left.quality_status.value,
            "right_quality": right.quality_status.value,
        },
        left_observation_id=left.observation_id,
        right_observation_id=right.observation_id,
        left_value=left_value,
        right_value=right_value,
        reason_codes=_dedupe(inherited + reasons),
    )


def reconcile_observations(
    left: ProviderObservation | None,
    right: ProviderObservation | None,
) -> ReconciliationResult:
    """Named alias for the pairwise reconciliation contract."""
    return reconcile_pair(left, right)


def attach_reconciliation(
    fact: CanonicalFact,
    result: ReconciliationResult,
) -> CanonicalFact:
    """Attach evidence without changing the canonical source or payload."""
    if fact.quality_status is QualityStatus.INVALID:
        quality = QualityStatus.INVALID
    elif result.status is ReconciliationStatus.UNKNOWN:
        quality = QualityStatus.UNKNOWN
    elif fact.quality_status is QualityStatus.UNKNOWN:
        quality = QualityStatus.UNKNOWN
    elif result.status in {
        ReconciliationStatus.MISMATCH,
        ReconciliationStatus.PARTIAL,
        ReconciliationStatus.TEMPORAL_INCOMPARABLE,
        ReconciliationStatus.SOURCE_UNAVAILABLE,
    }:
        quality = QualityStatus.DEGRADED
    else:
        quality = fact.quality_status
    return replace(
        fact,
        quality_status=quality,
        reconciliation_status=result.status,
        reason_codes=_dedupe(fact.reason_codes + result.reason_codes),
    )
