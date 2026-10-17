"""Offline tests for reconstructed bounded comparison production paths.

All inputs are synthetic committed CompanyResearch fixtures. The optional
COMPANY_COMPARISON_GOLDEN_DIR writes only responses actually observed through
the registered production router/service, never hand-authored accepted records.
"""
from __future__ import annotations

import asyncio
import copy
import ipaddress
import itertools
import json
import os
import socket
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import anyio
import httpx
import pytest
import requests
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

import app
import chat
import company_comparison as C
import company_comparison_router as router
import company_research as R
import company_research_router

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = "2026-09-30"
FIXED_NOW = "2026-10-13T12:00:00.000000Z"
CONFIG = {"provider": "deepseek", "model": "offline-fixture",
          "baseURL": "https://fixture.example/v1", "apiKey": "synthetic-only"}
REAL_STREAM = chat.stream_api_messages


def deny(*args, **kwargs):
    raise AssertionError("offline test attempted network, capture or live provider access")


def _literal_loopback(host):
    try:
        return isinstance(host, str) and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(C, "_ACTIVE", threading.BoundedSemaphore(2))
    # Windows Proactor loops may construct a numeric loopback socketpair.
    # Permit only this literal local plumbing, never hostname resolution.
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    real_create = socket.create_connection

    def allowed(sock, address):
        return (sock.family == getattr(socket, "AF_UNIX", object()) or
                isinstance(address, tuple) and _literal_loopback(address[0]))

    def connect(sock, address):
        if not allowed(sock, address):
            return deny()
        return real_connect(sock, address)

    def connect_ex(sock, address):
        if not allowed(sock, address):
            return deny()
        return real_connect_ex(sock, address)

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if not _literal_loopback(host):
            return deny()
        return real_getaddrinfo(host, port, family, type, proto, flags | socket.AI_NUMERICHOST)

    def create(address, *args, **kwargs):
        if not isinstance(address, tuple) or not _literal_loopback(address[0]):
            return deny()
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create)
    for name in ("gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
        monkeypatch.setattr(socket, name, deny)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny)
    monkeypatch.setattr(requests.Session, "request", deny)
    monkeypatch.setattr(R, "capture", deny)
    monkeypatch.setattr(R, "source_plan", deny)
    monkeypatch.setattr(chat, "_PUBLIC_MODE", False)
    monkeypatch.setattr(chat, "stream_api_messages", good_stream)


def load_bundle(name):
    value = json.loads((FIXTURES / "company_research" / f"{name}.json").read_text(encoding="utf-8"))
    return R.validate_bundle(value["bundle"])


def rehash(bundle):
    bundle["bundle_sha256"] = R.digest({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    return bundle


def seed_pair(variant=""):
    first = load_bundle("US-AAPL" + ("-failed-quote" if variant else ""))
    second = load_bundle("HK-00700")
    # Independent baseline fixtures reuse UUID counters. A pair must not.
    second["bundle_id"] = uuid.UUID(int=100).hex
    rehash(second)
    for bundle in (first, second):
        R.validate_bundle(bundle)
    with R._connect(True) as conn:
        for bundle in (first, second):
            conn.execute("INSERT INTO bundles VALUES(?,?,?)",
                         (bundle["bundle_id"], bundle["bundle_sha256"], R.canonical(bundle)))
    return [first, second]


@pytest.fixture
def pair():
    return seed_pair()


def registered_app():
    api = FastAPI()
    api.include_router(router.router)
    api.include_router(company_research_router.router)
    api.add_exception_handler(RequestValidationError, app._validation_handler)
    return api


@pytest.fixture
def client():
    with TestClient(registered_app()) as value:
        yield value


def refs(bundles):
    return [{**b["subject"], "bundle_id": b["bundle_id"],
             "expected_bundle_sha256": b["bundle_sha256"]} for b in bundles]


def request_body(bundles):
    return {"subjects": refs(bundles), "as_of": AS_OF,
            "confirm_model_calls": True, "llm": dict(CONFIG)}


def good_output(context):
    result = []
    for subject, ledger in zip(context["subjects"], context["evidence"]):
        result.append({**{key: subject[key] for key in ("market", "symbol")},
                       "summary": "Synthetic archived company evidence supports a limited qualitative draft.",
                       "citations": [{**{key: subject[key] for key in ("market", "symbol")},
                                      "evidence_id": row["evidence_id"]}
                                     for row in ledger["sources"] if row["status"] == "AVAILABLE"],
                       "missingness": ["Some sources are missing or unqualified."]
                                     if any(row["status"] != "AVAILABLE" for row in ledger["sources"]) else [],
                       "caveats": ["Current archived evidence is not historical point in time truth; units remain unverified."]})
    return {"subjects": result}


async def good_stream(cfg, messages, *, limits):
    assert limits.max_tokens == 2500
    assert limits.timeout == C.MODEL_SECONDS
    assert limits.body_bytes == 128 * 1024
    assert limits.line_bytes == 64 * 1024
    assert limits.text_chars == C.MAX_OUTPUT_BYTES
    assert limits.cleanup_grace == C.CLEANUP_SECONDS
    context = json.loads(messages[-1]["content"])
    yield {"type": "delta", "text": R.canonical(good_output(context))}
    yield {"type": "done"}


async def collect(bundles, stream=None, cancelled=None, cfg=None):
    return [event async for event in C.generate(
        bundles, AS_OF, cfg or CONFIG, cancelled or threading.Event(), stream=stream)]


def events(response):
    assert response.status_code == 200, response.text
    assert "application/x-ndjson" in response.headers["content-type"]
    return [json.loads(line) for line in response.text.splitlines()]


def test_registered_success_and_restore_use_frozen_pair_without_current_bundles(pair, client, monkeypatch):
    calls = []
    async def counted(*args, **kwargs):
        calls.append(1)
        async for event in good_stream(*args, **kwargs):
            yield event
    monkeypatch.setattr(chat, "stream_api_messages", counted)
    result = events(client.post("/api/company-comparison/generate", json=request_body(pair)))
    assert [e["type"] for e in result] == ["run_started", "done"]
    assert result[0]["max_model_calls"] == 1 and len(calls) == 1
    record = result[-1]["record"]
    assert record["subjects"] == refs(pair)
    assert record["evidence"] == C.evidence_ledger(pair)
    assert record["numeric_ranking"] == "NOT_PERFORMED"
    assert record["comparability"] == "NOT_ESTABLISHED"
    assert record["numeric_claim_verification"] == "NOT_EVALUATED"
    assert CONFIG["apiKey"] not in R.canonical(record)
    assert "baseURL" not in R.canonical(record)
    with R._connect(True) as conn:
        conn.execute("DELETE FROM bundles")
    monkeypatch.setattr(R, "read_bundle", deny)
    assert client.get("/api/company-comparison/runs").json() == {"data": [record]}
    assert client.get(f"/api/company-comparison/runs/{record['run_id']}").json() == {"data": record}
    with C._snapshot() as conn:
        assert conn.execute("SELECT count(*) FROM pairs").fetchone()[0] == 1
        assert CONFIG["apiKey"] not in conn.execute("SELECT payload FROM runs").fetchone()[0]


def test_empty_reads_do_not_initialize_stores(client):
    assert client.get("/api/company-comparison/runs").json() == {"data": []}
    assert client.get("/api/company-comparison/bundles", params={"market": "US", "symbol": "AAPL", "as_of": AS_OF}).json() == {"data": []}
    assert not C.db_path().exists() and not R.db_path().exists()


@pytest.mark.parametrize("path", [
    "/api/company-comparison/runs?limit=1",
    "/api/company-comparison/runs/" + "0" * 32 + "?live=1",
    "/api/company-comparison/bundles?market=US&symbol=AAPL&as_of=2026-09-30&live=1",
    "/api/company-comparison/bundles?market=US&symbol=AAPL&as_of=2026-09-30&symbol=AAPL",
    "/api/company-comparison/bundles?market=US&market=US&symbol=AAPL&as_of=2026-09-30",
    "/api/company-comparison/bundles?market=US&symbol=AAPL&as_of=2026-09-30&as_of=2026-09-30",
])
def test_read_query_keys_and_multiplicity_are_exact(client, path):
    response = client.get(path)
    assert response.status_code == 422
    assert response.json()["detail"] == "COMPARISON_QUERY_INVALID"


def test_selector_is_exact_bounded_validated_and_independent_of_completed_runs(pair, client):
    with R._connect(True) as conn:
        for number in range(201, 225):
            b = copy.deepcopy(pair[0])
            b["bundle_id"] = uuid.UUID(int=number).hex
            rehash(b)
            conn.execute("INSERT INTO bundles VALUES(?,?,?)", (b["bundle_id"], b["bundle_sha256"], R.canonical(b)))
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    result = client.get("/api/company-comparison/bundles", params={"market": "US", "symbol": "AAPL", "as_of": AS_OF})
    assert result.status_code == 200
    rows = result.json()["data"]
    assert len(rows) == 20
    assert all(set(row) == {"market", "symbol", "bundle_id", "bundle_sha256", "archive_cutoff", "captured_at",
                            "available_source_count", "missing_source_count", "limitations"} for row in rows)
    assert client.get("/api/company-comparison/bundles", params={"market": "US", "symbol": "AAPL", "as_of": "2026-09-29"}).json() == {"data": []}
    with R._connect(True) as conn:
        conn.execute("UPDATE bundles SET hash=? WHERE id=?", ("f" * 64, rows[0]["bundle_id"]))
    assert client.get("/api/company-comparison/bundles", params={"market": "US", "symbol": "AAPL", "as_of": AS_OF}).status_code == 409


@pytest.mark.parametrize("change,status", [
    ("budget", 400), ("cli", 400), ("extra", 422), ("count", 422),
    ("subject", 409), ("hash", 409), ("cutoff", 409), ("same_subject", 409),
    ("same_bundle", 409), ("invalid_day", 409), ("secret_metadata", 409),
])
def test_generation_preflight_never_calls_model_or_initializes_store(pair, client, monkeypatch, change, status):
    monkeypatch.setattr(chat, "stream_api_messages", deny)
    body = request_body(pair)
    if change == "budget": body["confirm_model_calls"] = False
    if change == "cli": body["llm"]["provider"] = "cli-codex"
    if change == "extra": body["retry"] = True
    if change == "count": body["subjects"] = body["subjects"][:1]
    if change == "subject": body["subjects"][0]["symbol"] = "MSFT"
    if change == "hash": body["subjects"][0]["expected_bundle_sha256"] = "f" * 64
    if change == "cutoff": body["as_of"] = "2026-09-29"
    if change == "same_subject": body["subjects"][1].update(market="US", symbol="aapl")
    if change == "same_bundle": body["subjects"][1]["bundle_id"] = body["subjects"][0]["bundle_id"]
    if change == "invalid_day": body["as_of"] = "2026-02-30"
    if change == "secret_metadata": body["llm"]["model"] = CONFIG["apiKey"]
    response = client.post("/api/company-comparison/generate", json=body)
    assert response.status_code == status, response.text
    assert CONFIG["apiKey"] not in response.text
    assert not C.db_path().exists()


def test_cli_direct_service_is_rejected_without_fallback(pair):
    with pytest.raises(ValueError, match="API_RUNTIME_REQUIRED"):
        asyncio.run(collect(pair, cfg={**CONFIG, "provider": " cli-codex "}))
    assert not C.db_path().exists()


@pytest.mark.parametrize("change", ["receipt_cutoff", "after_cutoff", "source_hash", "bundle_hash", "missing_cutoff", "duplicate_id"])
def test_rehashed_bundle_invalid_receipts_never_reach_model(pair, change):
    bundle = pair[0]
    row = next(s for s in bundle["sources"] if s["evidence_id"] == "global_quote_ref")
    if change == "receipt_cutoff": row["payload"]["as_of"] = "2026-09-29"
    if change == "after_cutoff": row["payload"]["block"]["rows"][0]["after_requested_date"] = True
    if change in {"receipt_cutoff", "after_cutoff"}: row["payload_sha256"] = R.digest(row["payload"])
    if change == "source_hash": row["payload_sha256"] = "f" * 64
    if change == "missing_cutoff": bundle.pop("archive_cutoff")
    if change == "duplicate_id": bundle["sources"].append(copy.deepcopy(row))
    rehash(bundle)
    if change == "bundle_hash": bundle["bundle_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        asyncio.run(collect(pair, stream=deny))
    assert not C.db_path().exists()


def test_capture_after_cutoff_is_not_rejected_as_historical_pit(pair):
    assert all(bundle["captured_at"][:10] > AS_OF for bundle in pair)
    result = asyncio.run(collect(pair))
    assert result[-1]["type"] == "done"


def test_missing_source_payload_is_redacted_and_ledger_retains_missingness():
    pair = seed_pair("missing")
    p = C.make_pair(pair, AS_OF)
    messages = C.comparison_messages(pair, p)
    context = json.loads(messages[-1]["content"])
    rows = context["SOURCE_DATA"][0]["SOURCE_DATA"]
    assert all(row["payload"] is None for row in rows if row["status"] != "AVAILABLE")
    record = asyncio.run(collect(pair))[-1]["record"]
    assert record["output"]["subjects"][0]["missingness"]
    ledger = record["evidence"][0]["sources"]
    assert next(row for row in ledger if row["evidence_id"] == "global_quote_ref")["status"] == "ERROR"


def test_fixture_flag_requires_immutable_archive_and_exact_boolean(pair):
    source = pair[0]["sources"][0]
    source["source"] = "custom_fixture_source"
    source["payload"] = {"block": {"fixture": True}}
    assert C.evidence_ledger(pair)[0]["sources"][0]["fixture"] is False
    source["source"] = "immutable_public_source_archive"
    source["payload"]["block"]["fixture"] = "true"
    assert C.evidence_ledger(pair)[0]["sources"][0]["fixture"] is False
    source["payload"]["block"]["fixture"] = True
    assert C.evidence_ledger(pair)[0]["sources"][0]["fixture"] is True


@pytest.mark.parametrize("change", ["cross_citation", "unknown_citation", "duplicate_citation", "no_citation",
                                   "order", "no_caveat", "extra", "number", "currency", "ranking",
                                   "long_summary", "long_array", "long_item"])
def test_output_strict_schema_pair_citations_and_syntax(pair, change):
    p = C.make_pair(pair, AS_OF)
    output = good_output(p)
    item = output["subjects"][0]
    if change == "cross_citation": item["citations"][0].update(market="HK", symbol="00700")
    if change == "unknown_citation": item["citations"][0]["evidence_id"] = "unknown"
    if change == "duplicate_citation": item["citations"].append(copy.deepcopy(item["citations"][0]))
    if change == "no_citation": item["citations"] = []
    if change == "order": output["subjects"].reverse()
    if change == "no_caveat": item["caveats"] = []
    if change == "extra": item["score"] = 1
    if change == "number": item["summary"] = "Revenue is １００."
    if change == "currency": item["summary"] = "Revenue is $unknown."
    if change == "ranking": item["summary"] = "Company is better."
    if change == "long_summary": item["summary"] = "a" * 3501
    if change == "long_array": item["caveats"] = ["Unknown"] * 21
    if change == "long_item": item["missingness"] = ["a" * 501]
    with pytest.raises(ValueError):
        C.validate_output(output, p)


def test_ordinary_chinese_prose_passes_without_semantic_verification_claim(pair):
    p = C.make_pair(pair, AS_OF)
    output = good_output(p)
    output["subjects"][0]["summary"] = "一般经营信息需要统一核验，三星与三一只是名称示例。"
    C.validate_output(output, p)
    # The filter is syntactic. Spelled quantities must not acquire a verified label.
    output["subjects"][0]["summary"] = "营收一亿元，数据仍需人工核验。"
    C.validate_output(output, p)
    assert asyncio.run(collect(pair))[-1]["record"]["numeric_claim_verification"] == "NOT_EVALUATED"


def test_missingness_required_when_sources_unavailable():
    pair = seed_pair("missing")
    p = C.make_pair(pair, AS_OF)
    output = good_output(p)
    output["subjects"][0]["missingness"] = []
    with pytest.raises(ValueError, match="MISSINGNESS"):
        C.validate_output(output, p)


@pytest.mark.parametrize("mode", ["invalid_json", "duplicate_json", "nan", "incomplete", "extra_event",
                                 "tool", "oversize", "exception", "secret", "escaped_secret"])
def test_invalid_provider_output_is_failed_once_no_partial_saved(pair, mode):
    calls = []
    async def broken(cfg, messages, *, limits):
        calls.append(1)
        output = good_output(json.loads(messages[-1]["content"]))
        raw = R.canonical(output)
        if mode == "invalid_json": raw = "not json"
        if mode == "duplicate_json": raw = '{"subjects":[],"subjects":[]}'
        if mode == "nan": raw = '{"subjects":NaN}'
        if mode == "oversize": raw = "a" * (C.MAX_OUTPUT_BYTES + 1)
        if mode in {"secret", "escaped_secret"}:
            output["subjects"][0]["summary"] = CONFIG["apiKey"]
            raw = R.canonical(output)
            if mode == "escaped_secret":
                raw = raw.replace("synthetic", "\\u0073ynthetic")
        if mode == "exception": raise RuntimeError("private provider URL and credential")
        if mode == "tool":
            yield {"type": "tool", "name": "forbidden"}
            return
        yield {"type": "delta", "text": raw}
        if mode != "incomplete":
            yield {"type": "done"}
        if mode == "extra_event":
            yield {"type": "delta", "text": "late"}
    result = asyncio.run(collect(pair, stream=broken))
    assert result[-1]["type"] == "error" and len(calls) == 1
    assert "private provider" not in R.canonical(result)
    assert CONFIG["apiKey"] not in R.canonical(result)
    record = C.list_runs()[0]
    assert record["status"] == "FAILED" and record["output"] is None
    assert "result_sha256" not in record


def test_byte_budget_not_just_character_count(pair):
    async def oversized(cfg, messages, *, limits):
        yield {"type": "delta", "text": "中" * (C.MAX_OUTPUT_BYTES // 2)}
        yield {"type": "done"}
    assert asyncio.run(collect(pair, stream=oversized))[-1]["type"] == "error"


def test_input_size_preflight_does_not_create_store(pair, monkeypatch):
    monkeypatch.setattr(C, "MAX_INPUT_BYTES", 10)
    with pytest.raises(ValueError, match="SIZE"):
        asyncio.run(collect(pair))
    assert not C.db_path().exists()


def test_cancel_before_start_does_not_save(pair):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect(pair, cancelled=cancelled))
    assert not C.db_path().exists()


def test_cancel_during_provider_never_saves_completed(pair):
    cancelled = threading.Event()
    closed = []
    async def model(cfg, messages, *, limits):
        try:
            cancelled.set()
            yield {"type": "delta", "text": "partial"}
        finally:
            closed.append(True)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect(pair, model, cancelled))
    assert closed == [True]
    assert C.list_runs()[0]["status"] == "CANCELLED"
    assert C.list_runs()[0]["output"] is None


def test_owner_transition_rolls_back_if_cancel_arrives_inside_transaction(pair):
    async def exercise():
        source = C.generate(pair, AS_OF, CONFIG, threading.Event())
        started = await anext(source)
        with C._snapshot() as conn:
            row = dict(conn.execute("SELECT * FROM runs WHERE id=?", (started["run_id"],)).fetchone())
        before = json.loads(row["payload"])
        changed = {**before, "status": "FAILED", "finished_at": C.now()}
        checks = iter([False, True])
        with pytest.raises(asyncio.CancelledError):
            C._terminal(started["run_id"], row["owner"], "FAILED", changed, cancelled=lambda: next(checks))
        assert C.read_run(started["run_id"]) == before
        with pytest.raises(ValueError, match="OWNER"):
            C._terminal(started["run_id"], "f" * 32, "FAILED", changed)
        await source.aclose()
        assert C.read_run(started["run_id"])["status"] == "CANCELLED"
    asyncio.run(exercise())


@pytest.mark.parametrize("shared", [False, True])
def test_stalled_success_close_is_bounded_failed_and_releases_slot(pair, monkeypatch, shared):
    monkeypatch.setattr(C, "_ACTIVE", threading.BoundedSemaphore(1))
    monkeypatch.setattr(C, "CLEANUP_SECONDS", .02 if not shared else .2)
    monkeypatch.setattr(C, "MODEL_SECONDS", .2 if not shared else .02)
    class Stalled:
        def __init__(self, messages):
            self.items = iter([{"type": "delta", "text": R.canonical(good_output(json.loads(messages[-1]["content"])))},
                               {"type": "done"}])
            self.closed = 0
        def __aiter__(self): return self
        async def __anext__(self):
            try: return next(self.items)
            except StopIteration: raise StopAsyncIteration from None
        async def aclose(self):
            self.closed += 1
            await anyio.sleep_forever()
    made = []
    def factory(cfg, messages, *, limits):
        value = Stalled(messages)
        made.append(value)
        return value
    start = time.monotonic()
    result = asyncio.run(collect(pair, factory))
    assert time.monotonic() - start < 2
    assert result[-1]["type"] == "error" and made[0].closed >= 1
    assert C.list_runs()[0]["status"] == "FAILED"
    monkeypatch.setattr(C, "MODEL_SECONDS", 90)
    monkeypatch.setattr(C, "CLEANUP_SECONDS", .5)
    assert asyncio.run(collect(pair))[-1]["type"] == "done"


def test_history_bounds_and_immutable_pair_reuse(pair):
    for _ in range(C.MAX_HISTORY + 1):
        assert asyncio.run(collect(pair))[-1]["type"] == "done"
    assert len(C.list_runs()) == C.MAX_HISTORY
    with C._snapshot() as conn:
        assert conn.execute("SELECT count(*) FROM pairs").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["cli", "future_cutoff", "ledger", "hash", "partial_output", "owner", "oversize", "pair_oversize", "trigger", "hidden_trigger"])
def test_restore_rejects_corrupt_or_rehashed_contract_violation(pair, client, change):
    record = asyncio.run(collect(pair))[-1]["record"]
    with sqlite3.connect(C.db_path()) as conn:
        if change in {"cli", "future_cutoff", "ledger", "hash", "partial_output"}:
            if change == "cli": record["model"]["provider"] = "cli-codex"
            if change == "future_cutoff":
                record["started_at"] = "2026-09-29T12:00:00Z"
                record["finished_at"] = "2026-09-29T12:01:00Z"
            if change == "ledger": record["evidence"][0]["sources"][0]["fixture"] = False
            if change == "partial_output":
                record["status"] = "FAILED"
                record.pop("result_sha256")
                conn.execute("UPDATE runs SET status='FAILED'")
            if record["status"] == "COMPLETED":
                record["result_sha256"] = C.digest({k: v for k, v in record.items() if k != "result_sha256"})
            if change == "hash": record["result_sha256"] = "f" * 64
            conn.execute("UPDATE runs SET payload=?", (C.canonical(record),))
        if change == "owner": conn.execute("UPDATE runs SET owner='bad'")
        if change == "oversize": conn.execute("UPDATE runs SET payload=?", ("x" * (C.MAX_RECORD_BYTES + 1),))
        if change == "pair_oversize": conn.execute("UPDATE pairs SET payload=?", ("x" * (C.MAX_PAIR_BYTES + 1),))
        if change == "trigger": conn.execute("CREATE TRIGGER bad AFTER INSERT ON runs BEGIN SELECT 1; END")
        if change == "hidden_trigger": conn.execute("CREATE TRIGGER sqliteevil AFTER INSERT ON runs BEGIN SELECT 1; END")
    assert client.get("/api/company-comparison/runs").status_code == 409
    assert client.get(f"/api/company-comparison/runs/{record['run_id']}").status_code == 409


def test_same_pair_cannot_overwrite_corrupt_existing_pair(pair, monkeypatch):
    asyncio.run(collect(pair))
    with sqlite3.connect(C.db_path()) as conn:
        conn.execute("UPDATE pairs SET payload=?", ("x" * (C.MAX_PAIR_BYTES + 1),))
    statements = []
    original = C._connect
    def traced(write=False):
        conn = original(write)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(C, "_connect", traced)
    result = asyncio.run(collect(pair))
    assert result[-1]["type"] == "error"
    assert any("typeof(payload)" in sql for sql in statements)
    assert not any(sql.startswith("SELECT payload FROM pairs") for sql in statements)
    with sqlite3.connect(C.db_path()) as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_malformed_schema_blocks_generation_and_history(pair):
    C.db_path().parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(C.db_path()) as conn:
        conn.execute("CREATE TABLE pairs (hash TEXT, payload TEXT)")
    assert asyncio.run(collect(pair))[-1]["type"] == "error"
    with pytest.raises(ValueError, match="SQL_SCHEMA"):
        C.list_runs()


def test_reparse_path_guard_rejects_read_and_write(pair, monkeypatch):
    C.db_path().write_bytes(b"private")
    original = C._is_link_or_reparse
    monkeypatch.setattr(C, "_is_link_or_reparse",
                        lambda path: path == C.db_path() or original(path))
    assert asyncio.run(collect(pair))[-1]["type"] == "error"
    with pytest.raises(ValueError, match="PATH"):
        C.list_runs()
    assert C.db_path().read_bytes() == b"private"


def test_network_guard_blocks_outbound_dns_connect_ex_and_http():
    with pytest.raises(AssertionError): socket.getaddrinfo("fixture.example", 443)
    with pytest.raises(AssertionError): socket.getaddrinfo("localhost", 80)
    with socket.socket() as sock:
        with pytest.raises(AssertionError): sock.connect_ex(("203.0.113.1", 443))
        with pytest.raises(AssertionError): sock.connect(("fixture.example", 443))
    with pytest.raises(AssertionError): httpx.get("https://fixture.example")
    with pytest.raises(AssertionError): requests.get("https://fixture.example")


def test_real_symlink_store_when_platform_allows(pair, tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"private")
    try:
        C.db_path().symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("OS lacks symlink privilege; unconditional reparse guard test still runs")
    with pytest.raises(ValueError, match="PATH"):
        C.list_runs()
    assert asyncio.run(collect(pair))[-1]["type"] == "error"
    assert target.read_bytes() == b"private"


def install_runtime(monkeypatch, handler):
    original = httpx.AsyncClient
    def client(*args, **kwargs):
        return original(*args, **{**kwargs, "transport": httpx.MockTransport(handler)})
    monkeypatch.setattr(chat.httpx, "AsyncClient", client)
    monkeypatch.setattr(chat, "stream_api_messages", REAL_STREAM)


class ResponseBytes(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.closed = False
    async def __aiter__(self):
        yield self.data
    async def aclose(self):
        self.closed = True


def sse_output(messages):
    output = good_output(json.loads(messages[-1]["content"]))
    chunk = {"choices": [{"delta": {"content": R.canonical(output)}}]}
    return ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode("utf-8")


def test_registered_real_chat_runtime_calls_one_no_tools_bounded_request(pair, client, monkeypatch):
    calls = []
    bodies = []
    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 2500
        assert payload["stream"] is True and "tools" not in payload
        assert request.headers["accept-encoding"] == "identity"
        body = ResponseBytes(sse_output(payload["messages"]))
        bodies.append(body)
        return httpx.Response(200, stream=body)
    install_runtime(monkeypatch, handler)
    result = events(client.post("/api/company-comparison/generate", json=request_body(pair)))
    assert result[-1]["type"] == "done" and len(calls) == 1
    assert bodies[0].closed and C.list_runs()[0]["status"] == "COMPLETED"


@pytest.mark.parametrize("boundary", ["headers", "body", "cleanup", "send_failure"])
def test_registered_asgi_disconnect_or_send_failure_closes_real_runtime(pair, monkeypatch, boundary):
    monkeypatch.setattr(C, "CLEANUP_SECONDS", .02)
    calls = []
    cleanup = []
    sent = []
    async def exercise():
        ready = asyncio.Event()
        class Body(ResponseBytes):
            async def __aiter__(self):
                if boundary == "body":
                    ready.set()
                    await anyio.sleep_forever()
                yield self.data
            async def aclose(self):
                cleanup.append(True)
                if boundary == "cleanup":
                    ready.set()
                    await anyio.sleep_forever()
                self.closed = True
        async def handler(request):
            calls.append(request)
            if boundary == "headers":
                ready.set()
                await anyio.sleep_forever()
            payload = json.loads(request.content)
            return httpx.Response(200, stream=Body(sse_output(payload["messages"])))
        install_runtime(monkeypatch, handler)
        delivered = False
        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": json.dumps(request_body(pair)).encode(), "more_body": False}
            await ready.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            sent.append(message)
            if boundary == "send_failure" and b"run_started" in message.get("body", b""):
                raise OSError("synthetic closed client")
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                 "http_version": "1.1", "method": "POST", "scheme": "http",
                 "path": "/api/company-comparison/generate",
                 "raw_path": b"/api/company-comparison/generate", "query_string": b"",
                 "root_path": "", "headers": [(b"content-type", b"application/json"), (b"host", b"testserver")],
                 "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 80)}
        with anyio.fail_after(3):
            await registered_app()(scope, receive, send)
    asyncio.run(exercise())
    assert len(calls) == (0 if boundary == "send_failure" else 1)
    if boundary in {"body", "cleanup"}:
        assert cleanup
    assert b'"type": "done"' not in b"".join(message.get("body", b"") for message in sent)
    record = C.list_runs()[0]
    assert record["status"] == "CANCELLED" and record["output"] is None
    assert C._ACTIVE.acquire(blocking=False)
    C._ACTIVE.release()


def test_cleanup_exception_still_finalizes_failure(pair):
    class BadClose:
        def __init__(self):
            self.count = 0
        def __aiter__(self): return self
        async def __anext__(self):
            if self.count:
                raise StopAsyncIteration
            self.count += 1
            return {"type": "delta", "text": "invalid"}
        async def aclose(self):
            raise RuntimeError("synthetic failed close")
    assert asyncio.run(collect(pair, lambda *a, **k: BadClose()))[-1]["type"] == "error"
    assert C.list_runs()[0]["status"] == "FAILED"


def test_cancellation_immediately_before_completed_save_rolls_back(pair, monkeypatch):
    stop = threading.Event()
    original = C._terminal
    def terminal(run_id, owner, status, record, *, cancelled=lambda: False):
        if status == "COMPLETED":
            stop.set()
        return original(run_id, owner, status, record, cancelled=cancelled)
    monkeypatch.setattr(C, "_terminal", terminal)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect(pair, cancelled=stop))
    value = C.list_runs()[0]
    assert value["status"] == "CANCELLED" and value["output"] is None
    assert "result_sha256" not in value


def _pin_golden(monkeypatch):
    numbers = itertools.count(101)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(numbers)))
    monkeypatch.setattr(C, "now", lambda: FIXED_NOW)


def _golden(name, value):
    committed = FIXTURES / "company_comparison" / name
    destination = os.environ.get("COMPANY_COMPARISON_GOLDEN_DIR")
    if committed.exists():
        assert json.loads(committed.read_text(encoding="utf-8")) == value
    elif not destination:
        pytest.fail(f"Missing registered production API golden: {name}; regenerate explicitly with offline tests")
    if destination:
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("variant", ["", "failed-quote"])
def test_registered_api_golden(monkeypatch, client, variant):
    _pin_golden(monkeypatch)
    bundles = seed_pair(variant)
    body = request_body(bundles)
    lists = []
    resolved = []
    for bundle in bundles:
        response = client.get("/api/company-comparison/bundles", params={**bundle["subject"], "as_of": AS_OF})
        assert response.status_code == 200
        lists.append(response.json()["data"])
        result = client.get(f"/api/company-research/bundles/{bundle['bundle_id']}")
        assert result.status_code == 200
        resolved.append(result.json()["data"])
    stream = events(client.post("/api/company-comparison/generate", json=body))
    assert [item["type"] for item in stream] == ["run_started", "done"]
    record = stream[-1]["record"]
    assert client.get("/api/company-comparison/runs").json() == {"data": [record]}
    assert resolved == bundles and all(len(rows) == 1 for rows in lists)
    assert CONFIG["apiKey"] not in C.canonical(record)
    value = {"fixture_only": True,
             "authority": "Registered production API with existing synthetic frozen research bundles and offline model stub",
             "request": body, "bundles": resolved, "bundle_lists": lists,
             "events": stream, "record": record}
    _golden("US-AAPL--HK-00700" + ("-failed-quote" if variant else "") + ".json", value)


def test_registered_history_states_golden(monkeypatch, client):
    _pin_golden(monkeypatch)
    bundles = seed_pair()
    stop = threading.Event()
    async def lifecycle():
        source = C.generate(bundles, AS_OF, CONFIG, stop)
        receipt = await anext(source)
        response = client.get("/api/company-comparison/runs")
        assert response.status_code == 200
        running = response.json()
        stop.set()
        await source.aclose()
        cancelled = client.get("/api/company-comparison/runs").json()
        return receipt, running, cancelled
    started, running, cancelled = asyncio.run(lifecycle())
    async def bad_model(*args, **kwargs):
        yield {"type": "delta", "text": "{}"}
        yield {"type": "done"}
    monkeypatch.setattr(chat, "stream_api_messages", bad_model)
    failed_events = events(client.post("/api/company-comparison/generate", json=request_body(bundles)))
    failed = client.get("/api/company-comparison/runs").json()
    assert running["data"][0]["status"] == "RUNNING"
    assert cancelled["data"][0]["status"] == "CANCELLED"
    assert failed_events[-1]["type"] == "error"
    assert [row["status"] for row in failed["data"]] == ["FAILED", "CANCELLED"]
    assert all(row["output"] is None for row in failed["data"])
    _golden("history-states.json", {
        "fixture_only": True,
        "authority": "Production service lifecycle and registered history API with synthetic frozen evidence; offline failed model stub",
        "request": request_body(bundles), "bundles": bundles, "run_started": started,
        "running_history": running, "cancelled_history": cancelled,
        "failed_events": failed_events, "failed_history": failed,
    })


def test_registered_empty_bundle_lists_golden(client):
    cases = []
    for market, symbol in (("US", "AAPL"), ("HK", "00700")):
        query = {"market": market, "symbol": symbol, "as_of": AS_OF}
        url = f"/api/company-comparison/bundles?market={market}&symbol={symbol}&as_of={AS_OF}"
        response = client.get(url)
        assert response.status_code == 200 and response.json() == {"data": []}
        cases.append({"url": url, "query": query, "status_code": response.status_code,
                      "response": response.json()})
    assert not C.db_path().exists() and not R.db_path().exists()
    _golden("empty-bundle-lists.json", {
        "fixture_only": True,
        "authority": "Registered production selector API against an empty temporary private store; no capture or model",
        "cases": cases,
    })


def test_cleanup_cancellation_still_finalizes_and_releases_slot(pair):
    class CancelClose:
        def __aiter__(self): return self
        async def __anext__(self): raise StopAsyncIteration
        async def aclose(self): raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect(pair, lambda *a, **k: CancelClose()))
    assert C.list_runs()[0]["status"] == "CANCELLED"
    assert C.list_runs()[0]["output"] is None
    assert C._ACTIVE.acquire(blocking=False)
    C._ACTIVE.release()


def test_shared_runtime_stopped_transport_error_preserves_owner_cancellation(pair):
    stop = threading.Event()
    async def stopped(cfg, messages, *, limits):
        stop.set()
        raise chat.ModelTransportError("synthetic runtime stopped after cleanup")
        yield  # Make this an async iterator; no provider bytes are accepted.
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect(pair, stopped, stop))
    value = C.list_runs()[0]
    assert value["status"] == "CANCELLED"
    assert value["output"] is None and "result_sha256" not in value


@pytest.mark.parametrize("cancel_owner", [False, True])
def test_held_cleanup_distinguishes_owner_cancel_from_timeout(pair, monkeypatch, cancel_owner):
    monkeypatch.setattr(C, "CLEANUP_SECONDS", .01)
    stop = threading.Event()
    calls = []
    class HeldClose:
        def __init__(self, messages):
            self.items = iter([{"type": "delta", "text": R.canonical(good_output(json.loads(messages[-1]["content"])))},
                               {"type": "done"}])
        def __aiter__(self): return self
        async def __anext__(self):
            try: return next(self.items)
            except StopIteration: raise StopAsyncIteration from None
        async def aclose(self):
            if cancel_owner:
                stop.set()
            await anyio.sleep_forever()
    def factory(cfg, messages, *, limits):
        calls.append(True)
        return HeldClose(messages)
    if cancel_owner:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(collect(pair, factory, stop))
    else:
        assert asyncio.run(collect(pair, factory, stop))[-1]["type"] == "error"
    value = C.list_runs()[0]
    assert value["status"] == ("CANCELLED" if cancel_owner else "FAILED")
    assert value["output"] is None and "result_sha256" not in value
    assert calls == [True]


def test_pair_history_filters_before_limit_and_keyset_pages(pair, client):
    wanted = asyncio.run(collect(pair))[-1]['record']
    reversed_pair = list(reversed(pair))
    for _ in range(51):
        asyncio.run(collect(reversed_pair))
    assert wanted['run_id'] not in {r['run_id'] for r in C.list_runs()}
    query = dict(first_market='US', first_symbol='AAPL', second_market='HK', second_symbol='00700', as_of=AS_OF)
    page = client.get('/api/company-comparison/runs', params=query).json()['data']
    assert page == {'records': [wanted], 'next_cursor': None}
    query.update(first_market='HK', first_symbol='00700', second_market='US', second_symbol='AAPL', limit=20)
    seen = set()
    for expected in [20, 20, 11]:
        page = client.get('/api/company-comparison/runs', params=query).json()['data']
        assert len(page['records']) == expected
        for record in page['records']:
            assert record['subjects'] == refs(reversed_pair)
            assert record['run_id'] not in seen
            seen.add(record['run_id'])
        if page['next_cursor']:
            query['before'] = page['next_cursor']
    assert len(seen) == 51 and page['next_cursor'] is None
    query['as_of'] = '2026-09-29'
    assert client.get('/api/company-comparison/runs', params=query).json()['data']['records'] == []


@pytest.mark.parametrize('extra', [{'limit':'0'}, {'limit':'51'}, {'before':'-1'}, {'before':'1.2'}, {'before':'9223372036854775808'}, {'unknown':'1'}])
def test_pair_history_rejects_invalid_bounds(client, extra):
    query = dict(first_market='US', first_symbol='AAPL', second_market='HK', second_symbol='00700', as_of=AS_OF)
    assert client.get('/api/company-comparison/runs', params={**query, **extra}).status_code in (409, 422)


@pytest.mark.parametrize('mode,category', [('timeout','TIMEOUT'), ('upstream','UPSTREAM'), ('invalid','OUTPUT_INVALID'), ('persist','PERSISTENCE')])
def test_safe_failure_categories_keep_run_identity_no_raw_errors(pair, monkeypatch, mode, category):
    secret = 'https://private.example/token=do-not-leak'
    async def stream(cfg, messages, *, limits):
        if mode == 'timeout': raise TimeoutError(secret)
        if mode == 'upstream': raise RuntimeError(secret)
        if mode == 'invalid':
            yield {'type':'delta','text':secret}
            yield {'type':'done'}
        else:
            async for event in good_stream(cfg, messages, limits=limits): yield event
    if mode == 'persist':
        monkeypatch.setattr(C, '_terminal', lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError(secret)))
    result = asyncio.run(collect(pair, stream=stream))
    assert result[-1]['category'] == category
    assert result[-1]['run_id'] == result[0]['run_id']
    assert secret not in R.canonical(result)
    stored = C.list_runs()[0]
    if mode == 'persist':
        assert stored['status'] == 'RUNNING' and stored['output'] is None
    else:
        assert stored['failure_category'] == category and stored['status'] == 'FAILED'


def test_failure_record_rejects_nonallowlisted_category(pair):
    async def failed(*args, **kwargs):
        raise RuntimeError('private')
        yield
    asyncio.run(collect(pair, stream=failed))
    with C._connect(True) as conn:
        row = conn.execute('SELECT * FROM runs').fetchone()
        record = R._json(row['payload'])
        record['failure_category'] = 'raw private detail'
        conn.execute('UPDATE runs SET payload=?', (C.canonical(record),))
    with pytest.raises(ValueError): C.list_runs()


@pytest.mark.parametrize('error', [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_real_shared_transport_timeout_has_safe_category(pair, client, monkeypatch, error):
    calls = []
    def handler(request):
        calls.append(request)
        raise error('private URL and credential', request=request)
    install_runtime(monkeypatch, handler)
    result = events(client.post('/api/company-comparison/generate', json=request_body(pair)))
    assert len(calls) == 1
    assert result[-1]['category'] == 'TIMEOUT'
    assert result[-1]['run_id'] == result[0]['run_id']
    assert 'private URL' not in R.canonical(result)
    assert C.list_runs()[0]['failure_category'] == 'TIMEOUT'


def test_configured_limits_are_frozen_metadata_not_observed_usage(pair):
    record = asyncio.run(collect(pair))[-1]['record']
    assert record['limits'] == {'max_model_calls':1, 'max_seconds':90, 'max_output_tokens':2500}
    assert not {'usage', 'cost', 'actual_tokens'} & set(record)
    assert C.read_run(record['run_id']) == record
    with C._connect(True) as conn:
        record['limits']['max_model_calls'] = 2
        conn.execute('UPDATE runs SET payload=?', (C.canonical(record),))
    with pytest.raises(ValueError): C.list_runs()


def test_registered_paged_history_browser_golden(monkeypatch, client):
    _pin_golden(monkeypatch)
    bundles = seed_pair()
    async def start_and_cancel(pair):
        stop = threading.Event()
        source = C.generate(pair, AS_OF, CONFIG, stop)
        receipt = await anext(source)
        stop.set()
        await source.aclose()
        return receipt['run_id']
    selected = [asyncio.run(start_and_cancel(bundles)) for _ in range(51)]
    other = [asyncio.run(start_and_cancel(list(reversed(bundles)))) for _ in range(51)]
    assert not set(selected) & {r['run_id'] for r in C.list_runs()}
    query = dict(first_market='US', first_symbol='AAPL', second_market='HK', second_symbol='00700', as_of=AS_OF)
    first = client.get('/api/company-comparison/runs', params=query)
    assert first.status_code == 200
    cursor = first.json()['data']['next_cursor']
    second = client.get('/api/company-comparison/runs', params={**query, 'before':cursor})
    assert second.status_code == 200
    pages = [first.json(), second.json()]
    assert [len(p['data']['records']) for p in pages] == [50, 1]
    assert [r['run_id'] for p in pages for r in p['data']['records']] == list(reversed(selected))
    assert not set(other) & {r['run_id'] for p in pages for r in p['data']['records']}
    _golden('paged-history.json', {'fixture_only':True,
        'authority':'Registered history API after 51 selected-pair cancelled runs and 51 newer reversed-pair cancelled runs; no model invocation',
        'newer_other_pair_count':51, 'selected_pair_count':51, 'query':query, 'pages':pages})


def test_registered_failure_categories_browser_golden(monkeypatch, client):
    _pin_golden(monkeypatch)
    bundles = seed_pair()
    results = {}
    for category in ['TIMEOUT', 'UPSTREAM', 'OUTPUT_INVALID', 'PERSISTENCE']:
        async def failing(cfg, messages, *, limits):
            if category == 'TIMEOUT': raise TimeoutError('private transport detail')
            if category == 'UPSTREAM': raise RuntimeError('private provider detail')
            if category == 'OUTPUT_INVALID':
                yield {'type':'delta', 'text':'{}'}
                yield {'type':'done'}
            else:
                async for event in good_stream(cfg, messages, limits=limits): yield event
        with monkeypatch.context() as patch:
            patch.setattr(chat, 'stream_api_messages', failing)
            if category == 'PERSISTENCE':
                def failed_save(*args, **kwargs): raise sqlite3.OperationalError('private database detail')
                patch.setattr(C, '_terminal', failed_save)
            result = events(client.post('/api/company-comparison/generate', json=request_body(bundles)))
        assert result[-1]['category'] == category and result[-1]['run_id'] == result[0]['run_id']
        assert 'private' not in C.canonical(result)
        results[category] = result
    _golden('failure-categories.json', {'fixture_only':True,
        'authority':'Registered generation API with offline synthetic transport/output/persistence faults; no real model invocation',
        'request':request_body(bundles), 'events':results})
