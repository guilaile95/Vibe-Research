"""Full-page browser mocks equal registered HTTP output from synthetic stores.

This parity test is separate from the browser; it makes no browser-to-real-DB
or genuine-provider claim. Fixture setup writes only fresh temporary archives.
"""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

import cohort_identity_service as cohort
import short_term_fact_store as store
import limit_up_shadow as shadow
import next_day_verification as journal
import evidence_readiness_service as readiness
from fact_lake_store import initialize_fact_lake
from test_cohort_identity import persist
from test_short_term_seal_quality_service import publish, tree, http_get

DAYS = ("2026-07-31", "2026-07-30", "2026-07-29")
UNAVAILABLE = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/daily-review-readiness-unavailable.json"
GOLDEN = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/daily-review-integrated.json"


def seed_archives(monkeypatch, root):
    monkeypatch.setenv("VR_DATA_DIR", str(root / "facts"))
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(root / "lake"))
    monkeypatch.setattr(store, "_utc_now", lambda: "2026-08-01T01:00:00+00:00")
    monkeypatch.setattr(cohort, "_now", lambda: datetime(2026, 8, 3, tzinfo=timezone.utc))
    monkeypatch.setattr(journal, "_now", lambda: datetime(2026, 8, 3, tzinfo=timezone.utc))
    original = shadow.RawCaptureBuffer
    class FixedCapture(original):
        def __call__(self, raw_bytes, metadata):
            super().__call__(raw_bytes, metadata)
            # A stable, synthetic event identity, never a substitute raw receipt.
            self.capture = replace(self.capture, capture_event_id="capture-" + hashlib.sha256(raw_bytes).hexdigest()[:32])
    monkeypatch.setattr(shadow, "RawCaptureBuffer", FixedCapture)
    lake = initialize_fact_lake(root / "lake")
    for index, day in enumerate(reversed(DAYS + ("2026-07-28",))):
        persist(day, [("600001.SH", index + 1), (f"00000{index + 1}.SZ", 1)])
        publish(lake, day=day, boards=index + 1)


@pytest.fixture
def archives(monkeypatch, tmp_path):
    seed_archives(monkeypatch, tmp_path)
    return tmp_path


def test_integrated_browser_goldens_equal_real_registered_readonly_routes(archives, http_get):
    before = tree(archives)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(golden) == set(DAYS)
    for day in DAYS:
        for name in ("seal-quality", "cohort-identity", "evidence-readiness"):
            response = http_get(f"/api/market/{name}?trade_date={day}")
            assert response.status_code == 200
            actual = response.json()["data"]
            if name != "evidence-readiness":
                assert actual["status"] == "normal", actual
            assert actual == golden[day][name]
    assert tree(archives) == before


def test_integrated_journal_write_matches_same_ready_archive(archives):
    # An explicitly expected synthetic write, unlike the read-only route test.
    saved = journal.replace_plan(DAYS[0], journal.SavePlan(revision=0, items=[journal.Condition(
        metric="limit_up_count", direction="up", reason="Synthetic prior condition")]))
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))[DAYS[0]]["journal-saved"]
    assert saved == expected
    assert saved["items"][0]["prior_value"] == 2
    before = tree(archives)
    assert journal.view(DAYS[0]) == expected
    assert tree(archives) == before


def test_unavailable_readiness_fixture_matches_real_empty_configuration(monkeypatch, tmp_path, http_get):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "missing"))
    monkeypatch.delenv("VR_FACT_LAKE_ROOT", raising=False)
    monkeypatch.setattr(journal, "_now", lambda: datetime(2026, 8, 3, tzinfo=timezone.utc))
    before = tree(tmp_path)
    response = http_get("/api/market/evidence-readiness?trade_date=" + DAYS[0])
    assert response.status_code == 200
    assert response.json()["data"] == json.loads(UNAVAILABLE.read_text(encoding="utf-8"))
    assert tree(tmp_path) == before
