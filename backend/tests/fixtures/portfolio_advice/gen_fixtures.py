"""
golden fixture 生成器——运行一次后可删除。
用法：
    cd E:\\AI Projects\\Vibe-Research\\backend
    ..\\.venv\\Scripts\\python.exe tests/fixtures/portfolio_advice/gen_fixtures.py
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

# 把 backend 目录加入路径
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from portfolio_advice_validator import validate_portfolio_advice

OUT_DIR = pathlib.Path(__file__).parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 共用 helper
# ---------------------------------------------------------------------------

def _ctx_holding(
    code="600519", name="贵州茅台",
    shares=1500, cost=100.0, price=110.0, weight=100.0,
):
    mv = round(price * shares, 2)
    cost_v = cost * shares
    pnl = round(mv - cost_v, 2)
    pnl_pct = round(pnl / cost_v * 100, 2) if cost_v else 0.0
    return {
        "code": code, "name": name,
        "shares": shares, "cost_price": cost, "current_price": price,
        "market_value": mv, "pnl_amount": pnl, "pnl_pct": pnl_pct,
        "holding_weight_pct": weight,
        "distance_to_cost_pct": round((price - cost) / cost * 100, 2) if cost else None,
        "quote": {}, "missing_quote_fields": [],
    }


def _context(holdings=None, status="normal", **extra):
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
            "review_metadata": {"status": status, "trade_date": "2026-07-21"},
        },
        "data_limitations": [
            "未提供账户总资产与可用现金，无法计算绝对账户仓位与具体买入金额。",
            "未提供可卖数量（sellable_shares），执行前需人工确认实际可卖股数。",
        ],
        "warnings": [],
        "account_fields_available": {
            "total_assets": False, "cash_available": False,
            "sellable_shares": False, "today_buy_shares": False, "today_sell_shares": False,
        },
    }
    base.update(extra)
    return base


def _ai_holding(
    code="600519",
    action="hold",
    confidence="high",
    size_pct=None,
    trigger=None, price_c=None, plan=None, risk=None, invalidation=None,
    limitations=None,
):
    return {
        "code": code,
        "action": action,
        "confidence": confidence,
        "execution_size_pct_of_holding": size_pct,
        "trigger_conditions": trigger or ["市场广度偏强"],
        "price_conditions": price_c or [],
        "execution_plan": plan or ["分批操作"],
        "risk_conditions": risk or ["若跌破110元止损"],
        "invalidation_conditions": invalidation or ["市场恶化不再操作"],
        "data_limitations": limitations or [],
    }


def _ai_result(holdings=None, account_action=None, status="normal", limitations=None):
    return {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-07-21T15:00:00",
        "market_status": status,
        "account_action": account_action or {"action": "hold", "reason": "市场平稳", "confidence": "high"},
        "holdings": holdings or [_ai_holding()],
        "warnings": [],
        "data_limitations": limitations or [],
    }


def _save(scenario_id: str, inp: dict, ctx: dict):
    """Run validate and save input + output."""
    output = validate_portfolio_advice(inp, ctx)
    data = {"ai_result": inp, "context": ctx}
    sid = scenario_id
    (OUT_DIR / f"{sid}_input.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / f"{sid}_expected.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  OK {sid}")


# ---------------------------------------------------------------------------
# 场景定义
# ---------------------------------------------------------------------------

def gen_all():
    print("Generating fixtures…")

    # s01 – add, high confidence, normal market
    _save("s01_add_high_conf_normal",
        _ai_result(holdings=[_ai_holding(action="add", confidence="high", size_pct=20.0)]),
        _context())

    # s02 – add, medium confidence, normal market
    _save("s02_add_medium_conf_normal",
        _ai_result(holdings=[_ai_holding(action="add", confidence="medium", size_pct=20.0)]),
        _context())

    # s03 – add, low confidence, normal market (only 10% allowed by conf cap)
    _save("s03_add_low_conf_normal",
        _ai_result(holdings=[_ai_holding(action="add", confidence="low", size_pct=10.0)]),
        _context())

    # s04 – add, high confidence, partial market (only 10% allowed in partial)
    _save("s04_add_high_conf_partial",
        _ai_result(holdings=[_ai_holding(action="add", confidence="high", size_pct=10.0)]),
        _context(status="partial"))

    # s05 – reduce, high confidence, normal market (30% allowed)
    _save("s05_reduce_high_conf_normal",
        _ai_result(holdings=[_ai_holding(action="reduce", confidence="high", size_pct=30.0,
                                         invalidation=["价格回升后重新评估"])]),
        _context())

    # s06 – reduce, medium confidence, normal market
    _save("s06_reduce_medium_conf_normal",
        _ai_result(holdings=[_ai_holding(action="reduce", confidence="medium", size_pct=20.0,
                                         invalidation=["价格回升后重新评估"])]),
        _context())

    # s07 – reduce, low confidence, partial market (only 10% allowed)
    _save("s07_reduce_low_conf_partial",
        _ai_result(holdings=[_ai_holding(action="reduce", confidence="low", size_pct=10.0,
                                         invalidation=["价格回升后重新评估"])]),
        _context(status="partial"))

    # s08 – sell action (fixed 100%)
    _save("s08_sell_action",
        _ai_result(holdings=[_ai_holding(action="sell", confidence="high", size_pct=None,
                                         trigger=["基本面恶化"],
                                         invalidation=["若行情反转重新评估"])]),
        _context())

    # s09 – hold action
    _save("s09_hold_action",
        _ai_result(holdings=[_ai_holding(action="hold", confidence="medium")]),
        _context())

    # s10 – watch action
    _save("s10_watch_action",
        _ai_result(holdings=[_ai_holding(action="watch", confidence="low")]),
        _context())

    # s11 – avoid action
    _save("s11_avoid_action",
        _ai_result(holdings=[_ai_holding(action="avoid", confidence="low")]),
        _context())

    # s12 – 模型 action 置信度为 low 时规范化
    _save("s12_low_conf_normalized",
        _ai_result(holdings=[_ai_holding(action="hold", confidence="unknown")]),
        _context())

    # s13 – invalid account_action → fallback to hold
    _save("s13_invalid_account_action_fallback",
        _ai_result(
            holdings=[_ai_holding()],
            account_action={"action": "all_in", "reason": "行情很好", "confidence": "high"},
        ),
        _context())

    # s14 – model misses a holding → auto-fill watch
    h1 = _ctx_holding(code="600519", name="贵州茅台", shares=1500, cost=100.0, price=110.0, weight=60.0)
    h2 = _ctx_holding(code="000001", name="平安银行", shares=3000, cost=12.0, price=14.0, weight=40.0)
    _save("s14_model_missing_holding",
        _ai_result(holdings=[_ai_holding(code="600519")]),
        _context(holdings=[h1, h2]))

    # s15 – add, no shares data (shares=0)
    h_no_shares = _ctx_holding(shares=0)
    _save("s15_add_no_shares_data",
        _ai_result(holdings=[_ai_holding(action="add", confidence="high", size_pct=20.0)]),
        _context(holdings=[h_no_shares]))

    # s16 – add, no price data (price=0)
    h_no_price = _ctx_holding(price=0.0, weight=0.0)
    h_no_price["market_value"] = 0.0
    h_no_price["pnl_amount"] = 0.0
    h_no_price["pnl_pct"] = 0.0
    _save("s16_add_no_price_data",
        _ai_result(holdings=[_ai_holding(
            action="add", confidence="high", size_pct=20.0,
            risk=["若市场趋势恶化则止损"],
        )]),
        _context(holdings=[h_no_price]))

    # s17 – add insufficient lot (shares=10, 20% = 2, which < 100)
    h_small = _ctx_holding(shares=10, cost=100.0, price=110.0, weight=100.0)
    h_small["market_value"] = round(10 * 110.0, 2)
    h_small["pnl_amount"] = round(10 * 110.0 - 10 * 100.0, 2)
    _save("s17_add_insufficient_lot",
        _ai_result(holdings=[_ai_holding(
            action="add", confidence="high", size_pct=20.0,
            risk=["若市场趋势恶化则止损"],
        )]),
        _context(holdings=[h_small]))

    # s18 – account_action: selective_add (valid non-hold)
    _save("s18_account_action_selective_add",
        _ai_result(
            holdings=[_ai_holding()],
            account_action={"action": "selective_add", "reason": "板块分化，精选龙头", "confidence": "medium"},
        ),
        _context())

    # s19 – account_action: defensive
    _save("s19_account_action_defensive",
        _ai_result(
            holdings=[_ai_holding()],
            account_action={"action": "defensive", "reason": "市场走弱，防御为主", "confidence": "low"},
        ),
        _context())

    # s20 – account_action: reduce_risk
    _save("s20_account_action_reduce_risk",
        _ai_result(
            holdings=[_ai_holding()],
            account_action={"action": "reduce_risk", "reason": "尾部风险升高", "confidence": "medium"},
        ),
        _context())

    # s21 – sell with large shares (qty floored to lot)
    h_large = _ctx_holding(shares=1523, cost=100.0, price=110.0, weight=100.0)
    h_large["market_value"] = round(1523 * 110.0, 2)
    h_large["pnl_amount"] = round(1523 * 110.0 - 1523 * 100.0, 2)
    _save("s21_sell_qty_floor_to_lot",
        _ai_result(holdings=[_ai_holding(action="sell", confidence="high",
                                         trigger=["基本面恶化"], invalidation=["若反转重新评估"])]),
        _context(holdings=[h_large]))

    # s22 – reduce, low confidence, normal: only 10% allowed by conf cap
    _save("s22_reduce_low_conf_cap",
        _ai_result(holdings=[_ai_holding(action="reduce", confidence="low", size_pct=10.0,
                                         invalidation=["价格回升后重新评估"])]),
        _context())

    # s23 – multi-holding portfolio_summary recomputed
    ha = _ctx_holding(code="600519", name="贵州茅台", shares=1500, cost=100.0, price=110.0, weight=60.0)
    hb = _ctx_holding(code="000858", name="五粮液", shares=2000, cost=150.0, price=160.0, weight=40.0)
    _save("s23_multi_holding_summary",
        _ai_result(holdings=[
            _ai_holding(code="600519", action="hold"),
            _ai_holding(code="000858", action="hold"),
        ]),
        _context(holdings=[ha, hb]))

    # s24 – data_limitations normalization and dedup
    ai = _ai_result(holdings=[_ai_holding(action="add", confidence="medium", size_pct=20.0,
                                           limitations=[
                                               "未提供账户总资产",
                                               "未提供可卖数量（sellable_shares），执行前需人工确认实际可卖股数。",
                                           ])])
    _save("s24_limitation_normalization", ai, _context())

    # s25 – add with 10% in normal market (valid tier)
    _save("s25_add_10pct_normal",
        _ai_result(holdings=[_ai_holding(action="add", confidence="medium", size_pct=10.0)]),
        _context())

    # s26 – reduce 10% in partial market (valid)
    _save("s26_reduce_10pct_partial",
        _ai_result(holdings=[_ai_holding(action="reduce", confidence="medium", size_pct=10.0,
                                         invalidation=["价格回升后重新评估"])]),
        _context(status="partial"))

    # s27 – reduce with shares=1523, qty floor-to-lot
    _save("s27_reduce_qty_floor_to_lot",
        _ai_result(holdings=[_ai_holding(action="reduce", confidence="high", size_pct=30.0,
                                         invalidation=["价格回升后重新评估"])]),
        _context(holdings=[h_large]))

    print(f"\nDone. Fixtures written to: {OUT_DIR}")


if __name__ == "__main__":
    gen_all()
