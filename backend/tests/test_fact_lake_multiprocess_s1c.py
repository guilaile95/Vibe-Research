"""Cross-process offline contracts for DS-L1-S1C Fact Lake hardening.

The workers in this module are fresh ``sys.executable`` interpreters.  File
barriers are used instead of inherited process state so the same tests cover
Windows spawn semantics and POSIX systems without relying on ``fork``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any

import pytest

import short_term_limit_up_pool_adapter as adapter
from fact_lake_store import (
    CONTROL_DB_FILENAME,
    FactLakeCorruptedError,
    FactLakeNormalizationConflictError,
    initialize_fact_lake,
    open_existing_fact_lake,
)
from limit_up_shadow import (
    CANONICAL_ENDPOINT,
    CANONICAL_OPERATION,
    DATASET_ID,
    RawResponseCapture,
    build_canonical_fact,
    build_provider_observation,
    build_request_fingerprint,
    persist_normalization,
    publish_canonical_fact,
    query_limit_up_pool,
)


TRADE_DATE = "2026-07-30"
_PROCESS_TIMEOUT_SECONDS = 30.0
_BARRIER_TIMEOUT_SECONDS = 20.0
_WORKER_SWITCH = "--fact-lake-s1c-worker"


def _metadata(*, fetched_at: str = "2026-07-30T08:00:00Z") -> dict[str, Any]:
    return {
        "operation": CANONICAL_OPERATION,
        "endpoint": CANONICAL_ENDPOINT,
        "requested_trade_date": TRADE_DATE,
        "dpt": "wz.ztzt",
        "page_index": 0,
        "page_size": 10_000,
        "sort": "fbt:asc",
        "http_status": 200,
        "content_type": "application/json; charset=utf-8",
        "fetched_at": fetched_at,
    }


def _snapshot(row_count: int = 1) -> dict[str, Any]:
    rows = [
        {"stock_code": f"{index:06d}", "lbc": index}
        for index in range(1, row_count + 1)
    ]
    return {
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
        "row_count": row_count,
        "legal_zero": False,
        "upstream_null": False,
        "unexplained_empty": False,
        "coverage_warning": False,
        "target_universe_empty_after_filter": False,
        "source_pool_row_count": row_count,
        "http_status": 200,
        "error_class": "NONE",
        "excluded_universe_count": 0,
        "invalid_row_count": 0,
        "duplicate_code_count": 0,
    }


def _capture(
    payload: bytes,
    event_id: str,
    *,
    fetched_at: str = "2026-07-30T08:00:00Z",
) -> RawResponseCapture:
    metadata = _metadata(fetched_at=fetched_at)
    from fact_lake_store import payload_sha256

    return RawResponseCapture(
        capture_event_id=event_id,
        raw_bytes=payload,
        metadata=metadata,
        request_fingerprint=build_request_fingerprint(metadata),
        source_payload_hash=payload_sha256(payload),
        content_type=str(metadata["content_type"]),
        fetched_at=fetched_at,
    )


def _event(index: int) -> str:
    return f"capture-{index:032x}"


def _prepare_raw_observation(
    root: Path,
    *,
    payload: bytes,
    event_id: str,
    row_count: int = 1,
) -> str:
    lake = open_existing_fact_lake(root, readonly=False)
    capture = _capture(payload, event_id)
    snapshot = _snapshot(row_count)
    candidate = build_provider_observation(capture, snapshot)
    stored = lake.store_observation(
        candidate,
        capture.raw_bytes,
        capture.content_type,
    ).stored
    return stored.observation.observation_id


def _prepare_observation(
    root: Path,
    *,
    payload: bytes,
    event_id: str,
    row_count: int = 1,
) -> str:
    # Publication tests must use provider bytes that independently reproduce
    # the persisted normalization.  The caller payload remains a deterministic
    # marker so equivalent/different evidence identities stay explicit.
    provider_payload = json.dumps(
        {
            "date": "20260730",
            "marker": payload.hex(),
            "data": {
                "pool": [
                    {"c": f"{index:06d}", "lbc": index}
                    for index in range(1, row_count + 1)
                ]
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    observation_id = _prepare_raw_observation(
        root,
        payload=provider_payload,
        event_id=event_id,
        row_count=row_count,
    )
    lake = open_existing_fact_lake(root, readonly=False)
    stored = lake.get_observation(observation_id)
    assert stored is not None
    persist_normalization(lake, stored, _snapshot(row_count))
    return observation_id


def _publish_prepared(root: Path, observation_id: str):
    lake = open_existing_fact_lake(root, readonly=False)
    stored = lake.get_observation(observation_id)
    normalization = lake.get_normalization(observation_id)
    assert stored is not None
    assert normalization is not None
    fact = build_canonical_fact(stored.observation, normalization)
    return publish_canonical_fact(lake, fact)


def _write_json_atomic(path: Path, value: Any) -> None:
    candidate = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    candidate.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(candidate, path)


def _wait_for_path(path: Path, timeout: float = _BARRIER_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for IPC path: {path}")
        time.sleep(0.01)


def _worker_action(job: dict[str, Any]) -> dict[str, Any]:
    root = Path(job["root"])
    action = job["action"]

    if action == "persist":
        lake = open_existing_fact_lake(root, readonly=False)
        capture = _capture(
            bytes.fromhex(job["payload_hex"]),
            job["event_id"],
            fetched_at=job.get("fetched_at", "2026-07-30T08:00:00Z"),
        )
        candidate = build_provider_observation(
            capture,
            _snapshot(int(job.get("row_count", 1))),
        )
        result = lake.store_observation(
            candidate,
            capture.raw_bytes,
            capture.content_type,
        )
        return {
            "created": result.created,
            "observation_id": result.stored.observation.observation_id,
            "blob_hash": result.stored.blob_hash,
            "blob_relpath": result.stored.blob_relpath,
        }

    if action == "normalize":
        lake = open_existing_fact_lake(root, readonly=False)
        stored = lake.get_observation(job["observation_id"])
        if stored is None:
            raise AssertionError("normalization source was not committed")
        attempted_count = int(job["row_count"])
        normalization = persist_normalization(
            lake,
            stored,
            _snapshot(attempted_count),
        )
        return {
            "attempted_count": attempted_count,
            "normalized_sha256": normalization.normalized_sha256,
            "normalized_payload": normalization.normalized_payload,
        }

    if action in {"publish", "publish_pause", "publish_crash"}:
        lake = open_existing_fact_lake(root, readonly=False)
        stored = lake.get_observation(job["observation_id"])
        normalization = lake.get_normalization(job["observation_id"])
        if stored is None or normalization is None:
            raise AssertionError("publication source was not prepared")
        fact = build_canonical_fact(stored.observation, normalization)

        def failure_hook(point: str) -> None:
            if point != "before_publication_commit":
                return
            if action == "publish_crash":
                Path(job["crash_ready"]).touch()
                os._exit(77)
            if action == "publish_pause":
                ready = Path(job["commit_ready"])
                proceed = Path(job["commit_continue"])
                ready.touch()
                _wait_for_path(proceed)

        publication = publish_canonical_fact(
            lake,
            fact,
            failure_hook=failure_hook,
        )
        return {
            "publication_id": publication.publication_id,
            "vintage_sequence": publication.vintage_sequence,
            "source_observation_id": publication.source_observation_id,
            "artifact_sha256": publication.artifact_sha256,
            "commit_state": publication.commit_state,
        }

    if action == "query":
        lake = open_existing_fact_lake(root)
        rows = query_limit_up_pool(lake, TRADE_DATE, selection="all")
        return {
            "publications": [
                {
                    "publication_id": row["publication_id"],
                    "vintage_sequence": row["vintage_sequence"],
                }
                for row in rows
            ]
        }

    if action == "query_two_phase":
        lake = open_existing_fact_lake(root)

        def read_ids() -> list[str]:
            return [
                row["publication_id"]
                for row in query_limit_up_pool(
                    lake,
                    TRADE_DATE,
                    selection="all",
                )
            ]

        before = read_ids()
        _write_json_atomic(Path(job["first_result"]), before)
        _wait_for_path(Path(job["query_continue"]))
        after = read_ids()
        return {"before": before, "after": after}

    if action == "drop_schema_index":
        conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
        try:
            conn.execute("DROP INDEX observations_blob_idx")
            conn.commit()
        finally:
            conn.close()
        return {"mutated": "schema"}

    if action == "drift_artifact":
        lake = open_existing_fact_lake(root)
        artifact = lake.canonical_artifact_path(job["artifact_relpath"])
        artifact.write_bytes(b"cross-process-artifact-drift")
        return {"mutated": "artifact"}

    raise AssertionError(f"unknown worker action: {action}")


def _worker_main(job_path: Path) -> int:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    Path(job["ready"]).touch()
    _wait_for_path(Path(job["start"]))
    try:
        result = {
            "status": "ok",
            "tag": job.get("tag"),
            **_worker_action(job),
        }
    except BaseException as exc:
        cause = exc.__cause__
        result = {
            "status": "error",
            "tag": job.get("tag"),
            "error_type": type(exc).__name__,
            "message": str(exc),
            "cause_type": None if cause is None else type(cause).__name__,
            "cause_message": None if cause is None else str(cause),
            "sqlite_errorcode": (
                None if cause is None else getattr(cause, "sqlite_errorcode", None)
            ),
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


def _start_batch(
    root: Path,
    ipc: Path,
    jobs: list[dict[str, Any]],
) -> list[subprocess.Popen[str]]:
    ipc.mkdir(parents=True)
    start = ipc / "start"
    backend_dir = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(backend_dir) + os.pathsep + environment.get(
        "PYTHONPATH",
        "",
    )
    processes: list[subprocess.Popen[str]] = []
    ready_paths: list[Path] = []
    for index, supplied in enumerate(jobs):
        ready = ipc / f"ready-{index}"
        ready_paths.append(ready)
        job = {
            **supplied,
            "root": str(root),
            "ready": str(ready),
            "start": str(start),
        }
        job_path = ipc / f"job-{index}.json"
        _write_json_atomic(job_path, job)
        processes.append(
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), _WORKER_SWITCH, str(job_path)],
                cwd=backend_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    try:
        for ready in ready_paths:
            _wait_for_path(ready)
    except Exception:
        _kill_processes(processes)
        raise
    start.touch()
    return processes


def _kill_processes(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
    for process in processes:
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _finish_batch(
    processes: list[subprocess.Popen[str]],
    *,
    expected_returncode: int | None = 0,
    parse_json: bool = True,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
    completed: list[tuple[int, str, str]] = []
    try:
        for process in processes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, _PROCESS_TIMEOUT_SECONDS)
            stdout, stderr = process.communicate(timeout=remaining)
            completed.append((int(process.returncode), stdout, stderr))
    except subprocess.TimeoutExpired:
        _kill_processes(processes)
        raise AssertionError(
            f"worker batch exceeded {_PROCESS_TIMEOUT_SECONDS:.0f}s hard timeout"
        ) from None

    for returncode, stdout, stderr in completed:
        if expected_returncode is None:
            assert returncode != 0, (
                "hard-exit worker unexpectedly returned success; "
                f"stdout={stdout!r}; stderr={stderr!r}"
            )
        else:
            assert returncode == expected_returncode, (
                f"worker exited {returncode}, expected {expected_returncode}; "
                f"stdout={stdout!r}; stderr={stderr!r}"
            )
    if not parse_json:
        return []

    decoded: list[dict[str, Any]] = []
    for _, stdout, stderr in completed:
        lines = [line for line in stdout.splitlines() if line.strip()]
        assert len(lines) == 1, f"non-deterministic worker stdout={stdout!r}; stderr={stderr!r}"
        decoded.append(json.loads(lines[0]))
    return decoded


def _run_jobs(
    root: Path,
    ipc: Path,
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _finish_batch(_start_batch(root, ipc, jobs))


def _table_count(root: Path, table: str) -> int:
    assert table in {"observations", "normalized_observations", "canonical_publications"}
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def test_same_capture_event_concurrently_persists_one_observation_and_blob(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    job = {
        "action": "persist",
        "payload_hex": b'{"same-event":true}'.hex(),
        "event_id": _event(1),
    }
    results = _run_jobs(root, tmp_path / "ipc-same-event", [job, job])

    assert {result["status"] for result in results} == {"ok"}, results
    assert len({result["observation_id"] for result in results}) == 1
    assert len({result["blob_relpath"] for result in results}) == 1
    assert sorted(result["created"] for result in results) == [False, True]
    assert _table_count(root, "observations") == 1
    assert len(list((root / "raw").rglob("*.blob"))) == 1


def test_distinct_capture_events_same_bytes_persist_two_observations_one_blob(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    common = {
        "action": "persist",
        "payload_hex": b'{"same-bytes":true}'.hex(),
    }
    results = _run_jobs(
        root,
        tmp_path / "ipc-same-bytes",
        [
            {**common, "event_id": _event(2)},
            {**common, "event_id": _event(3)},
        ],
    )

    assert {result["status"] for result in results} == {"ok"}, results
    assert len({result["observation_id"] for result in results}) == 2
    assert len({result["blob_hash"] for result in results}) == 1
    assert len({result["blob_relpath"] for result in results}) == 1
    assert _table_count(root, "observations") == 2
    assert len(list((root / "raw").rglob("*.blob"))) == 1


def test_distinct_bytes_concurrently_persist_distinct_content_hashes(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    results = _run_jobs(
        root,
        tmp_path / "ipc-distinct-bytes",
        [
            {
                "action": "persist",
                "payload_hex": b'{"bytes":"left"}'.hex(),
                "event_id": _event(4),
            },
            {
                "action": "persist",
                "payload_hex": b'{"bytes":"right"}'.hex(),
                "event_id": _event(5),
            },
        ],
    )

    assert {result["status"] for result in results} == {"ok"}
    assert len({result["blob_hash"] for result in results}) == 2
    assert len({result["blob_relpath"] for result in results}) == 2
    assert _table_count(root, "observations") == 2
    assert len(list((root / "raw").rglob("*.blob"))) == 2


def test_same_normalization_concurrently_has_one_authoritative_row(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    observation_id = _prepare_raw_observation(
        root,
        payload=b'{"normalization":"same"}',
        event_id=_event(6),
    )
    job = {
        "action": "normalize",
        "observation_id": observation_id,
        "row_count": 1,
    }
    results = _run_jobs(root, tmp_path / "ipc-normalize-same", [job, job])

    assert {result["status"] for result in results} == {"ok"}
    assert len({result["normalized_sha256"] for result in results}) == 1
    assert _table_count(root, "normalized_observations") == 1


def test_conflicting_normalization_has_one_winner_and_stable_conflict(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    lake = open_existing_fact_lake(root, readonly=False)
    capture = _capture(b'{"normalization":"race"}', _event(7))
    candidate = build_provider_observation(capture, _snapshot(1))
    observation_id = lake.store_observation(
        candidate,
        capture.raw_bytes,
        capture.content_type,
    ).stored.observation.observation_id
    results = _run_jobs(
        root,
        tmp_path / "ipc-normalize-conflict",
        [
            {
                "action": "normalize",
                "tag": "one",
                "observation_id": observation_id,
                "row_count": 1,
            },
            {
                "action": "normalize",
                "tag": "two",
                "observation_id": observation_id,
                "row_count": 2,
            },
        ],
    )
    winners = [result for result in results if result["status"] == "ok"]
    conflicts = [result for result in results if result["status"] == "error"]

    assert len(winners) == 1
    assert len(conflicts) == 1
    assert conflicts[0]["error_type"] == FactLakeNormalizationConflictError.__name__
    assert "conflicting output" in conflicts[0]["message"]
    persisted = lake.get_normalization(observation_id)
    assert persisted is not None
    assert persisted.normalized_payload == winners[0]["normalized_payload"]
    assert _table_count(root, "normalized_observations") == 1

    losing_count = 1 if conflicts[0]["tag"] == "one" else 2
    retry = _run_jobs(
        root,
        tmp_path / "ipc-normalize-conflict-retry",
        [{
            "action": "normalize",
            "tag": conflicts[0]["tag"],
            "observation_id": observation_id,
            "row_count": losing_count,
        }],
    )[0]
    assert retry["status"] == "error"
    assert retry["error_type"] == conflicts[0]["error_type"]
    assert retry["message"] == conflicts[0]["message"]
    assert lake.get_normalization(observation_id) == persisted


def test_same_fact_concurrently_publishes_one_authority(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    observation_id = _prepare_observation(
        root,
        payload=b'{"publication":"same-fact"}',
        event_id=_event(8),
    )
    job = {"action": "publish", "observation_id": observation_id}
    results = _run_jobs(root, tmp_path / "ipc-publish-same", [job, job])

    assert {result["status"] for result in results} == {"ok"}
    assert len({result["publication_id"] for result in results}) == 1
    assert {result["vintage_sequence"] for result in results} == {1}
    assert {result["commit_state"] for result in results} == {"COMMITTED"}
    assert _table_count(root, "canonical_publications") == 1
    assert len(list((root / "canonical").rglob("*.parquet"))) == 1


def test_equivalent_state_from_distinct_observations_deduplicates(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    payload = b'{"publication":"equivalent-events"}'
    left = _prepare_observation(root, payload=payload, event_id=_event(9))
    right = _prepare_observation(root, payload=payload, event_id=_event(10))
    assert left != right
    results = _run_jobs(
        root,
        tmp_path / "ipc-publish-equivalent",
        [
            {"action": "publish", "observation_id": left},
            {"action": "publish", "observation_id": right},
        ],
    )

    assert {result["status"] for result in results} == {"ok"}
    assert len({result["publication_id"] for result in results}) == 1
    assert {result["vintage_sequence"] for result in results} == {1}
    assert _table_count(root, "canonical_publications") == 1
    assert len(list((root / "canonical").rglob("*.parquet"))) == 1


def test_different_canonical_states_same_date_receive_unique_vintages(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    left = _prepare_observation(
        root,
        payload=b'{"publication":"state-one"}',
        event_id=_event(11),
        row_count=1,
    )
    right = _prepare_observation(
        root,
        payload=b'{"publication":"state-two"}',
        event_id=_event(12),
        row_count=2,
    )
    results = _run_jobs(
        root,
        tmp_path / "ipc-publish-vintages",
        [
            {"action": "publish", "observation_id": left},
            {"action": "publish", "observation_id": right},
        ],
    )

    assert {result["status"] for result in results} == {"ok"}
    assert len({result["publication_id"] for result in results}) == 2
    assert {result["vintage_sequence"] for result in results} == {1, 2}
    assert _table_count(root, "canonical_publications") == 2
    visible = _run_jobs(
        root,
        tmp_path / "ipc-publish-vintages-query",
        [{"action": "query"}],
    )[0]
    assert [row["vintage_sequence"] for row in visible["publications"]] == [1, 2]


def test_reader_sees_old_committed_set_then_complete_set_after_commit(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    first_observation = _prepare_observation(
        root,
        payload=b'{"visibility":"old"}',
        event_id=_event(13),
        row_count=1,
    )
    first = _publish_prepared(root, first_observation)
    second_observation = _prepare_observation(
        root,
        payload=b'{"visibility":"new"}',
        event_id=_event(14),
        row_count=2,
    )
    commit_ready = tmp_path / "publisher-before-commit"
    commit_continue = tmp_path / "publisher-continue"
    publisher = _start_batch(
        root,
        tmp_path / "ipc-visibility-publisher",
        [{
            "action": "publish_pause",
            "observation_id": second_observation,
            "commit_ready": str(commit_ready),
            "commit_continue": str(commit_continue),
        }],
    )
    reader: list[subprocess.Popen[str]] = []
    try:
        _wait_for_path(commit_ready)
        first_result = tmp_path / "reader-first-result.json"
        query_continue = tmp_path / "reader-continue"
        reader = _start_batch(
            root,
            tmp_path / "ipc-visibility-reader",
            [{
                "action": "query_two_phase",
                "first_result": str(first_result),
                "query_continue": str(query_continue),
            }],
        )
        _wait_for_path(first_result)
        before = json.loads(first_result.read_text(encoding="utf-8"))
        assert before == [first.publication_id]

        commit_continue.touch()
        published = _finish_batch(publisher)[0]
        assert published["status"] == "ok"
        query_continue.touch()
        observed = _finish_batch(reader)[0]
        reader = []
    finally:
        _kill_processes(publisher)
        _kill_processes(reader)

    assert observed["status"] == "ok"
    assert observed["before"] == [first.publication_id]
    assert len(observed["after"]) == 2
    assert set(observed["after"]) == {
        first.publication_id,
        published["publication_id"],
    }


def test_hard_exit_after_durable_parquet_recovers_in_fresh_process(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    observation_id = _prepare_observation(
        root,
        payload=b'{"crash":"after-durable-parquet"}',
        event_id=_event(15),
    )
    crash_ready = tmp_path / "durable-parquet-before-hard-exit"
    crashed = _start_batch(
        root,
        tmp_path / "ipc-crash",
        [{
            "action": "publish_crash",
            "observation_id": observation_id,
            "crash_ready": str(crash_ready),
        }],
    )
    # POSIX normally reports 77.  A Windows process terminating while DuckDB's
    # native library is loaded can surface a native non-zero status instead;
    # the marker proves that execution reached the precise post-durability hook.
    _finish_batch(crashed, expected_returncode=None, parse_json=False)
    assert crash_ready.is_file()

    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        states = conn.execute(
            "SELECT vintage_sequence, commit_state FROM canonical_publications"
        ).fetchall()
    finally:
        conn.close()
    assert states == [(1, "STAGING")]
    assert len(list((root / "canonical").rglob("*.parquet"))) == 1
    before = _run_jobs(
        root,
        tmp_path / "ipc-crash-query-before",
        [{"action": "query"}],
    )[0]
    assert before == {"status": "ok", "tag": None, "publications": []}

    recovered = _run_jobs(
        root,
        tmp_path / "ipc-crash-recover",
        [{"action": "publish", "observation_id": observation_id}],
    )[0]
    assert recovered["status"] == "ok"
    assert recovered["vintage_sequence"] == 1
    after = _run_jobs(
        root,
        tmp_path / "ipc-crash-query-after",
        [{"action": "query"}],
    )[0]
    assert after["status"] == "ok"
    assert after["publications"] == [{
        "publication_id": recovered["publication_id"],
        "vintage_sequence": 1,
    }]
    assert _table_count(root, "canonical_publications") == 1


def test_stale_handle_rejects_cross_process_schema_drift(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    stale = initialize_fact_lake(root)
    result = _run_jobs(
        root,
        tmp_path / "ipc-schema-drift",
        [{"action": "drop_schema_index"}],
    )[0]
    assert result["status"] == "ok"

    with pytest.raises(FactLakeCorruptedError, match="fingerprint"):
        stale.get_observation("not-present")


def test_stale_handle_rejects_cross_process_artifact_drift(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    stale = initialize_fact_lake(root)
    observation_id = _prepare_observation(
        root,
        payload=b'{"artifact":"before-drift"}',
        event_id=_event(16),
    )
    publication = _publish_prepared(root, observation_id)
    result = _run_jobs(
        root,
        tmp_path / "ipc-artifact-drift",
        [{
            "action": "drift_artifact",
            "artifact_relpath": publication.artifact_relpath,
        }],
    )[0]
    assert result["status"] == "ok"

    with pytest.raises(FactLakeCorruptedError, match="hash mismatch"):
        query_limit_up_pool(stale, TRADE_DATE)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != _WORKER_SWITCH:
        raise SystemExit("this module is only executable as its S1C worker")
    raise SystemExit(_worker_main(Path(sys.argv[2])))
