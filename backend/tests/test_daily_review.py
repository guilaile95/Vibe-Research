"""generate_daily_review 结构化每日复盘聚合器离线测试（全部 Mock，不联网）。"""
from __future__ import annotations

import threading
import time

import pytest

import daily_review
import market
import portfolio_advice_service


@pytest.fixture(autouse=True)
def _clear_daily_review_cache():
    """每个用例前后清空完整复盘缓存，避免用例间污染。"""
    daily_review._clear_review_cache()
    yield
    daily_review._clear_review_cache()


def _idx():
    return [
        {"name": "上证指数", "price": 3000.0, "change_pct": 0.5, "change_amt": 15.0},
        {"name": "深证成指", "price": 10000.0, "change_pct": -0.2, "change_amt": -20.0},
    ]


def _global():
    return [{"name": "道琼斯", "price": 39000.0, "change_pct": 0.1}]


def _breadth_env(
    *,
    status="normal",
    trade_date=None,
    total_amount=1.2e12,
    amount_valid_count=5000,
    warnings=None,
):
    data = None
    if status != "unavailable":
        data = {
            "stock_count": 5000,
            "valid_count": 4900,
            "up_count": 3000,
            "down_count": 1800,
            "flat_count": 100,
            "up_ratio": 0.6122,
            "up_3pct_count": 500,
            "down_3pct_count": 200,
            "total_amount": total_amount,
            "amount_valid_count": amount_valid_count,
            "amount_top": [{"code": "600519", "name": "茅台", "amount": 1e10}],
            "high_turnover": [{"code": "000001", "name": "平安", "turnover_pct": 20.0}],
        }
    return {
        "status": status,
        "source": "eastmoney_push2",
        "trade_date": trade_date,
        "data_time": None,
        "fetched_at": "2026-07-21 15:00:00",
        "is_stale": False,
        "warnings": list(warnings if warnings is not None else ["源数据未提供明确交易日期和行情时间"]),
        "data": data,
    }


def _emotion(date="2026-07-21", zt=80):
    return {
        "date": date,
        "zt_count": zt,
        "dt_count": 10,
        "zb_count": 20,
        "max_boards": 5,
        "lianban_count": 15,
        "ladder": [{"boards": 2, "count": 10, "plus": False}],
        "seal_rate": 0.8,
        "break_rate": 0.2,
        "promotion_rate": 0.3,
        "yzt_count": 50,
        "lianban_stocks": [{"code": "000001", "name": "测试", "boards": 2}],
    }


def _turnover():
    return {
        "stocks": [{"code": "600519", "name": "茅台", "amount": 1e10}],
        "updated": "2026-07-21 15:00",
    }


def _board(kind, status="normal"):
    data = None
    if status != "unavailable":
        data = {
            "type": kind,
            "total": 80,
            "ranked_count": 80 if status == "normal" else 70,
            "unknown_count": 0 if status == "normal" else 10,
            "top": [{"code": f"{kind[:2].upper()}1", "name": f"强{kind}", "change_pct": 5.0}],
            "bottom": [{"code": f"{kind[:2].upper()}2", "name": f"弱{kind}", "change_pct": -3.0}],
        }
    return {
        "status": status,
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:00:00",
        "is_stale": False,
        "warnings": ["源数据未提供明确交易日期和行情时间"]
        + ([f"有 10 个板块缺少有效涨跌幅"] if status == "partial" else []),
        "data": data,
    }


def _install_all_ok(monkeypatch, *, emotion_date="2026-07-21"):
    counts = {
        "index": 0, "global": 0, "breadth": 0, "emotion": 0,
        "turnover": 0, "boards": [],
    }

    def index_quote():
        counts["index"] += 1
        return _idx()

    def global_idx():
        counts["global"] += 1
        return _global()

    def breadth():
        counts["breadth"] += 1
        return _breadth_env()

    def emotion():
        counts["emotion"] += 1
        return _emotion(date=emotion_date)

    def turnover():
        counts["turnover"] += 1
        return _turnover()

    def boards(board_type="industry", top_n=20):
        counts["boards"].append((board_type, top_n))
        return _board(board_type)

    monkeypatch.setattr(daily_review.astock, "index_quote", index_quote)
    monkeypatch.setattr(market, "get_global_indices", global_idx)
    monkeypatch.setattr(market, "get_market_breadth", breadth)
    monkeypatch.setattr(market, "get_short_term_emotion", emotion)
    monkeypatch.setattr(market, "get_turnover_top", turnover)
    monkeypatch.setattr(market, "get_board_ranking", boards)
    # 旧总览一旦调用即失败
    monkeypatch.setattr(market, "get_overview", lambda: (_ for _ in ()).throw(RuntimeError("get_overview forbidden")))
    monkeypatch.setattr(market, "_sectors", lambda: (_ for _ in ()).throw(RuntimeError("_sectors forbidden")))
    return counts


# ── 1 全部正常 ──────────────────────────────────────────────────────

def test_daily_review_all_normal(monkeypatch):
    counts = _install_all_ok(monkeypatch)
    out = daily_review.generate_daily_review()
    assert out["schema_version"] == "daily-review-v0.1"
    assert out["status"] == "normal"
    assert out["trade_date"] == "2026-07-21"
    assert out["data_cutoff"] is None
    for k in (
        "market_environment", "sector_rotation", "short_term_emotion",
        "capital_activity", "data_health", "warnings", "generated_at",
    ):
        assert k in out
    assert out["market_environment"]["indices"]["status"] == "normal"
    assert out["market_environment"]["breadth"]["status"] == "normal"
    assert out["short_term_emotion"]["status"] == "normal"
    assert out["sector_rotation"]["highlights"]["strongest_industry"]["name"] == "强industry"
    assert out["sector_rotation"]["highlights"]["weakest_concept"]["name"] == "弱concept"
    assert counts["breadth"] == 1
    assert ("industry", 10) in counts["boards"]
    assert ("concept", 10) in counts["boards"]
    assert ("region", 10) in counts["boards"]


# ── 2 亮点提取 ──────────────────────────────────────────────────────

def test_highlights_extraction(monkeypatch):
    _install_all_ok(monkeypatch)
    out = daily_review.generate_daily_review()
    h = out["sector_rotation"]["highlights"]
    assert h["strongest_industry"]["change_pct"] == 5.0
    assert h["weakest_industry"]["change_pct"] == -3.0

    # 空 top/bottom（需清缓存后重聚合，模拟不同源数据）
    def empty_board(board_type="industry", top_n=20):
        env = _board(board_type)
        env["data"] = {
            "type": board_type, "total": 0, "ranked_count": 0, "unknown_count": 0,
            "top": [], "bottom": [],
        }
        env["status"] = "unavailable"
        env["data"] = None
        return env

    monkeypatch.setattr(market, "get_board_ranking", empty_board)
    daily_review._clear_review_cache()
    out2 = daily_review.generate_daily_review()
    h2 = out2["sector_rotation"]["highlights"]
    assert h2["strongest_industry"] is None
    assert h2["weakest_industry"] is None


# ── 3 广度复用 ──────────────────────────────────────────────────────

def test_breadth_reused_for_capital(monkeypatch):
    counts = _install_all_ok(monkeypatch)
    out = daily_review.generate_daily_review()
    assert counts["breadth"] == 1
    ca = out["capital_activity"]
    assert ca["total_amount"] == pytest.approx(1.2e12)
    assert ca["amount_valid_count"] == 5000
    assert ca["amount_top"][0]["code"] == "600519"
    assert ca["high_turnover"][0]["turnover_pct"] == 20.0
    assert ca["turnover_top"]["status"] == "normal"


# ── 4 核心组件失败 → partial ───────────────────────────────────────

def test_core_component_failure_partial(monkeypatch):
    _install_all_ok(monkeypatch)

    def boom_concept(board_type="industry", top_n=20):
        if board_type == "concept":
            raise RuntimeError("timeout")
        return _board(board_type)

    monkeypatch.setattr(market, "get_board_ranking", boom_concept)
    out = daily_review.generate_daily_review()
    assert out["status"] == "partial"
    assert out["sector_rotation"]["concept"]["status"] == "unavailable"
    assert out["sector_rotation"]["industry"]["status"] == "normal"
    assert any("[概念板块]" in w and "timeout" in w for w in out["warnings"])
    assert out["data_health"]["components"]["concept_boards"] == "unavailable"


# ── 5 可选组件失败仍 normal ─────────────────────────────────────────

def test_optional_failure_keeps_normal(monkeypatch):
    _install_all_ok(monkeypatch)

    def boom_global():
        raise RuntimeError("global down")

    monkeypatch.setattr(market, "get_global_indices", boom_global)
    out = daily_review.generate_daily_review()
    assert out["status"] == "normal"
    assert out["market_environment"]["global_indices"]["status"] == "unavailable"
    assert any("[全球指数]" in w and "global down" in w for w in out["warnings"])


# ── 6 全部核心失败 ──────────────────────────────────────────────────

def test_all_core_unavailable(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("all down")

    monkeypatch.setattr(daily_review.astock, "index_quote", fail)
    monkeypatch.setattr(market, "get_global_indices", fail)
    monkeypatch.setattr(market, "get_market_breadth", fail)
    monkeypatch.setattr(market, "get_short_term_emotion", fail)
    monkeypatch.setattr(market, "get_turnover_top", fail)
    monkeypatch.setattr(market, "get_board_ranking", fail)
    monkeypatch.setattr(market, "get_overview", lambda: (_ for _ in ()).throw(RuntimeError("no")))
    monkeypatch.setattr(market, "_sectors", lambda: (_ for _ in ()).throw(RuntimeError("no")))

    out = daily_review.generate_daily_review()  # 不向外抛
    assert out["status"] == "unavailable"
    assert out["schema_version"] == "daily-review-v0.1"
    assert "market_environment" in out
    assert out["capital_activity"]["amount_top"] == []


# ── 7 情绪为空 ──────────────────────────────────────────────────────

def test_empty_emotion(monkeypatch):
    _install_all_ok(monkeypatch)
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: {})
    out = daily_review.generate_daily_review()
    assert out["short_term_emotion"]["status"] == "unavailable"
    assert out["short_term_emotion"]["data"] is None
    assert out["trade_date"] is None
    assert out["status"] == "partial"


# ── 8 非法交易日期 ──────────────────────────────────────────────────

def test_invalid_trade_date(monkeypatch):
    _install_all_ok(monkeypatch, emotion_date="20260721")
    out = daily_review.generate_daily_review()
    assert out["trade_date"] is None
    assert any("交易日期格式无效" in w for w in out["warnings"])


# ── 9 warning 去重 ──────────────────────────────────────────────────

def test_warning_dedupe(monkeypatch):
    _install_all_ok(monkeypatch)
    same = "源数据未提供明确交易日期和行情时间"

    def boards(board_type="industry", top_n=20):
        env = _board(board_type)
        env["warnings"] = [same]
        return env

    monkeypatch.setattr(market, "get_board_ranking", boards)
    monkeypatch.setattr(
        market, "get_market_breadth",
        lambda: _breadth_env(warnings=[same]),
    )
    out = daily_review.generate_daily_review()
    # 完整文本（含前缀后）去重；同一原文加不同前缀会不同，但相同 full 只一次
    texts = out["warnings"]
    assert len(texts) == len(set(texts))


# ── 10 data_cutoff ──────────────────────────────────────────────────

def test_data_cutoff_none(monkeypatch):
    _install_all_ok(monkeypatch)
    out = daily_review.generate_daily_review()
    assert out["data_cutoff"] is None
    assert any("数据截止时间" in w for w in out["warnings"])


# ── 11 不调用旧总览 ─────────────────────────────────────────────────

def test_does_not_call_old_overview(monkeypatch):
    counts = _install_all_ok(monkeypatch)
    daily_review.generate_daily_review()
    # 若调用 get_overview/_sectors 会抛错导致测试失败
    assert counts["index"] == 1


# ── 12 调用次数 ─────────────────────────────────────────────────────

def test_call_counts_once_each(monkeypatch):
    counts = _install_all_ok(monkeypatch)
    daily_review.generate_daily_review()
    assert counts["index"] == 1
    assert counts["global"] == 1
    assert counts["breadth"] == 1
    assert counts["emotion"] == 1
    assert counts["turnover"] == 1
    assert len(counts["boards"]) == 3
    assert sorted(t for t, _ in counts["boards"]) == ["concept", "industry", "region"]
    assert all(n == 10 for _, n in counts["boards"])


# ── 完整结果缓存 + single-flight ────────────────────────────────────

def test_cache_first_call_runs_aggregation(monkeypatch):
    counts = _install_all_ok(monkeypatch)
    out = daily_review.generate_daily_review()
    assert out["status"] == "normal"
    assert counts["index"] == 1
    assert counts["breadth"] == 1


def test_cache_second_call_skips_components(monkeypatch):
    counts = _install_all_ok(monkeypatch)
    a = daily_review.generate_daily_review()
    b = daily_review.generate_daily_review()
    assert a["status"] == "normal"
    assert b["status"] == "normal"
    assert a["generated_at"] == b["generated_at"]
    assert counts["index"] == 1
    assert counts["global"] == 1
    assert counts["breadth"] == 1
    assert counts["emotion"] == 1
    assert counts["turnover"] == 1
    assert len(counts["boards"]) == 3


def test_cache_returns_deepcopy(monkeypatch):
    _install_all_ok(monkeypatch)
    a = daily_review.generate_daily_review()
    b = daily_review.generate_daily_review()
    assert a is not b
    assert a["data_health"] is not b["data_health"]
    assert a["market_environment"] is not b["market_environment"]


def test_cache_mutation_does_not_pollute(monkeypatch):
    _install_all_ok(monkeypatch)
    a = daily_review.generate_daily_review()
    orig_at = a["generated_at"]
    a["status"] = "hacked"
    a["generated_at"] = "1999-01-01 00:00:00"
    a["warnings"].append("pollute")
    a["market_environment"]["indices"]["status"] = "hacked"
    b = daily_review.generate_daily_review()
    assert b["status"] == "normal"
    assert b["generated_at"] == orig_at
    assert "pollute" not in b["warnings"]
    assert b["market_environment"]["indices"]["status"] == "normal"


def test_cache_ttl_expiry_regenerates(monkeypatch):
    counts = _install_all_ok(monkeypatch)
    monkeypatch.setattr(daily_review, "_REVIEW_TTL", 1)
    t0 = 1000.0
    clock = {"now": t0}

    def fake_time():
        return clock["now"]

    monkeypatch.setattr(daily_review.time, "time", fake_time)
    daily_review.generate_daily_review()
    assert counts["index"] == 1
    clock["now"] = t0 + 0.5
    daily_review.generate_daily_review()
    assert counts["index"] == 1
    clock["now"] = t0 + 1.01
    daily_review.generate_daily_review()
    assert counts["index"] == 2


def test_cache_stores_normal(monkeypatch):
    _install_all_ok(monkeypatch)
    out = daily_review.generate_daily_review()
    assert out["status"] == "normal"
    assert daily_review._REVIEW_CACHE_KEY in daily_review._review_cache
    assert daily_review._review_cache[daily_review._REVIEW_CACHE_KEY][1]["status"] == "normal"


def test_cache_stores_partial(monkeypatch):
    _install_all_ok(monkeypatch)

    def boom_concept(board_type="industry", top_n=20):
        if board_type == "concept":
            raise RuntimeError("timeout")
        return _board(board_type)

    monkeypatch.setattr(market, "get_board_ranking", boom_concept)
    out = daily_review.generate_daily_review()
    assert out["status"] == "partial"
    assert daily_review._REVIEW_CACHE_KEY in daily_review._review_cache
    assert daily_review._review_cache[daily_review._REVIEW_CACHE_KEY][1]["status"] == "partial"
    # 第二次应命中缓存，不再调组件
    counts = {"boards": 0}

    def boards(board_type="industry", top_n=20):
        counts["boards"] += 1
        return _board(board_type)

    monkeypatch.setattr(market, "get_board_ranking", boards)
    out2 = daily_review.generate_daily_review()
    assert out2["status"] == "partial"
    assert counts["boards"] == 0


def test_cache_skips_unavailable(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("all down")

    monkeypatch.setattr(daily_review.astock, "index_quote", fail)
    monkeypatch.setattr(market, "get_global_indices", fail)
    monkeypatch.setattr(market, "get_market_breadth", fail)
    monkeypatch.setattr(market, "get_short_term_emotion", fail)
    monkeypatch.setattr(market, "get_turnover_top", fail)
    monkeypatch.setattr(market, "get_board_ranking", fail)
    monkeypatch.setattr(market, "get_overview", lambda: (_ for _ in ()).throw(RuntimeError("no")))
    monkeypatch.setattr(market, "_sectors", lambda: (_ for _ in ()).throw(RuntimeError("no")))

    out = daily_review.generate_daily_review()
    assert out["status"] == "unavailable"
    assert daily_review._REVIEW_CACHE_KEY not in daily_review._review_cache


def test_cache_skips_on_aggregation_exception(monkeypatch):
    _install_all_ok(monkeypatch)

    def boom():
        raise RuntimeError("aggregate boom")

    monkeypatch.setattr(daily_review, "_build_daily_review", boom)
    with pytest.raises(RuntimeError, match="aggregate boom"):
        daily_review.generate_daily_review()
    assert daily_review._REVIEW_CACHE_KEY not in daily_review._review_cache


def test_cache_retry_after_failure(monkeypatch):
    calls = {"n": 0}

    def flaky_build():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first fail")
        return {
            "schema_version": "daily-review-v0.1",
            "generated_at": "2026-07-21 12:00:00",
            "trade_date": "2026-07-21",
            "data_cutoff": None,
            "status": "normal",
            "warnings": [],
            "data_health": {"components": {}},
            "market_environment": {},
            "sector_rotation": {},
            "short_term_emotion": {},
            "capital_activity": {},
        }

    monkeypatch.setattr(daily_review, "_build_daily_review", flaky_build)
    with pytest.raises(RuntimeError, match="first fail"):
        daily_review.generate_daily_review()
    out = daily_review.generate_daily_review()
    assert out["status"] == "normal"
    assert calls["n"] == 2
    # 第三次命中缓存
    out2 = daily_review.generate_daily_review()
    assert out2["status"] == "normal"
    assert calls["n"] == 2


def test_single_flight_only_one_build(monkeypatch):
    barrier = threading.Barrier(2)
    builds = {"n": 0}
    lock = threading.Lock()

    def slow_build():
        with lock:
            builds["n"] += 1
        time.sleep(0.15)
        return {
            "schema_version": "daily-review-v0.1",
            "generated_at": "2026-07-21 12:00:00",
            "trade_date": "2026-07-21",
            "data_cutoff": None,
            "status": "normal",
            "warnings": [],
            "data_health": {"components": {}},
            "market_environment": {},
            "sector_rotation": {},
            "short_term_emotion": {},
            "capital_activity": {},
        }

    monkeypatch.setattr(daily_review, "_build_daily_review", slow_build)

    results = []
    errors = []

    def worker():
        try:
            barrier.wait(timeout=5)
            results.append(daily_review.generate_daily_review())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not errors
    assert len(results) == 2
    assert builds["n"] == 1
    assert all(r["status"] == "normal" for r in results)


def test_single_flight_failure_releases_lock(monkeypatch):
    calls = {"n": 0}
    barrier = threading.Barrier(2)

    def boom_then_ok():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first concurrent fail")
        return {
            "schema_version": "daily-review-v0.1",
            "generated_at": "2026-07-21 12:00:00",
            "trade_date": "2026-07-21",
            "data_cutoff": None,
            "status": "normal",
            "warnings": [],
            "data_health": {"components": {}},
            "market_environment": {},
            "sector_rotation": {},
            "short_term_emotion": {},
            "capital_activity": {},
        }

    monkeypatch.setattr(daily_review, "_build_daily_review", boom_then_ok)

    outcomes = []

    def worker():
        barrier.wait(timeout=5)
        try:
            outcomes.append(("ok", daily_review.generate_daily_review()))
        except Exception as e:  # noqa: BLE001
            outcomes.append(("err", e))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(outcomes) == 2
    # 首个失败释放锁后，至少一个成功（另一个可能也失败若都在失败窗口内）
    # 再单独调用应能成功且不死锁
    out = daily_review.generate_daily_review()
    assert out["status"] == "normal"
    assert calls["n"] >= 2


def test_portfolio_advice_reuses_daily_review_cache(monkeypatch):
    """portfolio_advice 调 generate_daily_review，应命中完整复盘缓存。"""
    counts = _install_all_ok(monkeypatch)
    review = daily_review.generate_daily_review()
    assert review["status"] == "normal"
    assert counts["index"] == 1

    pf = {
        "holdings": [
            {
                "code": "001896",
                "name": "豫能控股",
                "shares": 1000,
                "cost": 5.0,
                "price": 5.5,
            }
        ],
        "totals": {"market_value": 5500.0, "cost": 5000.0, "pnl": 500.0, "pnl_pct": 10.0},
    }
    monkeypatch.setattr(portfolio_advice_service.portfolio, "get_portfolio", lambda: pf)
    prepared = portfolio_advice_service.prepare_portfolio_advice_messages()
    assert prepared["daily_review"]["generated_at"] == review["generated_at"]
    assert prepared["daily_review"]["status"] == "normal"
    # 未再次拉取任何组件
    assert counts["index"] == 1
    assert counts["breadth"] == 1
    assert counts["emotion"] == 1
