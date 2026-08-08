"""纯计算模块测试：手工可验证的小型 fixture，禁止真实网络。"""
from __future__ import annotations

import math
from datetime import datetime

import pytest

import technical_indicators as ti


# ── helpers ──────────────────────────────────────────────────────────────


def _idx_date(i):
    """生成唯一日期：从 2026-01-01 起逐日递增，跨年跨月。"""
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    return (base + timedelta(days=i)).isoformat()


def _klines_from_closes(closes, highs=None, lows=None, vols=None):
    """构造测试用 K 线：至少提供 close。"""
    klines = []
    for i, c in enumerate(closes):
        k = {
            "datetime": _idx_date(i),
            "close": c,
            "high": highs[i] if highs else c,
            "low": lows[i] if lows else c,
            "vol": vols[i] if vols else 1000 + i * 100,
        }
        klines.append(k)
    return klines


# ── SMA ────────────────────────────────────────────────────────────────


class TestSMA:
    def test_basic(self):
        closes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=10, trade_date="2026-01-10", fetched_at="2026-01-10T00:00:00")
        assert result["latest"]["sma5"] == pytest.approx(8.0)  # (6+7+8+9+10)/5
        assert result["latest"]["sma10"] == pytest.approx(5.5)  # avg 1..10

    def test_insufficient_data(self):
        closes = [1, 2, 3]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=3, trade_date="2026-01-03", fetched_at="2026-01-03T00:00:00")
        # 3 根 K 线不足以计算 SMA5
        assert result["latest"]["sma5"] is None
        assert result["status"] == "unavailable"


# ── EMA ────────────────────────────────────────────────────────────────


class TestEMA:
    def test_basic(self):
        # 3 个值：ema12 → 第一个有效值即初始 EMA，后续递推
        closes = [10.0, 11.0, 12.0]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=3, trade_date="2026-01-03", fetched_at="2026-01-03T00:00:00")
        # EMA12 k = 2/13 ≈ 0.1538
        # day0: 10.0; day1: 11 * 2/13 + 10 * 11/13 ≈ 10.1538; day2: 12 * 2/13 + 10.1538 * 11/13
        ema12 = result["latest"]["ema12"]
        assert ema12 is not None
        # 递推后应大于初始值
        assert ema12 > 10.0


# ── MACD ───────────────────────────────────────────────────────────────


class TestMACD:
    def test_computed(self):
        # 生成 70 根递增 K 线确保 MACD 可计算
        closes = [10 + i * 0.1 for i in range(70)]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=70, trade_date="2026-03-11", fetched_at="2026-03-11T00:00:00")
        assert result["latest"]["macd_dif"] is not None
        assert result["latest"]["macd_dea"] is not None
        assert result["latest"]["macd_histogram"] is not None
        # 递增序列 DIF 应为正
        assert result["latest"]["macd_dif"] > 0


# ── RSI ────────────────────────────────────────────────────────────────


class TestRSI:
    def test_all_up(self):
        # 连续上涨 → RSI 应接近 100
        closes = [10 + i for i in range(20)]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=20, trade_date="2026-01-20", fetched_at="2026-01-20T00:00:00")
        assert result["latest"]["rsi14"] is not None
        assert result["latest"]["rsi14"] > 80

    def test_all_down(self):
        # 连续下跌 → RSI 应接近 0
        closes = [30 - i for i in range(20)]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=20, trade_date="2026-01-20", fetched_at="2026-01-20T00:00:00")
        assert result["latest"]["rsi14"] is not None
        assert result["latest"]["rsi14"] < 20

    def test_flat_market_is_neutral(self):
        result = ti.compute_indicators(
            _klines_from_closes([10.0] * 20), code="000001", period="daily", days=20,
            trade_date="ignored", fetched_at="2026-01-20T00:00:00Z",
        )
        assert result["latest"]["rsi14"] == pytest.approx(50.0)


# ── Bollinger ─────────────────────────────────────────────────────────


class TestBollinger:
    def test_symmetric(self):
        # 20 个相同 close → 标准差 0，三轨重合
        closes = [10.0] * 20
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=20, trade_date="2026-01-20", fetched_at="2026-01-20T00:00:00")
        assert result["latest"]["bollinger_upper"] == pytest.approx(10.0)
        assert result["latest"]["bollinger_middle"] == pytest.approx(10.0)
        assert result["latest"]["bollinger_lower"] == pytest.approx(10.0)


# ── Volume Ratio ───────────────────────────────────────────────────────


class TestVolumeRatio:
    def test_spike(self):
        # 前 24 天 vol=1000，今天 vol=5000 → SMA(5)=1800, SMA(20)=1160 → ratio ≈ 1.55
        # 不够 → 改用 vol=10000 → SMA(5)=2600, SMA(20)=1400 → ratio ≈ 1.86
        # 改用 vol=100000 → SMA(5)=21800, SMA(20)=5900 → ratio ≈ 3.69 > 2
        vols = [1000] * 24 + [100000]
        closes = [10.0] * 25
        klines = _klines_from_closes(closes, vols=vols)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=25, trade_date="2026-01-25", fetched_at="2026-01-25T00:00:00")
        assert result["latest"]["volume_ratio_5_20"] is not None
        assert result["latest"]["volume_ratio_5_20"] > 2.0


# ── 触发 ──────────────────────────────────────────────────────────────


class TestTriggers:
    def test_above_20d_high(self):
        # 前 20 天 close=10, high=10；今天 close=11, high=11
        closes = [10.0] * 20 + [11.0]
        highs = [10.0] * 20 + [11.0]
        klines = _klines_from_closes(closes, highs=highs)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=21, trade_date="2026-01-21", fetched_at="2026-01-21T00:00:00")
        types = [t["type"] for t in result["triggers"]]
        assert "close_above_20d_high" in types

    def test_not_triggered_when_current_is_highest(self):
        # 构造：今日 close 最高但历史窗口不含今日，若历史最高等于今日 → 不应触发
        closes = [10.0] * 19 + [10.0, 10.0]  # 全部相同
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=20, trade_date="2026-01-20", fetched_at="2026-01-20T00:00:00")
        types = [t["type"] for t in result["triggers"]]
        assert "close_above_20d_high" not in types

    def test_below_20d_low(self):
        closes = [10.0] * 20 + [5.0]
        lows = [10.0] * 20 + [5.0]
        klines = _klines_from_closes(closes, lows=lows)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=21, trade_date="2026-01-21", fetched_at="2026-01-21T00:00:00")
        types = [t["type"] for t in result["triggers"]]
        assert "close_below_20d_low" in types

    def test_sma_golden_cross(self):
        # 需要 61 根 K 线：SMA60 在 idx=59 首次非 None，idx=60 才能比较交叉
        # 前 60 天 close=10 → SMA20=SMA60=10；第 61 天 close=100 → SMA20 跳升 > SMA60
        closes = [10.0] * 60 + [100.0]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=61, trade_date="2026-03-02", fetched_at="2026-03-02T00:00:00")
        types = [t["type"] for t in result["triggers"]]
        assert "sma_golden_cross" in types

    def test_sma_death_cross(self):
        # 前 60 天 close=100，第 61 天 close=1
        closes = [100.0] * 60 + [1.0]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=61, trade_date="2026-03-02", fetched_at="2026-03-02T00:00:00")
        types = [t["type"] for t in result["triggers"]]
        assert "sma_death_cross" in types

    def test_volume_spike(self):
        # vol=10000 → SMA(vol,5)=(1000*4+10000)/5=2800; SMA(vol,20)=(1000*19+10000)/20=1450 → ratio≈1.93
        # 不够；用 vol=20000 → SMA(5)=(4000+20000)/5=4800; SMA(20)=(19000+20000)/20=1950 → ratio≈2.46
        vols = [1000] * 24 + [20000]
        closes = [10.0] * 25
        klines = _klines_from_closes(closes, vols=vols)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=25, trade_date="2026-01-25", fetched_at="2026-01-25T00:00:00")
        types = [t["type"] for t in result["triggers"]]
        assert "volume_spike" in types


# ── 无未来函数 ────────────────────────────────────────────────────────


class TestNoFutureBias:
    def test_indicator_uses_only_history(self):
        # 构造两段数据：前 60 天递增 + 后 10 天递减
        # 验证第 59 天的指标不会受后 10 天影响
        closes_inc = [10 + i * 0.1 for i in range(60)]
        closes_dec = [20 - i * 0.5 for i in range(10)]
        full_closes = closes_inc + closes_dec

        klines_full = _klines_from_closes(full_closes)
        result_full = ti.compute_indicators(klines_full, code="000001", period="daily", days=70, trade_date="2026-03-11", fetched_at="2026-03-11T00:00:00")

        klines_partial = _klines_from_closes(closes_inc)
        result_partial = ti.compute_indicators(klines_partial, code="000001", period="daily", days=60, trade_date="2026-03-01", fetched_at="2026-03-01T00:00:00")

        # series 最多 60 个点（从 idx=10 开始），series 偏移 = len(klines) - 60 = 10
        offset = len(klines_full) - len(result_full["series"])
        assert result_full["series"][59 - offset]["sma20"] == result_partial["latest"]["sma20"]
        assert result_full["series"][59 - offset]["sma60"] == result_partial["latest"]["sma60"]


# ── 输入清洗 ──────────────────────────────────────────────────────────


class TestInputSanitization:
    def test_unsorted_dates(self):
        klines = [
            {"datetime": "2026-01-03", "close": 3.0, "high": 3.0, "low": 3.0, "vol": 100},
            {"datetime": "2026-01-01", "close": 1.0, "high": 1.0, "low": 1.0, "vol": 100},
            {"datetime": "2026-01-02", "close": 2.0, "high": 2.0, "low": 2.0, "vol": 100},
        ]
        result = ti.compute_indicators(klines, code="000001", period="daily", days=3, trade_date="2026-01-03", fetched_at="2026-01-03T00:00:00")
        # 排序后 SMA 应基于 1,2,3
        assert result["latest"]["sma5"] is None  # 只有 3 根

    def test_empty_data(self):
        result = ti.compute_indicators([], code="000001", period="daily", days=0, trade_date="", fetched_at="")
        assert result["status"] == "unavailable"
        assert result["latest"]["close"] is None

    def test_single_row(self):
        klines = [{"datetime": "2026-01-01", "close": 10.0, "high": 10.0, "low": 10.0, "vol": 100}]
        result = ti.compute_indicators(klines, code="000001", period="daily", days=1, trade_date="2026-01-01", fetched_at="2026-01-01T00:00:00")
        assert result["status"] == "unavailable"
        assert result["latest"]["close"] == 10.0
        assert result["latest"]["sma5"] is None

    def test_partial_status(self):
        # 30 根 K 线 → partial
        closes = [10 + i * 0.1 for i in range(30)]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=30, trade_date="2026-01-30", fetched_at="2026-01-30T00:00:00")
        assert result["status"] == "partial"
        assert result["latest"]["sma60"] is None
        assert len(result["limitations"]) > 0

    def test_missing_close(self):
        klines = [
            {"datetime": "2026-01-01", "close": None, "high": 10.0, "low": 10.0, "vol": 100},
        ]
        result = ti.compute_indicators(klines, code="000001", period="daily", days=1, trade_date="", fetched_at="")
        assert result["status"] == "unavailable"

    def test_missing_vol(self):
        closes = [10.0] * 20
        klines = [
            {"datetime": f"2026-01-{i+1:02d}", "close": c, "high": c, "low": c}
            for i, c in enumerate(closes)
        ]
        result = ti.compute_indicators(klines, code="000001", period="daily", days=20, trade_date="2026-01-20", fetched_at="2026-01-20T00:00:00")
        assert result["latest"]["volume_ratio_5_20"] is None

    def test_nan_inf_cleaning(self):
        closes = [1.0, 2.0, float("nan"), 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
                  11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=20, trade_date="2026-01-20", fetched_at="2026-01-20T00:00:00")
        # 输出不应含 NaN / Infinity
        for k, v in result["latest"].items():
            if v is not None:
                assert math.isfinite(v), f"{k}={v} is not finite"

    def test_normal_status(self):
        # 70 根递增 → normal
        closes = [10 + i * 0.1 for i in range(70)]
        klines = _klines_from_closes(closes)
        result = ti.compute_indicators(klines, code="000001", period="daily", days=70, trade_date="2026-03-11", fetched_at="2026-03-11T00:00:00")
        assert result["status"] == "normal"
        assert result["latest"]["sma60"] is not None
        assert result["latest"]["rsi14"] is not None
        assert result["latest"]["bollinger_middle"] is not None

    def test_sixty_rows_are_partial_until_previous_sma60_exists(self):
        result = ti.compute_indicators(
            _klines_from_closes([10.0] * 60), code="000001", period="daily", days=60,
            trade_date="ignored", fetched_at="2026-03-01T00:00:00Z",
        )
        assert result["status"] == "partial"
        assert any("均线交叉不可评估" in item for item in result["limitations"])

    def test_trade_date_comes_from_normalized_latest_row(self):
        klines = _klines_from_closes([10.0] * 20)
        result = ti.compute_indicators(
            list(reversed(klines)), code="000001", period="daily", days=20,
            trade_date="caller-is-ignored", fetched_at="2026-01-20T00:00:00Z",
        )
        assert result["trade_date"] == "2026-01-20"
        assert result["series"][-1]["date"] == result["trade_date"]

    def test_invalid_calendar_date_is_discarded(self):
        klines = _klines_from_closes([10.0] * 20)
        klines[0]["datetime"] = "2026-01-32"
        result = ti.compute_indicators(
            klines, code="000001", period="daily", days=20,
            trade_date="ignored", fetched_at="2026-01-20T00:00:00Z",
        )
        assert result["trade_date"] != "2026-01-32"
        assert all(point["date"] != "2026-01-32" for point in result["series"])

    def test_timezone_datetime_keeps_market_calendar_date(self):
        rows = _klines_from_closes([10.0] * 20)
        rows[-1]["datetime"] = "2026-01-20T00:00:00+08:00"
        result = ti.compute_indicators(rows, code="000001", period="daily", days=20, trade_date="ignored", fetched_at="2026-01-20T00:00:00Z")
        assert result["trade_date"] == "2026-01-20"

    def test_duplicate_date_selection_is_order_independent(self):
        base = _klines_from_closes([10.0] * 20)
        duplicate_a = {"datetime": "2026-01-21T09:00:00", "close": 11.0, "high": 11.1, "low": 10.9, "volume": 100}
        duplicate_b = {"datetime": "2026-01-21T15:00:00", "close": 12.0, "high": 12.1, "low": 11.9, "volume": 200}
        first = ti.compute_indicators(base + [duplicate_a, duplicate_b], code="000001", period="daily", days=22, trade_date="ignored", fetched_at="2026-01-22T00:00:00Z")
        second = ti.compute_indicators(base + [duplicate_b, duplicate_a], code="000001", period="daily", days=22, trade_date="ignored", fetched_at="2026-01-22T00:00:00Z")
        assert first["series"] == second["series"]
        assert first["latest"] == second["latest"]

    def test_invalid_duplicate_before_valid_duplicate_does_not_hide_valid(self):
        raw = [{"datetime": "2026-01-01", "close": None}]
        raw.extend(_klines_from_closes([10.0] * 19))
        result = ti.compute_indicators(raw, code="000001", period="daily", days=20, trade_date="ignored", fetched_at="2026-01-20T00:00:00Z")
        assert result["trade_date"] == "2026-01-19"
        assert result["latest"]["close"] == 10.0

    def test_volume_and_vol_are_supported_but_amount_is_not_volume(self):
        rows = _klines_from_closes([10.0] * 20)
        for row in rows:
            row.pop("vol", None)
            row["volume"] = 1000
            row["amount"] = 999999
        via_volume = ti.compute_indicators(rows, code="000001", period="daily", days=20, trade_date="ignored", fetched_at="2026-01-20T00:00:00Z")
        assert via_volume["latest"]["volume_ratio_5_20"] == pytest.approx(1.0)
        for row in rows:
            row.pop("volume", None)
            row["amount"] = 999999
        via_amount_only = ti.compute_indicators(rows, code="000001", period="daily", days=20, trade_date="ignored", fetched_at="2026-01-20T00:00:00Z")
        assert via_amount_only["latest"]["volume_ratio_5_20"] is None

    def test_missing_volume_for_long_history_is_partial(self):
        rows = _klines_from_closes([10.0] * 70)
        for row in rows:
            row.pop("vol", None)
        result = ti.compute_indicators(rows, code="000001", period="daily", days=70, trade_date="ignored", fetched_at="2026-01-20T00:00:00Z")
        assert result["status"] == "partial"
        assert any("成交量历史不足" in item for item in result["limitations"])

    @pytest.mark.parametrize("field", ["high", "low"])
    def test_incomplete_20_day_trigger_window_is_not_evaluated(self, field):
        rows = _klines_from_closes([10.0] * 21)
        rows[0][field] = None
        result = ti.compute_indicators(rows, code="000001", period="daily", days=21, trade_date="ignored", fetched_at="2026-01-21T00:00:00Z")
        assert not any(trigger["type"].startswith("close_") for trigger in result["triggers"])
        assert result["status"] == "partial"
        assert any("价格区间触发不可评估" in item for item in result["limitations"])

    def test_complete_20_day_high_low_window_allows_price_trigger(self):
        rows = _klines_from_closes([10.0] * 20 + [11.0])
        result = ti.compute_indicators(rows, code="000001", period="daily", days=21, trade_date="ignored", fetched_at="2026-01-21T00:00:00Z")
        assert any(trigger["type"] == "close_above_20d_high" for trigger in result["triggers"])

    def test_fetched_at_is_utc_and_microsecond_parseable(self):
        from technical_indicators_router import _utc_now_iso
        value = _utc_now_iso()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert value.endswith("Z")
        assert len(value.split(".")[-1].removesuffix("Z")) == 6


# ── KDJ ────────────────────────────────────────────────────────────────


class TestKDJ:
    def test_prefix_none_and_first_output_with_prev50(self):
        closes = [10.0] * 12
        highs = [11.0] * 12
        lows = [9.0] * 12
        k, d, j = ti._kdj(closes, highs, lows, 9)
        assert all(v is None for v in k[:8])
        assert all(v is None for v in d[:8])
        assert all(v is None for v in j[:8])
        # RSV = (10-9)/(11-9)*100 = 50 with prev K/D=50
        assert k[8] == pytest.approx(50.0)
        assert d[8] == pytest.approx(50.0)
        assert j[8] == pytest.approx(50.0)

    def test_flat_window_rsv50(self):
        closes = [10.0] * 12
        highs = [10.0] * 12
        lows = [10.0] * 12
        k, d, j = ti._kdj(closes, highs, lows, 9)
        assert k[8] == pytest.approx(50.0)
        assert d[8] == pytest.approx(50.0)
        assert j[8] == pytest.approx(50.0)

    def test_up_and_down_bias(self):
        up = [10 + i for i in range(20)]
        up_h = [c + 0.5 for c in up]
        up_l = [c - 0.5 for c in up]
        k_up, _, _ = ti._kdj(up, up_h, up_l, 9)
        assert k_up[-1] is not None and k_up[-1] > 50

        down = [30 - i for i in range(20)]
        down_h = [c + 0.5 for c in down]
        down_l = [c - 0.5 for c in down]
        k_down, _, _ = ti._kdj(down, down_h, down_l, 9)
        assert k_down[-1] is not None and k_down[-1] < 50

    def test_j_not_clamped(self):
        closes = [10 + i * 2 for i in range(20)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        _, _, j = ti._kdj(closes, highs, lows, 9)
        vals = [v for v in j if v is not None]
        assert vals
        assert any(v > 100 or v < 0 for v in vals)

    def test_invalid_windows_emit_none(self):
        n = 12
        closes = [10.0] * n
        highs = [11.0] * n
        lows = [9.0] * n

        highs2 = list(highs)
        highs2[10] = None
        k, d, j = ti._kdj(closes, highs2, lows, 9)
        assert k[10] is None and d[10] is None and j[10] is None

        highs3 = list(highs)
        lows3 = list(lows)
        highs3[10] = 8.0
        lows3[10] = 9.0
        k, d, j = ti._kdj(closes, highs3, lows3, 9)
        assert k[10] is None

        highs4 = list(highs)
        highs4[10] = float("nan")
        k, d, j = ti._kdj(closes, highs4, lows, 9)
        assert k[10] is None

        lows4 = list(lows)
        lows4[10] = float("inf")
        k, d, j = ti._kdj(closes, highs, lows4, 9)
        assert k[10] is None

        closes2 = list(closes)
        closes2[10] = 20.0
        k, d, j = ti._kdj(closes2, highs, lows, 9)
        assert k[10] is None

        closes3 = list(closes)
        closes3[10] = 1.0
        k, d, j = ti._kdj(closes3, highs, lows, 9)
        assert k[10] is None

    def test_recovery_preserves_state(self):
        # 9 valid bars, then one invalid day, then enough valid bars for a new window.
        closes = [10 + i * 0.1 for i in range(20)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        highs[9] = None  # invalid day after first complete window (index 8)
        k, d, j = ti._kdj(closes, highs, lows, 9)
        assert k[8] is not None
        assert k[9] is None and d[9] is None and j[9] is None
        # Windows that still include index 9 remain None; once it rolls out, recover.
        assert k[17] is None
        assert k[18] is not None and d[18] is not None and j[18] is not None
        assert math.isfinite(k[18]) and math.isfinite(d[18]) and math.isfinite(j[18])

    def test_no_future_function(self):
        base_closes = [10 + i * 0.2 for i in range(20)]
        base_highs = [c + 0.4 for c in base_closes]
        base_lows = [c - 0.4 for c in base_closes]
        k1, d1, j1 = ti._kdj(base_closes, base_highs, base_lows, 9)

        ext_closes = base_closes + [1000 + i for i in range(10)]
        ext_highs = base_highs + [c + 1 for c in ext_closes[20:]]
        ext_lows = base_lows + [c - 1 for c in ext_closes[20:]]
        k2, d2, j2 = ti._kdj(ext_closes, ext_highs, ext_lows, 9)
        assert k1[19] == pytest.approx(k2[19])
        assert d1[19] == pytest.approx(d2[19])
        assert j1[19] == pytest.approx(j2[19])

    def test_envelope_fields_and_status(self):
        closes = [10 + i * 0.1 for i in range(70)]
        highs = [c + 0.2 for c in closes]
        lows = [c - 0.2 for c in closes]
        klines = _klines_from_closes(
            closes, highs=highs, lows=lows, vols=[1000 + i * 10 for i in range(70)]
        )
        result = ti.compute_indicators(
            klines,
            code="000001",
            period="daily",
            days=120,
            trade_date="ignored",
            fetched_at="2026-03-11T00:00:00Z",
        )
        assert result["schema_version"] == "technical-indicators-v0.2"
        assert result["status"] == "normal"
        for key in ("kdj_k", "kdj_d", "kdj_j"):
            assert result["latest"][key] is not None
            assert math.isfinite(result["latest"][key])
        assert all("kdj_k" in p and "kdj_d" in p and "kdj_j" in p for p in result["series"])

        empty = ti.compute_indicators(
            [],
            code="000001",
            period="daily",
            days=120,
            trade_date=None,
            fetched_at="2026-01-01T00:00:00Z",
        )
        assert empty["status"] == "unavailable"
        assert empty["latest"]["kdj_k"] is None
        assert empty["latest"]["kdj_d"] is None
        assert empty["latest"]["kdj_j"] is None

        short = ti.compute_indicators(
            _klines_from_closes([10, 11, 12, 13, 14, 15, 16, 17]),
            code="000001",
            period="daily",
            days=8,
            trade_date="ignored",
            fetched_at="2026-01-08T00:00:00Z",
        )
        assert short["latest"]["kdj_k"] is None

        highs2 = [None if i == 69 else c + 0.2 for i, c in enumerate(closes)]
        lows2 = [None if i == 69 else c - 0.2 for i, c in enumerate(closes)]
        klines2 = _klines_from_closes(
            closes, highs=highs2, lows=lows2, vols=[1000 + i * 10 for i in range(70)]
        )
        partial = ti.compute_indicators(
            klines2,
            code="000001",
            period="daily",
            days=120,
            trade_date="ignored",
            fetched_at="2026-03-11T00:00:00Z",
        )
        assert partial["status"] == "partial"
        assert any("KDJ(9,3,3)" in x for x in partial["limitations"])
        assert partial["limitations"].count(ti.KDJ_LIMITATION) == 1
