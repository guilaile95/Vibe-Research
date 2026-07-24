"""决策驱动舱离线测试（watchlist_store / decision_cockpit_store / decision_cockpit_signals）。

隔离：VR_DATA_DIR / VIBE_RESEARCH_REVIEW_DB → tmp_path；不联网、不写仓库真实数据。
"""
from __future__ import annotations

import pytest

import watchlist_store
import decision_cockpit_store as store
import decision_cockpit_signals as signals


# ---------------------------------------------------------------------------
# watchlist_store
# ---------------------------------------------------------------------------


class TestWatchlistStore:
    def test_initial_not_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        assert watchlist_store.get_watchlist_status()["status"] == "not_configured"
        assert watchlist_store.load_watchlist() == []

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        r = watchlist_store.save_watchlist(["600519", "000001", "600519"])  # 去重
        assert r["codes"] == ["600519", "000001"]
        st = watchlist_store.get_watchlist_status()
        assert st["status"] == "valid"
        assert st["data"]["codes"] == ["600519", "000001"]
        assert st["etag"] == r["etag"]

    def test_invalid_codes_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        with pytest.raises(ValueError):
            watchlist_store.save_watchlist(["abc", "123456"])
        with pytest.raises(ValueError):
            watchlist_store.save_watchlist(["1234567"])

    def test_over_50_raises_not_silent_truncate(self, tmp_path, monkeypatch):
        """P8：>50 明确报错，不静默截断。"""
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        codes = [f"{i:06d}" for i in range(1, 70)]
        with pytest.raises(watchlist_store.WatchlistLimitExceededError) as ei:
            watchlist_store.save_watchlist(codes)
        assert ei.value.count == 69
        assert ei.value.limit == 50

    def test_exactly_50_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        codes = [f"{i:06d}" for i in range(1, 51)]
        r = watchlist_store.save_watchlist(codes)
        assert len(r["codes"]) == 50

    def test_merge_preserves_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        watchlist_store.save_watchlist(["600519"])
        r = watchlist_store.merge_watchlist(["600519", "300750", "000001"])
        assert r["codes"] == ["600519", "300750", "000001"]
        assert "300750" in r["added"]

    def test_merge_over_limit_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        watchlist_store.save_watchlist([f"{i:06d}" for i in range(1, 50)])
        with pytest.raises(watchlist_store.WatchlistLimitExceededError):
            watchlist_store.merge_watchlist([f"{i:06d}" for i in range(50, 60)])

    def test_etag_conflict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        watchlist_store.save_watchlist(["600519"])
        with pytest.raises(watchlist_store.WatchlistVersionConflictError):
            watchlist_store.save_watchlist(["000001"], expected_etag="staleetag")

    def test_corrupted_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist_store, "_CACHE_DIR", str(tmp_path))
        p = tmp_path / "watchlist.json"
        p.write_text("{not json", encoding="utf-8")
        assert watchlist_store.get_watchlist_status()["status"] == "corrupted"
        assert watchlist_store.load_watchlist() == []


# ---------------------------------------------------------------------------
# decision_cockpit_store
# ---------------------------------------------------------------------------


class TestDecisionCockpitStore:
    @pytest.fixture(autouse=True)
    def _db(self, tmp_path, monkeypatch):
        db = tmp_path / "daily_reviews.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(db))

    def _db_path(self, tmp_path):
        return str(tmp_path / "daily_reviews.sqlite3")

    def test_evidence_upsert_idempotent(self, tmp_path):
        db = self._db_path(tmp_path)
        r1 = store.upsert_evidence(db, "kline/600519", {"n": 10})
        assert r1["created"] is True
        r2 = store.upsert_evidence(db, "kline/600519", {"n": 20})
        assert r2["created"] is False
        assert r2["id"] == r1["id"]

    def test_signal_upsert(self, tmp_path):
        db = self._db_path(tmp_path)
        store.upsert_signal(
            db, plan_id="p1", candidate_code="600519", dimension="value",
            label="pe_percentile", assessment="strong", confidence=0.9,
        )
        store.upsert_signal(
            db, plan_id="p1", candidate_code="600519", dimension="value",
            label="pe_percentile", assessment="weak", confidence=0.4,
        )
        sigs = store.get_signals_for_plan(db, "p1")
        assert len(sigs) == 1
        assert sigs[0]["assessment"] == "weak"
        assert sigs[0]["confidence"] == 0.4

    def test_invalid_assessment_rejected(self, tmp_path):
        db = self._db_path(tmp_path)
        with pytest.raises(ValueError):
            store.upsert_signal(
                db, plan_id="p1", candidate_code="600519", dimension="value",
                label="x", assessment="excellent",
            )

    def test_create_plan_is_draft_not_current(self, tmp_path):
        """P1：draft 永不是 current；同日可多 draft。"""
        db = self._db_path(tmp_path)
        p1 = store.create_plan(db, trade_date="2026-07-24", payload={"v": 1})
        assert p1["is_current"] == 0 and p1["status"] == "draft"
        p2 = store.create_plan(db, trade_date="2026-07-24", payload={"v": 2})
        assert p2["is_current"] == 0 and p2["status"] == "draft"
        assert p2["version"] == p1["version"] + 1
        # 无 current
        assert store.get_current_plan(db, "2026-07-24") is None
        # 旧 draft 仍是 draft，未被 supersede
        old = store.get_plan(db, p1["id"])
        assert old["status"] == "draft" and old["is_current"] == 0

    def test_freeze_becomes_current_and_supersedes_old_frozen(self, tmp_path):
        """P1：freeze draft → current frozen；再 freeze 另一 draft 时 supersede 旧 frozen。"""
        db = self._db_path(tmp_path)
        d1 = store.create_plan(db, trade_date="2026-07-24", payload={"v": 1})
        d2 = store.create_plan(db, trade_date="2026-07-24", payload={"v": 2})
        fr1 = store.freeze_plan(db, d1["id"], expected_version=d1["version"])
        assert fr1["status"] == "frozen" and fr1["is_current"] == 1
        cur = store.get_current_plan(db, "2026-07-24")
        assert cur["id"] == d1["id"]

        # 生成更多 draft 不抢 current
        d3 = store.create_plan(db, trade_date="2026-07-24", payload={"v": 3})
        assert d3["is_current"] == 0
        cur2 = store.get_current_plan(db, "2026-07-24")
        assert cur2["id"] == d1["id"] and cur2["status"] == "frozen"

        # freeze 另一 draft → 旧 frozen superseded
        fr2 = store.freeze_plan(db, d2["id"], expected_version=d2["version"])
        assert fr2["status"] == "frozen" and fr2["is_current"] == 1
        old = store.get_plan(db, d1["id"])
        assert old["is_current"] == 0 and old["status"] == "superseded"
        # d3 仍是 draft
        assert store.get_plan(db, d3["id"])["status"] == "draft"

    def test_freeze_then_no_refreeze(self, tmp_path):
        db = self._db_path(tmp_path)
        p = store.create_plan(db, trade_date="2026-07-24", payload={"v": 1})
        fr = store.freeze_plan(db, p["id"], expected_version=p["version"])
        assert fr["status"] == "frozen"
        with pytest.raises(store.TomorrowPlanConflictError):
            store.freeze_plan(db, p["id"], expected_version=p["version"])

    def test_freeze_version_conflict(self, tmp_path):
        db = self._db_path(tmp_path)
        p = store.create_plan(db, trade_date="2026-07-24", payload={"v": 1})
        with pytest.raises(store.TomorrowPlanConflictError):
            store.freeze_plan(db, p["id"], expected_version=p["version"] + 99)

    def test_readonly_missing_db_returns_empty(self, tmp_path):
        db = str(tmp_path / "missing" / "daily_reviews.sqlite3")
        assert store.get_plan(db, 1) is None
        assert store.get_current_plan(db, "2026-07-24") is None
        assert store.list_plans(db) == []
        assert store.get_signals_for_plan(db, "p1") == []

    def test_list_plans_metadata_no_payload(self, tmp_path):
        db = self._db_path(tmp_path)
        p = store.create_plan(db, trade_date="2026-07-24", payload={"v": 1})
        metas = store.list_plans(db, "2026-07-24")
        assert len(metas) == 1
        assert metas[0]["id"] == p["id"]
        assert "payload" not in metas[0]

    def test_at_most_one_current_after_freeze(self, tmp_path):
        db = self._db_path(tmp_path)
        a = store.create_plan(db, trade_date="2026-07-24", payload={"v": 1})
        b = store.create_plan(db, trade_date="2026-07-24", payload={"v": 2})
        store.freeze_plan(db, a["id"], expected_version=a["version"])
        store.freeze_plan(db, b["id"], expected_version=b["version"])
        import sqlite3
        conn = sqlite3.connect(db)
        cur = conn.execute(
            "SELECT COUNT(*) FROM tomorrow_plans WHERE trade_date='2026-07-24' AND is_current=1"
        ).fetchone()[0]
        conn.close()
        assert cur == 1


# ---------------------------------------------------------------------------
# decision_cockpit_signals (纯阈值规则)
# ---------------------------------------------------------------------------


class TestDecisionCockpitSignals:
    def test_value_pe_pb_percentile(self):
        val = {
            "metrics": {
                "pe_ttm": {"percentile": 15, "current": 12},
                "pb": {"percentile": 85, "current": 3},
            }
        }
        fin = {
            "revenue_yoy": 12, "net_profit_yoy": -15, "roe": 16,
            "gross_margin": 40, "op_cf_ps": 1.2, "period": "2025Q4",
        }
        sigs = signals.evaluate_value("600519", val, fin, None)
        by_label = {s["label"]: s for s in sigs}
        assert by_label["pe_ttm_percentile"]["assessment"] == "strong"
        assert by_label["pb_percentile"]["assessment"] == "weak"
        assert by_label["revenue_yoy"]["assessment"] == "strong"
        assert by_label["net_profit_yoy"]["assessment"] == "weak"
        assert by_label["roe"]["assessment"] == "strong"
        assert by_label["gross_margin"].get("context", {}).get("fact_only") is True
        # 单期证据标记
        assert by_label["revenue_yoy"]["context"]["evidence_kind"] == "single_period"
        # 无 full_valuation → peg unknown，不得用 np_yoy 伪造
        assert by_label["peg"]["assessment"] == "unknown"
        assert by_label["peg"]["context"].get("source") == "full_valuation"

    def test_value_full_valuation_peg(self):
        """P5：PEG/CAGR 来自 full_valuation，不用单期 YoY。"""
        fv = {
            "eps_26e": 5.0, "eps_27e": 6.0, "pe_26e": 20.0,
            "cagr_pct": 20.0, "peg": 1.0, "pe_ttm": 18.0, "analyst_count": 10,
        }
        sigs = {s["label"]: s for s in signals.evaluate_value("600519", {}, {}, fv)}
        assert sigs["peg"]["assessment"] == "medium"  # peg == 1.0 → not <1 strong, not >2 weak
        assert sigs["peg"]["context"]["cagr_pct"] == 20.0
        assert sigs["cagr_pct"]["assessment"] == "strong"
        assert sigs["pe_26e"]["assessment"] == "medium"
        assert "cagr_proxy" not in (sigs["peg"].get("context") or {})

    def test_value_nan_yoy(self):
        sigs = signals.evaluate_value(
            "600519", {},
            {"revenue_yoy": None, "net_profit_yoy": None, "roe": None},
        )
        for s in sigs:
            if s["label"] in ("revenue_yoy", "net_profit_yoy", "roe"):
                assert s["assessment"] == "unknown"

    def test_value_strong_medium_weak_boundary(self):
        def mk(pct):
            return {"metrics": {"pe_ttm": {"percentile": pct, "current": 10}}}
        assert signals.evaluate_value("600519", mk(20), {})[0]["assessment"] == "strong"
        assert signals.evaluate_value("600519", mk(50), {})[0]["assessment"] == "medium"
        assert signals.evaluate_value("600519", mk(80), {})[0]["assessment"] == "weak"

    def test_trend_uptrend_strong(self):
        bars = []
        p = 100.0
        for i in range(80):
            p *= 1.005
            bars.append({
                "open": p * 0.99, "close": p, "high": p * 1.01,
                "low": p * 0.98, "volume": 1000000,
            })
        sigs = {s["label"]: s for s in signals.evaluate_trend("600519", bars)}
        assert sigs["ma_alignment"]["assessment"] == "strong"
        assert sigs["ma20_direction"]["value"] == "rising"
        assert sigs["ma20_direction"]["context"]["method"] == "ma20_vs_ma20_n_sessions_ago"
        assert "price_adjustment" in sigs["ma_alignment"]["context"]
        assert sigs["ma_alignment"]["context"]["price_adjustment"] == "none"

    def test_trend_insufficient_data(self):
        sigs = signals.evaluate_trend("600519", [{"close": 100}] * 10)
        assert sigs[0]["label"] == "ma_alignment"
        assert sigs[0]["assessment"] == "unknown"

    def test_trend_negative_gap_not_strong(self):
        """P6：负向跳空不得 strong；不复权断点 → ma_alignment unknown。"""
        bars = []
        p = 100.0
        for i in range(80):
            p *= 1.002
            bars.append({
                "open": p, "close": p, "high": p * 1.01,
                "low": p * 0.99, "volume": 1000,
            })
        # 人为制造 -25% 跳空
        bars[-1] = {
            "open": bars[-2]["close"] * 0.70,  # -30%
            "close": bars[-2]["close"] * 0.72,
            "high": bars[-2]["close"] * 0.75,
            "low": bars[-2]["close"] * 0.68,
            "volume": 1000,
        }
        sigs = {s["label"]: s for s in signals.evaluate_trend("600519", bars)}
        assert sigs["ma_alignment"]["assessment"] == "unknown"
        assert sigs["gap"]["assessment"] != "strong"
        assert sigs["gap"]["value"]["jump_pct"] < 0

    def test_candidate_pool_protected_sources(self):
        pool = signals.build_candidate_pool(
            [{"code": "600519", "name": "A"}],
            ["000001"],
            ["002463"],
            [{"code": "000002"}],
            [{"code": "000003"}],
            [{"code": "000004"}],
            max_candidates=4,
        )
        codes = [c["code"] for c in pool]
        assert "600519" in codes and "000001" in codes and "002463" in codes
        assert len(pool) <= 4

    def test_candidate_pool_dedup(self):
        pool = signals.build_candidate_pool(
            [{"code": "600519"}],
            ["600519"],
            [],
            [{"code": "600519"}],
            [], [],
        )
        codes = [c["code"] for c in pool]
        assert codes.count("600519") == 1

    def test_cash_exec_from_intended_qty(self):
        """P7：按建议原始数量 + 现金；完整可执行 is_executable=True。"""
        r = signals.compute_cash_exec(500, 100.0, 50000)
        assert r["required_cash"] == 50000.0
        assert r["max_executable_shares"] == 500
        assert r["funding_gap"] == 0.0
        assert r["is_executable"] is True
        assert r["shares"] == 500

        # 现金不足：部分可执行
        r2 = signals.compute_cash_exec(1000, 100.0, 30000)
        assert r2["required_cash"] == 100000.0
        assert r2["max_executable_shares"] == 300
        assert r2["funding_gap"] == 70000.0
        assert r2["is_executable"] is False
        assert r2["shares"] == 300
        assert r2["reason"] == "partial"

        # 现金未配置
        r3 = signals.compute_cash_exec(1000, 100.0, None)
        assert r3["is_executable"] is False
        assert r3["reason"] == "cash_unconfigured"
        assert r3["funding_gap"] == 100000.0

        # 非法输入
        r4 = signals.compute_cash_exec(None, 100.0, 50000)
        assert r4["is_executable"] is False
        assert r4["reason"] == "invalid_inputs"

        # 100 股一手向下取整
        r5 = signals.compute_cash_exec(250, 10.0, 10000)
        assert r5["shares"] == 200  # 250 → 200 lots floor
        assert r5["required_cash"] == 2000.0

    def test_market_short_envelope(self):
        m = signals.evaluate_market_short({"status": "normal", "data": {}}, {"zt_count": 5})
        assert m["status"] == "normal"
        m2 = signals.evaluate_market_short(None, None)
        assert m2["status"] == "unavailable" and m2["data"] is None

    def test_candidate_short_dimensions(self):
        """P4：候选级 short 含连板/成交额/高换手/板块/市场，不足 → unknown。"""
        mkt = {"status": "normal"}
        sigs = signals.evaluate_candidate_short(
            "600519",
            market_short=mkt,
            lianban_codes={"600519"},
            turnover_top_codes={"000001"},
            high_turnover_codes=set(),
            sector_rank=5,
            lianban_meta={"boards": 3},
        )
        by = {s["label"]: s for s in sigs}
        assert by["lianban"]["assessment"] == "strong"
        assert by["turnover_top"]["assessment"] == "medium"  # not in list
        assert by["high_turnover"]["assessment"] == "unknown"  # empty list → unavailable
        assert by["sector_strength"]["assessment"] == "strong"
        assert by["market_environment"]["assessment"] == "medium"

        # 全无数据
        sigs2 = signals.evaluate_candidate_short("600519", market_short=None)
        labels = {s["label"] for s in sigs2}
        assert "lianban" in labels and "sector_strength" in labels
        assert all(
            s["assessment"] == "unknown"
            for s in sigs2 if s["label"] != "market_environment"
        )
