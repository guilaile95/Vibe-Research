"""Offline behavioral contract tests for the DS-L1-S1B limit-up shadow path."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
import hashlib
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
    FactLakePublicationConflictError,
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


def _fact_for(lake, raw: bytes, snapshot=None):
    snapshot = snapshot or _snapshot()
    stored = persist_raw_observation(lake, _capture(raw), snapshot)
    normalization = persist_normalization(lake, stored, snapshot)
    return stored, build_canonical_fact(stored.observation, normalization)


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
    raw = b'{ "wire-order" : [2, 1] }\n'
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
    assert len(calls) == 1 and response.content_reads == 0
    assert access_log == ["status", "json"]

    access_log.clear()
    buffer = RawCaptureBuffer()

    def sink(content, metadata):
        access_log.append("sink")
        buffer(content, metadata)

    captured = adapter.fetch_limit_up_pool_snapshot(TRADE_DATE, raw_response_sink=sink)
    assert captured == baseline
    assert len(calls) == 2 and response.content_reads == 1
    # response.content is first.  Its exact bytes are handed to the callback
    # before the normal HTTP status classifier and JSON parser run.
    assert access_log == ["content", "status", "sink", "status", "json"]
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
    raw = b'{"normalization":"must-not-lose-raw-evidence"}'
    payload = {"data": {"date": TRADE_DATE, "pool": [{"c": "000001", "lbc": 2}]}}
    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: _Response(raw, payload))
    lake = initialize_fact_lake(tmp_path / failure_mode)
    expected = build_provider_observation(_capture(raw), _snapshot())

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

    committed = lake.get_observation(expected.observation_id)
    assert committed is not None and committed.commit_state == "COMMITTED"
    assert lake.read_payload(expected.observation_id) == raw
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
    stored, fact = _fact_for(lake, b'{"version":1}')
    first = publish_canonical_fact(lake, fact)
    assert publish_canonical_fact(lake, fact) == first
    assert persist_raw_observation(lake, _capture(b'{"version":1}'), _snapshot()) == stored

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


def test_exact_raw_replay_ignores_receipt_metadata_but_normalization_stays_immutable(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    raw = b'{"same-request-and-bytes":true}'
    snapshot = _snapshot()
    first = persist_raw_observation(lake, _capture(raw), snapshot)
    normalization = persist_normalization(lake, first, snapshot)
    fact = build_canonical_fact(first.observation, normalization)
    publication = publish_canonical_fact(lake, fact)

    replay = persist_raw_observation(
        lake,
        _capture(
            raw,
            content_type="application/problem+json",
            http_status=503,
            fetched_at="2026-07-30T11:00:00Z",
        ),
        snapshot,
    )
    assert replay == first
    assert lake.get_observation(first.observation.observation_id) == first

    conflicting_snapshot = _snapshot(rows=[{"stock_code": "000001", "lbc": 3}])
    with pytest.raises(FactLakeNormalizationConflictError, match="conflicting output"):
        persist_normalization(lake, replay, conflicting_snapshot)
    assert lake.get_normalization(first.observation.observation_id) == normalization
    assert query_limit_up_pool(lake, TRADE_DATE, selection="all") == (
        query_limit_up_pool(lake, TRADE_DATE, selection="publication", publication_id=publication.publication_id)[0],
    )


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

        raw = b'{"hard-exit":true}'
        snapshot = {
            "schema_version": "short-term-limit-up-pool-adapter-v0.1",
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

    _, fact = _fact_for(fresh, raw)
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

    with pytest.raises(FactLakePublicationConflictError, match="persisted normalized evidence"):
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


def test_reconciliation_is_count_only_and_never_switches_the_canonical_source(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    raw = b'{"reconciliation":true}'
    eastmoney = replace(
        build_provider_observation(_capture(raw), _snapshot(rows=[{"stock_code": "000001", "lbc": 2}])),
        payload={"row_count": 1},
    )
    tushare = replace(
        eastmoney,
        observation_id="obs-tushare",
        provider_id=VERIFIER_PROVIDER_ID,
        provider_endpoint=VERIFIER_ENDPOINT,
        provider_symbol="stk_limit:20260730",
        payload={"limit_up_count": 999},
    )
    lake.store_observation(eastmoney, raw, "application/json")
    stored_tushare = lake.store_observation(tushare, raw, "application/json").stored
    result = reconcile_limit_up_counts(lake, eastmoney, tushare)
    assert result.status is ReconciliationStatus.MISMATCH
    assert result.left_observation_id == eastmoney.observation_id
    assert result.right_observation_id == tushare.observation_id
    with pytest.raises((LimitUpCanonicalAdmissionError, DataContractError)):
        build_canonical_fact(tushare, persist_normalization(lake, stored_tushare, _snapshot()))


def test_explicit_shadow_run_uses_one_provider_call_and_default_adapter_stays_shadow_disabled(
    monkeypatch, adapter_environment, tmp_path
):
    payload = {"data": {"date": TRADE_DATE, "pool": [{"c": "000001", "lbc": 2}]}}
    response = _Response(b'{"wire":"exact"}', payload)
    calls = []
    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: calls.append(1) or response)
    baseline = adapter.fetch_limit_up_pool_snapshot(TRADE_DATE)
    assert baseline["status"] == "normal" and calls == [1] and response.content_reads == 0

    result = run_limit_up_shadow(TRADE_DATE, initialize_fact_lake(tmp_path / "lake"))
    assert calls == [1, 1]
    assert result.observation is not None and result.publication is not None
    assert response.content_reads == 1
