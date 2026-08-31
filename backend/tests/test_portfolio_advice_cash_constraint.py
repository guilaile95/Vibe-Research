"""持仓建议加仓可用现金约束纯函数与服务集成测试。

语义：
- spendable = available_cash * 0.9 为「可用现金安全垫」，非总资产 10%。
- 未配置账户 + add：qty/amount 置 null。
- 多笔 add：不按模型顺序静默分配，全部 null。
"""

from __future__ import annotations

import json

import account_profile
import astock
import daily_review
import portfolio as pf
import portfolio_advice_cash_constraint as cash_constraint
import portfolio_advice_service
import pytest
from portfolio_advice_cash_constraint import apply_available_cash_constraints
from portfolio_advice_policy import CASH_RESERVE_PCT, POLICY


def _base_result(
    *,
    holdings: list[dict],
    cash: float | None,
    configured: bool = True,
    canonical: bool = True,
) -> dict:
    funding: dict
    if configured and cash is not None:
        funding = {
            "configured": True,
            "canonical": canonical,
            "total_assets": 100000.0,
            "available_cash": cash,
            "available_cash_pct": round(cash / 100000.0 * 100, 2),
            "updated_at": "2026-01-01 10:00:00",
            "tracked_stock_market_value": 15000.0,
            "tracked_stock_weight_pct": 15.0,
            "quote_coverage": {
                "valid_holdings": len(holdings),
                "total_holdings": len(holdings),
                "complete": True,
            },
        }
    else:
        funding = {
            "configured": False,
            "canonical": False,
            "total_assets": None,
            "available_cash": None,
            "available_cash_pct": None,
            "updated_at": None,
            "tracked_stock_market_value": None,
            "tracked_stock_weight_pct": None,
            "quote_coverage": {
                "valid_holdings": len(holdings),
                "total_holdings": len(holdings),
                "complete": True,
            },
        }
    return {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-01-01 10:00:00",
        "market_status": "normal",
        "portfolio_summary": {
            "holding_count": len(holdings),
            "market_value": 15000.0,
            "cost": 21000.0,
            "pnl": -6000.0,
            "pnl_pct": -28.57,
        },
        "account_action": {"action": "hold", "reason": "稳健", "confidence": "high"},
        "holdings": holdings,
        "warnings": [],
        "data_limitations": [],
        "account_funding": funding,
    }


def _add_holding(
    code: str = "000001",
    *,
    qty: int | None = 100,
    amount: float | None = 1000.0,
    price: float | None = 10.0,
    shares: int = 1500,
) -> dict:
    return {
        "code": code,
        "name": f"股票{code}",
        "shares": shares,
        "cost_price": 14.0,
        "current_price": price,
        "market_value": shares * (price or 0),
        "pnl_amount": -6000.0,
        "pnl_pct": -28.57,
        "holding_weight_pct": 100.0,
        "action": "add",
        "execution_size_pct_of_holding": 10,
        "execution_quantity": qty,
        "estimated_amount": amount,
        "trigger_conditions": [],
        "price_conditions": [],
        "execution_plan": [],
        "risk_conditions": [],
        "invalidation_conditions": [],
        "confidence": "high",
        "data_limitations": [],
        "account_metrics": {"market_value": shares * (price or 0), "account_weight_pct": 15.0},
    }


def test_policy_cash_reserve_is_available_cash_pad_not_total_assets() -> None:
    """安全垫是可用现金比例，不是总资产 10%。"""
    assert CASH_RESERVE_PCT == 0.10
    assert POLICY.cash_reserve_pct == 0.10
    # 注释/常量语义：1 - reserve = 90% 可用现金可花
    assert abs((1.0 - CASH_RESERVE_PCT) - 0.9) < 1e-9


def test_cash_sufficient_unchanged() -> None:
    """单笔 add，现金充足：数量/金额/action 均不变。"""
    # usable = 20000 * 0.9 = 18000 > 1000
    h = _add_holding(qty=100, amount=1000.0, price=10.0)
    res = apply_available_cash_constraints(
        _base_result(holdings=[h], cash=20000.0)
    )
    out = res["holdings"][0]
    assert out["action"] == "add"
    assert out["execution_quantity"] == 100
    assert out["estimated_amount"] == 1000.0
    assert out["execution_size_pct_of_holding"] == 10
    assert not any("现金" in m for m in out["data_limitations"])
    assert not any("现金" in m for m in res["data_limitations"])


def test_cash_insufficient_floor_to_lot() -> None:
    """单笔 add，现金不足：按现价向下取整到整手，并说明已下调。"""
    # usable = 2000 * 0.9 = 1800；原 300 股 * 10 = 3000 > 1800 → max 100 股
    h = _add_holding(qty=300, amount=3000.0, price=10.0)
    res = apply_available_cash_constraints(
        _base_result(holdings=[h], cash=2000.0)
    )
    out = res["holdings"][0]
    assert out["action"] == "add"
    assert out["execution_quantity"] == 100
    assert out["estimated_amount"] == 1000.0
    assert out["execution_size_pct_of_holding"] == 10
    assert any("下调" in m for m in out["data_limitations"])


def test_cash_too_low_clears_quantity() -> None:
    """单笔 add，现金过少：不足一手时清空数量与金额，保留 action=add。"""
    # usable = 500 * 0.9 = 450 < 10*100 → 无法形成 100 股
    h = _add_holding(qty=100, amount=1000.0, price=10.0)
    res = apply_available_cash_constraints(
        _base_result(holdings=[h], cash=500.0)
    )
    out = res["holdings"][0]
    assert out["action"] == "add"
    assert out["execution_quantity"] is None
    assert out["estimated_amount"] is None
    assert out["execution_size_pct_of_holding"] == 10
    assert any("可用现金不足" in m for m in out["data_limitations"])


def test_corrupted_execution_policy_add_nulls_executable_qty(tmp_path, monkeypatch) -> None:
    """损坏策略不使用默认 lot/reserve，add 数量与金额 fail closed。"""
    policy_file = tmp_path / "account_execution_policy.json"
    original = b"{broken"
    policy_file.write_bytes(original)
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    h = _add_holding(qty=300, amount=3000.0, price=10.0)

    res = apply_available_cash_constraints(_base_result(holdings=[h], cash=5000.0))

    out = res["holdings"][0]
    assert out["action"] == "add"
    assert out["execution_quantity"] is None
    assert out["estimated_amount"] is None
    assert res["execution_policy"] == {
        "status": "corrupted",
        "reason_code": "ACCOUNT_EXECUTION_POLICY_CORRUPTED",
    }
    assert any("账户执行策略文件读取失败或损坏" in item for item in res["data_limitations"])
    assert policy_file.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupted_execution_policy_multi_add_nulls_all_executables(tmp_path, monkeypatch) -> None:
    """损坏策略下多笔 add 不按默认策略分配，全部数量与金额 fail closed。"""
    policy_file = tmp_path / "account_execution_policy.json"
    policy_file.write_bytes(b"{broken")
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))

    res = apply_available_cash_constraints(
        _base_result(
            holdings=[
                _add_holding("000001", qty=200, amount=2000.0, price=10.0),
                _add_holding("000002", qty=300, amount=3000.0, price=10.0),
            ],
            cash=5000.0,
        )
    )

    assert [item["action"] for item in res["holdings"]] == ["add", "add"]
    assert all(item["execution_quantity"] is None for item in res["holdings"])
    assert all(item["estimated_amount"] is None for item in res["holdings"])
    assert res["execution_policy"] == {
        "status": "corrupted",
        "reason_code": "ACCOUNT_EXECUTION_POLICY_CORRUPTED",
    }


def test_unconfigured_account_add_nulls_executable_qty() -> None:
    """未配置账户 + add：action 保留，execution_quantity/estimated_amount 必须 null。"""
    h = _add_holding(qty=100, amount=1000.0, price=10.0)
    res = apply_available_cash_constraints(
        _base_result(holdings=[h], cash=None, configured=False)
    )
    out = res["holdings"][0]
    assert out["action"] == "add"
    assert out["execution_quantity"] is None
    assert out["estimated_amount"] is None
    assert out["execution_size_pct_of_holding"] == 10  # 方向性参考保留
    assert any("未配置账户资金" in m for m in res["data_limitations"])
    assert res["data_limitations"].count(
        cash_constraint._LIMITATION_UNCONFIGURED
    ) == 1


def test_configured_noncanonical_account_nulls_add_but_not_reduce() -> None:
    add = _add_holding(qty=100, amount=1000.0, price=10.0)
    reduce = _add_holding(code="600519", qty=100, amount=160000.0, price=1600.0)
    reduce["action"] = "reduce"

    res = apply_available_cash_constraints(
        _base_result(
            holdings=[add, reduce],
            cash=20000.0,
            canonical=False,
        )
    )

    assert res["holdings"][0]["action"] == "add"
    assert res["holdings"][0]["execution_quantity"] is None
    assert res["holdings"][0]["estimated_amount"] is None
    assert res["holdings"][1]["action"] == "reduce"
    assert res["holdings"][1]["execution_quantity"] == 100
    assert cash_constraint._LIMITATION_ACCOUNT_NOT_CANONICAL in res["data_limitations"]


def test_multiple_adds_do_not_silent_allocate_by_order() -> None:
    """多笔 add：不按 holdings 顺序静默瓜分现金，全部 qty/amount 置 null。"""
    h1 = _add_holding("000001", qty=200, amount=2000.0, price=10.0)
    h2 = _add_holding("000002", qty=300, amount=3000.0, price=10.0)
    h3 = _add_holding("000003", qty=150, amount=1500.0, price=10.0)
    res = apply_available_cash_constraints(
        _base_result(holdings=[h1, h2, h3], cash=5000.0)
    )
    a, b, c = res["holdings"]
    assert a["action"] == b["action"] == c["action"] == "add"
    assert a["execution_quantity"] is None
    assert a["estimated_amount"] is None
    assert b["execution_quantity"] is None
    assert b["estimated_amount"] is None
    assert c["execution_quantity"] is None
    assert c["estimated_amount"] is None
    # 方向性比例仍保留
    assert a["execution_size_pct_of_holding"] == 10
    assert b["execution_size_pct_of_holding"] == 10
    assert c["execution_size_pct_of_holding"] == 10
    assert cash_constraint._LIMITATION_MULTI_ADD in res["data_limitations"]
    assert any("多个加仓方向" in m for m in res["data_limitations"])
    assert any("资金分配优先级" in m for m in res["data_limitations"])


def test_non_add_actions_untouched() -> None:
    """非 add 动作不受现金约束影响。"""
    hold = _add_holding(qty=None, amount=None)
    hold["action"] = "hold"
    hold["execution_size_pct_of_holding"] = None
    reduce = _add_holding(code="600519", qty=100, amount=160000.0, price=1600.0)
    reduce["action"] = "reduce"
    reduce["execution_size_pct_of_holding"] = 10
    res = apply_available_cash_constraints(
        _base_result(holdings=[hold, reduce], cash=100.0)
    )
    assert res["holdings"][0]["action"] == "hold"
    assert res["holdings"][1]["action"] == "reduce"
    assert res["holdings"][1]["execution_quantity"] == 100
    assert res["holdings"][1]["estimated_amount"] == 160000.0
    assert res["data_limitations"] == []


def test_exact_boundary_uses_full_usable() -> None:
    """单笔 add：estimated_amount 恰好等于 remaining usable 时不动。"""
    # usable = 10000 * 0.9 = 9000；amount=9000 → 不动
    h = _add_holding(qty=900, amount=9000.0, price=10.0)
    res = apply_available_cash_constraints(
        _base_result(holdings=[h], cash=10000.0)
    )
    out = res["holdings"][0]
    assert out["execution_quantity"] == 900
    assert out["estimated_amount"] == 9000.0
    assert out["data_limitations"] == []


def test_reserve_is_of_available_cash_not_total_assets() -> None:
    """可用额度 = 可用现金 * 0.9，与 total_assets 无关（非总资产 10%）。"""
    # cash=1000 → usable=900；amount=1000 → 下调
    # 若错误按 total_assets*0.1=10000 则会错误地通过
    h = _add_holding(qty=100, amount=1000.0, price=10.0)
    res = apply_available_cash_constraints(
        _base_result(holdings=[h], cash=1000.0)
    )
    out = res["holdings"][0]
    # usable 900 / 10 = 90 股 < 一手 → null
    assert out["execution_quantity"] is None
    assert out["estimated_amount"] is None


# ---------------------------------------------------------------------------
# 服务集成
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(account_profile, "ACCOUNT_FILE", str(tmp_path / "account_profile.json"))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(tmp_path / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        portfolio_advice_service.ai_result_service,
        "save_portfolio_advice",
        lambda *_a, **_k: {"trade_date": "2026-01-01"},
    )

    def mock_quote(codes):
        q = {}
        for c in codes:
            if c == "000001":
                q[c] = {"name": "平安银行", "price": 10.0}
            else:
                q[c] = {"name": f"股票{c}", "price": 20.0}
        return q

    monkeypatch.setattr(astock, "tencent_quote", mock_quote)
    monkeypatch.setattr(
        daily_review,
        "generate_daily_review",
        lambda: {
            "status": "normal",
            "trade_date": "2026-01-01",
            "generated_at": "2026-01-01 15:00:00",
            "data_health": {"components": {"breadth": "normal"}},
            "market_environment": {"breadth": {"status": "normal"}},
        },
    )
    return tmp_path


def _write_pf(tmp_path, holdings: list[dict]) -> None:
    with open(tmp_path / "portfolio.json", "w", encoding="utf-8") as f:
        json.dump({"holdings": holdings, "last_refresh": None}, f)


def _mock_runner(_cfg, _messages):
    return json.dumps(
        {
            "schema_version": "portfolio-advice-v0.1",
            "generated_at": "2026-01-01 10:00:00",
            "market_status": "normal",
            "portfolio_summary": {
                "holding_count": 1,
                "market_value": 15000.0,
                "cost": 21000.0,
                "pnl": -6000.0,
                "pnl_pct": -28.57,
            },
            "account_action": {
                "action": "hold",
                "reason": "稳健持仓",
                "confidence": "high",
            },
            "holdings": [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "shares": 1500,
                    "cost_price": 14.0,
                    "current_price": 10.0,
                    "market_value": 15000.0,
                    "pnl_amount": -6000.0,
                    "pnl_pct": -28.57,
                    "holding_weight_pct": 100.0,
                    "action": "add",
                    "execution_size_pct_of_holding": 10,
                    "execution_quantity": 100,
                    "estimated_amount": 1000.0,
                    "trigger_conditions": ["调整到位"],
                    "price_conditions": ["突破前高"],
                    "execution_plan": ["分批建仓"],
                    "risk_conditions": ["大盘调整"],
                    "invalidation_conditions": ["破位"],
                    "confidence": "high",
                    "data_limitations": [],
                }
            ],
            "warnings": [],
            "data_limitations": [],
        }
    )


def test_service_cash_5000_add_1000_unchanged(tmp_env, monkeypatch) -> None:
    """回归：cash=5000 usable=4500 > 1000，服务端数量不变。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])
    monkeypatch.setattr(
        portfolio_advice_service.account_reality_service,
        "get_account_reality",
        lambda: {
            "canonical": True,
            "canonical_reason_codes": [],
            "account_authority": {"state": "CANONICAL"},
            "account_total_assets": {"current_fact": {"value": 100000.0}},
            "cash": {"current_fact": {"value": 5000.0}},
        },
    )
    res = portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)
    h = res["holdings"][0]
    assert h["action"] == "add"
    assert h["execution_quantity"] == 100
    assert h["estimated_amount"] == 1000.0


def test_service_unconfigured_nulls_add_qty(tmp_env) -> None:
    """服务集成：未配置账户时 add 可执行数量/金额为 null。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])
    res = portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)
    h = res["holdings"][0]
    assert h["action"] == "add"
    assert h["execution_quantity"] is None
    assert h["estimated_amount"] is None
    assert h["execution_size_pct_of_holding"] == 10
    assert any("未配置账户资金" in m for m in res["data_limitations"])
    assert any("无法形成可执行加仓数量" in m for m in res["data_limitations"])
