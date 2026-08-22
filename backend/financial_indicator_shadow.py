"""DS-L1-S2 shadow PoC for Tushare ``fina_indicator``.

The module owns dataset semantics only.  It is deliberately not wired into
production runtime, never performs an implicit migration and never implements
point-in-time/as-of behavior.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, Mapping

import duckdb

from data_contracts import (
    AdjustmentSemantics,
    CanonicalFact,
    CoverageMode,
    DataContractError,
    DatasetSpec,
    FetchSemantics,
    HistoryMode,
    ProviderObservation,
    ProviderRole,
    ProviderRoute,
    QualityStatus,
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
from tushare_pro_client import (
    ENDPOINT as TUSHARE_ENDPOINT,
    TushareClient,
    TushareClientError,
    TushareParsedResponse,
    interpret_tushare_response_bytes,
)


DATASET_ID = "ds_financial_indicator"
CANONICAL_PROVIDER_ID = "tushare_pro"
CANONICAL_ENDPOINT = "fina_indicator"
DATASET_CONTRACT_REVISION = "ds-financial-indicator-contract-v0.1"
NORMALIZER_VERSION = "ds-financial-indicator-normalizer-v0.1"
FIELD_MANIFEST_VERSION = "ds-financial-indicator-fields-v0.1"
ARTIFACT_SCHEMA_VERSION = "ds-financial-indicator-parquet-v0.1"
NORMALIZED_SCHEMA_VERSION = "ds-financial-indicator-normalized-v0.1"
REVISION_ROW_ORDERING = (
    "ann_date ascending, update_flag lexical, canonical row SHA-256; "
    "deterministic presentation only, not provider revision chronology"
)
DUPLICATE_POLICY = (
    "dedupe exact canonical source projections and retain exact_duplicate_count; "
    "preserve every differing row for the company/report period"
)

IDENTITY_FIELDS = ("ts_code", "ann_date", "end_date", "update_flag")
METRIC_FIELDS = (
    "eps",
    "dt_eps",
    "ocfps",
    "grossprofit_margin",
    "netprofit_margin",
    "roe",
    "roa",
    "debt_to_assets",
    "current_ratio",
    "assets_turn",
    "inv_turn",
)
FINANCIAL_FIELD_MANIFEST = IDENTITY_FIELDS + METRIC_FIELDS
FINANCIAL_FIELDS_ARGUMENT = ",".join(FINANCIAL_FIELD_MANIFEST)

MAX_FINANCIAL_ROWS = 2_000
_TS_CODE_RE = re.compile(r"^[0-9]{6}\.(?:SZ|SH|BJ)$")
_PROVIDER_DATE_RE = re.compile(r"^[0-9]{8}$")

_PARQUET_COLUMNS = (
    "publication_id",
    "dataset_id",
    "canonical_key",
    "primary_temporal_field",
    "primary_temporal_value",
    "vintage_sequence",
    "fact_id",
    "canonical_source",
    "source_observation_id",
    "dataset_contract_revision",
    "normalizer_version",
    "raw_payload_hash",
    "artifact_schema_version",
    "canonical_fact_json",
    "canonical_payload_json",
)


class FinancialIndicatorError(RuntimeError):
    """Base fail-closed S2 error."""


class FinancialCaptureError(FinancialIndicatorError):
    """Secret-free response capture metadata was invalid."""


class FinancialNormalizationError(FinancialIndicatorError):
    """Provider rows could not satisfy the fixed financial contract."""


class FinancialReplayError(FinancialIndicatorError):
    """Committed raw evidence could not be replayed safely."""


class FinancialReplayUnsupportedError(FinancialReplayError):
    """The observation belongs to another transformation contract."""


class FinancialReplayMismatchError(FinancialReplayError):
    """Independent replay disagreed with immutable normalized evidence."""


class FinancialCanonicalAdmissionError(FinancialIndicatorError):
    """Questionable evidence was offered for canonical publication."""


class FinancialQueryError(FinancialIndicatorError):
    """A financial Parquet artifact violated its strict query contract."""


FINANCIAL_DATASET_SPEC = DatasetSpec(
    dataset_id=DATASET_ID,
    fetch_semantics=FetchSemantics.BY_DATE,
    history_mode=HistoryMode.BY_DATE,
    routes=(
        ProviderRoute(
            route_id="tushare-pro-fina-indicator",
            provider_id=CANONICAL_PROVIDER_ID,
            provider_endpoint=CANONICAL_ENDPOINT,
            role=ProviderRole.CANONICAL,
            semantic_contract_id="tushare-fina-indicator-v0.1",
        ),
    ),
    governance_revision_id=DATASET_CONTRACT_REVISION,
    required_temporal_fields=(TemporalSemantics.REPORT_PERIOD,),
    coverage_mode=CoverageMode.SPARSE,
    point_in_time_supported=False,
    revision_semantics=RevisionSemantics.RESTATABLE,
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
        raise FinancialNormalizationError("value is not canonical JSON") from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_date_from_provider(value: Any, field: str) -> str:
    if type(value) is not str or _PROVIDER_DATE_RE.fullmatch(value) is None:
        raise FinancialNormalizationError(f"{field} must be YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise FinancialNormalizationError(f"{field} is not a valid date") from exc
    return parsed.strftime("%Y-%m-%d")


def _provider_date_from_canonical(value: Any, field: str) -> str:
    if type(value) is not str:
        raise FinancialCaptureError(f"{field} must be YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise FinancialCaptureError(f"{field} must be YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise FinancialCaptureError(f"{field} must be canonical")
    return parsed.strftime("%Y%m%d")


def _finite_metric(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise FinancialNormalizationError(
            f"{field} must be a finite number or null"
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise FinancialNormalizationError(
            f"{field} must be a finite number or null"
        )
    return numeric


@dataclass(frozen=True)
class FinancialRequestContract:
    ts_code: str
    report_period: str

    def __post_init__(self) -> None:
        if type(self.ts_code) is not str or _TS_CODE_RE.fullmatch(
            self.ts_code
        ) is None:
            raise FinancialCaptureError("ts_code is not canonical")
        _provider_date_from_canonical(self.report_period, "report_period")

    @property
    def provider_period(self) -> str:
        return _provider_date_from_canonical(
            self.report_period,
            "report_period",
        )

    @property
    def params(self) -> dict[str, str]:
        return {"ts_code": self.ts_code, "period": self.provider_period}

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "provider_endpoint": TUSHARE_ENDPOINT,
            "api_name": CANONICAL_ENDPOINT,
            "ts_code": self.ts_code,
            "period": self.provider_period,
            "fields": list(FINANCIAL_FIELD_MANIFEST),
            "field_manifest_version": FIELD_MANIFEST_VERSION,
        }

    @classmethod
    def from_safe_dict(cls, value: Any) -> "FinancialRequestContract":
        if type(value) is not dict or set(value) != {
            "provider_endpoint",
            "api_name",
            "ts_code",
            "period",
            "fields",
            "field_manifest_version",
        }:
            raise FinancialReplayError("stored request contract is invalid")
        if value["provider_endpoint"] != TUSHARE_ENDPOINT \
                or value["api_name"] != CANONICAL_ENDPOINT \
                or value["field_manifest_version"] != FIELD_MANIFEST_VERSION \
                or value["fields"] != list(FINANCIAL_FIELD_MANIFEST):
            raise FinancialReplayError("stored request contract drifted")
        period = _canonical_date_from_provider(value["period"], "period")
        return cls(ts_code=value["ts_code"], report_period=period)


def build_request_fingerprint(contract: FinancialRequestContract) -> str:
    if not isinstance(contract, FinancialRequestContract):
        raise TypeError("contract must be FinancialRequestContract")
    return f"sha256:{_sha256_text(_canonical_json(contract.to_safe_dict()))}"


@dataclass(frozen=True)
class FinancialRawResponseCapture:
    capture_event_id: str
    contract: FinancialRequestContract
    raw_bytes: bytes
    request_fingerprint: str
    source_payload_hash: str
    http_status: int
    content_type: str
    fetched_at: str


class FinancialRawCaptureBuffer:
    """One-shot sink for exact Tushare response bytes and safe receipt data."""

    def __init__(self, contract: FinancialRequestContract) -> None:
        if not isinstance(contract, FinancialRequestContract):
            raise TypeError("contract must be FinancialRequestContract")
        self.contract = contract
        self.capture: FinancialRawResponseCapture | None = None

    def __call__(self, raw_bytes: bytes, metadata: Mapping[str, Any]) -> None:
        if self.capture is not None:
            raise FinancialCaptureError("one request produced multiple terminal responses")
        if type(raw_bytes) is not bytes:
            raise FinancialCaptureError("raw response must be exact bytes")
        if type(metadata) is not dict or set(metadata) != {
            "endpoint", "api_name", "params", "fields", "http_status",
            "content_type", "fetched_at",
        }:
            raise FinancialCaptureError("raw response receipt metadata is invalid")
        if metadata["endpoint"] != TUSHARE_ENDPOINT \
                or metadata["api_name"] != CANONICAL_ENDPOINT \
                or metadata["params"] != self.contract.params \
                or metadata["fields"] != FINANCIAL_FIELDS_ARGUMENT:
            raise FinancialCaptureError("raw response provider identity drifted")
        status = metadata["http_status"]
        content_type = metadata["content_type"]
        fetched_at = metadata["fetched_at"]
        if type(status) is not int or status < 100 or status > 599:
            raise FinancialCaptureError("HTTP status is invalid")
        if type(content_type) is not str or not content_type.strip() \
                or content_type != content_type.strip() \
                or "\r" in content_type or "\n" in content_type:
            raise FinancialCaptureError("content type is unsafe")
        if type(fetched_at) is not str or not fetched_at.endswith("Z"):
            raise FinancialCaptureError("fetched_at must be canonical UTC")
        self.capture = FinancialRawResponseCapture(
            capture_event_id=f"capture-{uuid.uuid4().hex}",
            contract=self.contract,
            raw_bytes=raw_bytes,
            request_fingerprint=build_request_fingerprint(self.contract),
            source_payload_hash=payload_sha256(raw_bytes),
            http_status=status,
            content_type=content_type,
            fetched_at=fetched_at,
        )


def _observation_id(capture: FinancialRawResponseCapture) -> str:
    if type(capture.capture_event_id) is not str or re.fullmatch(
        r"capture-[0-9a-f]{32}", capture.capture_event_id
    ) is None:
        raise FinancialCaptureError("capture event identity is invalid")
    identity = _canonical_json({
        "dataset_id": DATASET_ID,
        "provider_id": CANONICAL_PROVIDER_ID,
        "provider_endpoint": CANONICAL_ENDPOINT,
        "capture_event_id": capture.capture_event_id,
    })
    return f"obs-{_sha256_text(identity)}"


def build_provider_observation(
    capture: FinancialRawResponseCapture,
    *,
    quality_status: QualityStatus = QualityStatus.VALID,
    reason_codes: tuple[str, ...] = (),
) -> ProviderObservation:
    if not isinstance(capture, FinancialRawResponseCapture):
        raise TypeError("capture must be FinancialRawResponseCapture")
    if capture.request_fingerprint != build_request_fingerprint(capture.contract):
        raise FinancialCaptureError("capture request fingerprint drifted")
    if capture.source_payload_hash.lower() != payload_sha256(
        capture.raw_bytes
    ).lower():
        raise FinancialCaptureError("capture payload hash drifted")
    request = capture.contract.to_safe_dict()
    payload = {
        "capture_event_id": capture.capture_event_id,
        "request": request,
        "response": {
            "http_status": capture.http_status,
            "content_type": capture.content_type,
            "byte_length": len(capture.raw_bytes),
        },
        "dataset_contract_revision": DATASET_CONTRACT_REVISION,
    }
    return ProviderObservation(
        observation_id=_observation_id(capture),
        dataset_id=DATASET_ID,
        provider_id=CANONICAL_PROVIDER_ID,
        provider_endpoint=CANONICAL_ENDPOINT,
        provider_symbol=capture.contract.ts_code,
        request_fingerprint=capture.request_fingerprint,
        source_payload_hash=capture.source_payload_hash,
        normalizer_version=NORMALIZER_VERSION,
        payload=payload,
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        fetched_at=capture.fetched_at,
        published_at=None,
        trade_date=None,
        report_period=capture.contract.report_period,
        revision_id=None,
        data_version=None,
        revision_semantics=RevisionSemantics.RESTATABLE,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
        quality_status=quality_status,
        reason_codes=reason_codes,
    )


def normalize_financial_indicator(
    parsed: TushareParsedResponse,
    contract: FinancialRequestContract,
    *,
    source_observation_id: str,
) -> dict[str, Any]:
    """Pure deterministic projection; provider order is never authority."""
    if not isinstance(parsed, TushareParsedResponse):
        raise TypeError("parsed must be TushareParsedResponse")
    if not isinstance(contract, FinancialRequestContract):
        raise TypeError("contract must be FinancialRequestContract")
    if type(source_observation_id) is not str or not source_observation_id:
        raise FinancialNormalizationError("source observation id is required")
    if parsed.fields != FINANCIAL_FIELD_MANIFEST:
        raise FinancialNormalizationError("provider field manifest drifted")
    if not parsed.rows:
        raise FinancialNormalizationError("financial response is unexpectedly empty")
    if len(parsed.rows) > MAX_FINANCIAL_ROWS:
        raise FinancialNormalizationError("financial response row limit exceeded")

    unique_rows: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for raw_row in parsed.rows:
        if type(raw_row) is not dict or tuple(raw_row) != FINANCIAL_FIELD_MANIFEST:
            raise FinancialNormalizationError("financial row schema drifted")
        if raw_row["ts_code"] != contract.ts_code:
            raise FinancialNormalizationError("financial row ts_code mismatch")
        report_period = _canonical_date_from_provider(
            raw_row["end_date"],
            "end_date",
        )
        if report_period != contract.report_period:
            raise FinancialNormalizationError("financial row report period mismatch")
        ann_date = _canonical_date_from_provider(raw_row["ann_date"], "ann_date")
        update_flag = raw_row["update_flag"]
        if type(update_flag) is not str or update_flag not in {"0", "1"}:
            raise FinancialNormalizationError("update_flag must be '0' or '1'")
        row: dict[str, Any] = {
            "ts_code": contract.ts_code,
            "ann_date": ann_date,
            "end_date": report_period,
            "update_flag": update_flag,
        }
        for field in METRIC_FIELDS:
            row[field] = _finite_metric(raw_row[field], field)
        row_json = _canonical_json(row)
        if row_json in unique_rows:
            duplicate_count += 1
        else:
            unique_rows[row_json] = row

    versions = sorted(
        unique_rows.values(),
        key=lambda row: (
            row["ann_date"],
            row["update_flag"],
            _sha256_text(_canonical_json(row)),
        ),
    )
    return {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "field_manifest_version": FIELD_MANIFEST_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "ts_code": contract.ts_code,
        "report_period": contract.report_period,
        "versions": versions,
        "provider_row_count": len(parsed.rows),
        "unique_version_count": len(versions),
        "exact_duplicate_count": duplicate_count,
        "source_observation_id": source_observation_id,
    }


def persist_financial_observation(
    lake: FactLake,
    capture: FinancialRawResponseCapture,
    *,
    quality_status: QualityStatus = QualityStatus.VALID,
    reason_codes: tuple[str, ...] = (),
) -> StoredObservation:
    observation = build_provider_observation(
        capture,
        quality_status=quality_status,
        reason_codes=reason_codes,
    )
    return lake.store_observation(
        observation,
        capture.raw_bytes,
        capture.content_type,
    ).stored


def persist_financial_normalization(
    lake: FactLake,
    observation: StoredObservation,
    parsed: TushareParsedResponse,
) -> StoredNormalization:
    contract = FinancialRequestContract.from_safe_dict(
        observation.observation.payload["request"]
    )
    normalized = normalize_financial_indicator(
        parsed,
        contract,
        source_observation_id=observation.observation.observation_id,
    )
    return lake.store_normalization(
        observation.observation.observation_id,
        normalized,
        normalizer_version=NORMALIZER_VERSION,
    )


def persist_financial_evidence(
    lake: FactLake,
    capture: FinancialRawResponseCapture,
) -> tuple[StoredObservation, StoredNormalization]:
    if capture.http_status != 200:
        raise FinancialNormalizationError(
            "non-success HTTP response cannot become normalized evidence"
        )
    parsed = interpret_tushare_response_bytes(
        capture.raw_bytes,
        CANONICAL_ENDPOINT,
    )
    candidate = build_provider_observation(capture)
    normalized = normalize_financial_indicator(
        parsed,
        capture.contract,
        source_observation_id=candidate.observation_id,
    )
    observation = lake.store_observation(
        candidate,
        capture.raw_bytes,
        capture.content_type,
    ).stored
    normalization = lake.store_normalization(
        candidate.observation_id,
        normalized,
        normalizer_version=NORMALIZER_VERSION,
    )
    return observation, normalization


@dataclass(frozen=True)
class FinancialReplayResult:
    observation_id: str
    normalizer_version: str
    normalized_payload: dict[str, Any]


@dataclass(frozen=True)
class FinancialReplayVerification:
    status: Literal["ABSENT", "MATCH"]
    replay: FinancialReplayResult


def replay_financial_normalization(
    lake: FactLake,
    observation_id: str,
) -> FinancialReplayResult:
    stored = lake.get_observation(observation_id)
    if stored is None:
        raise FinancialReplayError("committed financial observation is absent")
    observation = stored.observation
    if observation.dataset_id != DATASET_ID \
            or observation.provider_id != CANONICAL_PROVIDER_ID \
            or observation.provider_endpoint != CANONICAL_ENDPOINT:
        raise FinancialReplayUnsupportedError(
            "financial replay only supports the canonical fina_indicator route"
        )
    if observation.normalizer_version != NORMALIZER_VERSION:
        raise FinancialReplayUnsupportedError(
            "financial observation normalizer version is unsupported"
        )
    if type(observation.payload) is not dict or set(observation.payload) != {
        "capture_event_id", "request", "response", "dataset_contract_revision",
    }:
        raise FinancialReplayError("financial observation metadata is corrupted")
    event_id = observation.payload["capture_event_id"]
    if type(event_id) is not str or re.fullmatch(
        r"capture-[0-9a-f]{32}", event_id
    ) is None:
        raise FinancialReplayError("financial capture event identity is corrupted")
    event_identity = {
        "dataset_id": DATASET_ID,
        "provider_id": CANONICAL_PROVIDER_ID,
        "provider_endpoint": CANONICAL_ENDPOINT,
        "capture_event_id": event_id,
    }
    expected_observation_id = (
        f"obs-{_sha256_text(_canonical_json(event_identity))}"
    )
    if expected_observation_id != observation.observation_id:
        raise FinancialReplayError("financial observation event binding drifted")
    if observation.payload["dataset_contract_revision"] \
            != DATASET_CONTRACT_REVISION:
        raise FinancialReplayUnsupportedError(
            "financial dataset contract revision is unsupported"
        )
    contract = FinancialRequestContract.from_safe_dict(
        observation.payload["request"]
    )
    if observation.request_fingerprint != build_request_fingerprint(contract):
        raise FinancialReplayError("financial request fingerprint drifted")
    if contract.ts_code != observation.provider_symbol \
            or contract.report_period != observation.report_period \
            or observation.trade_date is not None \
            or observation.published_at is not None:
        raise FinancialReplayError("financial observation temporal metadata drifted")
    response = observation.payload["response"]
    if type(response) is not dict or set(response) != {
        "http_status", "content_type", "byte_length",
    }:
        raise FinancialReplayError("financial response receipt is corrupted")
    if response["http_status"] != 200 \
            or response["content_type"] != stored.content_type \
            or type(response["byte_length"]) is not int \
            or response["byte_length"] < 0 \
            or observation.quality_status is not QualityStatus.VALID:
        raise FinancialReplayError("financial response receipt is not admissible")
    raw_bytes = lake.read_payload(observation_id)
    if raw_bytes is None:
        raise FinancialReplayError("committed financial raw payload is absent")
    if len(raw_bytes) != response["byte_length"] \
            or payload_sha256(raw_bytes).lower() \
                != observation.source_payload_hash.lower():
        raise FinancialReplayError("financial raw payload integrity failed")
    parsed = interpret_tushare_response_bytes(raw_bytes, CANONICAL_ENDPOINT)
    normalized = normalize_financial_indicator(
        parsed,
        contract,
        source_observation_id=observation_id,
    )
    return FinancialReplayResult(
        observation_id=observation_id,
        normalizer_version=NORMALIZER_VERSION,
        normalized_payload=normalized,
    )


def verify_financial_normalization_replay(
    lake: FactLake,
    observation_id: str,
) -> FinancialReplayVerification:
    replay = replay_financial_normalization(lake, observation_id)
    stored = lake.get_normalization(observation_id)
    if stored is None:
        return FinancialReplayVerification("ABSENT", replay)
    if stored.normalizer_version != NORMALIZER_VERSION \
            or _canonical_json(stored.normalized_payload) \
                != _canonical_json(replay.normalized_payload):
        raise FinancialReplayMismatchError(
            "financial normalization replay disagrees with immutable evidence"
        )
    return FinancialReplayVerification("MATCH", replay)


def build_financial_canonical_fact(
    observation: ProviderObservation,
    normalization: StoredNormalization,
) -> CanonicalFact:
    if not isinstance(normalization, StoredNormalization):
        raise TypeError("normalization must be StoredNormalization")
    if observation.dataset_id != DATASET_ID \
            or observation.provider_id != CANONICAL_PROVIDER_ID \
            or observation.provider_endpoint != CANONICAL_ENDPOINT \
            or observation.normalizer_version != NORMALIZER_VERSION:
        raise FinancialCanonicalAdmissionError("financial canonical route drifted")
    if observation.quality_status is not QualityStatus.VALID \
            or observation.trade_date is not None \
            or observation.report_period is None \
            or observation.published_at is not None \
            or observation.revision_id is not None \
            or observation.data_version is not None:
        raise FinancialCanonicalAdmissionError(
            "financial temporal/revision admission failed"
        )
    response = observation.payload.get("response") \
        if isinstance(observation.payload, Mapping) else None
    if type(response) is not dict or response.get("http_status") != 200:
        raise FinancialCanonicalAdmissionError(
            "financial response receipt is not canonical-admissible"
        )
    if normalization.source_observation_id != observation.observation_id \
            or normalization.normalizer_version != NORMALIZER_VERSION:
        raise FinancialCanonicalAdmissionError(
            "financial normalization is not bound to its observation"
        )
    payload = normalization.normalized_payload
    if type(payload) is not dict \
            or payload.get("report_period") != observation.report_period \
            or payload.get("ts_code") != observation.provider_symbol \
            or payload.get("normalizer_version") != NORMALIZER_VERSION:
        raise FinancialCanonicalAdmissionError(
            "financial normalized payload contract drifted"
        )
    canonical_key = (
        f"{DATASET_ID}:{observation.provider_symbol}:{observation.report_period}"
    )
    identity = _canonical_json({
        "dataset_id": DATASET_ID,
        "canonical_key": canonical_key,
        "source_observation_id": observation.observation_id,
        "canonical_payload": payload,
        "dataset_contract_revision": DATASET_CONTRACT_REVISION,
    })
    fact = canonicalize_observation(
        FINANCIAL_DATASET_SPEC,
        observation,
        fact_id=f"fact-{_sha256_text(identity)}",
        canonical_key=canonical_key,
        canonical_payload=dict(payload),
        as_of=None,
        reconciliation_status=ReconciliationStatus.UNKNOWN,
    )
    if fact.trade_date is not None or fact.published_at is not None \
            or fact.revision_id is not None or fact.data_version is not None:
        raise FinancialCanonicalAdmissionError(
            "financial fact fabricated unsupported temporal semantics"
        )
    return fact


def _canonical_state_document(fact: CanonicalFact) -> dict[str, Any]:
    document = fact.to_dict()
    document.pop("fact_id", None)
    document.pop("source_observation_ids", None)
    provenance = document.get("provenance_chain")
    if type(provenance) is list:
        document["provenance_chain"] = [
            {
                key: value
                for key, value in link.items()
                if key not in {"observation_id", "source_payload_hash"}
            }
            for link in provenance
        ]
    payload = document.get("canonical_payload")
    if type(payload) is dict:
        document["canonical_payload"] = {
            key: value
            for key, value in payload.items()
            if key != "source_observation_id"
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


def _write_financial_parquet(
    candidate: Path,
    *,
    publication_id: str,
    vintage_sequence: int,
    fact: CanonicalFact,
) -> None:
    report_period = fact.report_period
    if report_period is None:
        raise FinancialCanonicalAdmissionError("financial report_period is required")
    provenance = fact.provenance_chain[0]
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE canonical_artifact(
                publication_id VARCHAR NOT NULL,
                dataset_id VARCHAR NOT NULL,
                canonical_key VARCHAR NOT NULL,
                primary_temporal_field VARCHAR NOT NULL,
                primary_temporal_value VARCHAR NOT NULL,
                vintage_sequence BIGINT NOT NULL,
                fact_id VARCHAR NOT NULL,
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
        connection.execute(
            "INSERT INTO canonical_artifact VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                publication_id,
                fact.dataset_id,
                fact.canonical_key,
                TemporalSemantics.REPORT_PERIOD.value,
                report_period,
                vintage_sequence,
                fact.fact_id,
                fact.canonical_source,
                fact.source_observation_ids[0],
                fact.dataset_contract_revision,
                provenance.normalizer_version,
                provenance.source_payload_hash,
                ARTIFACT_SCHEMA_VERSION,
                _canonical_json(fact.to_dict()),
                _canonical_json(fact.canonical_payload),
            ),
        )
        quoted = str(candidate).replace("'", "''")
        connection.execute(
            f"COPY canonical_artifact TO '{quoted}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()


def publish_financial_canonical_fact(
    lake: FactLake,
    fact: CanonicalFact,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> StoredCanonicalPublication:
    FINANCIAL_DATASET_SPEC.validate_fact(fact)
    if fact.canonical_source != CANONICAL_PROVIDER_ID \
            or fact.trade_date is not None \
            or fact.report_period is None:
        raise FinancialCanonicalAdmissionError("financial canonical admission failed")
    verification = verify_financial_normalization_replay(
        lake,
        fact.source_observation_ids[0],
    )
    if verification.status != "MATCH" \
            or _canonical_json(verification.replay.normalized_payload) \
                != _canonical_json(fact.canonical_payload):
        raise FinancialReplayMismatchError(
            "publication requires matching independent financial replay"
        )
    publication_id, digest = _publication_identity(fact)
    artifact_relpath = PurePosixPath(
        CANONICAL_DIRECTORY_NAME,
        _sha256_text(DATASET_ID),
        fact.report_period,
        f"{digest}.parquet",
    ).as_posix()
    provenance = fact.provenance_chain[0]
    staged = lake.stage_canonical_publication(
        fact,
        publication_id=publication_id,
        source_observation_id=fact.source_observation_ids[0],
        primary_temporal_field=TemporalSemantics.REPORT_PERIOD,
        primary_temporal_value=fact.report_period,
        normalizer_version=provenance.normalizer_version,
        raw_payload_hash=provenance.source_payload_hash,
        artifact_schema_version=ARTIFACT_SCHEMA_VERSION,
        artifact_relpath=artifact_relpath,
        equivalent_replay=_same_canonical_state,
    )
    if staged.stored.commit_state == "COMMITTED":
        return staged.stored
    if failure_hook is not None:
        failure_hook("before_financial_parquet_creation")

    def writer(candidate: Path) -> None:
        _write_financial_parquet(
            candidate,
            publication_id=publication_id,
            vintage_sequence=staged.stored.vintage_sequence,
            fact=staged.stored.fact,
        )

    artifact_hash = lake.publish_canonical_artifact(artifact_relpath, writer)
    if failure_hook is not None:
        failure_hook("after_financial_parquet_durable")
    _read_financial_publication(lake, replace(
        staged.stored,
        artifact_sha256=artifact_hash,
        commit_state="COMMITTED",
    ))
    if failure_hook is not None:
        failure_hook("before_financial_publication_commit")
    return lake.commit_canonical_publication(publication_id, artifact_hash)


def _read_financial_publication(
    lake: FactLake,
    publication: StoredCanonicalPublication,
) -> dict[str, Any]:
    if publication.artifact_sha256 is None:
        raise FactLakeCorruptedError("committed financial artifact lacks hash")
    path = lake.verify_canonical_artifact(
        publication.artifact_relpath,
        publication.artifact_sha256,
    )
    connection = duckdb.connect(database=":memory:")
    try:
        cursor = connection.execute("SELECT * FROM read_parquet(?)", (str(path),))
        columns = tuple(column[0] for column in cursor.description)
        rows = cursor.fetchall()
    except Exception as exc:
        raise FinancialQueryError("financial Parquet query failed") from exc
    finally:
        connection.close()
    if columns != _PARQUET_COLUMNS or len(rows) != 1:
        raise FinancialQueryError("financial Parquet schema is incompatible")
    record = dict(zip(columns, rows[0]))
    try:
        fact = CanonicalFact.from_dict(json.loads(record["canonical_fact_json"]))
        payload = json.loads(record["canonical_payload_json"])
    except Exception as exc:
        raise FinancialQueryError("financial Parquet JSON is invalid") from exc
    expected = publication
    if (
        record["publication_id"] != expected.publication_id
        or record["dataset_id"] != DATASET_ID
        or record["canonical_key"] != expected.canonical_key
        or record["primary_temporal_field"]
            != TemporalSemantics.REPORT_PERIOD.value
        or record["primary_temporal_value"] != expected.primary_temporal_value
        or int(record["vintage_sequence"]) != expected.vintage_sequence
        or record["fact_id"] != expected.fact.fact_id
        or record["canonical_source"] != CANONICAL_PROVIDER_ID
        or record["source_observation_id"] != expected.source_observation_id
        or record["dataset_contract_revision"]
            != expected.dataset_contract_revision
        or record["normalizer_version"] != expected.normalizer_version
        or record["raw_payload_hash"] != expected.raw_payload_hash
        or record["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION
        or fact.to_dict() != expected.fact.to_dict()
        or payload != expected.fact.canonical_payload
    ):
        raise FinancialQueryError("financial Parquet disagrees with manifest")
    return {
        "publication_id": expected.publication_id,
        "dataset_id": DATASET_ID,
        "ts_code": payload["ts_code"],
        "report_period": payload["report_period"],
        "canonical_payload": payload,
        "revision_semantics": fact.revision_semantics.value,
        "source_observation_id": expected.source_observation_id,
        "normalizer_version": expected.normalizer_version,
        "dataset_contract_revision": expected.dataset_contract_revision,
        "vintage_sequence": expected.vintage_sequence,
    }


def query_financial_indicators(
    lake: FactLake,
    ts_code: str,
    report_period: str,
    *,
    selection: Literal["latest", "all", "publication"] = "latest",
    publication_id: str | None = None,
    as_of: str | None = None,
) -> tuple[dict[str, Any], ...]:
    if as_of is not None:
        raise DataContractError("financial indicators do not support as_of/PIT")
    contract = FinancialRequestContract(ts_code, report_period)
    canonical_key = f"{DATASET_ID}:{contract.ts_code}:{contract.report_period}"
    publications = tuple(
        item for item in lake.list_canonical_publications(
            dataset_id=DATASET_ID,
            primary_temporal_field=TemporalSemantics.REPORT_PERIOD,
            primary_temporal_value=contract.report_period,
        )
        if item.canonical_key == canonical_key
    )
    if selection == "latest":
        selected = publications[-1:] if publications else ()
    elif selection == "all":
        selected = publications
    elif selection == "publication":
        if type(publication_id) is not str or not publication_id:
            raise ValueError("publication selection requires publication_id")
        selected = tuple(
            item for item in publications if item.publication_id == publication_id
        )
    else:
        raise ValueError("selection must be latest, all or publication")
    return tuple(_read_financial_publication(lake, item) for item in selected)


@dataclass(frozen=True)
class FinancialShadowRunResult:
    observation: StoredObservation
    normalization: StoredNormalization
    fact: CanonicalFact
    publication: StoredCanonicalPublication


def run_financial_indicator_shadow(
    ts_code: str,
    report_period: str,
    lake: FactLake,
    *,
    client: TushareClient | None = None,
) -> FinancialShadowRunResult:
    contract = FinancialRequestContract(ts_code, report_period)
    capture_buffer = FinancialRawCaptureBuffer(contract)
    active_client = client or TushareClient()
    try:
        active_client.query(
            CANONICAL_ENDPOINT,
            contract.params,
            FINANCIAL_FIELDS_ARGUMENT,
            raw_response_sink=capture_buffer,
        )
    except TushareClientError:
        capture = capture_buffer.capture
        if capture is not None:
            persist_financial_observation(
                lake,
                capture,
                quality_status=QualityStatus.INVALID,
                reason_codes=("TUSHARE_RESPONSE_INVALID",),
            )
        raise
    capture = capture_buffer.capture
    if capture is None:
        raise FinancialCaptureError("Tushare client returned without raw evidence")
    observation, normalization = persist_financial_evidence(lake, capture)
    fact = build_financial_canonical_fact(
        observation.observation,
        normalization,
    )
    publication = publish_financial_canonical_fact(lake, fact)
    return FinancialShadowRunResult(
        observation,
        normalization,
        publication.fact,
        publication,
    )


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "CANONICAL_ENDPOINT",
    "CANONICAL_PROVIDER_ID",
    "DATASET_CONTRACT_REVISION",
    "DATASET_ID",
    "FIELD_MANIFEST_VERSION",
    "FINANCIAL_DATASET_SPEC",
    "FINANCIAL_FIELD_MANIFEST",
    "FINANCIAL_FIELDS_ARGUMENT",
    "FinancialCanonicalAdmissionError",
    "FinancialCaptureError",
    "FinancialNormalizationError",
    "FinancialRawCaptureBuffer",
    "FinancialRawResponseCapture",
    "FinancialReplayError",
    "FinancialReplayMismatchError",
    "FinancialReplayUnsupportedError",
    "FinancialRequestContract",
    "FinancialShadowRunResult",
    "MAX_FINANCIAL_ROWS",
    "NORMALIZER_VERSION",
    "REVISION_ROW_ORDERING",
    "DUPLICATE_POLICY",
    "build_financial_canonical_fact",
    "build_provider_observation",
    "build_request_fingerprint",
    "normalize_financial_indicator",
    "persist_financial_evidence",
    "persist_financial_normalization",
    "persist_financial_observation",
    "publish_financial_canonical_fact",
    "query_financial_indicators",
    "replay_financial_normalization",
    "run_financial_indicator_shadow",
    "verify_financial_normalization_replay",
]
