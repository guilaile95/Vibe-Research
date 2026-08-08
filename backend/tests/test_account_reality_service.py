"""P0-S1B-A account reality service tests (offline, deterministic).

覆盖测试矩阵 A–F（34 项核心场景）。价格源 astock.kline 全部 monkeypatch，
不触发任何网络请求；portfolio.json / account_profile.json 写入隔离目录。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import account_event_store
import account_profile
import account_reality_service as svc
import astock
import portfolio
import position_reality_service
import trade_ledger_service
import trade_ledger_store


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    isolated = tmp_path / "ledger_db"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    yield


@pytest.fixture
def pf_file(tmp_path, monkeypatch):
    pf = tmp_path / "portfolio.json"
    monkeypatch.setattr(portfolio, "PF_FILE", str(pf))
    return pf


@pytest.fixture
def profile_file(tmp_path, monkeypatch):
    pf = tmp_path / "account_profile.json"
    monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
    return pf


@pytest.fixture(autouse=True)
def _no_network_kline(monkeypatch):
    """默认不联网：kline 返回空（UNPRICED）。具体测试用 _fake_kline 覆盖。"""

    def _empty(_code):
        return []

    monkeypatch.setattr(astock, "kline", _empty)


def _fake_kline(monkeypatch, bars_by_code: dict[str, list[dict]]):
    def _kline(code, category=4, offset=60):
        return bars_by_code.get(code, [])

    monkeypatch.setattr(astock, "kline", _kline)


def _write_account_profile(profile_file: Path, total_assets: float, available_cash: float) -> None:
    account_profile.save_account_profile(total_assets, available_cash)


def _bootstrap(positions: list[dict] | None = None, opening_cash: float | None = 100000.0) -> dict:
    return position_reality_service.bootstrap_commit({
        "ledger_start_at": "2026-08-01",
        "opening_cash": opening_cash,
        "positions": positions or [],
    })


def _trade(code: str, operation: str, price: float, qty: int, name: str = "测试股票", fee: float = 0.0, day: str = "2026-08-03") -> dict:
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


def _legacy(code: str, shares: int, cost_basis: float, name: str = "测试股票") -> dict:
    return {"code": code, "shares": shares, "cost_basis": cost_basis, "name": name}


_BAR_20260804 = {"datetime": "2026-08-04 15:00:00", "close": 20.0}
_BAR_20260805 = {"datetime": "2026-08-05 15:00:00", "close": 21.0}


# ---------------------------------------------------------------------------
# A. Account Profile（cash fact）
# ---------------------------------------------------------------------------


class TestAccountProfileCash:
    def test_valid_available_cash_manual_fact(self, profile_file):
        _write_account_profile(profile_file, 200000.0, 50000.0)
        fact = svc._current_cash_fact()
        assert fact["value"] == 50000.0
        assert fact["source"] == "ACCOUNT_PROFILE"
        assert fact["fact_type"] == "MANUAL_CURRENT_FACT"
        assert fact["status"] == "AVAILABLE"

    def test_not_configured_is_unknown_not_zero(self, profile_file):
        fact = svc._current_cash_fact()
        assert fact["value"] is None
        assert fact["status"] == "UNKNOWN"

    def test_corrupted_profile_fail_closed(self, profile_file):
        profile_file.write_text("{corrupted json", encoding="utf-8")
        fact = svc._current_cash_fact()
        assert fact["value"] is None
        assert fact["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# B. Ledger Cash Candidate
# ---------------------------------------------------------------------------


class TestLedgerCashCandidate:
    def test_opening_cash_no_trade(self):
        _bootstrap([], opening_cash=100000.0)
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] == 100000.0
        assert cand["coverage"] == "TRADES_ONLY"
        assert cand["fact_type"] == "DERIVED_FACT"

    def test_buy_deduction(self):
        _bootstrap([], opening_cash=100000.0)
        _trade("600519", "buy", 10.0, 100, fee=5.0)
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] == 100000.0 - (10.0 * 100 + 5.0)

    def test_add_deduction(self):
        _bootstrap([_legacy("600519", 100, 10.0)], opening_cash=100000.0)
        _trade("600519", "add", 20.0, 50)
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] == 100000.0 - 1000.0

    def test_reduce_proceeds(self):
        _bootstrap([_legacy("600519", 100, 10.0)], opening_cash=100000.0)
        _trade("600519", "reduce", 15.0, 40, fee=3.0)
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] == 100000.0 + (15.0 * 40 - 3.0)

    def test_sell_proceeds(self):
        _bootstrap([_legacy("600519", 100, 10.0)], opening_cash=100000.0)
        _trade("600519", "sell", 15.0, 100)
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] == 100000.0 + 1500.0

    def test_fee_other_cost_reuses_compute_fields(self, monkeypatch):
        """ledger cash 使用 trade_ledger_service.compute_fields（不实现第二套算法）。"""
        called = {"n": 0}
        original = trade_ledger_service.compute_fields

        def _spy(record):
            called["n"] += 1
            return original(record)

        monkeypatch.setattr(trade_ledger_service, "compute_fields", _spy)
        _bootstrap([], opening_cash=100000.0)
        _trade("600519", "buy", 10.0, 100, fee=5.0)
        svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert called["n"] >= 1

    def test_voided_trade_excluded(self):
        _bootstrap([], opening_cash=100000.0)
        trade = _trade("600519", "buy", 10.0, 100)
        trade_ledger_service.void_trade(trade["trade_id"], "作废")
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] == 100000.0

    def test_not_executed_no_cash_change(self):
        _bootstrap([], opening_cash=100000.0)
        trade_ledger_service.create_trade({
            "code": "600519",
            "name": "测试股票",
            "operation": "buy",
            "execution_status": "not_executed",
            "planned_price": 10.0,
            "planned_quantity": 100,
            "unexecuted_reason": "未成交",
        })
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] == 100000.0

    def test_opening_cash_unknown(self):
        _bootstrap([], opening_cash=None)
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] is None
        assert cand["reason_code"] == "OPENING_CASH_UNKNOWN"

    def test_not_bootstrapped(self):
        cand = svc._ledger_cash_candidate(position_reality_service.derive_positions())
        assert cand["value"] is None
        assert cand["reason_code"] == "NOT_BOOTSTRAPPED"


# ---------------------------------------------------------------------------
# C. Cash Reconciliation
# ---------------------------------------------------------------------------


class TestCashReconciliation:
    def test_match(self, profile_file):
        _write_account_profile(profile_file, 200000.0, 100000.0)
        _bootstrap([], opening_cash=100000.0)
        derived = position_reality_service.derive_positions()
        recon = svc._cash_reconciliation(svc._current_cash_fact(), svc._ledger_cash_candidate(derived))
        assert recon["status"] == "MATCH"

    def test_mismatch(self, profile_file):
        _write_account_profile(profile_file, 200000.0, 99999.0)
        _bootstrap([], opening_cash=100000.0)
        derived = position_reality_service.derive_positions()
        recon = svc._cash_reconciliation(svc._current_cash_fact(), svc._ledger_cash_candidate(derived))
        assert recon["status"] == "MISMATCH"

    def test_either_unavailable_unknown(self):
        _bootstrap([], opening_cash=None)  # ledger candidate UNKNOWN
        derived = position_reality_service.derive_positions()
        recon = svc._cash_reconciliation(
            {"value": None, "status": "UNKNOWN"},
            svc._ledger_cash_candidate(derived),
        )
        assert recon["status"] == "UNKNOWN"

    def test_always_declares_trades_only_coverage(self):
        """account reality 顶层必须始终声明 cash coverage=TRADES_ONLY + CASH_EVENTS_UNSUPPORTED。"""
        _bootstrap([], opening_cash=100000.0)
        reality = svc.get_account_reality()
        assert reality["cash"]["coverage"] == "TRADES_ONLY"
        assert "CASH_EVENTS_UNSUPPORTED" in reality["reason_codes"]


# ---------------------------------------------------------------------------
# D. Settled Pricing
# ---------------------------------------------------------------------------


class TestSettledPricing:
    def test_single_position_priced(self, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _bootstrap([_legacy("600519", 100, 10.0)])
        derived = position_reality_service.derive_positions()
        pricing = svc._settled_pricing([p for p in derived["positions"] if p["status"] == "OPEN"])
        assert pricing["status"] == "COMPLETE"
        assert pricing["unified_price_date"] == "2026-08-04"
        assert pricing["positions"][0]["price"] == 20.0
        assert pricing["positions"][0]["market_value"] == 2000.0

    def test_multiple_same_price_date_complete(self, monkeypatch):
        _fake_kline(monkeypatch, {
            "600519": [_BAR_20260804],
            "000001": [{"datetime": "2026-08-04 15:00:00", "close": 10.0}],
        })
        _bootstrap([_legacy("600519", 100, 10.0), _legacy("000001", 200, 5.0)])
        derived = position_reality_service.derive_positions()
        pricing = svc._settled_pricing([p for p in derived["positions"] if p["status"] == "OPEN"])
        assert pricing["status"] == "COMPLETE"
        assert pricing["unified_price_date"] == "2026-08-04"

    def test_missing_price_partial(self, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})  # 000001 无价格
        _bootstrap([_legacy("600519", 100, 10.0), _legacy("000001", 200, 5.0)])
        derived = position_reality_service.derive_positions()
        pricing = svc._settled_pricing([p for p in derived["positions"] if p["status"] == "OPEN"])
        assert pricing["status"] == "PARTIAL"
        assert pricing["unified_price_date"] is None

    def test_invalid_price_rejected(self, monkeypatch):
        _fake_kline(monkeypatch, {
            "600519": [{"datetime": "2026-08-04 15:00:00", "close": float("nan")}],
        })
        _bootstrap([_legacy("600519", 100, 10.0)])
        derived = position_reality_service.derive_positions()
        pricing = svc._settled_pricing([p for p in derived["positions"] if p["status"] == "OPEN"])
        assert pricing["status"] == "UNAVAILABLE"
        assert pricing["positions"][0]["pricing_status"] == "UNPRICED"

    def test_mixed_cutoff_fail_closed(self, monkeypatch):
        _fake_kline(monkeypatch, {
            "600519": [_BAR_20260804],
            "000001": [_BAR_20260805],
        })
        _bootstrap([_legacy("600519", 100, 10.0), _legacy("000001", 200, 5.0)])
        derived = position_reality_service.derive_positions()
        pricing = svc._settled_pricing([p for p in derived["positions"] if p["status"] == "OPEN"])
        assert pricing["status"] == "MIXED_CUTOFF"
        assert pricing["unified_price_date"] is None  # 不选任一日期冒充

    def test_price_date_not_from_now(self, monkeypatch):
        """price_date 必须来自 kline 数据，不得用 now/today 伪造。"""
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _bootstrap([_legacy("600519", 100, 10.0)])
        derived = position_reality_service.derive_positions()
        pricing = svc._settled_pricing([p for p in derived["positions"] if p["status"] == "OPEN"])
        assert pricing["unified_price_date"] == "2026-08-04"  # 来自 bar，非系统时间


# ---------------------------------------------------------------------------
# E. Settled NAV
# ---------------------------------------------------------------------------


class TestSettledNav:
    def test_cash_fact_complete_pricing_nav(self, profile_file, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap([_legacy("600519", 100, 10.0)])
        reality = svc.get_account_reality()
        assert reality["settled_nav"] == 50000.0 + 2000.0
        assert reality["nav_cash_source"] == "ACCOUNT_PROFILE"

    def test_cash_unknown_nav_null(self, profile_file, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        # 未配置 account_profile → cash fact UNKNOWN
        _bootstrap([_legacy("600519", 100, 10.0)])
        reality = svc.get_account_reality()
        assert reality["settled_nav"] is None
        assert "CASH_UNKNOWN" in reality["reason_codes"]

    def test_partial_pricing_nav_null(self, profile_file, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap([_legacy("600519", 100, 10.0), _legacy("000001", 200, 5.0)])
        reality = svc.get_account_reality()
        assert reality["settled_nav"] is None
        assert reality["pricing"]["status"] == "PARTIAL"
        assert "PRICING_PARTIAL" in reality["reason_codes"]

    def test_mixed_cutoff_nav_null(self, profile_file, monkeypatch):
        _fake_kline(monkeypatch, {
            "600519": [_BAR_20260804],
            "000001": [_BAR_20260805],
        })
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap([_legacy("600519", 100, 10.0), _legacy("000001", 200, 5.0)])
        reality = svc.get_account_reality()
        assert reality["settled_nav"] is None
        assert "PRICING_MIXED_CUTOFF" in reality["reason_codes"]

    def test_empty_positions_nav_equals_cash(self, profile_file):
        _write_account_profile(profile_file, 50000.0, 50000.0)
        _bootstrap([], opening_cash=50000.0)
        reality = svc.get_account_reality()
        assert reality["settled_nav"] == 50000.0
        assert reality["pricing"]["status"] == "COMPLETE"

    def test_bootstrap_not_complete_fail_closed(self, profile_file, monkeypatch):
        """未 bootstrap → settled NAV null + NOT_BOOTSTRAPPED reason。"""
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _trade("600519", "buy", 10.0, 100)  # trade-only（未 bootstrap）
        reality = svc.get_account_reality()
        assert reality["settled_nav"] is None
        assert "NOT_BOOTSTRAPPED" in reality["reason_codes"]


# ---------------------------------------------------------------------------
# F. Reconciliation / Safety
# ---------------------------------------------------------------------------


class TestAccountRealitySafety:
    def test_nav_vs_total_assets_match(self, profile_file, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _bootstrap([_legacy("600519", 100, 10.0)])
        _write_account_profile(profile_file, 52000.0, 50000.0)
        reality = svc.get_account_reality()
        assert reality["settled_nav"] == 52000.0
        assert reality["nav_reconciliation"]["status"] == "MATCH"

    def test_nav_vs_total_assets_mismatch(self, profile_file, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _bootstrap([_legacy("600519", 100, 10.0)])
        _write_account_profile(profile_file, 53000.0, 50000.0)
        reality = svc.get_account_reality()
        assert reality["nav_reconciliation"]["status"] == "MISMATCH"

    def test_portfolio_json_untouched(self, pf_file, profile_file, monkeypatch):
        """portfolio.json 在 account reality 调用前后字节完全不变。"""
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap([_legacy("600519", 100, 10.0)])
        # 写一个 portfolio.json 供对照
        pf_file.write_text(
            json.dumps({"holdings": [{"code": "600519", "shares": 100, "cost": 10.0}], "last_refresh": None}),
            encoding="utf-8",
        )
        before = pf_file.read_bytes()
        svc.get_account_reality()
        assert pf_file.read_bytes() == before

    def test_account_profile_json_untouched(self, profile_file, monkeypatch):
        """account_profile.json 在 account reality 调用前后字节完全不变。"""
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap([_legacy("600519", 100, 10.0)])
        before = profile_file.read_bytes()
        svc.get_account_reality()
        assert profile_file.read_bytes() == before

    def test_deterministic_repeat(self, profile_file, monkeypatch):
        """同输入两次执行结果一致（除 as_of 时间戳）。"""
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap([_legacy("600519", 100, 10.0)])
        r1 = svc.get_account_reality()
        r2 = svc.get_account_reality()
        r1.pop("as_of")
        r2.pop("as_of")
        assert r1 == r2

    def test_corrupted_ledger_fail_closed(self, profile_file, monkeypatch):
        """corrupted ledger → 不产出部分 NAV，直接 fail closed。"""
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804]})
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap([_legacy("600519", 100, 10.0)])
        # 破坏 ledger 文件
        db = trade_ledger_service.resolve_db_path()
        with open(db, "wb") as f:
            f.write(b"corrupted data")
        with pytest.raises(
            (trade_ledger_store.TradeLedgerCorruptedError, account_event_store.AccountEventCorruptedError)
        ):
            svc.get_account_reality()

    def test_positions_only_from_s1a_derivation(self, profile_file, monkeypatch):
        """positions 只来自 S1A derivation；portfolio.json 中多出的持仓不得并入。"""
        _fake_kline(monkeypatch, {"600519": [_BAR_20260804], "000001": [_BAR_20260804]})
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap([_legacy("600519", 100, 10.0)])
        # portfolio.json 有 ledger 之外的 000001
        pf_file = profile_file.parent / "portfolio.json"
        pf_file.write_text(
            json.dumps({"holdings": [{"code": "000001", "shares": 200, "cost": 5.0}]}),
            encoding="utf-8",
        )
        reality = svc.get_account_reality()
        codes = {p["code"] for p in reality["positions"]}
        assert codes == {"600519"}  # 000001 不并入
