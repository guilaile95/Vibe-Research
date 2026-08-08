"""P0-S1A position reality service tests (offline, deterministic)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import account_event_store
import portfolio
import position_reality_service as svc
import trade_ledger_service


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Give each test its own isolated ledger DB directory."""
    isolated = tmp_path / "ledger_db"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    yield


@pytest.fixture
def pf_file(tmp_path, monkeypatch):
    """Point portfolio.PF_FILE at an isolated file; returns the path."""
    pf = tmp_path / "portfolio.json"
    monkeypatch.setattr(portfolio, "PF_FILE", str(pf))
    return pf


def _write_portfolio(pf_file: Path, holdings: list[dict]) -> None:
    pf_file.write_text(
        json.dumps({"holdings": holdings, "last_refresh": None}, ensure_ascii=False),
        encoding="utf-8",
    )


def _bootstrap(
    positions: list[dict] | None = None,
    ledger_start_at: str = "2026-08-01",
    opening_cash: float | None = 100000.0,
) -> dict:
    return svc.bootstrap_commit({
        "ledger_start_at": ledger_start_at,
        "opening_cash": opening_cash,
        "positions": positions or [],
    })


def _trade(code: str, operation: str, price: float, qty: int, name: str = "测试股票", day: str = "2026-08-03", fee: float = 0.0) -> dict:
    return trade_ledger_service.create_trade({
        "code": code,
        "name": name,
        "operation": operation,
        "execution_status": "full",
        "actual_price": price,
        "actual_quantity": qty,
        "executed_at": f"{day}T09:30:00+08:00",
        "fee": fee,
    })


def _legacy(code: str, shares: int, cost_basis: float | None, name: str = "测试股票") -> dict:
    return {"code": code, "shares": shares, "cost_basis": cost_basis, "name": name}


def _derived(code: str) -> dict:
    for p in svc.derive_positions()["positions"]:
        if p["code"] == code:
            return p
    raise AssertionError(f"code {code} 不在推导结果中")


class TestBootstrap:
    def test_empty_account_opening(self):
        result = _bootstrap([])
        assert result["status"] == "BOOTSTRAPPED"
        assert result["opening"]["event_type"] == "ACCOUNT_OPENING"
        assert result["opening"]["provenance"] == "MANUAL"
        assert result["opening"]["historical_trades"] == "UNKNOWN"
        assert result["positions"] == []
        derived = svc.derive_positions()
        assert derived["positions"] == []
        assert derived["ledger_start"]["ledger_start_at"] == "2026-08-01"
        assert derived["ledger_start"]["pre_vibe_history"] == "UNKNOWN"

    def test_single_legacy_holding(self):
        _bootstrap([_legacy("600519", 100, 1500.0)])
        pos = _derived("600519")
        assert pos["shares"] == 100
        assert pos["cost_basis"] == 150000.0
        assert pos["avg_cost"] == 1500.0
        assert pos["origin"] == "PRE_VIBE"
        assert pos["status"] == "OPEN"
        assert pos["cost_known"] is True

    def test_multiple_legacy_holdings(self):
        _bootstrap([
            _legacy("600519", 100, 1500.0),
            _legacy("000001", 200, 10.0),
        ])
        positions = {p["code"]: p for p in svc.derive_positions()["positions"]}
        assert positions["600519"]["shares"] == 100
        assert positions["000001"]["shares"] == 200
        assert positions["000001"]["cost_basis"] == 2000.0

    def test_legacy_opening_is_not_a_buy(self):
        _bootstrap([_legacy("600519", 100, 1500.0)])
        pos = _derived("600519")
        assert pos["origin"] == "PRE_VIBE"
        # 账本中不应存在任何 buy 记录（LEGACY_POSITION_OPENING != BUY）
        assert trade_ledger_service.list_trades() == []
        events = account_event_store.list_events(svc.resolve_db_path())
        opening_events = [e for e in events if e["event_type"] == "LEGACY_POSITION_OPENING"]
        assert len(opening_events) == 1
        assert opening_events[0]["origin"] == "PRE_VIBE"
        assert opening_events[0]["acquired_before_vibe"] == 1
        assert opening_events[0]["historical_trades"] == "UNKNOWN"

    def test_legacy_unknown_cost_stays_unknown(self):
        _bootstrap([_legacy("600519", 100, None)])
        pos = _derived("600519")
        assert pos["cost_basis"] is None
        assert pos["avg_cost"] is None
        assert pos["cost_known"] is False

    def test_duplicate_code_rejected(self):
        with pytest.raises(svc.PositionValidationError):
            svc.bootstrap_commit({
                "ledger_start_at": "2026-08-01",
                "positions": [
                    _legacy("600519", 100, 1500.0),
                    _legacy("600519", 200, 1500.0),
                ],
            })

    def test_duplicate_bootstrap_rejected(self):
        _bootstrap([])
        with pytest.raises(svc.BootstrapAlreadyExistsError):
            _bootstrap([])

    def test_bootstrap_after_post_vibe_trade_rejected(self):
        _trade("600519", "buy", 100.0, 100)
        with pytest.raises(svc.LedgerNotEmptyError):
            _bootstrap([])

    def test_preview_does_not_write(self):
        result = svc.bootstrap_preview({
            "ledger_start_at": "2026-08-01",
            "positions": [_legacy("600519", 100, 1500.0)],
        })
        assert result["preview"] is True
        assert result["validation"] == "ok"
        assert result["opening"]["event_type"] == "ACCOUNT_OPENING"
        assert len(result["positions"]) == 1
        derived = svc.derive_positions()
        assert derived["ledger_start"] is None
        assert derived["positions"] == []

    def test_preview_invalid_payload_rejected(self):
        with pytest.raises(svc.PositionValidationError):
            svc.bootstrap_preview({"positions": []})  # 缺 ledger_start_at

    def test_invalid_position_rejected(self):
        with pytest.raises(svc.PositionValidationError):
            svc.bootstrap_commit({
                "ledger_start_at": "2026-08-01",
                "positions": [{"code": "600519", "shares": -5, "cost_basis": 1500.0}],
            })
        with pytest.raises(svc.PositionValidationError):
            svc.bootstrap_commit({
                "ledger_start_at": "2026-08-01",
                "positions": [{"code": "123", "shares": 100, "cost_basis": 1500.0}],
            })


class TestDerivationWithTrades:
    def test_opening_plus_buy(self):
        _bootstrap([_legacy("600519", 100, 1500.0)])
        _trade("600519", "buy", 10.0, 100, fee=0.0)
        pos = _derived("600519")
        assert pos["shares"] == 200
        assert pos["cost_basis"] == 150000.0 + 1000.0
        assert pos["origin"] == "MIXED"

    def test_opening_plus_add_weighted_avg(self):
        _bootstrap([_legacy("600519", 100, 10.0)])
        _trade("600519", "add", 20.0, 100)
        pos = _derived("600519")
        assert pos["shares"] == 200
        assert pos["cost_basis"] == 1000.0 + 2000.0
        assert pos["avg_cost"] == 15.0

    def test_opening_plus_reduce(self):
        _bootstrap([_legacy("600519", 100, 10.0)])
        _trade("600519", "reduce", 15.0, 40)
        pos = _derived("600519")
        assert pos["shares"] == 60
        assert pos["cost_basis"] == 600.0
        assert pos["avg_cost"] == 10.0

    def test_opening_plus_sell_full_exit(self):
        _bootstrap([_legacy("600519", 100, 10.0)])
        _trade("600519", "sell", 15.0, 100)
        pos = _derived("600519")
        assert pos["shares"] == 0
        assert pos["status"] == "CLOSED"
        assert pos["cost_basis"] == 0.0

    def test_oversell_fail_closed(self):
        _bootstrap([_legacy("600519", 100, 10.0)])
        _trade("600519", "sell", 15.0, 150)
        with pytest.raises(svc.PositionDerivationError):
            svc.derive_positions()

    def test_post_vibe_trade_without_bootstrap(self):
        _trade("600519", "buy", 10.0, 100)
        pos = _derived("600519")
        assert pos["shares"] == 100
        assert pos["origin"] == "POST_VIBE"
        derived = svc.derive_positions()
        assert derived["ledger_start"] is None


class TestCorrection:
    def test_correction_after_opening(self):
        result = _bootstrap([_legacy("600519", 100, 10.0)])
        event_id = result["positions"][0]["event_id"]
        svc.create_correction({
            "target_event_id": event_id,
            "target_event_type": "account_event",
            "after_payload": {"shares": 120},
            "reason": "期初数量录入有误",
        })
        pos = _derived("600519")
        assert pos["shares"] == 120
        assert pos["cost_basis"] == 1200.0

    def test_correction_after_trade(self):
        _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        svc.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
            "reason": "成交数量录入有误",
        })
        pos = _derived("600519")
        assert pos["shares"] == 150
        assert pos["cost_basis"] == 1500.0

    def test_correction_target_not_found(self):
        with pytest.raises(svc.CorrectionTargetNotFoundError):
            svc.create_correction({
                "target_event_id": "missing",
                "target_event_type": "trade",
                "after_payload": {"actual_quantity": 10},
            })

    def test_correction_unknown_field_rejected(self):
        result = _bootstrap([_legacy("600519", 100, 10.0)])
        event_id = result["positions"][0]["event_id"]
        with pytest.raises(svc.PositionValidationError):
            svc.create_correction({
                "target_event_id": event_id,
                "target_event_type": "account_event",
                "after_payload": {"shares": 120, "name": "改名"},
            })

    def test_correction_voided_target_rejected(self):
        result = _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        trade_ledger_service.void_trade(trade["trade_id"], "作废")
        with pytest.raises(svc.PositionValidationError):
            svc.create_correction({
                "target_event_id": trade["trade_id"],
                "target_event_type": "trade",
                "after_payload": {"actual_quantity": 10},
            })


class TestReconciliation:
    def test_match(self, pf_file):
        _bootstrap([_legacy("600519", 100, 1500.0)])
        _write_portfolio(pf_file, [{"code": "600519", "shares": 100, "cost": 1500.0}])
        result = svc.reconcile_positions()
        item = result["items"][0]
        assert item["status"] == "MATCH"
        assert result["summary"]["match"] == 1

    def test_shares_mismatch(self, pf_file):
        _bootstrap([_legacy("600519", 100, 1500.0)])
        _write_portfolio(pf_file, [{"code": "600519", "shares": 90, "cost": 1500.0}])
        item = svc.reconcile_positions()["items"][0]
        assert item["status"] == "MISMATCH"
        assert item["reason"] == "shares mismatch"

    def test_cost_mismatch(self, pf_file):
        _bootstrap([_legacy("600519", 100, 1500.0)])
        _write_portfolio(pf_file, [{"code": "600519", "shares": 100, "cost": 1600.0}])
        item = svc.reconcile_positions()["items"][0]
        assert item["status"] == "MISMATCH"
        assert item["reason"] == "cost mismatch"

    def test_only_in_ledger(self, pf_file):
        _bootstrap([_legacy("600519", 100, 1500.0)])
        _write_portfolio(pf_file, [])
        item = svc.reconcile_positions()["items"][0]
        assert item["status"] == "MISSING_IN_PORTFOLIO"
        assert item["ledger_shares"] == 100

    def test_only_in_portfolio(self, pf_file):
        _bootstrap([])
        _write_portfolio(pf_file, [{"code": "000001", "shares": 100, "cost": 10.0}])
        item = svc.reconcile_positions()["items"][0]
        assert item["status"] == "MISSING_IN_LEDGER"
        assert item["ledger_shares"] == 0

    def test_reconciliation_never_writes(self, pf_file):
        _bootstrap([_legacy("600519", 100, 1500.0)])
        _write_portfolio(pf_file, [{"code": "600519", "shares": 90, "cost": 1500.0}])
        before = pf_file.read_text(encoding="utf-8")
        svc.reconcile_positions()
        after = pf_file.read_text(encoding="utf-8")
        assert before == after


class TestLegacyDbCompatibility:
    def test_old_schema_trade_records_still_readable(self, tmp_path, monkeypatch):
        """旧库（只有 trade_records，无 account_events）可继续读取与推导。"""
        old_db = tmp_path / "old_trade_ledger.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(old_db))
        conn = sqlite3.connect(str(old_db))
        conn.execute(
            """
            CREATE TABLE trade_records (
                trade_id TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                operation TEXT NOT NULL,
                execution_status TEXT NOT NULL,
                planned_price REAL,
                planned_quantity INTEGER,
                actual_price REAL,
                actual_quantity INTEGER NOT NULL DEFAULT 0,
                executed_at TEXT,
                fee REAL NOT NULL DEFAULT 0,
                other_cost REAL NOT NULL DEFAULT 0,
                unexecuted_reason TEXT,
                note TEXT,
                advice_trade_date TEXT,
                advice_generated_at TEXT,
                advice_snapshot TEXT,
                thesis_id TEXT,
                thesis_revision INTEGER,
                created_at TEXT NOT NULL,
                voided_at TEXT,
                void_reason TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO trade_records (
                trade_id, code, name, operation, execution_status,
                actual_price, actual_quantity, executed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("old1", "600519", "贵州茅台", "buy", "full",
             1500.0, 100, "2026-07-01T09:30:00+08:00", "2026-07-01T01:30:00+00:00"),
        )
        conn.commit()
        conn.close()

        # account_events 表不存在时读取返回空，不抛错
        assert account_event_store.list_events(old_db) == []
        # 旧 trade 记录仍可读取
        trades = trade_ledger_service.list_trades()
        assert len(trades) == 1
        assert trades[0]["code"] == "600519"
        # 推导正常
        derived = svc.derive_positions()
        assert derived["ledger_start"] is None
        assert {p["code"]: p["shares"] for p in derived["positions"]} == {"600519": 100}
        # 旧库已存在 post-Vibe 交易 → bootstrap 必须 fail closed 拒绝
        with pytest.raises(svc.LedgerNotEmptyError):
            svc.bootstrap_commit({
                "ledger_start_at": "2026-08-01",
                "positions": [],
            })
        # 旧库（无 account_events 表）上增量建表可用：干净库 bootstrap 正常
        fresh_db = tmp_path / "fresh_trade_ledger.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(fresh_db))
        result = svc.bootstrap_commit({
            "ledger_start_at": "2026-08-01",
            "positions": [],
        })
        assert result["status"] == "BOOTSTRAPPED"
