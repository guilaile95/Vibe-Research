"""今日实时行动只读聚合单测（mock portfolio / plan / advice / watchlist）。"""

from __future__ import annotations

import pytest

import decision_cockpit_today as today
from decision_cockpit_service import DecisionCockpitError


TRADE_DATE = "2026-07-24"


def _patch_common(monkeypatch, *, portfolio=None, plan=None, advice=None, watchlist=None, quotes=None):
    monkeypatch.setattr(
        today.pf,
        "get_portfolio",
        lambda: portfolio
        if portfolio is not None
        else {
            "holdings": [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "shares": 100,
                    "price": 1800.0,
                    "pnl_pct": 12.5,
                },
                {
                    "code": "000001",
                    "name": "平安银行",
                    "shares": 1000,
                    "price": 10.0,
                    "pnl_pct": -6.0,
                },
            ]
        },
    )
    monkeypatch.setattr(today, "get_current_plan", lambda _td: plan)
    monkeypatch.setattr(
        today.ai_result_service,
        "get_ai_result",
        lambda *a, **k: advice,
    )
    monkeypatch.setattr(
        today.watchlist_store,
        "load_watchlist",
        lambda: watchlist if watchlist is not None else ["300750", "600519", "000858"],
    )

    qmap = quotes if quotes is not None else {
        "600519": {"name": "贵州茅台", "price": 1800.0, "change_pct": 1.2},
        "000001": {"name": "平安银行", "price": 10.0, "change_pct": -5.5},
        "300750": {"name": "宁德时代", "price": 200.0, "change_pct": 6.2},
        "000858": {"name": "五粮液", "price": 140.0, "change_pct": -2.1},
    }
    monkeypatch.setattr(today.astock, "tencent_quote", lambda codes: {c: qmap[c] for c in codes if c in qmap})
    monkeypatch.setattr(today, "_now_beijing", lambda: "2026-07-24 14:30:00")
    # 放宽未来日校验：固定「今天」为 2026-07-25
    monkeypatch.setattr(
        "decision_cockpit_service._beijing_today",
        lambda: __import__("datetime").date(2026, 7, 25),
    )


class TestGetTodayActions:
    def test_full_aggregation_with_plan_and_advice(self, monkeypatch):
        plan = {
            "id": 9,
            "status": "frozen",
            "version": 3,
            "generated_at": "2026-07-24 18:00:00",
            "is_current": 1,
            "signals": [
                {
                    "candidate_code": "600519",
                    "dimension": "value",
                    "label": "pe",
                    "assessment": "strong",
                },
                {
                    "candidate_code": "600519",
                    "dimension": "trend",
                    "label": "ma",
                    "assessment": "medium",
                },
                {
                    "candidate_code": "000001",
                    "dimension": "short",
                    "label": "emotion",
                    "assessment": "weak",
                },
            ],
        }
        advice = {
            "result_type": "portfolio_advice",
            "trade_date": TRADE_DATE,
            "payload": {
                "holdings": [
                    {
                        "code": "600519",
                        "action": "hold",
                        "execution_quantity": None,
                    },
                    {
                        "code": "000001",
                        "action": "reduce",
                        "execution_quantity": 200,
                    },
                ]
            },
        }
        _patch_common(monkeypatch, plan=plan, advice=advice)

        out = today.get_today_actions(TRADE_DATE)

        assert out["trade_date"] == TRADE_DATE
        assert out["as_of"] == "2026-07-24 14:30:00"
        assert out["plan"]["id"] == 9
        assert out["plan"]["status"] == "frozen"
        assert out["plan_note"] is None
        assert len(out["holdings"]) == 2

        by_code = {h["code"]: h for h in out["holdings"]}
        h519 = by_code["600519"]
        assert h519["advice_action"] == "hold"
        assert h519["advice_qty"] is None
        assert "浮盈较大" in h519["flags"]
        assert h519["plan_signals_summary"] == "价值强 / 趋势中"
        assert h519["change_pct"] == 1.2

        h001 = by_code["000001"]
        assert h001["advice_action"] == "reduce"
        assert h001["advice_qty"] == 200
        assert "浮亏加深" in h001["flags"]
        assert "当日大跌" in h001["flags"]
        assert h001["plan_signals_summary"] == "短线弱"

        # 自选按 |change_pct| 排序：300750(6.2) > 000001 不在自选，600519(1.2), 000858(2.1)
        movers = out["watchlist_movers"]
        assert len(movers) <= 8
        assert movers[0]["code"] == "300750"
        assert movers[0]["flag"] == "大涨关注"
        assert abs(movers[0]["change_pct"]) >= abs(movers[1]["change_pct"])

    def test_no_plan_no_advice_flags_only(self, monkeypatch):
        _patch_common(
            monkeypatch,
            plan=None,
            advice=None,
            portfolio={
                "holdings": [
                    {
                        "code": "600000",
                        "name": "浦发银行",
                        "shares": 500,
                        "price": 8.5,
                        "pnl_pct": -1.0,  # 接近成本
                    }
                ]
            },
            quotes={
                "600000": {"name": "浦发银行", "price": 8.5, "change_pct": 0.3},
            },
            watchlist=[],
        )

        out = today.get_today_actions(TRADE_DATE)

        assert out["plan"] is None
        assert out["plan_note"] and "尚无冻结" in out["plan_note"]
        assert len(out["holdings"]) == 1
        h = out["holdings"][0]
        assert h["advice_action"] is None
        assert h["advice_qty"] is None
        assert h["plan_signals_summary"] is None
        assert "接近成本" in h["flags"]
        assert out["watchlist_movers"] == []

    def test_invalid_trade_date_raises(self, monkeypatch):
        monkeypatch.setattr(
            "decision_cockpit_service._beijing_today",
            lambda: __import__("datetime").date(2026, 7, 25),
        )
        with pytest.raises(DecisionCockpitError):
            today.get_today_actions("not-a-date")
        with pytest.raises(DecisionCockpitError):
            today.get_today_actions("2026-13-40")
        with pytest.raises(DecisionCockpitError):
            today.get_today_actions("2026-07-30")  # 未来

    def test_advice_trade_date_mismatch_ignored(self, monkeypatch):
        """建议 trade_date 不匹配时不带 action/qty。"""
        _patch_common(
            monkeypatch,
            plan=None,
            advice={
                "result_type": "portfolio_advice",
                "trade_date": "2026-07-01",  # 不匹配
                "payload": {
                    "holdings": [
                        {"code": "600519", "action": "add", "execution_quantity": 10}
                    ]
                },
            },
        )
        out = today.get_today_actions(TRADE_DATE)
        h519 = next(h for h in out["holdings"] if h["code"] == "600519")
        assert h519["advice_action"] is None
        assert h519["advice_qty"] is None

    def test_watchlist_top8_by_abs_change(self, monkeypatch):
        codes = [f"{i:06d}" for i in range(1, 12)]
        quotes = {
            c: {"name": c, "price": 10.0, "change_pct": float(i)}  # 1..11
            for i, c in enumerate(codes, start=1)
        }
        _patch_common(
            monkeypatch,
            portfolio={"holdings": []},
            plan=None,
            advice=None,
            watchlist=codes,
            quotes=quotes,
        )
        out = today.get_today_actions(TRADE_DATE)
        movers = out["watchlist_movers"]
        assert len(movers) == 8
        # 最大 |change| 优先：11,10,9,...
        assert movers[0]["change_pct"] == 11.0
        assert movers[1]["change_pct"] == 10.0


def test_compress_plan_signals_rank_strong_medium_weak_unknown():
    """同维度：strong > medium > weak > unknown；medium 高于 weak。"""
    code = "600519"
    # medium 后出现 weak：应保留 medium
    mid_over_weak = today._compress_plan_signals(
        [
            {"candidate_code": code, "dimension": "trend", "assessment": "medium"},
            {"candidate_code": code, "dimension": "trend", "assessment": "weak"},
        ],
        code,
    )
    assert mid_over_weak == "趋势中"

    # weak 后出现 medium：仍保留 medium
    weak_then_mid = today._compress_plan_signals(
        [
            {"candidate_code": code, "dimension": "value", "assessment": "weak"},
            {"candidate_code": code, "dimension": "value", "assessment": "medium"},
        ],
        code,
    )
    assert weak_then_mid == "价值中"

    # strong 压过 medium/weak/unknown
    strong_wins = today._compress_plan_signals(
        [
            {"candidate_code": code, "dimension": "short", "assessment": "unknown"},
            {"candidate_code": code, "dimension": "short", "assessment": "weak"},
            {"candidate_code": code, "dimension": "short", "assessment": "medium"},
            {"candidate_code": code, "dimension": "short", "assessment": "strong"},
        ],
        code,
    )
    assert strong_wins == "短线强"

    # 多维压缩顺序固定 value → trend → short
    multi = today._compress_plan_signals(
        [
            {"candidate_code": code, "dimension": "short", "assessment": "weak"},
            {"candidate_code": code, "dimension": "value", "assessment": "strong"},
            {"candidate_code": code, "dimension": "trend", "assessment": "medium"},
            {"candidate_code": code, "dimension": "value", "assessment": "weak"},
        ],
        code,
    )
    assert multi == "价值强 / 趋势中 / 短线弱"
