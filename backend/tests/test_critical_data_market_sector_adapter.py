"""P0-DS1 — cap.context.market_sector evaluator 专项测试。

全部注入 fake market reader / calendar；不访问真实数据源、不发网络请求。
覆盖：输入校验、retrieval time ≠ fact time、STALE 不冒充 current、
provider failure / partial 诚实映射、USABLE positive proof。
"""
from __future__ import annotations

import pytest

import critical_data_market_sector_adapter as adapter
from critical_data_market_sector_adapter import (
    ADAPTER_AUTHORITY_REF,
    SECTOR_CONTEXT_BLOCKER_REF,
    MarketSectorCapabilityError,
    evaluate_market_sector_capability,
)

SECURITY = "600519"
CAMPAIGN = "campaign_" + "a" * 32
AS_OF = "2026-08-13T04:00:00.000000Z"
TRADE_DATE = "2026-08-13"


def _envelope(**overrides):
    base = {
        "status": "normal",
        "source": "eastmoney_push2",
        "trade_date": TRADE_DATE,
        "data_time": "15:00:00",
        "fetched_at": "2026-08-13 15:05:00",
        "is_stale": False,
        "warnings": [],
        "data": {
            "stock_count": 5400,
            "up_count": 2900,
            "down_count": 2400,
            "up_ratio": 53.7,
            "limit_up_count": 60,
            "limit_down_count": 5,
        },
    }
    base.update(overrides)
    return base


def _industry_reader(industry: str | None):
    """sector_reader fake：industry=None 表示无法证明板块上下文。"""

    def _reader(_code):
        if industry is None:
            return {}
        return {"行业": industry, "总股本": 1.26e9}

    return _reader


def _evaluate(
    reader,
    *,
    calendar=lambda _as_of: TRADE_DATE,
    as_of: str = AS_OF,
    sector_reader=None,
):
    return evaluate_market_sector_capability(
        security_code=SECURITY,
        campaign_id=CAMPAIGN,
        as_of=as_of,
        market_reader=reader,
        sector_reader=sector_reader or _industry_reader("白酒"),
        calendar=calendar,
    )


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        {"security_code": "bad"},
        {"security_code": "6005190"},
        {"security_code": 600519},
        {"campaign_id": "nope"},
        {"as_of": ""},
        {"as_of": "not-a-timestamp"},
    ],
)
def test_invalid_inputs_raise(kwargs):
    params = {
        "security_code": SECURITY,
        "campaign_id": CAMPAIGN,
        "as_of": AS_OF,
        **kwargs,
    }
    with pytest.raises(MarketSectorCapabilityError):
        evaluate_market_sector_capability(**params)


# ---------------------------------------------------------------------------
# 时间闸门
# ---------------------------------------------------------------------------

def test_no_completed_trade_date_is_not_evaluated():
    result = _evaluate(_envelope, calendar=lambda _as_of: None)
    assert result["state"] == "NOT_EVALUATED"
    assert ADAPTER_AUTHORITY_REF in result["authority_refs"]


def test_reader_exception_is_error():
    def broken():
        raise RuntimeError("provider down")

    result = _evaluate(broken)
    assert result["state"] == "ERROR"


def test_reader_none_or_non_mapping_is_error():
    assert _evaluate(lambda: None)["state"] == "ERROR"
    assert _evaluate(lambda: "not-a-mapping")["state"] == "ERROR"


def test_envelope_unavailable_is_error():
    result = _evaluate(lambda: _envelope(status="unavailable", data=None))
    assert result["state"] == "ERROR"


def test_envelope_unknown_status_is_unknown():
    result = _evaluate(lambda: _envelope(status="bogus"))
    assert result["state"] == "UNKNOWN"


def test_missing_trade_date_is_unknown_not_fetched_at_fallback():
    """无 market fact time → UNKNOWN；绝不拿 fetched_at 冒充。"""
    result = _evaluate(lambda: _envelope(trade_date=None))
    assert result["state"] == "UNKNOWN"


def test_malformed_trade_date_is_error():
    result = _evaluate(lambda: _envelope(trade_date="2026/08/13"))
    assert result["state"] == "ERROR"


def test_future_trade_date_is_error():
    result = _evaluate(lambda: _envelope(trade_date="2026-08-14"))
    assert result["state"] == "ERROR"


def test_old_trade_date_is_stale_not_current():
    """§11-D：STALE 数据不冒充 current。"""
    result = _evaluate(lambda: _envelope(trade_date="2026-08-12"))
    assert result["state"] == "STALE"


# ---------------------------------------------------------------------------
# partial / 完整性
# ---------------------------------------------------------------------------

def test_partial_envelope_is_unknown_with_warning_refs():
    result = _evaluate(lambda: _envelope(
        status="partial",
        warnings=["全市场股票数量偏少：stock_count=100（阈值 3000）"],
    ))
    assert result["state"] == "UNKNOWN"
    assert any(
        ref.startswith("market-breadth:partial:")
        for ref in result["authority_refs"]
    )


def test_normal_without_data_is_unknown():
    assert _evaluate(lambda: _envelope(data=None))["state"] == "UNKNOWN"
    assert _evaluate(lambda: _envelope(data={}))["state"] == "UNKNOWN"


def test_normal_with_invalid_stock_count_is_unknown():
    assert _evaluate(lambda: _envelope(
        data={"stock_count": 0, "up_count": 0, "down_count": 0}
    ))["state"] == "UNKNOWN"


def test_normal_complete_is_usable_with_provenance():
    result = _evaluate(lambda: _envelope())
    assert result["state"] == "USABLE"
    assert result["dependency_id"] == "cap.context.market_sector"
    assert result["as_of"] == AS_OF
    refs = result["authority_refs"]
    assert ADAPTER_AUTHORITY_REF in refs
    assert any(ref.startswith("market-breadth:source=") for ref in refs)
    assert f"market-breadth:trade_date={TRADE_DATE}" in refs
    assert any(ref.startswith("market-breadth:fetched_at=") for ref in refs)
    assert "market-breadth:stock_count=5400" in refs


def test_result_uses_dependency_id_and_as_of():
    result = _evaluate(lambda: _envelope())
    assert result["dependency_id"] == adapter.DEPENDENCY_ID
    assert result["as_of"] == AS_OF


# ---------------------------------------------------------------------------
# §6-C/D：security-relevant sector context（market alone 不得 USABLE）
# ---------------------------------------------------------------------------

def test_market_alone_without_sector_context_is_not_usable():
    """§6-C：市场可用 + sector 缺失 → NOT USABLE + 显式 blocker。"""
    result = _evaluate(
        lambda: _envelope(),
        sector_reader=_industry_reader(None),
    )
    assert result["state"] == "UNKNOWN"
    assert SECTOR_CONTEXT_BLOCKER_REF in result["authority_refs"]


def test_market_plus_sector_proof_is_usable():
    """§6-D：市场 + security 板块正向证明 → USABLE（带板块 ref）。"""
    result = _evaluate(lambda: _envelope(), sector_reader=_industry_reader("白酒"))
    assert result["state"] == "USABLE"
    assert "market-sector:security-industry=白酒" in result["authority_refs"]


def test_sector_reader_exception_is_error():
    def broken(_code):
        raise RuntimeError("sector provider down")

    result = _evaluate(lambda: _envelope(), sector_reader=broken)
    assert result["state"] == "ERROR"


def test_sector_reader_none_or_non_mapping_is_unknown_with_blocker():
    assert _evaluate(
        lambda: _envelope(), sector_reader=lambda _code: None
    )["state"] == "UNKNOWN"
    result = _evaluate(lambda: _envelope(), sector_reader=lambda _code: "bad")
    assert result["state"] == "UNKNOWN"
    assert SECTOR_CONTEXT_BLOCKER_REF in result["authority_refs"]


def test_sector_missing_industry_key_is_unknown_with_blocker():
    result = _evaluate(
        lambda: _envelope(),
        sector_reader=lambda _code: {"总股本": 1.0},
    )
    assert result["state"] == "UNKNOWN"
    assert SECTOR_CONTEXT_BLOCKER_REF in result["authority_refs"]


def test_market_stale_short_circuits_even_with_sector_proof():
    """STALE 市场快照不因 sector 证明而救回。"""
    result = _evaluate(
        lambda: _envelope(trade_date="2026-08-12"),
        sector_reader=_industry_reader("白酒"),
    )
    assert result["state"] == "STALE"
