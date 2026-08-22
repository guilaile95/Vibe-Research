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
    # P0-SEC2：模拟已 opt-in + 鉴权 + claude 已证明 text-only 的部署
    monkeypatch.setattr(app_module.cli_runtime, "VR_ENABLE_LOCAL_CLI", True)
    monkeypatch.setattr(app_module.cli_runtime, "VR_API_KEY", "test-key")
    monkeypatch.setitem(
        app_module.cli_runtime.CLI_SECURITY_CAPABILITIES, "claude",
        {"text_only_proven": True, "proof_mode": "TEST", "http_allowed": True},
    )
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
    # P0-SEC2：先满足执行门（opt-in + 鉴权 + proven），再验证「已授权但 CLI 未安装 → 400」
    monkeypatch.setattr(app_module.cli_runtime, "VR_ENABLE_LOCAL_CLI", True)
    monkeypatch.setattr(app_module.cli_runtime, "VR_API_KEY", "test-key")
    monkeypatch.setitem(
        app_module.cli_runtime.CLI_SECURITY_CAPABILITIES, "claude",
        {"text_only_proven": True, "proof_mode": "TEST", "http_allowed": True},
    )
    monkeypatch.setattr(app_module.cli_runtime, "detect_cli", lambda _kind: None)
    r = client.post("/api/portfolio/advice", json={"user_request": None, "llm": _CLI_LLM})
    assert r.status_code == 400
    assert "未检测到" in r.json()["detail"]
    gen.assert_not_called()


def test_model_output_error_502(monkeypatch):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "generate_portfolio_advice",
        MagicMock(
            side_effect=advice_svc.PortfolioAdviceModelOutputError(
                "bad json", stage="json_parse", reason="持仓建议模型输出不是有效的JSON对象"
            )
        ),
    )
    r = client.post("/api/portfolio/advice", json={"llm": _LLM})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["message"] == "持仓建议模型输出无效"
    assert detail["error_code"] == "PORTFOLIO_ADVICE_OUTPUT_INVALID"
    assert detail["stage"] == "json_parse"
    assert detail["reason"] == "持仓建议模型输出不是有效的JSON对象"


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


# ---------------------------------------------------------------------------
# Product Reality：输出无效必须给出确切失败阶段与安全原因（不再只有一句静态文案）。
# 走真实 service → pipeline → validator 链路，仅注入 prepare / model runner / archive。
# ---------------------------------------------------------------------------

import json as _json

import decision_evidence_service
import signal_ledger_service


def _diag_context():
    return {
        "holdings": [{
            "code": "002031", "name": "股002031", "shares": 100, "cost_price": 10.0,
            "current_price": 12.0, "market_value": 1200.0, "pnl_amount": 200.0,
            "pnl_pct": 20.0, "holding_weight_pct": 100.0,
        }],
        "market_evidence": {"trade_date": "2026-08-23", "review_status": "normal"},
        "market_context": {"review_metadata": {"status": "normal", "trade_date": "2026-08-23"}},
        "portfolio_meta": {"trade_date": "2026-08-23"},
        "data_limitations": [],
        "warnings": [],
    }


def _prepared_payload():
    return {
        "portfolio": {
            "holdings": [{"code": "002031", "name": "股002031", "shares": 100,
                          "cost": 10.0, "price": 12.0, "market_value": 1200.0,
                          "pnl": 200.0, "pnl_pct": 20.0}],
            "totals": {"market_value": 1200.0, "cost": 1000.0, "pnl": 200.0, "pnl_pct": 20.0},
        },
        "input_fingerprint": "f" * 64,
        "daily_review": {"trade_date": "2026-08-23", "generated_at": "2026-08-23 15:00:00"},
        "context": _diag_context(),
        "context_json": "{}",
        "messages": [],
    }


def _ai_holding_text(action="hold", pct=None, trigger="市场广度修复后可继续持有"):
    holding = {
        "code": "002031", "name": "股002031", "action": action,
        "execution_size_pct_of_holding": pct, "execution_quantity": None,
        "trigger_conditions": [trigger],
        "price_conditions": [], "execution_plan": ["按计划持有"],
        "risk_conditions": ["个股相对板块明显转弱"],
        "invalidation_conditions": ["原风险证据消失"],
        "confidence": "medium", "data_limitations": [],
    }
    return _json.dumps({
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-08-23 15:30:00",
        "market_status": "normal",
        "portfolio_summary": {"holding_count": 1, "market_value": 1200.0,
                              "cost": 1000.0, "pnl": 200.0, "pnl_pct": 20.0},
        "account_action": {"action": "hold", "reason": "结构完整", "confidence": "medium"},
        "holdings": [holding],
        "warnings": [], "data_limitations": [],
    }, ensure_ascii=False)


def _post_with_model_output(monkeypatch, model_text):
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "prepare_portfolio_advice_messages",
        MagicMock(return_value=_prepared_payload()),
    )
    monkeypatch.setattr(
        app_module.portfolio_advice_service,
        "_default_model_runner",
        MagicMock(return_value=model_text),
    )
    monkeypatch.setattr(
        app_module.ai_result_service,
        "save_portfolio_advice",
        MagicMock(return_value={"trade_date": "2026-08-23"}),
    )
    monkeypatch.setattr(decision_evidence_service, "archive_decision_evidence", MagicMock())
    monkeypatch.setattr(signal_ledger_service, "archive_signal_ledger", MagicMock())
    return client.post("/api/portfolio/advice", json={"llm": _LLM})


def test_valid_model_output_succeeds(monkeypatch):
    r = _post_with_model_output(monkeypatch, _ai_holding_text())
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["data"]["holdings"][0]["action"] == "hold"


def test_malformed_json_diagnoses_parse_stage(monkeypatch):
    r = _post_with_model_output(monkeypatch, "好的，以下是建议：\n" + _ai_holding_text())
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["error_code"] == "PORTFOLIO_ADVICE_OUTPUT_INVALID"
    assert detail["stage"] == "json_parse"
    assert "JSON" in detail["reason"]


def test_invalid_action_diagnoses_schema_stage(monkeypatch):
    r = _post_with_model_output(monkeypatch, _ai_holding_text(action="trim"))
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["stage"] == "schema_validation"
    assert "非法 action" in detail["reason"]
    assert "trim" in detail["reason"]


def test_off_tier_reduce_diagnoses_policy_stage(monkeypatch):
    r = _post_with_model_output(monkeypatch, _ai_holding_text(action="reduce", pct=25))
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["stage"] == "policy_audit"
    assert "reduce" in detail["reason"]
    assert "25" in detail["reason"]
    assert "002031" in detail["reason"]


def test_untraceable_number_diagnoses_narrative_stage(monkeypatch):
    r = _post_with_model_output(
        monkeypatch, _ai_holding_text(trigger="跌破 9.9 元后减仓")
    )
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["stage"] == "narrative_audit"
    assert "无法追溯的数字" in detail["reason"]
    assert "9.9" in detail["reason"]


def test_diagnostic_detail_is_safe(monkeypatch):
    r = _post_with_model_output(monkeypatch, _ai_holding_text(action="reduce", pct=25))
    detail = r.json()["detail"]
    # 不泄露请求中的 API key、prompt 或路径
    serialized = _json.dumps(detail, ensure_ascii=False)
    assert "sk-test-secret" not in serialized
    assert "http://" not in serialized
    assert "baseURL" not in serialized
    assert set(detail) == {"message", "error_code", "stage", "reason"}
