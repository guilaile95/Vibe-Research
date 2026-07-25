"""持仓建议错误分类回归：内部错误不得伪装为「请求参数无效」。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import ai_result_service
import portfolio_advice_service as advice_svc

client = TestClient(app_module.app)

_LLM = {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "baseURL": "http://example.test/v1",
    "apiKey": "sk-test-secret",
}

_CLI_LLM = {
    "provider": "cli-claude",
    "model": "claude-code",
    "baseURL": "",
    "apiKey": "",
}


def test_legal_api_llm_enters_service(monkeypatch):
    gen = MagicMock(return_value={"schema_version": "portfolio-advice-v0.1"})
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    r = client.post("/api/portfolio/advice", json={"user_request": None, "llm": _LLM})
    assert r.status_code == 200
    gen.assert_called_once()
    assert gen.call_args[0][0]["provider"] == "deepseek"


def test_legal_cli_llm_enters_service(monkeypatch):
    gen = MagicMock(return_value={"schema_version": "portfolio-advice-v0.1"})
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    # 不依赖本机是否真的安装了 CLI
    monkeypatch.setattr(app_module.cli_runtime, "detect_cli", lambda _kind: "/usr/bin/claude")
    r = client.post("/api/portfolio/advice", json={"user_request": None, "llm": _CLI_LLM})
    assert r.status_code == 200
    assert gen.call_args[0][0]["provider"] == "cli-claude"
    assert gen.call_args[0][0]["apiKey"] == ""


def test_extra_fields_rejected_422():
    r = client.post(
        "/api/portfolio/advice",
        json={"llm": _LLM, "holdings": [], "context": {}},
    )
    assert r.status_code == 422


def test_empty_holdings_409(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=advice_svc.PortfolioAdviceUnavailableError("当前没有持仓，无法生成持仓操作建议")),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 409


def test_market_unavailable_503(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=advice_svc.PortfolioAdviceMarketDataError("市场核心数据暂不可用")),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 503


def test_model_error_502(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=advice_svc.PortfolioAdviceModelError("x")),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 502
    assert r.json()["detail"] == "持仓建议模型调用失败"


def test_model_auth_error_502_classified(monkeypatch):
    """假 key / HTTP 401 应映射为鉴权失败文案，而非笼统「模型调用失败」。"""
    inner = RuntimeError(
        '模型接口 HTTP 401: {"error":{"message":"Authentication Fails, Your api key: ****test is invalid"}}'
    )
    err = advice_svc.PortfolioAdviceModelError(
        advice_svc.public_model_error_detail(inner)
    )
    err.__cause__ = inner
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=err),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail == "持仓建议模型鉴权失败，请检查 API Key 或重新登录 CLI"
    assert "sk-" not in detail
    assert "****" not in detail
    assert "invalid" not in detail.lower()


def test_model_network_error_502_classified(monkeypatch):
    inner = RuntimeError("HTTPSConnectionPool: Max retries exceeded with url")
    err = advice_svc.PortfolioAdviceModelError(
        advice_svc.public_model_error_detail(inner)
    )
    err.__cause__ = inner
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=err),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 502
    assert r.json()["detail"] == "持仓建议模型网络调用失败，请检查网络后重试"


def test_missing_api_key_400(monkeypatch):
    gen = MagicMock(return_value={"schema_version": "portfolio-advice-v0.1"})
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    r = client.post(
        "/api/portfolio/advice",
        json={
            "llm": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "baseURL": "http://example.test/v1",
                "apiKey": "",
            }
        },
    )
    assert r.status_code == 400
    assert "接入 AI" in r.json()["detail"] or "API Key" in r.json()["detail"]
    gen.assert_not_called()


def test_missing_model_400(monkeypatch):
    gen = MagicMock(return_value={"schema_version": "portfolio-advice-v0.1"})
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    r = client.post(
        "/api/portfolio/advice",
        json={
            "llm": {
                "provider": "deepseek",
                "model": "",
                "baseURL": "http://example.test/v1",
                "apiKey": "sk-x",
            }
        },
    )
    assert r.status_code == 400
    assert "模型" in r.json()["detail"]
    gen.assert_not_called()


def test_cli_not_installed_400(monkeypatch):
    gen = MagicMock(return_value={"schema_version": "portfolio-advice-v0.1"})
    monkeypatch.setattr(app_module.portfolio_advice_service, "generate_portfolio_advice", gen)
    monkeypatch.setattr(app_module.cli_runtime, "detect_cli", lambda _kind: None)
    r = client.post("/api/portfolio/advice", json={"user_request": None, "llm": _CLI_LLM})
    assert r.status_code == 400
    assert "未检测到" in r.json()["detail"]
    gen.assert_not_called()


def test_model_output_error_502(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=advice_svc.PortfolioAdviceModelOutputError("bad json")),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 502
    assert r.json()["detail"] == "持仓建议模型输出无效"


def test_internal_typeerror_is_500_not_param_invalid(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=TypeError("unexpected internal")),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 500
    assert r.json()["detail"] != "持仓建议请求参数无效"
    assert "请求参数无效" not in r.json()["detail"]


def test_internal_valueerror_is_500_not_param_invalid(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=ValueError("trade_date 必须是 YYYY-MM-DD")),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 500
    assert "请求参数无效" not in r.json()["detail"]


def test_persist_error_500(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(side_effect=advice_svc.PortfolioAdvicePersistError(stage="save")),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 500
    assert "保存" in r.json()["detail"]


def test_fingerprint_accepts_integral_float_shares():
    fp = ai_result_service.compute_portfolio_fingerprint(
        [{"code": "600519", "shares": 1000.0, "cost": 10.5}]
    )
    assert isinstance(fp, str) and len(fp) == 64


def test_prepare_rejects_missing_trade_date(monkeypatch):
    monkeypatch.setattr(
        "portfolio_advice_service.portfolio.get_portfolio",
        lambda: {
            "holdings": [{"code": "600519", "name": "x", "shares": 100, "cost": 10.0, "price": 12.0}],
        },
    )
    monkeypatch.setattr(
        "portfolio_advice_service.daily_review.generate_daily_review",
        lambda: {
            "status": "normal",
            "trade_date": None,
            "data_health": {"components": {"breadth": "normal"}},
            "market_environment": {"breadth": {"status": "normal"}},
        },
    )
    with pytest.raises(advice_svc.PortfolioAdviceMarketDataError) as ei:
        advice_svc.prepare_portfolio_advice_messages()
    assert "交易日" in str(ei.value)


def test_public_model_error_detail_classifies_auth_and_strips_secrets():
    raw = RuntimeError(
        '模型接口 HTTP 401: {"error":{"message":"Authentication Fails, Your api key: sk-secret is invalid","type":"authentication_error"}}'
    )
    detail = advice_svc.public_model_error_detail(raw)
    assert detail == "持仓建议模型鉴权失败，请检查 API Key 或重新登录 CLI"
    assert "sk-secret" not in detail
    assert "Authentication" not in detail


def test_public_model_error_detail_cli_unavailable():
    import cli_runtime

    exc = cli_runtime.CliUnavailable(
        "未检测到「claude」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。"
    )
    detail = advice_svc.public_model_error_detail(exc)
    assert "未检测到" in detail
    assert "claude" in detail
