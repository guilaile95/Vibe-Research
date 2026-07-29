"""Offline production-chain integration: generate → evidence → signal ledger → SQLite."""

from __future__ import annotations

import json
from pathlib import Path

import decision_evidence_service
import decision_trace_store as trace_store
import portfolio_advice_service as svc
import signal_ledger_service
import signal_ledger_store
from authoritative_advice_fixtures import (
    load_golden,
    patch_account_profile,
    portfolio_data_from_context,
)


def test_production_advice_trace_integration(tmp_path, monkeypatch):
    """Full offline chain with injected model_runner and tmp DBs only."""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    db_path = tmp_path / "decision_trace.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_DECISION_TRACE_DB", str(db_path))

    import account_profile
    import portfolio as pf

    monkeypatch.setattr(account_profile, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        account_profile, "ACCOUNT_FILE", str(tmp_path / "account_profile.json")
    )
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    patch_account_profile(monkeypatch, configured=True)

    golden = load_golden("s05_reduce_high_conf_normal_input.json")
    context = golden["context"]
    ai_result = dict(golden["ai_result"])
    if not ai_result.get("trade_date"):
        ai_result["trade_date"] = (
            (context.get("market_context") or {})
            .get("review_metadata", {})
            .get("trade_date")
            or "2026-07-21"
        )
    if not ai_result.get("generated_at"):
        ai_result["generated_at"] = "2026-07-21T15:00:00"

    portfolio_data = portfolio_data_from_context(context)
    Path(tmp_path / "portfolio.json").write_text(
        json.dumps(portfolio_data, ensure_ascii=False), encoding="utf-8"
    )

    prepared = {
        "portfolio": portfolio_data,
        "input_fingerprint": "test-fingerprint",
        "daily_review": {
            "status": "normal",
            "trade_date": ai_result["trade_date"],
            "components": {},
        },
        "context": context,
        "context_json": "{}",
        "messages": [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "test"},
        ],
    }

    monkeypatch.setattr(
        svc, "prepare_portfolio_advice_messages", lambda _request=None: prepared
    )
    monkeypatch.setattr(
        svc.ai_result_service,
        "save_portfolio_advice",
        lambda *a, **k: {"trade_date": ai_result["trade_date"]},
    )

    # Wrap production archive functions to inject tmp db_path
    real_archive_evidence = decision_evidence_service.archive_decision_evidence
    real_archive_signals = signal_ledger_service.archive_signal_ledger

    def _archive_evidence(result, context_data=None, db_path=None):
        return real_archive_evidence(
            result, context_data=context_data, db_path=str(tmp_path / "decision_trace.sqlite3")
        )

    def _archive_signals(result, context_data=None, db_path=None):
        return real_archive_signals(
            result, context_data=context_data, db_path=str(tmp_path / "decision_trace.sqlite3")
        )

    monkeypatch.setattr(
        svc.decision_evidence_service, "archive_decision_evidence", _archive_evidence
    )
    monkeypatch.setattr(
        svc.signal_ledger_service, "archive_signal_ledger", _archive_signals
    )

    def model_runner(cfg, messages):
        return json.dumps(ai_result, ensure_ascii=False)

    result = svc.generate_portfolio_advice({}, model_runner=model_runner)

    assert isinstance(result, dict)
    assert "holdings" in result
    assert "account_funding" in result

    run_id = decision_evidence_service.generate_decision_run_id(
        str(result["trade_date"]), str(result["generated_at"])
    )
    bundle = trace_store.get_decision_run(run_id, db_path=db_path)
    assert bundle is not None
    assert bundle["decision_run"]["trace_status"] == "archived"
    scopes = {ev["scope"] for ev in bundle["evidence_items"]}
    assert {"account", "portfolio", "stock", "risk"}.issubset(scopes)
    account_ev = next(ev for ev in bundle["evidence_items"] if ev["scope"] == "account")
    assert account_ev["quality_status"] != "missing"

    timeline = signal_ledger_store.get_run_signal_ledger(run_id, db_path=db_path)
    stages = {e["stage"] for e in timeline["signal_entries"]}
    assert stages == set(signal_ledger_service.VALID_STAGES)
    assert len(timeline["decision_outcomes"]) == len(result["holdings"])
    outcome = timeline["decision_outcomes"][0]
    assert outcome["code"] == result["holdings"][0]["code"]
    size = result["holdings"][0].get("execution_size_pct_of_holding")
    if size is not None:
        assert abs(float(outcome["target_ratio"]) - float(size) / 100.0) < 1e-9
