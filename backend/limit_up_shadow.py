"""DS-L1-S1B shadow path for the EastMoney daily limit-up pool.

This module is deliberately not wired into production runtime.  Callers must
provide an explicit :class:`FactLake`; the existing BK-11 store and reads stay
authoritative for the production application.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, Mapping

import duckdb

import short_term_limit_up_pool_adapter as pool_adapter
from data_contracts import (
    AdjustmentSemantics,
    CanonicalFact,
    DataContractError,
    DatasetSpec,
    FetchSemantics,
    HistoryMode,
    ProviderObservation,
    ProviderRole,
    ProviderRoute,
    QualityStatus,
    ReconciliationResult,
    ReconciliationStatus,
    RevisionSemantics,
    TemporalSemantics,
    canonicalize_observation,
)
from fact_lake_store import (
    CANONICAL_DIRECTORY_NAME,
    FactLake,
    FactLakeCorruptedError,
    StoredCanonicalPublication,
    StoredNormalization,
    StoredObservation,
    payload_sha256,
)


DATASET_ID = "ds_limit_up_pool"
CANONICAL_PROVIDER_ID = "eastmoney_push2ex"
CANONICAL_OPERATION = "getTopicZTPool"
CANONICAL_ENDPOINT = "https://push2ex.eastmoney.com/getTopicZTPool"
VERIFIER_PROVIDER_ID = "tushare_pro"
VERIFIER_ENDPOINT = "stk_limit"
DATASET_CONTRACT_REVISION = "ds-limit-up-pool-contract-v0.1"
NORMALIZER_VERSION = "ds-limit-up-pool-normalizer-v0.1"
ARTIFACT_SCHEMA_VERSION = "ds-limit-up-pool-parquet-v0.1"
RECONCILIATION_POLICY_ID = "bk11-limit-up-count-tolerance"
RECONCILIATION_POLICY_VERSION = "v0.1"
VERIFIER_EVIDENCE_VERSION = "tushare-limit-up-count-verifier-v0.1"
MAX_RAW_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_SOURCE_POOL_ROWS = 10_000
MAX_NORMALIZED_JSON_BYTES = 4 * 1024 * 1024

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FINGERPRINT_FIELDS = (
    "operation",
    "endpoint",
    "requested_trade_date",
    "dpt",
    "page_index",
    "page_size",
    "sort",
)
_TRANSPORT_ONLY_FIELDS = frozenset({
    "http_status", "content_type", "fetched_at", "user_agent", "referer",
    "proxy_route", "retry_timing", "random_jitter", "session_state",
})
_SECRET_FIELDS = frozenset({
    "ut", "token", "authorization", "cookie", "cookies", "proxy_password",
})

_PARQUET_COLUMNS = (
    "publication_id",
    "dataset_id",
    "trade_date",
    "vintage_sequence",
    "fact_id",
    "canonical_key",
    "canonical_source",
    "source_observation_id",
    "dataset_contract_revision",
    "normalizer_version",
    "raw_payload_hash",
    "artifact_schema_version",
    "canonical_fact_json",
    "canonical_payload_json",
)


class LimitUpShadowError(RuntimeError):
    """Base class for fail-closed S1B shadow failures."""


class LimitUpCaptureError(LimitUpShadowError):
    """Raw transport evidence was missing, oversized or unsafe."""


class LimitUpNormalizationError(LimitUpShadowError):
    """The adapter output could not satisfy deterministic normalization."""


class LimitUpCanonicalAdmissionError(LimitUpShadowError):
    """A questionable or non-canonical observation was offered for admission."""


class LimitUpQueryError(LimitUpShadowError):
    """A committed artifact failed the strict DuckDB query contract."""


class LimitUpReplayError(LimitUpShadowError):
    """Base class for deterministic committed-raw replay failures."""


class LimitUpReplayNotFoundError(LimitUpReplayError):
    """The requested committed observation or raw payload does not exist."""


class LimitUpReplayUnsupportedError(LimitUpReplayError):
    """The observation route or normalizer version is not replayable here."""


class LimitUpReplayMetadataError(LimitUpReplayError):
    """Immutable observation receipt metadata is inconsistent or corrupted."""


class LimitUpReplayMismatchError(LimitUpReplayError):
    """Committed raw evidence disagrees with persisted derived evidence."""


LIMIT_UP_DATASET_SPEC = DatasetSpec(
    dataset_id=DATASET_ID,
    fetch_semantics=FetchSemantics.BY_DATE,
    history_mode=HistoryMode.BY_DATE,
    routes=(
        ProviderRoute(
            route_id="eastmoney-push2ex-getTopicZTPool",
            provider_id=CANONICAL_PROVIDER_ID,
            provider_endpoint=CANONICAL_ENDPOINT,
            role=ProviderRole.CANONICAL,
            semantic_contract_id="eastmoney-limit-up-pool-v0.1",
        ),
        ProviderRoute(
            route_id="tushare-pro-stk-limit",
            provider_id=VERIFIER_PROVIDER_ID,
            provider_endpoint=VERIFIER_ENDPOINT,
            role=ProviderRole.VERIFIER,
            semantic_contract_id="tushare-limit-up-count-v0.1",
        ),
    ),
    governance_revision_id=DATASET_CONTRACT_REVISION,
    required_temporal_fields=(TemporalSemantics.TRADE_DATE,),
    point_in_time_supported=False,
    revision_semantics=RevisionSemantics.UNKNOWN,
    adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise LimitUpNormalizationError("value is not canonical JSON") from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_request_fingerprint(metadata: Mapping[str, Any]) -> str:
    """Hash only logical request/coverage fields in deterministic order.

    Included: operation, endpoint, requested trade date, pool identity, page
    index/size and sort.  Excluded: ``ut``, headers, cookies, proxy/session
    state, retry timing, local timestamps and HTTP response metadata.
    """
    if not isinstance(metadata, Mapping):
        raise LimitUpCaptureError("request metadata must be a mapping")
    lowered = {str(key).lower() for key in metadata}
    if lowered.intersection(_SECRET_FIELDS):
        raise LimitUpCaptureError("secret-bearing request metadata is forbidden")
    logical = {field: metadata.get(field) for field in _FINGERPRINT_FIELDS}
    if any(value is None for value in logical.values()):
        raise LimitUpCaptureError("logical request fingerprint fields are incomplete")
    if (
        any(type(logical[field]) is not str for field in (
            "operation", "endpoint", "requested_trade_date", "dpt", "sort"
        ))
        or type(logical["page_index"]) is not int
        or type(logical["page_size"]) is not int
        or logical != {
        "operation": CANONICAL_OPERATION,
        "endpoint": CANONICAL_ENDPOINT,
        "requested_trade_date": logical["requested_trade_date"],
        "dpt": "wz.ztzt",
        "page_index": 0,
        "page_size": 10_000,
        "sort": "fbt:asc",
        }
    ):
        raise LimitUpCaptureError("request shape does not match the dataset contract")
    trade_date = logical["requested_trade_date"]
    if type(trade_date) is not str or _TRADE_DATE_RE.fullmatch(trade_date) is None:
        raise LimitUpCaptureError("requested trade date is not canonical")
    encoded = _canonical_json(logical)
    return f"sha256:{_sha256_text(encoded)}"


@dataclass(frozen=True)
class RawResponseCapture:
    capture_event_id: str
    raw_bytes: bytes
    metadata: dict[str, Any]
    request_fingerprint: str
    source_payload_hash: str
    content_type: str
    fetched_at: str


class RawCaptureBuffer:
    """One-shot, bounded exact-byte capture used by the optional callback."""

    def __init__(self, failure_hook: Callable[[str], None] | None = None) -> None:
        self.capture: RawResponseCapture | None = None
        self._failure_hook = failure_hook

    def __call__(self, raw_bytes: bytes, metadata: dict[str, Any]) -> None:
        if self.capture is not None:
            raise LimitUpCaptureError("one logical request produced multiple responses")
        if type(raw_bytes) is not bytes:
            raise LimitUpCaptureError("raw provider response must be exact bytes")
        if len(raw_bytes) > MAX_RAW_PAYLOAD_BYTES:
            raise LimitUpCaptureError("raw provider response exceeds the S1B size limit")
        fingerprint = build_request_fingerprint(metadata)
        content_type = metadata.get("content_type") or "application/octet-stream"
        if type(content_type) is not str or not content_type.strip() \
                or len(content_type) > 256 \
                or "\r" in content_type or "\n" in content_type:
            raise LimitUpCaptureError("response content type is unsafe")
        fetched_at = metadata.get("fetched_at")
        if type(fetched_at) is not str or not fetched_at.endswith("Z"):
            raise LimitUpCaptureError("capture fetched_at must be canonical UTC")
        safe_metadata = {
            key: metadata.get(key)
            for key in _FINGERPRINT_FIELDS + (
                "http_status", "content_type", "fetched_at",
            )
        }
        self.capture = RawResponseCapture(
            capture_event_id=f"capture-{uuid.uuid4().hex}",
            raw_bytes=raw_bytes,
            metadata=safe_metadata,
            request_fingerprint=fingerprint,
            source_payload_hash=payload_sha256(raw_bytes),
            content_type=content_type.strip(),
            fetched_at=fetched_at,
        )
        if self._failure_hook is not None:
            self._failure_hook("after_provider_bytes_captured")


def _strict_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise LimitUpNormalizationError(f"{field} must be an int >= {minimum}")
    return value


def normalize_adapter_snapshot(
    snapshot: Mapping[str, Any],
    *,
    source_observation_id: str,
) -> dict[str, Any]:
    """Project the production adapter contract into deterministic evidence."""
    if not isinstance(snapshot, Mapping):
        raise LimitUpNormalizationError("adapter snapshot must be a mapping")
    required = {
        "schema_version", "source_id", "endpoint", "requested_trade_date",
        "status", "reason_codes", "rows", "transport_success", "parse_success",
        "required_field_present", "data_array_present", "trade_date_match",
        "row_count", "legal_zero", "upstream_null", "unexplained_empty",
        "coverage_warning", "target_universe_empty_after_filter",
        "source_pool_row_count", "http_status", "error_class",
        "excluded_universe_count", "invalid_row_count", "duplicate_code_count",
    }
    missing = sorted(required - set(snapshot))
    if missing:
        raise LimitUpNormalizationError(f"adapter snapshot fields missing: {missing}")
    if snapshot["schema_version"] != pool_adapter.SCHEMA_VERSION:
        raise LimitUpNormalizationError("adapter schema version is incompatible")
    if snapshot["source_id"] != "eastmoney_getTopicZTPool" \
            or snapshot["endpoint"] != CANONICAL_OPERATION:
        raise LimitUpNormalizationError("adapter source identity drifted")
    trade_date = snapshot["requested_trade_date"]
    if type(trade_date) is not str or _TRADE_DATE_RE.fullmatch(trade_date) is None:
        raise LimitUpNormalizationError("adapter trade date is invalid")
    rows_value = snapshot["rows"]
    if type(rows_value) is not list:
        raise LimitUpNormalizationError("adapter rows must be a list")
    source_count = _strict_int(
        snapshot["source_pool_row_count"], "source_pool_row_count"
    )
    if source_count > MAX_SOURCE_POOL_ROWS:
        raise LimitUpNormalizationError("source pool exceeds the request coverage limit")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows_value:
        if type(row) is not dict or set(row) != {"stock_code", "lbc"}:
            raise LimitUpNormalizationError("normalized row schema is invalid")
        code = row["stock_code"]
        lbc = row["lbc"]
        if type(code) is not str or re.fullmatch(r"\d{6}", code) is None:
            raise LimitUpNormalizationError("normalized stock code is invalid")
        if code in seen:
            raise LimitUpNormalizationError("normalized rows contain a duplicate code")
        if type(lbc) is not int or lbc <= 0:
            raise LimitUpNormalizationError("normalized lbc is invalid")
        seen.add(code)
        rows.append({"stock_code": code, "lbc": lbc})
    rows.sort(key=lambda row: row["stock_code"])
    if _strict_int(snapshot["row_count"], "row_count") != len(rows):
        raise LimitUpNormalizationError("adapter row_count does not match rows")
    reason_codes = snapshot["reason_codes"]
    if type(reason_codes) is not list \
            or any(type(code) is not str or not code for code in reason_codes) \
            or len(reason_codes) != len(set(reason_codes)):
        raise LimitUpNormalizationError("adapter reason_codes are invalid")

    status = snapshot["status"]
    error_class = snapshot["error_class"]
    http_status = snapshot["http_status"]
    if status not in {"normal", "partial", "unavailable"}:
        raise LimitUpNormalizationError("adapter status is invalid")
    if type(error_class) is not str or not error_class:
        raise LimitUpNormalizationError("adapter error_class is invalid")
    if http_status is not None and (
        type(http_status) is not int or http_status < 100 or http_status > 599
    ):
        raise LimitUpNormalizationError("adapter http_status is invalid")

    normalized = {
        "schema_version": snapshot["schema_version"],
        "dataset_id": DATASET_ID,
        "trade_date": trade_date,
        "rows": rows,
        "row_count": len(rows),
        "source_pool_row_count": source_count,
        "excluded_universe_count": _strict_int(
            snapshot["excluded_universe_count"], "excluded_universe_count"),
        "invalid_row_count": _strict_int(
            snapshot["invalid_row_count"], "invalid_row_count"),
        "duplicate_code_count": _strict_int(
            snapshot["duplicate_code_count"], "duplicate_code_count"),
        "target_universe_empty_after_filter":
            snapshot["target_universe_empty_after_filter"],
        "trade_date_match": snapshot["trade_date_match"],
        "status": status,
        "reason_codes": list(reason_codes),
        "transport_success": snapshot["transport_success"],
        "parse_success": snapshot["parse_success"],
        "required_field_present": snapshot["required_field_present"],
        "data_array_present": snapshot["data_array_present"],
        "legal_zero": snapshot["legal_zero"],
        "upstream_null": snapshot["upstream_null"],
        "unexplained_empty": snapshot["unexplained_empty"],
        "coverage_warning": snapshot["coverage_warning"],
        "http_status": http_status,
        "error_class": error_class,
        "normalizer_version": NORMALIZER_VERSION,
        "source_observation_id": source_observation_id,
    }
    if normalized["trade_date_match"] not in (True, False, None):
        raise LimitUpNormalizationError("trade_date_match must be bool or null")
    for field in (
        "transport_success", "parse_success", "required_field_present",
        "data_array_present", "legal_zero", "upstream_null",
        "unexplained_empty", "coverage_warning",
        "target_universe_empty_after_filter",
    ):
        if type(normalized[field]) is not bool:
            raise LimitUpNormalizationError(f"{field} must be bool")
    accounted = (
        normalized["row_count"]
        + normalized["excluded_universe_count"]
        + normalized["invalid_row_count"]
        + normalized["duplicate_code_count"]
    )
    if accounted != normalized["source_pool_row_count"]:
        raise LimitUpNormalizationError(
            "adapter source-pool accounting identity does not hold"
        )
    encoded = _canonical_json(normalized).encode("utf-8")
    if len(encoded) > MAX_NORMALIZED_JSON_BYTES:
        raise LimitUpNormalizationError("normalized representation is too large")
    return normalized


@dataclass(frozen=True)
class ReplayedLimitUpNormalization:
    """Normalization re-derived only from committed raw evidence and receipt."""

    observation: StoredObservation
    adapter_snapshot: dict[str, Any]
    normalized_payload: dict[str, Any]
    normalized_sha256: str
    canonical_admissible: bool


@dataclass(frozen=True)
class LimitUpReplayVerification:
    """Comparison result; verification itself never persists or repairs data."""

    status: Literal["ABSENT", "MATCH"]
    replay: ReplayedLimitUpNormalization
    stored_normalization: StoredNormalization | None


def _observation_id(capture: RawResponseCapture) -> str:
    if type(capture.capture_event_id) is not str or re.fullmatch(
        r"capture-[0-9a-f]{32}", capture.capture_event_id
    ) is None:
        raise LimitUpCaptureError("capture event identity is invalid")
    identity = _canonical_json({
        "dataset_id": DATASET_ID,
        "provider_id": CANONICAL_PROVIDER_ID,
        "provider_endpoint": CANONICAL_ENDPOINT,
        "capture_event_id": capture.capture_event_id,
    })
    return f"obs-{_sha256_text(identity)}"


def _is_canonical_admissible(normalized: Mapping[str, Any]) -> bool:
    try:
        row_count = normalized["row_count"]
        source_count = normalized["source_pool_row_count"]
        excluded = normalized["excluded_universe_count"]
        invalid = normalized["invalid_row_count"]
        duplicates = normalized["duplicate_code_count"]
        empty_after_filter = normalized["target_universe_empty_after_filter"]
        empty_is_explained = (
            row_count > 0
            or (
                row_count == 0
                and source_count > 0
                and empty_after_filter is True
                and excluded == source_count
            )
        )
        return (
            type(row_count) is int
            and type(source_count) is int
            and type(excluded) is int
            and type(invalid) is int
            and type(duplicates) is int
            and row_count + excluded + invalid + duplicates == source_count
            and normalized["schema_version"] == pool_adapter.SCHEMA_VERSION
            and normalized["status"] == "normal"
            and normalized["transport_success"] is True
            and normalized["parse_success"] is True
            and normalized["required_field_present"] is True
            and normalized["data_array_present"] is True
            and normalized["trade_date_match"] is True
            and normalized["legal_zero"] is False
            and normalized["upstream_null"] is False
            and normalized["unexplained_empty"] is False
            and normalized["coverage_warning"] is False
            and invalid == 0
            and duplicates == 0
            and normalized["reason_codes"] == []
            and normalized["error_class"] == "NONE"
            and type(normalized["http_status"]) is int
            and 200 <= normalized["http_status"] < 300
            and empty_is_explained
        )
    except (KeyError, TypeError, ValueError):
        return False


def build_provider_observation(
    capture: RawResponseCapture,
    snapshot: Mapping[str, Any],
) -> ProviderObservation:
    observation_id = _observation_id(capture)
    # Persist only bounded, JSON-safe classification metadata here.  Provider
    # bytes become durable before row-level normalization is attempted.
    reason_value = snapshot.get("reason_codes") if isinstance(snapshot, Mapping) else None
    reasons = (
        tuple(reason_value)
        if type(reason_value) is list
        and all(type(code) is str and code for code in reason_value)
        and len(reason_value) == len(set(reason_value))
        else ("ADAPTER_CONTRACT_INVALID",)
    )
    requested_trade_date = (
        snapshot.get("requested_trade_date")
        if isinstance(snapshot, Mapping) else None
    )
    if type(requested_trade_date) is not str \
            or _TRADE_DATE_RE.fullmatch(requested_trade_date) is None:
        requested_trade_date = None
    trade_date_match = (
        snapshot.get("trade_date_match")
        if isinstance(snapshot, Mapping) else None
    )
    admitted = isinstance(snapshot, Mapping) and _is_canonical_admissible(snapshot)
    if not admitted and not reasons:
        reasons = ("CANONICAL_ADMISSION_REJECTED",)
    raw_observation_metadata = {
        "capture_event_id": capture.capture_event_id,
        "request": {
            field: capture.metadata[field]
            for field in _FINGERPRINT_FIELDS
        },
        "response": {
            "http_status": capture.metadata["http_status"],
            "content_type": capture.content_type,
            "byte_length": len(capture.raw_bytes),
        },
        "adapter_outcome": {
            "status": snapshot.get("status") if isinstance(snapshot, Mapping) else None,
            "reason_codes": list(reasons),
            "transport_success": snapshot.get("transport_success")
                if isinstance(snapshot, Mapping) else None,
            "parse_success": snapshot.get("parse_success")
                if isinstance(snapshot, Mapping) else None,
            "required_field_present": snapshot.get("required_field_present")
                if isinstance(snapshot, Mapping) else None,
            "data_array_present": snapshot.get("data_array_present")
                if isinstance(snapshot, Mapping) else None,
            "trade_date_match": trade_date_match,
            "requested_trade_date": requested_trade_date,
        },
        "dataset_contract_revision": DATASET_CONTRACT_REVISION,
    }
    # A malformed adapter scalar must not turn raw evidence persistence into an
    # unbounded/arbitrary-object serialization path.
    try:
        _canonical_json(raw_observation_metadata)
    except LimitUpNormalizationError:
        raw_observation_metadata["adapter_outcome"] = {
            "status": "invalid",
            "reason_codes": ["ADAPTER_CONTRACT_INVALID"],
            "transport_success": None,
            "parse_success": None,
            "required_field_present": None,
            "data_array_present": None,
            "trade_date_match": None,
            "requested_trade_date": None,
        }
        admitted = False
        reasons = ("ADAPTER_CONTRACT_INVALID",)
    return ProviderObservation(
        observation_id=observation_id,
        dataset_id=DATASET_ID,
        provider_id=CANONICAL_PROVIDER_ID,
        provider_endpoint=CANONICAL_ENDPOINT,
        provider_symbol=f"{CANONICAL_OPERATION}:{requested_trade_date or 'unknown'}",
        request_fingerprint=capture.request_fingerprint,
        source_payload_hash=capture.source_payload_hash,
        normalizer_version=NORMALIZER_VERSION,
        payload=raw_observation_metadata,
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        fetched_at=capture.fetched_at,
        trade_date=(requested_trade_date if trade_date_match is True else None),
        revision_semantics=RevisionSemantics.UNKNOWN,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
        quality_status=(QualityStatus.VALID if admitted else QualityStatus.INVALID),
        reason_codes=reasons,
    )


_RECEIPT_FIELDS = frozenset({
    "capture_event_id",
    "request",
    "response",
    "adapter_outcome",
    "dataset_contract_revision",
})
_RESPONSE_RECEIPT_FIELDS = frozenset({
    "http_status",
    "content_type",
    "byte_length",
})
_ADAPTER_OUTCOME_FIELDS = frozenset({
    "status",
    "reason_codes",
    "transport_success",
    "parse_success",
    "required_field_present",
    "data_array_present",
    "trade_date_match",
    "requested_trade_date",
})


def _exact_receipt_mapping(
    value: Any,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LimitUpReplayMetadataError(f"{name} receipt shape is invalid")
    return value


def replay_normalization(
    lake: FactLake,
    observation_id: str,
) -> ReplayedLimitUpNormalization:
    """Re-derive normalization without reading persisted normalization JSON.

    The only semantic inputs are a committed ProviderObservation receipt and
    its exact content-addressed provider bytes.  The stored normalization is
    deliberately not read here; it is the value verified by
    :func:`verify_normalization_replay`.
    """
    if type(observation_id) is not str or not observation_id:
        raise ValueError("observation_id must be non-empty")
    stored = lake.get_observation(observation_id)
    if stored is None:
        raise LimitUpReplayNotFoundError(
            "committed limit-up observation does not exist"
        )
    observation = stored.observation
    if (
        observation.dataset_id != DATASET_ID
        or observation.provider_id != CANONICAL_PROVIDER_ID
        or observation.provider_endpoint != CANONICAL_ENDPOINT
    ):
        raise LimitUpReplayUnsupportedError(
            "only the canonical EastMoney limit-up route is replayable"
        )
    if observation.normalizer_version != NORMALIZER_VERSION:
        raise LimitUpReplayUnsupportedError(
            "observation normalizer version is not replayable"
        )
    if (
        observation.fetch_semantics is not FetchSemantics.BY_DATE
        or observation.history_mode is not HistoryMode.BY_DATE
    ):
        raise LimitUpReplayMetadataError(
            "observation temporal contract drifted"
        )

    receipt = _exact_receipt_mapping(
        observation.payload,
        _RECEIPT_FIELDS,
        "observation",
    )
    if receipt["dataset_contract_revision"] != DATASET_CONTRACT_REVISION:
        raise LimitUpReplayMetadataError(
            "observation dataset contract revision drifted"
        )
    capture_event_id = receipt["capture_event_id"]
    if type(capture_event_id) is not str or re.fullmatch(
        r"capture-[0-9a-f]{32}", capture_event_id
    ) is None:
        raise LimitUpReplayMetadataError("capture event identity is invalid")
    request = _exact_receipt_mapping(
        receipt["request"],
        frozenset(_FINGERPRINT_FIELDS),
        "request",
    )
    response = _exact_receipt_mapping(
        receipt["response"],
        _RESPONSE_RECEIPT_FIELDS,
        "response",
    )
    _exact_receipt_mapping(
        receipt["adapter_outcome"],
        _ADAPTER_OUTCOME_FIELDS,
        "adapter outcome",
    )
    try:
        request_fingerprint = build_request_fingerprint(dict(request))
    except LimitUpCaptureError as exc:
        raise LimitUpReplayMetadataError(
            "request receipt does not satisfy the dataset contract"
        ) from exc
    if request_fingerprint != observation.request_fingerprint:
        raise LimitUpReplayMetadataError("request fingerprint drifted")
    content_type = response["content_type"]
    if type(content_type) is not str or content_type != stored.content_type:
        raise LimitUpReplayMetadataError("response content type drifted")
    byte_length = response["byte_length"]
    if type(byte_length) is not int or byte_length < 0:
        raise LimitUpReplayMetadataError("response byte length is invalid")

    raw_bytes = lake.read_payload(observation_id)
    if raw_bytes is None:
        raise LimitUpReplayNotFoundError("committed provider bytes are missing")
    if len(raw_bytes) != byte_length:
        raise LimitUpReplayMetadataError("response byte length drifted")
    if payload_sha256(raw_bytes).lower() != observation.source_payload_hash.lower():
        raise LimitUpReplayMismatchError("committed raw payload hash drifted")

    requested_trade_date = request["requested_trade_date"]
    snapshot = pool_adapter.interpret_limit_up_pool_response_bytes(
        raw_bytes,
        requested_trade_date=requested_trade_date,
        http_status=response["http_status"],
        observed_at=observation.fetched_at,
    )
    replay_capture = RawResponseCapture(
        capture_event_id=capture_event_id,
        raw_bytes=raw_bytes,
        metadata={
            **dict(request),
            "http_status": response["http_status"],
            "content_type": content_type,
            "fetched_at": observation.fetched_at,
        },
        request_fingerprint=request_fingerprint,
        source_payload_hash=payload_sha256(raw_bytes),
        content_type=content_type,
        fetched_at=observation.fetched_at,
    )
    expected_observation = build_provider_observation(replay_capture, snapshot)
    if expected_observation.to_dict() != observation.to_dict():
        raise LimitUpReplayMetadataError(
            "persisted observation classification disagrees with raw replay"
        )
    normalized = normalize_adapter_snapshot(
        snapshot,
        source_observation_id=observation_id,
    )
    normalized_sha256 = payload_sha256(
        _canonical_json(normalized).encode("utf-8")
    )
    return ReplayedLimitUpNormalization(
        observation=stored,
        adapter_snapshot=snapshot,
        normalized_payload=normalized,
        normalized_sha256=normalized_sha256,
        canonical_admissible=_is_canonical_admissible(normalized),
    )


def verify_normalization_replay(
    lake: FactLake,
    observation_id: str,
) -> LimitUpReplayVerification:
    """Compare replay with stored normalization without mutating history."""
    replay = replay_normalization(lake, observation_id)
    stored = lake.get_normalization(observation_id)
    if stored is None:
        return LimitUpReplayVerification("ABSENT", replay, None)
    if (
        stored.normalizer_version != NORMALIZER_VERSION
        or stored.normalized_sha256.lower()
            != replay.normalized_sha256.lower()
        or _canonical_json(stored.normalized_payload)
            != _canonical_json(replay.normalized_payload)
    ):
        raise LimitUpReplayMismatchError(
            "persisted normalization disagrees with committed raw replay"
        )
    return LimitUpReplayVerification("MATCH", replay, stored)


def persist_replayed_normalization(
    lake: FactLake,
    observation_id: str,
) -> StoredNormalization:
    """Explicitly persist a freshly replayed result; verification stays pure."""
    replay = replay_normalization(lake, observation_id)
    return lake.store_normalization(
        observation_id,
        replay.normalized_payload,
        normalizer_version=NORMALIZER_VERSION,
    )


def persist_raw_observation(
    lake: FactLake,
    capture: RawResponseCapture,
    snapshot: Mapping[str, Any],
) -> StoredObservation:
    candidate = build_provider_observation(capture, snapshot)
    # The Fact Lake owns full immutable replay validation.  A single capture
    # event reuses its event token and is idempotent only when the entire
    # observation receipt and exact bytes agree.  A new provider fetch receives
    # a new event token even if its request fingerprint and content hash match.
    return lake.store_observation(
        candidate,
        capture.raw_bytes,
        capture.content_type,
    ).stored


def persist_normalization(
    lake: FactLake,
    observation: StoredObservation,
    snapshot: Mapping[str, Any],
) -> StoredNormalization:
    normalized = normalize_adapter_snapshot(
        snapshot,
        source_observation_id=observation.observation.observation_id,
    )
    return lake.store_normalization(
        observation.observation.observation_id,
        normalized,
        normalizer_version=NORMALIZER_VERSION,
    )


def build_canonical_fact(
    observation: ProviderObservation,
    normalization: StoredNormalization,
) -> CanonicalFact:
    if not isinstance(normalization, StoredNormalization):
        raise TypeError("normalization must be persisted StoredNormalization")
    if normalization.source_observation_id != observation.observation_id \
            or normalization.normalizer_version != observation.normalizer_version:
        raise LimitUpCanonicalAdmissionError(
            "normalization is not bound to the source observation"
        )
    normalized = normalization.normalized_payload
    if not isinstance(normalized, Mapping):
        raise LimitUpCanonicalAdmissionError("normalized evidence must be an object")
    if observation.provider_id != CANONICAL_PROVIDER_ID \
            or observation.provider_endpoint != CANONICAL_ENDPOINT:
        raise LimitUpCanonicalAdmissionError(
            "only the configured EastMoney route may become canonical"
        )
    if observation.quality_status is not QualityStatus.VALID \
            or not _is_canonical_admissible(normalized):
        raise LimitUpCanonicalAdmissionError(
            "questionable provider evidence cannot become canonical"
        )
    trade_date = observation.trade_date
    if trade_date is None:
        raise LimitUpCanonicalAdmissionError(
            "canonical limit-up pool requires a bound trade_date"
        )
    canonical_key = f"{DATASET_ID}:{trade_date}"
    fact_identity = _canonical_json({
        "dataset_id": DATASET_ID,
        "canonical_key": canonical_key,
        "source_observation_id": observation.observation_id,
        "canonical_payload": normalized,
        "dataset_contract_revision": DATASET_CONTRACT_REVISION,
    })
    return canonicalize_observation(
        LIMIT_UP_DATASET_SPEC,
        observation,
        fact_id=f"fact-{_sha256_text(fact_identity)}",
        canonical_key=canonical_key,
        canonical_payload=dict(normalized),
        as_of=None,
        reconciliation_status=ReconciliationStatus.UNKNOWN,
    )


_PUBLICATION_EVENT_ONLY_PAYLOAD_FIELDS = frozenset({
    "http_status",
    "source_observation_id",
})


def _canonical_state_document(fact: CanonicalFact) -> dict[str, Any]:
    """Remove receipt/event identity while retaining canonical evidence state."""
    document = fact.to_dict()
    document.pop("fact_id", None)
    document.pop("source_observation_ids", None)
    provenance = document.get("provenance_chain")
    if type(provenance) is list:
        document["provenance_chain"] = [
            {
                key: value
                for key, value in link.items()
                if key != "observation_id"
            }
            for link in provenance
        ]
    payload = document.get("canonical_payload")
    if type(payload) is dict:
        document["canonical_payload"] = {
            key: value
            for key, value in payload.items()
            if key not in _PUBLICATION_EVENT_ONLY_PAYLOAD_FIELDS
        }
    return document


def _same_canonical_state(left: CanonicalFact, right: CanonicalFact) -> bool:
    return _canonical_json(_canonical_state_document(left)) == _canonical_json(
        _canonical_state_document(right)
    )


def _publication_identity(fact: CanonicalFact) -> tuple[str, str]:
    identity = _canonical_json({
        "canonical_state": _canonical_state_document(fact),
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
    })
    digest = _sha256_text(identity)
    return f"publication-{digest}", digest


def _write_fact_parquet(
    candidate: Path,
    *,
    publication_id: str,
    vintage_sequence: int,
    fact: CanonicalFact,
) -> None:
    fact_json = _canonical_json(fact.to_dict())
    payload_json = _canonical_json(fact.canonical_payload)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE canonical_artifact(
                publication_id VARCHAR NOT NULL,
                dataset_id VARCHAR NOT NULL,
                trade_date VARCHAR NOT NULL,
                vintage_sequence BIGINT NOT NULL,
                fact_id VARCHAR NOT NULL,
                canonical_key VARCHAR NOT NULL,
                canonical_source VARCHAR NOT NULL,
                source_observation_id VARCHAR NOT NULL,
                dataset_contract_revision VARCHAR NOT NULL,
                normalizer_version VARCHAR NOT NULL,
                raw_payload_hash VARCHAR NOT NULL,
                artifact_schema_version VARCHAR NOT NULL,
                canonical_fact_json VARCHAR NOT NULL,
                canonical_payload_json VARCHAR NOT NULL
            )
            """
        )
        provenance = fact.provenance_chain[0]
        connection.execute(
            "INSERT INTO canonical_artifact VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                publication_id,
                fact.dataset_id,
                fact.trade_date,
                vintage_sequence,
                fact.fact_id,
                fact.canonical_key,
                fact.canonical_source,
                fact.source_observation_ids[0],
                fact.dataset_contract_revision,
                provenance.normalizer_version,
                provenance.source_payload_hash,
                ARTIFACT_SCHEMA_VERSION,
                fact_json,
                payload_json,
            ),
        )
        quoted = str(candidate).replace("'", "''")
        connection.execute(
            f"COPY canonical_artifact TO '{quoted}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()


def publish_canonical_fact(
    lake: FactLake,
    fact: CanonicalFact,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> StoredCanonicalPublication:
    """Publish one fact artifact, then atomically make its manifest visible."""
    if len(fact.source_observation_ids) != 1:
        raise LimitUpCanonicalAdmissionError(
            "limit-up publication requires exactly one raw observation"
        )
    try:
        replay_verification = verify_normalization_replay(
            lake,
            fact.source_observation_ids[0],
        )
    except LimitUpReplayError as exc:
        raise LimitUpCanonicalAdmissionError(
            "canonical publication requires successful committed-raw replay"
        ) from exc
    if (
        replay_verification.status != "MATCH"
        or not replay_verification.replay.canonical_admissible
        or _canonical_json(fact.canonical_payload)
            != _canonical_json(replay_verification.replay.normalized_payload)
    ):
        raise LimitUpCanonicalAdmissionError(
            "canonical fact is not verified by committed raw evidence"
        )
    LIMIT_UP_DATASET_SPEC.validate_fact(fact)
    if fact.canonical_source != CANONICAL_PROVIDER_ID:
        raise LimitUpCanonicalAdmissionError("verifier/fallback cannot publish canonical")
    publication_id, digest = _publication_identity(fact)
    trade_date = fact.trade_date
    if trade_date is None:
        raise LimitUpCanonicalAdmissionError("publication requires trade_date")
    artifact_relpath = PurePosixPath(
        CANONICAL_DIRECTORY_NAME,
        _sha256_text(DATASET_ID),
        trade_date,
        f"{digest}.parquet",
    ).as_posix()
    provenance = fact.provenance_chain[0]
    staged = lake.stage_canonical_publication(
        fact,
        publication_id=publication_id,
        source_observation_id=fact.source_observation_ids[0],
        normalizer_version=provenance.normalizer_version,
        raw_payload_hash=provenance.source_payload_hash,
        artifact_schema_version=ARTIFACT_SCHEMA_VERSION,
        artifact_relpath=artifact_relpath,
        equivalent_replay=_same_canonical_state,
    )
    if staged.stored.commit_state == "COMMITTED":
        return staged.stored
    if failure_hook is not None:
        failure_hook("before_parquet_creation")

    def writer(candidate: Path) -> None:
        if failure_hook is not None:
            failure_hook("during_parquet_write")
        _write_fact_parquet(
            candidate,
            publication_id=publication_id,
            vintage_sequence=staged.stored.vintage_sequence,
            # A prior capture event may already own the same canonical state.
            # Always materialize the authoritative staged fact so concurrent
            # equivalent events cannot disagree about artifact contents.
            fact=staged.stored.fact,
        )

    artifact_hash = lake.publish_canonical_artifact(artifact_relpath, writer)
    if failure_hook is not None:
        failure_hook("after_parquet_durable")
    # Hash equality alone is insufficient: an existing orphan could have the
    # expected physical identity but an incompatible schema or wrong fact.
    # Validate through the same strict DuckDB contract before manifest commit.
    _read_publication_with_duckdb(
        lake,
        replace(
            staged.stored,
            artifact_sha256=artifact_hash,
            commit_state="COMMITTED",
        ),
    )
    if failure_hook is not None:
        failure_hook("before_publication_commit")
    committed = lake.commit_canonical_publication(publication_id, artifact_hash)
    if failure_hook is not None:
        failure_hook("after_publication_commit")
    return committed


def unknown_verifier_reconciliation(
    observation: ProviderObservation,
    normalized: Mapping[str, Any],
) -> ReconciliationResult:
    return ReconciliationResult(
        dataset_id=DATASET_ID,
        status=ReconciliationStatus.UNKNOWN,
        comparison_policy_id=RECONCILIATION_POLICY_ID,
        comparison_policy_version=RECONCILIATION_POLICY_VERSION,
        comparison_evidence={
            "basis": "verifier_observation_absent",
            "scope": "count_only",
        },
        left_observation_id=observation.observation_id,
        right_observation_id=None,
        left_value={"row_count": normalized["row_count"]},
        right_value=None,
        reason_codes=("VERIFIER_OBSERVATION_ABSENT",),
    )


def _committed_verifier_count(
    lake: FactLake,
    observation: ProviderObservation,
) -> int | None:
    """Read the count from the exact committed verifier evidence bytes."""
    if observation.normalizer_version != VERIFIER_EVIDENCE_VERSION:
        return None
    raw = lake.read_payload(observation.observation_id)
    if raw is None:
        return None
    try:
        evidence = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(evidence) is not dict or set(evidence) != {
        "limit_up_count",
        "trade_date",
    }:
        return None
    count = evidence["limit_up_count"]
    trade_date = evidence["trade_date"]
    if type(count) is not int or count < 0:
        return None
    if type(trade_date) is not str or trade_date != observation.trade_date:
        return None
    if not isinstance(observation.payload, Mapping) or _canonical_json(
        observation.payload
    ) != _canonical_json(evidence):
        return None
    return count


def reconcile_limit_up_counts(
    lake: FactLake,
    eastmoney: ProviderObservation,
    tushare: ProviderObservation,
) -> ReconciliationResult:
    """Compare count only; never select or change the canonical provider."""
    if eastmoney.dataset_id != DATASET_ID or tushare.dataset_id != DATASET_ID:
        raise DataContractError("reconciliation observations belong to another dataset")
    for observation in (eastmoney, tushare):
        persisted = lake.get_observation(observation.observation_id)
        if persisted is None or persisted.observation.to_dict() != observation.to_dict():
            raise DataContractError(
                "reconciliation requires exact committed raw observations"
            )
    LIMIT_UP_DATASET_SPEC.canonical_route_for(
        eastmoney.provider_id,
        eastmoney.provider_endpoint,
    )
    verifier_route = LIMIT_UP_DATASET_SPEC.route_for(
        tushare.provider_id,
        tushare.provider_endpoint,
    )
    if verifier_route.role is not ProviderRole.VERIFIER:
        raise DataContractError("right observation is not the configured verifier")
    replay_verification = verify_normalization_replay(
        lake,
        eastmoney.observation_id,
    )
    normalization = replay_verification.stored_normalization
    left = (
        replay_verification.replay.normalized_payload.get("row_count")
        if replay_verification.status == "MATCH"
        and normalization is not None
        else None
    )
    right: int | None = None
    tolerance: float | None = None
    absolute_delta: int | None = None
    if tushare.quality_status is not QualityStatus.VALID:
        status = ReconciliationStatus.UNKNOWN
        reasons = ("VERIFIER_QUALITY_UNTRUSTED",)
    elif eastmoney.trade_date != tushare.trade_date:
        status = ReconciliationStatus.TEMPORAL_INCOMPARABLE
        reasons = ("TRADE_DATE_MISMATCH",)
    else:
        right = _committed_verifier_count(lake, tushare)
        if type(left) is not int or left < 0 or right is None:
            status = ReconciliationStatus.UNKNOWN
            reasons = ("COUNT_EVIDENCE_UNAVAILABLE",)
        else:
            absolute_delta = abs(right - left)
            tolerance = max(3, left * 0.05)
            if absolute_delta <= tolerance:
                status = ReconciliationStatus.MATCH
                reasons = ("COUNT_MATCH",)
            else:
                status = ReconciliationStatus.MISMATCH
                reasons = ("COUNT_MISMATCH",)
    comparison_evidence: dict[str, Any] = {
        "basis": "count_only",
        "left_evidence": "committed_raw_replay.verified_row_count",
        "right_evidence": "committed_verifier_raw_json.limit_up_count",
    }
    if tolerance is not None and absolute_delta is not None:
        comparison_evidence.update({
            "absolute_delta": absolute_delta,
            "tolerance": tolerance,
        })
    return ReconciliationResult(
        dataset_id=DATASET_ID,
        status=status,
        comparison_policy_id=RECONCILIATION_POLICY_ID,
        comparison_policy_version=RECONCILIATION_POLICY_VERSION,
        comparison_evidence=comparison_evidence,
        left_observation_id=eastmoney.observation_id,
        right_observation_id=tushare.observation_id,
        left_value=({"row_count": left} if type(left) is int else None),
        right_value=({"limit_up_count": right} if type(right) is int else None),
        reason_codes=reasons,
    )


def _append_reconciliation_once(
    lake: FactLake,
    result: ReconciliationResult,
) -> None:
    if any(item.result.to_dict() == result.to_dict()
           for item in lake.list_reconciliations(dataset_id=DATASET_ID)):
        return
    lake.append_reconciliation(result)


@dataclass(frozen=True)
class ShadowRunResult:
    snapshot: dict[str, Any]
    observation: StoredObservation | None
    fact: CanonicalFact | None
    publication: StoredCanonicalPublication | None
    reconciliation: ReconciliationResult | None


def run_limit_up_shadow(
    requested_trade_date: str,
    lake: FactLake,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> ShadowRunResult:
    """Explicitly run the shadow path; production never calls this by default."""
    capture_buffer = RawCaptureBuffer(failure_hook=failure_hook)
    snapshot = pool_adapter.fetch_limit_up_pool_snapshot(
        requested_trade_date,
        raw_response_sink=capture_buffer,
    )
    capture = capture_buffer.capture
    if capture is None:
        # Transport failed before any provider response existed.  Do not invent
        # an EastMoney observation or issue an extra request.
        return ShadowRunResult(snapshot, None, None, None, None)
    observation = persist_raw_observation(lake, capture, snapshot)
    if failure_hook is not None:
        failure_hook("after_raw_observation_committed")
        failure_hook("before_normalization")
    normalization = persist_replayed_normalization(
        lake,
        observation.observation.observation_id,
    )
    if observation.observation.quality_status is not QualityStatus.VALID:
        return ShadowRunResult(snapshot, observation, None, None, None)
    fact = build_canonical_fact(observation.observation, normalization)
    publication = publish_canonical_fact(
        lake,
        fact,
        failure_hook=failure_hook,
    )
    # The publication may intentionally reuse an earlier capture event for an
    # unchanged canonical state.  Return the authoritative published fact.
    fact = publication.fact
    reconciliation = unknown_verifier_reconciliation(
        observation.observation,
        normalization.normalized_payload,
    )
    if failure_hook is not None:
        failure_hook("before_reconciliation_append")
    _append_reconciliation_once(lake, reconciliation)
    return ShadowRunResult(
        snapshot,
        observation,
        fact,
        publication,
        reconciliation,
    )


def _read_publication_with_duckdb(
    lake: FactLake,
    publication: StoredCanonicalPublication,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if publication.artifact_sha256 is None:
        raise FactLakeCorruptedError("committed publication lacks artifact hash")
    path = lake.verify_canonical_artifact(
        publication.artifact_relpath,
        publication.artifact_sha256,
    )
    if failure_hook is not None:
        failure_hook("before_duckdb_query")
    connection = duckdb.connect(database=":memory:")
    try:
        cursor = connection.execute(
            "SELECT * FROM read_parquet(?)",
            (str(path),),
        )
        columns = tuple(item[0] for item in cursor.description)
        if columns != _PARQUET_COLUMNS:
            raise LimitUpQueryError("canonical Parquet schema is incompatible")
        rows = cursor.fetchall()
    except LimitUpQueryError:
        raise
    except Exception as exc:
        raise LimitUpQueryError("canonical Parquet query failed") from exc
    finally:
        connection.close()
    if len(rows) != 1:
        raise LimitUpQueryError("canonical Parquet must contain exactly one state row")
    record = dict(zip(columns, rows[0]))
    try:
        fact = CanonicalFact.from_dict(json.loads(record["canonical_fact_json"]))
        payload = json.loads(record["canonical_payload_json"])
    except Exception as exc:
        raise LimitUpQueryError("canonical Parquet JSON is invalid") from exc
    expected = publication
    if (
        record["publication_id"] != expected.publication_id
        or record["dataset_id"] != expected.dataset_id
        or record["trade_date"] != expected.trade_date
        or int(record["vintage_sequence"]) != expected.vintage_sequence
        or record["fact_id"] != expected.fact.fact_id
        or record["canonical_key"] != expected.canonical_key
        or record["canonical_source"] != CANONICAL_PROVIDER_ID
        or record["source_observation_id"] != expected.source_observation_id
        or record["dataset_contract_revision"]
            != expected.dataset_contract_revision
        or record["normalizer_version"] != expected.normalizer_version
        or record["raw_payload_hash"] != expected.raw_payload_hash
        or record["artifact_schema_version"] != expected.artifact_schema_version
        or fact.to_dict() != expected.fact.to_dict()
        or payload != expected.fact.canonical_payload
    ):
        raise LimitUpQueryError("canonical Parquet disagrees with the manifest")
    return {
        "publication_id": expected.publication_id,
        "vintage_sequence": expected.vintage_sequence,
        "canonical_fact": fact.to_dict(),
        "canonical_payload": payload,
        "canonical_source": fact.canonical_source,
        "source_observation_id": expected.source_observation_id,
        "dataset_contract_revision": expected.dataset_contract_revision,
        "normalizer_version": expected.normalizer_version,
        "raw_payload_hash": expected.raw_payload_hash,
    }


def query_limit_up_pool(
    lake: FactLake,
    trade_date: str,
    *,
    selection: Literal["latest", "all", "publication"] = "latest",
    publication_id: str | None = None,
    as_of: str | None = None,
    failure_hook: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Read manifest-selected committed publications through DuckDB only."""
    if as_of is not None:
        raise DataContractError(
            "ds_limit_up_pool is BY_DATE and does not support point-in-time queries"
        )
    if _TRADE_DATE_RE.fullmatch(trade_date) is None:
        raise ValueError("trade_date must be YYYY-MM-DD")
    publications = lake.list_canonical_publications(
        dataset_id=DATASET_ID,
        trade_date=trade_date,
    )
    if selection == "latest":
        selected = publications[-1:] if publications else ()
    elif selection == "all":
        selected = publications
    elif selection == "publication":
        if type(publication_id) is not str or not publication_id:
            raise ValueError("publication selection requires publication_id")
        selected = tuple(
            publication for publication in publications
            if publication.publication_id == publication_id
        )
    else:
        raise ValueError("selection must be latest, all or publication")
    return tuple(
        _read_publication_with_duckdb(
            lake,
            publication,
            failure_hook=failure_hook,
        )
        for publication in selected
    )


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "CANONICAL_ENDPOINT",
    "CANONICAL_OPERATION",
    "CANONICAL_PROVIDER_ID",
    "DATASET_CONTRACT_REVISION",
    "DATASET_ID",
    "LIMIT_UP_DATASET_SPEC",
    "LimitUpCanonicalAdmissionError",
    "LimitUpCaptureError",
    "LimitUpNormalizationError",
    "LimitUpQueryError",
    "LimitUpReplayError",
    "LimitUpReplayMetadataError",
    "LimitUpReplayMismatchError",
    "LimitUpReplayNotFoundError",
    "LimitUpReplayUnsupportedError",
    "LimitUpReplayVerification",
    "NORMALIZER_VERSION",
    "RawCaptureBuffer",
    "RawResponseCapture",
    "ReplayedLimitUpNormalization",
    "ShadowRunResult",
    "build_canonical_fact",
    "build_provider_observation",
    "build_request_fingerprint",
    "normalize_adapter_snapshot",
    "persist_raw_observation",
    "persist_normalization",
    "persist_replayed_normalization",
    "publish_canonical_fact",
    "query_limit_up_pool",
    "reconcile_limit_up_counts",
    "replay_normalization",
    "run_limit_up_shadow",
    "unknown_verifier_reconciliation",
    "verify_normalization_replay",
]
