"""BK-11 Tushare ingestion service 与 CLI 离线测试。"""

from __future__ import annotations

import json
import sys
import threading
from copy import deepcopy
from datetime import datetime, timezone

import pytest

sys.path.insert(0, "backend")

import bk11_tushare_ingestion_service as service  # noqa: E402
import bk11_tushare_cli as cli  # noqa: E402
import short_term_fact_store as store  # noqa: E402
import tushare_pro_client as tpc  # noqa: E402


T = "2026-07-30"


def _daily(code, pct, close, high=None):
    return {"ts_code": code, "trade_date": T,
            "high": close if high is None else high,
            "close": close, "pct_chg": pct}


def _stk(code, up, down):
    return {"ts_code": code, "trade_date": T, "up_limit": up, "down_limit": down}


def _basic(code, status="L"):
    return {"ts_code": code, "symbol": code[:6], "exchange": "SSE",
            "market": "主板", "list_status": status,
            "list_date": "2010-01-01", "delist_date": None}


class FakeClient:
    def __init__(self, limit_up_code=None):
        codes = ["600519.SH", "000001.SZ"]
        self.limits = {
            "600519.SH": (1600.0, 1400.0),
            "000001.SZ": (12.0, 9.8),
        }
        self.daily = [
            _daily("600519.SH", 1.5, 1500.0),
            _daily("000001.SZ", -0.5, 11.0),
        ]
        if limit_up_code:
            self.daily.append(_daily(limit_up_code, 10.0, 100.0, high=100.0))
            codes.append(limit_up_code)
            self.limits[limit_up_code] = (100.0, 90.0)
        self.stk = [_stk(c, *self.limits[c]) for c in codes]
        self.suspend = []
        self.basic = [_basic(c) for c in codes]
        self.calls = {"daily": 0, "suspend_d": 0, "stk_limit": 0,
                      "stock_basic": 0}

    def query(self, api_name, params, fields=None):
        self.calls[api_name] += 1
        if api_name == "daily":
            return deepcopy(self.daily)
        if api_name == "suspend_d":
            return deepcopy(self.suspend)
        if api_name == "stk_limit":
            return deepcopy(self.stk)
        if api_name == "stock_basic":
            return deepcopy(self.basic)
        raise AssertionError(api_name)


def _producer(status="normal", rows=None):
    if rows is None:
        rows = []
    if status != "normal":
        return {
            "schema_version": "short-term-limit-up-final-snapshot-v0.1",
            "requested_trade_date": T,
            "observed_at": "2026-07-31T02:00:00.000000Z",
            "status": status,
            "reason_codes": ["SOURCE_UNAVAILABLE"] if status == "unavailable"
                            else ["SOURCE_PARTIAL"],
            "session": "not_final",
            "is_final": False,
            "finality_basis": None,
            "required_observations": 3,
            "completed_observations": 0,
            "stable_observation_count": 0,
            "observation_interval_seconds": 2.2,
            "required_stability_window_seconds": 4.4,
            "actual_stability_window_seconds": None,
            "first_observation_monotonic": None,
            "last_observation_monotonic": None,
            "snapshot": None,
            "warnings": [],
        }
    return {
        "schema_version": "short-term-limit-up-final-snapshot-v0.1",
        "requested_trade_date": T,
        "observed_at": "2026-07-31T02:00:00.000000Z",
        "status": "normal", "reason_codes": [], "session": "final",
        "is_final": True,
        "finality_basis": "three_identical_normal_observations",
        "required_observations": 3, "completed_observations": 3,
        "stable_observation_count": 3, "observation_interval_seconds": 2.2,
        "required_stability_window_seconds": 4.4,
        "actual_stability_window_seconds": 4.4,
        "first_observation_monotonic": 100.0,
        "last_observation_monotonic": 104.4,
        "snapshot": {
            "schema_version": "short-term-limit-up-pool-adapter-v0.2",
            "source_id": "eastmoney_getTopicZTPool",
            "endpoint": "getTopicZTPool",
            "requested_trade_date": T,
            "observed_at": "2026-07-31T02:00:00.000000Z",
            "status": "normal", "reason_codes": [], "rows": rows,
            "transport_success": True, "parse_success": True,
            "required_field_present": True, "data_array_present": True,
            "trade_date_match": True, "row_count": len(rows), "legal_zero": False,
            "upstream_null": False, "unexplained_empty": False,
            "coverage_warning": False,
        },
        "warnings": [],
    }


@pytest.fixture()
def sessions(monkeypatch):
    def fake_sessions():
        return ("2026-07-29", "2026-07-30", "2026-07-31")
    monkeypatch.setattr(service.trade_calendar, "_load_calendar", fake_sessions)
    monkeypatch.setattr(service, "_today_shanghai", lambda: "2026-08-06")


@pytest.fixture()
def data_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VR_REPORTS_DIR", str(tmp_path / "myreports"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB",
                       str(tmp_path / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_NEWS_RADAR_CACHE",
                       str(tmp_path / "radar.json"))
    import data_health_adapters as adapters
    adapters.reset_adapters_for_tests()
    return tmp_path


class TestService:
    def test_non_trading_date(self, sessions):
        result = service.ingest_trade_date("2026-07-28")
        assert result["reason_code"] == "NON_TRADING_DATE"

    def test_future_date(self, sessions):
        result = service.ingest_trade_date("2026-09-01")
        assert result["reason_code"] == "NOT_FINALIZED"

    def test_today_not_finalized(self, sessions):
        result = service.ingest_trade_date("2026-08-06")
        assert result["reason_code"] == "NOT_FINALIZED"

    def test_invalid_date_format(self):
        result = service.ingest_trade_date("2026-13-99")
        assert result["reason_code"] == "INVALID_TRADE_DATE"

    def test_credential_missing(self, sessions, monkeypatch):
        class NoTokenClient(FakeClient):
            def query(self, api_name, params, fields=None):
                raise tpc.TushareCredentialMissing("no token")
        result = service.ingest_trade_date(T, client=NoTokenClient())
        assert result["reason_code"] == "CREDENTIAL_MISSING"

    def test_permission_denied(self, sessions, monkeypatch):
        class DeniedClient(FakeClient):
            def query(self, api_name, params, fields=None):
                raise tpc.TusharePermissionDenied("denied")
        result = service.ingest_trade_date(T, client=DeniedClient())
        assert result["reason_code"] == "PERMISSION_DENIED"

    def test_normal_save_and_history_read(self, sessions, data_env,
                                         monkeypatch):
        db = data_env / "short_term_facts.sqlite3"
        monkeypatch.setattr(
            "bk11_tushare_ingestion_service._ingest_locked",
            lambda trade_date, client=None, store_db=None: _ingest_stub(
                trade_date, store_db,
                FakeClient(limit_up_code="688981.SH"),
                _producer(rows=[{"stock_code": "688981.SH", "lbc": 1}])),
        )
        result = service.ingest_trade_date(T, store_db=str(db))
        assert result["saved"] is True
        loaded = store.load_daily_facts(T, "final", db_path=db)
        assert loaded["schema_version"] == "short-term-daily-facts-v0.2"

        import bk11_history_service as history
        env = history.query_history(days=5, db_path=db)
        assert env["status"] == "normal"
        assert env["latest"]["schema_version"] == "short-term-daily-facts-v0.2"

    def test_data_health_transition(self, sessions, data_env, monkeypatch):
        db = data_env / "short_term_facts.sqlite3"
        import bk11_history_service as history
        before = history.query_history(days=5, db_path=db)
        assert before["status"] == "empty"

        monkeypatch.setattr(
            "bk11_tushare_ingestion_service._ingest_locked",
            lambda trade_date, client=None, store_db=None: _ingest_stub(
                trade_date, store_db,
                FakeClient(limit_up_code="688981.SH"),
                _producer(rows=[{"stock_code": "688981.SH", "lbc": 1}])),
        )
        service.ingest_trade_date(T, store_db=str(db))
        import data_health_adapters as adapters
        rec = adapters.Bk11HistoryAdapter().read(
            adapters.HealthReadContext(now_utc=datetime.now(timezone.utc)))
        assert rec["status"] == "normal"
        assert rec["data_trade_date"] == T

    def test_zero_limit_up_uses_empty_ladder(self, sessions, data_env,
                                             monkeypatch):
        db = data_env / "short_term_facts.sqlite3"
        result = _ingest_stub(
            T, str(db), _zero_facts_client(), _producer())
        assert result["saved"] is True
        loaded = store.load_daily_facts(T, "final", db_path=db)
        assert loaded["sections"]["ladder"]["metrics"]["max_boards"] == 0

    def test_single_flight(self, sessions, data_env, monkeypatch):
        calls = {"n": 0}
        lock = threading.Lock()

        def slow_ingest(trade_date, client=None, store_db=None):
            with lock:
                calls["n"] += 1
            return _ingest_stub(trade_date, store_db, FakeClient(), _producer())

        monkeypatch.setattr(
            "bk11_tushare_ingestion_service._ingest_locked", slow_ingest)
        db = data_env / "single.sqlite3"
        results = []
        threads = [
            threading.Thread(
                target=lambda: results.append(
                    service.ingest_trade_date(T, store_db=str(db))))
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert calls["n"] == 1
        assert len(results) == 4
        assert all(r.get("deduped") or r.get("saved") for r in results)

    def test_no_sensitive_output(self, sessions, data_env, monkeypatch):
        db = data_env / "short_term_facts.sqlite3"
        monkeypatch.setattr(
            "bk11_tushare_ingestion_service._ingest_locked",
            lambda trade_date, client=None, store_db=None: _ingest_stub(
                trade_date, store_db, FakeClient(), _producer()))
        result = service.ingest_trade_date(T, store_db=str(db))
        text = json.dumps(result)
        assert "TUSHARE_TOKEN" not in text
        assert str(data_env) not in text
        assert "Traceback" not in text

    def test_partial_existing_is_upgradable(self, sessions, data_env,
                                            monkeypatch):
        """已有 partial 记录：重跑必须走采集/升级路径，而非直接 deduped。"""
        db = data_env / "short_term_facts.sqlite3"
        calls = {"n": 0}
        import short_term_daily_facts_v02 as v02
        import bk11_tushare_facts_adapter as adapter
        import short_term_limit_up_final_snapshot as fp
        from tests.test_bk11_tushare_ingestion import FakeClient as _FC

        # 先落一条 partial v0.2（直接用 composer+monotonic 构造）
        fc = _FC()
        facts = adapter.fetch_tushare_facts_snapshot(T, fc)
        # 制造 partial：给 facts 一个 coverage warning
        facts["facts_data_health"]["coverage_warning"] = True
        facts["status"] = "partial"
        facts["reason_codes"] = ["COVERAGE_WARNING"]
        env = v02.compute_daily_facts_v02(
            facts, {"kind": "producer", "envelope": _producer(
                rows=[{"stock_code": "688981.SH", "lbc": 1}])})
        # facts partial → 整体 partial
        store.save_daily_facts_monotonic(env, db_path=db)
        assert store.load_daily_facts(T, "final", db_path=db)["status"] == "partial"

        def counting_ingest(trade_date, client=None, store_db=None):
            calls["n"] += 1
            return _ingest_stub(
                trade_date, store_db,
                _FC(limit_up_code="688981.SH"),
                _producer(rows=[{"stock_code": "688981.SH", "lbc": 1}]))

        monkeypatch.setattr(
            "bk11_tushare_ingestion_service._ingest_locked", counting_ingest)
        result = service.ingest_trade_date(T, store_db=str(db))
        assert calls["n"] == 1
        assert result["upgraded"] is True
        loaded = store.load_daily_facts(T, "final", db_path=db)
        assert loaded["status"] == "normal"

    def test_existing_normal_deduped(self, sessions, data_env, monkeypatch):
        db = data_env / "short_term_facts.sqlite3"
        calls = {"n": 0}
        _ingest_stub(T, str(db), FakeClient(limit_up_code="688981.SH"),
                     _producer(rows=[{"stock_code": "688981.SH", "lbc": 1}]))

        def counting_ingest(trade_date, client=None, store_db=None):
            calls["n"] += 1
            return _ingest_stub(trade_date, store_db)

        monkeypatch.setattr(
            "bk11_tushare_ingestion_service._ingest_locked", counting_ingest)
        result = service.ingest_trade_date(T, store_db=str(db))
        assert calls["n"] == 0
        assert result["deduped"] is True


def _ingest_stub(trade_date, store_db, fake_client, producer=None):
    """真实组合 + 保存路径（复用 service 内部逻辑的轻量替身）。"""
    import bk11_tushare_facts_adapter as adapter
    import short_term_daily_facts_v02 as v02
    import short_term_limit_up_final_snapshot as fp
    facts = adapter.fetch_tushare_facts_snapshot(trade_date, fake_client)
    limit_up = int(facts.get("limit_activity", {}).get("limit_up_count") or 0)
    if limit_up == 0 and facts.get("legal_zero") is True:
        ladder_input = {"kind": "empty_ladder_proof"}
    else:
        ladder_input = {"kind": "producer",
                        "envelope": producer or fp.fetch_final_limit_up_pool_snapshot(
                            trade_date)}
    env = v02.compute_daily_facts_v02(facts, ladder_input)
    if env["status"] not in ("normal", "partial"):
        return {
            "schema_version": service.SCHEMA_VERSION, "action": "ingest",
            "trade_date": trade_date, "status": "error", "saved": False,
            "deduped": False, "upgraded": False, "blocked": True,
            "reason_code": "ENVELOPE_VALIDATION_FAILED",
            "limitations": [], "snapshot": None,
        }
    result = store.save_daily_facts_monotonic(env, db_path=store_db)
    return {
        "schema_version": service.SCHEMA_VERSION, "action": "ingest",
        "trade_date": trade_date,
        "status": env["status"] if not result.get("blocked") else "blocked",
        "saved": bool(result.get("saved")),
        "deduped": bool(result.get("deduped")),
        "upgraded": bool(result.get("upgraded")),
        "blocked": bool(result.get("blocked")),
        "reason_code": result.get("reason_code"),
        "limitations": env.get("limitations") or [],
        "snapshot": result.get("snapshot"),
    }


def _zero_facts_client():
    """limit_up_count=0 且满足 legal-zero 全部条件的 client。"""
    fc = FakeClient()
    fc.daily = [_daily("600519.SH", 1.0, 1500.0, high=1500.0),
                _daily("000001.SZ", -0.2, 11.0, high=11.2)]
    fc.stk = [_stk("600519.SH", 1600.0, 1400.0),
              _stk("000001.SZ", 12.0, 9.8)]
    fc.suspend = []
    fc.basic = [_basic("600519.SH"), _basic("000001.SZ")]
    return fc


class TestCli:
    def test_exit_codes(self, monkeypatch):
        cases = [
            ("CREDENTIAL_MISSING", cli.EXIT_CREDENTIAL_MISSING),
            ("PERMISSION_DENIED", cli.EXIT_PERMISSION_DENIED),
            ("SOURCE_UNAVAILABLE", cli.EXIT_SOURCE_UNAVAILABLE),
            ("CONTRACT_FAILED", cli.EXIT_CONTRACT_FAILED),
            ("STORAGE_FAILED", cli.EXIT_STORAGE_FAILED),
        ]
        for reason, code in cases:
            monkeypatch.setattr(
                service, "ingest_trade_date",
                lambda *a, _r=reason, **k: {
                    "schema_version": "x", "action": "ingest",
                    "trade_date": T, "status": "error", "saved": False,
                    "deduped": False, "upgraded": False, "blocked": True,
                    "reason_code": _r, "limitations": [], "snapshot": None})
            assert cli.main(["ingest", "--trade-date", T]) == code

    def test_success_exit_zero(self, monkeypatch):
        monkeypatch.setattr(
            service, "ingest_trade_date",
            lambda *a, **k: {
                "schema_version": "x", "action": "ingest", "trade_date": T,
                "status": "normal", "saved": True, "deduped": False,
                "upgraded": False, "blocked": False, "reason_code": None,
                "limitations": [], "snapshot": {}})
        assert cli.main(["ingest", "--trade-date", T]) == cli.EXIT_OK

    def test_deduped_exit_zero(self, monkeypatch):
        monkeypatch.setattr(
            service, "ingest_trade_date",
            lambda *a, **k: {
                "schema_version": "x", "action": "ingest", "trade_date": T,
                "status": "deduped", "saved": False, "deduped": True,
                "upgraded": False, "blocked": False, "reason_code": "DEDUPED",
                "limitations": [], "snapshot": {}})
        assert cli.main(["ingest", "--trade-date", T]) == cli.EXIT_OK

    def test_storage_conflict_exit_14(self, monkeypatch):
        for reason in ("NORMAL_CONFLICT", "PARTIAL_CONFLICT",
                       "SCHEMA_CONFLICT_V01"):
            monkeypatch.setattr(
                service, "ingest_trade_date",
                lambda *a, _r=reason, **k: {
                    "schema_version": "x", "action": "ingest",
                    "trade_date": T, "status": "blocked", "saved": False,
                    "deduped": False, "upgraded": False, "blocked": True,
                    "reason_code": _r, "limitations": [], "snapshot": None})
            assert cli.main(["ingest", "--trade-date", T]) == cli.EXIT_STORAGE_FAILED

    def test_token_flag_not_accepted(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["ingest", "--trade-date", T, "--token", "abc"])
        assert exc.value.code == cli.EXIT_USAGE

    def test_missing_trade_date(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["ingest"])
        assert exc.value.code == cli.EXIT_USAGE

    def test_no_sensitive_output(self, monkeypatch, capsys):
        monkeypatch.setattr(
            service, "ingest_trade_date",
            lambda *a, **k: {
                "schema_version": "x", "action": "ingest", "trade_date": T,
                "status": "normal", "saved": True, "deduped": False,
                "upgraded": False, "blocked": False, "reason_code": None,
                "limitations": [], "snapshot": {}})
        cli.main(["ingest", "--trade-date", T])
        out = capsys.readouterr().out
        assert "token" not in out.lower()
