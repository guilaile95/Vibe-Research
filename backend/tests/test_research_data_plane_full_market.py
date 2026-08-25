from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import research_data_plane as rdp


def _write_fixture(tmp_path: Path, days: int = 65) -> Path:
    source = tmp_path / "full-market.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "trade_date", "open", "high", "low", "close", "volume"])
        start = date(2026, 1, 2)
        for index in range(days):
            trade_date = (start + timedelta(days=index)).isoformat()
            for code, base, volume in (("000001", 10.0, 100.0), ("000002", 20.0, 200.0)):
                close = base + index
                writer.writerow([code, trade_date, close, close + 1, close - 1, close, volume + index])
        # A separate short-history security proves per-row explicit unknowns.
        writer.writerow(["600519", "2026-03-07", 12, 13, 11, 12, 300])
    return source


def test_full_market_cross_section_is_set_based_and_explicit(tmp_path):
    root = tmp_path / "rdp"
    rdp.import_csv(_write_fixture(tmp_path), root=root, imported_at="2026-03-08T00:00:00Z")

    result = rdp.query_full_market(root=root, latest=True, sort_by="return_20d", sort_order="desc")

    assert result["status"] == "normal"
    assert result["schema_version"] == rdp.FULL_MARKET_SCHEMA_VERSION
    assert result["as_of"] == "2026-03-07"
    assert result["latest_date"] == "2026-03-07"
    assert result["coverage"]["universe_count"] == 3
    assert result["provenance"]["artifact_sha256"]
    assert "turnover" in " ".join(result["limitations"])

    full = next(row for row in result["rows"] if row["code"] == "000001")
    assert full["return_5d_status"] == "normal"
    assert full["return_20d_status"] == "normal"
    assert full["return_60d_status"] == "normal"
    assert full["ma20_status"] == "normal"
    assert full["ma60_status"] == "normal"
    assert full["current_volume"] == 164.0
    assert full["avg_volume_20d"] == pytest.approx(154.5)
    assert full["volume_ratio_20d"] == pytest.approx(164 / 154.5)

    short = next(row for row in result["rows"] if row["code"] == "600519")
    assert short["return_20d"] is None
    assert short["return_20d_status"] == "INSUFFICIENT_HISTORY"
    assert short["ma20"] is None
    assert short["ma20_status"] == "INSUFFICIENT_HISTORY"
    assert result["breadth"]["ma20"]["breadth"] == pytest.approx(2 / 2)
    assert result["breadth"]["ma20"]["insufficient_count"] == 1
    assert result["breadth"]["ma60"]["breadth"] == pytest.approx(2 / 2)


def test_full_market_explicit_as_of_filter_sort_pagination(tmp_path):
    root = tmp_path / "rdp"
    rdp.import_csv(_write_fixture(tmp_path), root=root)

    result = rdp.query_full_market(
        root=root,
        as_of="2026-02-20",
        latest=False,
        filter_metric="return_5d",
        filter_operator="gt",
        filter_value=0.05,
        sort_by="latest_close",
        sort_order="desc",
        limit=1,
        offset=0,
    )
    assert result["as_of"] == "2026-02-20"
    assert result["returned_rows"] == 1
    assert result["total_rows"] == 2
    assert result["next_offset"] == 1
    assert result["rows"][0]["code"] == "000002"

    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="as_of is required"):
        rdp.query_full_market(root=root, latest=False)
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="named metric"):
        rdp.query_full_market(root=root, filter_metric="amount", filter_operator="gt", filter_value=1)


def test_full_market_manifest_or_artifact_failure_has_no_fallback(tmp_path):
    root = tmp_path / "rdp"
    manifest = rdp.import_csv(_write_fixture(tmp_path), root=root)
    artifact = root / "artifacts" / f"{manifest['artifact_sha256']}.parquet"
    artifact.write_bytes(artifact.read_bytes() + b"tampered")

    with pytest.raises(rdp.ResearchDataPlaneValidationError, match="hash mismatch"):
        rdp.query_full_market(root=root)

    monkeypatch_root = tmp_path / "missing"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(monkeypatch_root))
        client = TestClient(app_module.app)
        response = client.get("/api/research-data/full-market")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["rows"] == []
    assert payload["breadth"]["ma20"]["breadth"] is None
    assert any("回退" in item for item in payload["limitations"])


def test_full_market_missing_rdp_returns_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(tmp_path / "missing"))
    client = TestClient(app_module.app)
    response = client.get("/api/research-data/full-market")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["rows"] == []
    assert payload["breadth"]["ma20"]["breadth"] is None
    assert any("回退" in item for item in payload["limitations"])


def test_screener_full_market_wrapper_is_fail_closed_and_not_candidate_pool(tmp_path, monkeypatch):
    root = tmp_path / "rdp"
    manifest = rdp.import_csv(_write_fixture(tmp_path), root=root)
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    client = TestClient(app_module.app)

    response = client.get(
        "/api/screener/full-market",
        params={
            "latest": "false",
            "as_of": "2026-02-20",
            "filter_metric": "return_5d",
            "filter_operator": "gt",
            "filter_value": "0.05",
            "sort_by": "latest_close",
            "sort_order": "desc",
            "limit": "1",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "normal"
    assert payload["rows"][0]["code"] == "000002"
    assert payload["provenance"]["artifact_sha256"] == manifest["artifact_sha256"]
    assert "matched" not in payload

    artifact = root / "artifacts" / f"{manifest['artifact_sha256']}.parquet"
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    unavailable = client.get("/api/screener/full-market")
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "unavailable"
    assert unavailable.json()["rows"] == []


def test_screener_full_market_wrapper_keeps_query_validation_distinct(tmp_path, monkeypatch):
    root = tmp_path / "rdp"
    rdp.import_csv(_write_fixture(tmp_path), root=root)
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    response = TestClient(app_module.app).get(
        "/api/screener/full-market",
        params={"latest": "false"},
    )
    assert response.status_code == 422
    assert "as_of is required" in response.json()["detail"]
