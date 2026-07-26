"""持仓建议 sellable_quantity_advisory 纯函数与服务集成测试。"""

from __future__ import annotations

import json

import account_profile
import astock
import daily_review
import portfolio as pf
import portfolio_advice_service
import pytest
from portfolio_advice_sellable import (
    _LIMITATION_ADVISORY,
    apply_sellable_quantity_advisory,
)


def _base_result(*, holdings: list[dict], trade_date: str | None = "2026-01-01") -> dict:
    return {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-01-01 10:00:00",
        "trade_date": trade_date,
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
    }


def _holding(
    code: str = "000001",
    *,
    action: str = "reduce",
    shares: int = 1000,
    qty: int | None = 300,
) -> dict:
    return {
        "code": code,
        "name": f"股票{code}",
        "shares": shares,
        "cost_price": 14.0,
        "current_price": 10.0,
        "market_value": shares * 10.0,
        "pnl_amount": -4000.0,
        "pnl_pct": -28.57,
        "holding_weight_pct": 100.0,
        "action": action,
        "execution_size_pct_of_holding": 30 if action in ("reduce", "sell") else None,
        "execution_quantity": qty,
        "estimated_amount": None,
        "trigger_conditions": [],
        "price_conditions": [],
        "execution_plan": [],
        "risk_conditions": [],
        "invalidation_conditions": [],
        "confidence": "high",
        "data_limitations": [],
    }


def test_reduce_advisory_min_qty_and_shares() -> None:
    h = _holding(action="reduce", shares=1000, qty=300)
    res = apply_sellable_quantity_advisory(
        _base_result(holdings=[h]),
        {"holdings": [{"code": "000001", "shares": 1000, "cost": 14.0}], "closed": []},
    )
    out = res["holdings"][0]
    assert out["execution_quantity"] == 300  # 不修改
    assert out["sellable_quantity_advisory"] == 300
    assert _LIMITATION_ADVISORY in res["data_limitations"]
    # 理论建议卖出数量（非券商可卖数量）——不得仅写「可卖数量」
    assert "理论建议卖出数量" in _LIMITATION_ADVISORY
    assert "非券商可卖" in _LIMITATION_ADVISORY


def test_sell_advisory_caps_at_shares() -> None:
    h = _holding(action="sell", shares=500, qty=800)
    res = apply_sellable_quantity_advisory(_base_result(holdings=[h]), {"closed": []})
    out = res["holdings"][0]
    assert out["execution_quantity"] == 800
    assert out["sellable_quantity_advisory"] == 500


def test_null_execution_quantity_yields_null_advisory() -> None:
    h = _holding(action="reduce", shares=1000, qty=None)
    res = apply_sellable_quantity_advisory(_base_result(holdings=[h]), None)
    out = res["holdings"][0]
    assert out["execution_quantity"] is None
    assert out["sellable_quantity_advisory"] is None
    assert _LIMITATION_ADVISORY in res["data_limitations"]


def test_hold_add_no_advisory_field() -> None:
    hold = _holding(action="hold", qty=None)
    add = _holding(code="000002", action="add", qty=100)
    res = apply_sellable_quantity_advisory(
        _base_result(holdings=[hold, add]),
        {"closed": []},
    )
    assert "sellable_quantity_advisory" not in res["holdings"][0]
    assert "sellable_quantity_advisory" not in res["holdings"][1]
    assert _LIMITATION_ADVISORY not in res["data_limitations"]


def test_top_limitation_deduped() -> None:
    h = _holding(action="reduce", shares=1000, qty=100)
    base = _base_result(holdings=[h])
    base["data_limitations"] = [_LIMITATION_ADVISORY]
    res = apply_sellable_quantity_advisory(base, {"closed": []})
    assert res["data_limitations"].count(_LIMITATION_ADVISORY) == 1


def test_same_day_closed_still_advisory_not_pretend_precise() -> None:
    """当日 closed 同 code：仍给 min(qty,H)，并写顶层 limitation（不假装精确）。"""
    h = _holding(code="600519", action="reduce", shares=1000, qty=400)
    portfolio = {
        "holdings": [{"code": "600519", "shares": 1000, "cost": 1600.0}],
        "closed": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "date": "2026-01-01",
                "price": 1600.0,
                "shares": 100,
                "cost": 1500.0,
                "pnl": 10000.0,
            }
        ],
    }
    res = apply_sellable_quantity_advisory(
        _base_result(holdings=[h], trade_date="2026-01-01"),
        portfolio,
    )
    out = res["holdings"][0]
    assert out["execution_quantity"] == 400
    assert out["sellable_quantity_advisory"] == 400
    assert _LIMITATION_ADVISORY in res["data_limitations"]


def test_closed_other_day_same_formula() -> None:
    h = _holding(action="sell", shares=200, qty=200)
    portfolio = {
        "closed": [
            {
                "code": "000001",
                "date": "2025-12-31",
                "price": 10.0,
                "shares": 100,
                "cost": 9.0,
                "pnl": 100.0,
            }
        ],
    }
    res = apply_sellable_quantity_advisory(
        _base_result(holdings=[h], trade_date="2026-01-01"),
        portfolio,
    )
    assert res["holdings"][0]["sellable_quantity_advisory"] == 200


def test_facts_shares_preferred_when_present() -> None:
    h = _holding(action="reduce", shares=9999, qty=500)
    h["facts"] = {"shares": 800}
    res = apply_sellable_quantity_advisory(_base_result(holdings=[h]), {})
    assert res["holdings"][0]["sellable_quantity_advisory"] == 500  # min(500, 800)


def test_invalid_result_passthrough() -> None:
    assert apply_sellable_quantity_advisory("bad") == "bad"  # type: ignore[arg-type]
    bare = {"schema_version": "portfolio-advice-v0.1"}
    assert apply_sellable_quantity_advisory(bare) is bare


# ---------------------------------------------------------------------------
# 服务集成
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(account_profile, "ACCOUNT_FILE", str(tmp_path / "account_profile.json"))
    monkeypatch.setattr(
        portfolio_advice_service.ai_result_service,
        "save_portfolio_advice",
        lambda *_a, **_k: {"trade_date": "2026-01-01"},
    )

    def mock_quote(codes):
        return {c: {"name": f"股票{c}", "price": 10.0} for c in codes}

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


def _write_pf(tmp_path, holdings: list[dict], closed: list[dict] | None = None) -> None:
    with open(tmp_path / "portfolio.json", "w", encoding="utf-8") as f:
        json.dump(
            {"holdings": holdings, "closed": closed or [], "last_refresh": None},
            f,
        )


def _mock_reduce_runner(_cfg, _messages):
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
                    "action": "reduce",
                    "execution_size_pct_of_holding": 20,
                    "execution_quantity": None,
                    "estimated_amount": None,
                    "trigger_conditions": ["高位震荡"],
                    "price_conditions": ["跌破支撑"],
                    "execution_plan": ["执行前确认实际可卖数量，并按计划数量执行"],
                    "risk_conditions": ["反弹不及预期"],
                    "invalidation_conditions": ["重新站上均线"],
                    "confidence": "medium",
                    "data_limitations": [],
                }
            ],
            "warnings": [],
            "data_limitations": [],
        }
    )


def test_service_reduce_gets_sellable_advisory(tmp_env) -> None:
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])
    res = portfolio_advice_service.generate_portfolio_advice(
        {},
        model_runner=_mock_reduce_runner,
    )
    h = res["holdings"][0]
    assert h["action"] == "reduce"
    # validator 会按 20% * 1500 重算 quantity（整手）
    assert h["execution_quantity"] is not None
    assert h["sellable_quantity_advisory"] == min(h["execution_quantity"], h["shares"])
    assert h["sellable_quantity_advisory"] <= h["shares"]
    assert any("理论建议卖出数量" in m for m in res["data_limitations"])
    assert any("非券商可卖" in m for m in res["data_limitations"])
    # advisory 语义：非真实券商可卖 / 无 T+1
    assert any("T+1" in m for m in res["data_limitations"])


def test_advisory_field_semantics_not_broker_sellable() -> None:
    """sellable_quantity_advisory 字段语义 = 理论建议，非券商可卖。"""
    h = _holding(action="sell", shares=400, qty=500)
    res = apply_sellable_quantity_advisory(_base_result(holdings=[h]), {"closed": []})
    out = res["holdings"][0]
    # 公式 min(qty, shares)，无 T+1 扣减
    assert out["sellable_quantity_advisory"] == 400
    assert out["execution_quantity"] == 500  # 不改 execution
    lim = " ".join(res["data_limitations"])
    assert "理论建议卖出数量" in lim
    assert "非券商可卖" in lim
    # 不得暗示已是券商真实可卖（limitation 应含否定语义）
    assert "非券商可卖数量" in lim or "非券商可卖" in lim
