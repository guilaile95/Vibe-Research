"""portfolio_advice_service 编排离线测试（Mock，不联网、不写 portfolio.json）。"""
from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock, call, patch

import pytest

import portfolio_advice_context
import portfolio_advice_prompt
import portfolio_advice_service as svc
import portfolio_advice_validator
from portfolio_advice_service import (
    PortfolioAdviceMarketDataError,
    PortfolioAdviceModelError,
    PortfolioAdviceModelOutputError,
    PortfolioAdviceUnavailableError,
    generate_portfolio_advice,
    prepare_portfolio_advice_messages,
    _parse_model_json,
)
from portfolio_advice_validator import PortfolioAdviceValidationError


@pytest.fixture(autouse=True)
def _never_write_real_ai_result_db(monkeypatch):
    save = MagicMock(return_value={"trade_date": "2026-07-21"})
    monkeypatch.setattr(svc.ai_result_service, "save_portfolio_advice", save)
    return save


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _holding(code="600519", name="贵州茅台", price=1800.0, shares=1500, cost=1600.0):
    mv = round(price * shares, 2)
    cv = cost * shares
    pnl = round(mv - cv, 2)
    return {
        "code": code,
        "name": name,
        "price": price,
        "shares": shares,
        "cost": cost,
        "market_value": mv,
        "pnl": pnl,
        "pnl_pct": round(pnl / cv * 100, 2) if cv else 0.0,
    }


def _portfolio(holdings=None):
    if holdings is None:
        holdings = [_holding()]
    tmv = sum(h["market_value"] for h in holdings)
    tcost = sum(h["cost"] * h["shares"] for h in holdings)
    tpnl = tmv - tcost
    return {
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


def _review(status="normal"):
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": status,
        "warnings": ["各数据源尚未提供统一的数据截止时间"],
        "data_health": {
            "components": {
                "indices": status if status != "unavailable" else "unavailable",
                "breadth": status,
                "emotion": status,
                "turnover": "normal",
                "industry_boards": "normal",
                "concept_boards": "normal",
                "region_boards": "normal",
            }
        },
        "market_environment": {
            "indices": {"status": "normal", "data": [{"name": "上证", "price": 3000, "change_pct": 0.5}]},
            "global_indices": {"status": "normal", "data": []},
            "breadth": {
                "status": status if status != "unavailable" else "unavailable",
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
                }
                if status != "unavailable"
                else None,
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
            "industry": {"status": "normal", "data": {"top": [], "bottom": []}},
            "concept": {"status": "normal", "data": {"top": [], "bottom": []}},
            "region": {"status": "normal", "data": {"top": [], "bottom": []}},
            "highlights": {},
        },
        "capital_activity": {
            "total_amount": 1.2e12,
            "amount_valid_count": 4900,
            "amount_top": [],
            "high_turnover": [],
        },
    }


def _ai_json_for(code="600519", action="hold", **extra):
    h = {
        "code": code,
        "name": "贵州茅台",
        "action": action,
        "execution_size_pct_of_holding": None,
        "execution_quantity": None,
        "trigger_conditions": ["条件"],
        "price_conditions": ["价格"],
        "execution_plan": ["计划"],
        "risk_conditions": ["风险"],
        "invalidation_conditions": ["失效"],
        "confidence": "medium",
        "data_limitations": [],
    }
    h.update(extra)
    return {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-07-21T16:00:00",
        "market_status": "normal",
        "portfolio_summary": {
            "holding_count": 1,
            "market_value": 1,
            "cost": 1,
            "pnl": 1,
            "pnl_pct": 1,
        },
        "account_action": {
            "action": "hold",
            "reason": "测试",
            "confidence": "medium",
        },
        "holdings": [h],
        "warnings": [],
        "data_limitations": [],
    }


def _msgs():
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


# ---------------------------------------------------------------------------
# 1–2 准备链路与顺序
# ---------------------------------------------------------------------------

def test_prepare_full_chain_and_structure():
    pf = _portfolio()
    review = _review()
    ctx = {"schema_version": "portfolio-advice-context-v0.1", "holdings": [{"code": "600519"}]}
    msgs = _msgs()
    order: list[str] = []

    def get_pf():
        order.append("portfolio")
        return pf

    def gen_rev():
        order.append("daily_review")
        return review

    def fingerprint(holdings):
        order.append("fingerprint")
        assert holdings is pf["holdings"]
        return "f" * 64

    def build_ctx(p, r, **kw):
        order.append("context")
        assert p is pf
        assert r is review
        return ctx

    def build_msgs(cj, user_request=None):
        order.append("prompt")
        return msgs

    with (
        patch.object(svc.portfolio, "get_portfolio", side_effect=get_pf) as m_pf,
        patch.object(
            svc.ai_result_service, "compute_portfolio_fingerprint", side_effect=fingerprint
        ) as m_fp,
        patch.object(svc.daily_review, "generate_daily_review", side_effect=gen_rev) as m_dr,
        patch.object(
            svc.portfolio_advice_context, "build_portfolio_advice_context", side_effect=build_ctx
        ) as m_ctx,
        patch.object(
            svc.portfolio_advice_prompt, "build_portfolio_advice_messages", side_effect=build_msgs
        ) as m_pr,
    ):
        out = prepare_portfolio_advice_messages("重点看减仓")

    assert order == ["portfolio", "fingerprint", "daily_review", "context", "prompt"]
    m_pf.assert_called_once_with()
    m_fp.assert_called_once_with(pf["holdings"])
    m_dr.assert_called_once_with()
    m_ctx.assert_called_once()
    m_pr.assert_called_once()
    assert set(out.keys()) == {
        "portfolio", "input_fingerprint", "daily_review", "context", "context_json", "messages",
    }
    assert out["input_fingerprint"] == "f" * 64
    assert out["portfolio"] is pf
    assert out["daily_review"] is review
    assert out["context"] is ctx
    assert out["messages"] is msgs
    assert json.loads(out["context_json"]) == ctx


def test_prepare_fails_closed_when_holding_authority_is_unproven():
    # 权威不可读必须走 503 service-unavailable 边界（MarketDataError），
    # 不得包装成“空持仓”类 409（UnavailableError）。
    with (
        patch.object(
            svc.holding_authority,
            "read_portfolio_authority",
            side_effect=svc.holding_authority.PositionDerivationError("broken ledger"),
        ),
        patch.object(svc.daily_review, "generate_daily_review") as daily_review,
    ):
        with pytest.raises(PortfolioAdviceMarketDataError, match="持仓权威不可读"):
            prepare_portfolio_advice_messages()
    daily_review.assert_not_called()


def test_prepare_uses_authority_read_model_for_canonical_holdings():
    canonical = _portfolio([_holding(shares=80, cost=10.0)])
    canonical["holding_authority"] = "LEDGER_DERIVED"
    canonical["authority_state"] = "CANONICAL"
    legacy = _portfolio([_holding(shares=999, cost=1.0)])
    review = _review()

    with (
        patch.object(svc.holding_authority, "read_portfolio_authority", return_value=canonical),
        patch.object(svc.portfolio, "get_portfolio", return_value=legacy) as legacy_read,
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
        patch.object(
            svc.portfolio_advice_context,
            "build_portfolio_advice_context",
            return_value={"holdings": []},
        ),
        patch.object(
            svc.portfolio_advice_prompt,
            "build_portfolio_advice_messages",
            return_value=_msgs(),
        ),
    ):
        prepared = prepare_portfolio_advice_messages()

    legacy_read.assert_not_called()
    assert prepared["portfolio"] is canonical
    assert prepared["portfolio"]["holdings"][0]["shares"] == 80
    assert "authority_state" not in prepared["portfolio"]


# ---------------------------------------------------------------------------
# 3–5 空持仓 / 缺失 / 非法类型
# ---------------------------------------------------------------------------

def test_empty_holdings_raises_and_skips_downstream():
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value={"holdings": []}) as m_pf,
        patch.object(svc.daily_review, "generate_daily_review") as m_dr,
        patch.object(svc.portfolio_advice_context, "build_portfolio_advice_context") as m_ctx,
        patch.object(svc.portfolio_advice_prompt, "build_portfolio_advice_messages") as m_pr,
    ):
        with pytest.raises(PortfolioAdviceUnavailableError, match="当前没有持仓"):
            prepare_portfolio_advice_messages()
    m_pf.assert_called_once()
    m_dr.assert_not_called()
    m_ctx.assert_not_called()
    m_pr.assert_not_called()


def test_missing_holdings_raises():
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value={}),
        patch.object(svc.daily_review, "generate_daily_review") as m_dr,
    ):
        with pytest.raises(PortfolioAdviceUnavailableError):
            prepare_portfolio_advice_messages()
    m_dr.assert_not_called()


def test_invalid_holdings_type_raises():
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value={"holdings": "bad"}),
        patch.object(svc.daily_review, "generate_daily_review") as m_dr,
    ):
        with pytest.raises(PortfolioAdviceUnavailableError):
            prepare_portfolio_advice_messages()
    m_dr.assert_not_called()


# ---------------------------------------------------------------------------
# 6–9 user_request
# ---------------------------------------------------------------------------

def test_user_request_none_passed():
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=_portfolio()),
        patch.object(svc.daily_review, "generate_daily_review", return_value=_review()),
        patch.object(
            svc.portfolio_advice_context,
            "build_portfolio_advice_context",
            return_value={"holdings": []},
        ),
        patch.object(
            svc.portfolio_advice_prompt, "build_portfolio_advice_messages", return_value=_msgs()
        ) as m_pr,
    ):
        prepare_portfolio_advice_messages(None)
    assert m_pr.call_args.kwargs.get("user_request") is None or m_pr.call_args[0][1] is None or (
        len(m_pr.call_args[0]) > 1 and m_pr.call_args[0][1] is None
    )
    # explicit kwargs preferred
    assert m_pr.call_args == call(m_pr.call_args.args[0], user_request=None) or \
        m_pr.call_args.kwargs.get("user_request") is None


def test_user_request_strip():
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=_portfolio()),
        patch.object(svc.daily_review, "generate_daily_review", return_value=_review()),
        patch.object(
            svc.portfolio_advice_context,
            "build_portfolio_advice_context",
            return_value={"holdings": []},
        ),
        patch.object(
            svc.portfolio_advice_prompt, "build_portfolio_advice_messages", return_value=_msgs()
        ) as m_pr,
    ):
        prepare_portfolio_advice_messages("  重点分析减仓风险  ")
    assert m_pr.call_args.kwargs["user_request"] == "重点分析减仓风险"


def test_user_request_blank_to_none():
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=_portfolio()),
        patch.object(svc.daily_review, "generate_daily_review", return_value=_review()),
        patch.object(
            svc.portfolio_advice_context,
            "build_portfolio_advice_context",
            return_value={"holdings": []},
        ),
        patch.object(
            svc.portfolio_advice_prompt, "build_portfolio_advice_messages", return_value=_msgs()
        ) as m_pr,
    ):
        prepare_portfolio_advice_messages("   \t  ")
    assert m_pr.call_args.kwargs["user_request"] is None


def test_user_request_invalid_type():
    with pytest.raises(TypeError):
        prepare_portfolio_advice_messages(123)  # type: ignore[arg-type]


def test_generate_saves_final_authoritative_result_from_same_snapshot(monkeypatch):
    portfolio_snapshot = _portfolio()
    review = _review()
    prepared = {
        "portfolio": portfolio_snapshot,
        "input_fingerprint": "a" * 64,
        "daily_review": review,
        "context": {"holdings": [{"code": "600519"}]},
        "context_json": "{}",
        "messages": _msgs(),
    }
    validated = _ai_json_for()
    authoritative = copy.deepcopy(validated)
    authoritative["account_funding"] = {"configured": True}
    save = MagicMock(return_value={"trade_date": "2026-07-21"})
    monkeypatch.setattr(svc, "prepare_portfolio_advice_messages", lambda _request=None: prepared)
    monkeypatch.setattr(svc.portfolio_advice_validator, "validate_portfolio_advice", lambda *_a: validated)
    monkeypatch.setattr(svc, "attach_account_funding_metrics", lambda *_a: authoritative)
    monkeypatch.setattr(svc.ai_result_service, "save_portfolio_advice", save)

    result = generate_portfolio_advice(
        {"provider": "deepseek", "model": "m"},
        model_runner=lambda *_a: json.dumps(_ai_json_for()),
    )

    assert result is authoritative
    save.assert_called_once_with(
        portfolio_snapshot,
        review,
        authoritative,
        {"provider": "deepseek", "model": "m"},
        input_fingerprint="a" * 64,
    )
    assert save.call_args.args[2] is not validated


def test_generate_save_failure_is_failure_not_success(monkeypatch):
    prepared = {
        "portfolio": _portfolio(),
        "input_fingerprint": "b" * 64,
        "daily_review": _review(),
        "context": {"holdings": [{"code": "600519"}]},
        "context_json": "{}",
        "messages": _msgs(),
    }
    monkeypatch.setattr(svc, "prepare_portfolio_advice_messages", lambda _request=None: prepared)
    monkeypatch.setattr(svc.portfolio_advice_validator, "validate_portfolio_advice", lambda *_a: _ai_json_for())
    monkeypatch.setattr(svc, "attach_account_funding_metrics", lambda result, *_a: result)
    monkeypatch.setattr(
        svc.ai_result_service,
        "save_portfolio_advice",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )

    with pytest.raises(svc.PortfolioAdvicePersistError, match="持仓建议结果保存失败"):
        generate_portfolio_advice(
            {"provider": "deepseek", "model": "m"},
            model_runner=lambda *_a: json.dumps(_ai_json_for()),
        )


def test_account_reality_read_failure_blocks_add_but_keeps_reduce(monkeypatch):
    holdings = [
        _holding("600519", shares=1000, price=12, cost=10),
        _holding("000001", name="平安银行", shares=1000, price=10, cost=8),
    ]
    prepared = {
        "portfolio": _portfolio(holdings),
        "input_fingerprint": "c" * 64,
        "daily_review": _review(),
        "context": {"holdings": [{"code": "600519"}, {"code": "000001"}]},
        "context_json": "{}",
        "messages": _msgs(),
    }
    validated = {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-07-21T16:00:00",
        "trade_date": "2026-07-21",
        "holdings": [
            {
                "code": "600519",
                "shares": 1000,
                "current_price": 12,
                "action": "add",
                "execution_quantity": 100,
                "estimated_amount": 1200,
                "data_limitations": [],
            },
            {
                "code": "000001",
                "shares": 1000,
                "current_price": 10,
                "action": "reduce",
                "execution_quantity": 200,
                "estimated_amount": None,
                "data_limitations": [],
            },
        ],
        "data_limitations": [],
    }
    monkeypatch.setattr(svc, "prepare_portfolio_advice_messages", lambda _request=None: prepared)
    monkeypatch.setattr(
        svc.portfolio_advice_validator,
        "validate_portfolio_advice",
        lambda *_a: copy.deepcopy(validated),
    )
    monkeypatch.setattr(
        svc.account_reality_service,
        "get_account_reality",
        MagicMock(side_effect=RuntimeError("authority unavailable")),
    )
    monkeypatch.setattr(svc.ai_result_service, "save_portfolio_advice", MagicMock())

    result = generate_portfolio_advice(
        {"provider": "deepseek", "model": "m"},
        model_runner=lambda *_a: json.dumps(_ai_json_for()),
    )

    by_code = {item["code"]: item for item in result["holdings"]}
    assert result["account_funding"]["reason_code"] == "ACCOUNT_REALITY_UNAVAILABLE"
    assert by_code["600519"]["execution_quantity"] is None
    assert by_code["600519"]["estimated_amount"] is None
    assert by_code["000001"]["execution_quantity"] == 200
    assert by_code["000001"]["sellable_quantity_advisory"] == 200


# ---------------------------------------------------------------------------
# JSON 解析单元
# ---------------------------------------------------------------------------

def test_parse_pure_json():
    obj = _parse_model_json('{"schema_version":"portfolio-advice-v0.1","a":1}')
    assert obj["a"] == 1


def test_parse_fenced_json():
    text = '```json\n{"schema_version":"portfolio-advice-v0.1","x":2}\n```'
    assert _parse_model_json(text)["x"] == 2


def test_parse_fenced_json_uppercase():
    text = '```JSON\n{"schema_version":"portfolio-advice-v0.1","x":3}\n```'
    assert _parse_model_json(text)["x"] == 3


def test_parse_fenced_plain():
    text = '```\n{"schema_version":"portfolio-advice-v0.1","x":4}\n```'
    assert _parse_model_json(text)["x"] == 4


def test_parse_rejects_prefix_text():
    text = '说明如下\n{"a":1}'
    with pytest.raises(PortfolioAdviceModelOutputError, match="不是有效的JSON"):
        _parse_model_json(text)


def test_parse_rejects_suffix_text():
    text = '{"a":1}\n总结：看多'
    with pytest.raises(PortfolioAdviceModelOutputError, match="不是有效的JSON"):
        _parse_model_json(text)


def test_parse_rejects_fence_then_trailing_markdown():
    """真实故障形态：fence + 合法 JSON + 尾部 Markdown 摘要 → 拒绝（不 repair）。"""
    body = json.dumps(
        {"schema_version": "portfolio-advice-v0.1", "account_action": {"action": "hold"}},
        ensure_ascii=False,
    )
    text = f"```json\n{body}\n```\n\n## Markdown 摘要\n- 风险提示：广度偏弱\n"
    with pytest.raises(PortfolioAdviceModelOutputError, match="不是有效的JSON"):
        _parse_model_json(text)


def test_parse_rejects_top_array():
    with pytest.raises(PortfolioAdviceModelOutputError, match="不是有效的JSON"):
        _parse_model_json("[1,2,3]")


def test_parse_rejects_python_dict():
    with pytest.raises(PortfolioAdviceModelOutputError, match="不是有效的JSON"):
        _parse_model_json("{'a': 1}")


def test_parse_rejects_invalid_json():
    with pytest.raises(PortfolioAdviceModelOutputError, match="不是有效的JSON"):
        _parse_model_json("{broken")


def test_parse_empty_and_none():
    with pytest.raises(PortfolioAdviceModelOutputError, match="未返回有效内容"):
        _parse_model_json("")
    with pytest.raises(PortfolioAdviceModelOutputError, match="未返回有效内容"):
        _parse_model_json("   ")
    with pytest.raises(PortfolioAdviceModelOutputError, match="未返回有效内容"):
        _parse_model_json(None)
    with pytest.raises(PortfolioAdviceModelOutputError, match="未返回有效内容"):
        _parse_model_json("```json\n\n```")


# ---------------------------------------------------------------------------
# generate_portfolio_advice + model_runner
# ---------------------------------------------------------------------------

def _patch_prepare_ok(ctx=None, msgs=None, pf=None, review=None):
    pf = pf or _portfolio()
    review = review or _review()
    ctx = ctx or {
        "schema_version": "portfolio-advice-context-v0.1",
        "holdings": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "shares": 1500,
                "cost_price": 1600.0,
                "current_price": 1800.0,
                "market_value": 2700000.0,
                "pnl_amount": 300000.0,
                "pnl_pct": 12.5,
                "holding_weight_pct": 100.0,
            }
        ],
        "portfolio_summary": {
            "holding_count": 1,
            "market_value": 2700000.0,
            "cost": 2400000.0,
            "pnl": 300000.0,
            "pnl_pct": 12.5,
        },
        "data_limitations": [],
        "warnings": [],
        "market_context": {"review_metadata": {"status": "normal"}},
    }
    msgs = msgs or _msgs()
    return (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
        patch.object(
            svc.portfolio_advice_context, "build_portfolio_advice_context", return_value=ctx
        ),
        patch.object(
            svc.portfolio_advice_prompt, "build_portfolio_advice_messages", return_value=msgs
        ),
        pf,
        review,
        ctx,
        msgs,
    )


def test_generate_with_model_runner_pure_json():
    patches = _patch_prepare_ok()
    pf, review, ctx, msgs = patches[4], patches[5], patches[6], patches[7]
    validated = {"schema_version": "portfolio-advice-v0.1", "holdings": [], "ok": True}
    runner = MagicMock(return_value=json.dumps(_ai_json_for(action="hold")))

    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator,
        "validate_portfolio_advice",
        return_value=validated,
    ) as m_val:
        out = generate_portfolio_advice({"model": "x"}, model_runner=runner)

    assert out is validated
    runner.assert_called_once()
    assert runner.call_args[0][1] is msgs
    m_val.assert_called_once()
    assert m_val.call_args[0][1] is ctx


def test_generate_fenced_json_via_runner():
    patches = _patch_prepare_ok()
    body = json.dumps(_ai_json_for(action="hold"))
    fenced = f"```json\n{body}\n```"
    validated = {"ok": True}

    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator,
        "validate_portfolio_advice",
        return_value=validated,
    ):
        out = generate_portfolio_advice(
            {}, model_runner=lambda cfg, m: fenced
        )
    assert out is validated


def test_generate_rejects_prefix_text_no_validator():
    patches = _patch_prepare_ok()
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator, "validate_portfolio_advice"
    ) as m_val:
        with pytest.raises(PortfolioAdviceModelOutputError):
            generate_portfolio_advice(
                {},
                model_runner=lambda c, m: '说明\n{"a":1}',
            )
    m_val.assert_not_called()


def test_generate_rejects_fence_plus_trailing_markdown_no_validator():
    patches = _patch_prepare_ok()
    body = json.dumps(_ai_json_for(action="hold"))
    raw = f"```json\n{body}\n```\n\n## Markdown 摘要\n风险提示：测试\n"
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator, "validate_portfolio_advice"
    ) as m_val:
        with pytest.raises(PortfolioAdviceModelOutputError, match="不是有效的JSON"):
            generate_portfolio_advice({}, model_runner=lambda c, m: raw)
    m_val.assert_not_called()


def test_generate_empty_output_no_validator():
    patches = _patch_prepare_ok()
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator, "validate_portfolio_advice"
    ) as m_val:
        with pytest.raises(PortfolioAdviceModelOutputError, match="未返回有效内容"):
            generate_portfolio_advice({}, model_runner=lambda c, m: "")
        with pytest.raises(PortfolioAdviceModelOutputError, match="未返回有效内容"):
            generate_portfolio_advice({}, model_runner=lambda c, m: None)  # type: ignore[arg-type,return-value]
    m_val.assert_not_called()


def test_validator_failure_wrapped_with_chain():
    patches = _patch_prepare_ok()
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator,
        "validate_portfolio_advice",
        side_effect=PortfolioAdviceValidationError("非法 action"),
    ):
        with pytest.raises(PortfolioAdviceModelOutputError, match="未通过结构和执行约束") as ei:
            generate_portfolio_advice(
                {},
                model_runner=lambda c, m: json.dumps(_ai_json_for()),
            )
    assert isinstance(ei.value.__cause__, PortfolioAdviceValidationError)


def test_validator_output_passthrough_no_second_mutation():
    patches = _patch_prepare_ok()
    validated = {"schema_version": "portfolio-advice-v0.1", "unique": 42, "holdings": []}
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator,
        "validate_portfolio_advice",
        return_value=validated,
    ):
        out = generate_portfolio_advice(
            {}, model_runner=lambda c, m: json.dumps(_ai_json_for())
        )
    assert out is validated
    assert out["unique"] == 42


# ---------------------------------------------------------------------------
# default runner / stream_messages
# ---------------------------------------------------------------------------

def test_default_runner_concat_deltas_in_order():
    patches = _patch_prepare_ok()
    events = [
        {"type": "delta", "text": '{"schema_'},
        {"type": "delta", "text": 'version":"portfolio-advice-v0.1",'},
        {"type": "delta", "text": '"holdings":[]}'},
        {"type": "done", "trace": [], "rounds": 1},
    ]
    validated = {"from": "validator"}

    def fake_stream(cfg, messages, *, use_tools=False):
        assert use_tools is False
        yield from events

    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.chat, "stream_messages", side_effect=fake_stream
    ) as m_sm, patch.object(
        svc.portfolio_advice_validator,
        "validate_portfolio_advice",
        return_value=validated,
    ) as m_val:
        out = generate_portfolio_advice({"model": "m"})

    assert out is validated
    m_sm.assert_called_once()
    assert m_sm.call_args.kwargs.get("use_tools") is False
    # validator 收到拼接后的完整 JSON
    ai_arg = m_val.call_args[0][0]
    assert ai_arg["schema_version"] == "portfolio-advice-v0.1"
    assert ai_arg["holdings"] == []


def test_default_runner_ignores_tool_events():
    patches = _patch_prepare_ok()
    body = json.dumps(_ai_json_for())
    # split body so tool in the middle must not inject text
    mid = len(body) // 2
    events = [
        {"type": "delta", "text": body[:mid]},
        {"type": "tool", "text": "SHOULD_NOT_APPEAR", "name": "search"},
        {"type": "delta", "text": body[mid:]},
        {"type": "done"},
    ]
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.chat, "stream_messages", return_value=iter(events)
    ), patch.object(
        svc.portfolio_advice_validator,
        "validate_portfolio_advice",
        return_value={"ok": True},
    ) as m_val:
        generate_portfolio_advice({})
    parsed = m_val.call_args[0][0]
    assert "SHOULD_NOT_APPEAR" not in json.dumps(parsed)


def test_default_runner_error_event():
    patches = _patch_prepare_ok()
    events = [
        {"type": "delta", "text": '{"partial":'},
        {"type": "error", "message": "上游失败"},
    ]
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.chat, "stream_messages", return_value=iter(events)
    ), patch.object(
        svc.portfolio_advice_validator, "validate_portfolio_advice"
    ) as m_val:
        # 流内 error 原文不直接外泄；映射为公开安全文案
        with pytest.raises(PortfolioAdviceModelError, match="持仓建议模型调用失败"):
            generate_portfolio_advice({})
    m_val.assert_not_called()


def test_default_runner_auth_error_classified():
    patches = _patch_prepare_ok()
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.chat,
        "stream_messages",
        side_effect=RuntimeError(
            '模型接口 HTTP 401: {"error":{"message":"Authentication Fails, Your api key: sk-leak is invalid"}}'
        ),
    ), patch.object(
        svc.portfolio_advice_validator, "validate_portfolio_advice"
    ) as m_val:
        with pytest.raises(PortfolioAdviceModelError) as ei:
            generate_portfolio_advice({})
        assert str(ei.value) == "持仓建议模型鉴权失败，请检查 API Key 或重新连接 Codex"
        assert "sk-leak" not in str(ei.value)
    m_val.assert_not_called()


def test_default_runner_stream_raises():
    patches = _patch_prepare_ok()
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.chat, "stream_messages", side_effect=RuntimeError("network down")
    ), patch.object(
        svc.portfolio_advice_validator, "validate_portfolio_advice"
    ) as m_val:
        with pytest.raises(PortfolioAdviceModelError):
            generate_portfolio_advice({})
    m_val.assert_not_called()


def test_default_runner_done_without_delta():
    patches = _patch_prepare_ok()
    events = [{"type": "done", "trace": [], "rounds": 1}]
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.chat, "stream_messages", return_value=iter(events)
    ), patch.object(
        svc.portfolio_advice_validator, "validate_portfolio_advice"
    ) as m_val:
        with pytest.raises(PortfolioAdviceModelOutputError, match="未返回有效内容"):
            generate_portfolio_advice({})
    m_val.assert_not_called()


def test_model_runner_exception_wrapped():
    patches = _patch_prepare_ok()

    def boom(cfg, messages):
        raise RuntimeError("runner boom")

    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator, "validate_portfolio_advice"
    ) as m_val:
        with pytest.raises(PortfolioAdviceModelError):
            generate_portfolio_advice({}, model_runner=boom)
    m_val.assert_not_called()


def test_model_and_validator_called_once_no_retry():
    patches = _patch_prepare_ok()
    runner = MagicMock(return_value=json.dumps(_ai_json_for()))
    with patches[0], patches[1], patches[2], patches[3], patch.object(
        svc.portfolio_advice_validator,
        "validate_portfolio_advice",
        return_value={"once": True},
    ) as m_val:
        generate_portfolio_advice({}, model_runner=runner)
    assert runner.call_count == 1
    assert m_val.call_count == 1


# ---------------------------------------------------------------------------
# partial / unavailable / missing quotes
# ---------------------------------------------------------------------------

def test_partial_review_still_prepares():
    pf = _portfolio()
    review = _review(status="partial")
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
        patch.object(
            svc.portfolio_advice_context,
            "build_portfolio_advice_context",
            return_value={"status": "partial", "holdings": []},
        ) as m_ctx,
        patch.object(
            svc.portfolio_advice_prompt, "build_portfolio_advice_messages", return_value=_msgs()
        ),
    ):
        out = prepare_portfolio_advice_messages()
    m_ctx.assert_called_once()
    assert out["daily_review"]["status"] == "partial"


def test_unavailable_review_fails_closed_before_context():
    """市场广度 unavailable 时失败关闭：不构建 context、不调模型。"""
    pf = _portfolio()
    review = _review(status="unavailable")
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
        patch.object(
            svc.portfolio_advice_context,
            "build_portfolio_advice_context",
        ) as m_ctx,
        patch.object(
            svc.portfolio_advice_prompt, "build_portfolio_advice_messages"
        ) as m_prompt,
    ):
        with pytest.raises(svc.PortfolioAdviceMarketDataError) as ei:
            prepare_portfolio_advice_messages()
    assert "市场核心数据暂不可用" in str(ei.value)
    m_ctx.assert_not_called()
    m_prompt.assert_not_called()


def test_missing_quote_not_filled_by_service():
    """集成真实 context：缺失行情保持 null，service 不补 0/成本。"""
    pf = _portfolio([_holding(price=10.0, shares=100, cost=9.0, code="000001", name="A")])
    review = _review()
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
    ):
        out = prepare_portfolio_advice_messages()
    h = out["context"]["holdings"][0]
    assert h["quote"]["open"] is None
    assert h["quote"]["amplitude_pct"] is None
    # 现价来自持仓行，不是补造
    assert h["current_price"] == 10.0


# ---------------------------------------------------------------------------
# 输入不可变 / 无存储副作用
# ---------------------------------------------------------------------------

def test_prepare_does_not_mutate_portfolio_or_review():
    pf = _portfolio()
    review = _review()
    pf_before = copy.deepcopy(pf)
    review_before = copy.deepcopy(review)
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
    ):
        prepare_portfolio_advice_messages()
    assert pf == pf_before
    assert review == review_before


def test_no_storage_side_effects():
    def fail(*a, **k):
        raise AssertionError("storage side effect")

    pf = _portfolio()
    review = _review()
    body = json.dumps(_ai_json_for(action="hold"))

    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
        patch("portfolio.add_holding", side_effect=fail),
        patch("portfolio.remove_holding", side_effect=fail),
        patch("portfolio.close_position", side_effect=fail),
        patch("review_history.save_current_daily_review", side_effect=fail, create=True),
        patch("review_store.save_daily_review_snapshot", side_effect=fail, create=True),
    ):
        # 真实 context + prompt + validator
        out = generate_portfolio_advice(
            {},
            model_runner=lambda c, m: body,
        )
    assert out["schema_version"] == "portfolio-advice-v0.1"
    assert "t_trade" not in out
    for h in out["holdings"]:
        assert "t_trade" not in h


def test_final_result_strips_t_trade_from_model():
    pf = _portfolio()
    review = _review()
    model_obj = _ai_json_for(action="hold")
    model_obj["holdings"][0]["t_trade"] = {
        "suitable": True,
        "direction": "sell_then_buy",
        "quantity": 100,
    }
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
    ):
        out = generate_portfolio_advice(
            {},
            model_runner=lambda c, m: json.dumps(model_obj),
        )
    assert "t_trade" not in out
    assert all("t_trade" not in h for h in out["holdings"])


def test_prepare_deterministic():
    pf = _portfolio()
    review = _review()
    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
    ):
        a = prepare_portfolio_advice_messages("重点")
        b = prepare_portfolio_advice_messages("重点")
    assert a["context_json"] == b["context_json"]
    assert a["messages"] == b["messages"]


# ---------------------------------------------------------------------------
# 有限集成：真实 context/prompt/validator + mock IO
# ---------------------------------------------------------------------------

def test_limited_integration_real_pipeline():
    pf = _portfolio([
        _holding("600519", "贵州茅台", 1800.0, 1500, 1600.0),
        _holding("000001", "平安银行", 10.0, 1000, 9.0),
    ])
    review = _review(status="partial")

    model = {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-07-21T16:00:00",
        "market_status": "partial",
        "portfolio_summary": {
            "holding_count": 99,
            "market_value": 1,
            "cost": 1,
            "pnl": 1,
            "pnl_pct": 1,
        },
        "account_action": {
            "action": "reduce_risk",
            "reason": "广度偏弱",
            "confidence": "medium",
        },
        "holdings": [
            {
                "code": "600519",
                "name": "错名",
                "shares": 1,
                "cost_price": 1,
                "current_price": 1,
                "market_value": 1,
                "pnl_amount": 1,
                "pnl_pct": 1,
                "holding_weight_pct": 1,
                "action": "reduce",
                "execution_size_pct_of_holding": 20,
                "execution_quantity": 99999,
                "trigger_conditions": ["弱"],
                "price_conditions": ["破位"],
                "execution_plan": ["减20%"],
                "risk_conditions": ["继续跌"],
                "invalidation_conditions": ["放量转强"],
                "confidence": "medium",
                "data_limitations": [],
                "t_trade": {"suitable": True, "quantity": 100},
            },
            {
                "code": "000001",
                "name": "错",
                "action": "add",
                "execution_size_pct_of_holding": 10,
                "execution_quantity": 500,
                "trigger_conditions": ["强"],
                "price_conditions": [],
                "execution_plan": ["加仓"],
                "risk_conditions": [],
                "invalidation_conditions": [],
                "confidence": "low",
                "data_limitations": [],
            },
        ],
        "warnings": [],
        "data_limitations": [],
    }

    with (
        patch.object(svc.portfolio, "get_portfolio", return_value=pf),
        patch.object(svc.daily_review, "generate_daily_review", return_value=review),
    ):
        out = generate_portfolio_advice(
            {"model": "test"},
            user_request="  关注减仓  ",
            model_runner=lambda c, m: json.dumps(model),
        )

    assert out["schema_version"] == "portfolio-advice-v0.1"
    by = {h["code"]: h for h in out["holdings"]}
    # 事实被代码覆盖
    assert by["600519"]["name"] == "贵州茅台"
    assert by["600519"]["shares"] == 1500
    assert by["600519"]["market_value"] == 2700000.0
    # reduce 20% × 1500 = 300
    assert by["600519"]["action"] == "reduce"
    assert by["600519"]["execution_quantity"] == 300
    assert by["600519"]["estimated_amount"] is None
    # 账户资金未配置：保留 add 方向，可执行数量/金额必须为 null
    assert by["000001"]["action"] == "add"
    assert by["000001"]["execution_quantity"] is None
    assert by["000001"].get("estimated_amount") is None
    assert any("未配置账户资金" in x for x in (out.get("data_limitations") or []))
    # 无 t_trade
    assert "t_trade" not in out
    assert all("t_trade" not in h for h in out["holdings"])
    # partial 允许
    assert out["market_status"] in ("partial", "normal", "")


def test_generate_empty_holdings_before_model():
    runner = MagicMock()
    with patch.object(svc.portfolio, "get_portfolio", return_value={"holdings": []}):
        with pytest.raises(PortfolioAdviceUnavailableError):
            generate_portfolio_advice({}, model_runner=runner)
    runner.assert_not_called()
