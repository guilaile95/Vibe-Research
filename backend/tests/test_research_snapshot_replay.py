"""Offline generation replay and fail-closed integrity acceptance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import factor_validation as fv
import factor_validation_router
import research_data_plane as rdp
import research_data_plane_router
from test_factor_validation import _write_series_fixture
from test_research_data_plane import CSV, _source


def _import(tmp_path, *, revised=False, imported_at="2026-08-25T00:00:00Z"):
    source = _source(tmp_path, CSV.replace(",11,13,10,12,", ",11,15,10,14,") if revised else CSV)
    return rdp.import_csv(source, root=tmp_path / "rdp", imported_at=imported_at)


@pytest.mark.parametrize("query,kwargs,key", [
    (rdp.query_daily_bars, {"code": "600519", "date_to": "2026-08-21"}, "rows"),
    (rdp.query_full_market, {"as_of": "2026-08-21", "latest": False}, "rows"),
    (rdp.query_patterns, {"as_of": "2026-08-21", "latest": False}, "events"),
])
def test_two_generation_replay_preserves_content_and_receipt(tmp_path, query, kwargs, key):
    first = _import(tmp_path)
    root = tmp_path / "rdp"
    before = query(root=root, **kwargs)
    second = _import(tmp_path, revised=True, imported_at="2026-08-26T00:00:00Z")
    current = query(root=root, **kwargs)
    replay = query(root=root, snapshot_id=first["snapshot_id"], **kwargs)
    assert current["snapshot_id"] == second["snapshot_id"] != first["snapshot_id"]
    assert replay[key] == before[key]
    assert replay["replay_receipt"] == before["replay_receipt"]
    assert replay["replay_receipt"]["historical_public_availability"] == "NOT_PROVEN"
    assert str(tmp_path) not in json.dumps(replay)
    assert replay["adjustment"] == "UNADJUSTED"
    if key == "rows":
        assert current[key] != before[key]


def test_same_artifact_different_metadata_has_distinct_snapshot_without_duplicate_parquet(tmp_path):
    first = _import(tmp_path)
    second = _import(tmp_path, imported_at="2026-08-26T00:00:00Z")
    assert first["artifact_sha256"] == second["artifact_sha256"]
    assert first["snapshot_id"] != second["snapshot_id"]
    assert len(list((tmp_path / "rdp" / "artifacts").glob("*.parquet"))) == 1
    assert len(list((tmp_path / "rdp" / "snapshots").glob("*.json"))) == 2
    assert _import(tmp_path, imported_at="2026-08-26T00:00:00Z") == second


@pytest.mark.parametrize("snapshot_id", ["../manifest", "/tmp/x", "https://host/snapshot", "A" * 64, "", 42])
def test_malformed_snapshot_is_rejected_without_latest_fallback(tmp_path, snapshot_id):
    _import(tmp_path)
    with pytest.raises(rdp.ResearchDataPlaneQueryValidationError):
        rdp.query_daily_bars(root=tmp_path / "rdp", snapshot_id=snapshot_id)


@pytest.mark.parametrize("failure", ["unknown", "invalid_json", "invalid_utf8", "metadata_drift", "artifact_drift", "missing_artifact"])
def test_snapshot_integrity_failures_never_fall_back(tmp_path, failure):
    first = _import(tmp_path)
    _import(tmp_path, revised=True)
    root = tmp_path / "rdp"
    snapshot_id = first["snapshot_id"]
    archive = root / "snapshots" / f"{snapshot_id}.json"
    artifact = root / "artifacts" / first["artifact_file"]
    if failure == "unknown":
        snapshot_id = "0" * 64
    elif failure == "invalid_json":
        archive.write_text("{")
    elif failure == "invalid_utf8":
        archive.write_bytes(b"\xff")
    elif failure == "metadata_drift":
        payload = json.loads(archive.read_text())
        payload["source_name"] = "changed.csv"
        archive.write_text(json.dumps(payload))
    elif failure == "artifact_drift":
        artifact.write_bytes(b"changed")
    else:
        artifact.unlink()
    with pytest.raises((rdp.ResearchDataPlaneValidationError, rdp.ResearchDataPlaneUnavailableError)):
        rdp.query_daily_bars(root=root, snapshot_id=snapshot_id)
    assert rdp.query_daily_bars(root=root)["snapshot_id"] != first["snapshot_id"]


def test_matching_snapshot_digest_still_reuses_manifest_metadata_validation(tmp_path):
    _import(tmp_path)
    root = tmp_path / "rdp"
    payload = json.loads((root / "manifest.json").read_text())
    payload["row_count"] += 1
    canonical = rdp._canonical_bytes(payload)
    digest = hashlib.sha256(canonical).hexdigest()
    (root / "snapshots" / f"{digest}.json").write_bytes(canonical)
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="metadata does not match"):
        rdp.read_manifest(root, snapshot_id=digest)


@pytest.mark.parametrize("stage", ["archive", "current"])
def test_interrupted_publication_preserves_previous_current_and_pinned_result(tmp_path, monkeypatch, stage):
    first = _import(tmp_path)
    root = tmp_path / "rdp"
    before = rdp.query_daily_bars(root=root)
    original = rdp.os.link if stage == "archive" else rdp.os.replace

    def interrupt(source, target):
        if stage == "archive" or Path(target).name == "manifest.json":
            raise OSError("simulated interrupted publication")
        return original(source, target)

    monkeypatch.setattr(rdp.os, "link" if stage == "archive" else "replace", interrupt)
    with pytest.raises((OSError, rdp.ResearchDataPlaneUnavailableError)):
        _import(tmp_path, revised=True)
    assert rdp.query_daily_bars(root=root) == before
    assert rdp.query_daily_bars(root=root, snapshot_id=first["snapshot_id"]) == before
    # A snapshot published before current-pointer failure remains complete/replayable.
    for path in (root / "snapshots").glob("*.json"):
        assert rdp.read_manifest(root, snapshot_id=path.stem)["snapshot_id"] == path.stem
    assert not list(root.rglob("*.tmp"))


def test_legacy_current_archives_only_validated_metadata(tmp_path):
    first = _import(tmp_path)
    root = tmp_path / "rdp"
    archive = root / "snapshots" / f"{first['snapshot_id']}.json"
    archive.unlink()  # emulate pre-snapshot current schema, no fabricated historical metadata
    assert rdp.read_manifest(root) == first
    assert archive.is_file()
    archive.unlink()
    payload = json.loads((root / "manifest.json").read_text())
    payload["coverage_end"] = "2030-01-01"
    (root / "manifest.json").write_text(json.dumps(payload))
    with pytest.raises(rdp.ResearchDataPlaneValidationError):
        rdp.read_manifest(root)
    assert not list((root / "snapshots").glob("*.json"))


def test_legacy_archive_failure_is_explicit_and_does_not_publish_new_current(tmp_path, monkeypatch):
    first = _import(tmp_path)
    root = tmp_path / "rdp"
    (root / "snapshots" / f"{first['snapshot_id']}.json").unlink()
    original = (root / "manifest.json").read_bytes()
    monkeypatch.setattr(rdp.os, "link", lambda *args: (_ for _ in ()).throw(OSError("unwritable")))
    with pytest.raises(rdp.ResearchDataPlaneUnavailableError, match="archive"):
        _import(tmp_path, revised=True)
    assert (root / "manifest.json").read_bytes() == original


def test_pagination_carries_snapshot_and_date_cutoff_survives_reimport(tmp_path):
    first = _import(tmp_path)
    root = tmp_path / "rdp"
    page = rdp.query_daily_bars(root=root, date_to="2026-08-20", limit=1)
    _import(tmp_path, revised=True)
    next_page = rdp.query_daily_bars(root=root, date_to="2026-08-20", limit=1, **page["next_page"])
    assert next_page["snapshot_id"] == first["snapshot_id"]
    assert [row["code"] for row in page["rows"] + next_page["rows"]] == ["000001", "600519"]
    assert all(row["trade_date"] <= "2026-08-20" for row in page["rows"] + next_page["rows"])
    assert next_page["replay_receipt"]["parameters"]["offset"] == 1
    assert next_page["replay_receipt"]["result_sha256"] != page["replay_receipt"]["result_sha256"]


@pytest.mark.parametrize("query", [rdp.query_full_market, rdp.query_patterns])
def test_normalized_default_asof_and_canonical_key_order(tmp_path, query):
    first = _import(tmp_path)
    root = tmp_path / "rdp"
    before = query(root=root)
    assert query(root=root, as_of="2026-08-21")["replay_receipt"] == before["replay_receipt"]
    path = root / "snapshots" / f"{first['snapshot_id']}.json"
    value = json.loads(path.read_text())
    path.write_text(json.dumps(dict(reversed(list(value.items()))), indent=4))
    assert query(root=root, snapshot_id=first["snapshot_id"])["replay_receipt"] == before["replay_receipt"]


def test_factor_pins_once_across_pages_and_dates_even_when_current_changes(tmp_path, monkeypatch):
    root = tmp_path / "rdp"
    source = _write_series_fixture(tmp_path)
    first = rdp.import_csv(source, root=root)
    options = dict(factor_id="return_5d", date_from="2026-03-01", date_to="2026-03-02", data_root=root)
    before = fv.evaluate_rdp(**options)
    original = rdp.query_full_market
    calls = []
    monkeypatch.setattr(rdp, "_MAX_LIMIT", 2)

    def replace_current(**kwargs):
        calls.append((kwargs["as_of"], kwargs["offset"], kwargs["snapshot_id"]))
        page = original(**kwargs)
        if len(calls) == 1:
            newer = _write_series_fixture(tmp_path, future_values={"000001": 999})
            rdp.import_csv(newer, root=root)
        return page

    monkeypatch.setattr(rdp, "query_full_market", replace_current)
    report = fv.evaluate_rdp(**options)
    assert len(calls) == 6
    assert {item[2] for item in calls} == {first["snapshot_id"]}
    assert report["results"] == before["results"]
    assert report["replay_receipt"] == before["replay_receipt"]
    assert report["historical_validity"]["status"] == "NOT_PROVEN"
    assert rdp.read_manifest(root)["snapshot_id"] != first["snapshot_id"]


@pytest.mark.parametrize("mutation", ["snapshot", "provenance"])
def test_factor_keeps_mismatch_guards(tmp_path, monkeypatch, mutation):
    root = tmp_path / "rdp"
    rdp.import_csv(_write_series_fixture(tmp_path), root=root)
    original = rdp.query_full_market
    monkeypatch.setattr(rdp, "_MAX_LIMIT", 2)

    def inconsistent(**kwargs):
        page = original(**kwargs)
        if kwargs["offset"]:
            if mutation == "snapshot":
                page["snapshot_id"] = "0" * 64
            else:
                page["provenance"]["source_name"] = "changed.csv"
        return page

    monkeypatch.setattr(rdp, "query_full_market", inconsistent)
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="snapshot|provenance"):
        fv.evaluate_rdp(factor_id="return_5d", date_from="2026-03-01", date_to="2026-03-01", data_root=root)


def test_http_selectors_and_missing_snapshot_fail_closed(tmp_path, monkeypatch):
    first = _import(tmp_path)
    _import(tmp_path, revised=True)
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(tmp_path / "rdp"))
    app = FastAPI()
    app.include_router(research_data_plane_router.router)
    app.include_router(factor_validation_router.router)
    client = TestClient(app)
    for endpoint in ["daily-bars", "full-market", "patterns", "manifest"]:
        response = client.get(f"/api/research-data/{endpoint}", params={"snapshot_id": first["snapshot_id"]})
        assert response.status_code == 200
        assert response.json()["snapshot_id"] == first["snapshot_id"]
        missing = client.get(f"/api/research-data/{endpoint}", params={"snapshot_id": "0" * 64})
        assert missing.json()["status"] == "unavailable"
        assert client.get(f"/api/research-data/{endpoint}", params={"snapshot_id": "../x"}).status_code == 422
    response = client.post("/api/signals/factor-validation/evaluate", json={"factor_id": "return_5d", "snapshot_id": first["snapshot_id"]})
    assert response.json()["snapshot_id"] == first["snapshot_id"]
    missing = client.post("/api/signals/factor-validation/evaluate", json={"factor_id": "return_5d", "snapshot_id": "0" * 64})
    assert missing.json()["status"] == "unavailable"


def test_factor_default_date_receipt_replays_under_different_clock(tmp_path, monkeypatch):
    root = tmp_path / "rdp"
    rdp.import_csv(_write_series_fixture(tmp_path, days=10), root=root)
    monkeypatch.setattr(fv, "_utc_now", lambda: "2026-10-09T00:00:00Z")
    first = fv.evaluate_rdp(factor_id="return_5d", data_root=root)
    receipt = first["replay_receipt"]
    monkeypatch.setattr(fv, "_utc_now", lambda: "2026-10-10T09:00:00+09:00")
    replay = fv.evaluate_rdp(data_root=root, snapshot_id=receipt["snapshot_id"], **receipt["parameters"])
    assert replay["generated_at"] != first["generated_at"]
    assert replay["replay_receipt"] == receipt


def test_empty_before_coverage_query_still_identifies_pinned_snapshot(tmp_path):
    first = _import(tmp_path)
    for query in [rdp.query_full_market, rdp.query_patterns]:
        result = query(root=tmp_path / "rdp", as_of="2020-01-01")
        assert result["status"] == "unavailable"
        assert result["replay_receipt"]["snapshot_id"] == first["snapshot_id"]


def test_invalid_import_timestamp_cannot_publish_snapshot_or_replace_current(tmp_path):
    first = _import(tmp_path)
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="imported_at"):
        _import(tmp_path, revised=True, imported_at="2026-01-01")
    assert rdp.read_manifest(tmp_path / "rdp") == first
    assert len(list((tmp_path / "rdp" / "snapshots").glob("*.json"))) == 1


def test_pinned_read_needs_neither_current_manifest_nor_archive_write(tmp_path, monkeypatch):
    first = _import(tmp_path)
    root = tmp_path / "rdp"
    (root / "manifest.json").unlink()
    monkeypatch.setattr(rdp, "_archive_manifest", lambda *args: pytest.fail("pinned read attempted archive write"))
    replay = rdp.query_daily_bars(root=root, snapshot_id=first["snapshot_id"])
    assert replay["snapshot_id"] == first["snapshot_id"]


def test_full_market_receipt_replays_normalized_legacy_filter_and_sort_alias(tmp_path):
    _import(tmp_path)
    root = tmp_path / "rdp"
    before = rdp.query_full_market(root=root, filter_metric="latest_close", filter_operator="gte", filter_value=10, sort_metric="latest_close")
    receipt = before["replay_receipt"]
    replay = rdp.query_full_market(root=root, snapshot_id=receipt["snapshot_id"], **receipt["parameters"])
    assert replay["replay_receipt"] == receipt
