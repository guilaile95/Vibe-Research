"""Gate 业务阻断 vs 运行失败事件编码。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import data_health_event_store as store
import data_health_service as svc
import portfolio_advice_service as pas


@pytest.fixture()
def events_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    return tmp_path


def test_breadth_unavailable_records_business_block(events_dir, monkeypatch):
    portfolio_data = {
        "holdings": [{"code": "600519", "shares": 100, "cost": 10.0, "price": 20.0}],
        "data_status": "normal",
    }
    monkeypatch.setattr(
        "portfolio.get_portfolio",
        lambda: portfolio_data,
    )
    monkeypatch.setattr(pas.portfolio, "get_portfolio", lambda: portfolio_data)
    monkeypatch.setattr(
        pas.portfolio,
        "_is_valid_price",
        lambda px: isinstance(px, (int, float)) and not isinstance(px, bool) and px > 0,
    )
    monkeypatch.setattr(
        pas.ai_result_service,
        "compute_portfolio_fingerprint",
        lambda holdings: "fp",
    )
    monkeypatch.setattr(
        pas.daily_review,
        "generate_daily_review",
        lambda: {
            "trade_date": "2026-07-28",
            "data_health": {"components": {"breadth": "unavailable"}},
            "market_environment": {"breadth": {"status": "unavailable"}},
        },
    )
    with pytest.raises(pas.PortfolioAdviceMarketDataError):
        pas.prepare_portfolio_advice_messages()
    ev = store.load_events_readonly()["portfolio_advice_gate"]
    assert ev["last_error_code"] == "MARKET_BREADTH_UNAVAILABLE"
    st, blocks, *_ = svc.map_gate_event(ev)
    assert st == "normal"
    assert blocks is True


def test_context_builder_typeerror_is_runtime_failure(events_dir, monkeypatch):
    portfolio_data = {
        "holdings": [{"code": "600519", "shares": 100, "cost": 10.0, "price": 20.0}],
        "data_status": "normal",
    }
    monkeypatch.setattr(pas.portfolio, "get_portfolio", lambda: portfolio_data)
    monkeypatch.setattr(
        pas.portfolio,
        "_is_valid_price",
        lambda px: True,
    )
    monkeypatch.setattr(
        pas.ai_result_service,
        "compute_portfolio_fingerprint",
        lambda holdings: "fp",
    )
    monkeypatch.setattr(
        pas.daily_review,
        "generate_daily_review",
        lambda: {
            "trade_date": "2026-07-28",
            "data_health": {"components": {"breadth": "normal"}},
            "market_environment": {"breadth": {"status": "normal"}},
        },
    )

    def boom(*a, **k):
        raise TypeError("context broken")

    monkeypatch.setattr(
        pas.portfolio_advice_context,
        "build_portfolio_advice_context",
        boom,
    )
    with pytest.raises(pas.PortfolioAdviceMarketDataError):
        pas.prepare_portfolio_advice_messages()
    ev = store.load_events_readonly()["portfolio_advice_gate"]
    assert ev["last_error_code"] == "SOURCE_UNAVAILABLE"
    assert ev["last_success_at"] is None or (
        store.parse_utc(ev["last_error_at"]) is not None
        and (
            ev["last_success_at"] is None
            or store.parse_utc(ev["last_error_at"]) >= store.parse_utc(ev["last_success_at"])
        )
    )
    st, blocks, *_ = svc.map_gate_event(ev)
    assert st == "unavailable"
    assert blocks is False


def test_prompt_builder_valueerror_is_runtime_failure(events_dir, monkeypatch):
    portfolio_data = {
        "holdings": [{"code": "600519", "shares": 100, "cost": 10.0, "price": 20.0}],
        "data_status": "normal",
    }
    monkeypatch.setattr(pas.portfolio, "get_portfolio", lambda: portfolio_data)
    monkeypatch.setattr(pas.portfolio, "_is_valid_price", lambda px: True)
    monkeypatch.setattr(
        pas.ai_result_service, "compute_portfolio_fingerprint", lambda holdings: "fp"
    )
    monkeypatch.setattr(
        pas.daily_review,
        "generate_daily_review",
        lambda: {
            "trade_date": "2026-07-28",
            "data_health": {"components": {"breadth": "normal"}},
            "market_environment": {"breadth": {"status": "normal"}},
        },
    )
    monkeypatch.setattr(
        pas.portfolio_advice_context,
        "build_portfolio_advice_context",
        lambda *a, **k: {"ok": True},
    )

    def boom(*a, **k):
        raise ValueError("prompt broken")

    monkeypatch.setattr(
        pas.portfolio_advice_prompt,
        "build_portfolio_advice_messages",
        boom,
    )
    with pytest.raises(pas.PortfolioAdviceMarketDataError):
        pas.prepare_portfolio_advice_messages()
    ev = store.load_events_readonly()["portfolio_advice_gate"]
    assert ev["last_error_code"] == "SOURCE_UNAVAILABLE"
    st, blocks, *_ = svc.map_gate_event(ev)
    assert st == "unavailable"
    assert blocks is False

from pathlib import Path



# ---------------------------------------------------------------------------
# Gate 业务码不得通过 record_failure 写入 + fail-closed 形状
# ---------------------------------------------------------------------------

def test_record_failure_rejects_gate_business_codes(events_dir):
    """record_failure(portfolio_advice_gate, business_code) must raise."""
    for code in ("NO_HOLDINGS", "HOLDING_QUOTES_UNAVAILABLE",
                 "MARKET_BREADTH_UNAVAILABLE", "REVIEW_TRADE_DATE_UNAVAILABLE"):
        with pytest.raises(store.DataHealthEventStoreError):
            store.record_failure("portfolio_advice_gate", code)


def test_record_failure_gate_only_allows_timeout_unavailable(events_dir):
    """Gate 只允许 SOURCE_TIMEOUT / SOURCE_UNAVAILABLE 通过 record_failure。"""
    for code in ("SOURCE_PARTIAL", "SOURCE_DEGRADED", "SOURCE_STALE",
                 "SOURCE_CORRUPTED", "SOURCE_SCHEMA_INCOMPATIBLE"):
        with pytest.raises(store.DataHealthEventStoreError):
            store.record_failure("portfolio_advice_gate", code)
    # 允许
    store.record_failure("portfolio_advice_gate", "SOURCE_TIMEOUT")
    store.record_failure("portfolio_advice_gate", "SOURCE_UNAVAILABLE")


def test_map_gate_event_business_code_no_success_fail_closed():
    """业务码 + last_error_at only (no last_success_at) → fail-closed SOURCE_CORRUPTED。"""
    e = {
        "last_success_at": None,
        "last_error_at": "2026-07-28T01:00:00.000000Z",
        "last_error_code": "NO_HOLDINGS",
    }
    st, blocks, reason, code, *_ = svc.map_gate_event(e)
    assert st == "unavailable"
    assert blocks is False
    assert code == "SOURCE_CORRUPTED"
    assert reason is None  # 不得显示业务阻断摘要


def test_map_gate_event_business_code_error_after_success_fail_closed():
    """业务码 + last_error_at > last_success_at → fail-closed。"""
    e = {
        "last_success_at": "2026-07-28T01:00:00.000000Z",
        "last_error_at": "2026-07-28T02:00:00.000000Z",
        "last_error_code": "HOLDING_QUOTES_UNAVAILABLE",
    }
    st, blocks, reason, code, *_ = svc.map_gate_event(e)
    assert st == "unavailable"
    assert blocks is False
    assert code == "SOURCE_CORRUPTED"
    assert reason is None


def test_map_gate_event_runtime_failure_not_block():
    """Gate 运行失败码（SOURCE_TIMEOUT）不得解释为业务阻断。"""
    e = {
        "last_success_at": None,
        "last_error_at": "2026-07-28T01:00:00.000000Z",
        "last_error_code": "SOURCE_TIMEOUT",
    }
    st, blocks, reason, code, *_ = svc.map_gate_event(e)
    assert st == "unavailable"
    assert blocks is False
    assert code == "SOURCE_TIMEOUT"
    assert reason is None


def test_map_gate_event_runtime_failure_illegal_code_fail_closed():
    """Gate 运行失败位置但非法错误码 → fail-closed SOURCE_CORRUPTED。"""
    e = {
        "last_success_at": None,
        "last_error_at": "2026-07-28T01:00:00.000000Z",
        "last_error_code": "SOURCE_PARTIAL",  # Gate 不允许
    }
    st, blocks, reason, code, *_ = svc.map_gate_event(e)
    assert st == "unavailable"
    assert blocks is False
    assert code == "SOURCE_CORRUPTED"
    assert reason is None


def test_record_failure_rejection_preserves_event_file(events_dir):
    """拒绝写入后原事件文件内容、size 和 mtime 不变。"""
    path = Path(store.events_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    snap_size = path.stat().st_size
    snap_mtime = path.stat().st_mtime_ns

    for code in ("NO_HOLDINGS", "HOLDING_QUOTES_UNAVAILABLE",
                 "MARKET_BREADTH_UNAVAILABLE", "REVIEW_TRADE_DATE_UNAVAILABLE"):
        try:
            store.record_failure("portfolio_advice_gate", code)
        except store.DataHealthEventStoreError:
            pass

    assert path.exists()
    assert path.stat().st_size == snap_size, "event file size must be unchanged"
    assert path.stat().st_mtime_ns == snap_mtime, "event file mtime must be unchanged"
    assert path.read_text(encoding="utf-8") == "{}"
