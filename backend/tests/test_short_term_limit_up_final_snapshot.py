"""BK-11 T+1 可信 final 涨停池快照生产者 v0.1 · 全路径失败关闭测试。

不发起任何 live 网络请求，不真实 sleep。所有适配器观测通过 monkeypatch
``_fetch_adapter_snapshot`` 注入；时钟通过 ``_monotonic`` 注入；休眠通过
``_sleep`` 注入；交易日历通过 ``trade_calendar`` 私有引用注入。
"""
from __future__ import annotations

import math
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, "backend")

import astock  # noqa: E402
import trade_calendar  # noqa: E402
import short_term_limit_up_final_snapshot as producer  # noqa: E402


SESSIONS = (
    "2024-01-02", "2024-01-03", "2026-06-18", "2026-06-22",
    "2026-07-24", "2026-07-27", "2026-07-29", "2026-07-30",
    "2026-07-31",
)
TODAY = date(2026, 8, 4)
GOOD_DATE = "2026-07-30"
ADAPTER_SCHEMA = "short-term-limit-up-pool-adapter-v0.1"
_UNSET = object()


@pytest.fixture(autouse=True)
def _calendar_stub(monkeypatch):
    monkeypatch.setattr(trade_calendar, "_load_calendar", lambda: SESSIONS)
    monkeypatch.setattr(trade_calendar, "_today_shanghai", lambda: TODAY)


class _Clock:
    """固定序列 monotonic 时钟；超出长度时重复最后一个值。"""

    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        v = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return v


def _adapter_obs(**overrides):
    obs = {
        "schema_version": ADAPTER_SCHEMA,
        "source_id": "eastmoney_getTopicZTPool",
        "endpoint": "getTopicZTPool",
        "requested_trade_date": GOOD_DATE,
        "observed_at": "2026-07-30T15:10:00Z",
        "status": "normal",
        "reason_codes": [],
        "rows": [{"stock_code": "600000", "lbc": 1}],
        "transport_success": True,
        "parse_success": True,
        "required_field_present": True,
        "data_array_present": True,
        "trade_date_match": True,
        "row_count": 1,
        "legal_zero": False,
        "upstream_null": False,
        "unexplained_empty": False,
        "coverage_warning": False,
        "target_universe_empty_after_filter": False,
        "source_pool_row_count": 1,
        "http_status": 200,
        "error_class": "NONE",
        "excluded_universe_count": 0,
        "invalid_row_count": 0,
        "duplicate_code_count": 0,
    }
    obs.update(overrides)
    return obs


def _target_universe_empty_obs(**overrides):
    obs = _adapter_obs(
        rows=[],
        row_count=0,
        source_pool_row_count=2,
        excluded_universe_count=2,
        target_universe_empty_after_filter=True,
    )
    obs.update(overrides)
    return obs


def _run(monkeypatch, obs_list, clock_values=None, sleep_exc=None,
         cal=_UNSET, today=_UNSET, clock_fn=None, req=GOOD_DATE):
    state = {"adapter_calls": 0, "sleep_calls": 0}

    def fake_adapter(r):
        i = min(state["adapter_calls"], len(obs_list) - 1)
        state["adapter_calls"] += 1
        item = obs_list[i]
        if isinstance(item, BaseException):
            raise item
        return item

    def fake_sleep(sec):
        state["sleep_calls"] += 1
        if sleep_exc is not None:
            raise sleep_exc

    monkeypatch.setattr(producer, "_fetch_adapter_snapshot", fake_adapter)
    monkeypatch.setattr(producer, "_sleep", fake_sleep)
    if clock_fn is not None:
        monkeypatch.setattr(producer, "_monotonic", clock_fn)
    else:
        clock = _Clock(clock_values if clock_values is not None
                       else [100.0, 102.2, 104.4])
        monkeypatch.setattr(producer, "_monotonic", clock)
    if cal is not _UNSET:
        monkeypatch.setattr(trade_calendar, "_load_calendar", lambda: cal)
    if today is not _UNSET:
        monkeypatch.setattr(trade_calendar, "_today_shanghai", lambda: today)
    return producer.fetch_final_limit_up_pool_snapshot(req), state


def _assert_output_shape(r):
    """所有输出字段存在、类型正确、finality 不变量与 reason 顺序满足。"""
    assert r["schema_version"] == producer.SCHEMA_VERSION
    assert isinstance(r["requested_trade_date"], str)
    assert isinstance(r["observed_at"], str)
    assert r["status"] in ("normal", "partial", "unavailable")
    assert isinstance(r["reason_codes"], list)
    for code in r["reason_codes"]:
        assert code in producer._REASON_CODE_SET
    assert r["session"] in ("final", "not_final")
    assert isinstance(r["is_final"], bool)
    assert r["finality_basis"] is None or isinstance(r["finality_basis"], str)
    assert isinstance(r["required_observations"], int)
    assert isinstance(r["completed_observations"], int)
    assert isinstance(r["stable_observation_count"], int)
    assert isinstance(r["observation_interval_seconds"], float)
    assert isinstance(r["required_stability_window_seconds"], float)
    assert r["actual_stability_window_seconds"] is None or isinstance(
        r["actual_stability_window_seconds"], float)
    assert r["first_observation_monotonic"] is None or isinstance(
        r["first_observation_monotonic"], float)
    assert r["last_observation_monotonic"] is None or isinstance(
        r["last_observation_monotonic"], float)
    assert r["snapshot"] is None or isinstance(r["snapshot"], dict)
    assert isinstance(r["warnings"], list)
    # timing 关系：无时间 → 全 None；有时间 → first<=last 且 actual==last-first
    first_t = r["first_observation_monotonic"]
    last_t = r["last_observation_monotonic"]
    actual_t = r["actual_stability_window_seconds"]
    if first_t is None:
        assert last_t is None and actual_t is None
    else:
        assert last_t is not None and actual_t is not None
        assert type(first_t) is float and type(last_t) is float
        assert type(actual_t) is float
        assert first_t <= last_t
        assert actual_t == pytest.approx(last_t - first_t)
    # 计数不变量
    assert 0 <= r["stable_observation_count"] <= r["completed_observations"]
    assert r["completed_observations"] <= r["required_observations"]
    # reason 固定顺序
    fixed = list(producer._REASON_CODE_ORDER)
    seen = []
    for c in r["reason_codes"]:
        if c not in seen:
            seen.append(c)
    for a, b in zip(seen, seen[1:]):
        assert fixed.index(a) < fixed.index(b)
    # finality 不变量
    if r["is_final"]:
        assert r["status"] == "normal"
        assert r["session"] == "final"
        assert r["reason_codes"] == []
        assert r["snapshot"] is not None
        assert r["completed_observations"] == 3
        assert r["stable_observation_count"] == 3
        assert r["actual_stability_window_seconds"] is not None
        assert r["actual_stability_window_seconds"] + 1e-9 >= 4.4
    if r["status"] != "normal":
        assert r["is_final"] is False
        assert r["session"] == "not_final"
        assert r["snapshot"] is None


# ---------------------------------------------------------------------------
# 1. 日期预检：零请求
# ---------------------------------------------------------------------------

class TestDatePreflight:
    @pytest.mark.parametrize("value", [None, True, False, 123, 3.14, object()])
    def test_non_string(self, monkeypatch, value):
        r, state = _run(monkeypatch, [_adapter_obs()], req=value)
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["NON_TRADING_DATE"]
        assert state["adapter_calls"] == 0
        assert state["sleep_calls"] == 0

    @pytest.mark.parametrize("value", [
        "", " 2026-07-30", "2026-07-30 ", " 2026-07-30 ",
        "20260730", "2026/07/30", "2026-7-30", "not-a-date",
        "2026-02-30", "2026-13-01", "2026-00-10",
        "2026-08-01", "2026-06-19", "2026-07-28",
    ])
    def test_invalid_or_non_session(self, monkeypatch, value):
        r, state = _run(monkeypatch, [_adapter_obs()], req=value)
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["NON_TRADING_DATE"]
        assert state["adapter_calls"] == 0
        assert state["sleep_calls"] == 0

    def test_today_not_final(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs()],
                        cal=SESSIONS + ("2026-08-04",), req="2026-08-04")
        _assert_output_shape(r)
        assert r["reason_codes"] == ["NOT_FINAL"]
        assert r["status"] == "unavailable"
        assert state["adapter_calls"] == 0
        assert state["sleep_calls"] == 0

    def test_future_in_sessions_not_final(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs()],
                        cal=SESSIONS + ("2026-12-31",), req="2026-12-31")
        _assert_output_shape(r)
        assert r["reason_codes"] == ["NOT_FINAL"]
        assert state["adapter_calls"] == 0
        assert state["sleep_calls"] == 0


# ---------------------------------------------------------------------------
# 2. 交易日历信任边界：零请求
# ---------------------------------------------------------------------------

class TestCalendarTrust:
    @pytest.mark.parametrize("bad_cal", [
        None, "string", {"2026-07-30": 1}, object(),
        [], (), set(), frozenset(),
        ["2026-07-30", 123], ["2026-07-30", True],
        ["2026-07-30", "bad-date"], ["2026-07-30", "2026-02-30"],
        [object()], [datetime(2026, 7, 30)],
    ])
    def test_invalid_calendar(self, monkeypatch, bad_cal):
        r, state = _run(monkeypatch, [_adapter_obs()], cal=bad_cal)
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["TRADING_CALENDAR_UNAVAILABLE"]
        assert state["adapter_calls"] == 0
        assert state["sleep_calls"] == 0

    def test_calendar_raises(self, monkeypatch):
        def boom():
            raise RuntimeError("cal broken")
        monkeypatch.setattr(trade_calendar, "_load_calendar", boom)
        r, state = _run(monkeypatch, [_adapter_obs()])
        assert r["reason_codes"] == ["TRADING_CALENDAR_UNAVAILABLE"]
        assert state["adapter_calls"] == 0

    @pytest.mark.parametrize("bad_today", [
        None, "2026-08-04", object(),
        datetime(2026, 8, 4, 9, 30),
        datetime(2026, 8, 4, 9, 30, tzinfo=timezone(timedelta(hours=8))),
    ])
    def test_invalid_today(self, monkeypatch, bad_today):
        r, state = _run(monkeypatch, [_adapter_obs()], today=bad_today,
                        cal=SESSIONS)
        _assert_output_shape(r)
        assert r["reason_codes"] == ["TRADING_CALENDAR_UNAVAILABLE"]
        assert state["adapter_calls"] == 0
        assert state["sleep_calls"] == 0

    def test_today_raises(self, monkeypatch):
        def boom():
            raise RuntimeError("today broken")
        monkeypatch.setattr(trade_calendar, "_today_shanghai", boom)
        r, state = _run(monkeypatch, [_adapter_obs()])
        assert r["reason_codes"] == ["TRADING_CALENDAR_UNAVAILABLE"]
        assert state["adapter_calls"] == 0

    @pytest.mark.parametrize("container", [
        ("2026-07-30", "2026-07-29"),
        ["2026-07-30", "2026-07-29"],
        {"2026-07-30", "2026-07-29"},
        frozenset({"2026-07-30", "2026-07-29"}),
    ])
    def test_valid_containers_work(self, monkeypatch, container):
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), _adapter_obs()],
                        cal=container)
        assert r["status"] == "normal"
        assert r["is_final"] is True

    def test_duplicate_legal_sessions_allowed(self, monkeypatch):
        r, _ = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), _adapter_obs()],
                    cal=("2026-07-30", "2026-07-30", "2026-07-30"))
        assert r["status"] == "normal"
        assert r["is_final"] is True


# ---------------------------------------------------------------------------
# 3. 成功 final
# ---------------------------------------------------------------------------

class TestFinalSuccess:
    def test_three_identical_non_empty(self, monkeypatch):
        obs = _adapter_obs()
        r, state = _run(monkeypatch, [obs, obs, obs])
        _assert_output_shape(r)
        assert r["status"] == "normal"
        assert r["reason_codes"] == []
        assert r["session"] == "final"
        assert r["is_final"] is True
        assert r["finality_basis"] == "three_identical_normal_observations"
        assert r["completed_observations"] == 3
        assert r["stable_observation_count"] == 3
        assert r["actual_stability_window_seconds"] == pytest.approx(4.4)
        assert r["snapshot"] is obs
        assert r["warnings"] == []
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2

    def test_three_identical_target_universe_empty(self, monkeypatch):
        obs = _target_universe_empty_obs()
        r, state = _run(monkeypatch, [obs, obs, obs])
        _assert_output_shape(r)
        assert r["status"] == "normal"
        assert r["is_final"] is True
        assert r["snapshot"]["rows"] == []
        assert r["snapshot"]["target_universe_empty_after_filter"] is True
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2

    def test_observed_at_differs_still_stable(self, monkeypatch):
        obs1 = _adapter_obs(observed_at="2026-07-30T15:10:00Z")
        obs2 = _adapter_obs(observed_at="2026-07-30T15:10:03Z")
        obs3 = _adapter_obs(observed_at="2026-07-30T15:10:06Z")
        r, _ = _run(monkeypatch, [obs1, obs2, obs3])
        assert r["status"] == "normal"
        assert r["is_final"] is True

    def test_http_status_differs_still_stable(self, monkeypatch):
        obs1 = _adapter_obs(http_status=200)
        obs2 = _adapter_obs(http_status=201)
        obs3 = _adapter_obs(http_status=202)
        r, _ = _run(monkeypatch, [obs1, obs2, obs3])
        assert r["status"] == "normal"
        assert r["is_final"] is True

    def test_dict_insertion_order_differs_still_stable(self, monkeypatch):
        obs1 = _adapter_obs(rows=[{"stock_code": "600000", "lbc": 1}])
        obs2 = _adapter_obs(rows=[{"lbc": 1, "stock_code": "600000"}])
        obs3 = _adapter_obs(rows=[{"stock_code": "600000", "lbc": 1}])
        r, _ = _run(monkeypatch, [obs1, obs2, obs3])
        assert r["status"] == "normal"
        assert r["is_final"] is True


# ---------------------------------------------------------------------------
# 4. 不稳定：指纹不一致
# ---------------------------------------------------------------------------

class TestUnstable:
    @pytest.mark.parametrize("third_overrides", [
        {"rows": [{"stock_code": "600001", "lbc": 1}], "row_count": 1,
         "source_pool_row_count": 1},
        {"rows": [{"stock_code": "600000", "lbc": 2}], "row_count": 1},
        {"rows": [{"stock_code": "600000", "lbc": 1},
                  {"stock_code": "600001", "lbc": 1}], "row_count": 2,
         "source_pool_row_count": 2},
        {"source_pool_row_count": 2, "excluded_universe_count": 1},
    ])
    def test_instability_variants(self, monkeypatch, third_overrides):
        obs1 = _adapter_obs()
        obs2 = _adapter_obs()
        obs3 = _adapter_obs(**third_overrides)
        r, state = _run(monkeypatch, [obs1, obs2, obs3])
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["NOT_FINAL", "SNAPSHOT_UNSTABLE"]
        assert r["session"] == "not_final"
        assert r["is_final"] is False
        assert r["snapshot"] is None
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2

    def test_target_universe_flag_change_unstable(self, monkeypatch):
        obs1 = _adapter_obs()
        obs2 = _adapter_obs()
        obs3 = _target_universe_empty_obs()
        r, _ = _run(monkeypatch, [obs1, obs2, obs3])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["NOT_FINAL", "SNAPSHOT_UNSTABLE"]
        assert r["snapshot"] is None


# ---------------------------------------------------------------------------
# 5. 适配器状态：partial / unavailable / 异常，失败即停
# ---------------------------------------------------------------------------

class TestAdapterStatus:
    def test_partial_first(self, monkeypatch):
        partial = _adapter_obs(status="partial",
                               reason_codes=["INVALID_POOL_ROW"],
                               coverage_warning=True)
        r, state = _run(monkeypatch, [partial])
        _assert_output_shape(r)
        assert r["status"] == "partial"
        assert r["reason_codes"] == ["SOURCE_PARTIAL"]
        assert r["session"] == "not_final"
        assert r["is_final"] is False
        assert r["snapshot"] is None
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 0
        assert r["completed_observations"] == 1
        assert r["stable_observation_count"] == 0
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 100.0
        assert r["actual_stability_window_seconds"] == 0.0

    def test_partial_second(self, monkeypatch):
        partial = _adapter_obs(status="partial",
                               reason_codes=["INVALID_POOL_ROW"],
                               coverage_warning=True)
        r, state = _run(monkeypatch, [_adapter_obs(), partial])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SOURCE_PARTIAL"]
        assert r["status"] == "partial"
        assert state["adapter_calls"] == 2
        assert state["sleep_calls"] == 1
        assert r["completed_observations"] == 2
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 102.2
        assert r["actual_stability_window_seconds"] == pytest.approx(2.2)

    def test_unavailable_first(self, monkeypatch):
        unavail = _adapter_obs(status="unavailable",
                               reason_codes=["HTTP_ERROR"], rows=[],
                               parse_success=False, required_field_present=False,
                               data_array_present=False, row_count=0)
        r, state = _run(monkeypatch, [unavail])
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["SOURCE_UNAVAILABLE"]
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 0
        assert r["completed_observations"] == 1
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 100.0
        assert r["actual_stability_window_seconds"] == 0.0

    def test_unavailable_second(self, monkeypatch):
        unavail = _adapter_obs(status="unavailable",
                               reason_codes=["HTTP_ERROR"], rows=[],
                               parse_success=False, required_field_present=False,
                               data_array_present=False, row_count=0)
        r, state = _run(monkeypatch, [_adapter_obs(), unavail])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SOURCE_UNAVAILABLE"]
        assert state["adapter_calls"] == 2
        assert state["sleep_calls"] == 1
        assert r["completed_observations"] == 2
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 102.2
        assert r["actual_stability_window_seconds"] == pytest.approx(2.2)

    def test_adapter_exception_no_leak(self, monkeypatch):
        r, state = _run(
            monkeypatch,
            [RuntimeError("secret upstream token abc123xyz"), _adapter_obs()],
        )
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SOURCE_UNAVAILABLE"]
        assert r["status"] == "unavailable"
        text = str(r)
        assert "abc123xyz" not in text
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 0
        assert r["completed_observations"] == 0
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 100.0
        assert r["actual_stability_window_seconds"] == 0.0

    def test_adapter_exception_third(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(),
                                      RuntimeError("boom")])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SOURCE_UNAVAILABLE"]
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2
        assert r["completed_observations"] == 2
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 104.4
        assert r["actual_stability_window_seconds"] == pytest.approx(4.4)


# ---------------------------------------------------------------------------
# 6. schema 校验：SNAPSHOT_SCHEMA_INVALID
# ---------------------------------------------------------------------------

class TestSchemaInvalid:
    @pytest.mark.parametrize("overrides", [
        {"status": "weird"},
        {"schema_version": "wrong-version"},
        {"requested_trade_date": "2026-07-29"},
        {"reason_codes": ["UNEXPLAINED_EMPTY"]},
        {"transport_success": False},
        {"parse_success": False},
        {"required_field_present": False},
        {"data_array_present": False},
        {"trade_date_match": None},
        {"trade_date_match": False},
        {"coverage_warning": True},
        {"upstream_null": True},
        {"unexplained_empty": True},
        {"legal_zero": True},
        {"row_count": 2},
        {"source_pool_row_count": 0},
        {"invalid_row_count": 1},
        {"duplicate_code_count": 1},
        {"rows": "not-a-list"},
        {"rows": [{"stock_code": "600000", "lbc": 1, "extra": 1}], "row_count": 1},
        {"rows": [{"stock_code": "60000", "lbc": 1}], "row_count": 1},
        {"rows": [{"stock_code": "600000", "lbc": 0}], "row_count": 1},
        {"rows": [{"stock_code": "600000", "lbc": True}], "row_count": 1},
        {"rows": [{"stock_code": "600000", "lbc": "2"}], "row_count": 1},
        {"rows": [{"stock_code": "600001", "lbc": 1},
                  {"stock_code": "600000", "lbc": 1}], "row_count": 2,
         "source_pool_row_count": 2},
        {"rows": [{"stock_code": "600000", "lbc": 1},
                  {"stock_code": "600000", "lbc": 2}], "row_count": 2,
         "source_pool_row_count": 2},
    ])
    def test_invalid_contract(self, monkeypatch, overrides):
        bad = _adapter_obs(**overrides)
        r, state = _run(monkeypatch, [bad])
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
        assert r["is_final"] is False
        assert r["snapshot"] is None
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 0

    def test_non_dict_observation(self, monkeypatch):
        r, state = _run(monkeypatch, ["not-a-dict"])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
        assert state["adapter_calls"] == 1

    def test_missing_row_count_key(self, monkeypatch):
        bad = _adapter_obs()
        del bad["row_count"]
        r, _ = _run(monkeypatch, [bad])
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]

    def test_source_empty_rejected(self, monkeypatch):
        # 原始 source pool 为空：适配器本就返回 partial/UNEXPLAINED_EMPTY，
        # 即使伪造 normal 也必须被 schema 校验拒绝
        bad = _adapter_obs(rows=[], row_count=0, source_pool_row_count=0,
                           excluded_universe_count=0,
                           target_universe_empty_after_filter=False)
        r, _ = _run(monkeypatch, [bad])
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]

    def test_empty_rows_excluded_mismatch_rejected(self, monkeypatch):
        bad = _adapter_obs(rows=[], row_count=0, source_pool_row_count=3,
                           excluded_universe_count=2,
                           target_universe_empty_after_filter=True)
        r, _ = _run(monkeypatch, [bad])
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]


# ---------------------------------------------------------------------------
# 7. 时钟与 sleep
# ---------------------------------------------------------------------------

class TestClockAndSleep:
    @pytest.mark.parametrize("clock_impl", [
        lambda: (_ for _ in ()).throw(RuntimeError("clock")),
        lambda: True,
        lambda: "abc",
        lambda: float("nan"),
        lambda: float("inf"),
    ])
    def test_bad_monotonic_first(self, monkeypatch, clock_impl):
        r, state = _run(monkeypatch, [_adapter_obs()], clock_fn=clock_impl)
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["STABILITY_WINDOW_ERROR"]
        assert state["adapter_calls"] == 0
        assert state["sleep_calls"] == 0

    def test_clock_regression(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), _adapter_obs()],
                        clock_values=[100.0, 102.2, 101.0])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["STABILITY_WINDOW_ERROR"]
        assert state["adapter_calls"] == 2
        assert state["sleep_calls"] == 2

    def test_window_shortfall(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), _adapter_obs()],
                        clock_values=[100.0, 102.0, 104.0])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["STABILITY_WINDOW_ERROR"]
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 104.0
        assert r["actual_stability_window_seconds"] == pytest.approx(4.0)
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2

    def test_sleep_raises(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs()],
                        sleep_exc=RuntimeError("sleep boom"))
        _assert_output_shape(r)
        assert r["reason_codes"] == ["STABILITY_WINDOW_ERROR"]
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 1

    def test_monotonic_raises_second_read(self, monkeypatch):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] <= 1:
                return 100.0
            raise RuntimeError("clock boom")

        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs()],
                        clock_fn=flaky)
        _assert_output_shape(r)
        assert r["reason_codes"] == ["STABILITY_WINDOW_ERROR"]
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 1
        assert r["completed_observations"] == 1
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 100.0
        assert r["actual_stability_window_seconds"] == 0.0


# ---------------------------------------------------------------------------
# 8. 进程控制异常自然传播
# ---------------------------------------------------------------------------

class TestProcessControl:
    def _propagates(self, fn, exc_type):
        with pytest.raises(exc_type):
            fn()

    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(), SystemExit(1), GeneratorExit(),
    ])
    def test_adapter_propagates(self, monkeypatch, exc):
        self._propagates(
            lambda: _run(monkeypatch, [exc]),
            type(exc),
        )

    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(), SystemExit(1), GeneratorExit(),
    ])
    def test_sleep_propagates(self, monkeypatch, exc):
        self._propagates(
            lambda: _run(monkeypatch, [_adapter_obs(), _adapter_obs()],
                         sleep_exc=exc),
            type(exc),
        )

    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(), SystemExit(1), GeneratorExit(),
    ])
    def test_monotonic_propagates(self, monkeypatch, exc):
        def raiser():
            raise exc
        self._propagates(
            lambda: _run(monkeypatch, [_adapter_obs()], clock_fn=raiser),
            type(exc),
        )

    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(), SystemExit(1), GeneratorExit(),
    ])
    def test_load_calendar_propagates(self, monkeypatch, exc):
        def raiser():
            raise exc
        monkeypatch.setattr(trade_calendar, "_load_calendar", raiser)
        self._propagates(lambda: _run(monkeypatch, [_adapter_obs()]), type(exc))

    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(), SystemExit(1), GeneratorExit(),
    ])
    def test_today_propagates(self, monkeypatch, exc):
        def raiser():
            raise exc
        monkeypatch.setattr(trade_calendar, "_today_shanghai", raiser)
        self._propagates(lambda: _run(monkeypatch, [_adapter_obs()]), type(exc))


# ---------------------------------------------------------------------------
# 9. 计时锚点
# ---------------------------------------------------------------------------

class TestTimingAnchors:
    def test_exact_success_anchors(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), _adapter_obs()],
                        clock_values=[100.0, 102.2, 104.4])
        _assert_output_shape(r)
        assert r["status"] == "normal"
        assert r["is_final"] is True
        assert r["first_observation_monotonic"] == 100.0
        assert r["last_observation_monotonic"] == 104.4
        assert r["actual_stability_window_seconds"] == pytest.approx(4.4)
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2

    def test_monotonic_calls_on_success(self, monkeypatch):
        calls = {"n": 0}

        def counting_clock():
            calls["n"] += 1
            return [100.0, 102.2, 104.4][min(calls["n"] - 1, 2)]

        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), _adapter_obs()],
                        clock_fn=counting_clock)
        _assert_output_shape(r)
        assert r["is_final"] is True
        # 成功路径恰 3 次 observation-start 读取，无 pre-loop 读取
        assert calls["n"] == 3

    def test_second_read_regression(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), _adapter_obs()],
                        clock_values=[100.0, 99.0])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["STABILITY_WINDOW_ERROR"]
        assert r["is_final"] is False
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 1

    def test_third_read_regression(self, monkeypatch):
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), _adapter_obs()],
                        clock_values=[100.0, 102.2, 101.0])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["STABILITY_WINDOW_ERROR"]
        assert state["adapter_calls"] == 2
        assert state["sleep_calls"] == 2

    def test_no_timing_evidence_before_first_read(self, monkeypatch):
        # monotonic 首次读取即失败 → 无 observation-start 时间
        def bad_clock():
            raise RuntimeError("clock")

        r, _ = _run(monkeypatch, [_adapter_obs()], clock_fn=bad_clock)
        _assert_output_shape(r)
        assert r["first_observation_monotonic"] is None
        assert r["last_observation_monotonic"] is None
        assert r["actual_stability_window_seconds"] is None


# ---------------------------------------------------------------------------
# 10. hash 碰撞不能伪造 final
# ---------------------------------------------------------------------------

class TestHashCollision:
    def test_forced_identical_digest_different_content(self, monkeypatch):
        class ConstantSHA:
            def __init__(self, *a, **k):
                pass

            def update(self, *a, **k):
                pass

            def hexdigest(self):
                return "deadbeef" * 8

        def fake_sha(*a, **k):
            return ConstantSHA(*a, **k)

        monkeypatch.setattr(producer.hashlib, "sha256", fake_sha)
        obs1 = _adapter_obs(rows=[{"stock_code": "600000", "lbc": 1}])
        obs2 = _adapter_obs(rows=[{"stock_code": "600000", "lbc": 2}])
        obs3 = _adapter_obs(rows=[{"stock_code": "000001", "lbc": 1}])
        r, state = _run(monkeypatch, [obs1, obs2, obs3])
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["NOT_FINAL", "SNAPSHOT_UNSTABLE"]
        assert r["is_final"] is False
        assert r["session"] == "not_final"
        assert r["snapshot"] is None
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2


# ---------------------------------------------------------------------------
# 11. 完整适配器字段集合
# ---------------------------------------------------------------------------

class TestMissingFields:
    @pytest.mark.parametrize("drop", [
        "source_id", "endpoint", "observed_at", "http_status",
        "error_class", "excluded_universe_count",
    ])
    def test_missing_field_rejected(self, monkeypatch, drop):
        bad = _adapter_obs()
        del bad[drop]
        r, state = _run(monkeypatch, [bad])
        _assert_output_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
        assert r["is_final"] is False
        assert r["snapshot"] is None
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 0

    def test_extra_top_level_field_rejected(self, monkeypatch):
        bad = _adapter_obs()
        bad["extra_field"] = 1
        r, state = _run(monkeypatch, [bad])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
        assert state["adapter_calls"] == 1


# ---------------------------------------------------------------------------
# 12. 类型边界
# ---------------------------------------------------------------------------

class TestTypeBoundaries:
    @pytest.mark.parametrize("bad_excluded", [
        "0", True, False, -1, 1.5, float("nan"), float("inf"),
        object(), set(), b"bytes",
    ])
    def test_excluded_count_rejected(self, monkeypatch, bad_excluded):
        bad = _adapter_obs(excluded_universe_count=bad_excluded)
        try:
            r, state = _run(monkeypatch, [bad])
            ok = (r["status"] == "unavailable"
                  and r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
                  and r["snapshot"] is None)
            assert ok, f"got {r['status']} {r['reason_codes']}"
            assert state["adapter_calls"] == 1
        except Exception as e:
            pytest.fail(f"raised {type(e).__name__}: {e}")

    @pytest.mark.parametrize("overrides", [
        {"invalid_row_count": False},
        {"duplicate_code_count": False},
        {"http_status": True},
        {"row_count": True},
        {"source_pool_row_count": True},
    ])
    def test_bool_cannot_impersonate(self, monkeypatch, overrides):
        bad = _adapter_obs(**overrides)
        r, _ = _run(monkeypatch, [bad])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
        assert r["is_final"] is False

    def test_observed_at_unparseable_rejected(self, monkeypatch):
        for bad in ["not-a-time", "2026-07-30", "2026-07-30T15:10:00+08:00"]:
            bad_obs = _adapter_obs(observed_at=bad)
            r, _ = _run(monkeypatch, [bad_obs])
            _assert_output_shape(r)
            assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"], bad

    def test_http_status_range_rejected(self, monkeypatch):
        for code in [99, 600, -1]:
            bad = _adapter_obs(http_status=code)
            r, _ = _run(monkeypatch, [bad])
            assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"], code


# ---------------------------------------------------------------------------
# 13. 计数守恒
# ---------------------------------------------------------------------------

class TestCountConservation:
    def test_inconsistent_counts_rejected(self, monkeypatch):
        bad = _adapter_obs(source_pool_row_count=3,
                           excluded_universe_count=1)
        r, state = _run(monkeypatch, [bad])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
        assert state["adapter_calls"] == 1

    def test_consistent_counts_accepted(self, monkeypatch):
        good = _adapter_obs(source_pool_row_count=2,
                            excluded_universe_count=1)
        r, _ = _run(monkeypatch, [good, good, good])
        assert r["status"] == "normal"
        assert r["is_final"] is True


# ---------------------------------------------------------------------------
# 14. completed_observations 计数语义
# ---------------------------------------------------------------------------

class TestCounters:
    def test_unavailable_third(self, monkeypatch):
        unavail = _adapter_obs(status="unavailable",
                               reason_codes=["HTTP_ERROR"], rows=[],
                               parse_success=False, required_field_present=False,
                               data_array_present=False, row_count=0)
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), unavail])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SOURCE_UNAVAILABLE"]
        assert r["completed_observations"] == 3
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2

    def test_schema_invalid_first(self, monkeypatch):
        bad = _adapter_obs(schema_version="wrong")
        r, state = _run(monkeypatch, [bad])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
        assert r["completed_observations"] == 1
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 0

    def test_schema_invalid_third(self, monkeypatch):
        bad = _adapter_obs(schema_version="wrong")
        r, state = _run(monkeypatch, [_adapter_obs(), _adapter_obs(), bad])
        _assert_output_shape(r)
        assert r["reason_codes"] == ["SNAPSHOT_SCHEMA_INVALID"]
        assert r["completed_observations"] == 3
        assert r["stable_observation_count"] == 2
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2


# ---------------------------------------------------------------------------
# 15. stable_observation_count 语义
# ---------------------------------------------------------------------------

class TestStableCount:
    def _seq(self, monkeypatch, lbc_seq):
        obs_list = [_adapter_obs(rows=[{"stock_code": "600000", "lbc": lbc}])
                    for lbc in lbc_seq]
        return _run(monkeypatch, obs_list)[0]

    def test_aaa(self, monkeypatch):
        r = self._seq(monkeypatch, [1, 1, 1])
        assert r["is_final"] is True
        assert r["stable_observation_count"] == 3

    def test_aba(self, monkeypatch):
        r = self._seq(monkeypatch, [1, 2, 1])
        assert r["reason_codes"] == ["NOT_FINAL", "SNAPSHOT_UNSTABLE"]
        assert r["stable_observation_count"] == 2

    def test_abb(self, monkeypatch):
        r = self._seq(monkeypatch, [1, 2, 2])
        assert r["reason_codes"] == ["NOT_FINAL", "SNAPSHOT_UNSTABLE"]
        assert r["stable_observation_count"] == 1

    def test_aab(self, monkeypatch):
        r = self._seq(monkeypatch, [1, 1, 2])
        assert r["reason_codes"] == ["NOT_FINAL", "SNAPSHOT_UNSTABLE"]
        assert r["stable_observation_count"] == 2


# ---------------------------------------------------------------------------
# 16. 完整合同
# ---------------------------------------------------------------------------

class TestContract:
    def test_reason_normalization(self):
        out = producer._normalize_reason_codes(
            ["UNKNOWN", "SNAPSHOT_UNSTABLE", "NOT_FINAL", "SNAPSHOT_UNSTABLE"])
        assert out == ["NOT_FINAL", "SNAPSHOT_UNSTABLE"]

    def test_public_symbols(self):
        assert producer.__all__ == [
            "SCHEMA_VERSION",
            "REQUIRED_OBSERVATIONS",
            "OBSERVATION_INTERVAL_SECONDS",
            "fetch_final_limit_up_pool_snapshot",
        ]
        assert producer.REQUIRED_OBSERVATIONS == 3
        assert producer.OBSERVATION_INTERVAL_SECONDS == 2.2
        assert producer.SCHEMA_VERSION == "short-term-limit-up-final-snapshot-v0.1"

    def test_public_api_signature(self):
        import inspect
        sig = inspect.signature(producer.fetch_final_limit_up_pool_snapshot)
        params = list(sig.parameters)
        assert params == ["requested_trade_date"]
        assert sig.parameters["requested_trade_date"].default is inspect.Parameter.empty

    def test_failure_paths_shape(self, monkeypatch):
        # 多条失败路径的输出合同与不变量
        bad_input, _ = _run(monkeypatch, [_adapter_obs()], req=None)
        _assert_output_shape(bad_input)
        partial = _adapter_obs(status="partial", reason_codes=["X"],
                               coverage_warning=True)
        r1, _ = _run(monkeypatch, [partial])
        _assert_output_shape(r1)
        unavail = _adapter_obs(status="unavailable", reason_codes=["HTTP_ERROR"],
                               rows=[], row_count=0, parse_success=False,
                               required_field_present=False, data_array_present=False)
        r2, _ = _run(monkeypatch, [unavail])
        _assert_output_shape(r2)

    def test_private_injectables_not_exported(self):
        assert "_fetch_adapter_snapshot" not in producer.__all__
        assert "_sleep" not in producer.__all__
        assert "_monotonic" not in producer.__all__


# ---------------------------------------------------------------------------
# 10. 运行时复用：真实适配器路径（fake 上游）
# ---------------------------------------------------------------------------

class TestRuntimeReuse:
    def _run_real(self, monkeypatch, bodies, cal=None, today=None):
        """不 patch 生产者适配器引用，走真实适配器；仅 fake 上游 HTTP。"""
        upstream = {"n": 0}

        def fake_em_get(*a, **k):
            body = bodies[min(upstream["n"], len(bodies) - 1)]
            upstream["n"] += 1

            class R:
                status_code = 200

                def json(self):
                    return body

            return R()

        monkeypatch.setattr(astock, "em_get", fake_em_get)
        state = {"adapter_calls": 0, "sleep_calls": 0}

        orig_adapter = producer._fetch_adapter_snapshot

        def counting_adapter(req):
            state["adapter_calls"] += 1
            return orig_adapter(req)

        monkeypatch.setattr(producer, "_fetch_adapter_snapshot", counting_adapter)
        monkeypatch.setattr(
            producer, "_sleep",
            lambda sec: state.__setitem__("sleep_calls", state["sleep_calls"] + 1),
        )
        monkeypatch.setattr(producer, "_monotonic", _Clock([100.0, 102.2, 104.4]))
        if cal is not None:
            monkeypatch.setattr(trade_calendar, "_load_calendar", lambda: cal)
        if today is not None:
            monkeypatch.setattr(trade_calendar, "_today_shanghai", lambda: today)
        return producer.fetch_final_limit_up_pool_snapshot(GOOD_DATE), state, upstream

    def test_real_adapter_success_path(self, monkeypatch):
        body = {"trade_date": "2026-07-30",
                "data": {"date": "2026-07-30",
                         "pool": [{"c": "600000", "lbc": 1}]}}
        r, state, upstream = self._run_real(monkeypatch, [body, body, body])
        _assert_output_shape(r)
        assert r["status"] == "normal"
        assert r["is_final"] is True
        assert r["snapshot"]["rows"] == [{"stock_code": "600000", "lbc": 1}]
        assert state["adapter_calls"] == 3
        assert state["sleep_calls"] == 2
        assert upstream["n"] == 3

    def test_real_adapter_returns_partial(self, monkeypatch):
        body = {"data": {"date": "2026-07-30", "pool": []}}
        r, state, upstream = self._run_real(monkeypatch, [body])
        _assert_output_shape(r)
        assert r["status"] == "partial"
        assert r["reason_codes"] == ["SOURCE_PARTIAL"]
        assert r["is_final"] is False
        assert r["snapshot"] is None
        assert state["adapter_calls"] == 1
        assert state["sleep_calls"] == 0
        assert upstream["n"] == 1
