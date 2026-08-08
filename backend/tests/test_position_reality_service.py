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
import trade_ledger_store


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


def _trade(code: str, operation: str, price: float, qty: int, name: str = "测试股票", day: str = "2026-08-03", fee: float = 0.0, executed_at: str | None = None) -> dict:
    return trade_ledger_service.create_trade({
        "code": code,
        "name": name,
        "operation": operation,
        "execution_status": "full",
        "actual_price": price,
        "actual_quantity": qty,
        "executed_at": executed_at if executed_at is not None else f"{day}T09:30:00+08:00",
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
        assert derived["bootstrap_status"] == "BOOTSTRAPPED"
        assert derived["canonical"] is True
        assert derived["ledger_start"]["ledger_start_at"] == "2026-07-31T16:00:00.000000+00:00"
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
        assert derived["bootstrap_status"] == "NOT_BOOTSTRAPPED"
        assert derived["canonical"] is False


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
        # 推导正常，且明确标注 canonical 边界未建立（旧库兼容读取 ≠ 正式 bootstrapped chain）
        derived = svc.derive_positions()
        assert derived["ledger_start"] is None
        assert derived["bootstrap_status"] == "NOT_BOOTSTRAPPED"
        assert derived["canonical"] is False
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
        fresh_derived = svc.derive_positions()
        assert fresh_derived["bootstrap_status"] == "BOOTSTRAPPED"
        assert fresh_derived["canonical"] is True


# ---------------------------------------------------------------------------
# Review round 2: 空仓买入成本 UNKNOWN 修复
# ---------------------------------------------------------------------------


class TestFreshBuyCostKnown:
    """BUY/ADD 前 shares==0 时必须建立已知成本（修复成本永久 UNKNOWN）。"""

    def test_empty_bootstrap_then_buy_cost_known(self):
        _bootstrap([])
        _trade("600519", "buy", 10.0, 100)
        pos = _derived("600519")
        assert pos["cost_known"] is True
        assert pos["cost_basis"] == 1000.0
        assert pos["avg_cost"] == 10.0

    def test_trade_only_compat_then_buy_cost_known(self):
        # 无 bootstrap（trade-only 旧库兼容模式）首次 BUY 也要建立成本
        _trade("600519", "buy", 10.0, 100)
        pos = _derived("600519")
        assert pos["cost_known"] is True
        assert pos["cost_basis"] == 1000.0
        assert pos["avg_cost"] == 10.0

    def test_legacy_unknown_then_partial_add_stays_unknown(self):
        _bootstrap([_legacy("600519", 100, None)])
        _trade("600519", "add", 20.0, 50)
        pos = _derived("600519")
        assert pos["cost_known"] is False
        assert pos["cost_basis"] is None
        assert pos["avg_cost"] is None
        assert pos["shares"] == 150

    def test_legacy_unknown_full_sell_then_new_buy_cost_known(self):
        _bootstrap([_legacy("600519", 100, None)])
        _trade("600519", "sell", 15.0, 100, executed_at="2026-08-03T09:30:00+08:00")
        _trade("600519", "buy", 20.0, 50, executed_at="2026-08-04T09:30:00+08:00")
        pos = _derived("600519")
        assert pos["shares"] == 50
        assert pos["cost_known"] is True
        assert pos["cost_basis"] == 1000.0
        assert pos["avg_cost"] == 20.0


# ---------------------------------------------------------------------------
# Review round 2: Ledger Start 时间边界
# ---------------------------------------------------------------------------


class TestLedgerStartBoundary:
    """ledger_start_at 是可解析的时间边界；边界前交易 fail closed。"""

    def test_trade_after_ledger_start_allowed(self):
        _bootstrap([_legacy("600519", 100, 10.0)])
        _trade("600519", "buy", 10.0, 100, executed_at="2026-08-03T09:30:00+08:00")
        pos = _derived("600519")
        assert pos["shares"] == 200

    def test_trade_at_exact_boundary_allowed(self):
        # 边界定义：YYYY-MM-DD 按当日 00:00+08:00 = 前一日 16:00 UTC；00:00 整点交易允许
        _bootstrap([_legacy("600519", 100, 10.0)], ledger_start_at="2026-08-03")
        _trade("600519", "buy", 10.0, 100, executed_at="2026-08-03T00:00:00+08:00")
        pos = _derived("600519")
        assert pos["shares"] == 200

    def test_trade_before_ledger_start_fail_closed(self):
        _bootstrap([_legacy("600519", 100, 10.0)], ledger_start_at="2026-08-05")
        _trade("600519", "buy", 10.0, 100, executed_at="2026-08-03T09:30:00+08:00")
        with pytest.raises(svc.PositionDerivationError):
            svc.derive_positions()

    def test_invalid_ledger_start_rejected(self):
        with pytest.raises(svc.PositionValidationError):
            _bootstrap([], ledger_start_at="not-a-date")
        with pytest.raises(svc.PositionValidationError):
            _bootstrap([], ledger_start_at="2026-13-40")
        with pytest.raises(svc.PositionValidationError):
            _bootstrap([], ledger_start_at="2026-08-03T10:00:00")  # 无时区
        with pytest.raises(svc.PositionValidationError):
            _bootstrap([], ledger_start_at="")

    def test_iso_ledger_start_accepted_and_normalized(self):
        _bootstrap([], ledger_start_at="2026-08-03T10:00:00+08:00")
        derived = svc.derive_positions()
        assert derived["ledger_start"]["ledger_start_at"] == "2026-08-03T02:00:00.000000+00:00"

    def test_not_bootstrapped_status_explicit(self):
        # 旧库有 trade 无 ACCOUNT_OPENING → 明确 NOT_BOOTSTRAPPED / canonical=false
        _trade("600519", "buy", 10.0, 100)
        derived = svc.derive_positions()
        assert derived["bootstrap_status"] == "NOT_BOOTSTRAPPED"
        assert derived["canonical"] is False
        assert derived["ledger_start"] is None


# ---------------------------------------------------------------------------
# Review round 2: Correction target 契约收紧
# ---------------------------------------------------------------------------


class TestCorrectionTargetContract:
    """Correction 只能指向 derivation 真正支持的 target 状态。"""

    def test_correction_account_opening_unsupported_field_rejected(self):
        result = _bootstrap([])
        opening_id = result["opening"]["event_id"]
        with pytest.raises(svc.PositionValidationError):
            svc.create_correction({
                "target_event_id": opening_id,
                "target_event_type": "account_event",
                "after_payload": {"ledger_start_at": "2026-08-02"},  # 事实边界不可变
            })
        with pytest.raises(svc.PositionValidationError):
            svc.create_correction({
                "target_event_id": opening_id,
                "target_event_type": "account_event",
                "after_payload": {"shares": 100},  # ACCOUNT_OPENING 无 shares
            })

    def test_correction_account_opening_opening_cash_allowed(self):
        result = _bootstrap([])
        opening_id = result["opening"]["event_id"]
        svc.create_correction({
            "target_event_id": opening_id,
            "target_event_type": "account_event",
            "after_payload": {"opening_cash": 50000.0},
            "reason": "期初现金修正",
        })
        derived = svc.derive_positions()
        assert derived["ledger_start"]["opening_cash"] == 50000.0

    def test_correction_correction_event_rejected(self):
        result = _bootstrap([_legacy("600519", 100, 10.0)])
        opening_id = result["positions"][0]["event_id"]
        corr = svc.create_correction({
            "target_event_id": opening_id,
            "target_event_type": "account_event",
            "after_payload": {"shares": 120},
            "reason": "第一次修正",
        })
        with pytest.raises(svc.PositionValidationError):
            svc.create_correction({
                "target_event_id": corr["event"]["event_id"],
                "target_event_type": "account_event",
                "after_payload": {"shares": 130},
            })

    def test_unsupported_trade_target_rejected(self):
        # not_executed 交易不参与推导，不接受修正
        _bootstrap([])
        not_executed = trade_ledger_service.create_trade({
            "code": "600519",
            "name": "测试股票",
            "operation": "buy",
            "execution_status": "not_executed",
            "planned_price": 10.0,
            "planned_quantity": 100,
            "unexecuted_reason": "未成交",
        })
        with pytest.raises(svc.PositionValidationError):
            svc.create_correction({
                "target_event_id": not_executed["trade_id"],
                "target_event_type": "trade",
                "after_payload": {"actual_quantity": 10},
            })

    def test_legacy_opening_correction_pass(self):
        result = _bootstrap([_legacy("600519", 100, 10.0)])
        event_id = result["positions"][0]["event_id"]
        svc.create_correction({
            "target_event_id": event_id,
            "target_event_type": "account_event",
            "after_payload": {"shares": 120, "cost_basis": 12.0},
            "reason": "期初修正",
        })
        pos = _derived("600519")
        assert pos["shares"] == 120
        assert pos["cost_basis"] == 1440.0

    def test_all_accepted_corrections_derive_ok(self):
        # 任意成功创建的 correction 后，derivation 不得因 target missing 失败
        result = _bootstrap([_legacy("600519", 100, 10.0)])
        opening_id = result["opening"]["event_id"]
        position_id = result["positions"][0]["event_id"]
        trade = _trade("600519", "buy", 10.0, 100)
        svc.create_correction({
            "target_event_id": position_id,
            "target_event_type": "account_event",
            "after_payload": {"shares": 120},
        })
        svc.create_correction({
            "target_event_id": opening_id,
            "target_event_type": "account_event",
            "after_payload": {"opening_cash": 90000.0},
        })
        svc.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
        })
        derived = svc.derive_positions()
        assert derived["derivation_status"] == "OK"
        pos = next(p for p in derived["positions"] if p["code"] == "600519")
        assert pos["shares"] == 170


# ---------------------------------------------------------------------------
# Review round 2: 连续 Correction 链式 before_payload
# ---------------------------------------------------------------------------


class TestChainedCorrections:
    """第二次及后续 correction 的 before 必须反映应用先前 correction 后的有效值。"""

    def test_chained_before_payload(self):
        result = _bootstrap([_legacy("600519", 100, 10.0)])
        event_id = result["positions"][0]["event_id"]

        corr1 = svc.create_correction({
            "target_event_id": event_id,
            "target_event_type": "account_event",
            "after_payload": {"shares": 120},
            "reason": "修正为 120",
        })
        assert json.loads(corr1["event"]["before_payload"])["shares"] == 100
        assert json.loads(corr1["event"]["after_payload"])["shares"] == 120

        corr2 = svc.create_correction({
            "target_event_id": event_id,
            "target_event_type": "account_event",
            "after_payload": {"shares": 130},
            "reason": "修正为 130",
        })
        # before 必须是应用第一条修正后的有效值 120，不是原始 100
        assert json.loads(corr2["event"]["before_payload"])["shares"] == 120
        assert json.loads(corr2["event"]["after_payload"])["shares"] == 130

        pos = _derived("600519")
        assert pos["shares"] == 130
        assert pos["cost_basis"] == 1300.0

    def test_chained_cost_basis(self):
        result = _bootstrap([_legacy("600519", 100, 10.0)])
        event_id = result["positions"][0]["event_id"]
        svc.create_correction({
            "target_event_id": event_id,
            "target_event_type": "account_event",
            "after_payload": {"cost_basis": 12.0},
            "reason": "成本修正",
        })
        corr2 = svc.create_correction({
            "target_event_id": event_id,
            "target_event_type": "account_event",
            "after_payload": {"cost_basis": 15.0},
            "reason": "成本再修正",
        })
        # 第二条 before 应反映第一条修正后的 cost_basis=12
        assert json.loads(corr2["event"]["before_payload"])["cost_basis"] == 12.0
        pos = _derived("600519")
        assert pos["cost_basis"] == 1500.0


# ---------------------------------------------------------------------------
# Review round 3: P1-1 void 后 correction 孤儿 + P2 加固回归
# ---------------------------------------------------------------------------


class TestVoidCascade:
    """作废交易必须级联作废其 CORRECTION，防止孤儿修正永久锁死账本（P1-1）。"""

    def test_void_trade_cascades_corrections(self):
        """active trade：同一事务内级联 void corrections + void trade（R5-P1-1）。"""
        _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        svc.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
            "reason": "成交数量修正",
        })
        result = svc.void_trade_with_cascade(trade["trade_id"], "录入错误")
        assert result["status"] == "VOIDED"
        assert result["cascade_voided"] == 1
        assert result["voided_trade"]["voided_at"] is not None
        # 交易与 correction 均已作废
        assert trade_ledger_service.get_trade(trade["trade_id"])["voided_at"] is not None
        events = account_event_store.list_events(
            svc.resolve_db_path(), include_voided=True
        )
        corr = [e for e in events if e["event_type"] == "CORRECTION"]
        assert len(corr) == 1
        assert corr[0]["voided_at"] is not None
        # derivation 不再因孤儿修正失败
        derived = svc.derive_positions()
        assert derived["derivation_status"] == "OK"
        assert {p["code"]: p["shares"] for p in derived["positions"]} == {"600519": 100}

    def test_void_cascade_idempotent(self):
        """already-voided + 无孤儿 correction → 保持 Already Voided（409），零副作用。"""
        _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        svc.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
        })
        svc.void_trade_with_cascade(trade["trade_id"], "录入错误")
        # 第二次 void：已作废且无孤儿 → 保持 TradeAlreadyVoidedError（409），零副作用
        with pytest.raises(trade_ledger_store.TradeAlreadyVoidedError):
            svc.void_trade_with_cascade(trade["trade_id"], "再次作废")
        # 账本未被破坏
        derived = svc.derive_positions()
        assert derived["derivation_status"] == "OK"

    def test_void_trade_no_corrections_noop(self):
        _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        result = svc.void_trade_with_cascade(trade["trade_id"], "录入错误")
        assert result["status"] == "VOIDED"
        assert result["cascade_voided"] == 0
        derived = svc.derive_positions()
        assert derived["derivation_status"] == "OK"

    def test_void_after_already_voided_recovers_orphan(self):
        """already-voided + 孤儿 correction：同一事务清理孤儿，返回 ALREADY_VOIDED_RECOVERED（200）。"""
        _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        svc.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
            "reason": "成交数量修正",
        })
        # 模拟既有 /api/trades/{id}/void（不级联）：交易作废，correction 残留为孤儿
        trade_ledger_service.void_trade(trade["trade_id"], "既有 void 端点")
        with pytest.raises(svc.PositionDerivationError):
            svc.derive_positions()
        # 新端点再调：同一事务清理孤儿 correction，返回成功恢复状态（不返回 409）
        result = svc.void_trade_with_cascade(trade["trade_id"], "恢复路径")
        assert result["status"] == "ALREADY_VOIDED_RECOVERED"
        assert result["cascade_voided"] == 1
        # 孤儿已清理，账本恢复可推导
        derived = svc.derive_positions()
        assert derived["derivation_status"] == "OK"
        assert {p["code"]: p["shares"] for p in derived["positions"]} == {"600519": 100}

    def test_void_cascade_overlong_reason_rejected(self):
        """reason 超过 500 字符 → 校验拒绝（422），且不产生任何级联副作用。"""
        _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        svc.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
        })
        with pytest.raises(svc.PositionValidationError):
            svc.void_trade_with_cascade(trade["trade_id"], "超长原因" * 200)
        # 校验失败发生在任何副作用之前：交易未作废、correction 未级联，账本完整
        derived = svc.derive_positions()
        assert derived["derivation_status"] == "OK"
        assert {p["code"]: p["shares"] for p in derived["positions"]} == {"600519": 150}


class TestVoidAtomicFailureInjection:
    """R5-P1-1：真原子性故障注入 —— 任何步骤失败必须整体回滚，无半完成状态。"""

    def test_failure_between_correction_and_trade_void_rolls_back(self, monkeypatch):
        """correction 更新后、trade 更新前失败 → ROLLBACK：trade 仍 active、correction 仍 active、
        derivation 保持 correction 后的有效值（BUY 100 → correction 50，失败后仍 = 50，绝不回 100）。"""
        _bootstrap([])
        trade = _trade("600519", "buy", 10.0, 100)
        svc.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
            "reason": "成交数量修正",
        })

        def _boom(conn, trade_id, now_iso, reason):
            raise RuntimeError("injected failure after correction void, before trade void")

        monkeypatch.setattr(trade_ledger_store, "void_trade_on_connection", _boom)
        with pytest.raises(RuntimeError):
            svc.void_trade_with_cascade(trade["trade_id"], "录入错误")

        # 回滚后：trade 仍 ACTIVE、correction 仍 ACTIVE
        rec = trade_ledger_service.get_trade(trade["trade_id"])
        assert rec["voided_at"] is None
        events = account_event_store.list_events(
            svc.resolve_db_path(), include_voided=True
        )
        corr = [e for e in events if e["event_type"] == "CORRECTION"]
        assert len(corr) == 1
        assert corr[0]["voided_at"] is None
        # derivation 保持 correction 后的有效值（100 → 50），绝不回 100
        derived = svc.derive_positions()
        pos = next(p for p in derived["positions"] if p["code"] == "600519")
        assert pos["shares"] == 50

    def test_missing_trade_no_side_effect(self):
        """missing trade：存在孤立 correction 数据也不得修改它；404 且零副作用。"""
        _bootstrap([])
        # 直接注入指向不存在交易的孤儿 correction（异常数据场景）
        db_path = svc.resolve_db_path()
        account_event_store.insert_event(db_path, {
            "event_id": "aev_orphan_missing",
            "event_type": "CORRECTION",
            "code": None,
            "name": None,
            "shares": None,
            "cost_basis": None,
            "opening_cash": None,
            "ledger_start_at": None,
            "origin": None,
            "acquired_before_vibe": None,
            "historical_trades": None,
            "provenance": "MANUAL",
            "target_event_id": "missing_trade_id",
            "target_event_type": "trade",
            "before_payload": '{"actual_quantity": 100}',
            "after_payload": '{"actual_quantity": 50}',
            "reason": "异常数据",
            "note": None,
            "created_at": "2026-08-09T00:00:00+00:00",
        })
        with pytest.raises(trade_ledger_store.TradeNotFoundError):
            svc.void_trade_with_cascade("missing_trade_id", "恢复")
        # 孤儿 correction 未被修改（仍 active）
        events = account_event_store.list_events(
            svc.resolve_db_path(), include_voided=True
        )
        orphan = [e for e in events if e["event_id"] == "aev_orphan_missing"]
        assert len(orphan) == 1
        assert orphan[0]["voided_at"] is None

    def test_recovery_path_atomic(self):
        """already-voided + 孤儿恢复必须真正提交（correction 被清理，derivation 恢复）。"""
        _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        svc.create_correction({
            "target_event_id": trade["trade_id"],
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
        })
        trade_ledger_service.void_trade(trade["trade_id"], "既有 void")
        result = svc.void_trade_with_cascade(trade["trade_id"], "恢复")
        assert result["status"] == "ALREADY_VOIDED_RECOVERED"
        assert result["cascade_voided"] == 1
        derived = svc.derive_positions()
        assert derived["derivation_status"] == "OK"
        assert {p["code"]: p["shares"] for p in derived["positions"]} == {"600519": 100}


class TestReviewP2:
    def test_mixed_timezone_trade_order_stable(self):
        """混时区 executed_at 按 UTC 纪元排序，顺序不因字符串格式错乱（P2-1）。"""
        _bootstrap([_legacy("600519", 100, 10.0)])
        # 12:00+00:00 真实时间早于 20:00+08:00（12:00 UTC），但字符串序相反
        _trade("600519", "buy", 10.0, 50, executed_at="2026-08-03T12:00:00+00:00")
        _trade("600519", "sell", 15.0, 50, executed_at="2026-08-03T20:00:00+08:00")
        pos = _derived("600519")
        assert pos["shares"] == 100

    def test_correction_quantity_zero_rejected(self):
        """修正不允许把交易数量改为 0（零数量交易不参与推导，P2-3）。"""
        _bootstrap([_legacy("600519", 100, 10.0)])
        trade = _trade("600519", "buy", 10.0, 100)
        with pytest.raises(svc.PositionValidationError):
            svc.create_correction({
                "target_event_id": trade["trade_id"],
                "target_event_type": "trade",
                "after_payload": {"actual_quantity": 0},
            })


# ---------------------------------------------------------------------------
# Review round 5: P1-2 4dp reconciliation 精度
# ---------------------------------------------------------------------------


class TestReconciliation4dp:
    """ledger avg cost 保留 4 位小数，reconciliation 使用同一 canonical 4dp 值（P1-2）。"""

    def test_legacy_4dp_cost_match(self, pf_file):
        """legacy per-share cost 10.1234（4dp）→ avg=10.1234；portfolio cost 10.1234 → MATCH。"""
        _bootstrap([_legacy("600519", 100, 10.1234)])
        _write_portfolio(pf_file, [{"code": "600519", "shares": 100, "cost": 10.1234}])
        result = svc.reconcile_positions()
        item = result["items"][0]
        assert item["status"] == "MATCH"
        assert item["ledger_cost"] == 10.1234

    def test_weighted_avg_4dp_match(self, pf_file):
        """加权平均后产生 4dp avg：legacy 100@10.1234 + ADD 100@20.5 → avg 15.3117；
        portfolio 4dp cost 15.3117 → MATCH。"""
        _bootstrap([_legacy("600519", 100, 10.1234)])
        _trade("600519", "add", 20.5, 100)
        pos = _derived("600519")
        assert pos["avg_cost"] == 15.3117
        _write_portfolio(pf_file, [{"code": "600519", "shares": 200, "cost": 15.3117}])
        result = svc.reconcile_positions()
        assert result["items"][0]["status"] == "MATCH"

    def test_weighted_avg_4dp_mismatch_on_4th_digit(self, pf_file):
        """真正的第 4 位不同 → MISMATCH（ledger 15.3117 vs portfolio 15.3118）。"""
        _bootstrap([_legacy("600519", 100, 10.1234)])
        _trade("600519", "add", 20.5, 100)
        _write_portfolio(pf_file, [{"code": "600519", "shares": 200, "cost": 15.3118}])
        result = svc.reconcile_positions()
        item = result["items"][0]
        assert item["status"] == "MISMATCH"
        assert item["reason"] == "cost mismatch"
