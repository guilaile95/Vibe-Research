"""每日复盘磁盘缓存 + 展示路径 stale-while-revalidate 离线测试。"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import daily_review
import daily_review_cache
import portfolio_advice_service as advice_svc


def _packet(status="normal", generated_at="2026-07-21 10:00:00"):
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": generated_at,
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": status,
        "warnings": [],
        "data_health": {
            "components": {
                "indices": "normal",
                "breadth": "normal",
                "emotion": "normal",
                "industry_boards": "normal",
                "concept_boards": "normal",
            }
        },
        "market_environment": {},
        "sector_rotation": {},
        "short_term_emotion": {},
        "capital_activity": {},
    }


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    # 模块在 import 时未缓存路径函数结果；cache_path 每次读 env
    daily_review._clear_review_cache()
    # 重置后台刷新标志
    with daily_review._bg_refresh_lock:
        daily_review._bg_refreshing = False
        daily_review._refresh_failed = False
        daily_review._refresh_error = None
    daily_review_cache.clear_latest_review_file()
    yield
    daily_review._clear_review_cache()
    with daily_review._bg_refresh_lock:
        daily_review._bg_refreshing = False
        daily_review._refresh_failed = False
        daily_review._refresh_error = None
    daily_review_cache.clear_latest_review_file()


def _packet_critical_unavailable(status="partial", generated_at="2026-07-21 12:00:00"):
    p = _packet(status=status, generated_at=generated_at)
    p["data_health"]["components"]["breadth"] = "unavailable"
    p["warnings"] = [
        "RuntimeError: a_share_snapshot page 6 request failed: "
        "HTTPSConnectionPool(host='push2.eastmoney.com', port=443): ProxyError"
    ]
    return p


# ── 1/2 persist rules ──────────────────────────────────────────────

def test_persist_normal_and_partial(tmp_path):
    ok_n = daily_review_cache.save_latest_review(
        _packet("normal"), saved_at="2026-07-21 10:00:00"
    )
    assert ok_n is True
    path = Path(daily_review_cache.cache_path())
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "daily-review-cache-v0.1"
    assert raw["review"]["status"] == "normal"

    # 无旧 normal 时 partial（关键组件正常）可落盘
    daily_review_cache.clear_latest_review_file()
    ok_p = daily_review_cache.save_latest_review(
        _packet("partial", generated_at="2026-07-21 11:00:00"),
        saved_at="2026-07-21 11:00:00",
    )
    assert ok_p is True
    review, saved_at = daily_review_cache.load_latest_review()
    assert review["status"] == "partial"
    assert saved_at == "2026-07-21 11:00:00"


def test_partial_does_not_overwrite_normal():
    daily_review_cache.save_latest_review(
        _packet("normal"), saved_at="2026-07-21 10:00:00"
    )
    before = Path(daily_review_cache.cache_path()).read_text(encoding="utf-8")
    ok = daily_review_cache.save_latest_review(
        _packet("partial", generated_at="later"),
        saved_at="2026-07-21 12:00:00",
    )
    assert ok is False
    assert Path(daily_review_cache.cache_path()).read_text(encoding="utf-8") == before
    rev, _ = daily_review_cache.load_latest_review()
    assert rev["status"] == "normal"
    assert rev["generated_at"] == "2026-07-21 10:00:00"


def test_critical_unavailable_partial_does_not_overwrite_normal():
    daily_review_cache.save_latest_review(
        _packet("normal"), saved_at="2026-07-21 10:00:00"
    )
    bad = _packet_critical_unavailable()
    assert daily_review_cache.save_latest_review(bad, saved_at="2026-07-21 13:00:00") is False
    rev, _ = daily_review_cache.load_latest_review()
    assert rev["status"] == "normal"
    assert rev["generated_at"] == "2026-07-21 10:00:00"


def test_unavailable_and_exception_do_not_overwrite():
    daily_review_cache.save_latest_review(
        _packet("normal"), saved_at="2026-07-21 10:00:00"
    )
    before = Path(daily_review_cache.cache_path()).read_text(encoding="utf-8")

    assert daily_review_cache.save_latest_review(
        _packet("unavailable"), saved_at="2026-07-21 12:00:00"
    ) is False
    assert Path(daily_review_cache.cache_path()).read_text(encoding="utf-8") == before

    # generate 路径：unavailable 不落盘
    daily_review._clear_review_cache()
    monkey_build = lambda: _packet("unavailable")
    with patch.object(daily_review, "_build_daily_review", monkey_build):
        out = daily_review.generate_daily_review()
    assert out["status"] == "unavailable"
    # 旧文件仍在
    rev, _ = daily_review_cache.load_latest_review()
    assert rev is not None
    assert rev["status"] == "normal"


def test_bad_file_safely_ignored(tmp_path):
    path = Path(daily_review_cache.cache_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert daily_review_cache.load_latest_review() == (None, None)

    path.write_text(json.dumps({"schema_version": "x", "review": None}), encoding="utf-8")
    assert daily_review_cache.load_latest_review() == (None, None)

    path.write_text(
        json.dumps({
            "schema_version": "daily-review-cache-v0.1",
            "saved_at": "2026-07-21 10:00:00",
            "review": _packet("unavailable"),
        }),
        encoding="utf-8",
    )
    assert daily_review_cache.load_latest_review() == (None, None)


# ── 4/5 display persisted + meta ───────────────────────────────────

def test_display_returns_persisted_immediately_with_stale_meta(monkeypatch):
    daily_review_cache.save_latest_review(
        _packet("normal", generated_at="2026-07-20 15:00:00"),
        saved_at="2026-07-20 15:00:00",
    )
    daily_review._clear_review_cache()

    builds = {"n": 0}
    barrier = threading.Event()

    def slow_build():
        builds["n"] += 1
        barrier.wait(timeout=2)
        return _packet("normal", generated_at="2026-07-21 12:00:00")

    monkeypatch.setattr(daily_review, "_build_daily_review", slow_build)
    payload = daily_review.get_daily_review_for_display()
    assert payload["data"]["generated_at"] == "2026-07-20 15:00:00"
    meta = payload["cache_meta"]
    assert meta["source"] == "persisted"
    assert meta["stale"] is True
    assert meta["refreshing"] is True
    assert meta["saved_at"] == "2026-07-20 15:00:00"
    assert meta["age_seconds"] is None or meta["age_seconds"] >= 0

    # 放行后台
    barrier.set()
    # 等后台完成
    for _ in range(50):
        if builds["n"] >= 1 and daily_review._cached_review() is not None:
            break
        time.sleep(0.05)
    assert builds["n"] == 1


def test_background_refresh_single_flight(monkeypatch):
    daily_review_cache.save_latest_review(
        _packet("normal"), saved_at="2026-07-20 15:00:00"
    )
    daily_review._clear_review_cache()

    builds = {"n": 0}
    entered = threading.Event()
    release = threading.Event()

    def slow_build():
        builds["n"] += 1
        entered.set()
        release.wait(timeout=3)
        return _packet("normal", generated_at="2026-07-21 13:00:00")

    monkeypatch.setattr(daily_review, "_build_daily_review", slow_build)

    p1 = daily_review.get_daily_review_for_display()
    p2 = daily_review.get_daily_review_for_display()
    assert p1["cache_meta"]["stale"] is True
    assert p2["cache_meta"]["stale"] is True
    assert entered.wait(timeout=2)
    # 后台仅一次聚合
    time.sleep(0.1)
    assert builds["n"] == 1
    release.set()
    for _ in range(50):
        if daily_review._cached_review() is not None:
            break
        time.sleep(0.05)
    assert builds["n"] == 1
    fresh = daily_review.get_daily_review_for_display()
    assert fresh["cache_meta"]["stale"] is False
    assert fresh["data"]["generated_at"] == "2026-07-21 13:00:00"


def test_refresh_success_replaces_disk(monkeypatch):
    daily_review_cache.save_latest_review(
        _packet("partial", generated_at="old"),
        saved_at="2026-07-20 15:00:00",
    )
    daily_review._clear_review_cache()
    monkeypatch.setattr(
        daily_review,
        "_build_daily_review",
        lambda: _packet("normal", generated_at="new-gen"),
    )
    # 同步 fresh 路径：normal 可替换 partial
    out = daily_review.generate_daily_review()
    assert out["status"] == "normal"
    rev, saved = daily_review_cache.load_latest_review()
    assert rev["generated_at"] == "new-gen"
    assert rev["status"] == "normal"


def test_refresh_failure_keeps_old(monkeypatch):
    daily_review_cache.save_latest_review(
        _packet("normal", generated_at="keep-me"),
        saved_at="2026-07-20 15:00:00",
    )
    daily_review._clear_review_cache()

    def boom():
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(daily_review, "_build_daily_review", boom)
    # 后台路径吞异常
    started = daily_review._kick_background_refresh()
    assert started is True
    for _ in range(40):
        if not daily_review._is_background_refreshing():
            break
        time.sleep(0.05)
    rev, _ = daily_review_cache.load_latest_review()
    assert rev is not None
    assert rev["generated_at"] == "keep-me"
    failed, err = daily_review._refresh_failure_state()
    assert failed is True
    assert err and "刷新失败" in err
    # 展示仍返回旧 normal，且 refresh_failed
    payload = daily_review.get_daily_review_for_display()
    assert payload["data"]["generated_at"] == "keep-me"
    assert payload["cache_meta"]["stale"] is True
    assert payload["cache_meta"]["refreshing"] is False
    assert payload["cache_meta"]["refresh_failed"] is True
    assert "ProxyError" not in json.dumps(payload, ensure_ascii=False)


def test_store_degraded_partial_does_not_replace_memory_normal(monkeypatch):
    monkeypatch.setattr(
        daily_review, "_build_daily_review",
        lambda: _packet("normal", generated_at="good"),
    )
    daily_review.generate_daily_review()
    assert daily_review._cached_review()["generated_at"] == "good"

    bad = _packet_critical_unavailable(generated_at="bad")
    daily_review._store_review(bad)
    assert daily_review._cached_review()["generated_at"] == "good"
    rev, _ = daily_review_cache.load_latest_review()
    assert rev["generated_at"] == "good"


def test_warnings_sanitized_no_proxy_leak(monkeypatch):
    def leaky():
        p = _packet("partial", generated_at="x")
        p["data_health"]["components"]["breadth"] = "unavailable"
        p["warnings"] = [
            "RuntimeError: a_share_snapshot page 6 request failed: "
            "HTTPSConnectionPool(host='push2.eastmoney.com', port=443): "
            "Max retries exceeded with url: /api/qt/clist/get?pn=6 (Caused by ProxyError(...))"
        ]
        p["market_environment"] = {
            "breadth": {
                "status": "unavailable",
                "warnings": ["ProxyError: Unable to connect to proxy"],
                "data": None,
            }
        }
        return p

    monkeypatch.setattr(daily_review, "_build_daily_review", leaky)
    out = daily_review.generate_daily_review()
    blob = json.dumps(out, ensure_ascii=False)
    assert "ProxyError" not in blob
    assert "HTTPSConnectionPool" not in blob
    assert "push2.eastmoney.com" not in blob
    assert "https://" not in blob
    assert any("市场广度" in w or "全市场" in w for w in out["warnings"])


# ── 9 portfolio advice 不使用 stale ─────────────────────────────────

def test_portfolio_advice_does_not_use_stale(monkeypatch):
    daily_review_cache.save_latest_review(
        _packet("normal", generated_at="stale-disk"),
        saved_at="2026-07-20 15:00:00",
    )
    daily_review._clear_review_cache()

    builds = {"n": 0}

    def build():
        builds["n"] += 1
        return _packet("normal", generated_at="fresh-live")

    monkeypatch.setattr(daily_review, "_build_daily_review", build)

    # 展示可 stale
    disp = daily_review.get_daily_review_for_display()
    assert disp["data"]["generated_at"] == "stale-disk"
    assert disp["cache_meta"]["stale"] is True

    # advice 必须 generate_daily_review（fresh）
    seen = {}

    def fake_get_portfolio():
        return {
            "holdings": [{
                "code": "001896", "name": "X", "shares": 100, "cost": 10, "price": 11,
            }],
            "totals": {},
        }

    monkeypatch.setattr(advice_svc.portfolio, "get_portfolio", fake_get_portfolio)

    # 等展示后台可能抢锁；直接调 generate 验证拿到 fresh
    # 先等后台完成以免竞争
    for _ in range(50):
        if not daily_review._is_background_refreshing():
            break
        time.sleep(0.05)

    daily_review._clear_review_cache()
    builds["n"] = 0
    # 不启动 bg：直接 generate
    with patch.object(daily_review, "_kick_background_refresh", return_value=False):
        pass
    fresh = daily_review.generate_daily_review()
    assert fresh["generated_at"] == "fresh-live"
    assert builds["n"] == 1

    # prepare 也走 generate_daily_review
    builds["n"] = 0
    daily_review._clear_review_cache()
    prepared = advice_svc.prepare_portfolio_advice_messages()
    assert prepared["daily_review"]["generated_at"] == "fresh-live"
    assert builds["n"] == 1


def test_memory_hit_not_stale(monkeypatch):
    monkeypatch.setattr(
        daily_review, "_build_daily_review",
        lambda: _packet("normal", generated_at="mem"),
    )
    daily_review.generate_daily_review()
    payload = daily_review.get_daily_review_for_display()
    assert payload["cache_meta"]["source"] == "memory"
    assert payload["cache_meta"]["stale"] is False
    assert payload["data"]["generated_at"] == "mem"


def test_load_returns_deepcopy():
    daily_review_cache.save_latest_review(
        _packet("normal"), saved_at="2026-07-21 10:00:00"
    )
    a, _ = daily_review_cache.load_latest_review()
    b, _ = daily_review_cache.load_latest_review()
    assert a is not b
    a["status"] = "hacked"
    c, _ = daily_review_cache.load_latest_review()
    assert c["status"] == "normal"
