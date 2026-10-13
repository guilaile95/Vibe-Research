"""Real temporary archive -> verified replay -> public HTTP, with no providers."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket
import sqlite3

import httpx
import pytest

import app
import astock
from fact_lake_store import CONTROL_DB_FILENAME, FactLake, initialize_fact_lake
import limit_up_shadow as shadow
import short_term_limit_up_pool_adapter as adapter
import short_term_seal_quality_service as service

DAY = "2026-07-30"


def publish(lake, *, day=DAY, boards=1, quality=True):
    row = {"c": "000001", "lbc": boards}
    if quality:
        row.update(fbt=93000, lbt=143000, zbc=1)
    payload = json.dumps({"date": day.replace("-", ""), "data": {"pool": [row]}}, separators=(",", ":")).encode()
    captured = f"{day}T07:05:00Z"
    sink = shadow.RawCaptureBuffer()
    sink(payload, {
        "operation": shadow.CANONICAL_OPERATION, "endpoint": shadow.CANONICAL_ENDPOINT,
        "requested_trade_date": day, "dpt": "wz.ztzt", "page_index": 0,
        "page_size": 10_000, "sort": "fbt:asc", "http_status": 200,
        "content_type": "application/json", "fetched_at": captured,
    })
    snapshot = adapter.interpret_limit_up_pool_response_bytes(payload, requested_trade_date=day, http_status=200, observed_at=captured)
    observation = shadow.persist_raw_observation(lake, sink.capture, snapshot)
    normalized = shadow.persist_replayed_normalization(lake, observation.observation.observation_id)
    fact = shadow.build_canonical_fact(observation.observation, normalized)
    return shadow.publish_canonical_fact(lake, fact)


def tree(root):
    return {str(p.relative_to(root)): ("link", str(p.readlink())) if p.is_symlink() else
            ("file", hashlib.sha256(p.read_bytes()).hexdigest()) if p.is_file() else ("dir",)
            for p in root.rglob("*")} if root.exists() else {}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.delenv("VR_FACT_LAKE_ROOT", raising=False)


@pytest.fixture
def archived(monkeypatch, tmp_path):
    root = tmp_path / "archive"
    lake = initialize_fact_lake(root)
    publication = publish(lake)
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(root))
    return root, lake, publication


@pytest.fixture
def http_get(monkeypatch):
    # Windows asyncio makes its own socketpair; prepare exactly one loop first.
    loop = asyncio.new_event_loop()
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append("forbidden")
        raise AssertionError("external effect forbidden")
    for owner, name in (
        (socket.socket, "connect"), (socket.socket, "connect_ex"), (socket, "create_connection"), (socket, "getaddrinfo"),
        (astock, "em_get"), (shadow, "run_limit_up_shadow"),
        (asyncio, "new_event_loop"), (asyncio.events, "new_event_loop"),
        (FactLake, "store_observation"), (FactLake, "store_normalization"),
        (FactLake, "stage_canonical_publication"), (FactLake, "commit_canonical_publication"),
        (FactLake, "append_reconciliation"), (FactLake, "publish_canonical_artifact"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    async def get(path, headers=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://testserver") as client:
            return await client.get(path, headers=headers)
    try:
        yield lambda path, headers=None: loop.run_until_complete(get(path, headers))
        assert attempts == []
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def test_archive_to_actual_registered_http_route_is_byte_immutable(archived, http_get):
    root, _, publication = archived
    before = tree(root)
    response = http_get(f"/api/market/seal-quality?trade_date={DAY}")
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "normal"
    assert result["projection"]["metrics"]["ever_opened_ratio"] == 1
    assert result["projection"]["finality"] == "NOT_ESTABLISHED"
    assert result["selection"]["selection_mode"] == "local_latest"
    assert result["selection"]["point_in_time_claim"] == "NONE"
    assert result["archive_identity"]["publication_id"] == publication.publication_id
    assert result["archive_identity"]["source_observation_id"] == publication.source_observation_id
    assert result["archive_identity"]["raw_payload_hash"] == publication.raw_payload_hash
    assert tree(root) == before


def test_unconnected_and_missing_root_do_not_create_files(monkeypatch, tmp_path, http_get):
    before = tree(tmp_path)
    result = http_get(f"/api/market/seal-quality?trade_date={DAY}").json()["data"]
    assert result["reason_codes"] == ["ARCHIVE_NOT_CONNECTED"]
    root = tmp_path / "not-created" / "nested"
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(root))
    result = http_get(f"/api/market/seal-quality?trade_date={DAY}").json()["data"]
    assert result["reason_codes"] == ["ARCHIVE_NOT_INITIALIZED"]
    assert not root.exists() and tree(tmp_path) == before


def test_missing_requested_date_never_falls_back_to_available_date(archived, http_get):
    root, _, _ = archived
    before = tree(root)
    result = http_get("/api/market/seal-quality?trade_date=2026-07-29").json()["data"]
    assert result["reason_codes"] == ["ARCHIVE_OBSERVATION_MISSING"]
    assert result["projection"] is None and tree(root) == before


@pytest.mark.parametrize("suffix", [
    "", "?trade_date=2026-02-30", "?trade_date=20260730",
    f"?trade_date={DAY}&as_of=2026-07-30T00:00:00Z", f"?trade_date={DAY}&observed_at=x",
    f"?trade_date={DAY}&root=/tmp/elsewhere", f"?trade_date={DAY}&path=/tmp/elsewhere",
    f"?trade_date={DAY}&selection=all", f"?trade_date={DAY}&trade_date={DAY}",
])
def test_only_exact_date_query_is_supported(suffix, http_get):
    assert http_get(f"/api/market/seal-quality{suffix}").status_code == 422


def test_older_archive_without_quality_fields_is_unavailable_not_zero(monkeypatch, tmp_path):
    lake = initialize_fact_lake(tmp_path / "archive")
    publish(lake, quality=False)
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(lake.root))
    before = tree(lake.root)
    result = service.query_seal_quality(DAY)
    assert result["reason_codes"] == ["QUALITY_FIELDS_INCOMPLETE"]
    assert result["archive_identity"] and result["projection"]["sample_count"] == 1
    assert all(value is None for value in result["projection"]["metrics"].values())
    assert tree(lake.root) == before


def test_local_latest_uses_existing_selection_not_source_chronology(archived):
    root, lake, first = archived
    second = publish(lake, boards=2)
    before = tree(root)
    result = service.query_seal_quality(DAY)
    assert second.vintage_sequence > first.vintage_sequence
    assert result["archive_identity"]["publication_id"] == second.publication_id
    assert result["projection"]["rows"][0]["lbc"] == 2
    assert result["selection"]["selection_basis"] == "local_vintage_sequence"
    assert result["selection"]["provider_revision_claim"] == "NONE"
    assert tree(root) == before


def test_corrupt_raw_fails_closed_without_echo_or_repair(archived, http_get):
    root, lake, publication = archived
    stored = lake.get_observation(publication.source_observation_id)
    (root / stored.blob_relpath).write_bytes(b"PRIVATE_SENTINEL bad raw")
    before = tree(root)
    response = http_get(f"/api/market/seal-quality?trade_date={DAY}")
    assert response.json()["data"]["reason_codes"] == ["ARCHIVE_VALIDATION_FAILED"]
    assert "PRIVATE_SENTINEL" not in response.text and str(root) not in response.text
    assert tree(root) == before


@pytest.mark.parametrize("kind", ["root", "raw"])
def test_symlink_archive_or_raw_rejected(archived, monkeypatch, tmp_path, kind):
    root, lake, publication = archived
    if kind == "root":
        link = tmp_path / "linked-archive"
        try:
            link.symlink_to(root, target_is_directory=True)
        except OSError:
            pytest.skip("platform does not permit synthetic symlink")
        monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(link))
    else:
        stored = lake.get_observation(publication.source_observation_id)
        path = root / stored.blob_relpath
        original = path.read_bytes()
        outside = tmp_path / "outside-payload"
        outside.write_bytes(original)
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            pytest.skip("platform does not permit synthetic symlink")
    before = tree(root)
    result = service.query_seal_quality(DAY)
    assert result["reason_codes"] == ["ARCHIVE_VALIDATION_FAILED"]
    assert tree(root) == before


@pytest.mark.parametrize("field,value", [
    ("raw_payload_hash", "sha256:" + "0" * 64), ("normalizer_version", "unknown-version"),
    ("source_observation_id", "missing-observation"),
])
def test_selected_publication_binding_must_match_replay(archived, monkeypatch, field, value):
    _, _, publication = archived
    monkeypatch.setattr(FactLake, "list_canonical_publications", lambda *args, **kwargs: (replace(publication, **{field: value}),))
    result = service.query_seal_quality(DAY)
    assert result["projection"] is None and result["status"] == "unavailable"


def test_read_errors_never_expose_paths_or_error_text(monkeypatch):
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", "/PRIVATE_SENTINEL/path")
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_SENTINEL https://provider.invalid/secret")
    monkeypatch.setattr(service, "open_existing_fact_lake_snapshot", fail)
    result = service.query_seal_quality(DAY)
    assert result["reason_codes"] == ["ARCHIVE_VALIDATION_FAILED"]
    assert "PRIVATE_SENTINEL" not in json.dumps(result)


def test_actual_route_inherits_hostile_origin_and_api_key_boundary(monkeypatch, http_get):
    calls = []
    monkeypatch.setattr(service, "query_seal_quality", lambda day: calls.append(day) or {"trade_date": day})
    path = f"/api/market/seal-quality?trade_date={DAY}"
    assert http_get(path, {"Origin": "https://hostile.invalid"}).status_code == 403
    assert calls == []
    monkeypatch.setattr(app, "_API_KEY", "synthetic-test-key")
    assert http_get(path).status_code == 401
    assert http_get(path, {"Authorization": "Bearer wrong"}).status_code == 401
    assert calls == []
    assert http_get(path, {"Authorization": "Bearer synthetic-test-key"}).status_code == 200
    assert calls == [DAY]


@pytest.mark.parametrize("version,code", [("fact_lake_control_v999", "ARCHIVE_VERSION_UNSUPPORTED"), ("broken", "ARCHIVE_VALIDATION_FAILED")])
def test_bad_schema_is_not_migrated_or_repaired(archived, version, code):
    root, _, _ = archived
    with sqlite3.connect(root / CONTROL_DB_FILENAME) as connection:
        connection.execute("UPDATE schema_meta SET value=? WHERE key='schema_version'", (version,))
    before = tree(root)
    assert service.query_seal_quality(DAY)["reason_codes"] == [code]
    assert tree(root) == before


def test_corrupt_committed_receipt_is_not_trusted(archived, monkeypatch):
    _, lake, publication = archived
    stored = lake.get_observation(publication.source_observation_id)
    receipt = json.loads(json.dumps(stored.observation.payload))
    receipt["request"]["requested_trade_date"] = "2026-07-29"
    tampered = replace(stored, observation=replace(stored.observation, payload=receipt))
    monkeypatch.setattr(FactLake, "get_observation", lambda *args: tampered)
    result = service.query_seal_quality(DAY)
    assert result["reason_codes"] == ["ARCHIVE_VALIDATION_FAILED"]


def test_ambiguous_local_publication_sequence_is_rejected(archived, monkeypatch):
    _, _, publication = archived
    other = replace(publication, publication_id="other-synthetic-publication")
    monkeypatch.setattr(FactLake, "list_canonical_publications", lambda *args, **kwargs: (publication, other))
    assert service.query_seal_quality(DAY)["reason_codes"] == ["ARCHIVE_VALIDATION_FAILED"]
