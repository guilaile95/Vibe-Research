"""P0-S1B-A account reality API tests (offline, deterministic)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import account_profile
import account_reality_service as svc
import app
import astock
import portfolio
import position_reality_service


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    isolated = tmp_path / "trade_db"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    yield


@pytest.fixture
def client():
    return TestClient(app.app)


@pytest.fixture(autouse=True)
def _no_network_kline(monkeypatch):
    def _empty(_code):
        return []

    monkeypatch.setattr(astock, "kline", _empty)


def _fake_kline(monkeypatch, bars_by_code: dict[str, list[dict]]):
    def _kline(code, category=4, offset=60):
        return bars_by_code.get(code, [])

    monkeypatch.setattr(astock, "kline", _kline)


def _bootstrap(opening_cash: float = 100000.0, positions: list[dict] | None = None) -> None:
    position_reality_service.bootstrap_commit({
        "ledger_start_at": "2026-08-01",
        "opening_cash": opening_cash,
        "positions": positions or [],
    })


def _write_account_profile(profile_file: Path, total_assets: float, available_cash: float) -> None:
    account_profile.save_account_profile(total_assets, available_cash)


class TestRouteRegistration:
    def test_routes_registered_exactly_once(self):
        target_paths = {("GET", "/api/account/reality")}
        found_counts = {t: 0 for t in target_paths}
        all_routes = []
        for route in app.app.routes:
            if hasattr(route, "original_router"):
                all_routes.extend(route.original_router.routes)
            else:
                all_routes.append(route)
        for route in all_routes:
            methods = getattr(route, "methods", set()) or set()
            path = getattr(route, "path", "")
            for m in methods:
                if (m, path) in found_counts:
                    found_counts[(m, path)] += 1
        for target, count in found_counts.items():
            assert count == 1, f"Route {target} registered {count} times (expected 1)"


class TestAccountRealityApi:
    def test_reality_structure(self, client, tmp_path, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [{"datetime": "2026-08-04 15:00:00", "close": 20.0}]})
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap(opening_cash=100000.0, positions=[
            {"code": "600519", "shares": 100, "cost_basis": 10.0, "name": "贵州茅台"},
        ])
        resp = client.get("/api/account/reality")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["canonical"] is False
        assert data["bootstrap_status"] == "BOOTSTRAPPED"
        assert data["cash"]["reconciliation"] in ("MATCH", "MISMATCH", "UNKNOWN")
        assert data["cash"]["coverage"] == "TRADES_PLUS_MANUAL_CASH_EVENTS"
        assert data["pricing"]["status"] == "COMPLETE"
        assert data["pricing"]["unified_price_date"] == "2026-08-04"
        assert data["settled_nav"] == 50000.0 + 2000.0
        assert data["nav_cash_source"] == "ACCOUNT_PROFILE"
        assert data["data_cutoff"] is None
        assert data["nav_temporal_state"] == "MIXED_UNPROVEN"
        assert "CASH_EFFECTIVE_AT_UNPROVEN" in data["nav_temporal_reason_codes"]
        assert data["cash"]["current_fact"]["effective_at"] is None
        assert data["cash"]["ledger_candidate"]["effective_at"] is None
        assert data["cash"]["current_fact"]["temporal_status"] == "UNPROVEN"
        assert "CASH_EVENTS_UNSUPPORTED" in data["reason_codes"]

    def test_reality_cash_unknown(self, client, tmp_path, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [{"datetime": "2026-08-04 15:00:00", "close": 20.0}]})
        _bootstrap(opening_cash=100000.0, positions=[
            {"code": "600519", "shares": 100, "cost_basis": 10.0},
        ])
        # 未配置 account_profile
        resp = client.get("/api/account/reality")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["settled_nav"] is None
        assert "CASH_UNKNOWN" in data["reason_codes"]

    def test_reality_corrupted_profile_is_explicit_and_fail_closed(self, client, tmp_path, monkeypatch):
        _fake_kline(monkeypatch, {"600519": [{"datetime": "2026-08-04 15:00:00", "close": 20.0}]})
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        profile_file.write_text("{corrupted json", encoding="utf-8")
        before = profile_file.read_bytes()
        _bootstrap(opening_cash=100000.0, positions=[
            {"code": "600519", "shares": 100, "cost_basis": 10.0},
        ])
        resp = client.get("/api/account/reality")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["cash"]["current_fact"]["status"] == "CORRUPTED"
        assert data["cash"]["current_fact"]["reason_code"] == "ACCOUNT_PROFILE_CORRUPTED"
        assert data["cash"]["ledger_candidate"]["status"] == "AVAILABLE"
        assert data["cash"]["reconciliation"] == "UNKNOWN"
        assert data["settled_nav"] is None
        assert "ACCOUNT_PROFILE_CORRUPTED" in data["reason_codes"]
        assert data["nav_reconciliation"]["status"] == "UNKNOWN"
        assert profile_file.read_bytes() == before

    def test_reality_not_bootstrapped(self, client, tmp_path, monkeypatch):
        """未 bootstrap → settled NAV null + NOT_BOOTSTRAPPED。"""
        _fake_kline(monkeypatch, {"600519": [{"datetime": "2026-08-04 15:00:00", "close": 20.0}]})
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        _write_account_profile(profile_file, 200000.0, 50000.0)
        resp = client.get("/api/account/reality")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["settled_nav"] is None
        assert "NOT_BOOTSTRAPPED" in data["reason_codes"]

    def test_internal_error_sanitized(self, client, tmp_path, monkeypatch):
        """内部错误必须脱敏为 500 通用消息，不泄漏内部细节。"""
        def _boom(*_args, **_kwargs):
            raise RuntimeError("internal secret detail: /path/to/db")

        # kline 异常会被服务捕获为 UNPRICED（fail-closed 降级），因此注入更上层错误路径
        monkeypatch.setattr(svc, "_settled_pricing", _boom)
        profile_file = tmp_path / "account_profile.json"
        monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
        _write_account_profile(profile_file, 200000.0, 50000.0)
        _bootstrap(opening_cash=100000.0, positions=[
            {"code": "600519", "shares": 100, "cost_basis": 10.0},
        ])
        resp = client.get("/api/account/reality")
        assert resp.status_code == 500
        assert "internal secret detail" not in resp.text
        assert resp.json()["detail"] == "内部错误"
