"""Stored v0.2 membership navigation; no providers or source SQLite writes."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

import cohort_identity_service as service
import short_term_daily_facts_v02 as composer
import short_term_fact_store as store
from test_short_term_daily_facts_v02 import _facts, _producer
from test_short_term_seal_quality_service import http_get  # guarded in-process actual app

P, T = "2026-07-29", "2026-07-30"


def envelope(day, members):
    facts = _facts(limit_up=len(members))
    facts["trade_date"] = day
    producer = _producer(trade_date=day, rows=[{"stock_code": code, "lbc": boards} for code, boards in members])
    def dates(value):
        if isinstance(value, dict):
            return {key: dates(item) for key, item in value.items()}
        if isinstance(value, list):
            return [dates(item) for item in value]
        if isinstance(value, str) and (value.startswith("2026-07-31T") or value.startswith("2026-07-30T")):
            return day + "T09:00:00.000000Z"
        return value
    facts, producer = dates(facts), dates(producer)
    result = composer.compute_daily_facts_v02(facts, {"kind": "producer", "envelope": producer})
    assert result["status"] == "normal", result
    return result


def tree(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob("*") if p.is_file()}


def persist(day, members):
    env = envelope(day, members)
    store.save_daily_facts_monotonic(env)
    return env


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(store, "_utc_now", lambda: "2026-07-31T01:00:00+00:00")
    monkeypatch.setattr(service, "_now", lambda: datetime(2026, 8, 1, tzinfo=timezone.utc))


@pytest.fixture
def archived():
    persist(P, [("600001", 1), ("000002.SZ", 3)])
    persist(T, [("600001.SH", 2), ("300003", 1)])
    return store.resolve_db_path()


def test_actual_store_route_and_legacy_reader_leave_whole_tree_unchanged(archived, http_get):
    before = tree(archived.parent)
    response = http_get(f"/api/market/cohort-identity?trade_date={T}")
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "normal", result
    assert result["point_in_time_claim"] == "NONE"
    assert result["projection"]["rows"] == [
        {"stock_code": "000002", "previous_source_code": "000002.SZ", "current_source_code": None,
         "previous_boards": 3, "current_boards": None, "present_today": False},
        {"stock_code": "600001", "previous_source_code": "600001", "current_source_code": "600001.SH",
         "previous_boards": 1, "current_boards": 2, "present_today": True},
    ]
    assert set(result["projection"]) == {"rows"}
    assert result["evidence"]["previous"]["row_count"] == 2
    assert len(result["evidence"]["current"]["envelope_sha256"]) == 64
    assert store.load_final_fact_record(T)["envelope"]["trade_date"] == T
    assert tree(archived.parent) == before


def test_no_missing_database_created(tmp_path):
    result = service.query_cohort_identity(T)
    assert result["projection"] is None
    assert result["reason_codes"] == ["ARCHIVE_MISSING"]
    assert not (tmp_path / "data").exists()
    assert store.load_final_fact_record(T) is None
    assert not (tmp_path / "data").exists()


def test_one_side_missing_cannot_be_absent(archived):
    assert service.query_cohort_identity("2026-07-31")["projection"] is None


@pytest.mark.parametrize("day", ["2026-08-01", "2027-01-01"])
def test_calendar_unknown_no_nearest_available_substitution(day):
    assert service.query_cohort_identity(day)["reason_codes"] == ["CALENDAR_UNAVAILABLE"]


@pytest.mark.parametrize("day", ["2026-7-30", "2026-02-30", "", None])
def test_bad_dates(day):
    with pytest.raises(ValueError): service.query_cohort_identity(day)


def valid_record():
    return {"envelope": envelope(P, [("600001", 1), ("000002", 3)]), "stored_at": "2026-07-31T01:00:00+00:00"}


@pytest.mark.parametrize("mutate", [
    lambda e: e.update(schema_version="short-term-daily-facts-v0.1"),
    lambda e: e.update(source_status="partial"),
    lambda e: e.update(source_reason_codes=["SOURCE_PARTIAL"]),
    lambda e: e["sections"]["facts"].update(status="partial"),
    lambda e: e["sections"]["gap"].update(trade_date=T),
    lambda e: e.update(status="partial"), lambda e: e.update(is_final=False),
    lambda e: e.update(trade_date=T), lambda e: e.update(source_ids=[]),
    lambda e: e.update(snapshot_at="2026-08-03T00:00:00Z"),
    lambda e: e.update(fetched_at="2026-07-29T01:00:00Z"),
    lambda e: e["sections"]["ladder"].update(status="partial"),
    lambda e: e["sections"]["ladder"].update(source_ids=["invented"]),
    lambda e: e["sections"]["ladder"].pop("board_semantics"),
    lambda e: e["sections"]["ladder"]["data_health"].update(row_count=True),
    lambda e: e["sections"]["ladder"]["data_health"].update(row_count=3),
    lambda e: e["sections"]["ladder"]["data_health"].update(legal_zero=True),
    lambda e: e["sections"]["ladder"]["data_health"].update(coverage_warning=True),
    lambda e: e["sections"]["ladder"]["data_health"].update(trade_date_match=False),
    lambda e: e["sections"]["ladder"]["metrics"].update(max_boards=9),
    lambda e: e["sections"]["ladder"]["metrics"].update(lianban_count=True),
    lambda e: e["sections"]["ladder"]["metrics"].update(ladder=[]),
    lambda e: e["sections"]["ladder"]["board_semantics"][0].update(boards=True),
    lambda e: e["sections"]["ladder"]["board_semantics"][0].update(boards=0),
    lambda e: e["sections"]["ladder"]["board_semantics"][0].update(stock_code="600001.SZ"),
    lambda e: e["sections"]["ladder"]["board_semantics"][0].update(effective_height=99),
])
def test_rejects_ineligible_membership(mutate):
    record = valid_record(); mutate(record["envelope"])
    with pytest.raises((ValueError, store.FactStoreError)):
        service._checked(record, P, service._now())


@pytest.mark.parametrize("instant", [None, "not-a-time", "2026-07-31", "2026-07-29T06:00:00Z", "2026-08-02T00:00:00Z", "9999-12-31T23:59:59-23:59"])
def test_invalid_persistence_timing(instant):
    record = valid_record(); record["stored_at"] = instant
    with pytest.raises((ValueError, OverflowError)):
        service._checked(record, P, service._now())


def test_alias_duplicates_rejected():
    record = valid_record(); ladder = record["envelope"]["sections"]["ladder"]
    ladder["board_semantics"][1] = deepcopy(ladder["board_semantics"][0])
    ladder["board_semantics"][1]["stock_code"] = "600001.SH"
    with pytest.raises(ValueError): service._checked(record, P, service._now())


def test_pending_wal_never_ignores_committed_data(archived):
    conn = sqlite3.connect(archived)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE pending_marker(value)"); conn.commit()
        before = tree(archived.parent)
        assert service.query_cohort_identity(T)["reason_codes"] == ["ARCHIVE_BUSY"]
        with pytest.raises(store.FactStoreBusyError): store.load_final_fact_record(T)
        assert tree(archived.parent) == before
    finally: conn.close()


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_nonempty_sidecars_fail_closed(archived, suffix):
    Path(str(archived) + suffix).write_bytes(b"pending")
    before = tree(archived.parent)
    assert service.query_cohort_identity(T)["reason_codes"] == ["ARCHIVE_BUSY"]
    assert tree(archived.parent) == before


def test_rollback_database_parity(archived):
    with sqlite3.connect(archived) as conn: conn.execute("PRAGMA journal_mode=DELETE")
    before = tree(archived.parent)
    assert service.query_cohort_identity(T)["status"] == "normal"
    assert tree(archived.parent) == before


def test_corrupt_database_no_repair(archived):
    archived.write_bytes(b"broken")
    before = tree(archived.parent)
    assert service.query_cohort_identity(T)["reason_codes"] == ["ARCHIVE_INELIGIBLE"]
    assert tree(archived.parent) == before


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_symlinks_fail_closed(archived, suffix, tmp_path):
    path = Path(str(archived) + suffix)
    target = tmp_path / "target"
    target.write_bytes(path.read_bytes() if path.exists() else b"")
    if path.exists(): path.unlink()
    path.symlink_to(target)
    assert service.query_cohort_identity(T)["reason_codes"] == ["ARCHIVE_INELIGIBLE"]


def test_drift_during_source_read(archived, monkeypatch):
    original = os.open
    calls = []
    def drift(path, flags, *args, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            original_bytes = archived.read_bytes()
            archived.write_bytes(original_bytes[:-1] + bytes([original_bytes[-1] ^ 1]))
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", drift)
    assert service.query_cohort_identity(T)["reason_codes"] == ["ARCHIVE_BUSY"]



@pytest.mark.parametrize("query", ["", "?trade_date=2026-07-30&trade_date=2026-07-30", "?trade_date=2026-07-30&as_of=x", "?trade_date=2026-07-30&path=/tmp", "?trade_date=2026-07-30&root=/tmp", "?trade_date=2026-07-30&selection=pit"])
def test_exact_route_query_boundary(http_get, query):
    assert http_get("/api/market/cohort-identity" + query).status_code == 422


def test_inherits_api_key_and_origin(http_get, monkeypatch):
    import app
    monkeypatch.setattr(app, "_API_KEY", "fixture-secret")
    path = f"/api/market/cohort-identity?trade_date={T}"
    assert http_get(path).status_code == 401
    assert http_get(path, {"Authorization": "Bearer wrong"}).status_code == 401
    assert http_get(path, {"Authorization": "Bearer fixture-secret"}).status_code == 200
    assert http_get(path, {"Authorization": "Bearer fixture-secret", "Origin": "https://hostile.invalid"}).status_code == 403


@pytest.mark.parametrize("code", ["610001.SH", "090001.SZ", "390001.SZ", "800001", "600001.SZ", "000001.SH"])
def test_exact_adapter_universe(code):
    with pytest.raises(ValueError): service._identity(code)


def test_empty_membership_cannot_upgrade_incomplete_or_contradictory_proof():
    record = valid_record(); ladder = record["envelope"]["sections"]["ladder"]
    ladder["board_semantics"] = []
    ladder["data_health"].update(row_count=0, legal_zero=True)
    ladder["metrics"] = {"max_boards": 0, "lianban_count": 0, "ladder": []}
    with pytest.raises(ValueError): service._checked(record, P, service._now())
    record["envelope"]["sections"]["facts"]["facts"]["limit_up_count"] = 0
    with pytest.raises(ValueError): service._checked(record, P, service._now())
    del ladder["board_semantics"]
    with pytest.raises(ValueError): service._checked(record, P, service._now())


def test_hash_changes_with_stored_envelope_but_not_invented_raw_identity():
    record = valid_record(); _, first = service._checked(record, P, service._now())
    record["envelope"]["limitations"].append("synthetic fixture revision")
    _, second = service._checked(record, P, service._now())
    assert first["envelope_sha256"] != second["envelope_sha256"]
    assert "raw_payload_hash" not in second


def test_closed_wal_empty_table_old_helper_does_not_create_sidecars(tmp_path):
    path = tmp_path / "empty.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE fact_snapshots(trade_date,session,envelope_json,stored_at)")
    conn.commit(); conn.close()
    before = tree(tmp_path)
    assert store.load_final_fact_record(T, path) is None
    assert tree(tmp_path) == before


def test_source_header_never_modified_and_memory_conversion_is_two_bytes(archived):
    before = archived.read_bytes()
    assert before[18:20] == b"\x02\x02"
    records = store.load_final_fact_records_readonly((P, T))
    assert records[P]["database_sha256"] == records[T]["database_sha256"] == hashlib.sha256(before).hexdigest()
    assert archived.read_bytes() == before


def test_identity_service_later_revision_is_posthoc_not_historical_pit(archived):
    result = service.query_cohort_identity(T)
    assert result["evidence"]["previous"]["stored_at"] > T
    assert result["status"] == "normal"
    assert result["selection_mode"] == "CURRENT_STORED_POSTHOC"
    assert result["point_in_time_claim"] == "NONE"


@pytest.mark.parametrize("indices, replacement", [(slice(18,20), b"\x02\x01"), (slice(16,18), b"\x00\x00"), (slice(28,32), b"\xff\xff\xff\xff")])
def test_unsupported_sqlite_header(archived, indices, replacement):
    image = bytearray(archived.read_bytes()); image[indices] = replacement; archived.write_bytes(image)
    before = tree(archived.parent)
    assert service.query_cohort_identity(T)["reason_codes"] == ["ARCHIVE_INELIGIBLE"]
    assert tree(archived.parent) == before


def test_strict_browser_missing_archive_goldens_match_actual_service():
    path = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/cohort-identity-unavailable.json"
    golden = json.loads(path.read_text(encoding="utf-8"))
    for day, expected in golden.items():
        assert service.query_cohort_identity(day) == expected


@pytest.mark.parametrize("count", [0, 1, 3, 1000, True, None])
def test_canonical_count_disagreement_cannot_be_complete_membership(count):
    record = valid_record()
    record["envelope"]["sections"]["facts"]["facts"]["limit_up_count"] = count
    with pytest.raises(ValueError): service._checked(record, P, service._now())



def test_deeply_corrupt_json_fails_closed_without_source_writes(archived):
    conn = sqlite3.connect(archived)
    conn.execute("UPDATE fact_snapshots SET envelope_json=? WHERE trade_date=?", ("[" * 1100 + "0" + "]" * 1100, P))
    conn.commit(); conn.close()
    before = tree(archived.parent)
    assert service.query_cohort_identity(T)["reason_codes"] == ["ARCHIVE_INELIGIBLE"]
    assert tree(archived.parent) == before


def test_malformed_canonical_facts_fails_closed():
    record = valid_record(); record["envelope"]["sections"]["facts"]["facts"] = []
    with pytest.raises(ValueError): service._checked(record, P, service._now())
