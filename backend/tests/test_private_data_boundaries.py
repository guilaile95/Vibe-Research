"""A52/A53 focused acceptance: synthetic private stores and captured model sinks.

Not a provider/model test or a claim that arbitrary user-submitted text is public.
"""
from __future__ import annotations
import asyncio
import base64
import copy
import json
import socket
import threading
from pathlib import Path

import pytest
import ai_tools
import chat
import company_research
import daily_review_context
import myreports
import personal_review
import portfolio
import shortline_review_contract as C
import shortline_review_service as segmented
import shortline_review_sources as sources
import shortline_review_store as review_store
import trade_ledger_service as ledger

DAY = "2026-07-23"
CANARIES = {kind: "PRIVATE_CANARY_" + kind.upper() for kind in
            ("trade", "portfolio", "assessment", "pattern", "report", "annotation")}


def serialized(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def assert_public(value):
    text = serialized(value)
    assert all(marker not in text for marker in CANARIES.values()), text


@pytest.fixture
def privacy_event_loop():
    # Windows creates the stdlib wakeup socketpair during loop construction.
    # Construct it before private_stores installs deny-all network guards.
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


@pytest.fixture
def private_stores(tmp_path, monkeypatch, privacy_event_loop):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(tmp_path / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", str(tmp_path / "formal.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(tmp_path / "daily_reviews.sqlite3"))
    monkeypatch.setattr(portfolio, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(myreports, "REPORTS_DIR", tmp_path / "reports")
    attempts = []
    def deny(*args, **kwargs):
        attempts.append("outbound")
        raise AssertionError("outbound forbidden in privacy acceptance")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    def deny_late_loop():
        raise AssertionError("late event loop forbidden in privacy acceptance")
    monkeypatch.setattr(asyncio, "new_event_loop", deny_late_loop)
    monkeypatch.setattr(asyncio.events, "new_event_loop", deny_late_loop)
    trade = ledger.create_trade({"code": "600000", "name": CANARIES["trade"], "operation": "buy",
        "execution_status": "full", "actual_price": 10.0, "actual_quantity": 100,
        "executed_at": "2026-07-21T10:00:00+08:00", "fee": 1.0, "other_cost": 0.0})
    personal_review.save("assessment", trade["trade_id"], personal_review.Assessment(
        revision=0, note=CANARIES["assessment"], environment=CANARIES["annotation"]))
    personal_review.save("pattern", "synthetic", personal_review.Pattern(revision=0,
        name=CANARIES["pattern"], setup="synthetic", entry_rule="synthetic", exit_rule="synthetic", invalidation="synthetic"))
    Path(portfolio.PF_FILE).write_text(serialized({"holdings": [{"code": "600000", "name": CANARIES["portfolio"], "shares": 100, "cost": 10}]}))
    myreports.save_report("synthetic-private.txt", base64.b64encode(CANARIES["report"].encode()).decode())
    # Establish that canaries really exist in authoritative/local read surfaces.
    assert CANARIES["portfolio"] in serialized(portfolio._load())
    assert CANARIES["pattern"] in serialized(personal_review.history())
    assert CANARIES["assessment"] in serialized(personal_review.history())
    files = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert all(any(marker.encode() in value for value in files.values()) for marker in CANARIES.values())
    yield tmp_path, files
    assert attempts == []
    # Analysis and rejected generic operations cannot mutate existing private state.
    for path, original in files.items():
        assert path.read_bytes() == original, path.name


def forbid_private_reads(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail("public analysis attempted a private reader")
    for module, name in [(portfolio, "_load"), (personal_review, "history"),
                         (personal_review, "view"), (ledger, "list_trades"),
                         (myreports, "list_reports"), (myreports, "search_report_text")]:
        if hasattr(module, name):
            monkeypatch.setattr(module, name, deny)


def test_generic_chat_and_mcp_reject_private_read_and_managed_write_tools(private_stores, monkeypatch):
    import mcp_server
    names = [f"{verb}_{kind}" for kind in ("portfolio", "trade_ledger", "frozen_decision", "evidence_thesis", "personal_review", "pattern", "report", "annotation", "account_profile", "account_event", "position", "campaign", "formal_attribution", "ai_result", "note", "watchlist")
             for verb in ("read", "write", "update", "delete")]
    names += ["write_file", "execute_sql", "generic_crud", "save_assessment", "save_pattern"]
    assert set(ai_tools.TOOL_NAMES) == set(ai_tools._HANDLERS)
    assert set(x["name"] for x in mcp_server.MCP_TOOLS) == set(ai_tools.TOOL_NAMES)
    assert all(name.startswith("query_") for name in ai_tools.TOOL_NAMES)
    forbid_private_reads(monkeypatch)
    captured = []
    def fake_model(cfg, messages, use_tools):
        captured.append(copy.deepcopy(messages))
        if len(captured) == 1:
            return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": str(i), "function": {"name": name, "arguments": '{"path":"trade_ledger.sqlite3","value":"attempted-write"}'}}
                for i, name in enumerate(names)]}}]}
        return {"choices": [{"message": {"role": "assistant", "content": "Rejected unavailable tools"}}]}
    monkeypatch.setattr(chat, "_call_llm", fake_model)
    result = chat.run_chat({}, [{"role": "user", "content": "Public market research"}])
    assert len(result["trace"]) == len(names)
    replies = []
    monkeypatch.setattr(mcp_server, "_result", lambda rid, result: replies.append(result))
    for name in names:
        assert "error" in ai_tools.exec_tool(name, {"kind": "trade_ledger"})
        mcp_server._handle({"id": 1, "method": "tools/call", "params": {"name": name, "arguments": {}}})
    assert all(row["isError"] for row in replies)
    assert_public(captured)
    assert_public(replies)


def test_daily_public_context_excludes_private_object_roots(private_stores, monkeypatch):
    forbid_private_reads(monkeypatch)
    review = {"schema_version": "synthetic", "trade_date": DAY, "status": "partial",
              "market_environment": {"indices": {"data": [{"name": "Public index", "value": 100}]}},
              **{kind: {"note": marker} for kind, marker in CANARIES.items()}}
    monkeypatch.setattr(chat.daily_review, "generate_daily_review", lambda: review)
    prepared = chat.prepare_daily_review_analysis()
    assert "Public index" in prepared["context_json"]
    assert_public(prepared["messages"])
    assert_public(daily_review_context.build_daily_review_ai_context(review))


@pytest.mark.parametrize("mode,expected_calls", [("daily", 6), ("weekly", 4)])
def test_segmented_actual_sources_and_all_model_sinks_exclude_private_state(private_stores, monkeypatch, mode, expected_calls):
    forbid_private_reads(monkeypatch)
    private = {"portfolio": {"name": CANARIES["portfolio"]}, "trades": [{"name": CANARIES["trade"]}],
               "account": {"name": CANARIES["assessment"]}, "reason": CANARIES["annotation"]}
    def query(module, name, day):
        if module == "shortline_research_service":
            return {"schema_version": "shortline-research.v1", "trade_date": day, "status": "normal",
                    "point_in_time_claim": "NONE", "selection_mode": "CURRENT_STORED_POSTHOC", "research_only": True,
                    "fixture": True, "projection": {"daily": {"count": 5, **private}, "cohort": {"count": 1}}, **private}
        if module == "short_term_theme_research_service":
            return {"schema_version": "short-term-theme-research-archive-v1", "trade_date": day, "status": "complete",
                    "point_in_time_claim": "NONE", "selection_mode": "CURRENT_STORED_POSTHOC", "archive_only": True,
                    "ingestion_enabled": False, "projection": {"canonical_authority": False, "fixture": True,
                    "tree": [{"tag": "Public theme", "count": 2, **private}], "days": []}, **private}
        if module == "shortline_review_supplement":
            return {key: {"trade_date": day, "status": "normal", "identity": "a"*64, "fixture": True,
                          "data": {"count": 1, **private}} for key in ("capital_extra", "dragon_tiger")}
        if module == "next_day_verification":
            return {"trade_date": day, "items": [{"metric": "limit_up_count", "direction": "up", "current_value": 5,
                    "prior_value": 4, "actual": "up", "state": "VERIFIED", "target_date": day, "verified": True, **private}], **private}
        pytest.fail("unexpected data source " + module)
    monkeypatch.setattr(sources, "_query", query)
    monkeypatch.setattr(review_store, "read_daily_snapshot", lambda day: {"payload_hash": "b"*64,
        "review": {"status": "normal", "capital_activity": {"count": 3, **private}, "market_environment": {"indices": []}, **private}})
    bundle = sources.build_bundle(DAY, mode, dates=lambda *_: [DAY])
    captured = []
    def model(cfg, messages, **kwargs):
        assert kwargs == {"use_tools": False}
        captured.append(copy.deepcopy(messages))
        body = json.loads(messages[-1]["content"])
        yield {"type": "delta", "text": "Public evidence only [" + body["evidence"][0]["id"] + "]"}
        yield {"type": "done"}
    events = list(segmented.generate(bundle, ("a" if mode == "daily" else "b")*32,
                                    {"model": "synthetic"}, threading.Event(), stream=model))
    assert events[-1]["type"] == "done"
    assert len(captured) == expected_calls
    assert_public(bundle)
    assert_public(captured)


@pytest.mark.parametrize("market,symbol", [("A", "600519"), ("HK", "00700"), ("US", "AAPL")])
def test_sixstage_actual_public_adapter_plan_has_no_private_reads(private_stores, privacy_event_loop, monkeypatch, market, symbol):
    forbid_private_reads(monkeypatch)
    for name in ("individual_info", "financials", "full_valuation", "announcements", "lockup_expiry"):
        monkeypatch.setattr(company_research.astock, name, lambda *args, **kwargs: {"code": "600519", "date": DAY, "value": 10})
    monkeypatch.setattr(company_research.astock, "tencent_quote", lambda *_: {"600519": {"code": "600519", "date": DAY, "value": 10}})
    monkeypatch.setattr(company_research.gstock, "us_hk_stock", lambda *_: {"market": market, "code": symbol, "date": DAY, "value": 10})
    monkeypatch.setattr(company_research.gstock, "hk_cashflow", lambda *_: {"code": symbol, "date": DAY, "value": 10})
    bundle = company_research.capture(market, symbol)
    captured = []
    async def model(cfg, messages, **kwargs):
        captured.append(copy.deepcopy(messages))
        body = json.loads(messages[-1]["content"])
        yield {"type": "delta", "text": json.dumps({"stage": body["stage"], "summary": "Public research", "evidence_ids": [row["evidence_id"] for row in body["SOURCE_DATA"] if row["status"] == "AVAILABLE"], "gaps": ["Synthetic only"]})}
        yield {"type": "done"}
    async def run():
        return [e async for e in company_research.generate(bundle, {"provider": "api", "model": "synthetic"}, threading.Event(), stream=model)]
    events = privacy_event_loop.run_until_complete(run())
    assert events[-1]["type"] == "done"
    assert len(captured) == 6
    assert_public(bundle)
    assert_public(captured)


def test_private_pipeline_cannot_create_an_unguarded_second_loop(private_stores):
    for factory in (asyncio.new_event_loop, asyncio.events.new_event_loop):
        with pytest.raises(AssertionError, match="late event loop forbidden"):
            factory()
