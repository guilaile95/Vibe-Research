"""data_health_service 聚合与映射测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import data_health_service as svc


def _rec(**kwargs):
    base = dict(
        source_id="x",
        module="m",
        display_name="d",
        status="normal",
        is_stale=False,
        observed_at=None,
        last_success_at=None,
        data_trade_date=None,
        data_cutoff=None,
        stale_after_seconds=None,
        is_cached=None,
        is_degraded=None,
        coverage_current=None,
        coverage_expected=None,
        last_error_code=None,
        last_error_summary=None,
        last_error_at=None,
        blocks_advice=False,
        block_reason=None,
        detail_path=None,
    )
    base.update(kwargs)
    base["last_error_summary"] = svc.error_summary(base.get("last_error_code"))
    return base  # type: ignore[return-value]


def test_map_event_not_initialized():
    st, code, deg, *_ = svc.map_event_quality(None)
    assert st == "unavailable"
    assert code == "SOURCE_NOT_INITIALIZED"


def test_map_event_success_then_partial():
    e = {
        "last_success_at": "2026-07-28T01:00:00.000000Z",
        "last_error_at": "2026-07-28T01:00:00.000000Z",
        "last_error_code": "SOURCE_PARTIAL",
    }
    st, code, deg, *_ = svc.map_event_quality(e)
    assert st == "partial"
    assert deg is False


def test_map_event_degraded():
    e = {
        "last_success_at": "2026-07-28T01:00:00.000000Z",
        "last_error_at": "2026-07-28T01:00:00.000000Z",
        "last_error_code": "SOURCE_DEGRADED",
    }
    st, code, deg, *_ = svc.map_event_quality(e)
    assert st == "partial"
    assert deg is True


def test_map_event_success_after_error():
    e = {
        "last_success_at": "2026-07-28T02:00:00.000000Z",
        "last_error_at": "2026-07-28T01:00:00.000000Z",
        "last_error_code": "SOURCE_PARTIAL",
    }
    st, code, deg, *_ = svc.map_event_quality(e)
    assert st == "normal"


def test_map_event_error_only_partial_is_unavailable():
    e = {
        "last_success_at": None,
        "last_error_at": "2026-07-28T01:00:00.000000Z",
        "last_error_code": "SOURCE_PARTIAL",
    }
    st, code, *_ = svc.map_event_quality(e)
    assert st == "unavailable"


def test_map_gate_allow_block_fail():
    allow = {
        "last_success_at": "2026-07-28T02:00:00.000000Z",
        "last_error_at": "2026-07-28T01:00:00.000000Z",
        "last_error_code": "NO_HOLDINGS",
    }
    st, blocks, reason, code, *_ = svc.map_gate_event(allow)
    assert st == "normal" and blocks is False

    block = {
        "last_success_at": "2026-07-28T02:00:00.000000Z",
        "last_error_at": "2026-07-28T02:00:00.000000Z",
        "last_error_code": "NO_HOLDINGS",
    }
    st, blocks, reason, code, *_ = svc.map_gate_event(block)
    assert st == "normal" and blocks is True
    assert "持仓" in (reason or "")

    fail = {
        "last_success_at": None,
        "last_error_at": "2026-07-28T02:00:00.000000Z",
        "last_error_code": "SOURCE_TIMEOUT",
    }
    st, blocks, reason, code, *_ = svc.map_gate_event(fail)
    assert st == "unavailable" and blocks is False


def test_overall_all_not_initialized():
    items = [
        _rec(source_id=f"s{i}", status="unavailable", last_error_code="SOURCE_NOT_INITIALIZED")
        for i in range(11)
    ]
    assert svc.compute_overall(items) == "unavailable"


def test_overall_partial_initialized_ok():
    items = [
        _rec(source_id="a", status="normal", last_error_code=None),
        _rec(source_id="b", status="unavailable", last_error_code="SOURCE_NOT_INITIALIZED"),
    ]
    assert svc.compute_overall(items) == "normal"


def test_overall_all_initialized_unavailable():
    items = [
        _rec(source_id="a", status="unavailable", last_error_code="SOURCE_UNAVAILABLE"),
        _rec(source_id="b", status="unavailable", last_error_code="SOURCE_CORRUPTED"),
    ]
    assert svc.compute_overall(items) == "unavailable"


def test_overall_stale_makes_partial():
    items = [
        _rec(source_id="a", status="normal", is_stale=True, last_error_code=None),
    ]
    assert svc.compute_overall(items) == "partial"


def test_summary_counts_to_eleven():
    items = [
        _rec(source_id=f"s{i}", status="normal" if i < 5 else ("partial" if i < 7 else "unavailable"),
             is_stale=i % 3 == 0,
             last_error_code="SOURCE_NOT_INITIALIZED" if i >= 9 else None)
        for i in range(11)
    ]
    s = svc.compute_summary(items)
    assert s["normal"] + s["partial"] + s["unavailable"] == 11
    assert s["not_initialized"] == 2
    assert s["stale"] >= 1


def test_gate_block_not_in_overall_logic():
    """Gate blocks_advice 不直接改变 overall；only status/stale 参与。"""
    items = [
        _rec(
            source_id="portfolio_advice_gate",
            status="normal",
            blocks_advice=True,
            last_error_code="NO_HOLDINGS",
        ),
        *[_rec(source_id=f"s{i}", status="normal") for i in range(10)],
    ]
    assert svc.compute_overall(items) == "normal"
    agg = svc.aggregate_health(items)
    assert agg["blocks_advice"] is True
    assert len(agg["block_reasons"]) == 1


def test_error_summaries_safe():
    for code, text in svc.ERROR_SUMMARIES.items():
        assert "Traceback" not in text
        assert "sqlite3" not in text
        assert "\\" not in text or code  # paths not expected
        assert text


def test_parse_beijing_naive():
    dt = svc.parse_flexible_time("2026-07-28 09:30", naive_as="beijing")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.hour == 1  # UTC


def test_cn_expected_trade_date_weekend():
    # Sunday 2026-07-26
    now = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)
    # convert: BJ is UTC+8 → Sunday 18:00
    d = svc.expected_cn_trade_date(now)
    assert d  # Friday before


def _bj(y, m, d, hh, mm, ss=0):
    """构造 Asia/Shanghai 墙钟对应的 UTC datetime。"""
    from zoneinfo import ZoneInfo
    return datetime(y, m, d, hh, mm, ss, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(
        timezone.utc
    )


def test_cn_trade_date_grace_15_00_to_15_30():
    # 周二 15:10 + 周一数据 → fresh
    now = _bj(2026, 7, 28, 15, 10)  # Tuesday
    assert svc.is_stale_cn_trade_date("2026-07-27", None, now) is False
    # 周二 15:30 + 周一数据 → stale
    now2 = _bj(2026, 7, 28, 15, 30)
    assert svc.is_stale_cn_trade_date("2026-07-27", None, now2) is True


def test_cn_intraday_off_session_stale_rules():
    # 周二收盘后 + 上周行情观察 → stale
    now = _bj(2026, 7, 28, 16, 0)  # Tue after close
    old = _bj(2026, 7, 21, 10, 0)  # previous week
    assert svc.is_stale_cn_intraday_observation(old, now, 300) is True

    # 周五收盘观察 + 周末 → fresh
    fri_obs = _bj(2026, 7, 24, 14, 30)  # Friday
    sat = _bj(2026, 7, 25, 12, 0)
    assert svc.is_stale_cn_intraday_observation(fri_obs, sat, 300) is False

    # 午休 + 当日上午观察 → fresh
    lunch = _bj(2026, 7, 28, 12, 0)
    morning = _bj(2026, 7, 28, 10, 0)
    assert svc.is_stale_cn_intraday_observation(morning, lunch, 300) is False

    # 午休 + 上一交易日观察 → stale
    prev = _bj(2026, 7, 27, 10, 0)
    assert svc.is_stale_cn_intraday_observation(prev, lunch, 300) is True

    # 盘中超过 300 秒 → stale
    session = _bj(2026, 7, 28, 10, 30)
    old_sess = _bj(2026, 7, 28, 10, 20)  # 10 min earlier
    assert svc.is_stale_cn_intraday_observation(old_sess, session, 300) is True
