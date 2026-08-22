"""Offline behavioral contract tests for the DS-L1-S1B limit-up shadow path."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

import pytest

import astock
import limit_up_shadow as shadow
import short_term_limit_up_pool_adapter as adapter
import trade_calendar
from data_contracts import (
    DataContractError,
    ProviderRole,
    QualityStatus,
    ReconciliationStatus,
)
from fact_lake_store import (
    CONTROL_DB_FILENAME,
    FactLakeCorruptedError,
    FactLakeNormalizationConflictError,
    FactLakeObservationConflictError,
    initialize_fact_lake,
    open_existing_fact_lake,
)
from limit_up_shadow import (
    CANONICAL_ENDPOINT,
    CANONICAL_OPERATION,
    CANONICAL_PROVIDER_ID,
    DATASET_ID,
    LIMIT_UP_DATASET_SPEC,
    VERIFIER_ENDPOINT,
    VERIFIER_PROVIDER_ID,
    LimitUpCanonicalAdmissionError,
    LimitUpCaptureError,
    LimitUpNormalizationError,
    LimitUpQueryError,
    RawCaptureBuffer,
    build_canonical_fact,
    build_provider_observation,
    build_request_fingerprint,
    normalize_adapter_snapshot,
    persist_normalization,
    persist_raw_observation,
    publish_canonical_fact,
    query_limit_up_pool,
    reconcile_limit_up_counts,
    run_limit_up_shadow,
    unknown_verifier_reconciliation,
)


TRADE_DATE = "2026-07-30"


def _metadata(**overrides):
    metadata = {
        "operation": CANONICAL_OPERATION,
        "endpoint": CANONICAL_ENDPOINT,
        "requested_trade_date": TRADE_DATE,
        "dpt": "wz.ztzt",
        "page_index": 0,
        "page_size": 10_000,
        "sort": "fbt:asc",
        "http_status": 200,
        "content_type": "application/json; charset=utf-8",
        "fetched_at": "2026-07-30T08:00:00Z",
    }
    metadata.update(overrides)
    return metadata


def _snapshot(*, rows=None, **overrides):
    rows = [{"stock_code": "000001", "lbc": 2}] if rows is None else rows
    value = {
        "schema_version": adapter.SCHEMA_VERSION,
        "source_id": "eastmoney_getTopicZTPool",
        "endpoint": CANONICAL_OPERATION,
        "requested_trade_date": TRADE_DATE,
        "status": "normal",
        "reason_codes": [],
        "rows": rows,
        "transport_success": True,
        "parse_success": True,
        "required_field_present": True,
        "data_array_present": True,
        "trade_date_match": True,
        "row_count": len(rows),
        "legal_zero": False,
        "upstream_null": False,
        "unexplained_empty": False,
        "coverage_warning": False,
        "target_universe_empty_after_filter": False,
        "source_pool_row_count": len(rows),
        "http_status": 200,
        "error_class": "NONE",
        "excluded_universe_count": 0,
        "invalid_row_count": 0,
        "duplicate_code_count": 0,
    }
    value.update(overrides)
    return value


def _capture(raw: bytes = b'{"data":{"pool":[]}}', **metadata_overrides):
    sink = RawCaptureBuffer()
    sink(raw, _metadata(**metadata_overrides))
    assert sink.capture is not None
    return sink.capture


def _provider_raw(snapshot=None, *, marker: bytes = b""):
    snapshot = snapshot or _snapshot()
    return json.dumps(
        {
            "date": TRADE_DATE.replace("-", ""),
            "marker_sha256": hashlib.sha256(marker).hexdigest(),
            "data": {
                "pool": [
                    {"c": row["stock_code"], "lbc": row["lbc"]}
                    for row in snapshot["rows"]
                ]
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _fact_for(lake, raw: bytes, snapshot=None):
    snapshot = snapshot or _snapshot()
    raw = _provider_raw(snapshot, marker=raw)
    stored = persist_raw_observation(lake, _capture(raw), snapshot)
    normalization = persist_normalization(lake, stored, snapshot)
    return stored, build_canonical_fact(stored.observation, normalization)


def _rows(count: int) -> list[dict[str, object]]:
    return [
        {"stock_code": f"{index:06d}", "lbc": 1}
        for index in range(1, count + 1)
    ]


def _persist_eastmoney_count(lake, count: int, *, raw: bytes | None = None):
    snapshot = _snapshot(rows=_rows(count))
    raw = _provider_raw(snapshot, marker=raw or f"count:{count}".encode())
    stored = persist_raw_observation(lake, _capture(raw), snapshot)
    normalization = persist_normalization(lake, stored, snapshot)
    assert "row_count" not in stored.observation.payload
    assert normalization.normalized_payload["row_count"] == count
    return stored, normalization


def _persist_tushare_count(
    lake,
    count: int,
    *,
    trade_date: str = TRADE_DATE,
    quality_status: QualityStatus = QualityStatus.VALID,
    payload_count: int | None = None,
):
    evidence = {"limit_up_count": count, "trade_date": trade_date}
    raw = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = hashlib.sha256(raw).hexdigest()
    base = build_provider_observation(_capture(b'{"verifier-base":true}'), _snapshot())
    verifier = replace(
        base,
        observation_id=f"obs-tushare-{digest}",
        provider_id=VERIFIER_PROVIDER_ID,
        provider_endpoint=VERIFIER_ENDPOINT,
        provider_symbol=f"stk_limit:{trade_date}",
        request_fingerprint=f"sha256:{hashlib.sha256(f'tushare:{trade_date}'.encode()).hexdigest()}",
        source_payload_hash=f"sha256:{digest}",
        normalizer_version=shadow.VERIFIER_EVIDENCE_VERSION,
        payload={
            "limit_up_count": count if payload_count is None else payload_count,
            "trade_date": trade_date,
        },
        fetched_at="2026-07-30T08:05:00Z",
        trade_date=trade_date,
        quality_status=quality_status,
        reason_codes=(
            () if quality_status is QualityStatus.VALID
            else ("VERIFIER_QUALITY_UNTRUSTED",)
        ),
    )
    stored = lake.store_observation(verifier, raw, "application/json").stored
    assert json.loads(lake.read_payload(verifier.observation_id)) == evidence
    return stored


class _Response:
    def __init__(self, content: bytes, payload: dict | None, *, status_code=200, json_raises=None, access_log=None):
        self._content = content
        self._payload = payload
        self._status_code = status_code
        self._json_raises = json_raises
        self.access_log = access_log if access_log is not None else []
        self.headers = {"Content-Type": "application/json; charset=utf-8"}
        self.content_reads = 0

    @property
    def status_code(self):
        self.access_log.append("status")
        return self._status_code

    @property
    def content(self):
        self.access_log.append("content")
        self.content_reads += 1
        return self._content

    def json(self):
        self.access_log.append("json")
        if self._json_raises is not None:
            raise self._json_raises
        return self._payload


@pytest.fixture
def adapter_environment(monkeypatch):
    monkeypatch.setattr(trade_calendar, "_load_calendar", lambda: (TRADE_DATE,))
    monkeypatch.setattr(trade_calendar, "_today_shanghai", lambda: date(2026, 8, 4))


def test_dataset_contract_has_only_eastmoney_canonical_and_tushare_verifier():
    assert LIMIT_UP_DATASET_SPEC.dataset_id == DATASET_ID
    assert LIMIT_UP_DATASET_SPEC.canonical_route.provider_id == CANONICAL_PROVIDER_ID
    assert LIMIT_UP_DATASET_SPEC.canonical_route.provider_endpoint == CANONICAL_ENDPOINT
    assert LIMIT_UP_DATASET_SPEC.route_for(
        VERIFIER_PROVIDER_ID, VERIFIER_ENDPOINT
    ).role is ProviderRole.VERIFIER
    assert not any(route.role is ProviderRole.FALLBACK for route in LIMIT_UP_DATASET_SPEC.routes)


def test_fingerprint_is_deterministic_and_rejects_secret_metadata():
    first = build_request_fingerprint(_metadata(http_status=503, user_agent="x"))
    second = build_request_fingerprint(_metadata(http_status=200, retry_timing=123))
    assert first == second
    assert first.startswith("sha256:")
    assert "secret" not in first.lower()
    with pytest.raises(LimitUpCaptureError):
        build_request_fingerprint(_metadata(token="must-not-be-hashed"))
    with pytest.raises(LimitUpCaptureError):
        build_request_fingerprint(_metadata(page_size=9999))


def test_adapter_shadow_capture_is_exact_and_disabled_path_has_no_extra_content_read(
    monkeypatch, adapter_environment
):
    raw = _provider_raw(marker=b"byte-authority")
    access_log = []
    response = _Response(
        raw,
        {"data": {"date": TRADE_DATE, "pool": [{"c": "000001", "lbc": 2}]}},
        access_log=access_log,
    )
    calls = []
    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: calls.append(1) or response)

    baseline = adapter.fetch_limit_up_pool_snapshot(TRADE_DATE)
    assert baseline["status"] == "normal"
    assert len(calls) == 1 and response.content_reads == 1
    assert access_log == ["content", "status"]

    access_log.clear()
    buffer = RawCaptureBuffer()

    def sink(content, metadata):
        access_log.append("sink")
        buffer(content, metadata)

    captured = adapter.fetch_limit_up_pool_snapshot(TRADE_DATE, raw_response_sink=sink)
    assert captured == baseline
    assert len(calls) == 2 and response.content_reads == 2
    # response.content is first.  Its exact bytes are handed to the callback
    # before the normal HTTP status classifier and JSON parser run.
    assert access_log == ["content", "status", "sink"]
    assert buffer.capture is not None
    assert buffer.capture.raw_bytes == raw
    assert buffer.capture.source_payload_hash == f"sha256:{hashlib.sha256(raw).hexdigest()}"
    assert "ut" not in buffer.capture.metadata
    assert buffer.capture.metadata["requested_trade_date"] == TRADE_DATE


def test_normalization_is_deterministic_and_invalid_or_partial_snapshots_never_admit(tmp_path):
    unordered = _snapshot(rows=[{"stock_code": "600001", "lbc": 1}, {"stock_code": "000001", "lbc": 2}])
    outputs = [normalize_adapter_snapshot(unordered, source_observation_id="obs-fixed") for _ in range(100)]
    assert all(output == outputs[0] for output in outputs)
    assert [row["stock_code"] for row in outputs[0]["rows"]] == ["000001", "600001"]
    with pytest.raises(LimitUpNormalizationError):
        normalize_adapter_snapshot(_snapshot(rows=[{"stock_code": "bad", "lbc": 1}]), source_observation_id="x")

    partial = _snapshot(status="partial", reason_codes=["DATE_BINDING_UNVERIFIED"], trade_date_match=None, coverage_warning=True)
    lake = initialize_fact_lake(tmp_path / "lake")
    stored = persist_raw_observation(lake, _capture(), partial)
    assert stored.observation.quality_status is QualityStatus.INVALID
    with pytest.raises(LimitUpCanonicalAdmissionError):
        build_canonical_fact(stored.observation, persist_normalization(lake, stored, partial))


def test_legal_zero_is_durable_raw_invalid_evidence_and_never_canonicalizes(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    legal_zero = _snapshot(
        rows=[],
        row_count=0,
        source_pool_row_count=0,
        legal_zero=True,
    )
    stored = persist_raw_observation(lake, _capture(b'{"legal_zero":true}'), legal_zero)
    assert stored.commit_state == "COMMITTED"
    assert stored.observation.quality_status is QualityStatus.INVALID
    assert stored.observation.payload["adapter_outcome"]["status"] == "normal"
    with pytest.raises(LimitUpCanonicalAdmissionError):
        build_canonical_fact(
            stored.observation,
            persist_normalization(lake, stored, legal_zero),
        )
    assert query_limit_up_pool(lake, TRADE_DATE) == ()


@pytest.mark.parametrize(
    ("status_code", "payload", "json_raises", "expected_reason"),
    [
        (503, {"data": {"date": TRADE_DATE, "pool": []}}, None, "HTTP_ERROR"),
        (200, None, ValueError("bad json"), "PARSE_ERROR"),
        (200, {"data": None}, None, "UPSTREAM_NULL"),
    ],
)
def test_response_level_failures_are_raw_only_not_canonical(
    monkeypatch,
    adapter_environment,
    tmp_path,
    status_code,
    payload,
    json_raises,
    expected_reason,
):
    if expected_reason == "PARSE_ERROR":
        raw = b"not-json"
    elif expected_reason == "UPSTREAM_NULL":
        raw = b'{"data":null}'
    else:
        raw = f'{{"case":"{expected_reason}"}}'.encode()
    response = _Response(raw, payload, status_code=status_code, json_raises=json_raises)
    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: response)
    lake = initialize_fact_lake(tmp_path / expected_reason)

    result = run_limit_up_shadow(TRADE_DATE, lake)
    assert result.observation is not None
    assert result.observation.commit_state == "COMMITTED"
    assert result.observation.observation.quality_status is QualityStatus.INVALID
    assert expected_reason in result.observation.observation.reason_codes
    assert lake.read_payload(result.observation.observation.observation_id) == raw
    assert result.fact is result.publication is result.reconciliation is None
    assert query_limit_up_pool(lake, TRADE_DATE) == ()


def test_transport_exception_creates_no_observation(monkeypatch, adapter_environment, tmp_path):
    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("offline")))
    lake = initialize_fact_lake(tmp_path / "lake")
    result = run_limit_up_shadow(TRADE_DATE, lake)
    assert result.snapshot["reason_codes"] == ["TRANSPORT_ERROR"]
    assert result.observation is result.fact is result.publication is result.reconciliation is None
    assert query_limit_up_pool(lake, TRADE_DATE) == ()


@pytest.mark.parametrize("failure_mode", ["before_normalization", "normalizer"])
def test_raw_observation_is_committed_before_hook_or_deterministic_normalization_failure(
    monkeypatch, adapter_environment, tmp_path, failure_mode
):
    raw = _provider_raw(marker=b"must-not-lose-raw-evidence")
    payload = {"data": {"date": TRADE_DATE, "pool": [{"c": "000001", "lbc": 2}]}}
    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: _Response(raw, payload))
    lake = initialize_fact_lake(tmp_path / failure_mode)

    if failure_mode == "before_normalization":
        def failure_hook(point):
            if point == "before_normalization":
                raise RuntimeError("interrupt before normalization")

        with pytest.raises(RuntimeError, match="before normalization"):
            run_limit_up_shadow(TRADE_DATE, lake, failure_hook=failure_hook)
    else:
        monkeypatch.setattr(
            shadow,
            "normalize_adapter_snapshot",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                LimitUpNormalizationError("deterministic normalizer rejected evidence")
            ),
        )
        with pytest.raises(LimitUpNormalizationError, match="normalizer rejected"):
            run_limit_up_shadow(TRADE_DATE, lake)

    conn = sqlite3.connect(tmp_path / failure_mode / CONTROL_DB_FILENAME)
    try:
        observation_ids = [
            row[0]
            for row in conn.execute(
                "SELECT observation_id FROM observations"
                " WHERE commit_state = 'COMMITTED'"
            ).fetchall()
        ]
    finally:
        conn.close()
    assert len(observation_ids) == 1
    committed = lake.get_observation(observation_ids[0])
    assert committed is not None and committed.commit_state == "COMMITTED"
    assert lake.read_payload(observation_ids[0]) == raw
    assert query_limit_up_pool(lake, TRADE_DATE) == ()


def test_verifier_observation_cannot_become_canonical_even_if_its_payload_looks_valid(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    raw = b'{"provider":"verifier"}'
    canonical = build_provider_observation(_capture(raw), _snapshot())
    verifier = replace(
        canonical,
        provider_id=VERIFIER_PROVIDER_ID,
        provider_endpoint=VERIFIER_ENDPOINT,
        provider_symbol="stk_limit:20260730",
        payload={"limit_up_count": 1},
    )
    stored = lake.store_observation(verifier, raw, "application/json").stored
    with pytest.raises(LimitUpCanonicalAdmissionError):
        build_canonical_fact(verifier, persist_normalization(lake, stored, _snapshot()))


def test_replay_is_idempotent_but_new_evidence_makes_a_new_vintage_and_survives_restart(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    snapshot = _snapshot()
    first_capture = _capture(_provider_raw(snapshot, marker=b"version:1"))
    stored = persist_raw_observation(lake, first_capture, snapshot)
    normalization = persist_normalization(lake, stored, snapshot)
    fact = build_canonical_fact(stored.observation, normalization)
    first = publish_canonical_fact(lake, fact)
    assert publish_canonical_fact(lake, fact) == first
    assert persist_raw_observation(lake, first_capture, snapshot) == stored

    _, changed_fact = _fact_for(lake, b'{"version":2}')
    second = publish_canonical_fact(lake, changed_fact)
    assert second.vintage_sequence == first.vintage_sequence + 1
    assert len(query_limit_up_pool(lake, TRADE_DATE, selection="all")) == 2

    restarted = open_existing_fact_lake(root)
    latest = query_limit_up_pool(restarted, TRADE_DATE)
    assert len(latest) == 1
    assert latest[0]["publication_id"] == second.publication_id
    with pytest.raises(DataContractError, match="point-in-time"):
        query_limit_up_pool(restarted, TRADE_DATE, as_of="2026-07-30T09:00:00Z")


def test_normalization_is_bound_once_per_raw_observation_and_normalizer(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    snapshot = _snapshot()
    stored = persist_raw_observation(lake, _capture(b'{"normalization":1}'), snapshot)
    first = persist_normalization(lake, stored, snapshot)
    assert lake.get_normalization(stored.observation.observation_id) == first
    conflicting_payload = dict(first.normalized_payload)
    conflicting_payload["row_count"] = 99
    with pytest.raises(FactLakeNormalizationConflictError, match="conflicting output"):
        lake.store_normalization(
            stored.observation.observation_id,
            conflicting_payload,
            normalizer_version=stored.observation.normalizer_version,
        )
    assert lake.get_normalization(stored.observation.observation_id) == first


def test_same_capture_event_replay_is_idempotent_and_receipt_is_immutable(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    raw = b'{"same-request-and-bytes":true}'
    snapshot = _snapshot()
    capture = _capture(raw)
    first = persist_raw_observation(lake, capture, snapshot)
    normalization = persist_normalization(lake, first, snapshot)
    replay = persist_raw_observation(lake, capture, snapshot)
    assert replay == first
    assert lake.get_observation(first.observation.observation_id) == first

    tampered_metadata = dict(capture.metadata)
    tampered_metadata.update({
        "content_type": "application/problem+json",
        "fetched_at": "2026-07-30T11:00:00Z",
        "http_status": 503,
    })
    tampered = replace(
        capture,
        metadata=tampered_metadata,
        content_type="application/problem+json",
        fetched_at="2026-07-30T11:00:00Z",
    )
    with pytest.raises(FactLakeObservationConflictError):
        persist_raw_observation(lake, tampered, snapshot)
    assert lake.get_observation(first.observation.observation_id) == first

    conflicting_snapshot = _snapshot(rows=[{"stock_code": "000001", "lbc": 3}])
    with pytest.raises(FactLakeNormalizationConflictError, match="conflicting output"):
        persist_normalization(lake, replay, conflicting_snapshot)
    assert lake.get_normalization(first.observation.observation_id) == normalization


def test_separate_capture_events_same_bytes_share_blob_and_reuse_canonical_state(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    snapshot = _snapshot()
    raw = _provider_raw(snapshot, marker=b"same-state-observed-twice")
    capture_t1 = _capture(raw, fetched_at="2026-07-30T08:00:00Z")
    capture_t2 = _capture(
        raw,
        content_type="application/problem+json",
        http_status=201,
        fetched_at="2026-07-30T08:05:00Z",
    )

    first = persist_raw_observation(lake, capture_t1, snapshot)
    second_snapshot = dict(snapshot)
    second_snapshot["http_status"] = 201
    second = persist_raw_observation(lake, capture_t2, second_snapshot)
    assert first.observation.observation_id != second.observation.observation_id
    assert capture_t1.capture_event_id != capture_t2.capture_event_id
    assert first.observation.request_fingerprint == second.observation.request_fingerprint
    assert first.blob_hash == second.blob_hash
    assert first.blob_relpath == second.blob_relpath
    assert first.observation.fetched_at == "2026-07-30T08:00:00Z"
    assert second.observation.fetched_at == "2026-07-30T08:05:00Z"
    assert first.content_type == "application/json; charset=utf-8"
    assert second.content_type == "application/problem+json"
    assert first.observation.payload["response"]["http_status"] == 200
    assert second.observation.payload["response"]["http_status"] == 201
    assert len(list((root / "raw").rglob("*.blob"))) == 1

    first_normalization = persist_normalization(lake, first, snapshot)
    second_normalization = persist_normalization(lake, second, second_snapshot)
    assert first_normalization.source_observation_id != second_normalization.source_observation_id
    first_publication = publish_canonical_fact(
        lake,
        build_canonical_fact(first.observation, first_normalization),
    )
    second_publication = publish_canonical_fact(
        lake,
        build_canonical_fact(second.observation, second_normalization),
    )
    assert second_publication == first_publication
    assert second_publication.vintage_sequence == 1
    assert len(query_limit_up_pool(lake, TRADE_DATE, selection="all")) == 1

    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM normalized_observations"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_publications"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_same_name_noop_append_only_trigger_spoof_fails_normal_open_and_write(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    db_path = root / CONTROL_DB_FILENAME
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TRIGGER normalized_observations_guard_update")
        conn.execute(
            "CREATE TRIGGER normalized_observations_guard_update "
            "BEFORE UPDATE ON normalized_observations BEGIN SELECT 1; END"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(FactLakeCorruptedError, match="fingerprint"):
        open_existing_fact_lake(root)
    with pytest.raises(FactLakeCorruptedError, match="fingerprint"):
        persist_raw_observation(lake, _capture(b'{"must-not-write":true}'), _snapshot())


def test_fresh_process_hard_exit_after_durable_parquet_recovers_exactly_one_vintage(tmp_path):
    """A process death after durable artifact validation cannot expose it early."""
    root = tmp_path / "crash-lake"
    raw = b'{"hard-exit":true}'
    worker = textwrap.dedent(
        """
        import os
        import sys
        from fact_lake_store import initialize_fact_lake
        from limit_up_shadow import (
            CANONICAL_ENDPOINT, CANONICAL_OPERATION, RawCaptureBuffer,
            build_canonical_fact, persist_normalization, persist_raw_observation,
            publish_canonical_fact,
        )

        raw = b'{"date":"20260730","marker":"hard-exit","data":{"pool":[{"c":"000001","lbc":2}]}}'
        snapshot = {
            "schema_version": "short-term-limit-up-pool-adapter-v0.2",
            "source_id": "eastmoney_getTopicZTPool",
            "endpoint": CANONICAL_OPERATION,
            "requested_trade_date": "2026-07-30",
            "status": "normal", "reason_codes": [],
            "rows": [{"stock_code": "000001", "lbc": 2}],
            "transport_success": True, "parse_success": True,
            "required_field_present": True, "data_array_present": True,
            "trade_date_match": True, "row_count": 1, "legal_zero": False,
            "upstream_null": False, "unexplained_empty": False,
            "coverage_warning": False,
            "target_universe_empty_after_filter": False,
            "source_pool_row_count": 1, "http_status": 200,
            "error_class": "NONE", "excluded_universe_count": 0,
            "invalid_row_count": 0, "duplicate_code_count": 0,
        }
        metadata = {
            "operation": CANONICAL_OPERATION,
            "endpoint": CANONICAL_ENDPOINT,
            "requested_trade_date": "2026-07-30", "dpt": "wz.ztzt",
            "page_index": 0, "page_size": 10000, "sort": "fbt:asc",
            "http_status": 200, "content_type": "application/json; charset=utf-8",
            "fetched_at": "2026-07-30T08:00:00Z",
        }
        sink = RawCaptureBuffer()
        sink(raw, metadata)
        lake = initialize_fact_lake(sys.argv[1])
        stored = persist_raw_observation(lake, sink.capture, snapshot)
        normalization = persist_normalization(lake, stored, snapshot)
        fact = build_canonical_fact(stored.observation, normalization)
        def hard_exit(point):
            if point == "before_publication_commit":
                os._exit(77)
        publish_canonical_fact(lake, fact, failure_hook=hard_exit)
        """
    )
    environment = os.environ.copy()
    backend_dir = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = backend_dir + os.pathsep + environment.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", worker, str(root)],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 77, completed.stderr

    fresh = open_existing_fact_lake(root, readonly=False)
    assert query_limit_up_pool(fresh, TRADE_DATE) == ()
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        states = conn.execute("SELECT commit_state FROM canonical_publications").fetchall()
    finally:
        conn.close()
    assert states == [("STAGING",)]
    assert list((root / "canonical").rglob("*.parquet"))

    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        observation_id = conn.execute(
            "SELECT source_observation_id FROM canonical_publications"
        ).fetchone()[0]
    finally:
        conn.close()
    stored = fresh.get_observation(observation_id)
    normalization = fresh.get_normalization(observation_id)
    assert stored is not None and normalization is not None
    fact = build_canonical_fact(stored.observation, normalization)
    publication = publish_canonical_fact(fresh, fact)
    assert publication.vintage_sequence == 1
    restarted = open_existing_fact_lake(root)
    assert query_limit_up_pool(restarted, TRADE_DATE)[0]["publication_id"] == publication.publication_id


def test_publication_rejects_forged_canonical_payload_not_equal_to_persisted_normalization(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, fact = _fact_for(lake, b'{"forgery":1}')
    forged_payload = dict(fact.canonical_payload)
    forged_payload["row_count"] = 999
    forged = replace(fact, fact_id="fact-forged-payload", canonical_payload=forged_payload)

    with pytest.raises(LimitUpCanonicalAdmissionError, match="committed raw evidence"):
        publish_canonical_fact(lake, forged)
    assert query_limit_up_pool(lake, TRADE_DATE) == ()


def test_staged_orphan_is_not_query_visible_and_durable_precommit_failure_retries(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, fact = _fact_for(lake, b'{"failure-window":true}')
    seen = []

    def fail_after_durable(point):
        seen.append(point)
        if point == "after_parquet_durable":
            raise RuntimeError("simulated process death")

    with pytest.raises(RuntimeError, match="process death"):
        publish_canonical_fact(lake, fact, failure_hook=fail_after_durable)
    assert "after_parquet_durable" in seen
    assert query_limit_up_pool(lake, TRADE_DATE) == ()

    # The artifact is an intentional orphan until its manifest commit; retry must
    # reuse its immutable bytes and make exactly that staged publication visible.
    committed = publish_canonical_fact(lake, fact)
    assert committed.commit_state == "COMMITTED"
    assert len(query_limit_up_pool(lake, TRADE_DATE)) == 1


def test_concurrent_identical_publication_has_one_visible_immutable_result(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, fact = _fact_for(lake, b'{"concurrent":true}')
    with ThreadPoolExecutor(max_workers=4) as executor:
        publications = list(executor.map(lambda _: publish_canonical_fact(lake, fact), range(8)))
    assert {item.publication_id for item in publications} == {publications[0].publication_id}
    assert {item.vintage_sequence for item in publications} == {1}
    assert len(query_limit_up_pool(lake, TRADE_DATE, selection="all")) == 1


def test_query_fails_closed_for_missing_hash_corrupt_and_wrong_schema_artifacts(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, fact = _fact_for(lake, b'{"artifact":1}')
    publication = publish_canonical_fact(lake, fact)
    artifact = lake.canonical_artifact_path(publication.artifact_relpath)

    artifact.unlink()
    with pytest.raises(FactLakeCorruptedError):
        query_limit_up_pool(lake, TRADE_DATE)

    # A retry recreates no artifact silently: a committed publication is immutable.
    with pytest.raises(FactLakeCorruptedError):
        publish_canonical_fact(lake, fact)

    # Build a fresh committed artifact and mutate it after publication; query must
    # reject the hash mismatch before DuckDB treats it as data.
    lake = initialize_fact_lake(tmp_path / "separate-lake")
    _, fact = _fact_for(lake, b'{"artifact":2}')
    publication = publish_canonical_fact(lake, fact)
    artifact = lake.canonical_artifact_path(publication.artifact_relpath)
    artifact.write_bytes(b"not parquet")
    with pytest.raises(FactLakeCorruptedError):
        query_limit_up_pool(lake, TRADE_DATE)


def test_query_rejects_schema_that_matches_manifest_hash_but_not_contract(tmp_path, monkeypatch):
    """Hash verification is necessary but schema validation is still mandatory."""
    import duckdb

    lake = initialize_fact_lake(tmp_path / "lake")
    _, fact = _fact_for(lake, b'{"artifact":3}')
    publication = publish_canonical_fact(lake, fact)
    artifact = lake.canonical_artifact_path(publication.artifact_relpath)
    # Replace with valid Parquet, then make the manifest hash agree to exercise
    # the separate DuckDB schema fail-closed boundary.
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE wrong_schema (only_column VARCHAR)")
        con.execute("INSERT INTO wrong_schema VALUES ('x')")
        quoted = str(artifact).replace("'", "''")
        con.execute(f"COPY wrong_schema TO '{quoted}' (FORMAT PARQUET)")
    finally:
        con.close()
    digest = lake._file_sha256(artifact)
    monkeypatch.setattr(lake, "verify_canonical_artifact", lambda *args: artifact)
    # The method's manifest payload must still claim a committed object, while
    # the query itself detects a non-contract schema rather than accepting it.
    assert digest.startswith("sha256:")
    with pytest.raises(LimitUpQueryError, match="schema"):
        query_limit_up_pool(lake, TRADE_DATE)


@pytest.mark.parametrize(
    ("eastmoney_count", "tushare_count", "expected_status"),
    [
        (100, 100, ReconciliationStatus.MATCH),
        (100, 104, ReconciliationStatus.MATCH),
        (60, 63, ReconciliationStatus.MATCH),
        (60, 64, ReconciliationStatus.MISMATCH),
    ],
)
def test_reconciliation_uses_real_normalization_and_bk11_count_tolerance(
    tmp_path,
    eastmoney_count,
    tushare_count,
    expected_status,
):
    lake = initialize_fact_lake(tmp_path / "lake")
    eastmoney, normalization = _persist_eastmoney_count(lake, eastmoney_count)
    tushare = _persist_tushare_count(lake, tushare_count)

    result = reconcile_limit_up_counts(
        lake,
        eastmoney.observation,
        tushare.observation,
    )
    assert result.status is expected_status
    assert result.left_observation_id == eastmoney.observation.observation_id
    assert result.right_observation_id == tushare.observation.observation_id
    assert result.left_value == {"row_count": eastmoney_count}
    assert result.right_value == {"limit_up_count": tushare_count}
    assert result.comparison_evidence["left_evidence"] \
        == "committed_raw_replay.verified_row_count"
    assert result.comparison_evidence["absolute_delta"] \
        == abs(tushare_count - eastmoney_count)
    assert result.comparison_evidence["tolerance"] \
        == max(3, eastmoney_count * 0.05)
    assert normalization.normalized_payload["row_count"] == eastmoney_count
    assert LIMIT_UP_DATASET_SPEC.canonical_route.provider_id \
        == CANONICAL_PROVIDER_ID
    with pytest.raises(DataContractError):
        LIMIT_UP_DATASET_SPEC.canonical_route_for(
            tushare.observation.provider_id,
            tushare.observation.provider_endpoint,
        )


def test_reconciliation_missing_normalization_and_verifier_fail_closed(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    snapshot = _snapshot(rows=_rows(2))
    eastmoney = persist_raw_observation(
        lake,
        _capture(_provider_raw(snapshot, marker=b"without-normalization")),
        snapshot,
    )
    tushare = _persist_tushare_count(lake, 2)

    missing_normalization = reconcile_limit_up_counts(
        lake,
        eastmoney.observation,
        tushare.observation,
    )
    assert missing_normalization.status is ReconciliationStatus.UNKNOWN
    assert missing_normalization.reason_codes == ("COUNT_EVIDENCE_UNAVAILABLE",)
    assert missing_normalization.left_value is None

    normalization = persist_normalization(lake, eastmoney, snapshot)
    missing_verifier = unknown_verifier_reconciliation(
        eastmoney.observation,
        normalization.normalized_payload,
    )
    assert missing_verifier.status is ReconciliationStatus.UNKNOWN
    assert missing_verifier.reason_codes == ("VERIFIER_OBSERVATION_ABSENT",)
    assert missing_verifier.left_value == {"row_count": 2}


def test_reconciliation_rejects_untrusted_or_temporally_incomparable_verifier(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    eastmoney, _ = _persist_eastmoney_count(lake, 4)
    untrusted = _persist_tushare_count(
        lake,
        4,
        quality_status=QualityStatus.INVALID,
    )
    untrusted_result = reconcile_limit_up_counts(
        lake,
        eastmoney.observation,
        untrusted.observation,
    )
    assert untrusted_result.status is ReconciliationStatus.UNKNOWN
    assert untrusted_result.reason_codes == ("VERIFIER_QUALITY_UNTRUSTED",)

    other_lake = initialize_fact_lake(tmp_path / "other-lake")
    eastmoney, _ = _persist_eastmoney_count(other_lake, 4)
    other_date = _persist_tushare_count(
        other_lake,
        4,
        trade_date="2026-07-29",
    )
    temporal_result = reconcile_limit_up_counts(
        other_lake,
        eastmoney.observation,
        other_date.observation,
    )
    assert temporal_result.status is ReconciliationStatus.TEMPORAL_INCOMPARABLE
    assert temporal_result.reason_codes == ("TRADE_DATE_MISMATCH",)
    assert LIMIT_UP_DATASET_SPEC.canonical_route.provider_id \
        == CANONICAL_PROVIDER_ID


def test_reconciliation_rejects_verifier_payload_not_derived_from_raw(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    eastmoney, _ = _persist_eastmoney_count(lake, 2)
    verifier = _persist_tushare_count(lake, 2, payload_count=3)

    result = reconcile_limit_up_counts(
        lake,
        eastmoney.observation,
        verifier.observation,
    )
    assert result.status is ReconciliationStatus.UNKNOWN
    assert result.reason_codes == ("COUNT_EVIDENCE_UNAVAILABLE",)
    assert result.right_value is None
    assert LIMIT_UP_DATASET_SPEC.canonical_route.provider_id \
        == CANONICAL_PROVIDER_ID


def test_explicit_shadow_run_uses_one_provider_call_and_default_adapter_stays_shadow_disabled(
    monkeypatch, adapter_environment, tmp_path
):
    payload = {"data": {"date": TRADE_DATE, "pool": [{"c": "000001", "lbc": 2}]}}
    response = _Response(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        payload,
    )
    calls = []
    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: calls.append(1) or response)
    baseline = adapter.fetch_limit_up_pool_snapshot(TRADE_DATE)
    assert baseline["status"] == "normal" and calls == [1] and response.content_reads == 1

    result = run_limit_up_shadow(TRADE_DATE, initialize_fact_lake(tmp_path / "lake"))
    assert calls == [1, 1]
    assert result.observation is not None and result.publication is not None
    assert response.content_reads == 2
