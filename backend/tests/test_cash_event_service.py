"""P0-S1B-B cash event service tests (offline, deterministic).

覆盖矩阵 A–I（43 项核心场景）。全部离线：无网络、临时库、不写真实数据。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import account_event_store
import account_reality_service as ar_svc
import cash_event_service as svc
import position_reality_service
import trade_ledger_service


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    isolated = tmp_path / "ledger_db"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    yield


def _bootstrap(positions: list[dict] | None = None, opening_cash: float | None = 100000.0) -> dict:
    return position_reality_service.bootstrap_commit({
        "ledger_start_at": "2026-08-01",
        "opening_cash": opening_cash,
        "positions": positions or [],
    })


def _trade(code: str, operation: str, price: float, qty: int, name: str = "测试股票", fee: float = 0.0) -> dict:
    return trade_ledger_service.create_trade({
        "code": code,
        "name": name,
        "operation": operation,
        "execution_status": "full",
        "actual_price": price,
        "actual_quantity": qty,
        "executed_at": "2026-08-03T09:30:00+08:00",
        "fee": fee,
    })


def _create(event_type: str, amount: float) -> dict:
    return svc.create_cash_event({"event_type": event_type, "amount": amount})


def _ledger_cash():
    return ar_svc._ledger_cash_candidate(position_reality_service.derive_positions())


# ---------------------------------------------------------------------------
# A. Cash Event Identity / Persistence
# ---------------------------------------------------------------------------


class TestCashEventPersistence:
    def test_deposit_durable(self):
        _bootstrap([])
        event = _create("CASH_DEPOSIT", 1000.0)
        assert event["event_type"] == "CASH_DEPOSIT"
        assert event["amount"] == 1000.0
        assert event["provenance"] == "MANUAL"
        assert svc.get_cash_event(event["event_id"])["event_id"] == event["event_id"]

    def test_withdrawal_create(self):
        _bootstrap([])
        event = _create("CASH_WITHDRAWAL", 200.0)
        assert svc.get_cash_event(event["event_id"])["event_type"] == "CASH_WITHDRAWAL"

    def test_dividend_create(self):
        _bootstrap([])
        event = _create("CASH_DIVIDEND", 100.0)
        assert svc.get_cash_event(event["event_id"])["event_type"] == "CASH_DIVIDEND"

    def test_fee_create(self):
        _bootstrap([])
        event = _create("CASH_FEE", 20.0)
        assert svc.get_cash_event(event["event_id"])["event_type"] == "CASH_FEE"

    def test_tax_create(self):
        _bootstrap([])
        event = _create("CASH_TAX", 10.0)
        assert svc.get_cash_event(event["event_id"])["event_type"] == "CASH_TAX"

    def test_restart_reopen_events_persist(self, tmp_path, monkeypatch):
        """重新打开 DB（重启模拟）→ 事件仍存在。"""
        db = tmp_path / "trade_ledger.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(db))
        _bootstrap([])
        _create("CASH_DEPOSIT", 1000.0)
        # 重启：新 process 模拟 —— 直接重新读库（同一 db 路径）
        events = account_event_store.list_events(svc.resolve_db_path())
        assert [e for e in events if e["event_type"] == "CASH_DEPOSIT"]

    def test_event_id_unique(self):
        _bootstrap([])
        e1 = _create("CASH_DEPOSIT", 100.0)
        e2 = _create("CASH_DEPOSIT", 200.0)
        assert e1["event_id"] != e2["event_id"]

    def test_duplicate_event_id_conflict_no_overwrite(self):
        """重复 event_id（手动插入同 id）→ 不静默覆盖（PK 冲突）。"""
        _bootstrap([])
        event = _create("CASH_DEPOSIT", 100.0)
        dup = dict(event)
        dup["amount"] = 999.0
        dup["created_at"] = "2099-01-01T00:00:00+00:00"
        db = svc.resolve_db_path()
        with pytest.raises(Exception):  # sqlite3.IntegrityError 被 store 封装
            account_event_store.insert_event(db, dup)
        # 原事件未被覆盖
        stored = svc.get_cash_event(event["event_id"])
        assert stored["amount"] == 100.0


# ---------------------------------------------------------------------------
# B. Amount Contract
# ---------------------------------------------------------------------------


class TestAmountContract:
    def test_amount_100_valid(self):
        _bootstrap([])
        assert _create("CASH_DEPOSIT", 100.0)["amount"] == 100.0

    def test_amount_zero_fail(self):
        _bootstrap([])
        with pytest.raises(svc.CashEventValidationError):
            _create("CASH_DEPOSIT", 0.0)

    def test_amount_negative_fail(self):
        _bootstrap([])
        with pytest.raises(svc.CashEventValidationError):
            _create("CASH_DEPOSIT", -100.0)

    def test_amount_nan_fail(self):
        _bootstrap([])
        with pytest.raises(svc.CashEventValidationError):
            _create("CASH_DEPOSIT", float("nan"))

    def test_amount_inf_fail(self):
        _bootstrap([])
        with pytest.raises(svc.CashEventValidationError):
            _create("CASH_DEPOSIT", float("inf"))

    def test_amount_string_fail_closed(self):
        _bootstrap([])
        with pytest.raises(svc.CashEventValidationError):
            _create("CASH_DEPOSIT", "100")

    def test_amount_bool_fail(self):
        _bootstrap([])
        with pytest.raises(svc.CashEventValidationError):
            _create("CASH_DEPOSIT", True)


# ---------------------------------------------------------------------------
# C. Cash Delta（方向由 event_type 决定）
# ---------------------------------------------------------------------------


class TestCashDelta:
    def test_deposit_positive(self):
        assert svc.cash_delta_for("CASH_DEPOSIT", 1000.0) == 1000.0

    def test_withdrawal_negative(self):
        assert svc.cash_delta_for("CASH_WITHDRAWAL", 200.0) == -200.0

    def test_dividend_positive(self):
        assert svc.cash_delta_for("CASH_DIVIDEND", 100.0) == 100.0

    def test_fee_negative(self):
        assert svc.cash_delta_for("CASH_FEE", 20.0) == -20.0

    def test_tax_negative(self):
        assert svc.cash_delta_for("CASH_TAX", 10.0) == -10.0

    def test_mixed_events_deterministic_sum(self):
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DEPOSIT", 1000.0)
        _create("CASH_WITHDRAWAL", 200.0)
        _create("CASH_DIVIDEND", 100.0)
        _create("CASH_FEE", 20.0)
        _create("CASH_TAX", 10.0)
        cand = _ledger_cash()
        assert cand["value"] == 100000.0 + 1000.0 - 200.0 + 100.0 - 20.0 - 10.0


# ---------------------------------------------------------------------------
# D. Ledger Cash Candidate（enhanced）
# ---------------------------------------------------------------------------


class TestEnhancedLedgerCash:
    def test_opening_cash_only(self):
        _bootstrap([], opening_cash=100000.0)
        assert _ledger_cash()["value"] == 100000.0

    def test_opening_plus_buy(self):
        _bootstrap([], opening_cash=100000.0)
        _trade("600519", "buy", 10.0, 100, fee=5.0)
        assert _ledger_cash()["value"] == 100000.0 - 1005.0

    def test_opening_plus_sell(self):
        _bootstrap([{"code": "600519", "shares": 100, "cost_basis": 10.0, "name": "测试股票"}], opening_cash=100000.0)
        _trade("600519", "sell", 15.0, 100)
        assert _ledger_cash()["value"] == 100000.0 + 1500.0

    def test_opening_plus_deposit(self):
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DEPOSIT", 5000.0)
        assert _ledger_cash()["value"] == 105000.0

    def test_opening_plus_withdrawal(self):
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_WITHDRAWAL", 3000.0)
        assert _ledger_cash()["value"] == 97000.0

    def test_opening_plus_dividend_fee_tax(self):
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DIVIDEND", 500.0)
        _create("CASH_FEE", 20.0)
        _create("CASH_TAX", 30.0)
        assert _ledger_cash()["value"] == 100000.0 + 500.0 - 20.0 - 30.0

    def test_trade_correction_plus_cash_event(self):
        """trade correction + cash event 同入 enhanced candidate。"""
        _bootstrap([], opening_cash=100000.0)
        trade = _trade("600519", "buy", 10.0, 100)
        position_reality_service.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_price": 20.0},
            "reason": "修正",
        })
        _create("CASH_DEPOSIT", 1000.0)
        assert _ledger_cash()["value"] == 100000.0 - 2000.0 + 1000.0

    def test_voided_not_executed_still_excluded(self):
        """R2 契约不回退：voided/not_executed trade 仍不计入。"""
        _bootstrap([], opening_cash=100000.0)
        trade = _trade("600519", "buy", 10.0, 100)
        trade_ledger_service.void_trade(trade["trade_id"], "作废")
        trade_ledger_service.create_trade({
            "code": "600519",
            "name": "测试股票",
            "operation": "buy",
            "execution_status": "not_executed",
            "planned_price": 10.0,
            "planned_quantity": 100,
            "unexecuted_reason": "未成交",
        })
        assert _ledger_cash()["value"] == 100000.0

    def test_opening_cash_unknown_no_backsolve(self):
        """opening_cash UNKNOWN → ledger candidate UNKNOWN，不反推。"""
        _bootstrap([], opening_cash=None)
        _create("CASH_DEPOSIT", 1000.0)
        cand = _ledger_cash()
        assert cand["value"] is None
        assert cand["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# E. Cash Reconciliation（enhanced candidate）
# ---------------------------------------------------------------------------


class TestCashReconciliationEnhanced:
    def test_match(self, tmp_path, monkeypatch):
        import account_profile
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        account_profile.save_account_profile(200000.0, 101000.0)
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DEPOSIT", 1000.0)  # ledger = 101000
        derived = position_reality_service.derive_positions()
        recon = ar_svc._cash_reconciliation(ar_svc._current_cash_fact(), ar_svc._ledger_cash_candidate(derived))
        assert recon["status"] == "MATCH"

    def test_mismatch(self, tmp_path, monkeypatch):
        import account_profile
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        account_profile.save_account_profile(200000.0, 99999.0)
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DEPOSIT", 1000.0)  # ledger = 101000 ≠ 99999
        derived = position_reality_service.derive_positions()
        recon = ar_svc._cash_reconciliation(ar_svc._current_cash_fact(), ar_svc._ledger_cash_candidate(derived))
        assert recon["status"] == "MISMATCH"

    def test_either_unavailable_unknown(self):
        _bootstrap([], opening_cash=None)
        derived = position_reality_service.derive_positions()
        recon = ar_svc._cash_reconciliation(
            {"value": None, "status": "UNKNOWN"}, ar_svc._ledger_cash_candidate(derived)
        )
        assert recon["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# F. NAV Isolation（ledger cash 不改变 NAV source）
# ---------------------------------------------------------------------------


class TestNavIsolation:
    def test_nav_still_uses_profile_cash(self, tmp_path, monkeypatch):
        import account_profile
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        account_profile.save_account_profile(200000.0, 50000.0)
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DEPOSIT", 90000.0)  # ledger = 190000 ≠ profile 50000
        reality = ar_svc.get_account_reality()
        assert reality["settled_nav"] == 50000.0  # 无持仓，NAV = profile cash
        assert reality["nav_cash_source"] == "ACCOUNT_PROFILE"
        assert reality["cash"]["reconciliation"] == "MISMATCH"


# ---------------------------------------------------------------------------
# G. Position Isolation（Hard Gate：cash events 不改变 position reality）
# ---------------------------------------------------------------------------


class TestPositionIsolation:
    def test_cash_events_do_not_change_derive_positions(self):
        _bootstrap([{"code": "600519", "shares": 100, "cost_basis": 10.0, "name": "测试股票"}], opening_cash=100000.0)
        _trade("600519", "buy", 10.0, 100)
        before = position_reality_service.derive_positions()
        _create("CASH_DEPOSIT", 1000.0)
        _create("CASH_WITHDRAWAL", 200.0)
        _create("CASH_DIVIDEND", 100.0)
        _create("CASH_FEE", 20.0)
        _create("CASH_TAX", 10.0)
        after = position_reality_service.derive_positions()
        assert before == after  # 完全一致（shares/cost/status/origin/bootstrap）

    def test_cash_events_do_not_change_position_reconciliation(self, tmp_path, monkeypatch):
        import portfolio
        pf = tmp_path / "portfolio.json"
        monkeypatch.setattr(portfolio, "PF_FILE", str(pf))
        pf.write_text(
            '{"holdings": [{"code": "600519", "shares": 100, "cost": 10.0}], "last_refresh": null}',
            encoding="utf-8",
        )
        _bootstrap([{"code": "600519", "shares": 100, "cost_basis": 10.0, "name": "测试股票"}], opening_cash=100000.0)
        before = position_reality_service.reconcile_positions()
        before.pop("as_of", None)
        _create("CASH_DEPOSIT", 1000.0)
        after = position_reality_service.reconcile_positions()
        after.pop("as_of", None)
        assert before == after  # 除瞬时 as_of 外完全一致

    def test_no_fake_positions(self):
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DEPOSIT", 1000.0)
        derived = position_reality_service.derive_positions()
        assert derived["positions"] == []  # 现金事件不生成持仓


# ---------------------------------------------------------------------------
# H. Unsupported Boundary
# ---------------------------------------------------------------------------


class TestUnsupportedBoundary:
    def test_corporate_action_not_silently_cash(self):
        _bootstrap([], opening_cash=100000.0)
        with pytest.raises(svc.CashEventValidationError):
            svc.create_cash_event({"event_type": "CORPORATE_ACTION", "amount": 100.0})
        cand = _ledger_cash()
        assert cand["value"] == 100000.0  # 未被计入

    def test_unknown_event_type_fail_closed(self):
        _bootstrap([])
        with pytest.raises(svc.CashEventValidationError):
            svc.create_cash_event({"event_type": "BOGUS", "amount": 100.0})

    def test_coverage_not_full_ledger(self):
        _bootstrap([], opening_cash=100000.0)
        cand = _ledger_cash()
        assert cand["coverage"] != "FULL_ACCOUNT_LEDGER"
        assert cand["coverage"] == "TRADES_PLUS_MANUAL_CASH_EVENTS"
        reality = ar_svc.get_account_reality()
        assert reality["cash_event_support"]["unsupported"] == ["CORPORATE_ACTION"]


# ---------------------------------------------------------------------------
# I. Legacy Schema Migration（旧 account_events 表 → 新 schema）
# ---------------------------------------------------------------------------


class TestLegacySchemaMigration:
    def test_old_schema_migrates_and_preserves_data(self, tmp_path, monkeypatch):
        """旧 3 值 CHECK 无 amount 表 → 惰性迁移：数据保留，可写 CASH_* 事件。"""
        db = tmp_path / "trade_ledger.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(db))
        # 手工建旧 schema + 一条 ACCOUNT_OPENING
        conn = sqlite3.connect(str(db))
        conn.execute(
            """
            CREATE TABLE account_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL CHECK (event_type IN ('ACCOUNT_OPENING','LEGACY_POSITION_OPENING','CORRECTION')),
                code TEXT, name TEXT, shares INTEGER, cost_basis REAL,
                opening_cash REAL, ledger_start_at TEXT, origin TEXT,
                acquired_before_vibe INTEGER, historical_trades TEXT,
                provenance TEXT NOT NULL, target_event_id TEXT, target_event_type TEXT,
                before_payload TEXT, after_payload TEXT, reason TEXT, note TEXT,
                created_at TEXT NOT NULL, voided_at TEXT, void_reason TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO account_events (event_id, event_type, provenance, created_at) VALUES (?, ?, ?, ?)",
            ("aev_old1", "ACCOUNT_OPENING", "MANUAL", "2026-08-01T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()

        # 首次写入触发迁移：写一条 CASH_DEPOSIT
        event = _create("CASH_DEPOSIT", 1000.0)
        assert event["event_type"] == "CASH_DEPOSIT"
        # 旧数据保留
        old = account_event_store.get_event(db, "aev_old1")
        assert old is not None
        assert old["event_type"] == "ACCOUNT_OPENING"
        # 新表结构：amount 列存在、event_type 无 CHECK
        conn2 = sqlite3.connect(str(db))
        schema = conn2.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='account_events'"
        ).fetchone()[0]
        conn2.close()
        assert "amount" in schema
        assert "CHECK (event_type IN" not in schema
