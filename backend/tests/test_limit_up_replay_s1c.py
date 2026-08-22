"""Deterministic committed-raw replay contracts for DS-L1-S1C."""

from __future__ import annotations

from dataclasses import replace
import hashlib
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
    SCHEMA_VERSION as FACT_LAKE_SCHEMA_VERSION,
    initialize_fact_lake,
    open_existing_fact_lake,
)


TRADE_DATE = "2026-07-30"
FETCHED_AT = "2026-07-30T08:00:00Z"
CONTENT_TYPE = "application/json; charset=utf-8"
NORMALIZER_V01 = "ds-limit-up-pool-normalizer-v0.1"
NORMALIZER_V02 = "ds-limit-up-pool-normalizer-v0.3"


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


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, int, str | None]]:
    snapshot: dict[str, tuple[str, int, int, str | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[relative] = ("file", stat.st_size, stat.st_mtime_ns, digest)
        else:
            snapshot[relative] = ("dir", 0, stat.st_mtime_ns, None)
    return snapshot


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
    visible = shadow.query_limit_up_pool(lake, TRADE_DATE)

    assert stored.observation.normalizer_version == NORMALIZER_V02
    assert verification.status == "MATCH"
    assert verification.replay.canonical_admissible is True
    assert (
        verification.replay.normalized_payload["normalizer_version"]
        == NORMALIZER_V02
    )
    assert verification.stored_normalization == normalization
    assert normalization.normalizer_version == NORMALIZER_V02
    assert (
        normalization.normalized_payload["normalizer_version"]
        == NORMALIZER_V02
    )
    assert fact.canonical_payload["normalizer_version"] == NORMALIZER_V02
    assert fact.provenance_chain[0].normalizer_version == NORMALIZER_V02
    assert publication.commit_state == "COMMITTED"
    assert publication.vintage_sequence == 1
    assert publication.normalizer_version == NORMALIZER_V02
    assert visible[0]["normalizer_version"] == NORMALIZER_V02
    assert visible[0]["canonical_payload"]["normalizer_version"] == NORMALIZER_V02
    assert (
        visible[0]["canonical_fact"]["provenance_chain"][0]["normalizer_version"]
        == NORMALIZER_V02
    )


def test_committed_v01_observation_is_readable_but_replay_is_unsupported_and_pure(
    tmp_path: Path,
) -> None:
    lake = initialize_fact_lake(tmp_path / "lake")
    raw = _raw(marker="legacy-v0.1")
    capture = _capture(raw)
    snapshot = adapter.interpret_limit_up_pool_response_bytes(
        raw,
        requested_trade_date=TRADE_DATE,
        http_status=200,
        observed_at=FETCHED_AT,
    )
    current = shadow.build_provider_observation(capture, snapshot)
    legacy = replace(current, normalizer_version=NORMALIZER_V01)
    stored = lake.store_observation(legacy, raw, CONTENT_TYPE).stored
    observation_id = stored.observation.observation_id

    before = lake.get_observation(observation_id)
    assert before == stored
    assert before.observation.normalizer_version == NORMALIZER_V01
    assert lake.read_payload(observation_id) == raw
    tree_before = _tree_snapshot(lake.root)

    with pytest.raises(shadow.LimitUpReplayUnsupportedError):
        shadow.replay_normalization(lake, observation_id)
    with pytest.raises(shadow.LimitUpReplayUnsupportedError):
        shadow.verify_normalization_replay(lake, observation_id)
    with pytest.raises(shadow.LimitUpReplayUnsupportedError):
        shadow.persist_replayed_normalization(lake, observation_id)

    assert _tree_snapshot(lake.root) == tree_before
    db_path = lake.root / CONTROL_DB_FILENAME
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()
    assert lake.get_observation(observation_id) == before
    assert lake.read_payload(observation_id) == raw
    assert lake.get_normalization(observation_id) is None
    assert _publication_rows(lake.root) == 0


def test_committed_v01_publication_remains_queryable_without_replay_or_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    raw = _raw(marker="legacy-v0.1-publication")
    capture = _capture(raw)
    snapshot = adapter.interpret_limit_up_pool_response_bytes(
        raw,
        requested_trade_date=TRADE_DATE,
        http_status=200,
        observed_at=FETCHED_AT,
    )

    # Build one frozen pre-R1 publication through the accepted v0.1 contract.
    with monkeypatch.context() as legacy_runtime:
        legacy_runtime.setattr(shadow, "NORMALIZER_VERSION", NORMALIZER_V01)
        stored = shadow.persist_raw_observation(lake, capture, snapshot)
        normalization = shadow.persist_normalization(lake, stored, snapshot)
        fact = shadow.build_canonical_fact(stored.observation, normalization)
        publication = shadow.publish_canonical_fact(lake, fact)
    artifact = lake.canonical_artifact_path(publication.artifact_relpath)
    artifact_before = artifact.read_bytes()

    # Current S1C-R1 can reopen and query committed history without replay.
    assert shadow.NORMALIZER_VERSION == NORMALIZER_V02
    reopened = open_existing_fact_lake(root)
    visible = shadow.query_limit_up_pool(
        reopened,
        TRADE_DATE,
        selection="publication",
        publication_id=publication.publication_id,
    )

    assert len(visible) == 1
    assert visible[0]["publication_id"] == publication.publication_id
    assert visible[0]["normalizer_version"] == NORMALIZER_V01
    assert lake.get_observation(stored.observation.observation_id) == stored
    assert lake.get_normalization(stored.observation.observation_id) == normalization
    assert artifact.read_bytes() == artifact_before
    assert _publication_rows(lake.root) == 1


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
    assert shadow.NORMALIZER_VERSION == NORMALIZER_V02
    assert shadow.DATASET_CONTRACT_REVISION == "ds-limit-up-pool-contract-v0.1"
    assert shadow.LIMIT_UP_DATASET_SPEC.governance_revision_id == (
        "ds-limit-up-pool-contract-v0.1"
    )
    assert shadow.ARTIFACT_SCHEMA_VERSION == "ds-limit-up-pool-parquet-v0.1"
    assert FACT_LAKE_SCHEMA_VERSION == "fact_lake_control_v3"
    assert shadow.LIMIT_UP_DATASET_SPEC.point_in_time_supported is False
    assert shadow.LIMIT_UP_DATASET_SPEC.fetch_semantics.value == "by_date"
    assert shadow.LIMIT_UP_DATASET_SPEC.history_mode.value == "by_date"
