from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import research_data_plane as rdp


CSV = """code,trade_date,open,high,low,close,volume
600519,2026-08-20,10,12,9,11,1000
000001,2026-08-20,5,6,4,5.5,2000
600519,2026-08-21,11,13,10,12,1100
"""


def _source(tmp_path: Path, content: str = CSV) -> Path:
    path = tmp_path / "daily.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_import_and_bounded_query_uses_real_parquet_hash(tmp_path):
    root = tmp_path / "rdp"
    manifest = rdp.import_csv(_source(tmp_path), root=root, imported_at="2026-08-25T00:00:00Z")

    assert manifest["dataset_id"] == rdp.DATASET_ID
    artifact = root / "artifacts" / f"{manifest['artifact_sha256']}.parquet"
    assert artifact.is_file()
    assert len(manifest["artifact_sha256"]) == 64

    result = rdp.query_daily_bars(root=root, code="600519", limit=1)
    assert result["status"] == "normal"
    assert result["provider_id"] == "local_bulk_dump"
    assert result["adjustment"] == "UNADJUSTED"
    assert result["returned_rows"] == 1
    assert result["rows"][0]["code"] == "600519"
    assert result["next_offset"] == 1
    assert result["limitations"]


def test_duplicate_observation_fails_closed(tmp_path):
    duplicate = CSV + "600519,2026-08-20,10,12,9,11,1000\n"
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="duplicate"):
        rdp.import_csv(_source(tmp_path, duplicate), root=tmp_path / "rdp")


def test_schema_drift_and_invalid_date_fail_closed(tmp_path):
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="missing required"):
        rdp.import_csv(_source(tmp_path, "code,trade_date,close\n600519,2026-08-20,1\n"), root=tmp_path / "rdp")
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="trade_date"):
        rdp.import_csv(_source(tmp_path, CSV.replace("2026-08-20", "2026-02-30")), root=tmp_path / "rdp")


def test_query_bounds_and_date_order_fail_closed(tmp_path):
    root = tmp_path / "rdp"
    rdp.import_csv(_source(tmp_path), root=root)
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="date_from"):
        rdp.query_daily_bars(root=root, date_from="2026-08-21", date_to="2026-08-20")
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="between"):
        rdp.query_daily_bars(root=root, limit=1001)
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="six-digit"):
        rdp.query_daily_bars(root=root, code="600519 OR 1=1")


def test_artifact_tampering_fails_closed(tmp_path):
    root = tmp_path / "rdp"
    manifest = rdp.import_csv(_source(tmp_path), root=root)
    artifact = root / "artifacts" / f"{manifest['artifact_sha256']}.parquet"
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="hash mismatch"):
        rdp.read_manifest(root)


def test_api_reports_unavailable_without_fabricating_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(tmp_path / "missing"))
    import app
    client = TestClient(app.app)
    response = client.get("/api/research-data/daily-bars")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["rows"] == []
    assert payload["as_of"] is None
    assert payload["limitations"]


def test_manifest_is_readable_json(tmp_path):
    root = tmp_path / "rdp"
    rdp.import_csv(_source(tmp_path), root=root)
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == rdp.SCHEMA_VERSION
