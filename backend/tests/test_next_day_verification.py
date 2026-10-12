"""Focused synthetic journal/HTTP tests: temp data, no network or models."""
import asyncio
from datetime import datetime, timezone
import json
import socket
import sqlite3

from fastapi import FastAPI
import httpx
import pytest

import next_day_verification as svc
import next_day_verification_router as router
import short_term_fact_store as facts
import trade_calendar
from test_short_term_fact_store import _envelope

DAY = "2026-07-31"
OPEN = "2026-07-31T08:00:00+00:00"
BEFORE = "2026-08-03T01:14:59.999999+00:00"
SEAL = "2026-08-03T01:15:00+00:00"
CLOSED = "2026-08-03T07:10:00+00:00"


def instant(value):
    return datetime.fromisoformat(value)


@pytest.fixture(autouse=True)
def guarded(monkeypatch, tmp_path):
    # Windows-compatible: construct stdlib wakeup sockets before network denial.
    loop = asyncio.new_event_loop()
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    clock = [instant(OPEN)]
    monkeypatch.setattr(svc, "_now", lambda: clock[0])
    def deny(*args, **kwargs):
        raise AssertionError("network prohibited")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(asyncio, "new_event_loop", deny)
    monkeypatch.setattr(asyncio.events, "new_event_loop", deny)
    app = FastAPI()
    app.include_router(router.router)
    async def call(method, path, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.request(method, path, json=body)
    try:
        yield clock, lambda method, path, body=None: loop.run_until_complete(call(method, path, body))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


def body(direction="up", revision=0):
    return svc.SavePlan(revision=revision, items=[svc.Condition(metric="limit_up_count", direction=direction, reason="synthetic")])


def seed(monkeypatch, day=DAY, count=40, rate=0.25, stored=None, **patch):
    at = f"{day}T07:10:00+00:00"
    env = _envelope(day, fetched_at=at, snapshot_at=at)
    env["sections"]["facts"].update({"trade_date": day, "session": "final", "is_final": True,
        "source_ids": ["synthetic"], "fetched_at": at, "snapshot_at": at,
        "facts": {"limit_up_count": count, "failed_board_rate": rate}})
    env.update(patch)
    monkeypatch.setattr(facts, "_utc_now", lambda: stored or at)
    facts.save_daily_facts(env)
    return env


def test_calendar_weekend_holiday_and_unknown():
    assert trade_calendar.next_trade_date(DAY) == "2026-08-03"
    assert trade_calendar.next_trade_date("2026-09-30") == "2026-10-08"
    assert trade_calendar.next_trade_date("2026-12-31") is None
    assert trade_calendar.next_trade_date("2026-08-01") is None
    assert trade_calendar.next_trade_date("bad") is None


def test_get_does_not_create_any_databases(tmp_path, guarded):
    result = guarded[1]("GET", f"/api/next-day-verification/{DAY}")
    assert result.status_code == 200
    assert result.json()["data"]["items"] == []
    assert list(tmp_path.iterdir()) == []


def test_create_freezes_prior_and_missing_is_unknown(monkeypatch, guarded):
    seed(monkeypatch)
    saved = svc.replace_plan(DAY, body())
    assert saved["items"][0]["prior_value"] == 40
    assert saved["items"][0]["state"] == "PENDING_CLOSE"
    guarded[0][0] = instant(CLOSED)
    checked = svc.view(DAY)
    assert checked["items"][0]["state"] == "NO_EVIDENCE"
    assert checked["summary"] == {"total": 1, "decided": 0, "hit": 0, "unknown": 1,
        "rate": None, "coverage": 0.0, "baseline_covered": 0, "expected_rate": None, "edge": None}
    assert checked["state"] == "SEALED"


@pytest.mark.parametrize("items", [[], [{"metric": "limit_up_count", "direction": "down", "reason": "changed"}]])
def test_exact_seal_denies_update_and_delete_atomically(guarded, items):
    svc.replace_plan(DAY, body())
    before = svc.journal_path().read_bytes()
    guarded[0][0] = instant(SEAL)
    with pytest.raises(svc.VerificationError):
        svc.replace_plan(DAY, svc.SavePlan.model_validate({"revision": 1, "items": items}))
    assert svc.journal_path().read_bytes() == before
    assert svc.view(DAY)["revision"] == 1


def test_before_boundary_save_and_unchanged_preserves_time(guarded):
    saved = svc.replace_plan(DAY, body())
    guarded[0][0] = instant(BEFORE)
    again = svc.replace_plan(DAY, body(revision=1))
    assert again["items"][0]["written_at"] == saved["items"][0]["written_at"]
    with pytest.raises(svc.VerificationError, match="已改变"):
        svc.replace_plan(DAY, body("down", revision=1))
    assert svc.view(DAY)["revision"] == 2


def test_new_plan_after_seal_unknown_calendar_and_preclose_no_write(monkeypatch, guarded, tmp_path):
    guarded[0][0] = instant(SEAL)
    with pytest.raises(svc.VerificationError):
        svc.replace_plan(DAY, body())
    guarded[0][0] = instant("2026-07-31T06:59:59+00:00")
    assert svc.view(DAY)["state"] == "NOT_YET_OPEN"
    with pytest.raises(svc.VerificationError):
        svc.replace_plan(DAY, body())
    guarded[0][0] = instant(OPEN)
    monkeypatch.setattr(trade_calendar, "_load_calendar", lambda: None)
    assert svc.view(DAY)["state"] == "CALENDAR_UNKNOWN"
    with pytest.raises(svc.VerificationError):
        svc.replace_plan(DAY, body())
    assert list(tmp_path.iterdir()) == []


def test_clock_crosses_seal_during_capture_rolls_back(monkeypatch, guarded):
    svc.replace_plan(DAY, body())
    capture = svc._capture
    def crossing(*args):
        result = capture(*args)
        guarded[0][0] = instant(SEAL)
        return result
    guarded[0][0] = instant(BEFORE)
    monkeypatch.setattr(svc, "_capture", crossing)
    with pytest.raises(svc.VerificationError, match="封存"):
        svc.replace_plan(DAY, body("down", revision=1))
    assert svc.view(DAY)["items"][0]["direction"] == "up"
    assert svc.view(DAY)["revision"] == 1


def test_real_fact_adapter_rate_units_threshold_and_current_result(monkeypatch, guarded):
    seed(monkeypatch, rate=0.25)
    request = svc.SavePlan(revision=0, items=[svc.Condition(metric="failed_board_rate", direction="flat")])
    svc.replace_plan(DAY, request)
    guarded[0][0] = instant(CLOSED)
    seed(monkeypatch, "2026-08-03", rate=0.30)
    result = svc.view(DAY)
    assert result["items"][0]["verified"] is True
    assert result["items"][0]["current_value"] == 0.30
    assert result["summary"]["rate"] == 1
    seed(monkeypatch, "2026-08-03", rate=30)
    assert svc.view(DAY)["items"][0]["verified"] is None


@pytest.mark.parametrize("mutation", [
    "partial", "wrong_date", "not_final", "future_fetched", "future_snapshot", "stored_later", "nan", "boolean",
])
def test_reject_unqualified_prior_evidence(monkeypatch, mutation):
    env = seed(monkeypatch)
    if mutation == "partial": env["sections"]["facts"]["status"] = "partial"
    if mutation == "wrong_date": env["sections"]["facts"]["trade_date"] = "2026-07-30"
    if mutation == "not_final": env["sections"]["facts"]["is_final"] = False
    if mutation == "future_fetched": env["sections"]["facts"]["fetched_at"] = CLOSED
    if mutation == "future_snapshot": env["snapshot_at"] = CLOSED
    if mutation == "nan": env["sections"]["facts"]["facts"]["limit_up_count"] = float("nan")
    if mutation == "boolean": env["sections"]["facts"]["facts"]["limit_up_count"] = True
    if mutation == "stored_later": monkeypatch.setattr(facts, "_utc_now", lambda: CLOSED)
    if mutation == "nan":
        with pytest.raises(facts.FactStoreInvalidEnvelopeError):
            facts.save_daily_facts(env)
        # Simulate an externally corrupted row; reader must also fail closed.
        with sqlite3.connect(facts.resolve_db_path()) as conn:
            conn.execute("UPDATE fact_snapshots SET envelope_json=?", (json.dumps(env),))
    else:
        facts.save_daily_facts(env)
    assert svc.replace_plan(DAY, body())["items"][0]["prior_value"] is None


def test_baseline_only_prior_dates_no_gap_pairs_and_frozen_after_backfill(monkeypatch, guarded):
    days = svc._history_days(DAY)[-15:]
    for index, day in enumerate(days):
        seed(monkeypatch, day, count=index * 10)
    initial = svc.replace_plan(DAY, body())["items"][0]
    assert initial["baseline"]["samples"] == 14
    assert initial["baseline"]["rate"] == 1
    # Target observation and later source corrections do not change saved baseline.
    seed(monkeypatch, "2026-08-03", count=1)
    seed(monkeypatch, days[-2], count=999, stored=CLOSED)
    assert svc.view(DAY)["items"][0]["baseline"] == initial["baseline"]
    # New pre-seal condition excludes the later-persisted row; no gap bridging.
    changed = svc.replace_plan(DAY, body("down", revision=1))["items"][0]
    assert changed["baseline"]["samples"] == 12
    assert changed["baseline"]["rate"] == 0
    assert changed["baseline"]["possible_pairs"] == 60
    assert changed["baseline"]["coverage"] == 12 / 60


def test_api_rejects_caller_time_extra_fields_duplicates_and_alternate_writes(guarded):
    call = guarded[1]
    path = f"/api/next-day-verification/{DAY}"
    for extra in ({"written_at": OPEN}, {"now": OPEN}, {"trade_date": DAY}):
        assert call("PUT", path, {**body().model_dump(), **extra}).status_code == 422
    bad = body().model_dump(); bad["items"][0]["written_at"] = OPEN
    assert call("PUT", path, bad).status_code == 422
    bad = body().model_dump(); bad["items"] *= 2
    assert call("PUT", path, bad).status_code == 409
    assert call("GET", path + "?as_of=" + OPEN).status_code == 422
    assert call("POST", path, body().model_dump()).status_code == 405
    assert call("DELETE", path).status_code == 405
    response = call("PUT", path, body().model_dump())
    assert response.status_code == 200 and response.json()["data"]["revision"] == 1
    guarded[0][0] = instant(SEAL)
    assert call("PUT", path, {"revision": 1, "items": []}).status_code == 409


def test_corruption_not_empty_and_safe_error(guarded):
    svc.journal_path().write_bytes(b"not a database private.invalid/token")
    response = guarded[1]("GET", f"/api/next-day-verification/{DAY}")
    assert response.status_code == 503
    assert "private" not in response.text


def test_cold_fact_reader_has_no_initialization(tmp_path):
    assert facts.load_final_fact_record(DAY) is None
    assert list(tmp_path.iterdir()) == []


def test_composed_snapshot_timestamp_order(monkeypatch):
    env = seed(monkeypatch, stored="2026-07-31T07:12:00+00:00")
    env["snapshot_at"] = "2026-07-31T07:11:00+00:00"
    env["sections"]["facts"]["snapshot_at"] = env["snapshot_at"]
    facts.save_daily_facts(env)
    assert svc._fact(DAY, instant(OPEN))["values"]["limit_up_count"] == 40
    env["sections"]["facts"]["fetched_at"] = "2026-07-31T07:11:01+00:00"
    facts.save_daily_facts(env)
    assert svc._fact(DAY, instant(OPEN)) is None


@pytest.mark.parametrize("mutation", ["prior_string", "prior_bool", "prior_nan", "prior_negative", "rate_missing", "rate_invalid", "samples_invalid", "coverage_invalid", "duplicate", "written_before_close"])
def test_corrupted_payload_read_and_write_fail_closed(guarded, mutation):
    svc.replace_plan(DAY, body())
    with sqlite3.connect(svc.journal_path()) as conn:
        items = json.loads(conn.execute("SELECT payload FROM plans").fetchone()[0])
        if mutation == "prior_string": items[0]["prior_value"] = "10"
        if mutation == "prior_bool": items[0]["prior_value"] = True
        if mutation == "prior_nan": items[0]["prior_value"] = float("nan")
        if mutation == "prior_negative": items[0]["prior_value"] = -1
        if mutation == "rate_missing": del items[0]["baseline"]["rate"]
        if mutation == "rate_invalid": items[0]["baseline"]["rate"] = 2
        if mutation == "samples_invalid": items[0]["baseline"]["samples"] = "12"
        if mutation == "coverage_invalid": items[0]["baseline"]["coverage"] = 0.99
        if mutation == "duplicate": items *= 2
        if mutation == "written_before_close": items[0]["written_at"] = "2026-07-31T06:00:00+00:00"
        conn.execute("UPDATE plans SET payload=?", (json.dumps(items),))
    before = svc.journal_path().read_bytes()
    with pytest.raises(svc.JournalError): svc.view(DAY)
    with pytest.raises(svc.JournalError): svc.replace_plan(DAY, body("down", revision=1))
    assert svc.journal_path().read_bytes() == before


def test_two_writers_same_revision_only_one_commits(guarded):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    svc.replace_plan(DAY, body())
    barrier = Barrier(2)
    def save(direction):
        barrier.wait()
        try:
            svc.replace_plan(DAY, body(direction, revision=1))
            return "saved"
        except svc.VerificationError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["up", "down"]))
    assert sorted(results) == ["conflict", "saved"]
    assert svc.view(DAY)["revision"] == 2


def test_seal_rechecked_after_obtaining_lock(monkeypatch, guarded):
    svc.replace_plan(DAY, body())
    real_now = svc._now
    calls = [0]
    def advancing():
        calls[0] += 1
        return instant(BEFORE if calls[0] == 1 else SEAL)
    monkeypatch.setattr(svc, "_now", advancing)
    with pytest.raises(svc.VerificationError):
        svc.replace_plan(DAY, body("down", revision=1))
    monkeypatch.setattr(svc, "_now", real_now)
    assert svc.view(DAY)["revision"] == 1


def test_huge_provider_integer_is_unknown_not_overflow(monkeypatch):
    seed(monkeypatch, count=10 ** 400)
    result = svc.replace_plan(DAY, body())
    assert result["items"][0]["prior_value"] is None
    assert result["items"][0]["prior_evidence"]["values"]["limit_up_count"] is None


@pytest.mark.parametrize("mutation", ["prior_huge", "baseline_huge", "nested_nan", "evidence_mismatch", "evidence_future"])
def test_nested_frozen_evidence_corruption_is_safe(monkeypatch, mutation, guarded):
    seed(monkeypatch)
    svc.replace_plan(DAY, body())
    with sqlite3.connect(svc.journal_path()) as conn:
        items = json.loads(conn.execute("SELECT payload FROM plans").fetchone()[0])
        if mutation == "prior_huge": items[0]["prior_value"] = 10 ** 400
        if mutation == "baseline_huge": items[0]["baseline"]["rate"] = 10 ** 400
        if mutation == "nested_nan": items[0]["prior_evidence"]["values"]["failed_board_rate"] = float("nan")
        if mutation == "evidence_mismatch": items[0]["prior_evidence"]["values"]["limit_up_count"] = 99
        if mutation == "evidence_future": items[0]["prior_evidence"]["stored_at"] = CLOSED
        conn.execute("UPDATE plans SET payload=?", (json.dumps(items),))
    assert guarded[1]("GET", f"/api/next-day-verification/{DAY}").status_code == 503
    with pytest.raises(svc.JournalError): svc.replace_plan(DAY, body("down", revision=1))


def test_browser_golden_payloads_match_real_journal_service(monkeypatch):
    from pathlib import Path
    from next_day_verification_browser_fixture import contracts
    fixture = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/next-day-verification.json"
    assert contracts(monkeypatch) == json.loads(fixture.read_text())
