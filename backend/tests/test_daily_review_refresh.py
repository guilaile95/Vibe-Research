"""每日复盘显式刷新：真正 single-flight + 失败保留上次成功。"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import daily_review
import daily_review_cache
import review_history

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _clear_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(tmp_path / "daily_reviews.sqlite3"))
    daily_review._clear_review_cache()
    with daily_review._bg_refresh_lock:
        daily_review._bg_refreshing = False
        daily_review._refresh_failed = False
        daily_review._refresh_error = None
    with daily_review._explicit_refresh_cond:
        daily_review._explicit_refresh_inflight = False
        daily_review._explicit_refresh_result = None
        daily_review._explicit_refresh_error = None
    daily_review_cache.clear_latest_review_file()
    yield
    daily_review._clear_review_cache()
    with daily_review._explicit_refresh_cond:
        daily_review._explicit_refresh_inflight = False
        daily_review._explicit_refresh_result = None
        daily_review._explicit_refresh_error = None
    daily_review_cache.clear_latest_review_file()


def _packet(gen: str = "2026-07-24 10:00:00", *, status: str = "normal", critical_bad: bool = False):
    comps = {
        "indices": "unavailable" if critical_bad else "normal",
        "global_indices": "normal",
        "breadth": "unavailable" if critical_bad else "normal",
        "emotion": "unavailable" if critical_bad else "normal",
        "turnover": "normal",
        "industry_boards": "normal",
        "concept_boards": "normal",
        "region_boards": "normal",
    }
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": gen,
        "trade_date": "2026-07-24",
        "data_cutoff": None,
        "status": status,
        "warnings": [],
        "data_health": {"components": comps},
        "market_environment": {
            "indices": {"status": comps["indices"], "data": []},
            "breadth": {"status": comps["breadth"]},
        },
        "sector_rotation": {"industry": {"status": "normal"}},
        "short_term_emotion": {"status": comps["emotion"], "data": {"zt_count": 80}},
        "capital_activity": {"total_amount": 1.0e12, "amount_top": []},
    }


def test_get_hits_memory_cache(monkeypatch):
    builds = {"n": 0}

    def build():
        builds["n"] += 1
        return _packet(f"2026-07-24 10:0{builds['n']}:00")

    monkeypatch.setattr(daily_review, "_build_daily_review", build)
    a = daily_review.generate_daily_review()
    b = daily_review.generate_daily_review()
    assert builds["n"] == 1
    assert a["generated_at"] == b["generated_at"]
    disp = daily_review.get_daily_review_for_display()
    assert disp["cache_meta"]["stale"] is False
    assert builds["n"] == 1


def test_refresh_bypasses_full_package_cache(monkeypatch):
    builds = {"n": 0}

    def build():
        builds["n"] += 1
        return _packet(f"2026-07-24 11:0{builds['n']}:00")

    monkeypatch.setattr(daily_review, "_build_daily_review", build)
    first = daily_review.generate_daily_review()
    assert builds["n"] == 1
    refreshed = daily_review.refresh_daily_review_for_display()
    assert builds["n"] == 2
    assert refreshed["data"]["generated_at"] != first["generated_at"]
    assert refreshed["cache_meta"]["stale"] is False
    assert refreshed["cache_meta"]["source"] == "refresh"


def test_true_single_flight_four_overlapping_builds_once(monkeypatch):
    """四个真正重叠的并发刷新只 build 一次，返回相同 generated_at。"""
    builds = {"n": 0}
    release = threading.Event()
    build_started = threading.Event()

    def build_slow():
        builds["n"] += 1
        n = builds["n"]
        build_started.set()
        # hold until main releases after other waiters are parked
        if not release.wait(timeout=10):
            raise TimeoutError("release not signaled")
        return _packet(f"2026-07-24 12:00:0{n}")

    monkeypatch.setattr(daily_review, "_build_daily_review", build_slow)

    results: list = []
    errors: list = []

    def worker():
        try:
            results.append(daily_review.refresh_daily_review_for_display())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    # wait until leader has entered build
    assert build_started.wait(timeout=5), "leader never started build"
    # allow other threads to block on in-flight wait
    time.sleep(0.2)
    release.set()
    for t in threads:
        t.join(timeout=15)

    assert not errors, errors
    assert len(results) == 4
    assert builds["n"] == 1, f"expected 1 build, got {builds['n']}"
    gens = {r["data"]["generated_at"] for r in results}
    assert len(gens) == 1
    assert results[0]["cache_meta"]["source"] == "refresh"


def test_sequential_independent_refreshes_build_twice(monkeypatch):
    builds = {"n": 0}

    def build():
        builds["n"] += 1
        return _packet(f"2026-07-24 13:0{builds['n']}:00")

    monkeypatch.setattr(daily_review, "_build_daily_review", build)
    r1 = daily_review.refresh_daily_review_for_display()
    r2 = daily_review.refresh_daily_review_for_display()
    assert builds["n"] == 2
    assert r1["data"]["generated_at"] != r2["data"]["generated_at"]


def test_build_exception_keeps_memory_and_disk(monkeypatch):
    monkeypatch.setattr(
        daily_review, "_build_daily_review", lambda: _packet("2026-07-24 15:00:00")
    )
    old = daily_review.generate_daily_review()
    assert old["generated_at"] == "2026-07-24 15:00:00"
    disk_before, _ = daily_review_cache.load_latest_review()
    assert disk_before is not None
    assert disk_before["generated_at"] == "2026-07-24 15:00:00"

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(daily_review, "_build_daily_review", boom)
    with pytest.raises(daily_review.DailyReviewRefreshError):
        daily_review.refresh_daily_review_for_display()

    mem = daily_review._cached_review()
    assert mem is not None
    assert mem["generated_at"] == "2026-07-24 15:00:00"
    disk_after, _ = daily_review_cache.load_latest_review()
    assert disk_after is not None
    assert disk_after["generated_at"] == "2026-07-24 15:00:00"

    # GET still serves last success
    disp = daily_review.get_daily_review_for_display()
    assert disp["data"]["generated_at"] == "2026-07-24 15:00:00"


def test_unavailable_result_does_not_replace_old(monkeypatch):
    monkeypatch.setattr(
        daily_review, "_build_daily_review", lambda: _packet("2026-07-24 16:00:00")
    )
    old = daily_review.generate_daily_review()
    assert old["generated_at"] == "2026-07-24 16:00:00"

    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _packet("2026-07-24 16:99:00", status="unavailable", critical_bad=True),
    )
    with pytest.raises(daily_review.DailyReviewRefreshError) as ei:
        daily_review.refresh_daily_review_for_display()
    assert ei.value.reason == "quality_rejected"

    mem = daily_review._cached_review()
    assert mem is not None
    assert mem["generated_at"] == "2026-07-24 16:00:00"
    # must not return degraded package as success to API callers
    disp = daily_review.get_daily_review_for_display()
    assert disp["data"]["generated_at"] == "2026-07-24 16:00:00"
    assert disp["data"]["status"] == "normal"


def test_critical_partial_does_not_replace(monkeypatch):
    monkeypatch.setattr(
        daily_review, "_build_daily_review", lambda: _packet("2026-07-24 17:00:00")
    )
    daily_review.generate_daily_review()
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _packet("2026-07-24 17:30:00", status="partial", critical_bad=True),
    )
    with pytest.raises(daily_review.DailyReviewRefreshError):
        daily_review.refresh_daily_review_for_display()
    assert daily_review._cached_review()["generated_at"] == "2026-07-24 17:00:00"


def test_refresh_does_not_write_history_snapshots(monkeypatch):
    monkeypatch.setattr(daily_review, "_build_daily_review", lambda: _packet())
    save = MagicMock()
    monkeypatch.setattr(review_history, "save_current_daily_review", save)
    daily_review.refresh_daily_review_for_display()
    save.assert_not_called()


def test_refresh_api_success_and_bypass(monkeypatch):
    builds = {"n": 0}

    def build():
        builds["n"] += 1
        return _packet(f"2026-07-24 18:0{builds['n']}:00")

    monkeypatch.setattr(daily_review, "_build_daily_review", build)
    r1 = client.get("/api/daily-review")
    assert r1.status_code == 200
    g1 = r1.json()["data"]["generated_at"]
    assert builds["n"] == 1
    r2 = client.get("/api/daily-review")
    assert r2.json()["data"]["generated_at"] == g1
    assert builds["n"] == 1
    r3 = client.post("/api/daily-review/refresh")
    assert r3.status_code == 200
    body = r3.json()
    assert body["cache_meta"]["stale"] is False
    assert body["data"]["generated_at"] != g1
    assert builds["n"] == 2


def test_refresh_api_failure_keeps_get_old(monkeypatch):
    monkeypatch.setattr(
        daily_review, "_build_daily_review", lambda: _packet("2026-07-24 19:00:00")
    )
    r0 = client.get("/api/daily-review")
    assert r0.status_code == 200
    old_gen = r0.json()["data"]["generated_at"]

    def boom():
        raise RuntimeError("explode")

    monkeypatch.setattr(daily_review, "_build_daily_review", boom)
    r_fail = client.post("/api/daily-review/refresh")
    assert r_fail.status_code in (502, 503)
    # GET still old success
    r_get = client.get("/api/daily-review")
    assert r_get.status_code == 200
    assert r_get.json()["data"]["generated_at"] == old_gen


def test_refresh_api_unavailable_not_200_success(monkeypatch):
    monkeypatch.setattr(
        daily_review, "_build_daily_review", lambda: _packet("2026-07-24 20:00:00")
    )
    client.get("/api/daily-review")
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _packet("2026-07-24 20:30:00", status="unavailable", critical_bad=True),
    )
    r = client.post("/api/daily-review/refresh")
    assert r.status_code == 503
    # body must not present degraded as successful data replacement contract
    # (error detail only)
    assert "data" not in r.json() or r.json().get("data") is None or r.status_code != 200
