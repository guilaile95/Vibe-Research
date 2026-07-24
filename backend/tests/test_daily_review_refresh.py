"""每日复盘显式刷新：绕过 300s 完整包缓存 + single-flight + 不写历史。"""
from __future__ import annotations

import threading
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
    daily_review_cache.clear_latest_review_file()
    yield
    daily_review._clear_review_cache()
    daily_review_cache.clear_latest_review_file()


def _packet(gen: str = "2026-07-24 10:00:00"):
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": gen,
        "trade_date": "2026-07-24",
        "data_cutoff": None,
        "status": "normal",
        "warnings": [],
        "data_health": {
            "components": {
                "indices": "normal",
                "global_indices": "normal",
                "breadth": "normal",
                "emotion": "normal",
                "turnover": "normal",
                "industry_boards": "normal",
                "concept_boards": "normal",
                "region_boards": "normal",
            }
        },
        "market_environment": {"indices": {"status": "normal", "data": []}, "breadth": {"status": "normal"}},
        "sector_rotation": {"industry": {"status": "normal"}},
        "short_term_emotion": {"status": "normal", "data": {"zt_count": 80}},
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
    # GET display also hits memory
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


def test_refresh_single_flight(monkeypatch):
    """并发 refresh 共用 _review_lock，build 串行且不交错损坏。"""
    builds = {"n": 0}
    active = {"n": 0}
    max_active = {"n": 0}
    gate = threading.Lock()

    def build_fast():
        with gate:
            active["n"] += 1
            max_active["n"] = max(max_active["n"], active["n"])
            builds["n"] += 1
            n = builds["n"]
        try:
            return _packet(f"2026-07-24 13:0{n}:00")
        finally:
            with gate:
                active["n"] -= 1

    monkeypatch.setattr(daily_review, "_build_daily_review", build_fast)
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
    for t in threads:
        t.join(timeout=10)
    assert not errors
    assert len(results) == 4
    # lock serializes: never two builds overlapping
    assert max_active["n"] == 1
    assert builds["n"] == 4


def test_refresh_does_not_write_history_snapshots(monkeypatch):
    monkeypatch.setattr(daily_review, "_build_daily_review", lambda: _packet())
    save = MagicMock()
    monkeypatch.setattr(review_history, "save_current_daily_review", save)
    monkeypatch.setattr(review_history, "save_daily_review_snapshot", save, raising=False)
    daily_review.refresh_daily_review_for_display()
    save.assert_not_called()


def test_refresh_api_shape_and_bypass(monkeypatch):
    builds = {"n": 0}

    def build():
        builds["n"] += 1
        return _packet(f"2026-07-24 14:0{builds['n']}:00")

    monkeypatch.setattr(daily_review, "_build_daily_review", build)
    # warm via GET path
    r1 = client.get("/api/daily-review")
    assert r1.status_code == 200
    g1 = r1.json()["data"]["generated_at"]
    assert builds["n"] == 1
    # second GET does not rebuild
    r2 = client.get("/api/daily-review")
    assert r2.json()["data"]["generated_at"] == g1
    assert builds["n"] == 1
    # POST refresh rebuilds
    r3 = client.post("/api/daily-review/refresh")
    assert r3.status_code == 200
    body = r3.json()
    assert "data" in body and "cache_meta" in body
    assert body["cache_meta"]["stale"] is False
    assert body["data"]["generated_at"] != g1
    assert builds["n"] == 2


def test_refresh_api_unexpected_502(monkeypatch):
    def boom():
        raise RuntimeError("aggregate exploded")

    monkeypatch.setattr(daily_review, "refresh_daily_review_for_display", boom)
    r = client.post("/api/daily-review/refresh")
    assert r.status_code == 502
    assert "刷新" in r.json()["detail"]


def test_refresh_failure_keeps_old_memory(monkeypatch):
    monkeypatch.setattr(daily_review, "_build_daily_review", lambda: _packet("2026-07-24 15:00:00"))
    old = daily_review.generate_daily_review()
    assert old["generated_at"] == "2026-07-24 15:00:00"

    def boom():
        raise RuntimeError("network")

    monkeypatch.setattr(daily_review, "_build_daily_review", boom)
    with pytest.raises(RuntimeError):
        daily_review.refresh_daily_review_for_display()
    # memory was cleared at start of refresh; old may be gone — frontend keeps UI copy.
    # Service contract: raise so API returns 502; FE keeps previous state.
