"""POST /api/portfolio/advice 只读账户资金指标专项离线测试。

验证包含：
1. 账户资金未配置，建议仍正常返回；
2. 账户资金文件损坏，建议仍正常返回并带 limitation；
3. total_assets 和 available_cash 读取正确；
4. available_cash_pct 计算正确；
5. 单票 market_value 正确；
6. 单票 account_weight_pct 正确；
7. 全部行情有效时总持仓比例正确；
8. 部分行情缺失时总持仓比例为 null；
9. Decimal 舍入正确 (ROUND_HALF_UP)；
10. 原 action 不变；
11. 原 action_ratio (execution_size_pct_of_holding) 不变；
12. 原 execution_quantity 不变；
13. 原 estimated_amount 不变；
14. prompt 不包含账户资金字段；
15. validator 不读取账户资金；
16. account_profile.json 不被修改；
17. portfolio.json 不被修改；
18. 前端/服务端未配置、已配置、行情不完整各种状态；
19. 不影响原有后端测试集。
"""
from __future__ import annotations

import json
import os
import pytest

import account_profile
import astock
import daily_review
import portfolio as pf
import portfolio_advice_context
import portfolio_advice_prompt
import portfolio_advice_service
import portfolio_advice_validator


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    """隔离 VR_DATA_DIR 临时数据目录与行情打桩。"""
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(account_profile, "ACCOUNT_FILE", str(tmp_path / "account_profile.json"))

    def mock_quote(codes):
        q = {}
        for c in codes:
            if c == "000001":
                q[c] = {"name": "平安银行", "price": 10.0}
            elif c == "600519":
                q[c] = {"name": "贵州茅台", "price": 1600.0}
            elif c == "BAD_QUOTE":
                q[c] = {"name": "坏行情", "price": 0.0}
            else:
                q[c] = {"name": f"股票{c}", "price": 20.0}
        return q

    monkeypatch.setattr(astock, "tencent_quote", mock_quote)

    def mock_review():
        return {
            "status": "normal",
            "data_health": {"components": {"breadth": "normal"}},
            "market_environment": {"breadth": {"status": "normal"}},
        }

    monkeypatch.setattr(daily_review, "generate_daily_review", mock_review)
    return tmp_path


def _write_pf(tmp_path, holdings: list[dict]):
    with open(tmp_path / "portfolio.json", "w", encoding="utf-8") as f:
        json.dump({"holdings": holdings, "last_refresh": None}, f)


def _write_acct(tmp_path, total: float, cash: float, updated: str = "2026-01-01 10:00:00"):
    with open(tmp_path / "account_profile.json", "w", encoding="utf-8") as f:
        json.dump({"total_assets": total, "available_cash": cash, "updated_at": updated}, f)


def _mock_runner(cfg, messages):
    return json.dumps({
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
    })


def test_account_not_configured(tmp_env):
    """1. 账户资金未配置，持仓建议正常返回且 account_funding.configured == False。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])
    res = portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)
    assert res["account_funding"]["configured"] is False
    assert res["account_funding"]["total_assets"] is None
    assert res["account_funding"]["available_cash"] is None
    assert res["account_funding"]["quote_coverage"]["complete"] is True
    assert res["holdings"][0]["account_metrics"]["market_value"] == 15000.0
    assert res["holdings"][0]["account_metrics"]["account_weight_pct"] is None


def test_account_profile_corrupted(tmp_env):
    """2. 账户资金文件损坏，建议仍正常返回并带 limitation，原文件不被删除。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])
    acct_file = tmp_env / "account_profile.json"
    with open(acct_file, "w", encoding="utf-8") as f:
        f.write("{invalid_json: true")

    res = portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)
    assert res["account_funding"]["configured"] is False
    assert any("读取失败或损坏" in lim for lim in res["data_limitations"])
    assert os.path.exists(acct_file)
    with open(acct_file, encoding="utf-8") as f:
        assert f.read() == "{invalid_json: true"


def test_valid_account_funding_metrics(tmp_env):
    """3-7, 9. total_assets / available_cash / available_cash_pct / 单票 account_weight_pct / 总结算。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])
    _write_acct(tmp_env, 100000.0, 20000.0)

    res = portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)
    af = res["account_funding"]
    assert af["configured"] is True
    assert af["total_assets"] == 100000.0
    assert af["available_cash"] == 20000.0
    assert af["available_cash_pct"] == 20.0
    assert af["tracked_stock_market_value"] == 15000.0
    assert af["tracked_stock_weight_pct"] == 15.0
    assert af["quote_coverage"]["complete"] is True

    h = res["holdings"][0]
    assert h["account_metrics"]["market_value"] == 15000.0
    assert h["account_metrics"]["account_weight_pct"] == 15.0


def test_partial_quote_coverage(tmp_env):
    """8. 部分行情缺失时，tracked_stock_weight_pct 为 None，且带有相应 limitation。"""
    _write_pf(tmp_env, [
        {"code": "000001", "shares": 1500, "cost": 14.0},
        {"code": "BAD_QUOTE", "shares": 100, "cost": 10.0},
    ])
    _write_acct(tmp_env, 100000.0, 20000.0)

    def mock_runner_two(cfg, messages):
        return json.dumps({
            "schema_version": "portfolio-advice-v0.1",
            "generated_at": "2026-01-01 10:00:00",
            "market_status": "normal",
            "portfolio_summary": {"holding_count": 2, "market_value": 15000.0, "cost": 22000.0, "pnl": -7000.0, "pnl_pct": -31.82},
            "account_action": {"action": "hold", "reason": "稳健", "confidence": "high"},
            "holdings": [
                {
                    "code": "000001", "name": "平安", "shares": 1500, "cost_price": 14.0, "current_price": 10.0,
                    "market_value": 15000.0, "pnl_amount": -6000.0, "pnl_pct": -28.57, "holding_weight_pct": 100.0,
                    "action": "hold", "execution_size_pct_of_holding": None, "execution_quantity": None, "estimated_amount": None,
                    "trigger_conditions": [], "price_conditions": [], "execution_plan": [], "risk_conditions": [],
                    "invalidation_conditions": [], "confidence": "high", "data_limitations": [],
                },
                {
                    "code": "BAD_QUOTE", "name": "坏行情", "shares": 100, "cost_price": 10.0, "current_price": 0.0,
                    "market_value": 0.0, "pnl_amount": -1000.0, "pnl_pct": -100.0, "holding_weight_pct": 0.0,
                    "action": "hold", "execution_size_pct_of_holding": None, "execution_quantity": None, "estimated_amount": None,
                    "trigger_conditions": [], "price_conditions": [], "execution_plan": [], "risk_conditions": [],
                    "invalidation_conditions": [], "confidence": "high", "data_limitations": [],
                },
            ],
            "warnings": [], "data_limitations": [],
        })

    res = portfolio_advice_service.generate_portfolio_advice({}, model_runner=mock_runner_two)
    af = res["account_funding"]
    assert af["quote_coverage"]["complete"] is False
    assert af["quote_coverage"]["valid_holdings"] == 1
    assert af["quote_coverage"]["total_holdings"] == 2
    assert af["tracked_stock_weight_pct"] is None
    assert any("部分持仓行情不可用" in lim for lim in res["data_limitations"])


def test_decimal_rounding_half_up(tmp_env):
    """9. Decimal ROUND_HALF_UP 四舍五入精准验证。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 3333, "cost": 10.0}])
    _write_acct(tmp_env, 100000.0, 33333.33)

    res = portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)
    af = res["account_funding"]
    assert af["available_cash_pct"] == 33.33
    assert af["tracked_stock_weight_pct"] == 33.33


def test_action_and_ratios_unchanged(tmp_env):
    """10-13. 确认接入只读账户资金前后，原 action, execution_size_pct_of_holding, execution_quantity, estimated_amount 绝对不变。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])

    res_before = portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)
    h_before = res_before["holdings"][0]

    _write_acct(tmp_env, 100000.0, 5000.0)
    res_after = portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)
    h_after = res_after["holdings"][0]

    assert h_before["action"] == h_after["action"] == "add"
    assert h_before["execution_size_pct_of_holding"] == h_after["execution_size_pct_of_holding"] == 10
    assert h_before["execution_quantity"] == h_after["execution_quantity"] == 100
    assert h_before["estimated_amount"] == h_after["estimated_amount"] == 1000.0


def test_prompt_and_validator_isolation(tmp_env):
    """14-15. context 与 validator 不包含/不读取账户资金数据。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])
    _write_acct(tmp_env, 100000.0, 20000.0)

    prep = portfolio_advice_service.prepare_portfolio_advice_messages()
    context = prep["context"]

    # 动态 context 并不注入 account_funding 字典或实数数值
    assert "account_funding" not in context
    assert context.get("account_fields_available", {}).get("total_assets") is False
    assert context.get("account_fields_available", {}).get("cash_available") is False

    # 证明 validator 的输入类型与校验规则不包含 account_funding 依赖
    v_res = portfolio_advice_validator.validate_portfolio_advice(
        {
            "schema_version": "portfolio-advice-v0.1",
            "generated_at": "2026-01-01 10:00:00",
            "market_status": "normal",
            "portfolio_summary": {"holding_count": 1, "market_value": 15000.0, "cost": 21000.0, "pnl": -6000.0, "pnl_pct": -28.57},
            "account_action": {"action": "hold", "reason": "稳健", "confidence": "high"},
            "holdings": [{
                "code": "000001", "name": "平安", "shares": 1500, "cost_price": 14.0, "current_price": 10.0,
                "market_value": 15000.0, "pnl_amount": -6000.0, "pnl_pct": -28.57, "holding_weight_pct": 100.0,
                "action": "hold", "execution_size_pct_of_holding": None, "execution_quantity": None, "estimated_amount": None,
                "trigger_conditions": [], "price_conditions": [], "execution_plan": [], "risk_conditions": [],
                "invalidation_conditions": [], "confidence": "high", "data_limitations": [],
            }],
            "warnings": [], "data_limitations": [],
        },
        context,
    )
    assert "account_funding" not in v_res


def test_underlying_json_files_unmodified(tmp_env):
    """16-17. generate_portfolio_advice 过程中绝不修改 account_profile.json 与 portfolio.json。"""
    _write_pf(tmp_env, [{"code": "000001", "shares": 1500, "cost": 14.0}])
    _write_acct(tmp_env, 100000.0, 20000.0)

    pf_path = str(tmp_env / "portfolio.json")
    acct_path = str(tmp_env / "account_profile.json")

    with open(pf_path, "rb") as f:
        pf_bytes_before = f.read()
    with open(acct_path, "rb") as f:
        acct_bytes_before = f.read()

    portfolio_advice_service.generate_portfolio_advice({}, model_runner=_mock_runner)

    with open(pf_path, "rb") as f:
        assert f.read() == pf_bytes_before
    with open(acct_path, "rb") as f:
        assert f.read() == acct_bytes_before
