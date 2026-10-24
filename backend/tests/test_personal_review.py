"""Synthetic isolated local review tests. No providers, models or real holdings."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import socket
import sqlite3

from fastapi import FastAPI
import httpx
import pytest

import account_event_store
import personal_review as svc
import personal_review_router as router
import position_reality_service as positions
import trade_ledger_service as ledger
import trade_ledger_store


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    loop = asyncio.new_event_loop()
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(tmp_path / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", str(tmp_path / "formal.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(tmp_path / "research"))
    clock = [datetime(2026, 7, 28, 8, tzinfo=timezone.utc)]
    monkeypatch.setattr(svc, "_now", lambda: clock[0])
    def deny(*args, **kwargs):
        raise AssertionError("outbound network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    app = FastAPI()
    app.include_router(router.router)
    async def call(method, path, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.request(method, path, json=body)
    yield clock, lambda method, path, body=None: loop.run_until_complete(call(method, path, body))
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(loop.shutdown_default_executor())
    loop.close()


def bootstrap(shares=0):
    return positions.bootstrap_commit({"ledger_start_at": "2026-07-01T00:00:00+08:00", "opening_cash": 10000.0,
        "positions": [{"code": "600000", "name": "Synthetic", "shares": shares, "cost_basis": None}] if shares else []})


def trade(operation="buy", quantity=100, price=10.0, day=21, hour=10, fee=1.0):
    return ledger.create_trade({"code": "600000", "name": "Synthetic", "operation": operation, "execution_status": "full",
        "actual_quantity": quantity, "actual_price": price, "executed_at": f"2026-07-{day:02d}T{hour:02d}:00:00+08:00", "fee": fee, "other_cost": 0.0})


def pattern(revision=0, **patch):
    return svc.Pattern(revision=revision, **{"name": "Synthetic card", "setup": "Test setup", "entry_rule": "Test entry", "exit_rule": "Test exit", "invalidation": "Test invalidation", **patch})


def test_empty_read_side_effect_free(isolated, tmp_path):
    response = isolated[1]("GET", "/api/personal-review")
    assert response.status_code == 200
    assert response.json()["data"]["windows"][0]["net_pnl"] is None
    assert list(tmp_path.iterdir()) == []


def test_append_cas_history_idempotency_and_trade_unchanged(isolated):
    t = trade()
    before = ledger.resolve_db_path().read_bytes()
    first = svc.save("assessment", t["trade_id"], svc.Assessment(revision=0, stop_price=9.0, judgment="correct"))
    assert svc.save("assessment", t["trade_id"], svc.Assessment(revision=0, stop_price=9.0, judgment="correct")) == first
    isolated[0][0] = datetime(2026, 7, 29, 8, tzinfo=timezone.utc)
    second = svc.save("assessment", t["trade_id"], svc.Assessment(revision=1, stop_price=9.0, note="only note"))
    assert second["stop_recorded_at"] == first["stop_recorded_at"]
    third = svc.save("assessment", t["trade_id"], svc.Assessment(revision=2, stop_price=8.0))
    assert third["stop_recorded_at"] != first["stop_recorded_at"]
    with pytest.raises(svc.ReviewError, match="已改变"):
        svc.save("assessment", t["trade_id"], svc.Assessment(revision=1, note="lost update"))
    assert len(svc.history()["assessment"][t["trade_id"]]) == 3
    assert before == ledger.resolve_db_path().read_bytes()


def test_pattern_next_calendar_day_and_no_backfill(isolated):
    isolated[0][0] = datetime(2026, 7, 20, 8, tzinfo=timezone.utc)
    one = svc.save("pattern", "card", pattern())
    assert one["effective_from"] == "2026-07-21"
    assert svc.save("pattern", "card", pattern()) == one
    with pytest.raises(svc.ReviewError, match="每天"):
        svc.save("pattern", "card", pattern(1, entry_rule="changed"))
    old = trade(day=20)
    with pytest.raises(svc.ReviewError, match="倒填"):
        svc.save("assessment", old["trade_id"], svc.Assessment(revision=0, pattern_id="card", pattern_revision=1))
    new = trade(day=21)
    isolated[0][0] = datetime(2026, 7, 21, 8, tzinfo=timezone.utc)
    svc.save("assessment", new["trade_id"], svc.Assessment(revision=0, pattern_id="card", pattern_revision=1))
    isolated[0][0] = datetime(2026, 7, 21, 16, tzinfo=timezone.utc)  # Shanghai July 22
    two = svc.save("pattern", "card", pattern(1, entry_rule="second"))
    assert two["effective_from"] == "2026-07-23"
    later = trade(day=23)
    isolated[0][0] = datetime(2026, 7, 23, 8, tzinfo=timezone.utc)
    with pytest.raises(svc.ReviewError):
        svc.save("assessment", later["trade_id"], svc.Assessment(revision=0, pattern_id="card", pattern_revision=1))
    assert svc.history()["pattern"]["card"][0] == one
    assert svc.view()["patterns"][0]["effective_until"] == "2026-07-23"


def test_unknown_anchor_never_invents_closed_episode():
    trade(); trade("sell", price=12.0, day=22)
    v = svc.view()
    assert v["closed_episodes"] == []
    assert v["diagnostics"][0]["reason"] == "OPENING_INVENTORY_UNKNOWN"


def test_closed_partial_exits_and_reentry_reuse_canonical_pnl():
    bootstrap()
    buy = trade(quantity=200)
    trade("reduce", quantity=100, price=12.0, day=22)
    assert svc.view()["windows"][0]["closed_count"] == 0
    trade("sell", quantity=100, price=11.0, day=23)
    trade(quantity=100, price=9.0, day=24)
    trade("sell", quantity=100, price=8.0, day=27)
    v = svc.view()
    assert v["windows"][0]["closed_count"] == 2
    assert v["windows"][0]["net_pnl"] == 195.0  # 300-3, -100-2
    assert v["windows"][0]["win_rate_excluding_flat"] == .5
    assert v["windows"][0]["insufficient_samples"]
    assert v["closed_episodes"][1]["trade_ids"][0] == buy["trade_id"]


def test_legacy_opening_consumed_until_flat_then_score():
    bootstrap(100)
    trade("sell", day=21)
    trade("buy", day=22)
    trade("sell", price=12.0, day=23)
    v = svc.view()
    assert v["windows"][0]["closed_count"] == 1
    assert v["closed_episodes"][0]["net_pnl"] == 198
    assert v["diagnostics"][0]["reason"] == "LEGACY_OPENING_EPISODE_UNSCORED"


def test_same_time_opposite_side_unknown_but_split_buy_supported():
    # Both same-instant orderings must be solvent at the strict write boundary.
    # Personal review still cannot infer which side executed first.
    bootstrap(100)
    trade(); trade("sell", hour=10)
    assert svc.view()["diagnostics"][0]["reason"] == "SAME_INSTANT_ORDER_UNKNOWN"


def test_split_fills_and_flat_denominator():
    bootstrap()
    trade(quantity=50, fee=0.0); trade(quantity=50, fee=0.0)
    trade("sell", price=10.0, day=22, fee=0.0)
    w = svc.view()["windows"][0]
    assert w["flat"] == 1 and w["closed_count"] == 1 and w["win_rate_excluding_flat"] is None


def test_oversell_blocks_fabricated_completion(monkeypatch):
    bootstrap(); trade()
    before = trade_ledger_store.list_records(ledger.resolve_db_path())
    with pytest.raises(ledger.TradeReconciliationRequiredError):
        trade("sell", quantity=200, day=22)
    assert trade_ledger_store.list_records(ledger.resolve_db_path()) == before
    assert svc.view()["closed_episodes"] == []

    # New writes reject oversells. Still exercise the read-side guard for legacy
    # inconsistent history without bypassing or weakening the write validator.
    sell = {**before[0], "trade_id": "legacy-oversell", "operation": "sell",
            "actual_quantity": 200, "executed_at": "2026-07-22T10:00:00+08:00"}
    events = account_event_store.list_events(ledger.resolve_db_path())
    monkeypatch.setattr(svc, "_ledger_rows", lambda conn: ([*before, sell], events))
    v = svc.view()
    assert v["closed_episodes"] == []
    assert v["diagnostics"][0]["reason"] == "OVERSELL_OR_MISSING_HISTORY"


def test_correction_not_ignored():
    bootstrap(); t = trade(); trade("sell", day=22)
    positions.create_correction({"target_event_type": "trade", "target_event_id": t["trade_id"], "after_payload": {"actual_price": 9.0}, "reason": "Synthetic correction"})
    assert svc.view()["diagnostics"][0]["reason"] == "CORRECTED_TRADE_REQUIRES_RECONCILIATION"


def test_mixed_campaign_excluded(monkeypatch):
    bootstrap(); t = trade(); trade("sell", day=22)
    monkeypatch.setattr(svc, "_formal", lambda tid, records: {"campaign_id": "a" if tid == t["trade_id"] else "b", "decision_id": tid, "decision_committed_at": "2026-07-20T00:00:00Z", "trade_executed_at": "2026-07-21T00:00:00Z"})
    v = svc.view()
    assert v["closed_episodes"][0]["state"] == "MIXED_CAMPAIGN_UNSCORED"
    assert v["windows"][0]["closed_count"] == 0


def test_unknown_fee_not_zero(monkeypatch):
    bootstrap(); trade(); trade("sell", day=22)
    rows = trade_ledger_store.list_records(ledger.resolve_db_path())
    rows[0]["fee"] = None
    events = account_event_store.list_events(ledger.resolve_db_path())
    monkeypatch.setattr(svc, "_ledger_rows", lambda conn: (rows, events))
    e = svc.view()["closed_episodes"][0]
    assert e["fees"] is None and e["net_pnl"] is None and e["fee_coverage"] == "UNKNOWN"


def test_self_judgment_execution_separate_and_stop_risk():
    bootstrap(); t = trade()
    svc.save("assessment", t["trade_id"], svc.Assessment(revision=0, judgment="correct", execution="deviated", stop_price=9.0, violations=["Synthetic rule"]))
    assert svc.view()["risk"]["open_episodes"][0]["entry_reference_stop_scenario"] == 100
    trade("sell", day=22, price=9.0)
    v = svc.view()
    assert v["windows"][0]["self_reported_deviations"] == 1
    assert v["closed_episodes"][0]["assessment"]["content"]["judgment"] == "correct"
    assert v["closed_episodes"][0]["net_pnl"] < 0  # Self belief never becomes outcome truth.


def test_voided_trade_denied_and_no_legacy_import(isolated):
    t = trade()
    trade_ledger_store.void_record_atomic(ledger.resolve_db_path(), t["trade_id"], "Synthetic")
    assert isolated[1]("PUT", f"/api/personal-review/assessments/{t['trade_id']}", {"revision": 0}).status_code == 409
    assert isolated[1]("PUT", "/api/personal-review/patterns/card", {**pattern().model_dump(), "effective_from": "2000-01-01"}).status_code == 422
    assert isolated[1]("GET", "/api/personal-review?as_of=2000-01-01").status_code == 422


def test_corrupt_storage_fails_closed_no_repair(isolated):
    svc.save("pattern", "card", pattern())
    with sqlite3.connect(svc._path()) as conn:
        conn.execute("UPDATE revisions SET payload='{}'")
    before = svc._path().read_bytes()
    assert isolated[1]("GET", "/api/personal-review").status_code == 503
    assert isolated[1]("PUT", "/api/personal-review/patterns/card", pattern(1).model_dump()).status_code == 503
    assert svc._path().read_bytes() == before


def test_daily_range_excludes_boundary_and_split_does_not_claim_returns(monkeypatch):
    import research_data_plane as rdp
    bootstrap(); trade(day=21); trade("sell", day=24)
    episode = svc.view()["closed_episodes"][0]
    import personal_review_price_basis as basis
    monkeypatch.setattr(basis, "current_snapshot", lambda: {"snapshot_id": "synthetic"})
    captured = []
    def bars(**kwargs):
        captured.append(kwargs)
        return {"adjustment": "UNADJUSTED", "rows": [{"trade_date": "2026-07-22", "high": 10.0, "low": 9.0, "volume": 1000}, {"trade_date": "2026-07-23", "high": 5.0, "low": 4.0, "volume": 1000}], "provider_id": "synthetic", "fetched_at": "2026-07-24T08:00:00Z", "as_of": "2026-07-24", "provenance": {"source_kind": "synthetic"}}
    monkeypatch.setattr(rdp, "query_daily_bars", bars)
    x = svc.excursion(episode)
    assert x["raw_interior_low"] == 4 and x["raw_interior_high"] == 10
    assert x["mfe_pct"] is None and x["mae_pct"] is None
    assert "deviation_pct" not in json.dumps(x)
    assert captured[0]["date_from"] == "2026-07-22" and captured[0]["date_to"] == "2026-07-23"
    monkeypatch.setattr(rdp, "query_daily_bars", lambda **kw: {**bars(**kw), "rows": bars(**kw)["rows"][:1]})
    assert svc.excursion(episode)["state"] == "PRICE_COVERAGE_OR_BASIS_UNKNOWN"


def test_storage_not_registered_with_models():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for name in ("chat.py", "agent_runtime.py", "portfolio_advice_prompt.py", "native_intel_mcp.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "import personal_review" not in source
        assert "/personal-review" not in source


def basis_capture(tmp_path):
    import research_data_plane as rdp
    csv = tmp_path / "synthetic.csv"
    csv.write_text("code,trade_date,open,high,low,close,volume\n600000,2026-07-21,10,11,9,10,1000\n600000,2026-07-22,10,12,8,10,1000\n600000,2026-07-23,5,6,4,5,1000\n600000,2026-07-24,5,6,4,5,1000\n")
    manifest = rdp.import_csv(csv, imported_at="2026-07-25T00:00:00Z")
    capture = {"schema_version": "personal-review-adjustment-capture.v1", "code": "600000",
        "raw_snapshot_id": manifest["snapshot_id"], "raw_artifact_sha256": manifest["artifact_sha256"],
        "provider_id": manifest["provider_id"], "provider_revision": "synthetic-split-v1", "adjustment_basis_id": "synthetic-july24",
        "formula": "ADJUSTED_PRICE_EQUALS_RAW_TIMES_FACTOR", "price_unit": "CNY_PER_SHARE", "source_id": "synthetic-fixture-not-real-market",
        "captured_at": "2026-07-25T00:00:00Z", "rows": [{"trade_date": f"2026-07-{day}", "factor": .5 if day < 23 else 1., "provider_revision": "synthetic-split-v1", "adjustment_basis_id": "synthetic-july24"} for day in (21, 22, 23, 24)]}
    return manifest, capture


def test_qualified_adjusted_bound_full_route_split_fixture(isolated, tmp_path):
    import personal_review_price_basis as basis
    bootstrap(); trade(day=21); trade("sell", day=24, price=5.)
    manifest, capture = basis_capture(tmp_path)
    raw = json.dumps(capture)
    before = ledger.resolve_db_path().read_bytes()
    preview = isolated[1]("POST", "/api/personal-review/price-basis/preview", {"raw_json": raw})
    assert preview.status_code == 200 and not basis._path().exists()
    saved = isolated[1]("POST", "/api/personal-review/price-basis/archive", {"raw_json": raw})
    assert saved.status_code == 200
    assert basis.archive(raw) == saved.json()["data"]
    e = svc.view()["closed_episodes"][0]
    source_bytes = {p: p.read_bytes() for p in (tmp_path / "research").rglob("*") if p.is_file()}
    result = isolated[1]("GET", f"/api/personal-review/episodes/{e['episode_id']}/excursion").json()["data"]
    bound = result["adjusted_bound"]
    assert bound["bounded_mfe_pct"] == 20. and bound["bounded_mae_pct"] == -20.
    assert bound["adjusted_entry_reference"] == 5.
    assert bound["source"]["raw_snapshot_id"] == manifest["snapshot_id"]
    assert bound["excluded_boundary_dates"] == ["2026-07-21", "2026-07-24"]
    assert result["mfe_pct"] is None and result["mae_pct"] is None
    assert ledger.resolve_db_path().read_bytes() == before
    assert source_bytes == {p: p.read_bytes() for p in (tmp_path / "research").rglob("*") if p.is_file()}


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "vintage", "snapshot", "provider", "unit", "infinite", "conflicting_field"])
def test_factor_bad_bindings_and_coverage_rejected(tmp_path, mutation):
    import personal_review_price_basis as basis
    _, capture = basis_capture(tmp_path)
    if mutation == "missing": capture["rows"].pop(1)
    if mutation == "duplicate": capture["rows"].append(capture["rows"][-1])
    if mutation == "vintage": capture["rows"][0]["provider_revision"] = "other"
    if mutation == "snapshot": capture["raw_artifact_sha256"] = "0" * 64
    if mutation == "provider": capture["provider_id"] = "other"
    if mutation == "unit": capture["price_unit"] = "CNY_PER_LOT"
    if mutation == "infinite": capture["rows"][0]["factor"] = float("inf")
    raw = json.dumps(capture)
    if mutation == "conflicting_field": raw = raw.replace('"code": "600000"', '"code": "600000", "code": "000001"')
    with pytest.raises(basis.BasisError): basis.archive(raw)
    assert not basis._path().exists()


def test_factor_conflicting_same_revision_cannot_overwrite(tmp_path):
    import personal_review_price_basis as basis
    _, capture = basis_capture(tmp_path)
    basis.archive(json.dumps(capture))
    before = basis._path().read_bytes()
    capture["rows"][0]["factor"] = .49
    with pytest.raises(basis.BasisError, match="冲突"):
        basis.archive(json.dumps(capture))
    assert basis._path().read_bytes() == before


def test_scale_in_partial_exits_not_claimed_as_entry_excursion(tmp_path):
    import personal_review_price_basis as basis
    bootstrap(); trade(day=21); trade("add", day=22); trade("reduce", day=23); trade("sell", day=24)
    _, capture = basis_capture(tmp_path)
    basis.archive(json.dumps(capture))
    e = svc.view()["closed_episodes"][0]
    assert svc.excursion(e)["state"] == "COMPLEX_EPISODE_UNSUPPORTED"


def test_dividend_factor_bound_separate_from_accounting(tmp_path):
    import personal_review_price_basis as basis
    bootstrap(); trade(day=21); trade("sell", day=24, price=5.)
    _, capture = basis_capture(tmp_path)
    for row in capture["rows"]:
        row["factor"] = .98 if row["trade_date"] < "2026-07-23" else 1.
    basis.archive(json.dumps(capture))
    episode = svc.view()["closed_episodes"][0]
    before = episode["net_pnl"]
    bound = svc.excursion(episode)["adjusted_bound"]
    assert bound["adjusted_entry_reference"] == pytest.approx(9.8)
    assert bound["bounded_mae_pct"] == pytest.approx(-59.1837)
    assert svc.view()["closed_episodes"][0]["net_pnl"] == before == -502.


def test_future_trade_and_clock_rollback_denied(isolated):
    t = trade(day=29)
    with pytest.raises(svc.ReviewError, match="未来"):
        svc.save("assessment", t["trade_id"], svc.Assessment(revision=0))
    svc.save("pattern", "card", pattern())
    isolated[0][0] = datetime(2026, 7, 27, 8, tzinfo=timezone.utc)
    with pytest.raises(svc.ReviewError, match="服务器时间"):
        svc.save("pattern", "card", pattern(1, name="new"))


def test_local_weekly_summary_and_future_rows_excluded(isolated):
    bootstrap(); trade(day=21); trade("sell", day=22, price=12.)
    assert svc.view()["weekly"]["summary"]["closed_count"] == 0  # clock July 28, new week
    assert svc.view()["weekly"]["from"] == "2026-07-27"
    trade(day=27); trade("sell", day=29)
    assert svc.view()["diagnostics"][0]["reason"] == "FUTURE_EXECUTION_UNVERIFIED"
    assert svc.view()["weekly"]["summary"]["closed_count"] == 0


def test_missing_price_archive_get_does_not_create_it(isolated, tmp_path):
    bootstrap(); trade(day=21); trade("sell", day=24)
    episode = svc.view()["closed_episodes"][0]
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    response = isolated[1]("GET", f"/api/personal-review/episodes/{episode['episode_id']}/excursion")
    assert response.status_code == 200 and response.json()["data"]["state"] == "NO_EVIDENCE"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_legacy_open_inventory_remains_visible_with_unknown_risk():
    bootstrap(100)
    risk = svc.view()["risk"]["open_episodes"]
    assert len(risk) == 1 and risk[0]["remaining_quantity"] == 100
    assert risk[0]["entry_reference_stop_scenario"] is None


def test_suspended_session_not_comparable_even_with_factor(tmp_path):
    import research_data_plane as rdp
    import personal_review_price_basis as basis
    _, capture = basis_capture(tmp_path)
    csv = tmp_path / "synthetic.csv"
    csv.write_text(csv.read_text().replace("2026-07-22,10,12,8,10,1000", "2026-07-22,10,12,8,10,0"))
    manifest = rdp.import_csv(csv, imported_at="2026-07-25T00:00:00Z")
    capture.update(raw_snapshot_id=manifest["snapshot_id"], raw_artifact_sha256=manifest["artifact_sha256"])
    with pytest.raises(basis.BasisError, match="零成交"):
        basis.qualify(json.dumps(capture))


def file_identity(path):
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, path.read_bytes())


def test_checkpointed_wal_review_read_never_creates_sidecars(tmp_path):
    with sqlite3.connect(svc._path()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE revisions(kind TEXT,entity_id TEXT,revision INTEGER,payload TEXT)")
    # sqlite connection context commits but does not close; explicitly close.
    conn.close()
    before = {p.name: file_identity(p) for p in tmp_path.iterdir()}
    assert svc.history() == {"assessment": {}, "pattern": {}}
    assert {p.name: file_identity(p) for p in tmp_path.iterdir()} == before


def test_checkpointed_wal_factor_read_never_creates_sidecars(tmp_path):
    import personal_review_price_basis as basis
    _, capture = basis_capture(tmp_path)
    receipt = basis.archive(json.dumps(capture))
    conn = sqlite3.connect(basis._path()); conn.execute("PRAGMA journal_mode=WAL"); conn.close()
    before = {p.name: file_identity(p) for p in tmp_path.iterdir() if p.is_file()}
    assert basis.receipt(receipt["capture_sha256"])["capture_sha256"] == receipt["capture_sha256"]
    assert basis.find(capture["raw_snapshot_id"], "600000", "2026-07-21", "2026-07-24")
    assert {p.name: file_identity(p) for p in tmp_path.iterdir() if p.is_file()} == before


def test_pending_wal_and_symlink_sources_fail_closed(tmp_path):
    conn = sqlite3.connect(svc._path())
    conn.execute("PRAGMA journal_mode=WAL"); conn.execute("CREATE TABLE revisions(kind TEXT,entity_id TEXT,revision INTEGER,payload TEXT)"); conn.commit()
    try:
        with pytest.raises(svc.ReviewUnavailable): svc.history()
    finally: conn.close()
    original = svc._path().with_suffix(".original")
    svc._path().rename(original)
    try: svc._path().symlink_to(original)
    except OSError: pytest.skip("symlinks unavailable")
    with pytest.raises(svc.ReviewUnavailable): svc.history()


def test_personal_history_row_budget_fail_closed():
    with sqlite3.connect(svc._path()) as conn:
        conn.execute("CREATE TABLE revisions(kind TEXT,entity_id TEXT,revision INTEGER,payload TEXT)")
        conn.executemany("INSERT INTO revisions VALUES ('assessment','a',?,'{}')", [(i,) for i in range(20001)])
    conn.close()
    with pytest.raises(svc.ReviewUnavailable): svc.history()


def test_ledger_generation_drift_during_compute_is_not_published(monkeypatch, isolated):
    bootstrap(); t = trade(); trade("sell", day=22)
    compute = svc.performance._compute_attribution_from_trades
    def drifting(**kwargs):
        result = compute(**kwargs)
        with sqlite3.connect(ledger.resolve_db_path()) as conn:
            conn.execute("UPDATE trade_records SET fee=999 WHERE trade_id=?", (t["trade_id"],))
        return result
    monkeypatch.setattr(svc.performance, "_compute_attribution_from_trades", drifting)
    assert isolated[1]("GET", "/api/personal-review").status_code == 503


@pytest.mark.parametrize("timestamp", ["2026-07-25T12:00:00+01:60", "2026-07-25T12:00:00+24:00", "2026-07-25+08:00", "2026-07-25T24:00:00Z", "2026-07-25T12:60:00Z"])
def test_factor_capture_timestamp_is_strict(tmp_path, timestamp):
    import personal_review_price_basis as basis
    _, capture = basis_capture(tmp_path)
    capture["captured_at"] = timestamp
    with pytest.raises(basis.BasisError): basis.qualify(json.dumps(capture))


def test_receipt_reconciliation_absent_present_and_wrong_digest(isolated, tmp_path):
    import personal_review_price_basis as basis
    _, capture = basis_capture(tmp_path)
    raw = json.dumps(capture)
    digest = basis.qualify(raw)[2]["capture_sha256"]
    assert isolated[1]("GET", f"/api/personal-review/price-basis/receipts/{digest}").json()["data"] is None
    basis.archive(raw)
    assert isolated[1]("GET", f"/api/personal-review/price-basis/receipts/{digest}").json()["data"]["capture_sha256"] == digest
    assert isolated[1]("GET", "/api/personal-review/price-basis/receipts/not-a-hash").status_code == 409


def test_orphan_sidecar_is_not_treated_as_empty(tmp_path):
    from pathlib import Path
    Path(str(svc._path()) + "-wal").write_bytes(b"orphan")
    with pytest.raises(svc.ReviewUnavailable): svc.history()


@pytest.mark.parametrize("variant", ["unknown", "missing", "duplicate"])
def test_formal_attribution_schema_authority_preserved(isolated, variant):
    from test_trade_attribution_store_and_reconciliation import _create_attribution_schema_variant
    store = svc.attribution_store
    path = store.resolve_formal_trade_attribution_db_path()
    _create_attribution_schema_variant(path, trade_unique="none" if variant == "duplicate" else "full")
    with sqlite3.connect(path) as conn:
        if variant == "unknown": conn.execute("UPDATE schema_meta SET value='unknown-version'")
        if variant == "missing": conn.execute("DELETE FROM schema_meta")
        if variant == "duplicate":
            columns = [r[1] for r in conn.execute("PRAGMA table_info(formal_trade_attributions)")]
            for identifier in ("a", "b"):
                values = [identifier if c == "attribution_id" else 1 if c == "thesis_revision" else "same-trade" if c == "trade_id" else "synthetic" for c in columns]
                conn.execute("INSERT INTO formal_trade_attributions VALUES (" + ",".join("?" for _ in columns) + ")", values)
    before = file_identity(path)
    assert isolated[1]("GET", "/api/personal-review").status_code == 503
    assert file_identity(path) == before


def test_formal_ledger_is_read_once_with_trusted_schema_off(monkeypatch):
    bootstrap(); trade(day=21); trade("sell", day=22); trade(day=23); trade("sell", day=24)
    store = svc.attribution_store
    conn = store._initialize(store.resolve_formal_trade_attribution_db_path()); conn.close()
    original = svc._formal_map
    calls = []
    def counted(conn):
        calls.append(conn.execute("PRAGMA trusted_schema").fetchone()[0])
        return original(conn)
    monkeypatch.setattr(svc, "_formal_map", counted)
    assert len(svc.view()["closed_episodes"]) == 2
    assert calls == [0]


def test_real_service_payloads_pass_production_frontend_guards(tmp_path, isolated):
    """Full nonempty service→TypeScript parser parity; not hand-authored UI DTOs."""
    import shutil
    import subprocess
    from pathlib import Path
    import formal_trade_attribution as fta
    import personal_review_price_basis as basis
    from test_formal_trade_attribution import make_decision
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for cross-language response parity")
    bootstrap()
    isolated[0][0] = datetime(2026, 7, 20, 8, tzinfo=timezone.utc)
    pattern_result = svc.save("pattern", "synthetic-card", pattern())
    buy = trade(day=21)
    sell = trade("sell", day=24, price=5.)
    decision = make_decision(security_code="600000", committed_at="2026-07-20T00:00:00.000000Z", review_by="2026-07-30T00:00:00.000000Z")
    for index, trade_result in enumerate((buy, sell)):
        record = trade_ledger_store.get_record(ledger.resolve_db_path(), trade_result["trade_id"])
        attribution = fta.create_attribution(decision, record, attribution_id="trade_attribution_" + str(index + 1) * 32,
            created_at=svc._stamp(datetime.now(timezone.utc) + timedelta(seconds=1)).replace("+00:00", "Z")).to_dict()
        svc.attribution_store.write_attribution(db_path=svc.attribution_store.resolve_formal_trade_attribution_db_path(), record=attribution)
    isolated[0][0] = datetime(2026, 7, 28, 8, tzinfo=timezone.utc)
    body = svc.Assessment(revision=0, pattern_id="synthetic-card", pattern_revision=1, judgment="correct", execution="deviated", note="Synthetic parity", stop_price=9.)
    assessment = svc.save("assessment", buy["trade_id"], body)
    _, capture = basis_capture(tmp_path)
    raw = json.dumps(capture)
    receipt = basis.archive(raw)
    view = svc.view()
    assert view["closed_episodes"][0]["formal_attributions"][0]["decision_id"] == decision["decision_id"]
    excursion = svc.excursion(view["closed_episodes"][0])
    assert excursion["adjusted_bound"]["state"] == "INTERIOR_DAILY_ADJUSTED_BOUND"
    data = {"view": view, "excursion": excursion, "assessment": assessment, "assessmentBody": body.model_dump(),
        "pattern": pattern_result, "patternBody": pattern().model_dump(), "receipt": receipt, "raw": raw}
    parser = (Path(__file__).resolve().parents[2] / "frontend/src/lib/personalReviewValidation.ts").as_uri()
    script = '''
import fs from 'node:fs';
import net from 'node:net';
net.Socket.prototype.connect=function(){throw new Error('outbound prohibited');};
globalThis.fetch=()=>{throw new Error('outbound prohibited');};
const p=await import(process.argv[1]);const d=JSON.parse(fs.readFileSync(0,'utf8'));
p.parsePersonalReview(d.view);p.parseExcursion(d.excursion);p.parseSavedAssessment(d.assessment,d.assessmentBody);p.parseSavedPattern(d.pattern,d.patternBody);await p.parseBasisReceipt(d.receipt,d.raw);
console.log('nonempty-service-parser-parity-passed');
'''
    result = subprocess.run([node, "--experimental-strip-types", "--input-type=module", "-e", script, parser], input=json.dumps(data), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "nonempty-service-parser-parity-passed" in result.stdout


@pytest.mark.parametrize("field,value", [("code", "000001"), ("operation", "add"), ("execution_status", "partial"), ("executed_at", "2026-07-21T03:00:00.000000+00:00"), ("created_at", "2026-10-11T00:00:00.000000+00:00")])
def test_individually_valid_trade_anchor_drift_fails_closed(isolated, field, value):
    import formal_trade_attribution as fta
    from test_formal_trade_attribution import make_decision
    bootstrap(); buy = trade(day=21); trade("sell", day=24)
    original = trade_ledger_store.get_record(ledger.resolve_db_path(), buy["trade_id"])
    decision = make_decision(security_code="600000", committed_at="2026-07-20T00:00:00.000000Z", review_by="2026-07-30T00:00:00.000000Z")
    record = fta.create_attribution(decision, original, attribution_id="trade_attribution_" + "1" * 32,
        created_at=svc._stamp(datetime.now(timezone.utc) + timedelta(seconds=1)).replace("+00:00", "Z")).to_dict()
    svc.attribution_store.write_attribution(db_path=svc.attribution_store.resolve_formal_trade_attribution_db_path(), record=record)
    with sqlite3.connect(ledger.resolve_db_path()) as conn:
        # Parameterized values; the column is selected only by this test's fixed list.
        conn.execute(f"UPDATE trade_records SET {field}=? WHERE trade_id=?", (value, buy["trade_id"]))
    changed = trade_ledger_store.get_record(ledger.resolve_db_path(), buy["trade_id"])
    fta.verify_trade_record(changed)  # Individually valid is insufficient binding proof.
    before = file_identity(ledger.resolve_db_path())
    assert isolated[1]("GET", "/api/personal-review").status_code == 503
    assert file_identity(ledger.resolve_db_path()) == before
