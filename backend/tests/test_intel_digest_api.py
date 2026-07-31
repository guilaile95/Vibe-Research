"""Unit & integration tests for Intel Daily Digest storage, service, and API endpoints.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app as app_module
import intel_digest_service as svc
import intel_digest_store as store

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))


def test_url_normalization_rules():
    # 1. Conservative tracking params (utm_*, fbclid, gclid, msclkid, spm, _hsenc, _hsmi, mkt_tok) removed
    raw1 = "https://Example.COM:443/path/To/Page?utm_source=google&spm=123&v=video-123#frag"
    norm1 = svc.normalize_url(raw1)
    # v is preserved, utm_source and spm removed, default port 443 removed, scheme & hostname lowercase
    assert norm1 == "https://example.com/path/To/Page?v=video-123"

    # 2. watch?v=video-A vs watch?v=video-B: normalized URLs & fingerprints are different
    url_a = "https://youtube.com/watch?v=video-A"
    url_b = "https://youtube.com/watch?v=video-B"
    assert svc.normalize_url(url_a) != svc.normalize_url(url_b)

    fp_a = svc.compute_input_fingerprint("ai", [{"url": url_a, "title": "A"}])
    fp_b = svc.compute_input_fingerprint("ai", [{"url": url_b, "title": "A"}])
    assert fp_a != fp_b

    # 3. utm_source different: normalized URLs & fingerprints are identical
    url_utm1 = "https://example.com/news?utm_source=news1&id=10"
    url_utm2 = "https://example.com/news?utm_source=news2&id=10"
    assert svc.normalize_url(url_utm1) == svc.normalize_url(url_utm2) == "https://example.com/news?id=10"

    fp_utm1 = svc.compute_input_fingerprint("ai", [{"url": url_utm1, "title": "A"}])
    fp_utm2 = svc.compute_input_fingerprint("ai", [{"url": url_utm2, "title": "A"}])
    assert fp_utm1 == fp_utm2

    # 4. Same query parameters in different order: normalized URLs are identical
    url_q1 = "https://example.com/api?b=2&a=1"
    url_q2 = "https://example.com/api?a=1&b=2"
    assert svc.normalize_url(url_q1) == svc.normalize_url(url_q2) == "https://example.com/api?a=1&b=2"

    # 5. IPv6 netloc preserved
    raw_ipv6 = "http://[2001:db8::1]:8080/path?b=2&a=1"
    assert svc.normalize_url(raw_ipv6) == "http://[2001:db8::1]:8080/path?a=1&b=2"


def test_shanghai_time_boundary_fixed_utc(tmp_path):
    items = [{"url": "https://a.com/1", "title": "T1", "source": "S1", "published_at": "2026-07-31"}]

    # UTC 2026-07-31 15:59:00 -> Shanghai 2026-07-31 23:59:00 (+08:00)
    utc_1559 = datetime(2026, 7, 31, 15, 59, 0, tzinfo=timezone.utc)
    res_1559, _ = svc.save_digest(
        sector_key="ai",
        status="normal",
        summary_text="- Digest 1",
        source_refs=[],
        input_items=items,
        db_path=tmp_path / "test.db",
        now_dt=utc_1559,
    )
    assert res_1559["digest_date"] == "2026-07-31"
    assert "+08:00" in res_1559["generated_at"]
    assert "+08:00" in res_1559["created_at"]
    assert res_1559["digest_id"] == svc.compute_digest_id("2026-07-31", "ai", res_1559["input_fingerprint"])

    # UTC 2026-07-31 16:01:00 -> Shanghai 2026-08-01 00:01:00 (+08:00)
    utc_1601 = datetime(2026, 7, 31, 16, 1, 0, tzinfo=timezone.utc)
    res_1601, _ = svc.save_digest(
        sector_key="ai",
        status="normal",
        summary_text="- Digest 2",
        source_refs=[],
        input_items=items,
        db_path=tmp_path / "test.db",
        now_dt=utc_1601,
    )
    assert res_1601["digest_date"] == "2026-08-01"
    assert "+08:00" in res_1601["generated_at"]
    assert "+08:00" in res_1601["created_at"]
    assert res_1601["digest_id"] == svc.compute_digest_id("2026-08-01", "ai", res_1601["input_fingerprint"])


def test_validation_strict_422_responses():
    items = [{"url": "https://a.com/1", "title": "T1", "source": "S1", "published_at": "2026-07-31"}]

    # 1. Invalid status
    r1 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "invalid_status", "summary_text": "- Text", "input_items": items})
    assert r1.status_code == 422

    # 2. Unknown sector_key
    r2 = client.post("/api/intel-digests", json={"sector_key": "unknown_key", "status": "normal", "summary_text": "- Text", "input_items": items})
    assert r2.status_code == 422

    # 3. Empty summary_text
    r3 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "   \n\t ", "input_items": items})
    assert r3.status_code == 422

    # 4. Empty input_items
    r4 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": []})
    assert r4.status_code == 422

    # 5. Client submitting forbidden extra fields (sector_name, digest_date, etc.)
    r5 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": items, "sector_name": "Fake Name"})
    assert r5.status_code == 422

    r6 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": items, "digest_date": "2026-07-31"})
    assert r6.status_code == 422


def test_get_endpoints_missing_vs_failure():
    # 1. Unknown sector_key -> 422
    assert client.get("/api/intel-digests/latest?sector_key=unknown").status_code == 422
    assert client.get("/api/intel-digests?sector_key=unknown").status_code == 422

    # 2. Record not found -> HTTP 200 {"digest": null}
    r_empty = client.get("/api/intel-digests/latest?sector_key=ai")
    assert r_empty.status_code == 200
    assert r_empty.json() == {"digest": None}

    # 3. IntelDigestCorruptedError on GET -> HTTP 500 {"digest": null, "error": "Intel 摘要数据存储故障"}
    with patch("intel_digest_service.get_latest_digest", side_effect=store.IntelDigestCorruptedError):
        r_corrupt = client.get("/api/intel-digests/latest?sector_key=ai")
        assert r_corrupt.status_code == 500
        assert r_corrupt.json() == {"digest": None, "error": "Intel 摘要数据存储故障"}

    # 4. Unexpected Exception on GET -> HTTP 500 {"digest": null, "error": "读取 Intel 摘要失败"}
    with patch("intel_digest_service.get_latest_digest", side_effect=RuntimeError("DB disconnect")):
        r_err = client.get("/api/intel-digests/latest?sector_key=ai")
        assert r_err.status_code == 500
        assert r_err.json() == {"digest": None, "error": "读取 Intel 摘要失败"}


def test_atomic_sqlite_deduplication_multi_connection(tmp_path):
    db_p = tmp_path / "multi_conn.db"
    items = [{"url": "https://c.com/1", "title": "Concurrent", "source": "S", "published_at": "2026-07-31"}]

    def _save_task(i: int):
        # Explicit independent call using db_path
        return svc.save_digest(
            sector_key="semiconductor",
            status="normal",
            summary_text=f"- Summary text from worker {i}",
            source_refs=[],
            input_items=items,
            db_path=db_p,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_save_task, i) for i in range(10)]
        results = [f.result() for f in futures]

    # Verify atomic deduplication results across independent DB connections
    not_deduped = [r for r, d in results if not d]
    deduped = [r for r, d in results if d]
    assert len(not_deduped) == 1
    assert len(deduped) == 9

    # Assert exactly 1 row exists in SQLite table
    with store._connect(db_p) as conn:
        count = conn.execute("SELECT COUNT(*) FROM intel_daily_digests").fetchone()[0]
        assert count == 1
