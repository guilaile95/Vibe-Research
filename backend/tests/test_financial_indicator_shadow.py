from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

import financial_indicator_shadow as financial_module
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
from financial_indicator_shadow import (
    ARTIFACT_SCHEMA_VERSION,
    FINANCIAL_FIELDS_ARGUMENT,
    CANONICAL_ENDPOINT,
    DATASET_CONTRACT_REVISION,
    DATASET_ID,
    FIELD_MANIFEST_VERSION,
    FINANCIAL_DATASET_SPEC,
    FINANCIAL_FIELD_MANIFEST,
    FinancialNormalizationError,
    FinancialCaptureError,
    FinancialReplayError,
    MAX_FINANCIAL_ROWS,
    FinancialRawResponseCapture,
    FinancialReplayMismatchError,
    FinancialReplayResult,
    FinancialReplayUnsupportedError,
    FinancialRequestContract,
    NORMALIZER_VERSION,
    build_financial_canonical_fact,
    build_provider_observation,
    build_request_fingerprint,
    normalize_financial_indicator,
    persist_financial_evidence,
    persist_financial_observation,
    publish_financial_canonical_fact,
    query_financial_indicators,
    replay_financial_normalization,
    run_financial_indicator_shadow,
    verify_financial_normalization_replay,
)


TS_CODE = "600519.SH"
REPORT_PERIOD = "2026-03-31"


def _row(
    *,
    ann_date: str = "20260430",
    end_date: str = "20260331",
    update_flag: str = "0",
    eps: object = 2.5,
    **overrides,
) -> list[object]:
    values = {
        "ts_code": TS_CODE,
        "ann_date": ann_date,
        "end_date": end_date,
        "update_flag": update_flag,
        "eps": eps,
        "dt_eps": 2.3,
        "ocfps": None,
        "grossprofit_margin": 91.2,
        "netprofit_margin": 52.1,
        "roe": 8.4,
        "roa": 6.2,
        "debt_to_assets": 19.5,
        "current_ratio": 3.1,
        "assets_turn": 0.13,
        "inv_turn": 0.42,
    }
    values.update(overrides)
    return [values[field] for field in FINANCIAL_FIELD_MANIFEST]


def _raw(
    rows: list[list[object]] | None = None,
    *,
    fields: tuple[str, ...] = FINANCIAL_FIELD_MANIFEST,
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
    fetched_at: str = "2026-05-01T08:00:00.000000Z",
) -> FinancialRawResponseCapture:
    contract = FinancialRequestContract(TS_CODE, REPORT_PERIOD)
    return FinancialRawResponseCapture(
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
    observation, normalization = persist_financial_evidence(
        lake,
        _capture(raw, event),
    )
    fact = build_financial_canonical_fact(
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


def test_dataset_contract_is_report_period_restatable_and_not_pit():
    spec = FINANCIAL_DATASET_SPEC
    assert spec.dataset_id == DATASET_ID
    assert spec.required_temporal_fields == (TemporalSemantics.REPORT_PERIOD,)
    assert spec.revision_semantics is RevisionSemantics.RESTATABLE
    assert spec.point_in_time_supported is False
    assert spec.canonical_route.provider_id == "tushare_pro"
    assert spec.canonical_route.provider_endpoint == "fina_indicator"
    assert len(spec.routes) == 1


def test_request_fingerprint_is_deterministic_and_secret_free():
    contract = FinancialRequestContract(TS_CODE, REPORT_PERIOD)
    assert build_request_fingerprint(contract) == build_request_fingerprint(contract)
    safe = json.dumps(contract.to_safe_dict(), sort_keys=True)
    assert "token" not in safe.lower()
    assert "authorization" not in safe.lower()
    assert contract.params == {"ts_code": TS_CODE, "period": "20260331"}


def test_capture_fingerprint_hash_and_http_status_bind_before_normalization(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    capture = _capture(_raw())
    with pytest.raises(FinancialCaptureError, match="fingerprint"):
        build_provider_observation(
            replace(capture, request_fingerprint="sha256:" + ("0" * 64))
        )
    with pytest.raises(FinancialCaptureError, match="payload hash"):
        build_provider_observation(
            replace(capture, source_payload_hash="sha256:" + ("0" * 64))
        )
    with pytest.raises(FinancialNormalizationError, match="HTTP"):
        persist_financial_evidence(lake, replace(capture, http_status=503))


def test_normalization_preserves_all_revisions_dedupes_exact_rows_and_orders(
    tmp_path,
):
    original = _row(update_flag="0", eps=2.0)
    updated = _row(ann_date="20260502", update_flag="1", eps=2.8)
    raw = _raw([updated, original, original])
    capture = _capture(raw)
    parsed = tpc.interpret_tushare_response_bytes(raw, CANONICAL_ENDPOINT)
    expected = normalize_financial_indicator(
        parsed,
        capture.contract,
        source_observation_id=build_provider_observation(capture).observation_id,
    )
    assert expected["versions"] == [
        {
            field: value
            for field, value in zip(FINANCIAL_FIELD_MANIFEST, original)
        } | {
            field: None if value is None else float(value)
            for field, value in zip(FINANCIAL_FIELD_MANIFEST, original)
            if field not in {"ts_code", "ann_date", "end_date", "update_flag"}
        } | {
            "ann_date": "2026-04-30",
            "end_date": REPORT_PERIOD,
        },
        {
            field: value
            for field, value in zip(FINANCIAL_FIELD_MANIFEST, updated)
        } | {
            field: None if value is None else float(value)
            for field, value in zip(FINANCIAL_FIELD_MANIFEST, updated)
            if field not in {"ts_code", "ann_date", "end_date", "update_flag"}
        } | {
            "ann_date": "2026-05-02",
            "end_date": REPORT_PERIOD,
        },
    ]
    assert expected["provider_row_count"] == 3
    assert expected["unique_version_count"] == 2
    assert expected["exact_duplicate_count"] == 1
    for _ in range(100):
        assert normalize_financial_indicator(
            parsed,
            capture.contract,
            source_observation_id=expected["source_observation_id"],
        ) == expected

    reordered = tpc.interpret_tushare_response_bytes(
        _raw([original, updated, original]),
        CANONICAL_ENDPOINT,
    )
    assert normalize_financial_indicator(
        reordered,
        capture.contract,
        source_observation_id=expected["source_observation_id"],
    ) == expected


@pytest.mark.parametrize(
    ("rows", "fields", "message"),
    [
        ([], FINANCIAL_FIELD_MANIFEST, "empty"),
        ([_row()[:-1]], FINANCIAL_FIELD_MANIFEST[:-1], "manifest"),
        ([_row(ts_code="000001.SZ")], FINANCIAL_FIELD_MANIFEST, "ts_code"),
        ([_row(end_date="20260230")], FINANCIAL_FIELD_MANIFEST, "end_date"),
        ([_row(ann_date="20260431")], FINANCIAL_FIELD_MANIFEST, "ann_date"),
        ([_row(update_flag=1)], FINANCIAL_FIELD_MANIFEST, "update_flag"),
        ([_row(eps=True)], FINANCIAL_FIELD_MANIFEST, "finite number"),
        ([_row(eps=float("nan"))], FINANCIAL_FIELD_MANIFEST, "finite number"),
        ([_row(eps=float("inf"))], FINANCIAL_FIELD_MANIFEST, "finite number"),
        ([_row(eps="")], FINANCIAL_FIELD_MANIFEST, "finite number"),
    ],
)
def test_financial_normalizer_fails_closed(rows, fields, message):
    raw = _raw(rows, fields=fields)
    parsed = tpc.interpret_tushare_response_bytes(raw, CANONICAL_ENDPOINT)
    with pytest.raises(FinancialNormalizationError, match=message):
        normalize_financial_indicator(
            parsed,
            FinancialRequestContract(TS_CODE, REPORT_PERIOD),
            source_observation_id="obs-test",
        )


def test_financial_dataset_row_limit_fails_closed():
    raw = _raw([_row()] * (MAX_FINANCIAL_ROWS + 1))
    parsed = tpc.interpret_tushare_response_bytes(raw, CANONICAL_ENDPOINT)
    with pytest.raises(FinancialNormalizationError, match="row limit"):
        normalize_financial_indicator(
            parsed,
            FinancialRequestContract(TS_CODE, REPORT_PERIOD),
            source_observation_id="obs-test",
        )


def test_replay_from_committed_raw_matches_without_using_stored_input(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    observation, normalization, fact = _persist_fact(lake, _raw())
    replay = replay_financial_normalization(
        lake,
        observation.observation.observation_id,
    )
    assert replay.normalized_payload == normalization.normalized_payload
    assert verify_financial_normalization_replay(
        lake,
        observation.observation.observation_id,
    ).status == "MATCH"
    assert fact.canonical_payload == replay.normalized_payload
    for _ in range(100):
        assert replay_financial_normalization(
            lake,
            observation.observation.observation_id,
        ) == replay


def test_replay_absent_mismatch_and_unsupported_are_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    capture = _capture(_raw())
    observation = persist_financial_observation(lake, capture)
    assert verify_financial_normalization_replay(
        lake,
        observation.observation.observation_id,
    ).status == "ABSENT"

    _, normalization, _ = _persist_fact(
        lake,
        _raw([_row(eps=3.0)]),
        event=2,
    )
    original_get = lake.get_normalization
    monkeypatch.setattr(
        lake,
        "get_normalization",
        lambda observation_id: replace(
            normalization,
            normalized_payload={**normalization.normalized_payload, "versions": []},
        ) if observation_id == normalization.source_observation_id else original_get(
            observation_id
        ),
    )
    with pytest.raises(FinancialReplayMismatchError):
        verify_financial_normalization_replay(
            lake,
            normalization.source_observation_id,
        )

    other_root = tmp_path / "old"
    other = initialize_fact_lake(other_root)
    old_candidate = replace(
        build_provider_observation(_capture(_raw(), event=3)),
        normalizer_version="ds-financial-indicator-normalizer-v0.0",
    )
    other.store_observation(
        old_candidate,
        _raw(),
        "application/json",
    )
    before = _tree_snapshot(other_root)
    with pytest.raises(FinancialReplayUnsupportedError):
        replay_financial_normalization(other, old_candidate.observation_id)
    assert _tree_snapshot(other_root) == before


def test_replay_rejects_corrupted_capture_event_binding(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    observation, _ = persist_financial_evidence(lake, _capture(_raw()))
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
    with pytest.raises(FinancialReplayError, match="event binding"):
        replay_financial_normalization(fresh, observation_id)


def test_fact_binds_report_period_without_fabricating_trade_or_publish_time(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    observation, normalization, fact = _persist_fact(lake, _raw())
    assert observation.observation.report_period == REPORT_PERIOD
    assert observation.observation.trade_date is None
    assert observation.observation.published_at is None
    assert fact.report_period == REPORT_PERIOD
    assert fact.trade_date is None
    assert fact.published_at is None
    assert fact.revision_id is None and fact.data_version is None
    assert fact.revision_semantics is RevisionSemantics.RESTATABLE
    assert fact.canonical_payload["versions"][0]["ann_date"] == "2026-04-30"
    assert "2026-04-30T00:00:00Z" not in json.dumps(fact.to_dict())
    assert normalization.normalizer_version == NORMALIZER_VERSION


def test_publication_replay_mismatch_preserves_raw_normalization_and_history(
    tmp_path,
    monkeypatch,
):
    lake = initialize_fact_lake(tmp_path / "lake")
    observation, normalization, fact = _persist_fact(lake, _raw())
    raw_before = lake.read_payload(observation.observation.observation_id)
    wrong = FinancialReplayResult(
        observation_id=observation.observation.observation_id,
        normalizer_version=NORMALIZER_VERSION,
        normalized_payload={**normalization.normalized_payload, "versions": []},
    )
    monkeypatch.setattr(
        financial_module,
        "replay_financial_normalization",
        lambda *_: wrong,
    )
    with pytest.raises(FinancialReplayMismatchError):
        publish_financial_canonical_fact(lake, fact)
    assert lake.read_payload(observation.observation.observation_id) == raw_before
    assert lake.get_normalization(
        observation.observation.observation_id
    ) == normalization
    assert query_financial_indicators(lake, TS_CODE, REPORT_PERIOD) == ()


def test_generic_temporal_index_rejects_manifest_fact_mismatch(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    observation, normalization, fact = _persist_fact(lake, _raw())
    with pytest.raises(
        FactLakePublicationConflictError,
        match="temporal index disagrees",
    ):
        lake.stage_canonical_publication(
            fact,
            publication_id="publication-wrong-period",
            source_observation_id=observation.observation.observation_id,
            primary_temporal_field=TemporalSemantics.REPORT_PERIOD,
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
    publication = publish_financial_canonical_fact(lake, fact)
    assert publication.primary_temporal_field == "report_period"
    assert publication.primary_temporal_value == REPORT_PERIOD
    assert publication.vintage_sequence == 1
    assert publication.normalizer_version == NORMALIZER_VERSION
    assert publication.artifact_schema_version == ARTIFACT_SCHEMA_VERSION
    rows = query_financial_indicators(lake, TS_CODE, REPORT_PERIOD)
    assert len(rows) == 1
    assert rows[0]["source_observation_id"] \
        == observation.observation.observation_id
    assert rows[0]["dataset_contract_revision"] == DATASET_CONTRACT_REVISION
    assert rows[0]["revision_semantics"] == "restatable"
    assert rows[0]["canonical_payload"] == normalization.normalized_payload
    assert query_financial_indicators(
        lake,
        TS_CODE,
        REPORT_PERIOD,
        selection="publication",
        publication_id=publication.publication_id,
    ) == rows
    with pytest.raises(DataContractError, match="as_of"):
        query_financial_indicators(
            lake,
            TS_CODE,
            REPORT_PERIOD,
            as_of="2026-05-01T00:00:00Z",
        )


def test_same_state_reobservation_dedups_but_restatements_are_immutable_vintages(
    tmp_path,
):
    lake = initialize_fact_lake(tmp_path / "lake")
    raw_original = _raw([_row(update_flag="0", eps=2.0)])
    first_observation, _, first_fact = _persist_fact(lake, raw_original, event=1)
    first = publish_financial_canonical_fact(lake, first_fact)

    second_observation, _, second_fact = _persist_fact(
        lake,
        raw_original,
        event=2,
    )
    same = publish_financial_canonical_fact(lake, second_fact)
    assert second_observation.observation.observation_id \
        != first_observation.observation.observation_id
    assert second_observation.blob_hash == first_observation.blob_hash
    assert same.publication_id == first.publication_id
    assert same.vintage_sequence == 1

    raw_added = _raw([
        _row(update_flag="0", eps=2.0),
        _row(ann_date="20260502", update_flag="1", eps=2.8),
    ])
    _, _, added_fact = _persist_fact(lake, raw_added, event=3)
    added = publish_financial_canonical_fact(lake, added_fact)
    assert added.vintage_sequence == 2

    raw_removed = _raw([_row(ann_date="20260502", update_flag="1", eps=2.8)])
    _, _, removed_fact = _persist_fact(lake, raw_removed, event=4)
    removed = publish_financial_canonical_fact(lake, removed_fact)
    assert removed.vintage_sequence == 3

    all_rows = query_financial_indicators(
        lake,
        TS_CODE,
        REPORT_PERIOD,
        selection="all",
    )
    assert [row["vintage_sequence"] for row in all_rows] == [1, 2, 3]
    assert len(all_rows[0]["canonical_payload"]["versions"]) == 1
    assert len(all_rows[1]["canonical_payload"]["versions"]) == 2
    assert len(all_rows[2]["canonical_payload"]["versions"]) == 1
    assert query_financial_indicators(
        lake,
        TS_CODE,
        REPORT_PERIOD,
    )[0]["publication_id"] == removed.publication_id


def test_orphan_financial_parquet_is_not_visible_until_manifest_commit(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, _, fact = _persist_fact(lake, _raw())

    def fail(point):
        if point == "after_financial_parquet_durable":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        publish_financial_canonical_fact(lake, fact, failure_hook=fail)
    assert query_financial_indicators(lake, TS_CODE, REPORT_PERIOD) == ()
    committed = publish_financial_canonical_fact(lake, fact)
    assert committed.commit_state == "COMMITTED"
    assert len(query_financial_indicators(lake, TS_CODE, REPORT_PERIOD)) == 1


def test_committed_financial_artifact_corruption_fails_closed(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, _, fact = _persist_fact(lake, _raw())
    publication = publish_financial_canonical_fact(lake, fact)
    lake.canonical_artifact_path(publication.artifact_relpath).write_bytes(b"bad")
    with pytest.raises(FactLakeCorruptedError):
        query_financial_indicators(lake, TS_CODE, REPORT_PERIOD)


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
        lambda: "2026-05-01T08:00:00.000000Z",
    )
    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        result = run_financial_indicator_shadow(
            TS_CODE,
            REPORT_PERIOD,
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
    assert result.fact.trade_date is None
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
            "fields": list(FINANCIAL_FIELD_MANIFEST),
            "items": [_row()],
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        with pytest.raises(tpc.TushareProtocolError) as exc:
            run_financial_indicator_shadow(
                TS_CODE,
                REPORT_PERIOD,
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
            "fields": list(FINANCIAL_FIELD_MANIFEST),
            "items": [_row()],
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert sentinel.encode("utf-8") not in raw

    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        with pytest.raises(tpc.TushareProtocolError) as exc:
            run_financial_indicator_shadow(
                TS_CODE,
                REPORT_PERIOD,
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
    contract = FinancialRequestContract(TS_CODE, REPORT_PERIOD)
    body_obj = {
        "api_name": CANONICAL_ENDPOINT,
        "token": sentinel,
        "params": contract.params,
        "fields": FINANCIAL_FIELDS_ARGUMENT,
    }
    body_bytes = json.dumps(
        body_obj, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    body_json_text = body_bytes.decode("utf-8")

    raw = json.dumps({
        "code": 0,
        "msg": body_json_text,
        "data": {
            "fields": list(FINANCIAL_FIELD_MANIFEST),
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
            run_financial_indicator_shadow(
                TS_CODE,
                REPORT_PERIOD,
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
    contract = FinancialRequestContract(TS_CODE, REPORT_PERIOD)
    body_obj = {
        "api_name": CANONICAL_ENDPOINT,
        "token": sentinel,
        "params": contract.params,
        "fields": FINANCIAL_FIELDS_ARGUMENT,
    }
    body_bytes = json.dumps(
        body_obj, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    body_json_text = body_bytes.decode("utf-8")

    raw_dict = {
        "code": 0,
        "msg": "clean msg",
        "data": {
            "fields": list(FINANCIAL_FIELD_MANIFEST),
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
            run_financial_indicator_shadow(
                TS_CODE,
                REPORT_PERIOD,
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
            "fields": list(FINANCIAL_FIELD_MANIFEST),
            "items": [_row()],
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert sentinel.encode("utf-8") not in raw

    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ) as request:
        with pytest.raises(tpc.TushareProtocolError) as exc:
            run_financial_indicator_shadow(
                TS_CODE,
                REPORT_PERIOD,
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
        lambda: "2026-05-01T08:00:00.000000Z",
    )
    with mock.patch(
        "urllib.request.urlopen",
        return_value=_Response(raw),
    ):
        with pytest.raises(tpc.TushareProtocolError):
            run_financial_indicator_shadow(
                TS_CODE,
                REPORT_PERIOD,
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
