"""portfolio_advice_validator 纯函数离线测试（不联网、不改输入、不写 portfolio.json）。"""
from __future__ import annotations

import copy

import pytest

from portfolio_advice_prompt import SCHEMA_VERSION
from portfolio_advice_validator import (
    PortfolioAdviceValidationError,
    compute_add_execution_quantity,
    compute_estimated_amount,
    compute_execution_quantity,
    floor_to_lot,
    validate_portfolio_advice,
)


def _ctx_holding(
    code="600519",
    name="贵州茅台",
    shares=1500,
    cost=100.0,
    price=110.0,
    weight=100.0,
):
    mv = round(price * shares, 2)
    cost_v = cost * shares
    pnl = round(mv - cost_v, 2)
    pnl_pct = round(pnl / cost_v * 100, 2) if cost_v else 0.0
    return {
        "code": code,
        "name": name,
        "shares": shares,
        "cost_price": cost,
        "current_price": price,
        "market_value": mv,
        "pnl_amount": pnl,
        "pnl_pct": pnl_pct,
        "holding_weight_pct": weight,
        "distance_to_cost_pct": round((price - cost) / cost * 100, 2) if cost else None,
        "quote": {},
        "missing_quote_fields": [],
    }


def _context(holdings=None, **extra):
    if holdings is None:
        holdings = [_ctx_holding()]
    tmv = sum(h["market_value"] for h in holdings)
    tcost = sum(h["cost_price"] * h["shares"] for h in holdings)
    tpnl = tmv - tcost
    base = {
        "schema_version": "portfolio-advice-context-v0.1",
        "portfolio_summary": {
            "holding_count": len(holdings),
            "market_value": round(tmv, 2),
            "cost": round(tcost, 2),
            "pnl": round(tpnl, 2),
            "pnl_pct": round(tpnl / tcost * 100, 2) if tcost else 0.0,
        },
        "holdings": holdings,
        "market_context": {
            "review_metadata": {"status": "normal"},
        },
        "data_limitations": [
            "未提供账户总资产与可用现金，无法计算绝对账户仓位与具体买入金额。",
            "未提供可卖数量（sellable_shares），执行前需人工确认实际可卖股数。",
        ],
        "warnings": [],
        "account_fields_available": {
            "total_assets": False,
            "cash_available": False,
            "sellable_shares": False,
            "today_buy_shares": False,
            "today_sell_shares": False,
        },
    }
    base.update(extra)
    return base


def _ai_holding(code="600519", action="hold", **kw):
    base = {
        "code": code,
        "name": "贵州茅台",
        "shares": 99999,  # 应被上下文覆盖
        "cost_price": 1,
        "current_price": 1,
        "market_value": 1,
        "pnl_amount": 1,
        "pnl_pct": 1,
        "holding_weight_pct": 1,
        "action": action,
        "execution_size_pct_of_holding": None,
        "execution_quantity": 999,
        "trigger_conditions": ["条件A"],
        "price_conditions": ["价格条件"],
        "execution_plan": ["计划"],
        "risk_conditions": ["风险"],
        "invalidation_conditions": ["失效"],
        "confidence": "medium",
        "data_limitations": [],
    }
    base.update(kw)
    return base


def _ai_result(holdings=None, **extra):
    if holdings is None:
        holdings = [_ai_holding()]
    d = {
        "schema_version": "wrong-version",
        "generated_at": "2026-07-21T16:00:00",
        "market_status": "normal",
        "portfolio_summary": {
            "holding_count": 99,
            "market_value": 1,
            "cost": 1,
            "pnl": 1,
            "pnl_pct": 1,
        },
        "account_action": {
            "action": "hold",
            "reason": "观望为主",
            "confidence": "medium",
        },
        "holdings": holdings,
        "warnings": [],
        "data_limitations": [],
    }
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# 数量工具
# ---------------------------------------------------------------------------

def test_floor_to_lot():
    assert floor_to_lot(375) == 300
    assert floor_to_lot(300) == 300
    assert floor_to_lot(99) == 0
    assert floor_to_lot(0) == 0
    assert floor_to_lot(-10) == 0


def test_compute_reduce_20pct_1500():
    # 1500 * 20% = 300
    assert compute_execution_quantity(1500, 20) == 300


def test_compute_reduce_25pct_1500_floor():
    # 1500 * 25% = 375 → 300
    assert compute_execution_quantity(1500, 25) == 300


def test_compute_sell_100pct_1500():
    assert compute_execution_quantity(1500, 100) == 1500


def test_compute_quantity_not_exceed_shares():
    # 即使百分比算出来更大，也不超过 shares（截断后仍 lot）
    assert compute_execution_quantity(150, 100) == 100  # 150 → floor 100? wait 150*100%=150, floor_to_lot(150)=100
    assert compute_execution_quantity(1500, 200) == 1500  # pct clamp to 100 first → 1500


# ---------------------------------------------------------------------------
# 空持仓
# ---------------------------------------------------------------------------

def test_empty_portfolio_validation():
    ctx = _context(holdings=[])
    ai = _ai_result(holdings=[])
    out = validate_portfolio_advice(ai, ctx)
    assert out["schema_version"] == SCHEMA_VERSION
    assert out["holdings"] == []
    assert out["portfolio_summary"]["holding_count"] == 0
    assert any("可卖" in m or "人工确认" in m for m in out["data_limitations"])


def test_warnings_deduped():
    ctx = _context(warnings=["同一警告", "另一警告"])
    ai = _ai_result(
        warnings=["同一警告", "同一警告", "第三警告", "同一警告"],
    )
    out = validate_portfolio_advice(ai, ctx)
    assert out["warnings"].count("同一警告") == 1
    assert out["warnings"].count("另一警告") == 1
    assert out["warnings"].count("第三警告") == 1
    # 稳定顺序：模型顺序优先，再合并上下文未出现项
    assert out["warnings"].index("同一警告") < out["warnings"].index("第三警告")


def test_data_limitations_deduped_top_and_holding():
    dup = "未提供可卖数量，执行前需要人工确认实际可卖股数。"
    ctx = _context(
        data_limitations=[dup, "未提供可用现金无法加仓", dup],
    )
    ai = _ai_result(
        data_limitations=[dup, "模型限制A", dup],
        holdings=[
            _ai_holding(
                action="reduce",
                execution_size_pct_of_holding=20,
                data_limitations=[dup, "持股限制", dup],
            )
        ],
    )
    out = validate_portfolio_advice(ai, ctx)
    assert out["data_limitations"].count(dup) == 1
    assert out["data_limitations"].count("模型限制A") == 1
    # 现金类语义归一为标准文案，且只一次
    cash_std = (
        "未提供账户总资产与可用现金，买入数量仅按当前持股比例计算；"
        "执行前需要确认可用资金充足。"
    )
    assert out["data_limitations"].count(cash_std) == 1
    h_lim = out["holdings"][0]["data_limitations"]
    assert h_lim.count(dup) == 1
    assert h_lim.count("持股限制") == 1


def test_trade_date_passthrough_not_fabricated():
    ctx = _context(
        portfolio_meta={"trade_date": "2026-07-20", "updated": None, "last_refresh": None}
    )
    out = validate_portfolio_advice(_ai_result(), ctx)
    assert out["trade_date"] == "2026-07-20"

    ctx2 = _context(portfolio_meta={"updated": None})
    out2 = validate_portfolio_advice(_ai_result(), ctx2)
    assert out2["trade_date"] is None


# ---------------------------------------------------------------------------
# 事实字段覆盖
# ---------------------------------------------------------------------------

def test_code_facts_override_ai_numbers():
    ctx = _context(holdings=[_ctx_holding(shares=1500, cost=100.0, price=110.0)])
    ai = _ai_result(holdings=[_ai_holding(action="hold", market_value=1, pnl_amount=1)])
    out = validate_portfolio_advice(ai, ctx)
    h = out["holdings"][0]
    assert h["shares"] == 1500
    assert h["cost_price"] == 100.0
    assert h["current_price"] == 110.0
    assert h["market_value"] == 165000.0
    assert h["pnl_amount"] == 15000.0
    assert h["pnl_pct"] == pytest.approx(10.0)
    assert h["holding_weight_pct"] == 100.0


def test_portfolio_summary_from_context():
    h1 = _ctx_holding("000001", "A", shares=100, cost=10, price=10, weight=25)
    h2 = _ctx_holding("000002", "B", shares=200, cost=15, price=15, weight=75)
    # fix market values
    h1["market_value"] = 1000.0
    h2["market_value"] = 3000.0
    ctx = _context(holdings=[h1, h2])
    ai = _ai_result(holdings=[
        _ai_holding(code="000001", action="hold"),
        _ai_holding(code="000002", action="hold"),
    ])
    out = validate_portfolio_advice(ai, ctx)
    assert out["portfolio_summary"]["market_value"] == 4000.0
    assert out["portfolio_summary"]["holding_count"] == 2


# ---------------------------------------------------------------------------
# reduce / sell 数量
# ---------------------------------------------------------------------------

def test_reduce_20pct_quantity_300():
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    ai = _ai_result(holdings=[
        _ai_holding(action="reduce", execution_size_pct_of_holding=20, execution_quantity=9999)
    ])
    out = validate_portfolio_advice(ai, ctx)
    h = out["holdings"][0]
    assert h["action"] == "reduce"
    assert h["execution_size_pct_of_holding"] == 20
    assert h["execution_quantity"] == 300
    assert any("可卖" in m or "人工确认" in m for m in h["data_limitations"])


def test_reduce_25pct_rejected_not_a_tier():
    """reduce 仅允许 10/20/30 档；25 非法。"""
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    ai = _ai_result(holdings=[
        _ai_holding(action="reduce", execution_size_pct_of_holding=25)
    ])
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice(ai, ctx)


def test_sell_100pct_quantity_1500():
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    ai = _ai_result(holdings=[
        _ai_holding(action="sell", execution_size_pct_of_holding=100)
    ])
    out = validate_portfolio_advice(ai, ctx)
    assert out["holdings"][0]["execution_quantity"] == 1500


def test_quantity_never_exceeds_shares():
    ctx = _context(holdings=[_ctx_holding(shares=250)])
    ai = _ai_result(holdings=[
        _ai_holding(action="sell", execution_size_pct_of_holding=100, execution_quantity=99999)
    ])
    out = validate_portfolio_advice(ai, ctx)
    # 250 floor lot = 200
    assert out["holdings"][0]["execution_quantity"] == 200
    assert out["holdings"][0]["execution_quantity"] <= 250


# ---------------------------------------------------------------------------
# add / hold / watch / avoid 数量
# ---------------------------------------------------------------------------

def test_add_overrides_model_quantity_and_amount():
    """模型结构化 quantity/amount 一律丢弃，后端按持股比例重算。"""
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    ai = _ai_result(holdings=[
        _ai_holding(
            action="add",
            execution_size_pct_of_holding=10,
            execution_quantity=500,
            estimated_amount=99999,
            confidence="medium",
        )
    ])
    out = validate_portfolio_advice(ai, ctx)
    h = out["holdings"][0]
    assert h["action"] == "add"
    assert h["execution_size_pct_of_holding"] == 10
    assert h["execution_quantity"] == 100  # 1500*10% → 150 → floor 100
    assert h["estimated_amount"] == 1429.0
    assert any("可用现金" in m or "持股比例" in m for m in h["data_limitations"])


def test_hold_watch_avoid_clear_quantity():
    for action in ("hold", "watch", "avoid"):
        ctx = _context()
        ai = _ai_result(holdings=[
            _ai_holding(
                action=action,
                execution_quantity=100,
                execution_size_pct_of_holding=50,
                estimated_amount=1000,
            )
        ])
        out = validate_portfolio_advice(ai, ctx)
        h = out["holdings"][0]
        assert h["action"] == action
        assert h["execution_quantity"] is None
        assert h["execution_size_pct_of_holding"] is None
        assert h["estimated_amount"] is None


# ---------------------------------------------------------------------------
# 非法 action / 百分比 / 做 T 拒绝
# ---------------------------------------------------------------------------

def test_illegal_action_raises():
    ctx = _context()
    ai = _ai_result(holdings=[_ai_holding(action="谨慎持有")])
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice(ai, ctx)


def test_action_t_trade_rejected():
    ctx = _context()
    ai = _ai_result(holdings=[_ai_holding(action="t_trade")])
    with pytest.raises(PortfolioAdviceValidationError) as ei:
        validate_portfolio_advice(ai, ctx)
    assert "t_trade" in str(ei.value)
    assert "非法 action" in str(ei.value)


def test_extra_t_trade_field_stripped():
    """模型额外输出 t_trade 字段：忽略并从权威结果中删除。"""
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(
            action="hold",
            t_trade={
                "suitable": True,
                "direction": "sell_then_buy",
                "quantity": 300,
            },
        )
    ])
    out = validate_portfolio_advice(ai, ctx)
    h = out["holdings"][0]
    assert "t_trade" not in h
    assert "t_trade" not in out
    # 递归确认权威结果无 t_trade 键
    blob = str(out)
    # 值层面：键名不得作为结果字段存在（action 已非 t_trade）
    def _has_t_trade_key(obj):
        if isinstance(obj, dict):
            if "t_trade" in obj:
                return True
            return any(_has_t_trade_key(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_has_t_trade_key(v) for v in obj)
        return False

    assert _has_t_trade_key(out) is False
    assert h["action"] == "hold"
    assert h["execution_quantity"] is None


def test_result_never_contains_t_trade_structure():
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(action="reduce", execution_size_pct_of_holding=20)
    ])
    out = validate_portfolio_advice(ai, ctx)
    assert "t_trade" not in out["holdings"][0]
    assert "t_trade" not in out


def test_illegal_pct_raises():
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(action="reduce", execution_size_pct_of_holding=150)
    ])
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice(ai, ctx)


def test_negative_pct_raises():
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(action="reduce", execution_size_pct_of_holding=-5)
    ])
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice(ai, ctx)


# ---------------------------------------------------------------------------
# 缺可卖 limitation / 多持仓
# ---------------------------------------------------------------------------

def test_sellable_limitation_on_reduce():
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(action="reduce", execution_size_pct_of_holding=20)
    ])
    out = validate_portfolio_advice(ai, ctx)
    assert any("可卖" in m for m in out["holdings"][0]["data_limitations"])
    assert any("可卖" in m for m in out["data_limitations"])


def test_multi_holdings_weights_preserved():
    h1 = _ctx_holding("000001", "A", shares=100, cost=10, price=10, weight=25.0)
    h2 = _ctx_holding("000002", "B", shares=300, cost=10, price=10, weight=75.0)
    h1["market_value"] = 1000.0
    h2["market_value"] = 3000.0
    ctx = _context(holdings=[h1, h2])
    ai = _ai_result(holdings=[
        _ai_holding(code="000001", action="hold"),
        _ai_holding(code="000002", action="reduce", execution_size_pct_of_holding=20),
    ])
    out = validate_portfolio_advice(ai, ctx)
    by = {h["code"]: h for h in out["holdings"]}
    assert by["000001"]["holding_weight_pct"] == 25.0
    assert by["000002"]["holding_weight_pct"] == 75.0
    assert by["000002"]["execution_quantity"] == 0  # 300*20%=60 → floor 0? 60//100*100=0
    # Actually 300 * 0.2 = 60, floor to 100 = 0. That's correct for lot rule.
    # User might want reduce on 300 shares with 20% - gets 0 lots. Correct.


def test_missing_ai_holding_synthesized_watch():
    ctx = _context(holdings=[
        _ctx_holding("000001", "A", shares=100, cost=10, price=10),
        _ctx_holding("000002", "B", shares=200, cost=10, price=10),
    ])
    ai = _ai_result(holdings=[_ai_holding(code="000001", action="hold")])
    out = validate_portfolio_advice(ai, ctx)
    codes = {h["code"] for h in out["holdings"]}
    assert codes == {"000001", "000002"}
    by = {h["code"]: h for h in out["holdings"]}
    assert by["000002"]["action"] == "watch"
    assert by["000002"]["confidence"] == "low"


def test_extra_ai_code_dropped():
    ctx = _context(holdings=[_ctx_holding("000001", "A", shares=100, cost=10, price=10)])
    ai = _ai_result(holdings=[
        _ai_holding(code="000001", action="hold"),
        _ai_holding(code="999999", action="sell", execution_size_pct_of_holding=100),
    ])
    out = validate_portfolio_advice(ai, ctx)
    assert len(out["holdings"]) == 1
    assert out["holdings"][0]["code"] == "000001"


def test_duplicate_code_invalid_first_valid_last_uses_last_entry():
    ctx = _context(holdings=[_ctx_holding("000001", "A", shares=100, cost=10, price=10)])
    ai = _ai_result(holdings=[
        _ai_holding(code="000001", action="not-an-action"),
        _ai_holding(
            code="000001",
            action="reduce",
            confidence="medium",
            execution_size_pct_of_holding=20,
            trigger_conditions=["后出现的建议"],
        ),
    ])

    out = validate_portfolio_advice(ai, ctx)

    holding = out["holdings"][0]
    assert holding["action"] == "reduce"
    assert holding["confidence"] == "medium"
    assert holding["trigger_conditions"] == ["后出现的建议"]
    assert holding["execution_size_pct_of_holding"] == 20


def test_duplicate_code_valid_first_invalid_last_rejects_final_entry():
    ctx = _context(holdings=[_ctx_holding("000001", "A", shares=100, cost=10, price=10)])
    ai = _ai_result(holdings=[
        _ai_holding(code="000001", action="hold"),
        _ai_holding(code="000001", action="not-an-action"),
    ])

    with pytest.raises(PortfolioAdviceValidationError, match="非法 action"):
        validate_portfolio_advice(ai, ctx)


def test_duplicate_code_valid_last_entry_overrides_all_advice_fields():
    ctx = _context(holdings=[_ctx_holding("000001", "A", shares=1500, cost=10, price=10)])
    ai = _ai_result(holdings=[
        _ai_holding(
            code="000001",
            action="hold",
            confidence="low",
            trigger_conditions=["第一条建议"],
        ),
        _ai_holding(
            code="000001",
            action="add",
            confidence="medium",
            execution_size_pct_of_holding=10,
            trigger_conditions=["第二条建议"],
        ),
    ])

    out = validate_portfolio_advice(ai, ctx)

    holding = out["holdings"][0]
    assert holding["action"] == "add"
    assert holding["confidence"] == "medium"
    assert holding["trigger_conditions"] == ["第二条建议"]
    assert holding["execution_size_pct_of_holding"] == 10
    assert holding["execution_quantity"] == 100


# ---------------------------------------------------------------------------
# 输入不被修改 / 确定性
# ---------------------------------------------------------------------------

def test_input_not_mutated():
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(action="reduce", execution_size_pct_of_holding=20, execution_quantity=1)
    ])
    ctx_before = copy.deepcopy(ctx)
    ai_before = copy.deepcopy(ai)
    validate_portfolio_advice(ai, ctx)
    assert ctx == ctx_before
    assert ai == ai_before


def test_deterministic_validation():
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(action="reduce", execution_size_pct_of_holding=20)
    ])
    a = validate_portfolio_advice(ai, ctx)
    b = validate_portfolio_advice(ai, ctx)
    assert a == b


def test_non_dict_raises():
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice([], _context())
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice({}, [])


# ---------------------------------------------------------------------------
# 数字可追溯 / 档位 / 一致性 / 模板话术 / 限制归一
# ---------------------------------------------------------------------------

def test_untraceable_number_2500_rejected():
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(
            action="hold",
            trigger_conditions=["上涨家数达到2500家"],
        )
    ])
    with pytest.raises(PortfolioAdviceValidationError, match="无法追溯的数字"):
        validate_portfolio_advice(ai, ctx)


def test_untraceable_number_2pct_rejected():
    ctx = _context()
    ai = _ai_result(holdings=[
        _ai_holding(
            action="hold",
            risk_conditions=["板块涨幅超过2%"],
        )
    ])
    with pytest.raises(PortfolioAdviceValidationError, match="无法追溯的数字"):
        validate_portfolio_advice(ai, ctx)


def test_context_number_allowed_in_conditions():
    """context 已有 up_count=3000 时，条件可引用 3000。"""
    ctx = _context(
        market_evidence={
            "breadth": {"up_count": 3000, "stock_count": 5000},
            "review_status": "normal",
        }
    )
    ai = _ai_result(holdings=[
        _ai_holding(
            action="hold",
            trigger_conditions=["上涨家数约3000家，维持观察"],
            invalidation_conditions=["市场广度明显修复"],
        )
    ])
    out = validate_portfolio_advice(ai, ctx)
    assert out["holdings"][0]["action"] == "hold"


def test_add_only_allows_10_or_20():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    for pct in (10, 20):
        out = validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(action="add", execution_size_pct_of_holding=pct, confidence="high")
            ]),
            ctx,
        )
        assert out["holdings"][0]["execution_size_pct_of_holding"] == pct
        expected_qty = 100 if pct == 10 else 300
        assert out["holdings"][0]["execution_quantity"] == expected_qty
        assert out["holdings"][0]["estimated_amount"] is not None
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(action="add", execution_size_pct_of_holding=15, confidence="high")
            ]),
            ctx,
        )


def test_reduce_only_allows_10_20_30():
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    for pct in (10, 20, 30):
        conf = "high" if pct == 30 else "medium"
        out = validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(action="reduce", execution_size_pct_of_holding=pct, confidence=conf)
            ]),
            ctx,
        )
        assert out["holdings"][0]["execution_size_pct_of_holding"] == pct
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(action="reduce", execution_size_pct_of_holding=15, confidence="high")
            ]),
            ctx,
        )


def test_sell_forced_to_100():
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="sell", execution_size_pct_of_holding=None, confidence="low")
        ]),
        ctx,
    )
    assert out["holdings"][0]["execution_size_pct_of_holding"] == 100
    assert out["holdings"][0]["execution_quantity"] == 1500


def test_confidence_caps_on_reduce():
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    # low 最多 10
    with pytest.raises(PortfolioAdviceValidationError, match="上限"):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(action="reduce", execution_size_pct_of_holding=20, confidence="low")
            ]),
            ctx,
        )
    # medium 最多 20，30 拒绝
    with pytest.raises(PortfolioAdviceValidationError, match="上限"):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(action="reduce", execution_size_pct_of_holding=30, confidence="medium")
            ]),
            ctx,
        )
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="reduce", execution_size_pct_of_holding=30, confidence="high")
        ]),
        ctx,
    )
    assert out["holdings"][0]["execution_size_pct_of_holding"] == 30


def test_partial_market_caps_add_and_reduce():
    ctx = _context(market_context={"review_metadata": {"status": "partial"}})
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(action="add", execution_size_pct_of_holding=20, confidence="high")
            ]),
            ctx,
        )
    with pytest.raises(PortfolioAdviceValidationError):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(action="reduce", execution_size_pct_of_holding=30, confidence="high")
            ]),
            _context(
                holdings=[_ctx_holding(shares=1500)],
                market_context={"review_metadata": {"status": "partial"}},
            ),
        )
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="add", execution_size_pct_of_holding=10, confidence="high")
        ]),
        ctx,
    )
    assert out["holdings"][0]["execution_size_pct_of_holding"] == 10


def test_reduce_risk_worsen_but_pause_rejected():
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    ai = _ai_result(holdings=[
        _ai_holding(
            action="reduce",
            execution_size_pct_of_holding=20,
            confidence="medium",
            invalidation_conditions=["若继续下跌或风险恶化则暂停减仓"],
        )
    ])
    with pytest.raises(PortfolioAdviceValidationError, match="冲突"):
        validate_portfolio_advice(ai, ctx)


def test_legal_invalidation_for_reduce_passes():
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    ai = _ai_result(holdings=[
        _ai_holding(
            action="reduce",
            execution_size_pct_of_holding=20,
            confidence="medium",
            invalidation_conditions=["市场广度明显修复后重新评估减仓"],
            risk_conditions=["市场继续走弱时优先执行减仓"],
            execution_plan=["执行前确认实际可卖数量，并按计划数量执行"],
        )
    ])
    out = validate_portfolio_advice(ai, ctx)
    assert out["holdings"][0]["action"] == "reduce"
    assert out["holdings"][0]["execution_quantity"] == 300


def test_market_impact_template_rejected():
    ctx = _context(holdings=[_ctx_holding(shares=1500)])
    ai = _ai_result(holdings=[
        _ai_holding(
            action="reduce",
            execution_size_pct_of_holding=20,
            confidence="medium",
            execution_plan=["分批卖出以减少市场冲击"],
        )
    ])
    with pytest.raises(PortfolioAdviceValidationError, match="市场冲击"):
        validate_portfolio_advice(ai, ctx)


def test_limitation_semantic_normalize_four_classes():
    ctx = _context(
        data_limitations=[
            "缺少可卖数量 sellable_shares",
            "没有账户总资产和现金",
            "无历史K线不能看均线支撑",
            "没有公告新闻不判断催化",
            "缺少可卖数量请人工确认",  # 再一次可卖 → 归一后只一次
        ]
    )
    out = validate_portfolio_advice(_ai_result(holdings=[_ai_holding(action="hold")]), ctx)
    lims = out["data_limitations"]
    assert lims.count("未提供可卖数量，执行前需要人工确认实际可卖股数。") == 1
    assert lims.count(
        "未提供账户总资产与可用现金，买入数量仅按当前持股比例计算；"
        "执行前需要确认可用资金充足。"
    ) == 1
    assert lims.count("未提供历史K线与技术指标，无法计算趋势、支撑位或压力位。") == 1
    assert lims.count("未接入可靠公告、新闻和机构公开信息，不判断消息催化原因。") == 1

# ---------------------------------------------------------------------------
# add：买入数量 / 预计金额
# ---------------------------------------------------------------------------

def test_compute_add_quantity_tiers():
    assert compute_add_execution_quantity(1500, 10) == 100
    assert compute_add_execution_quantity(1500, 20) == 300
    assert compute_add_execution_quantity(300, 10) is None
    assert compute_add_execution_quantity(600, 20) == 100
    assert compute_add_execution_quantity(None, 10) is None
    assert compute_add_execution_quantity(0, 20) is None


def test_compute_estimated_amount_precision():
    assert compute_estimated_amount(300, 14.29) == 4287.0
    assert compute_estimated_amount(100, 14.29) == 1429.0
    # 无浮点尾差
    assert compute_estimated_amount(3, 0.1) == 0.3
    assert compute_estimated_amount(None, 14.29) is None
    assert compute_estimated_amount(300, None) is None
    assert compute_estimated_amount(300, 0) is None
    assert compute_estimated_amount(300, -1) is None


def test_add_1500_10pct_qty_and_amount():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="add", execution_size_pct_of_holding=10, confidence="medium",
                        execution_quantity=None, estimated_amount=None)
        ]),
        ctx,
    )
    h = out["holdings"][0]
    assert h["execution_quantity"] == 100
    assert h["estimated_amount"] == 1429.0


def test_add_1500_20pct_qty_and_amount():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="add", execution_size_pct_of_holding=20, confidence="medium",
                        execution_quantity=None, estimated_amount=None)
        ]),
        ctx,
    )
    h = out["holdings"][0]
    assert h["execution_quantity"] == 300
    assert h["estimated_amount"] == 4287.0


def test_add_300_10pct_insufficient_lot():
    ctx = _context(holdings=[_ctx_holding(shares=300, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="add", execution_size_pct_of_holding=10, confidence="medium")
        ]),
        ctx,
    )
    h = out["holdings"][0]
    assert h["action"] == "add"
    assert h["execution_size_pct_of_holding"] == 10
    assert h["execution_quantity"] is None
    assert h["estimated_amount"] is None
    assert any("100股交易单位" in m for m in h["data_limitations"])


def test_add_missing_price_qty_ok_amount_null():
    h0 = _ctx_holding(shares=1500, price=14.29)
    h0["current_price"] = None
    ctx = _context(holdings=[h0])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="add", execution_size_pct_of_holding=20, confidence="medium")
        ]),
        ctx,
    )
    h = out["holdings"][0]
    assert h["execution_quantity"] == 300
    assert h["estimated_amount"] is None
    assert any("当前价格不可用" in m for m in h["data_limitations"])


def test_add_zero_price_no_amount():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=0)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="add", execution_size_pct_of_holding=10, confidence="medium")
        ]),
        ctx,
    )
    h = out["holdings"][0]
    assert h["execution_quantity"] == 100
    assert h["estimated_amount"] is None


def test_add_missing_shares_nulls():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    ctx["holdings"][0]["shares"] = None
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="add", execution_size_pct_of_holding=10, confidence="medium")
        ]),
        ctx,
    )
    h = out["holdings"][0]
    assert h["execution_quantity"] is None
    assert h["estimated_amount"] is None
    assert any("持股数量不可用" in m for m in h["data_limitations"])


def test_add_model_null_fields_backend_fills():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(
                action="add",
                execution_size_pct_of_holding=20,
                confidence="medium",
                execution_quantity=None,
                estimated_amount=None,
            )
        ]),
        ctx,
    )
    h = out["holdings"][0]
    assert h["execution_quantity"] == 300
    assert h["estimated_amount"] == 4287.0


def test_add_text_buy_qty_match_passes():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(
                action="add",
                execution_size_pct_of_holding=10,
                confidence="medium",
                execution_plan=["当前持有1500股，建议买入100股"],
            )
        ]),
        ctx,
    )
    assert out["holdings"][0]["execution_quantity"] == 100


def test_add_text_buy_qty_mismatch_rejects():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    with pytest.raises(PortfolioAdviceValidationError, match="买入股数"):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(
                    action="add",
                    execution_size_pct_of_holding=10,
                    confidence="medium",
                    execution_plan=["建议买入150股"],
                )
            ]),
            ctx,
        )


def test_add_text_add_qty_300_passes():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(
                action="add",
                execution_size_pct_of_holding=20,
                confidence="medium",
                execution_plan=["加仓300股"],
            )
        ]),
        ctx,
    )
    assert out["holdings"][0]["execution_quantity"] == 300


def test_add_text_buy_qty_when_null_rejects():
    ctx = _context(holdings=[_ctx_holding(shares=300, price=14.29)])
    with pytest.raises(PortfolioAdviceValidationError, match="无具体买入数量"):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(
                    action="add",
                    execution_size_pct_of_holding=10,
                    confidence="medium",
                    execution_plan=["买入100股"],
                )
            ]),
            ctx,
        )


def test_add_text_amount_approx_passes():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(
                action="add",
                execution_size_pct_of_holding=20,
                confidence="medium",
                execution_plan=["预计需要约4287元", "加仓300股"],
            )
        ]),
        ctx,
    )
    assert out["holdings"][0]["estimated_amount"] == 4287.0


def test_add_text_amount_wan_approx_passes():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(
                action="add",
                execution_size_pct_of_holding=20,
                confidence="medium",
                execution_plan=["约0.43万元", "加仓300股"],
            )
        ]),
        ctx,
    )
    assert out["holdings"][0]["estimated_amount"] == 4287.0


def test_add_text_amount_mismatch_rejects():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    with pytest.raises(PortfolioAdviceValidationError, match="投入金额"):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(
                    action="add",
                    execution_size_pct_of_holding=20,
                    confidence="medium",
                    execution_plan=["预计需要5000元", "加仓300股"],
                )
            ]),
            ctx,
        )


def test_add_text_amount_when_null_rejects():
    h0 = _ctx_holding(shares=1500, price=14.29)
    h0["current_price"] = None
    ctx = _context(holdings=[h0])
    with pytest.raises(PortfolioAdviceValidationError, match="预计金额"):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(
                    action="add",
                    execution_size_pct_of_holding=20,
                    confidence="medium",
                    execution_plan=["投入3000元", "加仓300股"],
                )
            ]),
            ctx,
        )


def test_add_current_holdings_not_buy_qty():
    """「当前持有1500股」不得被当成建议买入1500股。"""
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(
                action="add",
                execution_size_pct_of_holding=10,
                confidence="medium",
                trigger_conditions=["当前持有1500股，相对当前持股加仓10%"],
                execution_plan=["建议买入100股"],
            )
        ]),
        ctx,
    )
    assert out["holdings"][0]["execution_quantity"] == 100


def test_add_relative_holding_pct_language_passes():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(
                action="add",
                execution_size_pct_of_holding=20,
                confidence="medium",
                execution_plan=["相对当前持股加仓20%", "加仓300股"],
            )
        ]),
        ctx,
    )
    assert out["holdings"][0]["action"] == "add"


@pytest.mark.parametrize(
    "bad",
    [
        "使用账户20%资金买入",
        "将账户仓位提高20%",
        "投入总资产20%",
    ],
)
def test_add_account_ratio_language_rejects(bad):
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    with pytest.raises(PortfolioAdviceValidationError, match="账户/总资产/可用资金"):
        validate_portfolio_advice(
            _ai_result(holdings=[
                _ai_holding(
                    action="add",
                    execution_size_pct_of_holding=20,
                    confidence="medium",
                    execution_plan=[bad, "加仓300股"],
                )
            ]),
            ctx,
        )


def test_reduce_sell_estimated_amount_null():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out_r = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="reduce", execution_size_pct_of_holding=20, confidence="medium")
        ]),
        ctx,
    )
    assert out_r["holdings"][0]["execution_quantity"] == 300
    assert out_r["holdings"][0]["estimated_amount"] is None
    out_s = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(action="sell", execution_size_pct_of_holding=100, confidence="low")
        ]),
        ctx,
    )
    assert out_s["holdings"][0]["execution_quantity"] == 1500
    assert out_s["holdings"][0]["estimated_amount"] is None


def test_add_limitation_notes_once():
    ctx = _context(holdings=[_ctx_holding(shares=1500, price=14.29)])
    out = validate_portfolio_advice(
        _ai_result(holdings=[
            _ai_holding(
                action="add",
                execution_size_pct_of_holding=20,
                confidence="medium",
                data_limitations=[
                    "未提供账户总资产与可用现金，买入数量仅按当前持股比例计算；执行前需要确认可用资金充足。",
                    "预计金额按当前价格计算，不包含手续费和实际成交价偏差。",
                    "预计金额按当前价格计算，不包含手续费和实际成交价偏差。",
                ],
            )
        ]),
        ctx,
    )
    lims = out["holdings"][0]["data_limitations"]
    assert lims.count(
        "未提供账户总资产与可用现金，买入数量仅按当前持股比例计算；"
        "执行前需要确认可用资金充足。"
    ) == 1
    assert lims.count("预计金额按当前价格计算，不包含手续费和实际成交价偏差。") == 1
    # 资金确认已含在现金文案中，不应再额外堆叠同义重复
    cash_hits = [m for m in lims if "可用资金" in m]
    assert len(cash_hits) == 1
