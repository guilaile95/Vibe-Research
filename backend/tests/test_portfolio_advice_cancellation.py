"""Offline cancellation regressions: actual ASGI disconnect and real SQLite restore."""
from __future__ import annotations

import asyncio
import copy
import json
import threading
import sqlite3

import pytest

import ai_result_service
import ai_result_store
import app as app_module
import portfolio_advice_service as service
import decision_evidence_service
import decision_trace_store
import signal_ledger_service
from test_ai_result_service import _advice_payload, _portfolio, _review


@pytest.mark.parametrize("cancel_stage", ["model", "before_save", "inside_save"])
def test_repeated_cancel_preserves_completed_result_and_retry_restores(tmp_path, monkeypatch, cancel_stage):
    db = tmp_path / "advice.sqlite3"
    monkeypatch.setattr(ai_result_service.review_history, "resolve_review_db_path", lambda: db)
    portfolio = _portfolio()
    payload = _advice_payload()
    cfg = {"provider": "deepseek", "model": "offline-test"}
    initial = copy.deepcopy(payload)
    initial["account_action"]["reason"] = "completed-initial"
    ai_result_service.save_portfolio_advice(portfolio, _review(), initial, cfg)
    prepared = {
        "portfolio": portfolio, "daily_review": _review(), "context": {}, "messages": [],
        "input_fingerprint": ai_result_service.compute_portfolio_fingerprint(portfolio["holdings"]),
    }
    monkeypatch.setattr(service, "prepare_portfolio_advice_messages", lambda *_a: prepared)
    monkeypatch.setattr(service.portfolio_advice_validator, "validate_portfolio_advice", lambda *_a: copy.deepcopy(payload))
    monkeypatch.setattr(service, "apply_available_cash_constraints", lambda advice: advice)
    monkeypatch.setattr(service, "apply_sellable_quantity_advisory", lambda advice, _pf: advice)
    monkeypatch.setattr(service.account_reality_service, "get_account_reality", lambda: {})
    archives = []
    monkeypatch.setattr(service.decision_evidence_service, "archive_decision_evidence", lambda *_a, **_kw: archives.append("evidence"))
    monkeypatch.setattr(service.signal_ledger_service, "archive_signal_ledger", lambda *_a, **_kw: archives.append("signals"))
    original_connect = ai_result_store._connect
    current_event = threading.Event()
    cancelling = True

    def connect(path):
        conn = original_connect(path)
        if cancel_stage == "inside_save" and cancelling:
            conn.set_trace_callback(lambda sql: current_event.set() if sql.lstrip().upper().startswith("INSERT INTO AI_GENERATED_RESULTS") else None)
        return conn

    monkeypatch.setattr(ai_result_store, "_connect", connect)

    def attach(advice, *_a):
        if cancelling and cancel_stage == "before_save":
            current_event.set()
        return advice

    monkeypatch.setattr(service, "attach_account_funding_metrics", attach)

    def runner(_cfg, _messages):
        if cancelling and cancel_stage == "model":
            current_event.set()
        return json.dumps(payload)

    for _attempt in range(3):
        current_event = threading.Event()
        with pytest.raises(service.PortfolioAdviceCancelledError):
            service.generate_portfolio_advice({**cfg, "_cancel_event": current_event}, model_runner=runner)
        restored = ai_result_service.get_ai_result("portfolio_advice", trade_date="2026-07-23", current_portfolio=portfolio)
        assert restored["payload"]["account_action"]["reason"] == "completed-initial"
        assert archives == []

    cancelling = False
    current_event = threading.Event()
    service.generate_portfolio_advice({**cfg, "_cancel_event": current_event}, model_runner=runner)
    restored = ai_result_service.get_ai_result("portfolio_advice", trade_date="2026-07-23", current_portfolio=portfolio)
    assert restored["payload"]["account_action"]["reason"] == payload["account_action"]["reason"]
    assert archives == ["evidence", "signals"]


def test_actual_asgi_disconnect_reaches_running_model_before_save(monkeypatch):
    started = threading.Event()
    observed = threading.Event()
    deliveries = []
    writes = []
    monkeypatch.setattr(app_module, "_require_llm_ready", lambda _cfg: None)
    monkeypatch.setattr(service, "prepare_portfolio_advice_messages", lambda *_a: {"messages": [], "context": {}})

    def model(cfg, _messages):
        started.set()
        assert cfg["_cancel_event"].wait(2), "The application did not consume http.disconnect"
        observed.set()
        raise RuntimeError("synthetic model transport stopped")

    monkeypatch.setattr(service, "_default_model_runner", model)
    monkeypatch.setattr(service.ai_result_service, "save_portfolio_advice", lambda *_a, **_kw: writes.append("save"))
    body = json.dumps({"llm": {"provider": "deepseek", "model": "test", "apiKey": "offline", "baseURL": "http://example.test/v1"}}).encode()

    async def exercise():
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            while not started.is_set():
                await asyncio.sleep(0.001)
            deliveries.append("http.disconnect")
            return {"type": "http.disconnect"}

        async def send(_message):
            pass

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "POST", "scheme": "http",
            "path": "/api/portfolio/advice", "raw_path": b"/api/portfolio/advice",
            "query_string": b"", "root_path": "", "state": {},
            "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            "client": ("127.0.0.1", 12345), "server": ("testserver", 80),
        }
        await asyncio.wait_for(app_module.app(scope, receive, send), timeout=3)

    asyncio.run(exercise())
    assert deliveries == ["http.disconnect"]
    assert observed.is_set()
    assert writes == []


@pytest.mark.parametrize("archive", [decision_evidence_service.archive_decision_evidence, signal_ledger_service.archive_signal_ledger])
@pytest.mark.parametrize("has_completed_archive", [False, True])
def test_archive_cancel_inside_transaction_rolls_back_without_failed_trace(tmp_path, monkeypatch, archive, has_completed_archive):
    db = tmp_path / "trace.sqlite3"
    payload = _advice_payload()
    decision_trace_store.init_db(db)
    if has_completed_archive:
        archive(payload, db_path=db)

    def snapshot():
        with sqlite3.connect(db) as conn:
            return {
                table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("decision_runs", "evidence_items", "explanation_items", "signal_entries", "decision_outcomes")
            }

    before = snapshot()
    event = threading.Event()
    original_connect = decision_trace_store._get_write_connection

    def connect(path):
        conn = original_connect(path)
        conn.set_trace_callback(lambda sql: event.set() if sql.lstrip().upper().startswith("INSERT INTO DECISION_RUNS") else None)
        return conn

    monkeypatch.setattr(decision_trace_store, "_get_write_connection", connect)
    cancelled = copy.deepcopy(payload)
    cancelled["account_action"]["reason"] = "cancelled-replacement"
    result = archive(cancelled, db_path=db, should_cancel=event.is_set)
    assert event.is_set()
    assert result["status"] == "cancelled"
    assert snapshot() == before
