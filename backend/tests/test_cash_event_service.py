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


# ---------------------------------------------------------------------------
# P0-S1B-B P1 regression：旧 schema 首写为 create_correction（caller-owned 事务）
# ---------------------------------------------------------------------------


class TestMigrationWithCorrectionFirstWrite:
    def test_legacy_db_first_write_correction_succeeds(self, tmp_path, monkeypatch):
        """旧 3 值 CHECK 无 amount 表 + 已有 ACCOUNT_OPENING/trade，升级后首写为
        create_correction（caller-owned BEGIN IMMEDIATE 事务）→ 成功（不 500），
        旧数据保留、新 schema 生效。"""
        db = tmp_path / "trade_ledger.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(db))
        # 旧 schema + ACCOUNT_OPENING + trade_records + 一笔 buy trade
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
            "INSERT INTO account_events (event_id, event_type, opening_cash, ledger_start_at, provenance, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("aev_open1", "ACCOUNT_OPENING", 100000.0, "2026-08-01T00:00:00+00:00", "MANUAL", "2026-08-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            CREATE TABLE trade_records (
                trade_id TEXT PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL,
                operation TEXT NOT NULL, execution_status TEXT NOT NULL,
                planned_price REAL, planned_quantity INTEGER, actual_price REAL,
                actual_quantity INTEGER NOT NULL DEFAULT 0, executed_at TEXT,
                fee REAL NOT NULL DEFAULT 0, other_cost REAL NOT NULL DEFAULT 0,
                unexecuted_reason TEXT, note TEXT, advice_trade_date TEXT,
                advice_generated_at TEXT, advice_snapshot TEXT, thesis_id TEXT,
                thesis_revision INTEGER, created_at TEXT NOT NULL, voided_at TEXT, void_reason TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO trade_records (trade_id, code, name, operation, execution_status,"
            " actual_price, actual_quantity, executed_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("tr_old1", "600519", "测试股票", "buy", "full", 10.0, 100,
             "2026-08-03T01:30:00+00:00", "2026-08-03T01:30:00+00:00"),
        )
        conn.commit()
        conn.close()

        # 升级后首写 = create_correction（此前会触发事务内嵌套 BEGIN → 500）
        corr = position_reality_service.create_correction({
            "target_event_id": "tr_old1",
            "target_event_type": "trade",
            "after_payload": {"actual_price": 20.0},
            "reason": "修正",
        })
        assert corr["status"] == "CORRECTION_RECORDED"
        # 旧数据保留
        old = account_event_store.get_event(db, "aev_open1")
        assert old is not None
        assert old["event_type"] == "ACCOUNT_OPENING"
        # 新 schema 生效（amount 列存在）
        conn2 = sqlite3.connect(str(db))
        schema = conn2.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='account_events'"
        ).fetchone()[0]
        conn2.close()
        assert "amount" in schema
        # 迁移后 cash event 可写
        ev = svc.create_cash_event({"event_type": "CASH_DEPOSIT", "amount": 1000.0})
        assert ev["amount"] == 1000.0


# ---------------------------------------------------------------------------
# P0-S1B-B R2：Persisted Cash Event Fact Integrity（fail-closed 事实链）
# ---------------------------------------------------------------------------


def _raw_insert(event_type: str, amount, provenance: str = "MANUAL", event_id: str | None = None):
    """直接向 account_events 表插入原始行（绕过 service 校验，模拟持久化损坏）。"""
    account_event_store.insert_event(svc.resolve_db_path(), {
        "event_id": event_id or f"raw_{abs(hash((event_type, str(amount))))}",
        "event_type": event_type,
        "code": None, "name": None, "shares": None, "cost_basis": None,
        "opening_cash": None, "ledger_start_at": None, "origin": None,
        "acquired_before_vibe": None, "historical_trades": None,
        "provenance": provenance, "target_event_id": None, "target_event_type": None,
        "before_payload": None, "after_payload": None, "reason": None, "note": None,
        "amount": amount, "created_at": "2026-08-09T00:00:00+00:00",
    })


class TestPersistedFactIntegrity:
    """持久化事实链 fail closed：RAW → NORMALIZE → PERSIST → REOPEN → VALIDATE → DELTA。"""

    def test_amount_0001_create_fails_no_00_persisted(self):
        """0.001 归一化后为 0.00 → 拒绝，不得落盘 0.00 事件。"""
        _bootstrap([], opening_cash=100000.0)
        with pytest.raises(svc.CashEventValidationError):
            _create("CASH_DEPOSIT", 0.001)
        assert svc.list_cash_events() == []  # 无 0.00 事件

    def test_persisted_null_amount_fail_closed(self):
        """raw CASH_DEPOSIT amount=NULL → list/get 必须 fail closed（不得当 0）。"""
        _bootstrap([], opening_cash=100000.0)
        _raw_insert("CASH_DEPOSIT", None)
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            svc.list_cash_events()
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            ar_svc.get_account_reality()

    def test_persisted_negative_amount_fail_closed(self):
        """raw CASH_WITHDRAWAL amount=-100 → fail closed，不得被算成 +100。"""
        _bootstrap([], opening_cash=100000.0)
        _raw_insert("CASH_WITHDRAWAL", -100.0)
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            svc.list_cash_events()
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            ar_svc.get_account_reality()

    def test_persisted_zero_amount_fail_closed(self):
        """raw CASH_DEPOSIT amount=0 → fail closed。"""
        _bootstrap([], opening_cash=100000.0)
        _raw_insert("CASH_DEPOSIT", 0)
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            svc.list_cash_events()

    def test_persisted_bogus_event_type_fail_closed(self):
        """raw event_type=BOGUS → 账户事件读取 / 账户现实 / derive 全部 fail closed，不得静默忽略。"""
        _bootstrap([], opening_cash=100000.0)
        _raw_insert("BOGUS", 100.0)
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            svc.list_cash_events()
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            ar_svc.get_account_reality()
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            position_reality_service.derive_positions()

    def test_persisted_valid_cash_event_reopen_ok(self):
        """persisted valid CASH_* → reopen 后仍正常（list/get 通过）。"""
        _bootstrap([], opening_cash=100000.0)
        event = _create("CASH_DEPOSIT", 1000.0)
        # reopen（重新读库）
        assert svc.get_cash_event(event["event_id"])["amount"] == 1000.0
        assert svc.list_cash_events()[0]["event_type"] == "CASH_DEPOSIT"
        assert ar_svc.get_account_reality()["cash"]["ledger_candidate"]["value"] == 101000.0

    def test_legacy_non_cash_events_still_readable(self):
        """旧 ACCOUNT_OPENING / LEGACY / CORRECTION 迁移与读取全部正常。"""
        _bootstrap([{"code": "600519", "shares": 100, "cost_basis": 10.0, "name": "测试股票"}], opening_cash=100000.0)
        trade = _trade("600519", "buy", 10.0, 100)
        position_reality_service.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_price": 20.0},
        })
        derived = position_reality_service.derive_positions()
        assert derived["derivation_status"] == "OK"
        # 旧事件读取正常
        events = account_event_store.list_events(svc.resolve_db_path())
        types = {e["event_type"] for e in events}
        assert {"ACCOUNT_OPENING", "LEGACY_POSITION_OPENING", "CORRECTION"} <= types
        # 账户现实正常（含旧事件 + cash event）
        reality = ar_svc.get_account_reality()
        assert reality["bootstrap_status"] == "BOOTSTRAPPED"

    def test_cash_reconciliation_correct(self, tmp_path, monkeypatch):
        """cash reconciliation 继续 MATCH/MISMATCH/UNKNOWN 正确。"""
        import account_profile
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        account_profile.save_account_profile(200000.0, 101000.0)
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DEPOSIT", 1000.0)
        derived = position_reality_service.derive_positions()
        recon = ar_svc._cash_reconciliation(ar_svc._current_cash_fact(), ar_svc._ledger_cash_candidate(derived))
        assert recon["status"] == "MATCH"

    def test_nav_still_account_profile(self, tmp_path, monkeypatch):
        """NAV 仍使用 ACCOUNT_PROFILE（ledger 有 cash event 也不改）。"""
        import account_profile
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        account_profile.save_account_profile(200000.0, 50000.0)
        _bootstrap([], opening_cash=100000.0)
        _create("CASH_DEPOSIT", 90000.0)  # ledger = 190000
        reality = ar_svc.get_account_reality()
        assert reality["settled_nav"] == 50000.0
        assert reality["nav_cash_source"] == "ACCOUNT_PROFILE"

    def test_position_reality_hard_gate_unchanged(self):
        """Position Reality Hard Gate：cash events 不改变 derive_positions。"""
        _bootstrap([{"code": "600519", "shares": 100, "cost_basis": 10.0, "name": "测试股票"}], opening_cash=100000.0)
        _trade("600519", "buy", 10.0, 100)
        before = position_reality_service.derive_positions()
        _create("CASH_DEPOSIT", 1000.0)
        _create("CASH_WITHDRAWAL", 200.0)
        after = position_reality_service.derive_positions()
        assert before == after


# ---------------------------------------------------------------------------
# P0-S1B-C：Manual Cash Event Correction & Effective Cash Facts
# ---------------------------------------------------------------------------


def _correct_cash(event_id: str, amount: float, reason: str = "修正") -> dict:
    return svc.correct_cash_event(event_id, {"amount": amount, "reason": reason})


class TestCashCorrectionContract:
    """Cash Event Correction（复用现有 correction engine，不改 raw，方向由 event_type 决定）。"""

    def test_deposit_correction_success(self):
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        result = _correct_cash(ev["event_id"], 150.0)
        assert result["status"] == "CORRECTION_RECORDED"
        # effective: 100 → 150
        effective = svc.effective_cash_events()
        assert effective[0]["amount"] == 150.0
        assert _ledger_cash()["value"] == 100000.0 + 150.0

    def test_withdrawal_correction_success(self):
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_WITHDRAWAL", 100.0)
        _correct_cash(ev["event_id"], 150.0)
        assert _ledger_cash()["value"] == 100000.0 - 150.0

    def test_dividend_correction_success(self):
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DIVIDEND", 100.0)
        _correct_cash(ev["event_id"], 200.0)
        assert _ledger_cash()["value"] == 100000.0 + 200.0

    def test_fee_correction_success(self):
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_FEE", 100.0)
        _correct_cash(ev["event_id"], 20.0)
        assert _ledger_cash()["value"] == 100000.0 - 20.0

    def test_tax_correction_success(self):
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_TAX", 100.0)
        _correct_cash(ev["event_id"], 30.0)
        assert _ledger_cash()["value"] == 100000.0 - 30.0

    def test_original_fact_immutable(self):
        """raw cash event amount 永不被修改；effective 由 CORRECTION 表达。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 120.0)
        _correct_cash(ev["event_id"], 80.0)
        raw = svc.get_cash_event(ev["event_id"])
        assert raw["amount"] == 100.0  # raw 不变
        effective = svc.effective_cash_events()
        assert effective[0]["amount"] == 80.0  # effective = 80
        assert _ledger_cash()["value"] == 100000.0 + 80.0

    def test_chained_before_payload(self):
        """100 → 120 → 80：第二条 correction before_payload.amount 必须 = 120（非 raw 100）。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 120.0)
        r2 = _correct_cash(ev["event_id"], 80.0)
        import json as _json
        before2 = _json.loads(r2["event"]["before_payload"])
        assert before2["amount"] == 120.0

    def test_correction_durable_reopen(self):
        """CORRECTION durable：restart/reopen 后仍生效。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 120.0)
        # reopen：重新读库
        assert _ledger_cash()["value"] == 100000.0 + 120.0
        effective = svc.effective_cash_events()
        assert effective[0]["amount"] == 120.0

    def test_event_type_not_modifiable(self):
        """correction 不允许改 event_type / 其他字段。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        with pytest.raises(svc.CashEventValidationError):
            svc.correct_cash_event(ev["event_id"], {"amount": 120.0, "event_type": "CASH_WITHDRAWAL"})

    def test_target_non_cash_rejected(self):
        """target 非 CASH_* account event → 拒绝（404）。"""
        result = _bootstrap([{"code": "600519", "shares": 100, "cost_basis": 10.0, "name": "测试股票"}], opening_cash=100000.0)
        legacy_id = result["positions"][0]["event_id"]
        with pytest.raises(svc.CashEventNotFoundError):
            svc.correct_cash_event(legacy_id, {"amount": 120.0})

    def test_target_correction_event_rejected(self):
        """target CORRECTION event → 拒绝（404）。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        corr = _correct_cash(ev["event_id"], 120.0)
        corr_id = corr["event"]["event_id"]
        with pytest.raises(svc.CashEventNotFoundError):
            svc.correct_cash_event(corr_id, {"amount": 130.0})

    def test_unknown_event_404(self):
        _bootstrap([])
        with pytest.raises(svc.CashEventNotFoundError):
            svc.correct_cash_event("nonexistent", {"amount": 100.0})

    def test_amount_zero_rejected(self):
        _bootstrap([])
        ev = _create("CASH_DEPOSIT", 100.0)
        with pytest.raises(svc.CashEventValidationError):
            _correct_cash(ev["event_id"], 0.0)

    def test_amount_negative_rejected(self):
        _bootstrap([])
        ev = _create("CASH_DEPOSIT", 100.0)
        with pytest.raises(svc.CashEventValidationError):
            _correct_cash(ev["event_id"], -10.0)

    def test_amount_nan_inf_rejected(self):
        _bootstrap([])
        ev = _create("CASH_DEPOSIT", 100.0)
        with pytest.raises(svc.CashEventValidationError):
            _correct_cash(ev["event_id"], float("nan"))
        with pytest.raises(svc.CashEventValidationError):
            _correct_cash(ev["event_id"], float("inf"))

    def test_amount_0001_rejected(self):
        """0.001 → 归一化 0.00 → 拒绝（与 create 同一 contract）。"""
        _bootstrap([])
        ev = _create("CASH_DEPOSIT", 100.0)
        with pytest.raises(svc.CashEventValidationError):
            _correct_cash(ev["event_id"], 0.001)
        # 不得落盘 0.00 correction
        effective = svc.effective_cash_events()
        assert effective[0]["amount"] == 100.0

    def test_2dp_normalization_same_as_create(self):
        """12.345 → 12.35（与 create 同一 rounding）。"""
        _bootstrap([])
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 12.345)
        effective = svc.effective_cash_events()
        assert effective[0]["amount"] == 12.35

    def test_extra_field_rejected(self):
        _bootstrap([])
        ev = _create("CASH_DEPOSIT", 100.0)
        with pytest.raises(svc.CashEventValidationError):
            svc.correct_cash_event(ev["event_id"], {"amount": 120.0, "name": "x"})

    def test_deposit_corrected_delta_positive(self):
        """DEPOSIT correction → +方向。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 150.0)
        assert _ledger_cash()["value"] == 100000.0 + 150.0

    def test_withdrawal_corrected_delta_negative(self):
        """WITHDRAWAL correction → -方向。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_WITHDRAWAL", 100.0)
        _correct_cash(ev["event_id"], 150.0)
        assert _ledger_cash()["value"] == 100000.0 - 150.0

    def test_ledger_candidate_uses_corrected_not_raw(self):
        """ledger_cash_candidate 用 corrected amount，不用 raw。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 500.0)
        assert _ledger_cash()["value"] == 100000.0 + 500.0  # 非 +100

    def test_reconciliation_corrected_match(self, tmp_path, monkeypatch):
        """profile cash == corrected ledger candidate → MATCH。"""
        import account_profile
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        account_profile.save_account_profile(200000.0, 101500.0)
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 1500.0)  # ledger = 101500
        derived = position_reality_service.derive_positions()
        recon = ar_svc._cash_reconciliation(ar_svc._current_cash_fact(), ar_svc._ledger_cash_candidate(derived))
        assert recon["status"] == "MATCH"

    def test_reconciliation_corrected_mismatch(self, tmp_path, monkeypatch):
        """profile cash != corrected ledger candidate → MISMATCH。"""
        import account_profile
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        account_profile.save_account_profile(200000.0, 99999.0)
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 1500.0)  # ledger = 101500
        derived = position_reality_service.derive_positions()
        recon = ar_svc._cash_reconciliation(ar_svc._current_cash_fact(), ar_svc._ledger_cash_candidate(derived))
        assert recon["status"] == "MISMATCH"

    def test_nav_still_account_profile(self, tmp_path, monkeypatch):
        """NAV 仍 ACCOUNT_PROFILE（cash correction 不改 NAV source）。"""
        import account_profile
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        account_profile.save_account_profile(200000.0, 50000.0)
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 90000.0)  # ledger = 190000
        reality = ar_svc.get_account_reality()
        assert reality["settled_nav"] == 50000.0
        assert reality["nav_cash_source"] == "ACCOUNT_PROFILE"

    def test_position_reality_hard_gate(self):
        """derive_positions 在 cash correction 前后完全一致。"""
        _bootstrap([{"code": "600519", "shares": 100, "cost_basis": 10.0, "name": "测试股票"}], opening_cash=100000.0)
        _trade("600519", "buy", 10.0, 100)
        before = position_reality_service.derive_positions()
        ev = _create("CASH_DEPOSIT", 100.0)
        _correct_cash(ev["event_id"], 200.0)
        after = position_reality_service.derive_positions()
        assert before == after

    def test_persisted_correction_bad_json_fail_closed(self):
        """持久化针对 CASH_* 的 correction after_payload 损坏 → fail closed。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        account_event_store.insert_event(svc.resolve_db_path(), {
            "event_id": "aev_corrupt_corr",
            "event_type": "CORRECTION",
            "code": None, "name": None, "shares": None, "cost_basis": None,
            "opening_cash": None, "ledger_start_at": None, "origin": None,
            "acquired_before_vibe": None, "historical_trades": None,
            "provenance": "MANUAL", "target_event_id": ev["event_id"],
            "target_event_type": "account_event",
            "before_payload": '{"amount": 100}', "after_payload": '{"amount": "bad"}',
            "reason": "损坏", "note": None, "amount": None,
            "created_at": "2026-08-09T01:00:00+00:00",
        })
        with pytest.raises(account_event_store.AccountEventCorruptedError):
            ar_svc.get_account_reality()

    def test_corrupt_correction_no_raw_fallback(self):
        """损坏 correction 不得回退 raw amount（fail closed 而非静默用 raw）。"""
        _bootstrap([], opening_cash=100000.0)
        ev = _create("CASH_DEPOSIT", 100.0)
        account_event_store.insert_event(svc.resolve_db_path(), {
            "event_id": "aev_corrupt_corr2",
            "event_type": "CORRECTION",
            "code": None, "name": None, "shares": None, "cost_basis": None,
            "opening_cash": None, "ledger_start_at": None, "origin": None,
            "acquired_before_vibe": None, "historical_trades": None,
            "provenance": "MANUAL", "target_event_id": ev["event_id"],
            "target_event_type": "account_event",
            "before_payload": '{"amount": 100}', "after_payload": 'not-json',
            "reason": "损坏", "note": None, "amount": None,
            "created_at": "2026-08-09T01:00:00+00:00",
        })
        # 损坏 correction payload → fail closed（AccountEventCorruptedError 或 PositionDerivationError），
        # 不得静默回退 raw amount=100 继续计算。
        with pytest.raises((account_event_store.AccountEventCorruptedError, position_reality_service.PositionDerivationError)):
            _ledger_cash()
