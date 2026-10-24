"""The browser clock fixture controls time, never production business rules."""
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path

import pytest

from test_frozen_decision_service import valid_payload


@pytest.fixture
def clock(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "frontend/tests/e2e/temporal_clock.py"
    spec = importlib.util.spec_from_file_location("e2e_temporal_clock", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock_file = tmp_path / "clock.txt"
    clock_file.write_text("2026-08-28T08:00:00.000000Z")
    monkeypatch.setenv("E2E_CLOCK_FILE", str(clock_file))
    module.install(monkeypatch.setattr)
    return module, clock_file


def test_all_boundary_clocks_follow_explicit_phases(clock):
    import decision_commit_runtime as commit
    import decision_challenge_runtime as challenge
    import formal_decision_outcome_runtime as outcome
    import frozen_decision_service as frozen
    import trade_ledger_service as trades
    module, file = clock
    for instant in ("2026-08-28T08:00:00.000000Z", "2026-09-02T08:00:00.000000Z"):
        file.write_text(instant)
        assert module.utc_now_iso() == commit.utc_now_iso() == frozen._utc_now_iso() == instant
        assert challenge.PRODUCTION_PORTS.clock() == outcome._now() == instant
        assert trades._execution_now() == datetime.fromisoformat(instant.replace("Z", "+00:00"))


def test_expiry_blocks_new_decisions_but_keeps_exact_historical_replay(clock, tmp_path):
    import frozen_decision_service as frozen
    _, file = clock
    db = tmp_path / "decisions.sqlite3"
    payload = valid_payload(review_by="2026-08-29T10:00:00Z")
    original = frozen.freeze_decision(payload, db)
    assert original["committed_at"] == "2026-08-28T08:00:00.000000Z"
    file.write_text("2026-09-02T08:00:00Z")
    with pytest.raises(frozen.FrozenDecisionReviewBoundaryExpiredError):
        frozen.freeze_decision(payload, db)
    assert frozen.freeze_decision(original, db) == original
    assert frozen.get_decision(original["decision_id"], db) == original


def test_preview_still_rejects_expired_review_before_reading_authorities(clock):
    import decision_commit_runtime as commit
    payload = {
        "asset_view": {}, "trade_view": {}, "portfolio_view": {},
        "review_by": "2026-08-28T08:00:00Z", "key_assumptions": [],
        "event_invalidation_conditions": [], "strategy_horizon": "2w",
    }
    with pytest.raises(commit.DecisionCommitInputError, match="review_by"):
        commit.preview_decision_proposal("campaign_" + "a" * 32, payload)


def test_executed_trade_boundary_is_unchanged(clock, monkeypatch, tmp_path):
    import trade_ledger_service as trades
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(tmp_path / "trades.sqlite3"))
    module, file = clock
    payload = {
        "code": "600519", "name": "Synthetic", "operation": "buy",
        "execution_status": "full", "actual_price": 100, "actual_quantity": 1,
        "fee": 0, "other_cost": 0,
    }
    boundary = module.now() + timedelta(minutes=5)
    payload["executed_at"] = (boundary + timedelta(microseconds=1)).isoformat()
    with pytest.raises(trades.TradeValidationError, match="未来"):
        trades.create_trade(payload)
    payload["executed_at"] = boundary.isoformat()
    accepted = trades.create_trade(payload)
    assert datetime.fromisoformat(accepted["executed_at"]) == boundary
    # TAR1 facts are after freeze but already executed in the observation phase.
    file.write_text("2026-09-02T08:00:00Z")
    for instant in ("2026-08-29T01:00:00Z", "2026-08-30T10:00:00Z", "2026-08-31T11:15:00Z"):
        payload["executed_at"] = instant
        assert trades.create_trade(payload)["execution_status"] == "full"


def test_missing_or_invalid_clock_fails_closed(clock, monkeypatch):
    import frozen_decision_service as frozen
    module, file = clock
    previous = frozen._utc_now_iso
    monkeypatch.delenv("E2E_CLOCK_FILE")
    module.install(monkeypatch.setattr)
    assert frozen._utc_now_iso is previous
    monkeypatch.setenv("E2E_CLOCK_FILE", str(file))
    for invalid in ("not-a-time", "2026-08-28T08:00:00", "2026-08-28T08:00:00+08:00"):
        file.write_text(invalid)
        with pytest.raises(ValueError):
            module.install(monkeypatch.setattr)
    file.unlink()
    with pytest.raises(FileNotFoundError):
        module.install(monkeypatch.setattr)
