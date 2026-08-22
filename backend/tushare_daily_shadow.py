"""DS-L1-S3 shadow PoC for Tushare ``daily`` (existing integrated dataset).

Dataset selection evidence (DS-L1-S3 §17):

- ``ds_tushare_daily`` is the Tushare Pro ``daily`` endpoint already used by
  the existing BK-11 ingestion path (``bk11_tushare_facts_adapter``), so no
  new provider and no new transport are introduced.
- ``TushareClient.query(..., raw_response_sink=...)`` already exposes the
  exact provider response bytes at the transport boundary, so raw capture
  does not require reimplementing the transport (Gate B).
- The dataset's temporal coordinate is the exchange trade date, expressed by
  the existing ``TemporalSemantics.TRADE_DATE`` (Gate C).
- No change to ``data_contracts.py``, no Fact Lake schema bump, no new
  runtime dependency, no new credential (Gates D-G).
- ``daily`` returns unadjusted OHLCV for a completed trade date
  (``UNADJUSTED``), but the provider contract does not establish historical
  revision semantics, so the conservative revision state is ``UNKNOWN``,
  BY_DATE, no PIT (Gates H-I).
- Daily price cross-sections have clear research value beyond a test
  fixture (Gate J).

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


DATASET_ID = "ds_tushare_daily"
CANONICAL_PROVIDER_ID = "tushare_pro"
CANONICAL_ENDPOINT = "daily"
DATASET_CONTRACT_REVISION = "ds-tushare-daily-contract-v0.1"
NORMALIZER_VERSION = "ds-tushare-daily-normalizer-v0.1"
FIELD_MANIFEST_VERSION = "ds-tushare-daily-fields-v0.1"
ARTIFACT_SCHEMA_VERSION = "ds-tushare-daily-parquet-v0.1"
NORMALIZED_SCHEMA_VERSION = "ds-tushare-daily-normalized-v0.1"
REVISION_ROW_ORDERING = (
    "ts_code ascending, canonical row SHA-256; "
    "deterministic presentation only, not provider revision chronology"
)
DUPLICATE_POLICY = (
    "row identity is (ts_code, trade_date); exact duplicates collapse with "
    "exact_duplicate_count, same-identity conflicts fail closed"
)

IDENTITY_FIELDS = ("ts_code", "trade_date")
METRIC_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)
DAILY_FIELD_MANIFEST = IDENTITY_FIELDS + METRIC_FIELDS
DAILY_FIELDS_ARGUMENT = ",".join(DAILY_FIELD_MANIFEST)

MAX_DAILY_ROWS = 10_000
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


class TushareDailyError(RuntimeError):
    """Base fail-closed S3 error."""


class TushareDailyCaptureError(TushareDailyError):
    """Secret-free response capture metadata was invalid."""


class TushareDailyNormalizationError(TushareDailyError):
    """Provider rows could not satisfy the fixed tushare_daily contract."""


class TushareDailyReplayError(TushareDailyError):
    """Committed raw evidence could not be replayed safely."""


class TushareDailyReplayUnsupportedError(TushareDailyReplayError):
    """The observation belongs to another transformation contract."""


class TushareDailyReplayMismatchError(TushareDailyReplayError):
    """Independent replay disagreed with immutable normalized evidence."""


class TushareDailyCanonicalAdmissionError(TushareDailyError):
    """Questionable evidence was offered for canonical publication."""


class TushareDailyQueryError(TushareDailyError):
    """A tushare_daily Parquet artifact violated its strict query contract."""


TUSHARE_DAILY_DATASET_SPEC = DatasetSpec(
    dataset_id=DATASET_ID,
    fetch_semantics=FetchSemantics.BY_DATE,
    history_mode=HistoryMode.BY_DATE,
    routes=(
        ProviderRoute(
            route_id="tushare-pro-daily",
            provider_id=CANONICAL_PROVIDER_ID,
            provider_endpoint=CANONICAL_ENDPOINT,
            role=ProviderRole.CANONICAL,
            semantic_contract_id="tushare-daily-v0.1",
        ),
    ),
    governance_revision_id=DATASET_CONTRACT_REVISION,
    required_temporal_fields=(TemporalSemantics.TRADE_DATE,),
    coverage_mode=CoverageMode.SESSION_DENSE,
    point_in_time_supported=False,
    revision_semantics=RevisionSemantics.UNKNOWN,
    adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
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
        raise TushareDailyError("value is not canonical JSON") from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_date_from_provider(value: Any, field: str) -> str:
    if type(value) is not str or _PROVIDER_DATE_RE.fullmatch(value) is None:
        raise TushareDailyNormalizationError(f"{field} is not a provider date")
    parsed = f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    try:
        datetime.strptime(parsed, "%Y-%m-%d")
    except ValueError as exc:
        raise TushareDailyNormalizationError(f"{field} is not a calendar date") from exc
    return parsed


def _provider_date_from_canonical(value: Any, field: str) -> str:
    if type(value) is not str:
        raise TushareDailyCaptureError(f"{field} is not canonical")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise TushareDailyCaptureError(f"{field} is not canonical") from exc
    return value.replace("-", "")


def _finite_metric(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise TushareDailyNormalizationError(
            f"{field} must be a finite number or null"
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise TushareDailyNormalizationError(
            f"{field} must be a finite number or null"
        )
    return numeric


@dataclass(frozen=True)
class TushareDailyRequestContract:
    trade_date: str

    def __post_init__(self) -> None:
        if type(self.trade_date) is not str:
            raise TushareDailyCaptureError("trade_date is not canonical")
        try:
            datetime.strptime(self.trade_date, "%Y-%m-%d")
        except ValueError as exc:
            raise TushareDailyCaptureError("trade_date is not canonical") from exc

    @property
    def provider_trade_date(self) -> str:
        return _provider_date_from_canonical(
            self.trade_date,
            "trade_date",
        )

    @property
    def params(self) -> dict[str, str]:
        return {"trade_date": self.provider_trade_date}

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "provider_endpoint": TUSHARE_ENDPOINT,
            "api_name": CANONICAL_ENDPOINT,
            "trade_date": self.trade_date,
            "provider_trade_date": self.provider_trade_date,
            "fields": list(DAILY_FIELD_MANIFEST),
            "field_manifest_version": FIELD_MANIFEST_VERSION,
        }

    @classmethod
    def from_safe_dict(cls, value: Any) -> "TushareDailyRequestContract":
        if type(value) is not dict or set(value) != {
            "provider_endpoint",
            "api_name",
            "trade_date",
            "provider_trade_date",
            "fields",
            "field_manifest_version",
        }:
            raise TushareDailyReplayError("stored request contract is invalid")
        if value["provider_endpoint"] != TUSHARE_ENDPOINT \
                or value["api_name"] != CANONICAL_ENDPOINT \
                or value["field_manifest_version"] != FIELD_MANIFEST_VERSION \
                or value["fields"] != list(DAILY_FIELD_MANIFEST):
            raise TushareDailyReplayError("stored request contract drifted")
        trade_date = _canonical_date_from_provider(
            value["provider_trade_date"],
            "provider_trade_date",
        )
        if trade_date != value["trade_date"]:
            raise TushareDailyReplayError("stored request trade date drifted")
        return cls(trade_date=trade_date)


def build_request_fingerprint(contract: TushareDailyRequestContract) -> str:
    if not isinstance(contract, TushareDailyRequestContract):
        raise TypeError("contract must be TushareDailyRequestContract")
    return f"sha256:{_sha256_text(_canonical_json(contract.to_safe_dict()))}"


@dataclass(frozen=True)
class TushareDailyRawResponseCapture:
    capture_event_id: str
    contract: TushareDailyRequestContract
    raw_bytes: bytes
    request_fingerprint: str
    source_payload_hash: str
    http_status: int
    content_type: str
    fetched_at: str


class TushareDailyRawCaptureBuffer:
    """One-shot sink for exact Tushare response bytes and safe receipt data."""

    def __init__(self, contract: TushareDailyRequestContract) -> None:
        if not isinstance(contract, TushareDailyRequestContract):
            raise TypeError("contract must be TushareDailyRequestContract")
        self.contract = contract
        self.capture: TushareDailyRawResponseCapture | None = None

    def __call__(self, raw_bytes: bytes, metadata: Mapping[str, Any]) -> None:
        if self.capture is not None:
            raise TushareDailyCaptureError(
                "one request produced multiple terminal responses"
            )
        if type(raw_bytes) is not bytes:
            raise TushareDailyCaptureError("raw response must be exact bytes")
        if type(metadata) is not dict or set(metadata) != {
            "endpoint", "api_name", "params", "fields", "http_status",
            "content_type", "fetched_at",
        }:
            raise TushareDailyCaptureError(
                "raw response receipt metadata is invalid"
            )
        if metadata["endpoint"] != TUSHARE_ENDPOINT \
                or metadata["api_name"] != CANONICAL_ENDPOINT \
                or metadata["params"] != self.contract.params \
                or metadata["fields"] != DAILY_FIELDS_ARGUMENT:
            raise TushareDailyCaptureError(
                "raw response provider identity drifted"
            )
        status = metadata["http_status"]
        content_type = metadata["content_type"]
        fetched_at = metadata["fetched_at"]
        if type(status) is not int or status < 100 or status > 599:
            raise TushareDailyCaptureError("HTTP status is invalid")
        if type(content_type) is not str or not content_type.strip() \
                or content_type != content_type.strip() \
                or "\r" in content_type or "\n" in content_type:
            raise TushareDailyCaptureError("content type is unsafe")
        if type(fetched_at) is not str or not fetched_at.endswith("Z"):
            raise TushareDailyCaptureError("fetched_at must be canonical UTC")
        self.capture = TushareDailyRawResponseCapture(
            capture_event_id=f"capture-{uuid.uuid4().hex}",
            contract=self.contract,
            raw_bytes=raw_bytes,
            request_fingerprint=build_request_fingerprint(self.contract),
            source_payload_hash=payload_sha256(raw_bytes),
            http_status=status,
            content_type=content_type,
            fetched_at=fetched_at,
        )


def _observation_id(capture: TushareDailyRawResponseCapture) -> str:
    if type(capture.capture_event_id) is not str or re.fullmatch(
        r"capture-[0-9a-f]{32}", capture.capture_event_id
    ) is None:
        raise TushareDailyCaptureError("capture event identity is invalid")
    identity = _canonical_json({
        "dataset_id": DATASET_ID,
        "provider_id": CANONICAL_PROVIDER_ID,
        "provider_endpoint": CANONICAL_ENDPOINT,
        "capture_event_id": capture.capture_event_id,
    })
    return f"obs-{_sha256_text(identity)}"


def build_provider_observation(
    capture: TushareDailyRawResponseCapture,
    *,
    quality_status: QualityStatus = QualityStatus.VALID,
    reason_codes: tuple[str, ...] = (),
) -> ProviderObservation:
    if not isinstance(capture, TushareDailyRawResponseCapture):
        raise TypeError("capture must be TushareDailyRawResponseCapture")
    if capture.request_fingerprint != build_request_fingerprint(capture.contract):
        raise TushareDailyCaptureError("capture request fingerprint drifted")
    if capture.source_payload_hash.lower() != payload_sha256(
        capture.raw_bytes
    ).lower():
        raise TushareDailyCaptureError("capture payload hash drifted")
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
        provider_symbol=f"{CANONICAL_ENDPOINT}:{capture.contract.trade_date}",
        request_fingerprint=capture.request_fingerprint,
        source_payload_hash=capture.source_payload_hash,
        normalizer_version=NORMALIZER_VERSION,
        payload=payload,
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        fetched_at=capture.fetched_at,
        published_at=None,
        trade_date=capture.contract.trade_date,
        report_period=None,
        revision_id=None,
        data_version=None,
        revision_semantics=RevisionSemantics.UNKNOWN,
        adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
        quality_status=quality_status,
        reason_codes=reason_codes,
    )


def normalize_tushare_daily(
    parsed: TushareParsedResponse,
    contract: TushareDailyRequestContract,
    *,
    source_observation_id: str,
) -> dict[str, Any]:
    """Pure deterministic projection; provider order is never authority."""
    if not isinstance(parsed, TushareParsedResponse):
        raise TypeError("parsed must be TushareParsedResponse")
    if not isinstance(contract, TushareDailyRequestContract):
        raise TypeError("contract must be TushareDailyRequestContract")
    if type(source_observation_id) is not str or not source_observation_id:
        raise TushareDailyNormalizationError("source observation id is required")
    if parsed.fields != DAILY_FIELD_MANIFEST:
        raise TushareDailyNormalizationError("provider field manifest drifted")
    if not parsed.rows:
        raise TushareDailyNormalizationError("tushare_daily response is unexpectedly empty")
    if len(parsed.rows) > MAX_DAILY_ROWS:
        raise TushareDailyNormalizationError("tushare_daily response row limit exceeded")

    rows_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_count = 0
    for raw_row in parsed.rows:
        if type(raw_row) is not dict or tuple(raw_row) != DAILY_FIELD_MANIFEST:
            raise TushareDailyNormalizationError("daily row schema drifted")
        ts_code = raw_row["ts_code"]
        if type(ts_code) is not str or _TS_CODE_RE.fullmatch(ts_code) is None:
            raise TushareDailyNormalizationError("daily row ts_code invalid")
        row_trade_date = _canonical_date_from_provider(
            raw_row["trade_date"],
            "trade_date",
        )
        if row_trade_date != contract.trade_date:
            raise TushareDailyNormalizationError("daily row trade_date mismatch")
        row: dict[str, Any] = {
            "ts_code": ts_code,
            "trade_date": row_trade_date,
        }
        for field in METRIC_FIELDS:
            row[field] = _finite_metric(raw_row[field], field)
        identity = (row["ts_code"], row["trade_date"])
        existing = rows_by_identity.get(identity)
        if existing is None:
            rows_by_identity[identity] = row
            continue
        if _canonical_json(existing) == _canonical_json(row):
            duplicate_count += 1
        else:
            raise TushareDailyNormalizationError(
                "daily row identity conflict for "
                f"{row['ts_code']} {row['trade_date']}"
            )

    rows = sorted(
        rows_by_identity.values(),
        key=lambda r: (
            r["ts_code"],
            _sha256_text(_canonical_json(r)),
        ),
    )
    return {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "field_manifest_version": FIELD_MANIFEST_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "trade_date": contract.trade_date,
        "rows": rows,
        "provider_row_count": len(parsed.rows),
        "unique_row_count": len(rows),
        "exact_duplicate_count": duplicate_count,
        "source_observation_id": source_observation_id,
    }


def persist_tushare_daily_observation(
    lake: FactLake,
    capture: TushareDailyRawResponseCapture,
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


def persist_tushare_daily_normalization(
    lake: FactLake,
    observation: StoredObservation,
    parsed: TushareParsedResponse,
) -> StoredNormalization:
    contract = TushareDailyRequestContract.from_safe_dict(
        observation.observation.payload["request"]
    )
    normalized = normalize_tushare_daily(
        parsed,
        contract,
        source_observation_id=observation.observation.observation_id,
    )
    return lake.store_normalization(
        observation.observation.observation_id,
        normalized,
        normalizer_version=NORMALIZER_VERSION,
    )


def persist_tushare_daily_evidence(
    lake: FactLake,
    capture: TushareDailyRawResponseCapture,
) -> tuple[StoredObservation, StoredNormalization]:
    if capture.http_status != 200:
        raise TushareDailyNormalizationError(
            "non-success HTTP response cannot become normalized evidence"
        )
    parsed = interpret_tushare_response_bytes(
        capture.raw_bytes,
        CANONICAL_ENDPOINT,
    )
    candidate = build_provider_observation(capture)
    normalized = normalize_tushare_daily(
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
class TushareDailyReplayResult:
    observation_id: str
    normalizer_version: str
    normalized_payload: dict[str, Any]


@dataclass(frozen=True)
class TushareDailyReplayVerification:
    status: Literal["ABSENT", "MATCH"]
    replay: TushareDailyReplayResult


def replay_tushare_daily_normalization(
    lake: FactLake,
    observation_id: str,
) -> TushareDailyReplayResult:
    stored = lake.get_observation(observation_id)
    if stored is None:
        raise TushareDailyReplayError("committed tushare_daily observation is absent")
    observation = stored.observation
    if observation.dataset_id != DATASET_ID \
            or observation.provider_id != CANONICAL_PROVIDER_ID \
            or observation.provider_endpoint != CANONICAL_ENDPOINT:
        raise TushareDailyReplayUnsupportedError(
            "tushare_daily replay only supports the canonical daily route"
        )
    if observation.normalizer_version != NORMALIZER_VERSION:
        raise TushareDailyReplayUnsupportedError(
            "tushare_daily observation normalizer version is unsupported"
        )
    if type(observation.payload) is not dict or set(observation.payload) != {
        "capture_event_id", "request", "response", "dataset_contract_revision",
    }:
        raise TushareDailyReplayError("tushare_daily observation metadata is corrupted")
    event_id = observation.payload["capture_event_id"]
    if type(event_id) is not str or re.fullmatch(
        r"capture-[0-9a-f]{32}", event_id
    ) is None:
        raise TushareDailyReplayError(
            "tushare_daily capture event identity is corrupted"
        )
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
        raise TushareDailyReplayError("tushare_daily observation event binding drifted")
    if observation.payload["dataset_contract_revision"] \
            != DATASET_CONTRACT_REVISION:
        raise TushareDailyReplayUnsupportedError(
            "tushare_daily dataset contract revision is unsupported"
        )
    contract = TushareDailyRequestContract.from_safe_dict(
        observation.payload["request"]
    )
    if observation.request_fingerprint != build_request_fingerprint(contract):
        raise TushareDailyReplayError("tushare_daily request fingerprint drifted")
    expected_symbol = f"{CANONICAL_ENDPOINT}:{contract.trade_date}"
    if observation.provider_symbol != expected_symbol \
            or contract.trade_date != observation.trade_date \
            or observation.report_period is not None \
            or observation.published_at is not None:
        raise TushareDailyReplayError("tushare_daily observation temporal metadata drifted")
    response = observation.payload["response"]
    if type(response) is not dict or set(response) != {
        "http_status", "content_type", "byte_length",
    }:
        raise TushareDailyReplayError("tushare_daily response receipt is corrupted")
    if response["http_status"] != 200 \
            or response["content_type"] != stored.content_type \
            or type(response["byte_length"]) is not int \
            or response["byte_length"] < 0 \
            or observation.quality_status is not QualityStatus.VALID:
        raise TushareDailyReplayError(
            "tushare_daily response receipt is not admissible"
        )
    raw_bytes = lake.read_payload(observation_id)
    if raw_bytes is None:
        raise TushareDailyReplayError("committed tushare_daily raw payload is absent")
    if len(raw_bytes) != response["byte_length"] \
            or payload_sha256(raw_bytes).lower() \
                != observation.source_payload_hash.lower():
        raise TushareDailyReplayError("tushare_daily raw payload integrity failed")
    parsed = interpret_tushare_response_bytes(raw_bytes, CANONICAL_ENDPOINT)
    normalized = normalize_tushare_daily(
        parsed,
        contract,
        source_observation_id=observation_id,
    )
    return TushareDailyReplayResult(
        observation_id=observation_id,
        normalizer_version=NORMALIZER_VERSION,
        normalized_payload=normalized,
    )


def verify_tushare_daily_normalization_replay(
    lake: FactLake,
    observation_id: str,
) -> TushareDailyReplayVerification:
    replay = replay_tushare_daily_normalization(lake, observation_id)
    stored = lake.get_normalization(observation_id)
    if stored is None:
        return TushareDailyReplayVerification("ABSENT", replay)
    if stored.normalizer_version != NORMALIZER_VERSION \
            or _canonical_json(stored.normalized_payload) \
                != _canonical_json(replay.normalized_payload):
        raise TushareDailyReplayMismatchError(
            "tushare_daily normalization replay disagrees with immutable evidence"
        )
    return TushareDailyReplayVerification("MATCH", replay)


def build_tushare_daily_canonical_fact(
    observation: ProviderObservation,
    normalization: StoredNormalization,
) -> CanonicalFact:
    if not isinstance(normalization, StoredNormalization):
        raise TypeError("normalization must be StoredNormalization")
    if observation.dataset_id != DATASET_ID \
            or observation.provider_id != CANONICAL_PROVIDER_ID \
            or observation.provider_endpoint != CANONICAL_ENDPOINT \
            or observation.normalizer_version != NORMALIZER_VERSION:
        raise TushareDailyCanonicalAdmissionError("tushare_daily canonical route drifted")
    if observation.quality_status is not QualityStatus.VALID \
            or observation.trade_date is None \
            or observation.report_period is not None \
            or observation.published_at is not None \
            or observation.revision_id is not None \
            or observation.data_version is not None:
        raise TushareDailyCanonicalAdmissionError(
            "tushare_daily temporal/revision admission failed"
        )
    response = observation.payload.get("response") \
        if isinstance(observation.payload, Mapping) else None
    if type(response) is not dict or response.get("http_status") != 200:
        raise TushareDailyCanonicalAdmissionError(
            "tushare_daily response receipt is not canonical-admissible"
        )
    if normalization.source_observation_id != observation.observation_id \
            or normalization.normalizer_version != NORMALIZER_VERSION:
        raise TushareDailyCanonicalAdmissionError(
            "tushare_daily normalization is not bound to its observation"
        )
    payload = normalization.normalized_payload
    if type(payload) is not dict \
            or payload.get("trade_date") != observation.trade_date \
            or payload.get("normalizer_version") != NORMALIZER_VERSION:
        raise TushareDailyCanonicalAdmissionError(
            "tushare_daily normalized payload contract drifted"
        )
    canonical_key = f"{DATASET_ID}:{observation.trade_date}"
    identity = _canonical_json({
        "dataset_id": DATASET_ID,
        "canonical_key": canonical_key,
        "source_observation_id": observation.observation_id,
        "canonical_payload": payload,
        "dataset_contract_revision": DATASET_CONTRACT_REVISION,
    })
    fact = canonicalize_observation(
        TUSHARE_DAILY_DATASET_SPEC,
        observation,
        fact_id=f"fact-{_sha256_text(identity)}",
        canonical_key=canonical_key,
        canonical_payload=dict(payload),
        as_of=None,
        reconciliation_status=ReconciliationStatus.UNKNOWN,
    )
    if fact.trade_date != observation.trade_date \
            or fact.report_period is not None \
            or fact.published_at is not None \
            or fact.revision_id is not None \
            or fact.data_version is not None:
        raise TushareDailyCanonicalAdmissionError(
            "tushare_daily fact fabricated unsupported temporal semantics"
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


def _write_tushare_daily_parquet(
    candidate: Path,
    *,
    publication_id: str,
    vintage_sequence: int,
    fact: CanonicalFact,
) -> None:
    trade_date = fact.trade_date
    if trade_date is None:
        raise TushareDailyCanonicalAdmissionError("tushare_daily trade_date is required")
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
                TemporalSemantics.TRADE_DATE.value,
                trade_date,
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


def publish_tushare_daily_canonical_fact(
    lake: FactLake,
    fact: CanonicalFact,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> StoredCanonicalPublication:
    TUSHARE_DAILY_DATASET_SPEC.validate_fact(fact)
    if fact.canonical_source != CANONICAL_PROVIDER_ID \
            or fact.trade_date is None \
            or fact.report_period is not None:
        raise TushareDailyCanonicalAdmissionError(
            "tushare_daily canonical admission failed"
        )
    verification = verify_tushare_daily_normalization_replay(
        lake,
        fact.source_observation_ids[0],
    )
    if verification.status != "MATCH" \
            or _canonical_json(verification.replay.normalized_payload) \
                != _canonical_json(fact.canonical_payload):
        raise TushareDailyReplayMismatchError(
            "publication requires matching independent tushare_daily replay"
        )
    publication_id, digest = _publication_identity(fact)
    artifact_relpath = PurePosixPath(
        CANONICAL_DIRECTORY_NAME,
        _sha256_text(DATASET_ID),
        fact.trade_date,
        f"{digest}.parquet",
    ).as_posix()
    provenance = fact.provenance_chain[0]
    staged = lake.stage_canonical_publication(
        fact,
        publication_id=publication_id,
        source_observation_id=fact.source_observation_ids[0],
        primary_temporal_field=TemporalSemantics.TRADE_DATE,
        primary_temporal_value=fact.trade_date,
        normalizer_version=provenance.normalizer_version,
        raw_payload_hash=provenance.source_payload_hash,
        artifact_schema_version=ARTIFACT_SCHEMA_VERSION,
        artifact_relpath=artifact_relpath,
        equivalent_replay=_same_canonical_state,
    )
    if staged.stored.commit_state == "COMMITTED":
        return staged.stored
    if failure_hook is not None:
        failure_hook("before_tushare_daily_parquet_creation")

    def writer(candidate: Path) -> None:
        _write_tushare_daily_parquet(
            candidate,
            publication_id=publication_id,
            vintage_sequence=staged.stored.vintage_sequence,
            fact=staged.stored.fact,
        )

    artifact_hash = lake.publish_canonical_artifact(artifact_relpath, writer)
    if failure_hook is not None:
        failure_hook("after_tushare_daily_parquet_durable")
    _read_tushare_daily_publication(lake, replace(
        staged.stored,
        artifact_sha256=artifact_hash,
        commit_state="COMMITTED",
    ))
    if failure_hook is not None:
        failure_hook("before_tushare_daily_publication_commit")
    return lake.commit_canonical_publication(publication_id, artifact_hash)


def _read_tushare_daily_publication(
    lake: FactLake,
    publication: StoredCanonicalPublication,
) -> dict[str, Any]:
    if publication.artifact_sha256 is None:
        raise FactLakeCorruptedError("committed tushare_daily artifact lacks hash")
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
        raise TushareDailyQueryError("tushare_daily Parquet query failed") from exc
    finally:
        connection.close()
    if columns != _PARQUET_COLUMNS or len(rows) != 1:
        raise TushareDailyQueryError("tushare_daily Parquet schema is incompatible")
    record = dict(zip(columns, rows[0]))
    try:
        fact = CanonicalFact.from_dict(json.loads(record["canonical_fact_json"]))
        payload = json.loads(record["canonical_payload_json"])
    except Exception as exc:
        raise TushareDailyQueryError("tushare_daily Parquet JSON is invalid") from exc
    expected = publication
    if (
        record["publication_id"] != expected.publication_id
        or record["dataset_id"] != DATASET_ID
        or record["canonical_key"] != expected.canonical_key
        or record["primary_temporal_field"]
            != TemporalSemantics.TRADE_DATE.value
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
        raise TushareDailyQueryError("tushare_daily Parquet disagrees with manifest")
    return {
        "publication_id": expected.publication_id,
        "dataset_id": DATASET_ID,
        "trade_date": payload["trade_date"],
        "canonical_payload": payload,
        "revision_semantics": fact.revision_semantics.value,
        "source_observation_id": expected.source_observation_id,
        "normalizer_version": expected.normalizer_version,
        "dataset_contract_revision": expected.dataset_contract_revision,
        "vintage_sequence": expected.vintage_sequence,
    }


def query_tushare_daily(
    lake: FactLake,
    trade_date: str,
    *,
    selection: Literal["latest", "all", "publication"] = "latest",
    publication_id: str | None = None,
    as_of: str | None = None,
) -> tuple[dict[str, Any], ...]:
    if as_of is not None:
        raise DataContractError("tushare_daily does not support as_of/PIT")
    contract = TushareDailyRequestContract(trade_date)
    canonical_key = f"{DATASET_ID}:{contract.trade_date}"
    publications = tuple(
        item for item in lake.list_canonical_publications(
            dataset_id=DATASET_ID,
            primary_temporal_field=TemporalSemantics.TRADE_DATE,
            primary_temporal_value=contract.trade_date,
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
    return tuple(_read_tushare_daily_publication(lake, item) for item in selected)


@dataclass(frozen=True)
class TushareDailyShadowRunResult:
    observation: StoredObservation
    normalization: StoredNormalization
    fact: CanonicalFact
    publication: StoredCanonicalPublication


def run_tushare_daily_shadow(
    trade_date: str,
    lake: FactLake,
    *,
    client: TushareClient | None = None,
) -> TushareDailyShadowRunResult:
    contract = TushareDailyRequestContract(trade_date)
    capture_buffer = TushareDailyRawCaptureBuffer(contract)
    active_client = client or TushareClient()
    try:
        active_client.query(
            CANONICAL_ENDPOINT,
            contract.params,
            DAILY_FIELDS_ARGUMENT,
            raw_response_sink=capture_buffer,
        )
    except TushareClientError:
        capture = capture_buffer.capture
        if capture is not None:
            persist_tushare_daily_observation(
                lake,
                capture,
                quality_status=QualityStatus.INVALID,
                reason_codes=("TUSHARE_RESPONSE_INVALID",),
            )
        raise
    capture = capture_buffer.capture
    if capture is None:
        raise TushareDailyCaptureError("Tushare client returned without raw evidence")
    observation, normalization = persist_tushare_daily_evidence(lake, capture)
    fact = build_tushare_daily_canonical_fact(
        observation.observation,
        normalization,
    )
    publication = publish_tushare_daily_canonical_fact(lake, fact)
    return TushareDailyShadowRunResult(
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
    "TUSHARE_DAILY_DATASET_SPEC",
    "DAILY_FIELD_MANIFEST",
    "DAILY_FIELDS_ARGUMENT",
    "TushareDailyCanonicalAdmissionError",
    "TushareDailyCaptureError",
    "TushareDailyNormalizationError",
    "TushareDailyRawCaptureBuffer",
    "TushareDailyRawResponseCapture",
    "TushareDailyReplayError",
    "TushareDailyReplayMismatchError",
    "TushareDailyReplayUnsupportedError",
    "TushareDailyRequestContract",
    "TushareDailyShadowRunResult",
    "MAX_DAILY_ROWS",
    "NORMALIZER_VERSION",
    "REVISION_ROW_ORDERING",
    "DUPLICATE_POLICY",
    "build_tushare_daily_canonical_fact",
    "build_provider_observation",
    "build_request_fingerprint",
    "normalize_tushare_daily",
    "persist_tushare_daily_evidence",
    "persist_tushare_daily_normalization",
    "persist_tushare_daily_observation",
    "publish_tushare_daily_canonical_fact",
    "query_tushare_daily",
    "replay_tushare_daily_normalization",
    "run_tushare_daily_shadow",
    "verify_tushare_daily_normalization_replay",
]
