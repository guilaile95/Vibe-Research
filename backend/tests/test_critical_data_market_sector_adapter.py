"""P0-DS1 — cap.context.market_sector evaluator 专项测试。

全部注入 fake market reader / calendar；不访问真实数据源、不发网络请求。
覆盖：输入校验、retrieval time ≠ fact time、NO LOOKAHEAD、observation-time
归属（盘中/收盘后/周末）、provider 显式 trade_date 优先、
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
from trade_calendar import observation_trade_date_at

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


def _overview_fake(industry: str, *, updated: str | None = f"{TRADE_DATE} 15:05"):
    """sector observation fake：含匹配 industry 的板块条目 + freshness。"""

    def _reader():
        return {
            "sentiment": {},
            "sectors": [
                {"name": industry, "pct": 1.23, "net": 4.5e8,
                 "inflow": 1.0e9, "outflow": 5.5e8, "firms": 40},
                {"name": "银行", "pct": -0.1, "net": -1.0e8,
                 "inflow": 2.0e8, "outflow": 3.0e8, "firms": 42},
            ],
            "updated": updated,
        }

    return _reader


def _evaluate(
    reader,
    *,
    calendar=lambda _as_of: TRADE_DATE,
    as_of: str = AS_OF,
    sector_reader=None,
    sector_observation=None,
):
    return evaluate_market_sector_capability(
        security_code=SECURITY,
        campaign_id=CAMPAIGN,
        as_of=as_of,
        market_reader=reader,
        sector_reader=sector_reader or _industry_reader("白酒"),
        sector_observation_reader=sector_observation or _overview_fake("白酒"),
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
# 时间闸门 / temporal attribution（P0-RU2-R1）
# ---------------------------------------------------------------------------

def test_unresolvable_observation_date_is_not_evaluated():
    """缺失 trade_date 且观察时点无法映射交易日 → NOT_EVALUATED（不伪造日期）。"""
    result = _evaluate(
        lambda: _envelope(trade_date=None),
        calendar=lambda _inst: None,
    )
    assert result["state"] == "NOT_EVALUATED"
    assert ADAPTER_AUTHORITY_REF in result["authority_refs"]


def test_missing_or_invalid_observation_time_is_unknown():
    """真实获取时点缺失/非法 → 无法做 temporal attribution → UNKNOWN。"""
    assert _evaluate(
        lambda: _envelope(trade_date=None, fetched_at=None)
    )["state"] == "UNKNOWN"
    result = _evaluate(lambda: _envelope(fetched_at="2026/08/13 15:05:00"))
    assert result["state"] == "UNKNOWN"
    assert "market-breadth:observation-time=missing-or-invalid" in (
        result["authority_refs"]
    )


def test_reader_exception_is_error():
    def broken():
        raise RuntimeError("provider down")

    result = _evaluate(broken)
    assert result["state"] == "ERROR"


def test_impossible_as_of_date_fails_closed_as_error():
    """as_of 格式合规但非真实时刻（2月30日）→ 不得崩溃 → ERROR。"""
    result = _evaluate(lambda: _envelope(), as_of="2026-02-30T07:00:00Z")
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


def test_missing_trade_date_derives_from_observation_time():
    """真实 breadth 快照无 trade_date → 事实日期由真实 observation timestamp
    + 权威交易日历归属 MARKET OBSERVATION DATE；date-basis 显式
    observation-time，绝不写 calendar-derived。"""
    result = _evaluate(lambda: _envelope(trade_date=None))
    assert result["state"] == "USABLE"
    refs = result["authority_refs"]
    assert "market-breadth:date-basis=observation-time" in refs
    assert "market-breadth:observed_at=2026-08-13 15:05:00" in refs
    assert f"market-breadth:trade_date={TRADE_DATE}" in refs
    assert not any("calendar-derived" in ref for ref in refs)


def test_malformed_trade_date_is_error():
    result = _evaluate(lambda: _envelope(trade_date="2026/08/13"))
    assert result["state"] == "ERROR"


def test_provider_trade_date_after_as_of_is_not_evaluated():
    """provider trade_date 晚于 caller as_of → NO LOOKAHEAD → NOT_EVALUATED。"""
    result = _evaluate(lambda: _envelope(trade_date="2026-08-14"))
    assert result["state"] == "NOT_EVALUATED"
    assert "market-breadth:not-usable=fact-date-after-as_of" in (
        result["authority_refs"]
    )


def test_provider_historical_trade_date_within_as_of_is_usable():
    """provider 显式历史 trade_date（<= as_of）是可证明的历史 market
    observation → 可用且日期保留 provider 值（绝不重标为 caller as_of 日期）。"""
    result = _evaluate(lambda: _envelope(trade_date="2026-08-12"))
    assert result["state"] == "USABLE"
    refs = result["authority_refs"]
    assert "market-breadth:date-basis=provider-trade_date" in refs
    assert "market-breadth:trade_date=2026-08-12" in refs


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
    assert "market-breadth:date-basis=provider-trade_date" in refs
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


def test_lookahead_short_circuits_even_with_sector_proof():
    """观察时点晚于 as_of → NOT_EVALUATED，不因 sector 证明而救回。"""
    result = _evaluate(
        lambda: _envelope(trade_date=None, fetched_at="2026-08-14 10:00:00"),
        calendar=observation_trade_date_at,
        sector_reader=_industry_reader("白酒"),
    )
    assert result["state"] == "NOT_EVALUATED"
    assert "market-breadth:not-usable=fact-date-after-as_of" in (
        result["authority_refs"]
    )


# ---------------------------------------------------------------------------
# P0-RU2-R1：review required A–F
# ---------------------------------------------------------------------------

MONDAY = "2026-08-17"
FRIDAY = "2026-08-14"
MONDAY_MORNING_AS_OF = "2026-08-17T02:30:00.000000Z"  # 北京时间周一 10:30
SATURDAY_AS_OF = "2026-08-15T03:00:00.000000Z"  # 北京时间周六 11:00


def test_A_intraday_monday_observation_is_monday_not_friday():
    """A：周一盘中 10:30 实时快照 → date = 周一，绝不上周五 completed。"""
    result = _evaluate(
        lambda: _envelope(trade_date=None, fetched_at="2026-08-17 10:30:00"),
        as_of=MONDAY_MORNING_AS_OF,
        calendar=observation_trade_date_at,
        sector_observation=_overview_fake("白酒", updated="2026-08-17 10:35"),
    )
    assert result["state"] == "USABLE"
    refs = result["authority_refs"]
    assert f"market-breadth:trade_date={MONDAY}" in refs
    assert f"market-breadth:trade_date={FRIDAY}" not in refs
    assert "market-breadth:date-basis=observation-time" in refs
    assert "market-breadth:observed_at=2026-08-17 10:30:00" in refs


def test_B_post_close_monday_observation_is_monday():
    """B：周一收盘后快照 → date = 周一。"""
    result = _evaluate(
        lambda: _envelope(trade_date=None, fetched_at="2026-08-17 15:30:00"),
        as_of="2026-08-17T07:30:00.000000Z",  # 北京时间周一 15:30
        calendar=observation_trade_date_at,
        sector_observation=_overview_fake("白酒", updated="2026-08-17 15:35"),
    )
    assert result["state"] == "USABLE"
    assert f"market-breadth:trade_date={MONDAY}" in result["authority_refs"]


def test_C_weekend_observation_maps_to_recent_trading_day():
    """C：周末读取 → 最近交易日（周五），绝不伪造周末为交易日。"""
    result = _evaluate(
        lambda: _envelope(trade_date=None, fetched_at="2026-08-15 11:00:00"),
        as_of=SATURDAY_AS_OF,
        calendar=observation_trade_date_at,
        sector_observation=_overview_fake("白酒", updated="2026-08-15 11:05"),
    )
    assert result["state"] == "USABLE"
    refs = result["authority_refs"]
    assert f"market-breadth:trade_date={FRIDAY}" in refs
    assert "market-breadth:trade_date=2026-08-15" not in refs
    assert "market-breadth:date-basis=observation-time" in refs


def test_D_historical_as_of_with_live_snapshot_is_not_usable():
    """D：historical as_of + current/live 快照 → 不得重标为历史日期
    → NOT_EVALUATED（NO LOOKAHEAD）。"""
    result = _evaluate(
        lambda: _envelope(trade_date=None, fetched_at="2026-08-13 15:05:00"),
        as_of="2026-08-12T04:00:00.000000Z",  # 北京时间周三 12:00
        calendar=observation_trade_date_at,
    )
    assert result["state"] == "NOT_EVALUATED"
    refs = result["authority_refs"]
    assert "market-breadth:not-usable=fact-date-after-as_of" in refs
    assert "market-breadth:trade_date=2026-08-13" in refs


def test_E_explicit_provider_trade_date_is_preferred():
    """E：provider 显式 trade_date 优先于 observation-time 推导。"""
    result = _evaluate(
        lambda: _envelope(trade_date="2026-08-14",
                          fetched_at="2026-08-17 10:30:00"),
        as_of=MONDAY_MORNING_AS_OF,
        calendar=observation_trade_date_at,
        sector_observation=_overview_fake("白酒", updated="2026-08-17 10:35"),
    )
    assert result["state"] == "USABLE"
    refs = result["authority_refs"]
    assert "market-breadth:date-basis=provider-trade_date" in refs
    assert "market-breadth:trade_date=2026-08-14" in refs
    assert f"market-breadth:trade_date={MONDAY}" not in refs


def test_F_fetched_at_is_observation_attribution_not_fact_time():
    """F：fetched_at 只用于 observation attribution / freshness，
    绝不充当市场事实精确时刻。"""
    result = _evaluate(
        lambda: _envelope(trade_date=None, fetched_at="2026-08-15 11:00:00"),
        as_of=SATURDAY_AS_OF,
        calendar=observation_trade_date_at,
        sector_observation=_overview_fake("白酒", updated="2026-08-15 11:05"),
    )
    refs = result["authority_refs"]
    assert "market-breadth:observed_at=2026-08-15 11:00:00" in refs
    assert any(ref.startswith("market-breadth:fetched_at=") for ref in refs)
    # fetched_at 的周六日期绝不作为 trade_date
    assert "market-breadth:trade_date=2026-08-15" not in refs


# ---------------------------------------------------------------------------
# R2：real sector context（industry identity alone ≠ sector context）
# ---------------------------------------------------------------------------

def test_industry_identity_alone_is_not_usable():
    """§D：行业名存在但没有 matching sector observation → 非 USABLE。"""
    result = _evaluate(
        lambda: _envelope(),
        sector_reader=_industry_reader("白酒"),
        sector_observation=_overview_fake("银行"),  # 无匹配板块
    )
    assert result["state"] == "UNKNOWN"
    assert SECTOR_CONTEXT_BLOCKER_REF in result["authority_refs"]


def test_matching_sector_observation_is_usable():
    """§E：industry identity + matching sector observation → USABLE。"""
    result = _evaluate(
        lambda: _envelope(),
        sector_reader=_industry_reader("酿酒行业"),
        sector_observation=_overview_fake("酿酒行业"),
    )
    assert result["state"] == "USABLE"
    refs = result["authority_refs"]
    assert "market-sector:security-industry=酿酒行业" in refs
    assert "market-sector:sector=酿酒行业" in refs
    assert "market-sector:sector-pct=1.23" in refs
    assert "market-sector:sector-net=450000000.0" in refs
    assert f"market-sector:updated={TRADE_DATE}" in refs


def test_sector_observation_reader_exception_is_error():
    def broken():
        raise RuntimeError("overview down")

    result = _evaluate(lambda: _envelope(), sector_observation=broken)
    assert result["state"] == "ERROR"


def test_sector_observation_missing_updated_is_unknown():
    result = _evaluate(
        lambda: _envelope(),
        sector_observation=_overview_fake("白酒", updated=None),
    )
    assert result["state"] == "UNKNOWN"
    assert SECTOR_CONTEXT_BLOCKER_REF in result["authority_refs"]


def test_sector_observation_stale_date_is_stale():
    """sector snapshot 北京日期早于 market fact date → STALE。"""
    result = _evaluate(
        lambda: _envelope(),
        sector_observation=_overview_fake("白酒", updated="2026-08-12 15:05"),
    )
    assert result["state"] == "STALE"
