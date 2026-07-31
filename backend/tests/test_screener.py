"""Unit tests for screener pure evaluation logic."""

from __future__ import annotations

import math

import pytest

import screener_service as svc
from screener_models import (
    CondBreakdown20dLow,
    CondBreakout20dHigh,
    CondMacdHistNegative,
    CondMacdHistPositive,
    CondPriceGtSma20,
    CondPriceGtSma60,
    CondPriceLtSma20,
    CondRsiBetween,
    CondSma20GtSma60,
    CondVolumeRatioGte,
    RsiBetweenParams,
    ScreenerEvaluateIn,
    VolumeRatioParams,
)


def _envelope(
    *,
    status="normal",
    close=12.0,
    sma20=11.0,
    sma60=10.0,
    rsi14=50.0,
    macd_histogram=0.5,
    volume_ratio_5_20=1.2,
    triggers=None,
    trade_date="2026-07-30",
    limitations=None,
):
    return {
        "status": status,
        "trade_date": trade_date,
        "limitations": limitations or [],
        "latest": {
            "close": close,
            "sma20": sma20,
            "sma60": sma60,
            "rsi14": rsi14,
            "macd_histogram": macd_histogram,
            "volume_ratio_5_20": volume_ratio_5_20,
        },
        "triggers": triggers or [],
    }


def test_all_conditions_match():
    env = _envelope(triggers=[{"type": "close_above_20d_high"}])
    conds = [
        CondPriceGtSma20(id="price_gt_sma20"),
        CondSma20GtSma60(id="sma20_gt_sma60"),
        CondMacdHistPositive(id="macd_hist_positive"),
        CondRsiBetween(id="rsi_between", params=RsiBetweenParams(min=30, max=70)),
        CondBreakout20dHigh(id="breakout_20d_high"),
    ]
    results = [svc.evaluate_condition(c, env) for c in conds]
    assert all(r["evaluable"] and r["passed"] for r in results)
    assert svc.classify_stock(results, "normal") == "matched"


def test_single_condition_reject():
    env = _envelope(close=10.0, sma20=11.0)
    r = svc.evaluate_condition(CondPriceGtSma20(id="price_gt_sma20"), env)
    assert r["evaluable"] is True
    assert r["passed"] is False
    assert svc.classify_stock([r], "normal") == "rejected"


def test_and_any_false_is_rejected_even_with_unevaluable():
    env = _envelope(close=10.0, sma20=11.0, sma60=None)
    results = [
        svc.evaluate_condition(CondPriceGtSma20(id="price_gt_sma20"), env),  # false
        svc.evaluate_condition(CondPriceGtSma60(id="price_gt_sma60"), env),  # unevaluable
    ]
    assert results[0]["passed"] is False
    assert results[1]["evaluable"] is False
    assert svc.classify_stock(results, "normal") == "rejected"


def test_missing_sma60_unavailable_not_rejected():
    env = _envelope(sma60=None)
    results = [
        svc.evaluate_condition(CondPriceGtSma20(id="price_gt_sma20"), env),
        svc.evaluate_condition(CondPriceGtSma60(id="price_gt_sma60"), env),
    ]
    assert results[0]["passed"] is True
    assert results[1]["evaluable"] is False
    assert svc.classify_stock(results, "normal") == "unavailable"
    assert svc.classify_stock(results, "normal") != "rejected"


def test_technical_unavailable_bucket():
    assert svc.classify_stock([], "unavailable") == "unavailable"


def test_breakout_uses_exact_trigger_key():
    env = _envelope(triggers=[{"type": "close_above_20d_high"}])
    r = svc.evaluate_condition(CondBreakout20dHigh(id="breakout_20d_high"), env)
    assert r["passed"] is True
    assert r["evidence"]["trigger"] == "close_above_20d_high"

    env2 = _envelope(triggers=[])
    r2 = svc.evaluate_condition(CondBreakout20dHigh(id="breakout_20d_high"), env2)
    assert r2["evaluable"] is True
    assert r2["passed"] is False


def test_breakdown_uses_exact_trigger_key():
    env = _envelope(triggers=[{"type": "close_below_20d_low"}])
    r = svc.evaluate_condition(CondBreakdown20dLow(id="breakdown_20d_low"), env)
    assert r["passed"] is True
    assert r["evidence"]["trigger"] == "close_below_20d_low"


def test_breakout_unevaluable_when_price_range_limitation():
    """partial + incomplete high/low + no trigger → unevaluable → unavailable if sole cond."""
    env = _envelope(
        status="partial",
        triggers=[],
        limitations=["价格区间触发不可评估：过去 20 个交易日的 high/low 数据不完整"],
    )
    r = svc.evaluate_condition(CondBreakout20dHigh(id="breakout_20d_high"), env)
    assert r["evaluable"] is False
    assert r["passed"] is None
    assert svc.classify_stock([r], "partial") == "unavailable"


def test_breakout_evaluable_false_when_partial_unrelated_to_price_range():
    """partial only due to SMA60/volume — price window complete, no trigger → rejected."""
    env = _envelope(
        status="partial",
        triggers=[],
        limitations=["历史长度 40 不足 60 个交易日，SMA60 不可用"],
    )
    r = svc.evaluate_condition(CondBreakout20dHigh(id="breakout_20d_high"), env)
    assert r["evaluable"] is True
    assert r["passed"] is False
    assert svc.classify_stock([r], "partial") == "rejected"


def test_breakout_trigger_present_passed_true_even_with_other_limitations():
    env = _envelope(
        status="partial",
        triggers=[{"type": "close_above_20d_high"}],
        limitations=["成交量历史不足，5/20 日均量比不可用"],
    )
    r = svc.evaluate_condition(CondBreakout20dHigh(id="breakout_20d_high"), env)
    assert r["evaluable"] is True
    assert r["passed"] is True


def test_macd_hist_negative():
    env = _envelope(macd_histogram=-0.3)
    r = svc.evaluate_condition(CondMacdHistNegative(id="macd_hist_negative"), env)
    assert r["passed"] is True


def test_volume_ratio_gte():
    env = _envelope(volume_ratio_5_20=2.0)
    c = CondVolumeRatioGte(id="volume_ratio_gte", params=VolumeRatioParams(threshold=1.5))
    r = svc.evaluate_condition(c, env)
    assert r["passed"] is True


def test_evaluate_one_stock_isolation_on_kline_error():
    def boom(_code, _days):
        raise RuntimeError("upstream down")

    stock = svc.evaluate_one_stock(
        "600519",
        [CondPriceGtSma20(id="price_gt_sma20")],
        kline_fn=boom,
    )
    assert stock["bucket"] == "unavailable"
    assert stock["matched"] is None


def test_batch_isolation_and_determinism():
    def kline_fn(code, days):
        if code == "000002":
            raise RuntimeError("fail one")
        # minimal valid-looking bars for compute mock
        return [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 100}]

    def compute_fn(raw, **kwargs):
        code = kwargs["code"]
        if code == "000001":
            return _envelope(close=12, sma20=11)
        return _envelope(close=10, sma20=11)  # 600519 reject

    body = ScreenerEvaluateIn(
        codes=["600519", "000001", "000002", "000001"],  # dup + unsorted
        conditions=[CondPriceGtSma20(id="price_gt_sma20")],
    )
    # codes already normalized by model
    assert body.codes == ["000001", "000002", "600519"]

    r1 = svc.evaluate_screener(body, kline_fn=kline_fn, compute_fn=compute_fn, now_iso="T0")
    r2 = svc.evaluate_screener(body, kline_fn=kline_fn, compute_fn=compute_fn, now_iso="T1")

    assert [s["code"] for s in r1["matched"]] == ["000001"]
    assert [s["code"] for s in r1["rejected"]] == ["600519"]
    assert [s["code"] for s in r1["unavailable"]] == ["000002"]
    assert r1["status"] == "partial"

    # Deterministic excluding evaluated_at
    for key in ("matched", "rejected", "unavailable", "status", "logic", "schema_version"):
        assert r1[key] == r2[key]


def test_price_lt_sma20():
    env = _envelope(close=10, sma20=11)
    r = svc.evaluate_condition(CondPriceLtSma20(id="price_lt_sma20"), env)
    assert r["passed"] is True


def test_list_sector_representative_codes_authoritative():
    """Codes come from sector_research_data public API; sorted, 6-digit, deduped."""
    import sector_research_data as srd

    codes = svc.list_sector_representative_codes()
    assert len(codes) > 0
    assert codes == sorted(codes)
    assert len(codes) == len(set(codes))
    for c in codes:
        assert isinstance(c, str) and len(c) == 6 and c.isdigit()

    # Rebuild expected from public getters (not private SECTOR_SOURCES)
    expected: list[str] = []
    seen: set[str] = set()
    for key in srd.list_sector_source_keys():
        src = srd.get_sector_source(key)
        assert src is not None
        for raw in src.representative_company_codes or []:
            code = str(raw).strip()
            if code.isdigit() and len(code) == 6 and code not in seen:
                seen.add(code)
                expected.append(code)
    expected.sort()
    assert codes == expected
    # Known registry size at design time was 103 unique
    assert len(codes) == 103
