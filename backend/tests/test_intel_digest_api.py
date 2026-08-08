"""Unit & integration tests for Intel Daily Digest storage, service, and API endpoints.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
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

    fp_a = svc.compute_input_fingerprint("ai", [{"url": url_a, "title": "A", "source": "S", "published_at": "2026-07-31T10:00:00+08:00"}])
    fp_b = svc.compute_input_fingerprint("ai", [{"url": url_b, "title": "A", "source": "S", "published_at": "2026-07-31T10:00:00+08:00"}])
    assert fp_a != fp_b

    # 3. utm_source different: normalized URLs & fingerprints are identical
    url_utm1 = "https://example.com/news?utm_source=news1&id=10"
    url_utm2 = "https://example.com/news?utm_source=news2&id=10"
    assert svc.normalize_url(url_utm1) == svc.normalize_url(url_utm2) == "https://example.com/news?id=10"

    fp_utm1 = svc.compute_input_fingerprint("ai", [{"url": url_utm1, "title": "A", "source": "S", "published_at": "2026-07-31T10:00:00+08:00"}])
    fp_utm2 = svc.compute_input_fingerprint("ai", [{"url": url_utm2, "title": "A", "source": "S", "published_at": "2026-07-31T10:00:00+08:00"}])
    assert fp_utm1 == fp_utm2

    # 4. Same query parameters in different order: normalized URLs are identical
    url_q1 = "https://example.com/api?b=2&a=1"
    url_q2 = "https://example.com/api?a=1&b=2"
    assert svc.normalize_url(url_q1) == svc.normalize_url(url_q2) == "https://example.com/api?a=1&b=2"

    # 5. IPv6 netloc preserved
    raw_ipv6 = "http://[2001:db8::1]:8080/path?b=2&a=1"
    assert svc.normalize_url(raw_ipv6) == "http://[2001:db8::1]:8080/path?a=1&b=2"


def test_shanghai_time_boundary_fixed_utc(tmp_path):
    items = [{"url": "https://a.com/1", "title": "T1", "source": "S1", "published_at": "2026-07-31T10:00:00+08:00"}]

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
    valid_items = [{"url": "https://a.com/1", "title": "T1", "source": "S1", "published_at": "2026-07-31T10:00:00+08:00"}]

    # 1. Invalid status
    r1 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "invalid_status", "summary_text": "- Text", "input_items": valid_items})
    assert r1.status_code == 422

    # 2. Unknown sector_key
    r2 = client.post("/api/intel-digests", json={"sector_key": "unknown_key", "status": "normal", "summary_text": "- Text", "input_items": valid_items})
    assert r2.status_code == 422

    # 3. Empty summary_text
    r3 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "   \n\t ", "input_items": valid_items})
    assert r3.status_code == 422

    # 4. Empty input_items
    r4 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": []})
    assert r4.status_code == 422

    # 5. Client submitting forbidden extra top-level fields
    r5 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": valid_items, "sector_name": "Fake Name"})
    assert r5.status_code == 422

    r6 = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": valid_items, "digest_date": "2026-07-31"})
    assert r6.status_code == 422

    # 6. Item contract validations
    # input_items=[{}]
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{}]}).status_code == 422

    # empty title
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "https://a.com", "title": "", "source": "S", "published_at": "2026-07-31T10:00:00+08:00"}]}).status_code == 422

    # empty source
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "https://a.com", "title": "T", "source": "", "published_at": "2026-07-31T10:00:00+08:00"}]}).status_code == 422

    # invalid published_at
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "https://a.com", "title": "T", "source": "S", "published_at": "invalid-date"}]}).status_code == 422

    # bare date without time → 422
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "https://a.com", "title": "T", "source": "S", "published_at": "2026-07-31"}]}).status_code == 422

    # naive datetime without timezone → 422
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "https://a.com", "title": "T", "source": "S", "published_at": "2026-07-31T10:00:00"}]}).status_code == 422

    # invalid URL scheme (e.g. ftp://)
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "ftp://a.com", "title": "T", "source": "S", "published_at": "2026-07-31T10:00:00+08:00"}]}).status_code == 422

    # URL with empty hostname (https://) → 422
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "https://", "title": "T", "source": "S", "published_at": "2026-07-31T10:00:00+08:00"}]}).status_code == 422

    # URL with illegal port → 422 (must not become 500)
    r_bad_port = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "https://example.com:bad-port/a", "title": "T", "source": "S", "published_at": "2026-07-31T10:00:00+08:00"}]})
    assert r_bad_port.status_code == 422

    # extra item field
    assert client.post("/api/intel-digests", json={"sector_key": "ai", "status": "normal", "summary_text": "- Text", "input_items": [{"url": "https://a.com", "title": "T", "source": "S", "published_at": "2026-07-31T10:00:00+08:00", "extra_field": 123}]}).status_code == 422

    # 7. Valid sector + unavailable status -> 200 {"digest": null}
    r_unavail = client.post("/api/intel-digests", json={"sector_key": "ai", "status": "unavailable"})
    assert r_unavail.status_code == 200
    assert r_unavail.json() == {"digest": None, "deduped": False}

    # 8. Unknown sector + unavailable status -> 422 (validates sector_key first!)
    r_unavail_bad = client.post("/api/intel-digests", json={"sector_key": "unknown_key", "status": "unavailable"})
    assert r_unavail_bad.status_code == 422


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


def _worker_process_save(db_path_str: str, worker_id: int, return_dict: dict):
    from pathlib import Path
    import intel_digest_service as svc

    items = [{
        "title": "Concurrent Process Title",
        "source": "Process Source",
        "published_at": "2026-07-31T10:00:00+08:00",
        "url": "https://example.com/process-news",
    }]
    try:
        rec, deduped = svc.save_digest(
            sector_key="biotech",
            status="normal",
            summary_text=f"- Text from process {worker_id}",
            source_refs=[],
            input_items=items,
            db_path=Path(db_path_str),
        )
        return_dict[worker_id] = (True, deduped, rec["digest_id"])
    except Exception as e:
        return_dict[worker_id] = (False, str(e), None)


def test_atomic_sqlite_deduplication_multiprocess(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    manager = ctx.Manager()
    return_dict = manager.dict()
    db_p = tmp_path / "process_dedup.db"

    processes = [
        ctx.Process(target=_worker_process_save, args=(str(db_p), i, return_dict))
        for i in range(4)
    ]

    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=10)

    # All processes exited cleanly
    for p in processes:
        assert p.exitcode == 0

    results = dict(return_dict)
    assert len(results) == 4

    successes = [v for v in results.values() if v[0]]
    assert len(successes) == 4

    not_deduped = [v for v in successes if not v[1]]
    deduped = [v for v in successes if v[1]]

    assert len(not_deduped) == 1
    assert len(deduped) == 3

    # Assert database table has exactly 1 row
    with store._connect(db_p) as conn:
        count = conn.execute("SELECT COUNT(*) FROM intel_daily_digests").fetchone()[0]
        assert count == 1


# ── Round 4: source time integrity ───────────────────────────────────────────


def test_old_cache_migration_from_ts():
    """Old cache with only ts → published_at filled as Asia/Shanghai ISO."""
    import newsradar

    # 2026-07-31 10:00:00+08:00
    ts = int(datetime(2026, 7, 31, 2, 0, 0, tzinfo=timezone.utc).timestamp())
    item = {
        "title": "Old news",
        "source": "Wire",
        "url": "https://example.com/old",
        "ts": ts,
        "time": "07-31 10:00",
        # no published_at
    }
    migrated = newsradar.migrate_radar_item(dict(item))
    assert migrated["published_at"] is not None
    assert "+08:00" in migrated["published_at"] or migrated["published_at"].endswith("Z")
    # Round-trip: parsed value equals original instant
    parsed = datetime.fromisoformat(migrated["published_at"].replace("Z", "+00:00"))
    assert int(parsed.timestamp()) == ts


def test_old_cache_display_time_only_does_not_fabricate_published_at():
    """Old cache with only display time (no ts) → published_at stays null."""
    import newsradar

    item = {
        "title": "Display only",
        "source": "Wire",
        "url": "https://example.com/display",
        "time": "07-31 10:00",
        "ts": 0,
    }
    migrated = newsradar.migrate_radar_item(dict(item))
    assert migrated["published_at"] is None

    item2 = {
        "title": "Dash",
        "source": "Wire",
        "url": "https://example.com/dash",
        "time": "—",
    }
    migrated2 = newsradar.migrate_radar_item(dict(item2))
    assert migrated2["published_at"] is None


def test_cache_migration_fingerprint_stable_for_same_news():
    """Fingerprint of a news item is stable across migration (ts → published_at)."""
    import newsradar

    ts = int(datetime(2026, 7, 31, 2, 0, 0, tzinfo=timezone.utc).timestamp())
    base = {
        "title": "Stable News",
        "source": "Reuters",
        "url": "https://example.com/stable-news",
        "ts": ts,
        "summary": "Body",
    }
    # Pre-migration: construct published_at the same way migrate does, then fingerprint
    migrated_once = newsradar.migrate_radar_item(dict(base))
    migrated_twice = newsradar.migrate_radar_item(dict(migrated_once))

    assert migrated_once["published_at"] == migrated_twice["published_at"]

    items_a = [{
        "title": base["title"],
        "source": base["source"],
        "url": base["url"],
        "published_at": migrated_once["published_at"],
        "summary": base["summary"],
    }]
    items_b = [{
        "title": base["title"],
        "source": base["source"],
        "url": base["url"],
        "published_at": migrated_twice["published_at"],
        "summary": base["summary"],
    }]
    assert svc.compute_input_fingerprint("ai", items_a) == svc.compute_input_fingerprint("ai", items_b)


def test_undated_rss_does_not_fabricate_published_at():
    """Undated RSS items must keep published_at=None, time='—', ts=0 (no datetime.now)."""
    import newsradar
    from unittest.mock import patch, MagicMock

    # Minimal RSS with one item and no pubDate
    rss_xml = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Undated Article</title>
        <link>https://example.com/undated</link>
        <description>No date here</description>
      </item>
    </channel></rss>"""

    mock_resp = MagicMock()
    mock_resp.read.return_value = rss_xml
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    src = {"name": "TestSource", "url": "https://example.com/feed.xml"}
    with patch("urllib.request.urlopen", return_value=mock_resp):
        items1 = newsradar._fetch_source(src, per=5, cutoff=None, redline=[])
        items2 = newsradar._fetch_source(src, per=5, cutoff=None, redline=[])

    assert items1 is not None and len(items1) == 1
    assert items2 is not None and len(items2) == 1

    a, b = items1[0], items2[0]
    assert a["published_at"] is None
    assert a["time"] == "—"
    assert a["ts"] == 0
    assert b["published_at"] is None
    # Two runs must not invent different pseudo published_at values
    assert a["published_at"] == b["published_at"]
    assert a["ts"] == b["ts"]


def test_undated_items_excluded_from_fingerprint_stability():
    """When undated items are excluded, two canonical inputs remain identical."""
    # Only dated items contribute to fingerprint — undated ones never enter input_items
    dated = [{
        "title": "Dated",
        "source": "S",
        "url": "https://example.com/dated",
        "published_at": "2026-07-31T10:00:00+08:00",
    }]
    fp1 = svc.compute_input_fingerprint("ai", dated)
    fp2 = svc.compute_input_fingerprint("ai", dated)
    assert fp1 == fp2
