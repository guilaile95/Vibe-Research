"""API contract tests for POST /api/screener/evaluate."""

from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app as app_module
import screener_service as svc
from screener_models import FORBIDDEN_RESPONSE_KEYS

client = TestClient(app_module.app)


def _valid_body(**overrides):
    body = {
        "codes": ["000001", "600519"],
        "conditions": [{"id": "price_gt_sma20"}],
    }
    body.update(overrides)
    return body


def _mock_env(close=12.0, sma20=11.0, sma60=10.0, status="normal"):
    return {
        "status": status,
        "trade_date": "2026-07-30",
        "limitations": [],
        "latest": {
            "close": close,
            "sma20": sma20,
            "sma60": sma60,
            "rsi14": 55.0,
            "macd_histogram": 0.2,
            "volume_ratio_5_20": 1.1,
        },
        "triggers": [],
    }


def _assert_no_forbidden(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in FORBIDDEN_RESPONSE_KEYS, f"forbidden key {k}"
            _assert_no_forbidden(v)
    elif isinstance(obj, list):
        for it in obj:
            _assert_no_forbidden(it)


def _write_screener_fixture(tmp_path: Path, *, days: int = 60) -> Path:
    source = tmp_path / "daily-bars.csv"
    start = date(2026, 1, 2)
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "trade_date", "open", "high", "low", "close", "volume"])
        for index in range(days):
            day = (start + timedelta(days=index)).isoformat()
            close = 10.0 + index * 0.1
            writer.writerow(["000001", day, close, close + 1, close - 1, close, 1000 + index])
    return source


def test_real_rdp_to_screener_vertical(tmp_path, monkeypatch):
    import research_data_plane as rdp

    root = tmp_path / "research-data"
    manifest = rdp.import_csv(
        _write_screener_fixture(tmp_path),
        root=root,
        imported_at="2026-03-02T00:00:00Z",
    )
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    response = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["research_data"]["dataset_id"] == rdp.DATASET_ID
    assert payload["research_data"]["provider_id"] == rdp.PROVIDER_ID
    assert payload["research_data"]["adjustment"] == rdp.ADJUSTMENT
    assert payload["research_data"]["as_of"] == "2026-03-02"
    assert payload["research_data"]["coverage"]["row_count"] == 60
    assert payload["research_data"]["provenance"]["artifact_sha256"] == manifest["artifact_sha256"]
    assert [item["code"] for item in payload["matched"]] == ["000001"]
    assert not {"rows", "returned_rows", "next_offset"} & set(payload["research_data"])


def _assert_rdp_unavailable(payload: dict) -> None:
    assert payload["status"] == "unavailable"
    assert payload["matched"] == []
    assert payload["rejected"] == []
    assert [item["code"] for item in payload["unavailable"]] == ["000001"]
    source = payload["research_data"]
    assert source["status"] == "unavailable"
    assert source["coverage"] is None
    assert not {"rows", "returned_rows", "next_offset"} & set(source)


def test_rdp_tamper_is_unavailable_at_screener_boundary(tmp_path, monkeypatch):
    import research_data_plane as rdp

    root = tmp_path / "research-data"
    manifest = rdp.import_csv(_write_screener_fixture(tmp_path), root=root)
    artifact = root / "artifacts" / f"{manifest['artifact_sha256']}.parquet"
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    response = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert response.status_code == 200
    _assert_rdp_unavailable(response.json())


def test_malformed_manifest_is_unavailable_at_screener_boundary(tmp_path, monkeypatch):
    import research_data_plane as rdp

    root = tmp_path / "research-data"
    rdp.import_csv(_write_screener_fixture(tmp_path), root=root)
    manifest_path = root / "manifest.json"
    manifest = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(manifest[:-2] + "not-json\n", encoding="utf-8")
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    response = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert response.status_code == 200
    _assert_rdp_unavailable(response.json())


def test_missing_artifact_is_unavailable_at_screener_boundary(tmp_path, monkeypatch):
    import research_data_plane as rdp

    root = tmp_path / "research-data"
    manifest = rdp.import_csv(_write_screener_fixture(tmp_path), root=root)
    (root / "artifacts" / f"{manifest['artifact_sha256']}.parquet").unlink()
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    response = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert response.status_code == 200
    _assert_rdp_unavailable(response.json())


def test_hash_mismatch_is_unavailable_without_fallback(tmp_path, monkeypatch):
    import research_data_plane as rdp

    root = tmp_path / "research-data"
    manifest = rdp.import_csv(_write_screener_fixture(tmp_path), root=root)
    artifact = root / "artifacts" / f"{manifest['artifact_sha256']}.parquet"
    artifact.write_bytes(artifact.read_bytes() + b"changed")
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    response = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert response.status_code == 200
    _assert_rdp_unavailable(response.json())


def test_happy_path_match_and_reject(monkeypatch):
    monkeypatch.setattr(
        svc,
        "_research_bars",
        lambda code, days: (
            [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}],
            svc._injected_data_envelope(),
        ),
    )

    def compute(raw, **kwargs):
        if kwargs["code"] == "000001":
            return _mock_env(close=12, sma20=11)
        return _mock_env(close=10, sma20=11)

    monkeypatch.setattr("screener_service.ti.compute_indicators", compute)

    r = client.post("/api/screener/evaluate", json=_valid_body())
    assert r.status_code == 200
    data = r.json()
    assert data["logic"] == "AND"
    assert data["schema_version"] == "screener-v0.1"
    assert [s["code"] for s in data["matched"]] == ["000001"]
    assert [s["code"] for s in data["rejected"]] == ["600519"]
    assert data["unavailable"] == []
    assert data["status"] == "normal"
    _assert_no_forbidden(data)


def test_kline_exception_isolated(monkeypatch):
    def kline(code, category=4, offset=120):
        if code == "000002":
            raise RuntimeError("down")
        return [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}]

    monkeypatch.setattr(svc, "_research_bars", lambda code, days: (kline(code, days), svc._injected_data_envelope()))
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11),
    )

    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001", "000002"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert [s["code"] for s in data["matched"]] == ["000001"]
    assert [s["code"] for s in data["unavailable"]] == ["000002"]
    assert data["status"] == "partial"
    assert data["unavailable"][0]["matched"] is None


def test_missing_sma60_unavailable(monkeypatch):
    monkeypatch.setattr(
        svc,
        "_research_bars",
        lambda code, days: ([{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}], svc._injected_data_envelope()),
    )
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11, sma60=None, status="partial"),
    )
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["600519"], "conditions": [{"id": "price_gt_sma60"}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["matched"] == []
    assert data["rejected"] == []
    assert len(data["unavailable"]) == 1
    assert data["unavailable"][0]["bucket"] == "unavailable"


def test_code_dedupe_sort(monkeypatch):
    seen = []

    def kline(code, category=4, offset=120):
        seen.append(code)
        return [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}]

    monkeypatch.setattr(svc, "_research_bars", lambda code, days: (kline(code, days), svc._injected_data_envelope()))
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11),
    )
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["600519", "000001", "600519"],
            "conditions": [{"id": "price_gt_sma20"}],
        },
    )
    assert r.status_code == 200
    assert seen == ["000001", "600519"]


def test_empty_codes_422():
    r = client.post("/api/screener/evaluate", json={"codes": [], "conditions": [{"id": "price_gt_sma20"}]})
    assert r.status_code == 422


def test_too_many_unique_codes_422():
    codes = [f"{i:06d}" for i in range(31)]
    r = client.post("/api/screener/evaluate", json={"codes": codes, "conditions": [{"id": "price_gt_sma20"}]})
    assert r.status_code == 422


def test_31_raw_30_unique_accepted_200(monkeypatch):
    """Dedupe-before-limit: 31 raw with one duplicate → 30 unique → 200."""
    monkeypatch.setattr(
        svc,
        "_research_bars",
        lambda code, days: ([{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}], svc._injected_data_envelope()),
    )
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11),
    )
    codes = [f"{i:06d}" for i in range(30)] + ["000000"]  # 000000 already first → still 30 unique
    # range(30) is 000000..000029; append 000000 again
    codes = [f"{i:06d}" for i in range(30)] + ["000001"]
    assert len(codes) == 31
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": codes, "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert r.status_code == 200
    data = r.json()
    # all unique codes evaluated
    total = len(data["matched"]) + len(data["rejected"]) + len(data["unavailable"])
    assert total == 30


def test_31_unique_codes_422_not_sliced():
    codes = [f"{i:06d}" for i in range(31)]
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": codes, "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert r.status_code == 422


def test_invalid_code_422():
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["ABC"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert r.status_code == 422


def test_duplicate_condition_id_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "price_gt_sma20"}, {"id": "price_gt_sma20"}],
        },
    )
    assert r.status_code == 422


def test_unknown_condition_422():
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "not_a_real_condition"}]},
    )
    assert r.status_code == 422


def test_missing_params_422():
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "rsi_between"}]},
    )
    assert r.status_code == 422


def test_extra_params_field_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [
                {"id": "rsi_between", "params": {"min": 30, "max": 70, "extra": 1}}
            ],
        },
    )
    assert r.status_code == 422


def test_extra_top_level_field_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "price_gt_sma20"}],
            "days": 120,
        },
    )
    assert r.status_code == 422


def test_min_gt_max_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "rsi_between", "params": {"min": 80, "max": 20}}],
        },
    )
    assert r.status_code == 422


def test_threshold_le_zero_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "volume_ratio_gte", "params": {"threshold": 0}}],
        },
    )
    assert r.status_code == 422


def test_nan_infinity_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "rsi_between", "params": {"min": "NaN", "max": 70}}],
        },
    )
    assert r.status_code == 422

    r2 = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [
                {"id": "volume_ratio_gte", "params": {"threshold": "Infinity"}}
            ],
        },
    )
    assert r2.status_code == 422


def test_sector_representatives_endpoint():
    import sector_research_data as srd

    r = client.get("/api/screener/sources/sector-representatives")
    assert r.status_code == 200
    data = r.json()
    assert data.get("schema_version") == "screener-sources-v0.1"
    assert "codes" in data and "count" in data
    assert data["count"] == len(data["codes"])
    assert data["codes"] == sorted(data["codes"])
    assert all(isinstance(c, str) and len(c) == 6 and c.isdigit() for c in data["codes"])
    # Uniqueness
    assert len(data["codes"]) == len(set(data["codes"]))

    # Expected only from public sector_research_data getters — never SourceRef parsing
    expected: list[str] = []
    seen: set[str] = set()
    for key in srd.list_sector_source_keys():
        src = srd.get_sector_source(key)
        assert src is not None
        for raw in src.representative_company_codes or []:
            code = str(raw).strip()
            if code.isdigit() and len(code) == 6 and code not in seen:
                seen.add(code)
                expected.append(code)
    expected.sort()
    assert data["codes"] == expected
    assert data["count"] == 103

    # Must include known representatives
    for code in ("002463", "002916", "300476"):
        assert code in data["codes"]

    # Must exclude known false-positives from frontend text scrape era
    for code in ("002036", "002466", "600549", "600741", "600862", "601126", "688070"):
        assert code not in data["codes"]

    # No forbidden research/trade fields
    for forbidden in (
        "buy", "sell", "score", "weight", "url", "sources", "holdings",
        "signal", "expected_return", "target_position",
    ):
        assert forbidden not in data


def test_determinism_excluding_evaluated_at(monkeypatch):
    monkeypatch.setattr(
        svc,
        "_research_bars",
        lambda code, days: ([{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}], svc._injected_data_envelope()),
    )
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11),
    )
    body = {"codes": ["600519", "000001"], "conditions": [{"id": "price_gt_sma20"}]}
    a = client.post("/api/screener/evaluate", json=body).json()
    b = client.post("/api/screener/evaluate", json=body).json()
    for key in ("matched", "rejected", "unavailable", "status", "logic", "schema_version"):
        assert a[key] == b[key]
