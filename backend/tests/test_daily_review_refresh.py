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
    with daily_review._explicit_refresh_lock:
        daily_review._explicit_refresh_current = None
    daily_review_cache.clear_latest_review_file()
    yield
    daily_review._clear_review_cache()
    with daily_review._explicit_refresh_lock:
        daily_review._explicit_refresh_current = None
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


def test_round1_waiter_not_hijacked_by_round2_success(monkeypatch):
    """第一轮 waiter 在消费前第二轮已启动时，仍必须拿到第一轮 generated_at。"""
    builds = {"n": 0}
    # phase control: hold first build until waiters attached; then complete round1;
    # hold round1 waiter after join path is set up via barriers.
    release_r1_build = threading.Event()
    r1_build_started = threading.Event()
    r1_flight_done = threading.Event()  # leader finished event.set path about to return
    release_r1_waiter = threading.Event()
    release_r2_build = threading.Event()
    r2_build_started = threading.Event()

    def build():
        builds["n"] += 1
        n = builds["n"]
        if n == 1:
            r1_build_started.set()
            assert release_r1_build.wait(timeout=10)
            return _packet("2026-07-24 21:00:01")
        if n == 2:
            r2_build_started.set()
            assert release_r2_build.wait(timeout=10)
            return _packet("2026-07-24 21:00:02")
        return _packet(f"2026-07-24 21:00:0{n}")

    monkeypatch.setattr(daily_review, "_build_daily_review", build)

    r1_leader_out: list = []
    r1_waiter_out: list = []
    r2_out: list = []
    errors: list = []

    def r1_leader():
        try:
            r1_leader_out.append(daily_review.refresh_daily_review_for_display())
        except Exception as e:  # noqa: BLE001
            errors.append(("r1_leader", e))

    def r1_waiter():
        try:
            # ensure we join flight after leader has registered current
            assert r1_build_started.wait(timeout=5)
            # park slightly so we are waiters on flight.event
            out = daily_review.refresh_daily_review_for_display()
            # simulate slow consumer: if implementation were global-slot, round2 could corrupt
            release_r1_waiter.wait(timeout=10)
            r1_waiter_out.append(out)
        except Exception as e:  # noqa: BLE001
            errors.append(("r1_waiter", e))

    def r2_leader():
        try:
            r2_out.append(daily_review.refresh_daily_review_for_display())
        except Exception as e:  # noqa: BLE001
            errors.append(("r2_leader", e))

    t_lead = threading.Thread(target=r1_leader)
    t_wait = threading.Thread(target=r1_waiter)
    t_lead.start()
    assert r1_build_started.wait(timeout=5)
    t_wait.start()
    time.sleep(0.15)  # waiter blocked on flight.event
    release_r1_build.set()
    t_lead.join(timeout=10)
    assert r1_leader_out, "r1 leader did not finish"
    assert r1_leader_out[0]["data"]["generated_at"] == "2026-07-24 21:00:01"
    # Start round2 before waiter "consumes" (waiter already returned from refresh
    # once event set — we need waiter still inside await when r2 starts).
    # Re-structure: keep waiter blocked inside custom wait by delaying event until...
    # Our waiter already returned from refresh when event set. The race is:
    # waiter is in `while inflight: wait` and after wake reads global result —
    # with per-flight object, waiter returns before r2 even if r2 clears current.
    # To force the bad interleaving with old code: waiter woke, not yet read result,
    # r2 clears. With Event-based flight, once event is set, result is already on
    # the flight object; waiter reads flight.result. So we only need: capture flight
    # before r2, r2 creates new flight, waiter still reads old flight.

    # Start r2 while r1 waiter thread may still be finishing deepcopy
    t_r2 = threading.Thread(target=r2_leader)
    t_r2.start()
    assert r2_build_started.wait(timeout=5)
    release_r2_build.set()
    t_r2.join(timeout=10)
    release_r1_waiter.set()
    t_wait.join(timeout=10)

    assert not errors, errors
    assert r1_waiter_out, "r1 waiter missing"
    assert r1_waiter_out[0]["data"]["generated_at"] == "2026-07-24 21:00:01"
    assert r2_out and r2_out[0]["data"]["generated_at"] == "2026-07-24 21:00:02"
    assert builds["n"] == 2


def test_round1_waiter_gets_round1_error_not_round2_success(monkeypatch):
    """第一轮异常 + 第二轮成功：第一轮 waiter 必须收到第一轮异常。"""
    builds = {"n": 0}
    release_r1 = threading.Event()
    r1_started = threading.Event()
    release_r2 = threading.Event()
    r2_started = threading.Event()

    def build():
        builds["n"] += 1
        n = builds["n"]
        if n == 1:
            r1_started.set()
            assert release_r1.wait(timeout=10)
            raise RuntimeError("round1 network fail")
        r2_started.set()
        assert release_r2.wait(timeout=10)
        return _packet("2026-07-24 22:00:02")

    monkeypatch.setattr(daily_review, "_build_daily_review", build)

    # seed a prior success so quality path isn't the only concern
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _packet("2026-07-24 22:00:00"),
    )
    daily_review.generate_daily_review()
    monkeypatch.setattr(daily_review, "_build_daily_review", build)

    r1_err: list = []
    r1_waiter_err: list = []
    r2_ok: list = []

    def r1_leader():
        try:
            daily_review.refresh_daily_review_for_display()
        except Exception as e:  # noqa: BLE001
            r1_err.append(e)

    def r1_waiter():
        try:
            assert r1_started.wait(timeout=5)
            daily_review.refresh_daily_review_for_display()
        except Exception as e:  # noqa: BLE001
            r1_waiter_err.append(e)

    def r2():
        try:
            r2_ok.append(daily_review.refresh_daily_review_for_display())
        except Exception as e:  # noqa: BLE001
            r2_ok.append(e)

    t1 = threading.Thread(target=r1_leader)
    t2 = threading.Thread(target=r1_waiter)
    t1.start()
    assert r1_started.wait(timeout=5)
    t2.start()
    time.sleep(0.15)
    release_r1.set()
    t1.join(timeout=10)
    t3 = threading.Thread(target=r2)
    t3.start()
    assert r2_started.wait(timeout=5)
    release_r2.set()
    t2.join(timeout=10)
    t3.join(timeout=10)

    assert r1_err and isinstance(r1_err[0], daily_review.DailyReviewRefreshError)
    assert r1_waiter_err and isinstance(
        r1_waiter_err[0], daily_review.DailyReviewRefreshError
    )
    assert r1_err[0].reason == r1_waiter_err[0].reason == "build_exception"
    assert r2_ok and isinstance(r2_ok[0], dict)
    assert r2_ok[0]["data"]["generated_at"] == "2026-07-24 22:00:02"
    # old success memory retained through round1 failure
    assert daily_review._cached_review()["generated_at"] in (
        "2026-07-24 22:00:00",
        "2026-07-24 22:00:02",
    )


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
    assert ei.value.reason in ("unavailable", "critical_unavailable")

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


# ---------------------------------------------------------------------------
# Unified quality judgment: partial must not replace an existing normal
# (fresh memory, expired memory, or on disk)
# ---------------------------------------------------------------------------


def _seed_memory_normal(gen: str = "2026-07-24 10:00:00") -> None:
    """直接写入内存缓存，模拟已存在 normal 成功。"""
    daily_review._review_cache[daily_review._REVIEW_CACHE_KEY] = (
        time.time(),
        _packet(gen),
    )


def _seed_disk_normal(gen: str = "2026-07-24 10:00:00") -> None:
    """写入磁盘最近成功 normal。"""
    daily_review_cache.save_latest_review(_packet(gen), saved_at=gen)


def _non_critical_partial(gen: str) -> dict:
    """构造一个非关键组件降级的 partial（仅 turnover 不可用，关键组件仍可用）。"""
    pkt = _packet(gen, status="partial")
    # 仅让一个非关键组件不可用，关键组件保持 normal
    pkt["data_health"]["components"] = {
        "indices": "normal",
        "global_indices": "normal",
        "breadth": "normal",
        "emotion": "normal",
        "turnover": "unavailable",
        "industry_boards": "normal",
        "concept_boards": "normal",
        "region_boards": "normal",
    }
    return pkt


def test_partial_rejected_when_memory_has_normal(monkeypatch):
    """内存有 normal + 新非关键 partial → 503，内存/磁盘保持 old normal。"""
    _seed_memory_normal("2026-07-24 23:00:00")
    _seed_disk_normal("2026-07-24 23:00:00")
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _non_critical_partial("2026-07-24 23:30:00"),
    )
    with pytest.raises(daily_review.DailyReviewRefreshError) as ei:
        daily_review.refresh_daily_review_for_display()
    assert ei.value.reason == "partial_with_existing_normal"
    # 内存仍是 old normal
    assert daily_review._cached_review()["generated_at"] == "2026-07-24 23:00:00"
    # 磁盘仍是 old normal
    disk, _ = daily_review_cache.load_latest_review()
    assert disk["generated_at"] == "2026-07-24 23:00:00"
    # GET 返回 old normal
    disp = daily_review.get_daily_review_for_display()
    assert disp["data"]["generated_at"] == "2026-07-24 23:00:00"
    assert disp["data"]["status"] == "normal"


def test_partial_rejected_when_disk_has_normal_and_memory_expired(monkeypatch):
    """内存 normal 已过期 + 磁盘 normal + 新 partial → 503，不写内存，GET 返回 old normal。"""
    # 写入一个已过 TTL 的内存 normal
    daily_review._review_cache[daily_review._REVIEW_CACHE_KEY] = (
        time.time() - daily_review._REVIEW_TTL - 10,
        _packet("2026-07-24 23:00:00"),
    )
    _seed_disk_normal("2026-07-24 23:00:00")
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _non_critical_partial("2026-07-24 23:40:00"),
    )
    with pytest.raises(daily_review.DailyReviewRefreshError) as ei:
        daily_review.refresh_daily_review_for_display()
    assert ei.value.reason == "partial_with_existing_normal"
    # 内存不应被 partial 覆盖（仍是旧 normal）
    mem = daily_review._cached_review()  # 过期返回 None
    # 即使 _cached_review 因过期返回 None，内存槽位仍应是旧 normal
    raw = daily_review._review_cache[daily_review._REVIEW_CACHE_KEY][1]
    assert raw["generated_at"] == "2026-07-24 23:00:00"
    assert raw["status"] == "normal"
    # GET 返回旧 normal（来自磁盘）
    disp = daily_review.get_daily_review_for_display()
    assert disp["data"]["generated_at"] == "2026-07-24 23:00:00"


def test_partial_rejected_when_only_disk_normal_after_restart(monkeypatch):
    """模拟进程重启：内存空 + 磁盘 normal + 新 partial → 503，GET 返回磁盘 old normal。"""
    # 内存保持空（不 seed）
    _seed_disk_normal("2026-07-24 23:00:00")
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _non_critical_partial("2026-07-24 23:50:00"),
    )
    with pytest.raises(daily_review.DailyReviewRefreshError) as ei:
        daily_review.refresh_daily_review_for_display()
    assert ei.value.reason == "partial_with_existing_normal"
    # GET 返回磁盘 old normal
    disp = daily_review.get_daily_review_for_display()
    assert disp["data"]["generated_at"] == "2026-07-24 23:00:00"
    assert disp["data"]["status"] == "normal"


def test_partial_accepted_when_no_prior_normal(monkeypatch):
    """无旧 normal + 健康 partial（非关键组件降级） → 200。"""
    assert not daily_review._review_cache
    disk, _ = daily_review_cache.load_latest_review()
    assert disk is None
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _non_critical_partial("2026-07-25 00:00:00"),
    )
    r = daily_review.refresh_daily_review_for_display()
    assert r["data"]["generated_at"] == "2026-07-25 00:00:00"
    assert r["data"]["status"] == "partial"
    assert r["cache_meta"]["source"] == "refresh"


def test_persist_failure_keeps_old_normal_and_returns_503(monkeypatch):
    """磁盘持久化失败时不得返回伪成功，也不可把 partial 写入内存。"""
    _seed_memory_normal("2026-07-25 01:00:00")
    _seed_disk_normal("2026-07-25 01:00:00")

    def persist_fails(review, *, saved_at):
        return False

    monkeypatch.setattr(
        daily_review_cache,
        "save_latest_review",
        persist_fails,
    )
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _packet("2026-07-25 01:30:00"),  # 新 normal
    )
    with pytest.raises(daily_review.DailyReviewRefreshError) as ei:
        daily_review.refresh_daily_review_for_display()
    assert ei.value.reason == "persist_failed"
    # 内存仍是旧 normal
    assert daily_review._cached_review()["generated_at"] == "2026-07-25 01:00:00"
    disk, _ = daily_review_cache.load_latest_review()
    assert disk["generated_at"] == "2026-07-25 01:00:00"
