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
    assert "add" in p and "reduce" in p and "avoid" in p
    assert "t_trade" not in ACTIONS
    # 枚举列表中不得作为合法动作出现
    assert '"action": "add|hold|reduce|sell|watch|avoid"' in p
    assert "t_trade" not in p.split("只能使用：")[1].split("禁止")[0]


def test_actions_exclude_t_trade():
    assert "t_trade" not in ACTIONS
    assert set(ACTIONS) == {"add", "hold", "reduce", "sell", "watch", "avoid"}


def test_system_prompt_forbids_t_trade():
    p = build_portfolio_advice_system_prompt()
    assert "不支持做 T" in p or "禁止" in p
    assert "做 T" in p or "做T" in p
    assert "先卖后买" in p
    assert "先买后卖" in p
    assert "高抛低吸" in p
    assert "盘中滚动仓位" in p
    assert "不得输出 t_trade" in p or "禁止：做 T" in p


def test_system_prompt_forbids_vague_only():
    p = build_portfolio_advice_system_prompt()
    assert "谨慎持有" in p
    assert "控制仓位" in p
    assert "禁止" in p or "不得" in p


def test_system_prompt_quantity_rules():
    p = build_portfolio_advice_system_prompt()
    assert "execution_quantity" in p
    assert "可卖" in p
    assert "无法计算具体买入股数" in p or "可用现金" in p
    assert "不得默认" in p or "全部" in p
    # 不得再要求做 T quantity 规则
    assert "### t_trade" not in p


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
    # 输出结构不得含 t_trade 对象
    assert '"t_trade"' not in p


def test_system_prompt_requires_json_only_response():
    """Prompt 与 parser 契约：整个响应只能是一个 JSON 对象。"""
    p = build_portfolio_advice_system_prompt()
    assert "整个响应只能包含一个合法 JSON 对象" in p
    assert "第一个非空字符必须是 {" in p
    assert "最后一个非空字符必须是 }" in p
    assert "不要使用 Markdown 代码块" in p
    assert "不要在 JSON 前后输出任何说明" in p
    # 结论写在 JSON 字段内，不得另写 Markdown
    assert "account_action.reason" in p
    assert "不得另写 Markdown" in p or "禁止：Markdown" in p


def test_system_prompt_forbids_trailing_markdown_and_prose():
    p = build_portfolio_advice_system_prompt()
    # 旧「可选 Markdown / 附加摘要」指令必须移除
    assert "可选 Markdown" not in p
    assert "可在 JSON 之后" not in p
    assert "附简短 Markdown" not in p
    assert "可附带 Markdown" not in p
    assert "Markdown 摘要" in p  # 出现在禁止条款中
    assert "禁止" in p
    # 不得再鼓励代码块包装
    assert "可在 Markdown 代码块中" not in p


def test_user_prompt_requires_json_only():
    ctx = _sample_context()
    user = build_portfolio_advice_user_prompt(ctx)
    assert "整个响应只能包含一个合法 JSON 对象" in user
    assert "不要使用 Markdown 代码块" in user
    assert "第一个非空字符必须是 {" in user
    assert "最后一个非空字符必须是 }" in user
    assert "再可选附简短 Markdown 摘要" not in user
    assert "Markdown 摘要" not in user or "不要" in user


def test_default_user_task_json_only():
    assert "合法 JSON 对象" in _DEFAULT_USER_TASK
    assert "Markdown 代码块" in _DEFAULT_USER_TASK
    assert "可附带 Markdown 摘要" not in _DEFAULT_USER_TASK
    assert "JSON 为权威" not in _DEFAULT_USER_TASK


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
