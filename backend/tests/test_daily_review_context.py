"""daily_review_context 纯函数投影器离线测试（不联网、不改输入）。"""
from __future__ import annotations

import copy
import json

import pytest

from daily_review_context import (
    build_daily_review_ai_context,
    render_daily_review_ai_context,
    _FORBIDDEN_KEYS,
)


def _full_review():
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": "normal",
        "warnings": [
            "各数据源尚未提供统一的数据截止时间",
            "各数据源尚未提供统一的数据截止时间",  # 重复
            "",
            "[市场广度] 源数据未提供明确交易日期和行情时间",
        ],
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
        "market_environment": {
            "indices": {
                "status": "normal",
                "source": "tencent_quote",
                "warnings": [],
                "data": [
                    {"name": "上证", "price": 3000, "change_pct": 0.5},
                    {"name": "深证", "price": 10000, "change_pct": -0.2},
                ],
            },
            "global_indices": {
                "status": "normal",
                "source": "eastmoney_global_indices",
                "warnings": [],
                "data": [{"name": "道琼斯", "price": 39000, "change_pct": 0.1}],
            },
            "breadth": {
                "status": "normal",
                "source": "eastmoney_push2",
                "trade_date": None,
                "data_time": None,
                "fetched_at": "2026-07-21 15:00:00",
                "is_stale": False,
                "warnings": ["源数据未提供明确交易日期和行情时间"],
                "data": {
                    "stock_count": 5000,
                    "valid_count": 4900,
                    "up_count": 3000,
                    "down_count": 1800,
                    "flat_count": 100,
                    "up_ratio": 0.6122,
                    "up_3pct_count": 500,
                    "down_3pct_count": 200,
                    "total_amount": 1.2e12,
                    "amount_valid_count": 4900,
                    "amount_top": [{"code": "600519", "amount": 1e10}],
                    "high_turnover": [{"code": "000001", "turnover_pct": 20.0}],
                },
            },
        },
        "short_term_emotion": {
            "status": "normal",
            "source": "eastmoney_limit_pool",
            "warnings": [],
            "data": {
                "date": "2026-07-21",
                "zt_count": 80,
                "dt_count": 10,
                "zb_count": 20,
                "max_boards": 5,
                "lianban_count": 15,
                "seal_rate": 0.8,
                "break_rate": 0.2,
                "promotion_rate": 0.3,
                "yzt_count": 50,
                "ladder": [{"boards": i, "count": i} for i in range(1, 25)],
                "lianban_stocks": [
                    {"code": f"{i:06d}", "name": f"股{i}", "boards": 2}
                    for i in range(20)
                ],
            },
        },
        "sector_rotation": {
            "industry": {
                "status": "normal",
                "source": "eastmoney_push2",
                "warnings": [],
                "data": {
                    "type": "industry",
                    "total": 90,
                    "ranked_count": 90,
                    "unknown_count": 0,
                    "top": [
                        {"code": f"TI{i}", "name": f"强业{i}", "change_pct": 5 - i * 0.1}
                        for i in range(10)
                    ],
                    "bottom": [
                        {"code": f"WI{i}", "name": f"弱业{i}", "change_pct": -5 + i * 0.1}
                        for i in range(10)
                    ],
                },
            },
            "concept": {
                "status": "normal",
                "source": "eastmoney_push2",
                "warnings": [],
                "data": {
                    "type": "concept",
                    "total": 80,
                    "ranked_count": 80,
                    "unknown_count": 0,
                    "top": [{"code": f"TC{i}", "name": f"强概{i}", "change_pct": 4 - i}
                            for i in range(10)],
                    "bottom": [{"code": f"WC{i}", "name": f"弱概{i}", "change_pct": -4 + i}
                               for i in range(10)],
                },
            },
            "region": {
                "status": "normal",
                "source": "eastmoney_push2",
                "warnings": [],
                "data": {
                    "type": "region",
                    "total": 30,
                    "ranked_count": 30,
                    "unknown_count": 0,
                    "top": [{"code": "R1", "name": "粤", "change_pct": 2.0}],
                    "bottom": [{"code": "R2", "name": "甘", "change_pct": -1.0}],
                },
            },
            "highlights": {
                "strongest_industry": {"code": "TI0", "name": "强业0", "change_pct": 5.0},
                "weakest_industry": {"code": "WI0", "name": "弱业0", "change_pct": -5.0},
                "strongest_concept": {"code": "TC0", "name": "强概0", "change_pct": 4.0},
                "weakest_concept": {"code": "WC0", "name": "弱概0", "change_pct": -4.0},
                "strongest_region": {"code": "R1", "name": "粤", "change_pct": 2.0},
                "weakest_region": {"code": "R2", "name": "甘", "change_pct": -1.0},
            },
        },
        "capital_activity": {
            "turnover_top": {"status": "normal", "data": {"stocks": []}},
            "total_amount": 1.2e12,
            "amount_valid_count": 4900,
            "amount_top": [
                {"code": f"{i:06d}", "name": f"成交{i}", "amount": 1e9 - i}
                for i in range(25)
            ],
            "high_turnover": [
                {"code": f"H{i:04d}", "name": f"换手{i}", "turnover_pct": 30 - i}
                for i in range(25)
            ],
        },
    }


def _assert_top_keys(ctx: dict):
    for k in (
        "schema_version", "review_metadata", "data_health",
        "market_environment", "short_term_emotion",
        "sector_rotation", "capital_activity", "unknowns",
    ):
        assert k in ctx


# ── 1 完整投影 ──────────────────────────────────────────────────────

def test_full_projection():
    review = _full_review()
    ctx = build_daily_review_ai_context(review)
    _assert_top_keys(ctx)
    assert ctx["schema_version"] == "daily-review-ai-context-v0.1"
    assert ctx["review_metadata"]["trade_date"] == "2026-07-21"
    assert ctx["review_metadata"]["status"] == "normal"
    assert ctx["review_metadata"]["data_cutoff"] is None
    b = ctx["market_environment"]["breadth"]
    assert b is not None
    assert b["up_count"] == 3000
    assert b["up_ratio"] == pytest.approx(0.6122)
    assert "amount_top" not in b
    emo = ctx["short_term_emotion"]
    assert emo["zt_count"] == 80
    assert emo["seal_rate"] == 0.8
    assert len(ctx["market_environment"]["indices"]) == 2
    assert ctx["capital_activity"]["total_amount"] == 1.2e12
    assert "turnover_top" not in ctx["capital_activity"]


# ── 2 board_limit ───────────────────────────────────────────────────

def test_board_limit():
    review = _full_review()
    ctx = build_daily_review_ai_context(review, board_limit=3)
    ind = ctx["sector_rotation"]["industry"]
    assert len(ind["strongest"]) == 3
    assert len(ind["weakest"]) == 3
    assert ind["strongest"][0]["code"] == "TI0"
    assert ind["weakest"][0]["code"] == "WI0"
    con = ctx["sector_rotation"]["concept"]
    assert len(con["strongest"]) == 3


# ── 3 stock_limit ───────────────────────────────────────────────────

def test_stock_limit():
    review = _full_review()
    ctx = build_daily_review_ai_context(review, stock_limit=7)
    assert len(ctx["capital_activity"]["amount_top"]) == 7
    assert len(ctx["capital_activity"]["high_turnover"]) == 7
    assert len(ctx["short_term_emotion"]["lianban_stocks"]) == 7
    assert len(ctx["short_term_emotion"]["ladder"]) == 20  # ladder 固定最多 20


# ── 4 不重新排序 ────────────────────────────────────────────────────

def test_no_resort():
    review = _full_review()
    # 故意乱序 top
    tops = [
        {"code": "B", "name": "乙", "change_pct": 1.0},
        {"code": "A", "name": "甲", "change_pct": 9.0},
        {"code": "C", "name": "丙", "change_pct": -1.0},
    ]
    review["sector_rotation"]["industry"]["data"]["top"] = tops
    review["capital_activity"]["amount_top"] = [
        {"code": "Z", "amount": 1},
        {"code": "Y", "amount": 9},
    ]
    ctx = build_daily_review_ai_context(review, board_limit=5, stock_limit=5)
    assert [x["code"] for x in ctx["sector_rotation"]["industry"]["strongest"]] == ["B", "A", "C"]
    assert [x["code"] for x in ctx["capital_activity"]["amount_top"]] == ["Z", "Y"]


# ── 5 空 review ─────────────────────────────────────────────────────

def test_empty_review():
    ctx = build_daily_review_ai_context({})
    _assert_top_keys(ctx)
    assert ctx["market_environment"]["indices"] == []
    assert ctx["market_environment"]["global_indices"] == []
    assert ctx["market_environment"]["breadth"] is None
    assert ctx["short_term_emotion"] is None
    assert ctx["sector_rotation"]["industry"]["strongest"] == []
    assert any("缺少明确交易日期" in u for u in ctx["unknowns"])
    assert any("市场广度不可用" in u for u in ctx["unknowns"])


# ── 6 unavailable / partial 组件 ────────────────────────────────────

def test_unavailable_and_partial_components():
    review = _full_review()
    review["status"] = "partial"
    review["data_health"]["components"]["breadth"] = "unavailable"
    review["data_health"]["components"]["concept_boards"] = "partial"
    review["market_environment"]["breadth"] = {
        "status": "unavailable", "source": "eastmoney_push2",
        "warnings": ["timeout"], "data": None,
    }
    review["sector_rotation"]["concept"]["status"] = "partial"
    ctx = build_daily_review_ai_context(review)
    assert "breadth" in ctx["data_health"]["unavailable_components"]
    assert "concept_boards" in ctx["data_health"]["partial_components"]
    assert ctx["market_environment"]["breadth"] is None
    assert any("组件不可用：breadth" in u for u in ctx["unknowns"])
    assert any("组件数据部分缺失：concept_boards" in u for u in ctx["unknowns"])
    assert any("每日复盘数据部分缺失" in u for u in ctx["unknowns"])


# ── 7 warning 去重 ──────────────────────────────────────────────────

def test_warning_dedupe_and_limit():
    review = _full_review()
    review["warnings"] = ["a", "a", "", "b"] + [f"w{i}" for i in range(30)]
    ctx = build_daily_review_ai_context(review)
    warns = ctx["data_health"]["warnings"]
    assert warns[0] == "a"
    assert warns.count("a") == 1
    assert "" not in warns
    assert len(warns) <= 20


# ── 8 highlights 键稳定 ─────────────────────────────────────────────

def test_highlights_keys_stable():
    review = _full_review()
    review["sector_rotation"]["highlights"] = {"strongest_industry": {"code": "X"}}
    ctx = build_daily_review_ai_context(review)
    h = ctx["sector_rotation"]["highlights"]
    assert set(h.keys()) == {
        "strongest_industry", "weakest_industry",
        "strongest_concept", "weakest_concept",
        "strongest_region", "weakest_region",
    }
    assert h["strongest_industry"]["code"] == "X"
    assert h["weakest_industry"] is None


# ── 9 None 与 0 ─────────────────────────────────────────────────────

def test_none_and_zero_preserved():
    review = _full_review()
    review["market_environment"]["breadth"]["data"]["flat_count"] = 0
    review["market_environment"]["breadth"]["data"]["up_ratio"] = None
    review["capital_activity"]["total_amount"] = 0
    review["capital_activity"]["amount_valid_count"] = None
    ctx = build_daily_review_ai_context(review)
    assert ctx["market_environment"]["breadth"]["flat_count"] == 0
    assert ctx["market_environment"]["breadth"]["up_ratio"] is None
    assert ctx["capital_activity"]["total_amount"] == 0
    assert ctx["capital_activity"]["amount_valid_count"] is None


# ── 10 输入不被修改 ─────────────────────────────────────────────────

def test_input_immutable():
    review = _full_review()
    original = copy.deepcopy(review)
    build_daily_review_ai_context(review, board_limit=2, stock_limit=3)
    assert review == original


# ── 11 非法参数 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bl", [0, 21])
def test_invalid_board_limit(bl):
    with pytest.raises(ValueError, match="board_limit"):
        build_daily_review_ai_context({}, board_limit=bl)


@pytest.mark.parametrize("sl", [0, 31])
def test_invalid_stock_limit(sl):
    with pytest.raises(ValueError, match="stock_limit"):
        build_daily_review_ai_context({}, stock_limit=sl)


# ── 12 非字典输入 ───────────────────────────────────────────────────

def test_non_dict_review():
    with pytest.raises(TypeError, match="字典"):
        build_daily_review_ai_context([])  # type: ignore[arg-type]


# ── 13 文本渲染 ─────────────────────────────────────────────────────

def test_render_json_string():
    review = _full_review()
    s = render_daily_review_ai_context(review, board_limit=2, stock_limit=3)
    assert isinstance(s, str)
    assert not s.startswith("```")
    assert "\\u" not in s or "上证" in s  # 中文不转义
    assert "上证" in s
    parsed = json.loads(s)
    built = build_daily_review_ai_context(review, board_limit=2, stock_limit=3)
    assert parsed == built


# ── 14 确定性 ───────────────────────────────────────────────────────

def test_render_deterministic():
    review = _full_review()
    a = render_daily_review_ai_context(review)
    b = render_daily_review_ai_context(review)
    assert a == b


# ── 15 禁止结论字段 ─────────────────────────────────────────────────

def test_no_conclusion_keys():
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in _FORBIDDEN_KEYS, f"forbidden key at {path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    ctx = build_daily_review_ai_context(_full_review())
    walk(ctx)


def test_unavailable_board_not_fake_normal():
    review = _full_review()
    review["sector_rotation"]["industry"] = {
        "status": "unavailable",
        "source": "eastmoney_push2",
        "warnings": ["fail"],
        "data": None,
    }
    ctx = build_daily_review_ai_context(review)
    ind = ctx["sector_rotation"]["industry"]
    assert ind["status"] == "unavailable"
    assert ind["strongest"] == []
    assert ind["weakest"] == []
    assert any("行业板块排名不可用" in u for u in ctx["unknowns"])
