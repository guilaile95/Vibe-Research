from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from data_contracts import (
    AdjustmentSemantics,
    FetchSemantics,
    HistoryMode,
    ProviderObservation,
    QualityStatus,
    ReconciliationResult,
    ReconciliationStatus,
    RevisionSemantics,
)
from fact_lake_store import (
    CONTROL_DB_FILENAME,
    SCHEMA_VERSION,
    FactLakeCorruptedError,
    FactLakeHashMismatchError,
    FactLakeNotInitializedError,
    FactLakeObservationConflictError,
    FactLakePathError,
    FactLakeReadOnlyError,
    FactLakeSchemaVersionError,
    initialize_fact_lake,
    open_existing_fact_lake,
    payload_sha256,
)


def _observation(
    payload_bytes: bytes,
    *,
    observation_id: str = "obs-001",
    dataset_id: str = "dataset.daily-bars",
    provider_id: str = "provider.primary",
    **overrides,
) -> ProviderObservation:
    values = {
        "observation_id": observation_id,
        "dataset_id": dataset_id,
        "provider_id": provider_id,
        "provider_endpoint": "https://provider.invalid/daily",
        "provider_symbol": "000001.SZ",
        "request_fingerprint": "request:2026-08-08:000001.SZ",
        "source_payload_hash": payload_sha256(payload_bytes),
        "normalizer_version": "normalizer/v1",
        "payload": {"provider_row_count": 1, "note": "not raw bytes"},
        "fetch_semantics": FetchSemantics.BY_DATE,
        "history_mode": HistoryMode.BY_DATE,
        "fetched_at": "2026-08-08T08:00:00Z",
        "effective_at": None,
        "published_at": None,
        "observed_at": None,
        "trade_date": "2026-08-08",
        "report_period": None,
        "revision_id": None,
        "data_version": None,
        "revision_semantics": RevisionSemantics.IMMUTABLE,
        "adjustment_semantics": AdjustmentSemantics.UNADJUSTED,
        "quality_status": QualityStatus.VALID,
        "reason_codes": (),
    }
    values.update(overrides)
    return ProviderObservation(**values)


def _reconciliation() -> ReconciliationResult:
    return ReconciliationResult(
        dataset_id="dataset.daily-bars",
        status=ReconciliationStatus.MISMATCH,
        comparison_policy_id="exact-pairwise",
        comparison_policy_version="v1",
        comparison_evidence={"field": "close", "tolerance": 0},
        left_observation_id="obs-001",
        right_observation_id="obs-002",
        left_value={"close": 10.0},
        right_value={"close": 10.1},
        reason_codes=("VALUE_MISMATCH",),
    )


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, int, str | None]]:
    if not root.exists():
        return {}
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


def _sqlite_state(path: Path) -> tuple[bytes, int, tuple, tuple, str]:
    raw = path.read_bytes()
    conn = sqlite3.connect(path)
    try:
        master = tuple(
            conn.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            )
        )
        try:
            metadata = tuple(
                conn.execute("SELECT key, value FROM schema_meta ORDER BY key")
            )
        except sqlite3.DatabaseError:
            metadata = ()
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        conn.close()
    return raw, len(raw), master, metadata, journal_mode


def _make_version_only_database(root: Path, version: str) -> Path:
    root.mkdir()
    (root / "raw").mkdir()
    db_path = root / CONTROL_DB_FILENAME
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (version,),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.mark.parametrize("readonly", [True, False])
def test_normal_open_missing_path_zero_write(tmp_path: Path, readonly: bool) -> None:
    root = tmp_path / "missing-lake"
    before = _tree_snapshot(root)

    with pytest.raises(FactLakeNotInitializedError):
        open_existing_fact_lake(root, readonly=readonly)

    assert _tree_snapshot(root) == before == {}
    assert not root.exists()


def test_normal_open_existing_directory_without_db_zero_write(tmp_path: Path) -> None:
    root = tmp_path / "empty-root"
    root.mkdir()
    marker = root / "user-marker.bin"
    marker.write_bytes(b"preserve-me")
    before = _tree_snapshot(root)

    with pytest.raises(FactLakeNotInitializedError):
        open_existing_fact_lake(root)

    assert _tree_snapshot(root) == before


def test_explicit_initialize_and_current_version_open_are_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)

    assert lake.readonly is False
    assert (root / CONTROL_DB_FILENAME).is_file()
    assert (root / "raw").is_dir()
    before = _tree_snapshot(root)

    assert initialize_fact_lake(root).readonly is False
    assert open_existing_fact_lake(root).readonly is True
    assert open_existing_fact_lake(root, readonly=False).readonly is False
    assert _tree_snapshot(root) == before


@pytest.mark.parametrize(
    "operation",
    [
        lambda root: open_existing_fact_lake(root),
        lambda root: open_existing_fact_lake(root, readonly=False),
        lambda root: initialize_fact_lake(root),
    ],
)
def test_unsupported_newer_schema_zero_mutation(tmp_path: Path, operation) -> None:
    root = tmp_path / "future"
    db_path = _make_version_only_database(root, "fact_lake_control_v999")
    before_tree = _tree_snapshot(root)
    before_sqlite = _sqlite_state(db_path)

    with pytest.raises(FactLakeSchemaVersionError):
        operation(root)

    assert _tree_snapshot(root) == before_tree
    assert _sqlite_state(db_path) == before_sqlite
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()


def test_older_schema_requires_explicit_migration_without_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "older"
    db_path = _make_version_only_database(root, "fact_lake_control_v0")
    before = _tree_snapshot(root)

    with pytest.raises(FactLakeSchemaVersionError):
        open_existing_fact_lake(root, readonly=False)

    assert _tree_snapshot(root) == before
    assert _sqlite_state(db_path)[3] == (
        ("schema_version", "fact_lake_control_v0"),
    )


def test_long_lived_write_handle_rechecks_version_before_any_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    future_root = tmp_path / "future-source"
    future_db = _make_version_only_database(
        future_root, "fact_lake_control_v999"
    )
    future_db.replace(root / CONTROL_DB_FILENAME)
    before = _tree_snapshot(root)
    payload = b"must-not-write"

    with pytest.raises(FactLakeSchemaVersionError):
        lake.store_observation(
            _observation(payload), payload, "application/octet-stream"
        )

    assert _tree_snapshot(root) == before
    assert not Path(f"{root / CONTROL_DB_FILENAME}-wal").exists()
    assert not Path(f"{root / CONTROL_DB_FILENAME}-shm").exists()


def test_corrupt_schema_metadata_and_layout_fail_closed(tmp_path: Path) -> None:
    corrupt_root = tmp_path / "corrupt-version"
    _make_version_only_database(corrupt_root, "not-a-version")
    with pytest.raises(FactLakeCorruptedError):
        open_existing_fact_lake(corrupt_root)

    layout_root = tmp_path / "corrupt-layout"
    initialize_fact_lake(layout_root)
    conn = sqlite3.connect(layout_root / CONTROL_DB_FILENAME)
    try:
        conn.execute("DROP TABLE reconciliation_results")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(FactLakeCorruptedError):
        open_existing_fact_lake(layout_root)


def test_source_hash_mismatch_is_rejected_before_manifest_or_blob_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    payload = b"exact-provider-bytes"
    observation = _observation(
        payload,
        source_payload_hash=payload_sha256(b"different"),
    )

    with pytest.raises(FactLakeHashMismatchError):
        lake.store_observation(observation, payload, "application/octet-stream")

    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    finally:
        conn.close()
    assert list((root / "raw").rglob("*.blob")) == []


def test_exact_bytes_persist_and_restart_readability(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    payload = b"\x00\xffprovider\r\nbytes\x00"
    observation = _observation(payload)
    result = initialize_fact_lake(root).store_observation(
        observation,
        payload,
        "application/octet-stream",
    )

    assert result.created is True
    assert result.stored.observation == observation
    assert result.stored.commit_state == "COMMITTED"
    assert result.stored.blob_hash == payload_sha256(payload)

    reopened = open_existing_fact_lake(root)
    assert reopened.get_observation(observation.observation_id) == result.stored
    assert reopened.read_payload(observation.observation_id) == payload


def test_exact_replay_is_idempotent_and_changed_payload_conflicts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    first_payload = b"first"
    first = _observation(first_payload)

    first_result = lake.store_observation(first, first_payload, "application/json")
    replay = lake.store_observation(first, first_payload, "application/json")
    assert first_result.created is True
    assert replay.created is False
    assert replay.stored == first_result.stored

    changed_payload = b"changed"
    changed = _observation(changed_payload, observation_id=first.observation_id)
    with pytest.raises(FactLakeObservationConflictError):
        lake.store_observation(changed, changed_payload, "application/json")

    changed_metadata = _observation(
        first_payload,
        observation_id=first.observation_id,
        provider_symbol="000002.SZ",
    )
    with pytest.raises(FactLakeObservationConflictError):
        lake.store_observation(changed_metadata, first_payload, "application/json")

    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    finally:
        conn.close()


def test_two_observation_ids_may_reference_same_blob(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    payload = b"shared-content"
    left = _observation(payload, observation_id="obs-left")
    right = _observation(payload, observation_id="obs-right")

    left_result = lake.store_observation(left, payload, "application/json")
    right_result = lake.store_observation(right, payload, "application/json")

    assert left_result.stored.blob_relpath == right_result.stored.blob_relpath
    assert len(list((root / "raw").rglob("*.blob"))) == 1
    assert lake.read_payload("obs-left") == payload
    assert lake.read_payload("obs-right") == payload


def test_path_control_tokens_are_rejected_without_escape(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    payload = b"payload"
    observation = _observation(payload, dataset_id="../../outside")

    with pytest.raises(FactLakePathError):
        lake.store_observation(observation, payload, "application/json")

    assert not (tmp_path / "outside").exists()
    assert list((root / "raw").rglob("*.blob")) == []


def test_staging_manifest_is_not_visible_when_blob_publication_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    payload = b"payload"
    observation = _observation(payload)

    def fail_before_publish(destination: Path, supplied: bytes) -> None:
        raise OSError("simulated pre-publication crash")

    monkeypatch.setattr(lake, "_publish_blob", fail_before_publish)
    with pytest.raises(OSError, match="pre-publication"):
        lake.store_observation(observation, payload, "application/json")

    assert lake.get_observation(observation.observation_id) is None
    assert list((root / "raw").rglob("*.blob")) == []
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        assert conn.execute(
            "SELECT commit_state FROM observations WHERE observation_id = ?",
            (observation.observation_id,),
        ).fetchone()[0] == "STAGING"
    finally:
        conn.close()


def test_orphan_blob_not_visible_and_exact_retry_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    payload = b"orphan-then-recover"
    observation = _observation(payload)

    def fail_after_publish(observation_id: str):
        raise RuntimeError("simulated manifest crash")

    monkeypatch.setattr(lake, "_commit_observation", fail_after_publish)
    with pytest.raises(RuntimeError, match="manifest crash"):
        lake.store_observation(observation, payload, "application/json")

    assert lake.get_observation(observation.observation_id) is None
    assert len(list((root / "raw").rglob("*.blob"))) == 1

    recovered = open_existing_fact_lake(root, readonly=False)
    result = recovered.store_observation(observation, payload, "application/json")
    assert result.created is False
    assert recovered.read_payload(observation.observation_id) == payload


def test_committed_observation_is_immutable_at_api_and_sqlite_layers(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    payload = b"immutable"
    observation = _observation(payload)
    lake = initialize_fact_lake(root)
    lake.store_observation(observation, payload, "application/json")

    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE observations SET content_type = 'text/plain'"
                " WHERE observation_id = ?",
                (observation.observation_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute(
                "DELETE FROM observations WHERE observation_id = ?",
                (observation.observation_id,),
            )
    finally:
        conn.close()

    assert lake.read_payload(observation.observation_id) == payload


def test_read_only_handle_rejects_writes(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    readonly = open_existing_fact_lake(root)
    payload = b"payload"

    with pytest.raises(FactLakeReadOnlyError):
        readonly.store_observation(
            _observation(payload), payload, "application/json"
        )
    with pytest.raises(FactLakeReadOnlyError):
        readonly.append_reconciliation(_reconciliation())


def test_null_and_unknown_temporal_semantics_roundtrip_exactly(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    payload = b"unknown"
    observation = _observation(
        payload,
        fetch_semantics=FetchSemantics.SNAPSHOT,
        history_mode=HistoryMode.SNAPSHOT_ONLY,
        effective_at=None,
        published_at=None,
        observed_at=None,
        trade_date=None,
        report_period=None,
        revision_id=None,
        data_version=None,
        revision_semantics=RevisionSemantics.UNKNOWN,
        adjustment_semantics=AdjustmentSemantics.UNKNOWN,
        quality_status=QualityStatus.UNKNOWN,
        reason_codes=("SOURCE_SEMANTICS_UNKNOWN",),
    )

    lake = initialize_fact_lake(root)
    lake.store_observation(observation, payload, "application/json")
    restored = open_existing_fact_lake(root).get_observation(
        observation.observation_id
    )

    assert restored is not None
    assert restored.observation.to_dict() == observation.to_dict()
    assert restored.observation.published_at is None
    assert restored.observation.trade_date is None
    assert restored.observation.revision_id is None
    assert restored.observation.quality_status is QualityStatus.UNKNOWN


def test_reconciliation_append_and_read_roundtrip_preserves_disagreement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    result = _reconciliation()

    first = lake.append_reconciliation(result)
    second = lake.append_reconciliation(result)
    restored = open_existing_fact_lake(root).list_reconciliations(
        dataset_id=result.dataset_id
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [item.result.to_dict() for item in restored] == [
        result.to_dict(),
        result.to_dict(),
    ]
    assert all(
        item.result.status is ReconciliationStatus.MISMATCH for item in restored
    )

    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE reconciliation_results SET dataset_id = 'changed'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute("DELETE FROM reconciliation_results")
    finally:
        conn.close()


def test_committed_blob_corruption_fails_closed_without_repair(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    payload = b"original"
    observation = _observation(payload)
    lake = initialize_fact_lake(root)
    stored = lake.store_observation(
        observation, payload, "application/octet-stream"
    ).stored
    blob_path = root.joinpath(*stored.blob_relpath.split("/"))
    blob_path.write_bytes(b"tampered")
    before = blob_path.read_bytes()

    with pytest.raises(FactLakeCorruptedError, match="blob is corrupted"):
        open_existing_fact_lake(root).get_observation(observation.observation_id)

    assert blob_path.read_bytes() == before


def test_only_explicit_tmp_root_is_touched(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "forbidden-home"
    fake_data = tmp_path / "forbidden-data"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("VR_DATA_DIR", str(fake_data))
    root = tmp_path / "explicit-lake"

    lake = initialize_fact_lake(root)
    payload = b"isolated"
    lake.store_observation(_observation(payload), payload, "application/json")

    assert root.is_dir()
    assert not fake_home.exists()
    assert not fake_data.exists()
    assert all(root in path.parents for path in root.rglob("*") if path != root)


def test_schema_version_constant_is_current_v1() -> None:
    assert SCHEMA_VERSION == "fact_lake_control_v1"
