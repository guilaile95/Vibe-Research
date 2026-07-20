"""portfolio_advice_prompt 纯函数提示词契约离线测试（不联网、不调模型）。"""
from __future__ import annotations

import json

import pytest

from portfolio_advice_prompt import (
    ACTIONS,
    ACCOUNT_ACTIONS,
    SCHEMA_VERSION,
    build_portfolio_advice_messages,
    build_portfolio_advice_system_prompt,
    build_portfolio_advice_user_prompt,
    _DEFAULT_USER_TASK,
)


def _sample_context() -> str:
    return json.dumps(
        {
            "schema_version": "portfolio-advice-context-v0.1",
            "portfolio_summary": {
                "holding_count": 1,
                "market_value": 10000,
                "cost": 9000,
                "pnl": 1000,
                "pnl_pct": 11.11,
            },
            "holdings": [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "shares": 1000,
                    "cost_price": 9.0,
                    "current_price": 10.0,
                    "market_value": 10000,
                    "pnl_amount": 1000,
                    "pnl_pct": 11.11,
                    "holding_weight_pct": 100.0,
                }
            ],
            "data_limitations": ["未提供可卖数量"],
            "account_fields_available": {
                "total_assets": False,
                "cash_available": False,
                "sellable_shares": False,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def test_system_prompt_action_enum():
    p = build_portfolio_advice_system_prompt()
    for a in ACTIONS:
        assert a in p
    assert "add" in p and "reduce" in p and "t_trade" in p and "avoid" in p


def test_system_prompt_forbids_vague_only():
    p = build_portfolio_advice_system_prompt()
    assert "谨慎持有" in p
    assert "控制仓位" in p
    assert "禁止" in p or "不得" in p


def test_system_prompt_quantity_rules():
    p = build_portfolio_advice_system_prompt()
    assert "execution_quantity" in p
    assert "可卖" in p
    assert "做 T" in p or "t_trade" in p
    assert "quantity 必须为 null" in p or "quantity" in p
    assert "无法计算具体买入股数" in p or "可用现金" in p
    assert "不得默认" in p or "全部" in p


def test_system_prompt_no_fabricated_catalyst():
    p = build_portfolio_advice_system_prompt()
    assert "催化" in p or "公告" in p
    assert "资金净流入" in p or "不得把成交额" in p


def test_system_prompt_market_context_rules():
    p = build_portfolio_advice_system_prompt()
    assert "广度" in p
    assert "不得仅根据" in p or "浮动盈亏" in p or "浮盈" in p


def test_system_prompt_json_schema():
    p = build_portfolio_advice_system_prompt()
    assert SCHEMA_VERSION in p
    assert "portfolio_summary" in p
    assert "account_action" in p
    assert "holding_weight_pct" in p
    assert "invalidation_conditions" in p
    for a in ACCOUNT_ACTIONS:
        assert a in p


def test_user_prompt_embeds_context_raw():
    ctx = _sample_context()
    user = build_portfolio_advice_user_prompt(ctx)
    assert ctx in user
    assert "<PORTFOLIO_ADVICE_CONTEXT>" in user
    assert "</PORTFOLIO_ADVICE_CONTEXT>" in user
    assert _DEFAULT_USER_TASK in user


def test_user_prompt_custom_request():
    ctx = _sample_context()
    user = build_portfolio_advice_user_prompt(ctx, user_request="重点看减仓")
    assert "重点看减仓" in user
    assert ctx in user


def test_user_prompt_empty_request_falls_back():
    ctx = _sample_context()
    user = build_portfolio_advice_user_prompt(ctx, user_request="   ")
    assert _DEFAULT_USER_TASK in user


def test_user_prompt_invalid_context():
    with pytest.raises(TypeError):
        build_portfolio_advice_user_prompt(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_portfolio_advice_user_prompt("")
    with pytest.raises(ValueError):
        build_portfolio_advice_user_prompt("not-json")
    with pytest.raises(ValueError):
        build_portfolio_advice_user_prompt("[1,2,3]")


def test_messages_shape():
    msgs = build_portfolio_advice_messages(_sample_context())
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert msgs[0]["content"] == build_portfolio_advice_system_prompt()


def test_deterministic_prompts():
    ctx = _sample_context()
    assert build_portfolio_advice_system_prompt() == build_portfolio_advice_system_prompt()
    assert build_portfolio_advice_user_prompt(ctx) == build_portfolio_advice_user_prompt(ctx)
    assert build_portfolio_advice_messages(ctx) == build_portfolio_advice_messages(ctx)
