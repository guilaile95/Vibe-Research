"""P0-DS1 — cap.security.financials evaluator 专项测试。

全部注入 fake financials reader；不访问真实数据源、不发网络请求。
核心语义：真实 retrieval 成功也绝不 USABLE —— report-period
applicability 无 authority，capability 恒 NOT_EVALUATED 且 blocker
显式为 REPORT_PERIOD_APPLICABILITY_NOT_RESOLVED（不是 NO_ADAPTER）。
"""
from __future__ import annotations

import pytest

import critical_data_financials_adapter as adapter
from critical_data_financials_adapter import (
    ADAPTER_AUTHORITY_REF,
    FinancialsCapabilityError,
    REPORT_PERIOD_BLOCKER_REF,
    evaluate_financials_capability,
)

SECURITY = "600519"
CAMPAIGN = "campaign_" + "a" * 32
AS_OF = "2026-08-13T04:00:00.000000Z"


def _payload(**overrides):
    base = {
        "period": "2025-12-31",
        "revenue": 123.45e8,
        "net_profit": 40.5e8,
        "roe": 20.1,
    }
    base.update(overrides)
    return base


def _evaluate(reader, *, as_of: str = AS_OF):
    return evaluate_financials_capability(
        security_code=SECURITY,
        campaign_id=CAMPAIGN,
        as_of=as_of,
        financials_reader=reader,
    )


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        {"security_code": "bad"},
        {"campaign_id": "nope"},
        {"as_of": ""},
    ],
)
def test_invalid_inputs_raise(kwargs):
    params = {
        "security_code": SECURITY,
        "campaign_id": CAMPAIGN,
        "as_of": AS_OF,
        **kwargs,
    }
    with pytest.raises(FinancialsCapabilityError):
        evaluate_financials_capability(**params)


# ---------------------------------------------------------------------------
# retrieval 语义
# ---------------------------------------------------------------------------

def test_reader_exception_is_error():
    def broken(_code):
        raise RuntimeError("provider down")

    assert _evaluate(broken)["state"] == "ERROR"


def test_reader_none_is_unknown():
    assert _evaluate(lambda _code: None)["state"] == "UNKNOWN"


def test_reader_non_mapping_is_error():
    assert _evaluate(lambda _code: "bad")["state"] == "ERROR"


def test_empty_payload_is_unknown_data_missing():
    """真实检索成功但无数据 → UNKNOWN（数据缺失，非 provider failure）。"""
    assert _evaluate(lambda _code: {})["state"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# report-period applicability blocker（§11-F）
# ---------------------------------------------------------------------------

def test_retrieval_success_never_forges_usable():
    """真实 retrieval 成功 → 仍 NOT_EVALUATED，绝不把 provider 最新报告期
    当作 authoritative latest。"""
    result = _evaluate(lambda _code: _payload())
    assert result["state"] == "NOT_EVALUATED"
    refs = result["authority_refs"]
    assert ADAPTER_AUTHORITY_REF in refs
    assert "financials:provider-claimed-period=2025-12-31" in refs
    # 显式 blocker：applicability 未解决，而不是 NO_ADAPTER
    assert REPORT_PERIOD_BLOCKER_REF in refs


def test_retrieval_success_without_period_still_blocked():
    """period 字段缺失同样 NOT_EVALUATED + 显式 blocker。"""
    result = _evaluate(lambda _code: {"revenue": 1.0})
    assert result["state"] == "NOT_EVALUATED"
    assert REPORT_PERIOD_BLOCKER_REF in result["authority_refs"]
    assert not any(
        ref.startswith("financials:provider-claimed-period=")
        for ref in result["authority_refs"]
    )


def test_dataset_semantics_ref_present():
    """provenance 对齐 ds_financial_indicator dataset 语义常量。"""
    result = _evaluate(lambda _code: _payload())
    assert any(
        ref.startswith("dataset-semantics:ds_financial_indicator:")
        for ref in result["authority_refs"]
    )


def test_result_identity_and_as_of():
    result = _evaluate(lambda _code: _payload())
    assert result["dependency_id"] == adapter.DEPENDENCY_ID
    assert result["as_of"] == AS_OF
