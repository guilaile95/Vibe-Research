"""Explicit clocks for historical decision/execution fixture scenarios only."""
import pytest


@pytest.fixture(autouse=True)
def historical_decision_server_clock(monkeypatch):
    import frozen_decision_service
    import decision_commit_runtime
    instant = "2026-08-16T00:00:00.000000Z"
    monkeypatch.setattr(frozen_decision_service, "_utc_now_iso", lambda: instant)
    monkeypatch.setattr(decision_commit_runtime, "utc_now_iso", lambda: instant)


@pytest.fixture(autouse=True)
def synthetic_execution_clock(monkeypatch):
    from datetime import datetime, timezone
    import trade_ledger_service
    monkeypatch.setattr(trade_ledger_service, "_execution_now", lambda: datetime(2098, 1, 2, tzinfo=timezone.utc))
