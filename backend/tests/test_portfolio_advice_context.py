"""portfolio_advice_context 纯函数离线测试（不联网、不改输入、不写 portfolio.json）。"""
from __future__ import annotations

import copy
import json

import pytest

from portfolio_advice_context import (
    SCHEMA_VERSION,
    build_portfolio_advice_context,
    render_portfolio_advice_context,
)


def _minimal_review(**overrides):
    base = {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": "normal",
        "warnings": ["各数据源尚未提供统一的数据截止时间"],
        "data_health": {
            "components": {
                "indices": "normal",
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
                "data": [{"name": "上证", "price": 3000, "change_pct": 0.5}],
            },
            "global_indices": {"status": "normal", "data": []},
            "breadth": {
                "status": "normal",
                "source": "eastmoney_push2",
                "warnings": [],
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
                "ladder": [],
                "lianban_stocks": [],
            },
        },
        "sector_rotation": {
            "industry": {
                "status": "normal",
                "data": {
                    "top": [{"code": "BK01", "name": "电子", "change_pct": 2.0}],
                    "bottom": [{"code": "BK02", "name": "地产", "change_pct": -1.0}],
                },
            },
            "concept": {
                "status": "normal",
                "data": {"top": [], "bottom": []},
            },
            "region": {
                "status": "normal",
                "data": {"top": [], "bottom": []},
            },
            "highlights": {},
        },
        "capital_activity": {
            "total_amount": 1.2e12,
            "amount_valid_count": 4900,
            "amount_top": [],
            "high_turnover": [],
        },
    }
    base.update(overrides)
    return base


def _holding(code, name, price, shares, cost, **extra):
    mv = round(price * shares, 2)
    cv = cost * shares
    pnl = round(mv - cv, 2)
    row = {
        "code": code,
        "name": name,
        "price": price,
        "shares": shares,
        "cost": cost,
        "market_value": mv,
        "pnl": pnl,
        "pnl_pct": round(pnl / cv * 100, 2) if cv else 0.0,
    }
    row.update(extra)
    return row


def _portfolio(holdings, **extra):
    tmv = sum(h["market_value"] for h in holdings)
    tcost = sum(h["cost"] * h["shares"] for h in holdings)
    tpnl = tmv - tcost
    d = {
        "holdings": holdings,
        "totals": {
            "market_value": round(tmv, 2),
            "cost": round(tcost, 2),
            "pnl": round(tpnl, 2),
            "pnl_pct": round(tpnl / tcost * 100, 2) if tcost else 0.0,
        },
        "closed": [],
        "realized_pnl": 0.0,
        "updated": "2026-07-21 15:00",
        "last_refresh": None,
    }
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# 空持仓
# ---------------------------------------------------------------------------

def test_empty_portfolio():
    pf = _portfolio([])
    review = _minimal_review()
    ctx = build_portfolio_advice_context(pf, review)
    assert ctx["schema_version"] == SCHEMA_VERSION
    assert ctx["holdings"] == []
    assert ctx["portfolio_summary"]["holding_count"] == 0
    assert ctx["portfolio_summary"]["market_value"] == 0
    assert any("无持仓" in m for m in ctx["data_limitations"])
    assert ctx["account_fields_available"]["sellable_shares"] is False
    assert ctx["account_fields_available"]["total_assets"] is False


# ---------------------------------------------------------------------------
# 单只持仓
# ---------------------------------------------------------------------------

def test_single_holding_fields():
    pf = _portfolio([_holding("600519", "贵州茅台", 1800.0, 100, 1600.0)])
    ctx = build_portfolio_advice_context(pf, _minimal_review())
    assert len(ctx["holdings"]) == 1
    h = ctx["holdings"][0]
    assert h["code"] == "600519"
    assert h["name"] == "贵州茅台"
    assert h["shares"] == 100
    assert h["cost_price"] == 1600.0
    assert h["current_price"] == 1800.0
    assert h["market_value"] == 180000.0
    assert h["pnl_amount"] == 20000.0
    assert h["pnl_pct"] == 12.5
    assert h["holding_weight_pct"] == 100.0
    assert h["distance_to_cost_pct"] == 12.5
    assert "quote" in h
    assert set(h["quote"].keys()) >= {
        "open", "high", "low", "prev_close", "price", "change_pct",
        "amount", "turnover_pct", "amplitude_pct", "limit_up", "limit_down",
    }


# ---------------------------------------------------------------------------
# 多只持仓权重
# ---------------------------------------------------------------------------

def test_multi_holding_weights():
    # A: 100*10=1000, B: 200*15=3000 → 25% / 75%
    pf = _portfolio([
        _holding("000001", "平安银行", 10.0, 100, 9.0),
        _holding("000002", "万科A", 15.0, 200, 14.0),
    ])
    ctx = build_portfolio_advice_context(pf, _minimal_review())
    assert ctx["portfolio_summary"]["holding_count"] == 2
    assert ctx["portfolio_summary"]["market_value"] == 4000.0
    by_code = {h["code"]: h for h in ctx["holdings"]}
    assert by_code["000001"]["holding_weight_pct"] == 25.0
    assert by_code["000002"]["holding_weight_pct"] == 75.0
    # 权重和约为 100
    assert abs(sum(h["holding_weight_pct"] for h in ctx["holdings"]) - 100.0) < 0.05


# ---------------------------------------------------------------------------
# 行情补充 / 缺失
# ---------------------------------------------------------------------------

def test_quote_enrichment():
    pf = _portfolio([_holding("600000", "浦发银行", 10.0, 1000, 9.5)])
    quotes = {
        "600000": {
            "open": 9.8,
            "high": 10.5,
            "low": 9.7,
            "prev_close": 9.9,
            "price": 10.2,
            "change_pct": 3.03,
            "amount": 1.2e9,
            "turnover_pct": 1.5,
            "amplitude_pct": 8.08,
            "limit_up": 10.89,
            "limit_down": 8.91,
        }
    }
    ctx = build_portfolio_advice_context(pf, _minimal_review(), quotes=quotes)
    h = ctx["holdings"][0]
    assert h["current_price"] == 10.2  # 使用 quote 价重算
    assert h["quote"]["open"] == 9.8
    assert h["quote"]["high"] == 10.5
    assert h["quote"]["limit_up"] == 10.89
    assert h["missing_quote_fields"] == []


def test_missing_quote_fields_null():
    pf = _portfolio([_holding("600000", "浦发银行", 10.0, 1000, 9.5)])
    ctx = build_portfolio_advice_context(pf, _minimal_review(), quotes=None)
    h = ctx["holdings"][0]
    assert h["quote"]["price"] == 10.0  # 回退持仓价
    assert h["quote"]["open"] is None
    assert h["quote"]["amplitude_pct"] is None
    assert "open" in h["missing_quote_fields"]
    assert any("缺少完整日内行情" in m for m in ctx["data_limitations"])


def test_tencent_last_close_maps_to_prev_close():
    pf = _portfolio([_holding("600000", "浦发银行", 10.0, 100, 9.0)])
    quotes = {"600000": {"last_close": 9.8, "price": 10.0}}
    ctx = build_portfolio_advice_context(pf, _minimal_review(), quotes=quotes)
    assert ctx["holdings"][0]["quote"]["prev_close"] == 9.8


# ---------------------------------------------------------------------------
# 市场上下文嵌入
# ---------------------------------------------------------------------------

def test_embeds_market_context():
    ctx = build_portfolio_advice_context(
        _portfolio([_holding("000001", "平安银行", 10.0, 100, 9.0)]),
        _minimal_review(),
    )
    mc = ctx["market_context"]
    assert "review_metadata" in mc
    assert "market_environment" in mc
    assert mc["market_environment"]["breadth"]["up_ratio"] == 0.6122
    assert "short_term_emotion" in mc


# ---------------------------------------------------------------------------
# 不生成建议 / 固定 limitations
# ---------------------------------------------------------------------------

def test_no_action_fields_in_holdings():
    ctx = build_portfolio_advice_context(
        _portfolio([_holding("000001", "平安银行", 10.0, 100, 9.0)]),
        _minimal_review(),
    )
    h = ctx["holdings"][0]
    assert "action" not in h
    assert "execution_quantity" not in h
    for key in ("sellable_shares", "total_assets", "cash_available"):
        assert key not in h


def test_base_limitations_always_present():
    ctx = build_portfolio_advice_context(_portfolio([]), _minimal_review())
    text = "\n".join(ctx["data_limitations"])
    assert "可卖数量" in text or "sellable" in text.lower() or "人工确认" in text
    assert "账户总资产" in text or "可用现金" in text
    assert "催化" in text or "公告" in text
    # 第一版不做 T：context limitations 不再提做 T 数量
    assert "做 T" not in text and "做T" not in text


def test_context_has_no_t_trade_fields():
    ctx = build_portfolio_advice_context(
        _portfolio([_holding("000001", "平安银行", 10.0, 100, 9.0)]),
        _minimal_review(),
    )
    assert "t_trade" not in ctx
    assert "allow_t_trade" not in ctx
    for h in ctx["holdings"]:
        assert "t_trade" not in h
        assert "allow_t_trade" not in h


# ---------------------------------------------------------------------------
# 输入不被修改 / 确定性
# ---------------------------------------------------------------------------

def test_input_not_mutated():
    pf = _portfolio([_holding("000001", "平安银行", 10.0, 100, 9.0)])
    review = _minimal_review()
    pf_before = copy.deepcopy(pf)
    review_before = copy.deepcopy(review)
    build_portfolio_advice_context(pf, review, quotes={"000001": {"price": 11.0}})
    assert pf == pf_before
    assert review == review_before


def test_deterministic_same_input():
    pf = _portfolio([
        _holding("000001", "A", 10.0, 100, 9.0),
        _holding("000002", "B", 20.0, 200, 18.0),
    ])
    review = _minimal_review()
    quotes = {"000001": {"price": 10.5, "open": 10.0}, "000002": {"price": 20.0}}
    a = build_portfolio_advice_context(pf, review, quotes=quotes)
    b = build_portfolio_advice_context(pf, review, quotes=quotes)
    assert a == b
    assert render_portfolio_advice_context(pf, review, quotes=quotes) == \
        render_portfolio_advice_context(pf, review, quotes=quotes)


def test_render_is_valid_json():
    s = render_portfolio_advice_context(
        _portfolio([_holding("000001", "A", 10.0, 100, 9.0)]),
        _minimal_review(),
    )
    parsed = json.loads(s)
    assert parsed["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 类型校验
# ---------------------------------------------------------------------------

def test_type_errors():
    with pytest.raises(TypeError):
        build_portfolio_advice_context([], _minimal_review())
    with pytest.raises(TypeError):
        build_portfolio_advice_context(_portfolio([]), [])
    with pytest.raises(ValueError):
        build_portfolio_advice_context(_portfolio([]), _minimal_review(), board_limit=0)


def test_zero_price_holding():
    """行情/价格为 0 时不崩溃，市值与权重为 0。"""
    pf = _portfolio([_holding("000001", "A", 0.0, 100, 10.0)])
    # 手动改 market_value 以匹配 0 价
    pf["holdings"][0]["market_value"] = 0.0
    pf["holdings"][0]["pnl"] = -1000.0
    pf["totals"] = {"market_value": 0.0, "cost": 1000.0, "pnl": -1000.0, "pnl_pct": -100.0}
    ctx = build_portfolio_advice_context(pf, _minimal_review())
    h = ctx["holdings"][0]
    assert h["market_value"] == 0.0
    assert h["holding_weight_pct"] == 0.0
