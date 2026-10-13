"""Synthetic raw receipt → frozen snapshot → research API; no live acquisition."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import socket

from fastapi import FastAPI
import httpx
import pytest

from fact_lake_store import initialize_fact_lake, open_existing_fact_lake_snapshot
import shortline_research_contract as C
import shortline_research_adapters as A
import shortline_research_archive as archive
import shortline_research_metrics as M
import shortline_research_service as service
from shortline_research_router import router

DAY, PREVIOUS = "2026-07-30", "2026-07-29"
CODES = ["000001", "600001", "300001"]


def metadata(kind, day=DAY, *, batch=None, page=0, pages=1, codes=None):
    return {"kind": kind, "trade_date": day, "provider": "eastmoney_push2ex" if kind in C.KINDS[:3] else "tushare_pro",
            "endpoint": C.ENDPOINTS[kind], "captured_at": day + "T07:35:00Z", "http_status": 200,
            "fixture": True, "page_index": page, "page_count": pages,
            "batch_id": batch or day + "-" + kind, "request_shape": "synthetic-full-pool" if kind in C.KINDS[:3] else "synthetic-cohort",
            "requested_codes": [] if kind in C.KINDS[:3] else list(CODES if codes is None else codes)}


def raw_pool(rows, day=DAY, total=None):
    return C.canonical({"date": day.replace("-", ""), "data": {"pool": rows, "tc": len(rows) if total is None else total, "is_final": True, "revision_id": "synthetic-v1"}}).encode()


def poolrow(code, boards=1):
    return {"c": code, "lbc": boards, "fbt": 93000, "lbt": 143000, "zbc": 1, "fund": 1000}


def raw_prices(*, suspended=True, day=DAY):
    fields = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "trade_status", "vol"]
    items = [["000001.SZ", day.replace("-", ""), 10.5, 11, 10, 11, 10, "traded", 100],
             ["600001.SH", day.replace("-", ""), 10, 10, 9.3, 9.3, 10, "traded", 100],
             ["300001.SZ", day.replace("-", ""), 10, 10, 10, 10, 10, "suspended" if suspended else "traded", 0 if suspended else 100]]
    return C.canonical({"code": 0, "data": {"fields": fields, "items": items}}).encode()


def raw_limits(day=DAY):
    return C.canonical({"code": 0, "data": {"fields": ["ts_code", "trade_date", "up_limit", "down_limit"],
        "items": [[c + (".SH" if c.startswith("6") else ".SZ"), day.replace("-", ""), 11 if c != "300001" else 12, 9 if c != "300001" else 8] for c in CODES]}}).encode()


def seed(lake):
    for kind, rows in [("limit_up", [poolrow("000001"), poolrow("600001", 2)]), ("broken", [poolrow("300001")]), ("limit_down", [])]:
        archive.persist_capture(lake, raw_pool(rows, PREVIOUS), metadata(kind, PREVIOUS))
    for kind, raw in [("limit_up", raw_pool([poolrow("000001", 2)])), ("broken", raw_pool([])), ("limit_down", raw_pool([])),
                      ("daily_prices", raw_prices()), ("daily_limits", raw_limits())]:
        archive.persist_capture(lake, raw, metadata(kind))


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.delenv("VR_FACT_LAKE_ROOT", raising=False)
    loop = asyncio.new_event_loop()
    def forbidden(*args, **kwargs):
        raise AssertionError("outbound I/O forbidden")
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    try:
        yield loop
    finally:
        loop.close()


def test_exact_raw_replay_full_cohort_and_unknown_suspension(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    seed(lake)
    data = archive.load_research_days(open_existing_fact_lake_snapshot(lake.root), [PREVIOUS, DAY])
    result = M.cohort_feedback(data[PREVIOUS], data[DAY])
    assert result["union_denominator"] == 3
    assert len(result["rows"]) == 3
    assert result["groups"]["all_yesterday"]["unknown"] == 1
    assert result["groups"]["all_yesterday"]["mean_pct"] is None
    assert result["groups"]["yesterday_limit_up"]["mean_pct"] == pytest.approx(1.5)
    assert result["groups"]["yesterday_limit_up"]["loss_ge_7_count"] == 1
    assert result["promotion"][0]["rate"] == 1
    missing = next(r for r in result["rows"] if r["stock_code"] == "300001")
    assert missing["price_status"] == "suspended" and missing["return_pct"] is None
    assert result["promotion_authority"] == "DESCRIPTIVE_SOURCE_STREAK_ONLY"


def test_pool_zero_requires_source_date_and_explicit_total():
    result = A.normalize_capture(raw_pool([]), metadata("limit_up"))
    assert result["complete"] and result["source_fields"] is None
    data = C.decode(raw_pool([])); del data["data"]["tc"]
    assert not A.normalize_capture(C.canonical(data).encode(), metadata("limit_up"))["complete"]
    del data["date"]
    assert A.normalize_capture(C.canonical(data).encode(), metadata("limit_up"))["status"] == "unavailable"


@pytest.mark.parametrize("mutation", ["bool", "nan", "negative", "ohlc", "mixed_date", "duplicate", "unexpected"])
def test_price_domain_failures(mutation):
    raw = C.decode(raw_prices(suspended=False))
    items = raw["data"]["items"]
    if mutation == "bool": items[0][5] = True
    if mutation == "nan":
        with pytest.raises(ValueError): A.normalize_capture(b'{"code":0,"data":NaN}', metadata("daily_prices"))
        return
    if mutation == "negative": items[0][6] = -10
    if mutation == "ohlc": items[0][3] = 10
    if mutation == "mixed_date": items[0][1] = "20260728"
    if mutation == "duplicate": items.append(items[0])
    if mutation == "unexpected": items[0][0] = "000002.SZ"
    if mutation in ("mixed_date", "duplicate", "unexpected"):
        with pytest.raises(ValueError): A.normalize_capture(C.canonical(raw).encode(), metadata("daily_prices"))
    else:
        value = A.normalize_capture(C.canonical(raw).encode(), metadata("daily_prices"))
        assert value["rows"][0]["return_pct"] is None


def test_missing_quality_does_not_become_zero_or_first_board():
    result = A.normalize_capture(raw_pool([{"c": "000001"}]), metadata("limit_up"))
    assert result["rows"][0]["boards"] is None
    daily = M.daily_observation({"limit_up": result})
    assert daily["highest_board"] is None
    assert daily["seal_quality"]["never_broken_count"] is None
    assert daily["broken_rate"] is None


def test_multi_page_proof_and_duplicates(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    for page, code in enumerate(CODES[:2]):
        archive.persist_capture(lake, raw_pool([poolrow(code)], total=2), metadata("limit_up", page=page, pages=2))
    result = archive.load_research_days(lake, [DAY])[DAY]["limit_up"]
    assert result["complete"] and len(result["rows"]) == 2
    archive.persist_capture(lake, raw_pool([poolrow("000001")], total=2), metadata("limit_up", page=0, pages=2))
    with pytest.raises(ValueError, match="duplicate"):
        archive.load_research_days(lake, [DAY])


def test_partial_later_batch_does_not_overwrite_complete(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    archive.persist_capture(lake, raw_pool([poolrow("000001")]), metadata("limit_up"))
    late = metadata("limit_up", batch="later-partial"); late["captured_at"] = DAY + "T08:00:00Z"
    archive.persist_capture(lake, raw_pool([], total=3), late)
    result = archive.load_research_days(lake, [DAY])[DAY]["limit_up"]
    assert result["complete"] and result["rows"][0]["stock_code"] == "000001"


def test_source_schema_empty_and_null_are_distinct():
    a = A.normalize_capture(raw_pool([poolrow("000001")]), metadata("limit_up"))
    row = poolrow("000001"); row["fund"] = None
    b = A.normalize_capture(raw_pool([row]), metadata("limit_up"))
    assert a["source_fields"] == b["source_fields"]
    assert b["rows"][0]["seal_fund_yuan"] is None
    assert A.normalize_capture(raw_pool([]), metadata("limit_up"))["source_fields"] is None


def test_same_cent_never_one_cent_tolerance():
    assert A.same_cent(10.99, 11) is False
    assert A.same_cent(11, 11) is True
    assert A.same_cent(10.999, 11) is None
    assert A.same_cent(True, 1) is None


def test_frozen_service_does_not_mutate_archive_and_labels_fixture(tmp_path, monkeypatch):
    root = tmp_path / "lake"; lake = initialize_fact_lake(root); seed(lake)
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(root))
    def tree(): return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    before = tree()
    result = service.query_shortline_research(DAY)
    assert result["status"] == "partial", result
    assert result["fixture"] is True and result["point_in_time_claim"] == "NONE"
    assert result["projection"]["daily"]["limit_up_count"] == 1
    assert result["projection"]["cohort"]["union_denominator"] == 3
    assert all(r["committed_at"] is None for e in result["evidence"] for r in e["receipts"])
    assert before == tree()
    history = result["projection"]["history"]["windows"][0]
    assert len(history["dates"]) == 10 and DAY not in history["dates"]
    assert history["metrics"]["limit_up_count"]["percentile"] is None


def test_missing_archive_is_not_created(tmp_path, monkeypatch):
    root = tmp_path / "missing"; monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(root))
    result = service.query_shortline_research(DAY)
    assert result["reason_codes"] == ["ARCHIVE_NOT_INITIALIZED"]
    assert not root.exists()


def test_capture_batch_reports_all_five_independently(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    seed(lake)
    calls = []
    def capture(kind, day, codes):
        calls.append(kind)
        if kind == "broken": raise RuntimeError("sensitive detail must not escape")
        raw = raw_pool([]) if kind in C.KINDS[:3] else raw_prices() if kind == "daily_prices" else raw_limits()
        return [(raw, metadata(kind, batch="new-close-" + kind))]
    result = archive.capture_close_batch(lake, trade_date=DAY, capture_one=capture, requested_codes=CODES)
    assert calls == list(C.KINDS)
    assert result["status"] == "partial" and not result["schedule_enabled"]
    assert "sensitive" not in str(result)


def test_request_does_not_accept_paths_asof_or_duplicates(monkeypatch, isolated):
    app = FastAPI(); app.include_router(router)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            good = await client.get(f"/api/market/shortline-research?trade_date={DAY}")
            assert good.status_code == 200 and good.json()["data"]["projection"] is None
            for suffix in ("&path=/tmp/x", "&as_of=2026-01-01", f"&trade_date={PREVIOUS}"):
                assert (await client.get(f"/api/market/shortline-research?trade_date={DAY}{suffix}")).status_code == 422
    isolated.run_until_complete(run())


def test_huge_boards_derived_overflow_and_zero_volume_fail_closed():
    capture = A.normalize_capture(raw_pool([poolrow("000001", 2147483647)]), metadata("limit_up"))
    assert capture["rows"][0]["boards"] is None
    assert M.daily_observation({"limit_up": capture})["ladder_gaps"] is None
    for value in (0, None):
        payload = C.decode(raw_prices(suspended=False)); payload["data"]["items"][0][8] = value
        assert A.normalize_capture(C.canonical(payload).encode(), metadata("daily_prices"))["rows"][0]["return_pct"] is None
    payload = C.decode(raw_prices(suspended=False)); payload["data"]["items"][0][6] = 1e-300
    assert A.normalize_capture(C.canonical(payload).encode(), metadata("daily_prices"))["rows"][0]["return_pct"] is None


def test_price_pool_conflict_keeps_promotion_unknown(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake"); seed(lake)
    data = archive.load_research_days(lake, [PREVIOUS, DAY])
    data[DAY]["limit_up"]["rows"] = []
    result = M.cohort_feedback(data[PREVIOUS], data[DAY])
    member = next(r for r in result["rows"] if r["stock_code"] == "000001")
    assert member["promotion"] is None and member["result"] == "unknown"
    assert member["return_pct"] == 10
    assert result["status"] == "partial" and result["outcome_coverage"]["unknown"] >= 1


def test_capture_rejects_narrowed_cohort_and_keeps_failed_receipts(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    seed(lake)
    def narrowed(kind, day, codes):
        if kind == "daily_prices":
            return [(raw_prices(), metadata(kind, codes=["000001"]))]
        if kind == "broken":
            return [(b"malformed", metadata(kind, batch="failure-" + kind))]
        return [(raw_pool([]) if kind in C.KINDS[:3] else raw_limits(), metadata(kind, batch="capture-" + kind))]
    result = archive.capture_close_batch(lake, trade_date=DAY, capture_one=narrowed, requested_codes=CODES)
    by_kind = {r["kind"]: r for r in result["endpoints"]}
    assert by_kind["daily_prices"]["status"] == "unavailable"
    assert by_kind["broken"]["status"] == "unavailable" and len(by_kind["broken"]["receipts"]) == 1
    receipt = by_kind["broken"]["receipts"][0]["observation_id"]
    assert lake.read_payload(receipt) == b"malformed"
    assert archive.replay_capture(lake, lake.get_observation(receipt))["status"] == "unavailable"


def test_aggregate_finite_and_source_provisional_guard(tmp_path):
    rows = [poolrow("000001"), poolrow("600001")]
    for row in rows: row["fund"] = 1e308
    capture = A.normalize_capture(raw_pool(rows), metadata("limit_up"))
    assert M.daily_observation({"limit_up": capture})["seal_quality"]["seal_fund_total_yuan"] is None
    payload = C.decode(raw_pool(rows)); payload["data"]["is_final"] = False
    assert A.normalize_capture(C.canonical(payload).encode(), metadata("limit_up"))["status"] == "partial"


def test_public_listing_byte_budget_precedes_payload_verification(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    archive.persist_capture(lake, raw_pool([poolrow("000001")]), metadata("limit_up"))
    with pytest.raises(Exception, match="budget"):
        lake.list_observations(dataset_id=C.DATASETS["limit_up"], start_trade_date=DAY, end_trade_date=DAY, max_payload_bytes=1)


def test_provisional_and_error_prices_never_qualify_close_returns(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake"); seed(lake)
    for mutation in ("provisional", "error"):
        inputs = archive.load_research_days(lake, [PREVIOUS, DAY])
        if mutation == "provisional":
            inputs[DAY]["daily_prices"]["source_finality"] = "source_declared_provisional"
        else:
            inputs[DAY]["daily_prices"]["status"] = "unavailable"
        result = M.cohort_feedback(inputs[PREVIOUS], inputs[DAY])
        assert result["groups"]["all_yesterday"]["observed"] == 0
        assert result["groups"]["yesterday_limit_up"]["median_pct"] is None


def test_missing_entry_cohorts_hide_survivor_window_statistics(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake"); seed(lake)
    inputs = archive.load_research_days(lake, [PREVIOUS, DAY])
    observations = {d: M.daily_observation(inputs[d]) for d in inputs}
    feedback = {DAY: M.cohort_feedback(inputs[PREVIOUS], inputs[DAY])}
    samples = M.historical_samples([PREVIOUS, DAY], observations, feedback, DAY)
    assert samples["windows"][0]["summary"]["mean_pct"] is None
    assert samples["windows"][0]["denominator_scope"] == "KNOWN_ENTRY_COHORTS_ONLY"


def test_producer_cannot_claim_a_narrow_requested_set_is_complete(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake"); seed(lake)
    def forbidden(*args):
        raise AssertionError("must validate cohort before any transport")
    with pytest.raises(ValueError, match="omit prior cohort"):
        archive.capture_close_batch(lake, trade_date=DAY, capture_one=forbidden, requested_codes=["000001"])


def test_price_bands_use_source_prices_not_stock_name_or_prefix(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake"); seed(lake)
    inputs = archive.load_research_days(lake, [DAY])[DAY]
    result = M.daily_observation(inputs)
    assert result["price_limit_bands"]["share_10"] == 1
    assert result["price_limit_bands"]["share_20"] == 0
    inputs["daily_limits"]["rows"][0]["limit_up"] = 11.01
    result = M.daily_observation(inputs)
    assert result["price_limit_bands"]["share_10"] is None
    assert result["price_limit_bands"]["counts"]["unknown"] == 1


@pytest.mark.parametrize("stamp", ["2026-07-30T12:00:00+01:60", "2026-07-30T24:00:00Z", "2026-02-30T12:00:00Z", "2026-07-30T12:00:00+24:00", "2026-07-30T12:00:00", "0000-07-30T12:00:00Z"])
def test_captured_timestamp_rejects_normalized_invalid_fields(stamp):
    import shortline_research_contract as contract
    with pytest.raises(ValueError):
        contract.instant(stamp)


def test_captured_timestamp_preserves_valid_offset_microseconds():
    import shortline_research_contract as contract
    assert contract.utc("2026-07-30T15:00:00.000001+08:00") == "2026-07-30T07:00:00.000001Z"
