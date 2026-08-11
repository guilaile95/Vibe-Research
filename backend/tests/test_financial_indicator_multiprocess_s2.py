"""Bounded fresh-process publication checks for DS-L1-S2."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any

from fact_lake_store import (
    CONTROL_DB_FILENAME,
    initialize_fact_lake,
    open_existing_fact_lake,
)
from financial_indicator_shadow import (
    FINANCIAL_FIELD_MANIFEST,
    FinancialRawResponseCapture,
    FinancialRequestContract,
    build_financial_canonical_fact,
    build_request_fingerprint,
    persist_financial_evidence,
    publish_financial_canonical_fact,
    query_financial_indicators,
    replay_financial_normalization,
)
from fact_lake_store import payload_sha256


TS_CODE = "600519.SH"
REPORT_PERIOD = "2026-03-31"
_WORKER_SWITCH = "--financial-s2-worker"
_PROCESS_TIMEOUT = 30.0
_BARRIER_TIMEOUT = 20.0


def _row(eps: float = 2.5, *, update_flag: str = "0") -> list[Any]:
    values = {
        "ts_code": TS_CODE,
        "ann_date": "20260430" if update_flag == "0" else "20260502",
        "end_date": "20260331",
        "update_flag": update_flag,
        "eps": eps,
        "dt_eps": eps - 0.1,
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
    return [values[field] for field in FINANCIAL_FIELD_MANIFEST]


def _raw(eps: float = 2.5, *, update_flag: str = "0") -> bytes:
    return json.dumps({
        "code": 0,
        "msg": "synthetic",
        "data": {
            "fields": list(FINANCIAL_FIELD_MANIFEST),
            "items": [_row(eps, update_flag=update_flag)],
        },
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _capture(raw: bytes, event: int) -> FinancialRawResponseCapture:
    contract = FinancialRequestContract(TS_CODE, REPORT_PERIOD)
    return FinancialRawResponseCapture(
        capture_event_id=f"capture-{event:032x}",
        contract=contract,
        raw_bytes=raw,
        request_fingerprint=build_request_fingerprint(contract),
        source_payload_hash=payload_sha256(raw),
        http_status=200,
        content_type="application/json; charset=utf-8",
        fetched_at=f"2026-05-01T08:00:{event % 60:02d}.000000Z",
    )


def _write_json_atomic(path: Path, value: Any) -> None:
    candidate = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    candidate.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(candidate, path)


def _wait(path: Path, timeout: float = _BARRIER_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {path}")
        time.sleep(0.01)


def _worker(job: dict[str, Any]) -> dict[str, Any]:
    root = Path(job["root"])
    action = job["action"]
    if action == "query":
        rows = query_financial_indicators(
            open_existing_fact_lake(root),
            TS_CODE,
            REPORT_PERIOD,
            selection=job.get("selection", "all"),
        )
        return {"rows": rows}
    if action == "replay":
        replay = replay_financial_normalization(
            open_existing_fact_lake(root),
            job["observation_id"],
        )
        return {
            "observation_id": replay.observation_id,
            "normalized_payload": replay.normalized_payload,
        }

    lake = open_existing_fact_lake(root, readonly=False)
    raw = bytes.fromhex(job["payload_hex"])
    observation, normalization = persist_financial_evidence(
        lake,
        _capture(raw, int(job["event"])),
    )
    result: dict[str, Any] = {
        "observation_id": observation.observation.observation_id,
        "blob_hash": observation.blob_hash,
        "normalization_sha256": normalization.normalized_sha256,
    }
    if action == "persist":
        return result
    fact = build_financial_canonical_fact(
        observation.observation,
        normalization,
    )

    def hook(point: str) -> None:
        if point != "after_financial_parquet_durable" \
                or "entered" not in job:
            return
        _write_json_atomic(Path(job["entered"]), {"pid": os.getpid()})
        _wait(Path(job["release"]))

    publication = publish_financial_canonical_fact(
        lake,
        fact,
        failure_hook=hook,
    )
    result.update({
        "publication_id": publication.publication_id,
        "vintage_sequence": publication.vintage_sequence,
    })
    return result


def _worker_main() -> int:
    job_path = Path(sys.argv[2])
    result_path = Path(sys.argv[3])
    try:
        result = {"ok": True, "value": _worker(json.loads(
            job_path.read_text(encoding="utf-8")
        ))}
    except BaseException as exc:
        result = {"ok": False, "type": type(exc).__name__, "message": str(exc)}
    _write_json_atomic(result_path, result)
    return 0 if result["ok"] else 1


def _start(tmp_path: Path, index: int, job: dict[str, Any]):
    job_path = tmp_path / f"job-{index}.json"
    result_path = tmp_path / f"result-{index}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    environment = os.environ.copy()
    backend = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = backend + os.pathsep + environment.get(
        "PYTHONPATH", ""
    )
    process = subprocess.Popen(
        [sys.executable, __file__, _WORKER_SWITCH, str(job_path), str(result_path)],
        cwd=backend,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, result_path


def _finish(process, result_path: Path) -> dict[str, Any]:
    stdout, stderr = process.communicate(timeout=_PROCESS_TIMEOUT)
    assert result_path.is_file(), (process.returncode, stdout, stderr)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert process.returncode == 0 and result["ok"], (result, stdout, stderr)
    return result["value"]


def _run_pair(tmp_path: Path, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    running = [_start(tmp_path, index, job) for index, job in enumerate(jobs)]
    return [_finish(process, result) for process, result in running]


def test_processes_same_event_are_idempotent(tmp_path):
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    raw = _raw()
    job = {
        "action": "persist",
        "root": str(root),
        "payload_hex": raw.hex(),
        "event": 1,
    }
    results = _run_pair(tmp_path, [job, job])
    assert len({item["observation_id"] for item in results}) == 1
    assert len({item["blob_hash"] for item in results}) == 1
    conn = sqlite3.connect(root / CONTROL_DB_FILENAME)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE dataset_id = ?",
            ("ds_financial_indicator",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
    assert len(tuple((root / "raw").rglob("*.blob"))) == 1


def test_fresh_process_replays_committed_exact_raw(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    observation, normalization = persist_financial_evidence(
        lake,
        _capture(_raw(), 1),
    )
    result = _run_pair(tmp_path, [{
        "action": "replay",
        "root": str(root),
        "observation_id": observation.observation.observation_id,
    }])[0]
    assert result["observation_id"] == observation.observation.observation_id
    assert result["normalized_payload"] == normalization.normalized_payload


def test_processes_distinct_events_same_bytes_share_blob(tmp_path):
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    raw = _raw()
    jobs = [{
        "action": "persist",
        "root": str(root),
        "payload_hex": raw.hex(),
        "event": event,
    } for event in (1, 2)]
    results = _run_pair(tmp_path, jobs)
    assert len({item["observation_id"] for item in results}) == 2
    assert len({item["blob_hash"] for item in results}) == 1
    assert len(tuple((root / "raw").rglob("*.blob"))) == 1


def test_processes_same_canonical_state_converge_to_one_publication(tmp_path):
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    raw = _raw()
    jobs = [{
        "action": "publish",
        "root": str(root),
        "payload_hex": raw.hex(),
        "event": event,
    } for event in (1, 2)]
    results = _run_pair(tmp_path, jobs)
    assert {item["vintage_sequence"] for item in results} == {1}
    assert len({item["publication_id"] for item in results}) == 1
    assert len(query_financial_indicators(
        open_existing_fact_lake(root),
        TS_CODE,
        REPORT_PERIOD,
        selection="all",
    )) == 1


def test_processes_different_states_receive_unique_local_vintages(tmp_path):
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    jobs = [
        {
            "action": "publish",
            "root": str(root),
            "payload_hex": _raw(2.5, update_flag="0").hex(),
            "event": 1,
        },
        {
            "action": "publish",
            "root": str(root),
            "payload_hex": _raw(2.8, update_flag="1").hex(),
            "event": 2,
        },
    ]
    results = _run_pair(tmp_path, jobs)
    assert {item["vintage_sequence"] for item in results} == {1, 2}
    assert len({item["publication_id"] for item in results}) == 2
    rows = query_financial_indicators(
        open_existing_fact_lake(root),
        TS_CODE,
        REPORT_PERIOD,
        selection="all",
    )
    assert [row["vintage_sequence"] for row in rows] == [1, 2]


def test_reader_sees_old_committed_set_until_writer_commit(tmp_path):
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    first_job = {
        "action": "publish",
        "root": str(root),
        "payload_hex": _raw(2.5, update_flag="0").hex(),
        "event": 1,
    }
    first = _run_pair(tmp_path, [first_job])[0]
    entered = tmp_path / "entered.json"
    release = tmp_path / "release.json"
    writer_job = {
        "action": "publish",
        "root": str(root),
        "payload_hex": _raw(2.8, update_flag="1").hex(),
        "event": 2,
        "entered": str(entered),
        "release": str(release),
    }
    writer, result_path = _start(tmp_path, 10, writer_job)
    _wait(entered)
    reader_job = {
        "action": "query",
        "root": str(root),
        "selection": "all",
    }
    before = _run_pair(tmp_path, [reader_job])[0]["rows"]
    assert [row["publication_id"] for row in before] == [
        first["publication_id"]
    ]
    _write_json_atomic(release, {"continue": True})
    second = _finish(writer, result_path)
    after = _run_pair(tmp_path, [reader_job])[0]["rows"]
    assert [row["publication_id"] for row in after] == [
        first["publication_id"],
        second["publication_id"],
    ]


if __name__ == "__main__" and len(sys.argv) > 1 \
        and sys.argv[1] == _WORKER_SWITCH:
    raise SystemExit(_worker_main())
