"""POST /api/portfolio/advice 离线 API 测试（Mock service，不联网、不写持仓）。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import chat as chat_layer
import portfolio_advice_service as advice_svc

client = TestClient(app_module.app)

_LLM = {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "baseURL": "http://example.test/v1",
    "apiKey": "sk-test-secret",
}


def _advice_payload(**overrides):
    base = {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-07-21 16:00:00",
        "market_status": "normal",
        "portfolio_summary": {
            "holding_count": 1,
            "market_value": 22230.0,
            "cost": 20325.0,
            "pnl": 1905.0,
            "pnl_pct": 9.37,
        },
        "account_action": {
            "action": "hold",
            "reason": "测试",
            "confidence": "medium",
        },
        "holdings": [
            {
                "code": "001896",
                "name": "豫能控股",
                "shares": 1500,
                "cost_price": 13.55,
                "current_price": 14.82,
                "market_value": 22230.0,
                "pnl_amount": 1905.0,
                "pnl_pct": 9.37,
                "holding_weight_pct": 100.0,
                "action": "reduce",
                "execution_size_pct_of_holding": 20,
                "execution_quantity": 300,
                "trigger_conditions": ["条件"],
                "price_conditions": [],
                "execution_plan": ["减仓"],
                "risk_conditions": [],
                "invalidation_conditions": [],
                "confidence": "medium",
                "data_limitations": [
                    "未提供可卖数量，执行前需要人工确认实际可卖股数。"
                ],
            }
        ],
        "warnings": [],
        "data_limitations": ["未提供账户总资产与可用现金，无法计算绝对账户仓位与具体买入金额。"],
    }
    base.update(overrides)
    return base


def _has_key(obj, key: str) -> bool:
    if isinstance(obj, dict):
        if key in obj:
            return True
        return any(_has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, key) for v in obj)
    return False


def _fail(*_a, **_k):
    raise AssertionError("forbidden side effect or direct dependency call")


# ---------------------------------------------------------------------------
# 1–4 正常成功
# ---------------------------------------------------------------------------

def test_advice_ok_passthrough(monkeypatch):
    payload = _advice_payload()
    gen = MagicMock(return_value=payload)
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)

    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "ndjson" not in r.headers["content-type"]
    assert "event-stream" not in r.headers["content-type"]
    body = r.json()
    assert "data" in body
    assert body["data"] is payload or body["data"] == payload
    gen.assert_called_once()
    assert gen.call_args[0][0]["model"] == "deepseek-chat"
    assert gen.call_args[0][0]["apiKey"] == "sk-test-secret"
    assert gen.call_args.kwargs.get("user_request") is None


def test_advice_user_request_none(monkeypatch):
    gen = MagicMock(return_value=_advice_payload())
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    r = client.post("/api/portfolio/advice", json={"user_request": None, "llm": _LLM})
    assert r.status_code == 200
    assert gen.call_args.kwargs["user_request"] is None


def test_advice_user_request_string_passed_through(monkeypatch):
    gen = MagicMock(return_value=_advice_payload())
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    text = "重点判断是否应该减仓"
    r = client.post(
        "/api/portfolio/advice",
        json={"user_request": text, "llm": _LLM},
    )
    assert r.status_code == 200
    assert gen.call_args.kwargs["user_request"] == text


def test_advice_without_client_portfolio(monkeypatch):
    gen = MagicMock(return_value=_advice_payload())
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    # 仅 cfg + user_request
    assert set(gen.call_args.kwargs.keys()) <= {"user_request"}
    assert len(gen.call_args[0]) == 1  # cfg only positional


# ---------------------------------------------------------------------------
# 5–8 错误映射
# ---------------------------------------------------------------------------

def test_advice_empty_holdings_409(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(
            side_effect=advice_svc.PortfolioAdviceUnavailableError(
                "当前没有持仓，无法生成持仓操作建议"
            )
        ),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 409
    assert r.json()["detail"] == "当前没有持仓，无法生成持仓操作建议"
    assert "data" not in r.json() or r.json().get("data") is None


def test_advice_model_error_502_generic(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(
            side_effect=advice_svc.PortfolioAdviceModelError(
                "upstream error with secret-key sk-leak"
            )
        ),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail == "持仓建议模型调用失败"
    assert "secret" not in detail.lower()
    assert "sk-leak" not in detail
    assert "upstream" not in detail


def test_advice_model_output_error_502_generic(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(
            side_effect=advice_svc.PortfolioAdviceModelOutputError(
                'invalid model JSON: {"schema_version":"x","secret":"hide"}'
            )
        ),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail == "持仓建议模型输出无效"
    assert "schema_version" not in detail
    assert "secret" not in detail
    assert "invalid model JSON" not in detail


def test_advice_unexpected_500_no_path_leak(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(
            side_effect=RuntimeError(
                r"failed to read C:\Users\secret\.vibe-research\portfolio.json"
            )
        ),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail == "持仓操作建议生成失败"
    assert "Users" not in detail
    assert "portfolio.json" not in detail
    assert "secret" not in detail


# ---------------------------------------------------------------------------
# 9–14 请求校验 / 禁止字段
# ---------------------------------------------------------------------------

def test_advice_missing_llm_422():
    r = client.post("/api/portfolio/advice", json={"user_request": "x"})
    assert r.status_code == 422


def test_advice_invalid_llm_422():
    r = client.post("/api/portfolio/advice", json={"llm": "not-an-object"})
    assert r.status_code == 422


def test_advice_invalid_user_request_type_422():
    r = client.post(
        "/api/portfolio/advice",
        json={"user_request": ["list"], "llm": _LLM},
    )
    assert r.status_code == 422


def test_advice_rejects_portfolio_field_422(monkeypatch):
    gen = MagicMock(return_value=_advice_payload())
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    r = client.post(
        "/api/portfolio/advice",
        json={
            "llm": _LLM,
            "portfolio": {"holdings": []},
        },
    )
    assert r.status_code == 422
    gen.assert_not_called()


@pytest.mark.parametrize(
    "extra_field",
    ["context", "messages", "system_prompt", "daily_review", "db_path"],
)
def test_advice_rejects_injection_fields_422(monkeypatch, extra_field):
    gen = MagicMock(return_value=_advice_payload())
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    body = {"llm": _LLM, extra_field: {"x": 1} if extra_field != "system_prompt" else "hack"}
    r = client.post("/api/portfolio/advice", json=body)
    assert r.status_code == 422
    gen.assert_not_called()


# ---------------------------------------------------------------------------
# 15–19 状态透传 / 数量透传 / 无 t_trade
# ---------------------------------------------------------------------------

def test_advice_partial_status_200(monkeypatch):
    payload = _advice_payload(
        market_status="partial",
        data_limitations=["广度 partial"],
    )
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(return_value=payload),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    assert r.json()["data"]["market_status"] == "partial"
    assert "广度 partial" in r.json()["data"]["data_limitations"]


def test_advice_unavailable_status_200(monkeypatch):
    payload = _advice_payload(
        market_status="unavailable",
        data_limitations=["市场核心数据不可用"],
        account_action={
            "action": "defensive",
            "reason": "数据不足",
            "confidence": "low",
        },
    )
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(return_value=payload),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["market_status"] == "unavailable"
    assert "市场核心数据不可用" in data["data_limitations"]


def test_advice_reduce_quantity_passthrough(monkeypatch):
    payload = _advice_payload()
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(return_value=payload),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    h = r.json()["data"]["holdings"][0]
    assert h["action"] == "reduce"
    assert h["execution_quantity"] == 300
    assert h["execution_size_pct_of_holding"] == 20


def test_advice_add_quantity_null_passthrough(monkeypatch):
    payload = _advice_payload(
        holdings=[
            {
                "code": "000001",
                "name": "平安银行",
                "shares": 1000,
                "cost_price": 9.0,
                "current_price": 10.0,
                "market_value": 10000.0,
                "pnl_amount": 1000.0,
                "pnl_pct": 11.11,
                "holding_weight_pct": 100.0,
                "action": "add",
                "execution_size_pct_of_holding": 10,
                "execution_quantity": None,
                "trigger_conditions": [],
                "price_conditions": [],
                "execution_plan": [],
                "risk_conditions": [],
                "invalidation_conditions": [],
                "confidence": "low",
                "data_limitations": [],
            }
        ]
    )
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(return_value=payload),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    h = r.json()["data"]["holdings"][0]
    assert h["action"] == "add"
    assert h["execution_quantity"] is None


def test_advice_response_no_t_trade(monkeypatch):
    payload = _advice_payload()
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(return_value=payload),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    assert _has_key(r.json(), "t_trade") is False


# ---------------------------------------------------------------------------
# 20–23 隔离：API 只依赖 service；无写入
# ---------------------------------------------------------------------------

def test_advice_api_only_calls_service(monkeypatch):
    gen = MagicMock(return_value=_advice_payload())
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)

    monkeypatch.setattr(app_module.pf, "get_portfolio", _fail)
    monkeypatch.setattr("daily_review.generate_daily_review", _fail)
    monkeypatch.setattr(
        "portfolio_advice_context.build_portfolio_advice_context", _fail, raising=False
    )
    monkeypatch.setattr(
        "portfolio_advice_prompt.build_portfolio_advice_messages", _fail, raising=False
    )
    monkeypatch.setattr(
        "portfolio_advice_validator.validate_portfolio_advice", _fail, raising=False
    )
    monkeypatch.setattr(chat_layer, "stream_messages", _fail)

    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    gen.assert_called_once()


def test_advice_no_portfolio_write(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(return_value=_advice_payload()),
    )
    monkeypatch.setattr(app_module.pf, "add_holding", _fail)
    monkeypatch.setattr(app_module.pf, "remove_holding", _fail)
    monkeypatch.setattr(app_module.pf, "close_position", _fail)

    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200


def test_advice_no_history_save(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(return_value=_advice_payload()),
    )
    monkeypatch.setattr(
        app_module.review_history, "save_current_daily_review", _fail, raising=False
    )
    # review_store 可能未直接挂在 app 上
    monkeypatch.setattr(
        "review_store.save_daily_review_snapshot", _fail, raising=False
    )

    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 24 daily-review analyze 不变
# ---------------------------------------------------------------------------

def test_daily_review_analyze_unchanged_and_no_portfolio_advice(monkeypatch):
    prepare = MagicMock(
        return_value=[
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ]
    )
    advice_gen = MagicMock(side_effect=AssertionError("must not call portfolio advice"))

    def fake_stream(cfg, messages, *, use_tools=False):
        yield {"type": "delta", "text": "ok"}
        yield {"type": "done", "trace": [], "rounds": 1}

    monkeypatch.setattr(chat_layer, "prepare_daily_review_messages", prepare)
    monkeypatch.setattr(chat_layer, "stream_messages", fake_stream)
    monkeypatch.setattr(
        app_module.portfolio_advice_service, "generate_portfolio_advice", advice_gen
    )

    r = client.post("/api/daily-review/analyze", json={"llm": _LLM})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    prepare.assert_called_once()
    advice_gen.assert_not_called()


# ---------------------------------------------------------------------------
# 25 路由命中 advice，而非股票代码路径
# ---------------------------------------------------------------------------

def test_route_is_portfolio_advice_not_code(monkeypatch):
    gen = MagicMock(return_value=_advice_payload(schema_version="portfolio-advice-v0.1"))
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    # 若被当成 code 路径通常会 405/404/422，而非 200 + schema
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 200
    assert r.json()["data"]["schema_version"] == "portfolio-advice-v0.1"
    gen.assert_called_once()


# ---------------------------------------------------------------------------
# 有限集成：真实 service 链路 + mock IO/模型
# ---------------------------------------------------------------------------

def test_limited_api_integration(monkeypatch):
    """真实 service/context/prompt/validator；Mock 持仓、复盘、模型流。"""
    pf_data = {
        "holdings": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "price": 1800.0,
                "shares": 1500,
                "cost": 1600.0,
                "market_value": 2700000.0,
                "pnl": 300000.0,
                "pnl_pct": 12.5,
            },
            {
                "code": "000001",
                "name": "平安银行",
                "price": 10.0,
                "shares": 1000,
                "cost": 9.0,
                "market_value": 10000.0,
                "pnl": 1000.0,
                "pnl_pct": 11.11,
            },
        ],
        "totals": {
            "market_value": 2710000.0,
            "cost": 2409000.0,
            "pnl": 301000.0,
            "pnl_pct": 12.49,
        },
        "closed": [],
        "realized_pnl": 0.0,
        "updated": "2026-07-21 15:00",
        "last_refresh": None,
    }
    review = {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": "partial",
        "warnings": ["测试 partial"],
        "data_health": {
            "components": {
                "indices": "normal",
                "breadth": "partial",
                "emotion": "normal",
                "turnover": "normal",
                "industry_boards": "normal",
                "concept_boards": "normal",
                "region_boards": "normal",
            }
        },
        "market_environment": {
            "indices": {"status": "normal", "data": []},
            "global_indices": {"status": "normal", "data": []},
            "breadth": {
                "status": "partial",
                "source": "test",
                "warnings": [],
                "data": {
                    "stock_count": 100,
                    "valid_count": 90,
                    "up_count": 40,
                    "down_count": 50,
                    "flat_count": 0,
                    "up_ratio": 0.44,
                    "up_3pct_count": 5,
                    "down_3pct_count": 8,
                    "total_amount": 1e11,
                    "amount_valid_count": 90,
                },
            },
        },
        "short_term_emotion": {
            "status": "normal",
            "source": "test",
            "warnings": [],
            "data": {
                "date": "2026-07-21",
                "zt_count": 10,
                "dt_count": 2,
                "zb_count": 3,
                "max_boards": 2,
                "lianban_count": 1,
                "seal_rate": 0.7,
                "break_rate": 0.3,
                "promotion_rate": 0.2,
                "yzt_count": 5,
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
            "total_amount": 1e11,
            "amount_valid_count": 90,
            "amount_top": [],
            "high_turnover": [],
        },
    }
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
                "price_conditions": [],
                "execution_plan": ["减20%"],
                "risk_conditions": [],
                "invalidation_conditions": [],
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
                "execution_plan": ["加"],
                "risk_conditions": [],
                "invalidation_conditions": [],
                "confidence": "low",
                "data_limitations": [],
            },
        ],
        "warnings": [],
        "data_limitations": [],
    }

    monkeypatch.setattr("portfolio.get_portfolio", lambda: pf_data)
    monkeypatch.setattr("daily_review.generate_daily_review", lambda: review)

    def fake_stream(cfg, messages, *, use_tools=False):
        assert use_tools is False
        text = json.dumps(model, ensure_ascii=False)
        yield {"type": "delta", "text": text}
        yield {"type": "done", "trace": [], "rounds": 1}

    monkeypatch.setattr(chat_layer, "stream_messages", fake_stream)
    monkeypatch.setattr(app_module.pf, "add_holding", _fail)
    monkeypatch.setattr(app_module.pf, "close_position", _fail)

    r = client.post(
        "/api/portfolio/advice",
        json={"user_request": "关注减仓", "llm": _LLM},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()["data"]
    assert data["schema_version"] == "portfolio-advice-v0.1"
    by = {h["code"]: h for h in data["holdings"]}
    assert by["600519"]["name"] == "贵州茅台"
    assert by["600519"]["shares"] == 1500
    assert by["600519"]["execution_quantity"] == 300
    assert by["000001"]["action"] == "add"
    assert by["000001"]["execution_quantity"] is None
    assert _has_key(data, "t_trade") is False
