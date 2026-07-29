"""Unit tests for signal ledger extraction and archiving service."""

from __future__ import annotations

import signal_ledger_service as svc
import signal_ledger_store as store


def test_archive_signal_ledger(tmp_path):
    db_path = tmp_path / "decision_trace.sqlite3"

    advice_result = {
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00Z",
        "market_overview": {
            "market_sentiment": "cautious_optimistic",
            "position_recommendation": "moderate",
        },
        "account_funding_metrics": {
            "total_asset": 100000.0,
            "available_cash": 20000.0,
            "is_sufficient": True,
        },
        "actions": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "action": "buy",
                "target_ratio": 0.20,
                "reason": "估值回落至合理区间",
                "sellable_quantity_advisory": {
                    "shares_held": 100,
                    "sellable_shares": 100,
                },
            }
        ],
    }

    res = svc.archive_signal_ledger(advice_result, db_path=db_path)
    assert res["status"] == "success"
    assert res["signal_entries_count"] >= 3
    assert res["decision_outcomes_count"] == 1

    run_id = res["decision_run_id"]
    timeline = store.get_run_signal_ledger(run_id, db_path=db_path)
    assert len(timeline["signal_entries"]) >= 3
    assert timeline["decision_outcomes"][0]["code"] == "600519"
    assert timeline["decision_outcomes"][0]["action"] == "buy"
