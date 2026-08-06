"""BK-11 Tushare 市场事实 adapter 离线测试（FakeClient，无网络）。"""

from __future__ import annotations

import sys
from copy import deepcopy

import pytest

sys.path.insert(0, "backend")

import bk11_tushare_facts_adapter as adapter  # noqa: E402


T = "2026-07-30"


def _daily(code, pct, close, high=None):
    return {
        "ts_code": code, "trade_date": T,
        "high": close if high is None else high,
        "close": close, "pct_chg": pct,
    }


def _stk(code, up, down):
    return {"ts_code": code, "trade_date": T, "up_limit": up, "down_limit": down}


def _suspend(code, stype="S"):
    return {"ts_code": code, "trade_date": T,
            "suspend_timing": "全天", "suspend_type": stype}


def _basic(code, symbol=None, status="L", list_date="2010-01-01",
           delist_date=None):
    return {
        "ts_code": code, "symbol": symbol or code[:6],
        "exchange": "SSE" if code.endswith("SH") else "SZSE",
        "market": "主板", "list_status": status,
        "list_date": list_date, "delist_date": delist_date,
    }


def _pool():
    return [
        _basic("600519.SH"), _basic("000001.SZ"), _basic("300750.SZ"),
        _basic("688981.SH"), _basic("000002.SZ"), _basic("000003.SZ"),
    ]


def _daily_rows():
    return [
        _daily("600519.SH", 1.5, 1500.0, high=1510.0),
        _daily("000001.SZ", -0.5, 11.0, high=11.2),
        _daily("300750.SZ", 0.0, 70.0, high=70.5),
        _daily("688981.SH", 10.0, 100.0, high=100.0),
        _daily("000003.SZ", 6.0, 9.5, high=10.0),
    ]


def _stk_rows():
    return [
        _stk("600519.SH", 1600.0, 1400.0),
        _stk("000001.SZ", 12.0, 9.8),
        _stk("300750.SZ", 80.0, 65.0),
        _stk("688981.SH", 100.0, 90.0),
        _stk("000003.SZ", 10.0, 8.0),
    ]


def _suspend_rows():
    return [_suspend("000002.SZ")]


class FakeClient:
    def __init__(self, daily=None, suspend=None, stk=None, basic=None):
        self.daily = daily if daily is not None else _daily_rows()
        self.suspend = suspend if suspend is not None else _suspend_rows()
        self.stk = stk if stk is not None else _stk_rows()
        self.basic = basic if basic is not None else _pool()
        self.calls: list[tuple[str, dict, str]] = []

    def query(self, api_name, params, fields=None):
        self.calls.append((api_name, dict(params), fields))
        if api_name == "daily":
            return deepcopy(self.daily)
        if api_name == "suspend_d":
            return deepcopy(self.suspend)
        if api_name == "stk_limit":
            return deepcopy(self.stk)
        if api_name == "stock_basic":
            return deepcopy(self.basic)
        raise AssertionError(f"unexpected api {api_name}")


def _normal(fc=None):
    return adapter.fetch_tushare_facts_snapshot(T, fc or FakeClient())


class TestNormalContract:
    def test_normal_counts(self):
        result = _normal()
        assert result["status"] == "normal"
        b = result["breadth"]
        assert b["advance_count"] == 3   # 600519, 688981, 000003
        assert b["decline_count"] == 1   # 000001
        assert b["flat_count"] == 1      # 300750
        assert b["suspended_count"] == 1  # 000002
        assert b["eligible_count"] == 6
        assert b["valid_count"] == 5
        assert b["intraday_suspend_count"] == 0
        a = result["limit_activity"]
        assert a["limit_up_count"] == 1   # 688981 close==up_limit
        assert a["limit_down_count"] == 0
        assert a["failed_limit_up_count"] == 1  # 000003 high 达 up_limit 未封住
        assert result["legal_zero"] is False

    def test_trade_date_match(self):
        result = _normal()
        assert result["trade_date"] == T
        assert result["session"] == "final"
        assert result["is_final"] is True

    def test_input_not_modified(self):
        fc = FakeClient()
        daily_before = deepcopy(fc.daily)
        basic_before = deepcopy(fc.basic)
        adapter.fetch_tushare_facts_snapshot(T, fc)
        assert fc.daily == daily_before
        assert fc.basic == basic_before


class TestDateMismatch:
    def _with_bad_date(self, api_name):
        fc = FakeClient()
        if api_name == "daily":
            fc.daily = [{**_daily("600519.SH", 1.5, 1500.0),
                         "trade_date": "2026-07-29"}]
        elif api_name == "suspend_d":
            fc.suspend = [{**_suspend("000002.SZ"), "trade_date": "2026-07-29"}]
        else:
            fc.stk = [{**_stk("600519.SH", 1600.0, 1400.0),
                       "trade_date": "2026-07-29"}]
        return fc

    def test_daily_date_mismatch(self):
        assert _normal(self._with_bad_date("daily"))["status"] == "unavailable"

    def test_suspend_date_mismatch(self):
        result = _normal(self._with_bad_date("suspend_d"))
        assert result["status"] == "unavailable"

    def test_stk_limit_date_mismatch(self):
        assert _normal(self._with_bad_date("stk_limit"))["status"] == "unavailable"


class TestDuplicateCodes:
    def test_daily_duplicate(self):
        fc = FakeClient()
        fc.daily = fc.daily + [deepcopy(fc.daily[0])]
        assert _normal(fc)["status"] == "unavailable"

    def test_suspend_duplicate(self):
        fc = FakeClient()
        fc.suspend = fc.suspend + [deepcopy(fc.suspend[0])]
        assert _normal(fc)["status"] == "unavailable"

    def test_stk_limit_duplicate(self):
        fc = FakeClient()
        fc.stk = fc.stk + [deepcopy(fc.stk[0])]
        assert _normal(fc)["status"] == "unavailable"


class TestStockBasic:
    def test_status_conflict_fails_closed(self):
        fc = FakeClient()
        fc.basic = _pool() + [_basic("600519.SH", status="D",
                                     delist_date="2025-01-01")]
        assert _normal(fc)["status"] == "unavailable"

    def test_delisted_excluded_from_pool(self):
        fc = FakeClient()
        fc.basic = _pool() + [_basic("600000.SH", status="D",
                                     delist_date="2025-01-01")]
        result = _normal(fc)
        assert result["status"] == "normal"
        assert result["universe"]["delisted_excluded_count"] == 1

    def test_b_share_and_fund_excluded(self):
        fc = FakeClient()
        fc.basic = _pool() + [
            _basic("900901.SH"), _basic("200002.SZ"),
            _basic("510300.SH"), _basic("159919.SZ"),
        ]
        result = _normal(fc)
        assert result["status"] == "normal"
        assert result["universe"]["historical_pool_count"] == 6


class TestSuspension:
    def test_full_day_suspension(self):
        result = _normal()
        assert result["breadth"]["suspended_count"] == 1

    def test_intraday_suspension_not_suspended(self):
        fc = FakeClient()
        # 600519 同时有 daily 行与 suspend_d(S) 行 → 日内停牌，不计 suspended
        fc.suspend = _suspend_rows() + [_suspend("600519.SH")]
        result = _normal(fc)
        assert result["breadth"]["suspended_count"] == 1
        assert result["breadth"]["intraday_suspend_count"] == 1
        assert "intraday suspend stocks: 1" in result["warnings"]


class TestInvalidData:
    def test_pct_chg_missing_fails_closed(self):
        fc = FakeClient()
        fc.daily[0]["pct_chg"] = None
        result = _normal(fc)
        assert result["status"] == "unavailable"
        assert "INVALID_PCT_CHG" in result["reason_codes"]

    def test_non_finite_price_fails(self):
        fc = FakeClient()
        fc.daily[0]["close"] = float("nan")
        result = _normal(fc)
        # 非法价格 → coverage_warning（partial），不误判停牌、不伪造指标
        assert result["status"] == "partial"
        assert result["facts_data_health"]["coverage_warning"] is True
        assert result["universe"]["invalid_price_rows"] == 1

    def test_unexplained_universe_gap_small(self):
        fc = FakeClient()
        fc.basic = _pool() + [_basic("000004.SZ")]
        result = _normal(fc)
        assert result["status"] == "partial"
        assert result["facts_data_health"]["coverage_warning"] is True

    def test_unexplained_universe_gap_large_fails_closed(self):
        fc = FakeClient()
        extra = [_basic(f"{i:06d}.SZ") for i in range(60, 120)]
        fc.basic = _pool() + extra
        result = _normal(fc)
        assert result["status"] == "unavailable"
        assert "UNEXPLAINED_UNIVERSE_GAP" in result["reason_codes"]

    def test_stk_limit_join_gap_partial(self):
        fc = FakeClient()
        fc.stk = fc.stk[:4]  # 去掉 000003
        result = _normal(fc)
        assert result["status"] == "partial"
        assert result["facts_data_health"]["coverage_warning"] is True


class TestLimitActivity:
    def test_decimal_boundary_close_equals_up_limit(self):
        # close == up_limit 精确 0.01：应计涨停
        fc = FakeClient()
        fc.daily = [_daily("600519.SH", 10.0, 1600.0, high=1600.0)]
        fc.stk = [_stk("600519.SH", 1600.0, 1400.0)]
        fc.suspend = []
        fc.basic = [_basic("600519.SH")]
        result = _normal(fc)
        assert result["status"] == "normal"
        assert result["limit_activity"]["limit_up_count"] == 1

    def test_near_limit_not_counted(self):
        fc = FakeClient()
        fc.daily = [_daily("600519.SH", 9.9, 1599.99, high=1599.99)]
        fc.stk = [_stk("600519.SH", 1600.0, 1400.0)]
        fc.suspend = []
        fc.basic = [_basic("600519.SH")]
        result = _normal(fc)
        assert result["limit_activity"]["limit_up_count"] == 0
        assert result["limit_activity"]["failed_limit_up_count"] == 0

    def test_failed_limit_up(self):
        result = _normal()
        assert result["limit_activity"]["failed_limit_up_count"] == 1
        assert result["limit_activity"]["touched_limit_up_count"] == 2
        assert result["limit_activity"]["seal_rate"] == 0.5


class TestLegalZero:
    def test_legal_zero_full_proof(self):
        fc = FakeClient()
        fc.daily = [_daily("600519.SH", 1.0, 1500.0, high=1500.0)]
        fc.stk = [_stk("600519.SH", 1600.0, 1400.0)]
        fc.suspend = []
        fc.basic = [_basic("600519.SH")]
        result = _normal(fc)
        assert result["status"] == "normal"
        assert result["limit_activity"]["limit_up_count"] == 0
        assert result["legal_zero"] is True

    def test_empty_daily_not_legal_zero(self):
        fc = FakeClient()
        fc.daily = []
        fc.suspend = []
        fc.stk = []
        result = _normal(fc)
        assert result["status"] == "unavailable"
        assert result["legal_zero"] is False

    def test_stk_gap_breaks_legal_zero(self):
        fc = FakeClient()
        fc.daily = [_daily("600519.SH", 1.0, 1500.0, high=1500.0)]
        fc.stk = []
        fc.suspend = []
        fc.basic = [_basic("600519.SH")]
        result = _normal(fc)
        assert result["legal_zero"] is False


def test_invalid_trade_date_format():
    result = adapter.fetch_tushare_facts_snapshot("2026-13-45", FakeClient())
    assert result["status"] == "unavailable"


def test_client_errors_propagate():
    class BoomClient(FakeClient):
        def query(self, api_name, params, fields=None):
            import tushare_pro_client as tpc
            raise tpc.TusharePermissionDenied("denied")

    import tushare_pro_client as tpc
    with pytest.raises(tpc.TusharePermissionDenied):
        adapter.fetch_tushare_facts_snapshot(T, BoomClient())
