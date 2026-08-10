"""Deterministic committed-raw replay contracts for DS-L1-S1C."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

import limit_up_shadow as shadow
import short_term_limit_up_pool_adapter as adapter
from fact_lake_store import (
    CONTROL_DB_FILENAME,
    FactLakeCorruptedError,
    initialize_fact_lake,
)


TRADE_DATE = "2026-07-30"
FETCHED_AT = "2026-07-30T08:00:00Z"
CONTENT_TYPE = "application/json; charset=utf-8"


def _raw(*, lbc: int = 2, marker: str = "base") -> bytes:
    return json.dumps(
        {
            "date": "20260730",
            "marker": marker,
            "data": {"pool": [{"c": "000001", "lbc": lbc}]},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _metadata(**overrides):
    value = {
        "operation": shadow.CANONICAL_OPERATION,
        "endpoint": shadow.CANONICAL_ENDPOINT,
        "requested_trade_date": TRADE_DATE,
        "dpt": "wz.ztzt",
        "page_index": 0,
        "page_size": 10_000,
        "sort": "fbt:asc",
        "http_status": 200,
        "content_type": CONTENT_TYPE,
        "fetched_at": FETCHED_AT,
    }
    value.update(overrides)
    return value


def _capture(raw: bytes, **metadata_overrides):
    sink = shadow.RawCaptureBuffer()
    sink(raw, _metadata(**metadata_overrides))
    assert sink.capture is not None
    return sink.capture


def _committed(lake, raw: bytes | None = None):
    raw = _raw() if raw is None else raw
    capture = _capture(raw)
    snapshot = adapter.interpret_limit_up_pool_response_bytes(
        raw,
        requested_trade_date=TRADE_DATE,
        http_status=200,
        observed_at=FETCHED_AT,
    )
    candidate = shadow.build_provider_observation(capture, snapshot)
    stored = lake.store_observation(candidate, raw, CONTENT_TYPE).stored
    return stored, snapshot


def _publication_rows(root: Path) -> int:
    with sqlite3.connect(root / CONTROL_DB_FILENAME) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM canonical_publications").fetchone()[0])


def test_absent_replay_is_pure_and_deterministic_for_one_hundred_runs(tmp_path: Path) -> None:
    lake = initialize_fact_lake(tmp_path / "lake")
    stored, _ = _committed(lake)

    results = [
        shadow.replay_normalization(lake, stored.observation.observation_id)
        for _ in range(100)
    ]

    assert all(result.normalized_payload == results[0].normalized_payload for result in results)
    assert all(result.normalized_sha256 == results[0].normalized_sha256 for result in results)
    verification = shadow.verify_normalization_replay(
        lake,
        stored.observation.observation_id,
    )
    assert verification.status == "ABSENT"
    assert verification.stored_normalization is None
    assert lake.get_normalization(stored.observation.observation_id) is None


def test_explicit_persist_then_verify_match_and_publish(tmp_path: Path) -> None:
    lake = initialize_fact_lake(tmp_path / "lake")
    stored, _ = _committed(lake)
    observation_id = stored.observation.observation_id

    normalization = shadow.persist_replayed_normalization(lake, observation_id)
    verification = shadow.verify_normalization_replay(lake, observation_id)
    fact = shadow.build_canonical_fact(stored.observation, normalization)
    publication = shadow.publish_canonical_fact(lake, fact)

    assert verification.status == "MATCH"
    assert verification.replay.canonical_admissible is True
    assert verification.stored_normalization == normalization
    assert publication.commit_state == "COMMITTED"
    assert publication.vintage_sequence == 1


def test_mismatched_stored_normalization_fails_without_mutating_history(tmp_path: Path) -> None:
    lake = initialize_fact_lake(tmp_path / "lake")
    stored, replay_snapshot = _committed(lake)
    observation_id = stored.observation.observation_id
    forged_snapshot = dict(replay_snapshot)
    forged_snapshot["rows"] = [{"stock_code": "000001", "lbc": 99}]
    forged = shadow.persist_normalization(lake, stored, forged_snapshot)
    before = json.dumps(forged.normalized_payload, sort_keys=True)

    with pytest.raises(shadow.LimitUpReplayMismatchError):
        shadow.verify_normalization_replay(lake, observation_id)
    fact = shadow.build_canonical_fact(stored.observation, forged)
    with pytest.raises(shadow.LimitUpCanonicalAdmissionError):
        shadow.publish_canonical_fact(lake, fact)

    after = lake.get_normalization(observation_id)
    assert after is not None
    assert json.dumps(after.normalized_payload, sort_keys=True) == before
    assert _publication_rows(lake.root) == 0


def test_replay_rejects_corrupt_blob_without_mutating_manifest(tmp_path: Path) -> None:
    lake = initialize_fact_lake(tmp_path / "lake")
    stored, _ = _committed(lake)
    blob = lake.root.joinpath(*stored.blob_relpath.split("/"))
    original = blob.read_bytes()
    blob.write_bytes(b"x" * len(original))

    with pytest.raises(FactLakeCorruptedError):
        shadow.replay_normalization(lake, stored.observation.observation_id)

    assert lake.get_normalization(stored.observation.observation_id) is None
    assert _publication_rows(lake.root) == 0


def test_replay_rejects_corrupt_receipt_and_unsupported_route(tmp_path: Path) -> None:
    lake = initialize_fact_lake(tmp_path / "lake")
    raw = _raw()
    capture = _capture(raw)
    snapshot = adapter.interpret_limit_up_pool_response_bytes(
        raw,
        requested_trade_date=TRADE_DATE,
        http_status=200,
        observed_at=FETCHED_AT,
    )
    candidate = shadow.build_provider_observation(capture, snapshot)
    bad_payload = dict(candidate.payload)
    bad_response = dict(bad_payload["response"])
    bad_response["byte_length"] += 1
    bad_payload["response"] = bad_response
    corrupt = replace(candidate, payload=bad_payload)
    lake.store_observation(corrupt, raw, CONTENT_TYPE)
    with pytest.raises(shadow.LimitUpReplayMetadataError):
        shadow.replay_normalization(lake, corrupt.observation_id)

    other_capture = replace(capture, capture_event_id="capture-" + "1" * 32)
    other = shadow.build_provider_observation(other_capture, snapshot)
    unsupported = replace(
        other,
        provider_id="tushare_pro",
        provider_endpoint="stk_limit",
    )
    lake.store_observation(unsupported, raw, CONTENT_TYPE)
    with pytest.raises(shadow.LimitUpReplayUnsupportedError):
        shadow.replay_normalization(lake, unsupported.observation_id)


def test_replay_is_identical_in_fresh_interpreter(tmp_path: Path) -> None:
    lake = initialize_fact_lake(tmp_path / "lake")
    stored, _ = _committed(lake)
    expected = shadow.replay_normalization(
        lake,
        stored.observation.observation_id,
    )
    script = (
        "import json,sys; "
        "from fact_lake_store import open_existing_fact_lake; "
        "from limit_up_shadow import replay_normalization; "
        "r=replay_normalization(open_existing_fact_lake(sys.argv[1]),sys.argv[2]); "
        "print(json.dumps(r.normalized_payload,sort_keys=True,separators=(',',':')))"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(lake.root),
            stored.observation.observation_id,
        ],
        cwd=Path(shadow.__file__).resolve().parent,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert json.loads(completed.stdout) == expected.normalized_payload


def test_normalizer_version_and_temporal_authorities_remain_unchanged() -> None:
    assert shadow.NORMALIZER_VERSION == "ds-limit-up-pool-normalizer-v0.1"
    assert shadow.LIMIT_UP_DATASET_SPEC.point_in_time_supported is False
    assert shadow.LIMIT_UP_DATASET_SPEC.fetch_semantics.value == "by_date"
    assert shadow.LIMIT_UP_DATASET_SPEC.history_mode.value == "by_date"
