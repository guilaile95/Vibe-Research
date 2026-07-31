"""Unit & integration tests for Intel Daily Digest storage, service, and API endpoints.
"""

from __future__ import annotations

import concurrent.futures
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


def test_url_normalization():
    # 1. Hostname lowercase & scheme lowercase
    raw1 = "HTTP://Example.COM/path/To/Resource?utm_source=rss&spm=123&QUERY=Value#section1"
    norm1 = svc.normalize_url(raw1)
    assert norm1 == "http://example.com/path/To/Resource?QUERY=Value"  # path casing preserved, fragment & tracking params removed

    # 2. Port 80 / 443 default normalization
    raw_http = "http://example.com:80/path"
    assert svc.normalize_url(raw_http) == "http://example.com/path"

    raw_https = "https://example.com:443/path"
    assert svc.normalize_url(raw_https) == "https://example.com/path"

    # 3. Non-default port preserved
    raw_custom = "https://example.com:8443/path"
    assert svc.normalize_url(raw_custom) == "https://example.com:8443/path"

    # 4. Query parameters deterministically sorted
    raw_q = "https://example.com/api?b=2&a=1&c=3"
    assert svc.normalize_url(raw_q) == "https://example.com/api?a=1&b=2&c=3"

    # 5. Empty string
    assert svc.normalize_url("") == ""


def test_fingerprint_deterministic_order_and_content_change():
    items_order_a = [
        {"url": "https://a.com/news/1", "title": "Title 1", "source": "Src 1", "published_at": "2026-07-31"},
        {"url": "https://b.com/news/2", "title": "Title 2", "source": "Src 2", "published_at": "2026-07-31"},
    ]
    items_order_b = [
        {"url": "https://b.com/news/2", "title": "Title 2", "source": "Src 2", "published_at": "2026-07-31"},
        {"url": "https://a.com/news/1", "title": "Title 1", "source": "Src 1", "published_at": "2026-07-31"},
    ]

    fp_a = svc.compute_input_fingerprint("ai", items_order_a)
    fp_b = svc.compute_input_fingerprint("ai", items_order_b)

    # Order change yields same fingerprint
    assert fp_a == fp_b

    # Content change yields different fingerprint
    items_changed = [
        {"url": "https://a.com/news/1", "title": "Title 1 CHANGED", "source": "Src 1", "published_at": "2026-07-31"},
        {"url": "https://b.com/news/2", "title": "Title 2", "source": "Src 2", "published_at": "2026-07-31"},
    ]
    fp_changed = svc.compute_input_fingerprint("ai", items_changed)
    assert fp_a != fp_changed


def test_digest_id_stability():
    fp = "abcd1234efgh5678"
    id1 = svc.compute_digest_id("2026-07-31", "ai", fp)
    id2 = svc.compute_digest_id("2026-07-31", "ai", fp)
    assert id1 == id2
    assert id1.startswith("idg_")


def test_normal_and_partial_save(tmp_path):
    items = [{"url": "https://example.com/1", "title": "Test 1", "source": "S1", "published_at": "2026-07-31"}]

    res_norm, dedup1 = svc.save_digest(
        sector_key="ai",
        status="normal",
        summary_text="- Point 1",
        source_refs=[],
        input_items=items,
        db_path=tmp_path / "test.db",
    )
    assert res_norm is not None
    assert res_norm["status"] == "normal"
    assert dedup1 is False

    res_part, dedup2 = svc.save_digest(
        sector_key="semiconductor",
        status="partial",
        summary_text="- Partial point",
        source_refs=[],
        input_items=items,
        db_path=tmp_path / "test.db",
    )
    assert res_part is not None
    assert res_part["status"] == "partial"
    assert dedup2 is False


def test_unavailable_status_does_not_save(tmp_path):
    items = [{"url": "https://example.com/1", "title": "Test 1"}]
    res, dedup = svc.save_digest(
        sector_key="ai",
        status="unavailable",
        summary_text="Unavailable",
        source_refs=[],
        input_items=items,
        db_path=tmp_path / "test.db",
    )
    assert res is None
    assert dedup is False

    latest = svc.get_latest_digest("ai", db_path=tmp_path / "test.db")
    assert latest is None


def test_deduplication_same_fingerprint(tmp_path):
    items = [{"url": "https://example.com/news1", "title": "News 1", "source": "Source 1", "published_at": "2026-07-31"}]

    res1, dedup1 = svc.save_digest(
        sector_key="ai",
        status="normal",
        summary_text="Original summary",
        source_refs=[],
        input_items=items,
        db_path=tmp_path / "test.db",
    )
    assert dedup1 is False
    assert res1["summary_text"] == "Original summary"

    # Save again with same fingerprint and date
    res2, dedup2 = svc.save_digest(
        sector_key="ai",
        status="normal",
        summary_text="Different text for same input",
        source_refs=[],
        input_items=items,
        db_path=tmp_path / "test.db",
    )
    assert dedup2 is True
    assert res2["digest_id"] == res1["digest_id"]
    # Does not overwrite original record!
    assert res2["summary_text"] == "Original summary"


def test_api_endpoints_flow(tmp_path):
    items = [{"url": "https://a.com/1", "title": "T1", "source": "S1", "published_at": "2026-07-31"}]

    # 1. Latest query when empty
    r_empty = client.get("/api/intel-digests/latest?sector_key=ai")
    assert r_empty.status_code == 200
    assert r_empty.json() == {"digest": None}

    # 2. Save via POST API
    post_payload = {
        "sector_key": "ai",
        "status": "normal",
        "summary_text": "- Important AI news",
        "source_refs": items,
        "input_items": items,
    }
    r_post = client.post("/api/intel-digests", json=post_payload)
    assert r_post.status_code == 200
    res_data = r_post.json()
    assert res_data["deduped"] is False
    assert res_data["digest"]["sector_key"] == "ai"
    assert res_data["digest"]["digest_date"] is not None

    # 3. Latest query after save
    r_latest = client.get("/api/intel-digests/latest?sector_key=ai")
    assert r_latest.status_code == 200
    assert r_latest.json()["digest"]["digest_id"] == res_data["digest"]["digest_id"]

    # 4. Repeat POST API -> deduped
    r_post_dup = client.post("/api/intel-digests", json=post_payload)
    assert r_post_dup.status_code == 200
    assert r_post_dup.json()["deduped"] is True

    # 5. Unavailable POST API -> digest: null
    r_unavail = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "unavailable", "summary_text": "err"})
    assert r_unavail.status_code == 200
    assert r_unavail.json() == {"digest": None, "deduped": False}


def test_concurrent_writes_single_record(tmp_path):
    db_p = tmp_path / "concurrent.db"
    items = [{"url": "https://c.com/1", "title": "Concurrent", "source": "S", "published_at": "2026-07-31"}]

    def _write():
        return svc.save_digest(
            sector_key="robotics",
            status="normal",
            summary_text="Summary text",
            source_refs=[],
            input_items=items,
            db_path=db_p,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_write) for _ in range(5)]
        results = [f.result() for f in futures]

    # Exactly 1 should be deduped=False, remaining 4 deduped=True
    not_deduped = [r for r, d in results if not d]
    deduped = [r for r, d in results if d]
    assert len(not_deduped) == 1
    assert len(deduped) == 4


def test_corrupted_db_graceful_error(monkeypatch):
    def mock_save(*_args, **_kwargs):
        raise store.IntelDigestCorruptedError()

    monkeypatch.setattr(svc, "save_digest", mock_save)

    r = client.post(
        "/api/intel-digests",
        json={"sector_key": "ai", "status": "normal", "summary_text": "Text"},
    )
    assert r.status_code == 500
    body = r.json()
    assert body["digest"] is None
    assert "error" in body
    # Traceback / raw str(exc) should NOT leak
    assert "Intel 摘要数据存储故障" in body["error"]
