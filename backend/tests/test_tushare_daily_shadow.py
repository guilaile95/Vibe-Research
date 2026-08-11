from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

import tushare_daily_shadow as daily_module
import tushare_pro_client as tpc
from data_contracts import (
    DataContractError,
    QualityStatus,
    RevisionSemantics,
    TemporalSemantics,
)
from fact_lake_store import (
    CONTROL_DB_FILENAME,
    FactLakeCorruptedError,
    FactLakePublicationConflictError,
    initialize_fact_lake,
    open_existing_fact_lake,
    payload_sha256,
)
from tushare_daily_shadow import (
    ARTIFACT_SCHEMA_VERSION,
    DAILY_FIELDS_ARGUMENT,
    CANONICAL_ENDPOINT,
    DATASET_CONTRACT_REVISION,
    DATASET_ID,
    FIELD_MANIFEST_VERSION,
    TUSHARE_DAILY_DATASET_SPEC,
    DAILY_FIELD_MANIFEST,
    TushareDailyNormalizationError,
    TushareDailyCaptureError,
    TushareDailyReplayError,
    MAX_DAILY_ROWS,
    TushareDailyRawResponseCapture,
    TushareDailyReplayMismatchError,
    TushareDailyReplayResult,
    TushareDailyReplayUnsupportedError,
    TushareDailyRequestContract,
    NORMALIZER_VERSION,
    build_tushare_daily_canonical_fact,
    build_provider_observation,
    build_request_fingerprint,
    normalize_tushare_daily,
    persist_tushare_daily_evidence,
    persist_tushare_daily_observation,
    publish_tushare_daily_canonical_fact,
    query_tushare_daily,
    replay_tushare_daily_normalization,
    run_tushare_daily_shadow,
    verify_tushare_daily_normalization_replay,
)


TRADE_DATE = "2026-07-30"


def _row(
    *,
    ts_code: str = "600519.SH",
    trade_date: str = "20260730",
    close: object = 1800.0,
    pct_chg: object = 1.5,
    **overrides,
) -> list[object]:
    values = {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": 1780.0,
        "high": 1810.0,
        "low": 1775.0,
        "close": close,
        "pre_close": 1773.4,
        "change": 26.6,
        "pct_chg": pct_chg,
        "vol": 35000.0,
        "amount": 6280000.0,
    }
    values.update(overrides)
    return [values[field] for field in DAILY_FIELD_MANIFEST]


def _raw(
    rows: list[list[object]] | None = None,
    *,
    fields: tuple[str, ...] = DAILY_FIELD_MANIFEST,
    code: int = 0,
) -> bytes:
    return json.dumps({
        "code": code,
        "msg": "synthetic",
        "data": {
            "fields": list(fields),
            "items": [_row()] if rows is None else rows,
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _capture(
    raw: bytes,
    event: int = 1,
    *,
    fetched_at: str = "2026-07-30T08:00:00.000000Z",
) -> TushareDailyRawResponseCapture:
    contract = TushareDailyRequestContract(TRADE_DATE)
    return TushareDailyRawResponseCapture(
        capture_event_id=f"capture-{event:032x}",
        contract=contract,
        raw_bytes=raw,
        request_fingerprint=build_request_fingerprint(contract),
        source_payload_hash=payload_sha256(raw),
        http_status=200,
        content_type="application/json; charset=utf-8",
        fetched_at=fetched_at,
    )


def _persist_fact(lake, raw: bytes, event: int = 1):
    observation, normalization = persist_tushare_daily_evidence(
        lake,
        _capture(raw, event),
    )
    fact = build_tushare_daily_canonical_fact(
        observation.observation,
        normalization,
    )
    return observation, normalization, fact


def _tree_snapshot(root: Path):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        result[relative] = (
            "file" if path.is_file() else "dir",
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file() else None,
        )
    return result


class _Response:
    def __init__(self, body: bytes):
        self.body = body
        self.status = 200
        self.headers = {"Content-Type": "application/json; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=None):
        return self.body if limit is None else self.body[:limit]


def test_dataset_contract_is_trade_date_immutable_unadjusted_and_not_pit():
    spec = TUSHARE_DAILY_DATASET_SPEC
    assert spec.dataset_id == DATASET_ID
    assert spec.required_temporal_fields == (TemporalSemantics.TRADE_DATE,)
    assert spec.revision_semantics is RevisionSemantics.IMMUTABLE
    assert spec.point_in_time_supported is False
    assert spec.canonical_route.provider_id == "tushare_pro"
    assert spec.canonical_route.provider_endpoint == "daily"
    assert len(spec.routes) == 1


def test_request_fingerprint_is_deterministic_and_secret_free():
    contract = TushareDailyRequestContract(TRADE_DATE)
    assert build_request_fingerprint(contract) == build_request_fingerprint(contract)
    safe = json.dumps(contract.to_safe_dict(), sort_keys=True)
    assert "token" not in safe.lower()
    assert "authorization" not in safe.lower()
    assert contract.params == {"trade_date": "20260730"}


def test_capture_fingerprint_hash_and_http_status_bind_before_normalization(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    capture = _capture(_raw())
    with pytest.raises(TushareDailyCaptureError, match="fingerprint"):
        build_provider_observation(
            replace(capture, request_fingerprint="sha256:" + ("0" * 64))
        )
    with pytest.raises(TushareDailyCaptureError, match="payload hash"):
        build_provider_observation(
            replace(capture, source_payload_hash="sha256:" + ("0" * 64))
        )
    with pytest.raises(TushareDailyNormalizationError, match="HTTP"):
        persist_tushare_daily_evidence(lake, replace(capture, http_status=503))


def test_normalization_preserves_all_rows_dedupes_exact_rows_and_orders(
    tmp_path,
):
    original = _row()
    updated = _row(ts_code="000001.SZ", close=12.5)
    raw = _raw([updated, original, original])
    capture = _capture(raw)
    parsed = tpc.interpret_tushare_response_bytes(raw, CANONICAL_ENDPOINT)
    expected = normalize_tushare_daily(
        parsed,
        capture.contract,
        source_observation_id=build_provider_observation(capture).observation_id,
    )
    assert expected["rows"] == [
        {
            field: (
                value
                if field in {"ts_code", "trade_date"}
                else (None if value is None else float(value))
            )
            for field, value in zip(DAILY_FIELD_MANIFEST, updated)
        } | {
            "trade_date": TRADE_DATE,
        },
        {
            field: (
                value
                if field in {"ts_code", "trade_date"}
                else (None if value is None else float(value))
            )
            for field, value in zip(DAILY_FIELD_MANIFEST, original)
        } | {
            "trade_date": TRADE_DATE,
        },
    ]
    assert expected["provider_row_count"] == 3
    assert expected["unique_row_count"] == 2
    assert expected["exact_duplicate_count"] == 1
    for _ in range(100):
        assert normalize_tushare_daily(
            parsed,
            capture.contract,
            source_observation_id=expected["source_observation_id"],
        ) == expected

    reordered = tpc.interpret_tushare_response_bytes(
        _raw([original, updated, original]),
        CANONICAL_ENDPOINT,
    )
    assert normalize_tushare_daily(
        reordered,
        capture.contract,
        source_observation_id=expected["source_observation_id"],
    ) == expected


@pytest.mark.parametrize(
    ("rows", "fields", "message"),
    [
        ([], DAILY_FIELD_MANIFEST, "empty"),
        ([_row()[:-1]], DAILY_FIELD_MANIFEST[:-1], "manifest"),
        ([_row(ts_code="600519")], DAILY_FIELD_MANIFEST, "ts_code"),
        ([_row(trade_date="20260230")], DAILY_FIELD_MANIFEST, "trade_date"),
        ([_row(trade_date="20260731")], DAILY_FIELD_MANIFEST, "trade_date"),
        ([_row(close=True)], DAILY_FIELD_MANIFEST, "finite number"),
        ([_row(close=float("nan"))], DAILY_FIELD_MANIFEST, "finite number"),
        ([_row(close=float("inf"))], DAILY_FIELD_MANIFEST, "finite number"),
        ([_row(close="")], DAILY_FIELD_MANIFEST, "finite number"),
    ],
)
def test_daily_normalizer_fails_closed(rows, fields, message):
    raw = _raw(rows, fields=fields)
    parsed = tpc.interpret_tushare_response_bytes(raw, CANONICAL_ENDPOINT)
    with pytest.raises(TushareDailyNormalizationError, match=message):
        normalize_tushare_daily(
            parsed,
            TushareDailyRequestContract(TRADE_DATE),
            source_observation_id="obs-test",
        )


def test_daily_dataset_row_limit_fails_closed():
    raw = _raw([_row()] * (MAX_DAILY_ROWS + 1))
    parsed = tpc.interpret_tushare_response_bytes(raw, CANONICAL_ENDPOINT)
    with pytest.raises(TushareDailyNormalizationError, match="row limit"):
        normalize_tushare_daily(
            parsed,
            TushareDailyRequestContract(TRADE_DATE),
            source_observation_id="obs-test",
        )


def test_replay_from_committed_raw_matches_without_using_stored_input(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    observation, normalization, fact = _persist_fact(lake, _raw())
    replay = replay_tushare_daily_normalization(
        lake,
        observation.observation.observation_id,
    )
    assert replay.normalized_payload == normalization.normalized_payload
    assert verify_tushare_daily_normalization_replay(
        lake,
        observation.observation.observation_id,
    ).status == "MATCH"
    assert fact.canonical_payload == replay.normalized_payload
    for _ in range(100):
        assert replay_tushare_daily_normalization(
            lake,
            observation.observation.observation_id,
        ) == replay


def test_replay_absent_mismatch_and_unsupported_are_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    capture = _capture(_raw())
    observation = persist_tushare_daily_observation(lake, capture)
    assert verify_tushare_daily_normalization_replay(
        lake,
        observation.observation.observation_id,
    ).status == "ABSENT"

    _, normalization, _ = _persist_fact(
        lake,
        _raw([_row(close=2000.0)]),
        event=2,
    )
    original_get = lake.get_normalization
    monkeypatch.setattr(
        lake,
        "get_normalization",
        lambda observation_id: replace(
            normalization,
            normalized_payload={**normalization.normalized_payload, "rows": []},
        ) if observation_id == normalization.source_observation_id else original_get(
            observation_id
        ),
    )
    with pytest.raises(TushareDailyReplayMismatchError):
        verify_tushare_daily_normalization_replay(
            lake,
            normalization.source_observation_id,
        )

    other_root = tmp_path / "old"
    other = initialize_fact_lake(other_root)
    old_candidate = replace(
        build_provider_observation(_capture(_raw(), event=3)),
        normalizer_version="ds-tushare-daily-normalizer-v0.0",
    )
    other.store_observation(
        old_candidate,
        _raw(),
        "application/json",
    )
    before = _tree_snapshot(other_root)
    with pytest.raises(TushareDailyReplayUnsupportedError):
        replay_tushare_daily_normalization(other, old_candidate.observation_id)
    assert _tree_snapshot(other_root) == before


def test_replay_rejects_corrupted_capture_event_binding(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    observation, _ = persist_tushare_daily_evidence(lake, _capture(_raw()))
    observation_id = observation.observation.observation_id
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master"
            " WHERE type='trigger' AND name='observations_guard_update'"
        ).fetchone()[0]
        payload = json.loads(conn.execute(
            "SELECT observation_json FROM observations WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()[0])
        payload["payload"]["capture_event_id"] = "capture-" + ("f" * 32)
        conn.execute("DROP TRIGGER observations_guard_update")
        conn.execute(
            "UPDATE observations SET observation_json = ?"
            " WHERE observation_id = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), observation_id),
        )
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()
    fresh = open_existing_fact_lake(root)
    with pytest.raises(TushareDailyReplayError, match="event binding"):
        replay_tushare_daily_normalization(fresh, observation_id)


def test_fact_binds_trade_date_without_fabricating_report_or_publish_time(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    observation, normalization, fact = _persist_fact(lake, _raw())
    assert observation.observation.trade_date == TRADE_DATE
    assert observation.observation.report_period is None
    assert observation.observation.published_at is None
    assert fact.trade_date == TRADE_DATE
    assert fact.report_period is None
    assert fact.published_at is None
    assert fact.revision_id is None and fact.data_version is None
    assert fact.revision_semantics is RevisionSemantics.IMMUTABLE
    assert fact.canonical_payload["rows"][0]["close"] == 1800.0
    assert normalization.normalizer_version == NORMALIZER_VERSION


def test_publication_replay_mismatch_preserves_raw_normalization_and_history(
    tmp_path,
    monkeypatch,
):
    lake = initialize_fact_lake(tmp_path / "lake")
    observation, normalization, fact = _persist_fact(lake, _raw())
    raw_before = lake.read_payload(observation.observation.observation_id)
    wrong = TushareDailyReplayResult(
        observation_id=observation.observation.observation_id,
        normalizer_version=NORMALIZER_VERSION,
        normalized_payload={**normalization.normalized_payload, "rows": []},
    )
    monkeypatch.setattr(
        daily_module,
        "replay_tushare_daily_normalization",
        lambda *_: wrong,
    )
    with pytest.raises(TushareDailyReplayMismatchError):
        publish_tushare_daily_canonical_fact(lake, fact)
    assert lake.read_payload(observation.observation.observation_id) == raw_before
    assert lake.get_normalization(
        observation.observation.observation_id
    ) == normalization
    assert query_tushare_daily(lake, TRADE_DATE) == ()


def test_generic_temporal_index_rejects_manifest_fact_mismatch(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    observation, normalization, fact = _persist_fact(lake, _raw())
    with pytest.raises(
        FactLakePublicationConflictError,
        match="temporal index disagrees",
    ):
        lake.stage_canonical_publication(
            fact,
            publication_id="publication-wrong-date",
            source_observation_id=observation.observation.observation_id,
            primary_temporal_field=TemporalSemantics.TRADE_DATE,
            primary_temporal_value="2025-12-31",
            normalizer_version=normalization.normalizer_version,
            raw_payload_hash=observation.observation.source_payload_hash,
            artifact_schema_version=ARTIFACT_SCHEMA_VERSION,
            artifact_relpath=(
                "canonical/"
                + ("a" * 64)
                + "/2025-12-31/"
                + ("b" * 64)
                + ".parquet"
            ),
        )


def test_publication_parquet_query_and_as_of_boundary(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    observation, normalization, fact = _persist_fact(lake, _raw())
    publication = publish_tushare_daily_canonical_fact(lake, fact)
    assert publication.primary_temporal_field == "trade_date"
    assert publication.primary_temporal_value == TRADE_DATE
    assert publication.vintage_sequence == 1
    assert publication.normalizer_version == NORMALIZER_VERSION
    assert publication.artifact_schema_version == ARTIFACT_SCHEMA_VERSION
    rows = query_tushare_daily(lake, TRADE_DATE)
    assert len(rows) == 1
    assert rows[0]["source_observation_id"] \
        == observation.observation.observation_id
    assert rows[0]["dataset_contract_revision"] == DATASET_CONTRACT_REVISION
    assert rows[0]["revision_semantics"] == "immutable"
    assert rows[0]["canonical_payload"] == normalization.normalized_payload
    assert query_tushare_daily(
        lake,
        TRADE_DATE,
        selection="publication",
        publication_id=publication.publication_id,
    ) == rows
    with pytest.raises(DataContractError, match="as_of"):
        query_tushare_daily(
            lake,
            TRADE_DATE,
            as_of="2026-07-30T00:00:00Z",
        )


def test_same_state_reobservation_dedups_but_corrections_are_immutable_vintages(
    tmp_path,
):
    lake = initialize_fact_lake(tmp_path / "lake")
    raw_original = _raw([_row()])
    first_observation, _, first_fact = _persist_fact(lake, raw_original, event=1)
    first = publish_tushare_daily_canonical_fact(lake, first_fact)

    second_observation, _, second_fact = _persist_fact(
        lake,
        raw_original,
        event=2,
    )
    same = publish_tushare_daily_canonical_fact(lake, second_fact)
    assert second_observation.observation.observation_id \
        != first_observation.observation.observation_id
    assert second_observation.blob_hash == first_observation.blob_hash
    assert same.publication_id == first.publication_id
    assert same.vintage_sequence == 1

    raw_added = _raw([
        _row(),
        _row(ts_code="000001.SZ", close=12.5),
    ])
    _, _, added_fact = _persist_fact(lake, raw_added, event=3)
    added = publish_tushare_daily_canonical_fact(lake, added_fact)
    assert added.vintage_sequence == 2

    raw_removed = _raw([_row(ts_code="000001.SZ", close=12.5)])
    _, _, removed_fact = _persist_fact(lake, raw_removed, event=4)
    removed = publish_tushare_daily_canonical_fact(lake, removed_fact)
    assert removed.vintage_sequence == 3

    all_rows = query_tushare_daily(
        lake,
        TRADE_DATE,
        selection="all",
    )
    assert [row["vintage_sequence"] for row in all_rows] == [1, 2, 3]
    assert len(all_rows[0]["canonical_payload"]["rows"]) == 1
    assert len(all_rows[1]["canonical_payload"]["rows"]) == 2
    assert len(all_rows[2]["canonical_payload"]["rows"]) == 1
    assert query_tushare_daily(
        lake,
        TRADE_DATE,
    )[0]["publication_id"] == removed.publication_id


def test_orphan_daily_parquet_is_not_visible_until_manifest_commit(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, _, fact = _persist_fact(lake, _raw())

    def fail(point):
        if point == "after_tushare_daily_parquet_durable":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        publish_tushare_daily_canonical_fact(lake, fact, failure_hook=fail)
    assert query_tushare_daily(lake, TRADE_DATE) == ()
    committed = publish_tushare_daily_canonical_fact(lake, fact)
    assert committed.commit_state == "COMMITTED"
    assert len(query_tushare_daily(lake, TRADE_DATE)) == 1


def test_committed_daily_artifact_corruption_fails_closed(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, _, fact = _persist_fact(lake, _raw())
    publication = publish_tushare_daily_canonical_fact(lake, fact)
    lake.canonical_artifact_path(publication.artifact_relpath).write_bytes(b"bad")
    with pytest.raises(FactLakeCorruptedError):
        query_tushare_daily(lake, TRADE_DATE)


def test_shadow_client_path_captures_exact_bytes_without_persisting_request_body(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    raw = _raw()
    placeholder = "test-only-placeholder"
    monkeypatch.setenv("TUSHARE_TOKEN", placeholder)
    monkeypatch.setattr(
        tpc,
        "_utc_now_iso",
        lambda: "2026-07-30T08:00:00.000000Z",
    )
    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        result = run_tushare_daily_shadow(
            TRADE_DATE,
            lake,
        )
    assert request.call_count == 1
    assert lake.read_payload(result.observation.observation.observation_id) == raw
    persisted = json.dumps(
        result.observation.observation.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
    )
    assert placeholder not in persisted
    assert "token" not in persisted.lower()
    assert "raw post body" not in persisted.lower()
    assert result.fact.trade_date == TRADE_DATE
    assert result.fact.published_at is None


def test_shadow_rejects_secret_echo_without_any_fact_lake_persistence(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    sentinel = "TEST_ONLY_SECRET_SENTINEL_FACT_LAKE_ECHO_60a729b3"
    monkeypatch.setenv("TUSHARE_TOKEN", sentinel)
    raw = json.dumps({
        "code": 0,
        "msg": f"provider echoed {sentinel}",
        "data": {
            "fields": list(DAILY_FIELD_MANIFEST),
            "items": [_row()],
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        with pytest.raises(tpc.TushareProtocolError) as exc:
            run_tushare_daily_shadow(
                TRADE_DATE,
                lake,
            )

    assert request.call_count == 1
    assert str(exc.value) == "Tushare 响应包含禁止持久化的敏感材料"
    assert sentinel not in str(exc.value)
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM normalized_observations"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_publications"
        ).fetchone()[0] == 0
    finally:
        conn.close()
    assert list((root / "raw").rglob("*.blob")) == []
    sentinel_bytes = sentinel.encode("utf-8")
    assert all(
        sentinel_bytes not in path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    )


def test_shadow_rejects_json_escaped_secret_echo_without_any_fact_lake_persistence(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    sentinel = 'TEST_ONLY_SECRET_SENTINEL_"\\_FACT_LAKE_ECHO_90b841a2'
    monkeypatch.setenv("TUSHARE_TOKEN", sentinel)
    raw = json.dumps({
        "code": 0,
        "msg": f"provider echoed {sentinel}",
        "data": {
            "fields": list(DAILY_FIELD_MANIFEST),
            "items": [_row()],
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert sentinel.encode("utf-8") not in raw

    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        with pytest.raises(tpc.TushareProtocolError) as exc:
            run_tushare_daily_shadow(
                TRADE_DATE,
                lake,
            )

    assert request.call_count == 1
    assert str(exc.value) == "Tushare 响应包含禁止持久化的敏感材料"
    assert sentinel not in str(exc.value)
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM normalized_observations"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_publications"
        ).fetchone()[0] == 0
    finally:
        conn.close()
    assert list((root / "raw").rglob("*.blob")) == []
    sentinel_bytes = sentinel.encode("utf-8")
    assert all(
        sentinel_bytes not in path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    )


def test_shadow_rejects_stringified_request_json_without_any_fact_lake_persistence(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    sentinel = 'TEST_ONLY_SECRET_"\\_SHADOW_STRINGIFIED'
    monkeypatch.setenv("TUSHARE_TOKEN", sentinel)
    contract = TushareDailyRequestContract(TRADE_DATE)
    body_obj = {
        "api_name": CANONICAL_ENDPOINT,
        "token": sentinel,
        "params": contract.params,
        "fields": DAILY_FIELDS_ARGUMENT,
    }
    body_bytes = json.dumps(
        body_obj, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    body_json_text = body_bytes.decode("utf-8")

    raw = json.dumps({
        "code": 0,
        "msg": body_json_text,
        "data": {
            "fields": list(DAILY_FIELD_MANIFEST),
            "items": [_row()],
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert sentinel.encode("utf-8") not in raw
    assert body_bytes not in raw

    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        with pytest.raises(tpc.TushareProtocolError) as exc:
            run_tushare_daily_shadow(
                TRADE_DATE,
                lake,
            )

    assert request.call_count == 1
    assert str(exc.value) == "Tushare 响应包含禁止持久化的敏感材料"
    assert sentinel not in str(exc.value)
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM normalized_observations"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_publications"
        ).fetchone()[0] == 0
    finally:
        conn.close()
    assert list((root / "raw").rglob("*.blob")) == []
    sentinel_bytes = sentinel.encode("utf-8")
    assert all(
        sentinel_bytes not in path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    )


def test_shadow_rejects_secret_bearing_key_without_any_fact_lake_persistence(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    sentinel = 'TEST_ONLY_SECRET_"\\_SHADOW_KEY_ATTACK'
    monkeypatch.setenv("TUSHARE_TOKEN", sentinel)
    contract = TushareDailyRequestContract(TRADE_DATE)
    body_obj = {
        "api_name": CANONICAL_ENDPOINT,
        "token": sentinel,
        "params": contract.params,
        "fields": DAILY_FIELDS_ARGUMENT,
    }
    body_bytes = json.dumps(
        body_obj, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    body_json_text = body_bytes.decode("utf-8")

    raw_dict = {
        "code": 0,
        "msg": "clean msg",
        "data": {
            "fields": list(DAILY_FIELD_MANIFEST),
            "items": [_row()],
        },
        body_json_text: "attack_key_value",
    }
    raw = json.dumps(raw_dict, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert sentinel.encode("utf-8") not in raw
    assert body_bytes not in raw

    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        with pytest.raises(tpc.TushareProtocolError) as exc:
            run_tushare_daily_shadow(
                TRADE_DATE,
                lake,
            )

    assert request.call_count == 1
    assert str(exc.value) == "Tushare 响应包含禁止持久化的敏感材料"
    assert sentinel not in str(exc.value)
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM normalized_observations"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_publications"
        ).fetchone()[0] == 0
    finally:
        conn.close()
    assert list((root / "raw").rglob("*.blob")) == []
    sentinel_bytes = sentinel.encode("utf-8")
    assert all(
        sentinel_bytes not in path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    )


def test_shadow_rejects_truncated_object_candidate_without_any_fact_lake_persistence(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    sentinel = 'TEST_ONLY_SECRET_"\\_SHADOW_TRUNCATED'
    monkeypatch.setenv("TUSHARE_TOKEN", sentinel)
    escaped_token = json.dumps(sentinel)
    truncated_msg = f'{{"token":{escaped_token}'

    raw = json.dumps({
        "code": 0,
        "msg": truncated_msg,
        "data": {
            "fields": list(DAILY_FIELD_MANIFEST),
            "items": [_row()],
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert sentinel.encode("utf-8") not in raw

    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        with pytest.raises(tpc.TushareProtocolError) as exc:
            run_tushare_daily_shadow(
                TRADE_DATE,
                lake,
            )

    assert request.call_count == 1
    assert str(exc.value) == "Tushare 响应包含禁止持久化的敏感材料"
    assert sentinel not in str(exc.value)
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM normalized_observations"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_publications"
        ).fetchone()[0] == 0
    finally:
        conn.close()
    assert list((root / "raw").rglob("*.blob")) == []
    sentinel_bytes = sentinel.encode("utf-8")
    assert all(
        sentinel_bytes not in path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    )


def test_invalid_provider_response_persists_raw_only_and_never_canonicalizes(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    raw = _raw(code=1001)
    monkeypatch.setenv("TUSHARE_TOKEN", "test-only-placeholder")
    monkeypatch.setattr(
        tpc,
        "_utc_now_iso",
        lambda: "2026-07-30T08:00:00.000000Z",
    )
    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ):
        with pytest.raises(tpc.TushareProtocolError):
            run_tushare_daily_shadow(
                TRADE_DATE,
                lake,
            )
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        observation_rows = conn.execute(
            "SELECT observation_json FROM observations"
        ).fetchall()
        normalization_count = conn.execute(
            "SELECT COUNT(*) FROM normalized_observations"
        ).fetchone()[0]
        publication_count = conn.execute(
            "SELECT COUNT(*) FROM canonical_publications"
        ).fetchone()[0]
    finally:
        conn.close()
    assert len(observation_rows) == 1
    assert json.loads(observation_rows[0][0])["quality_status"] == "invalid"
    assert normalization_count == 0
    assert publication_count == 0


def test_v3_schema_has_generic_temporal_columns_not_trade_date(tmp_path):
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        columns = tuple(
            row[1] for row in conn.execute(
                "PRAGMA table_info(canonical_publications)"
            )
        )
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert version == "fact_lake_control_v3"
    assert "primary_temporal_field" in columns
    assert "primary_temporal_value" in columns
    assert "trade_date" not in columns
    assert open_existing_fact_lake(root).readonly is True
