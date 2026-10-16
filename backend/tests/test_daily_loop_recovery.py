"""Reconstructed offline contracts; runtime results must come from exact-head CI."""
import copy
import multiprocessing
import os
from pathlib import Path
import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import astock
import daily_review as review
import daily_review_sources as sources
import market
import public_data_budget as budget


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    def denied(*args, **kwargs):
        raise AssertionError("external network forbidden")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(budget, "_CACHE", {})
    monkeypatch.setattr(budget, "_INFLIGHT", set())
    monkeypatch.setattr(review, "_review_cache", {})
    monkeypatch.setattr(review, "_build_flight", None)
    monkeypatch.setattr(review, "_build_generation", 0)
    monkeypatch.setattr(review, "_committed_generation", 0)


def _held_worker(path, operation, code):
    def denied(*args, **kwargs):
        raise AssertionError("synthetic child network forbidden")
    with patch.object(socket.socket, "connect", denied), patch.object(socket, "getaddrinfo", denied):
        marker = os.environ.get("VR_P0_SYNTHETIC_MARKER")
        if marker:
            Path(marker).write_text("entered", encoding="utf-8")
        if operation == "daily_review":
            value = {"sources": {"indices": {"status": "complete", "value": [{"code": "000001"}]}},
                     "reason_code": "SOURCE_TIMEOUT"}
        else:
            value = {"revenue": 0, "net_profit": -1, "status": "partial", "reason_code": "SOURCE_TIMEOUT"}
        budget._write_result(path + ".checkpoint", value)
        time.sleep(60)


@pytest.mark.parametrize("operation", ["daily_review", "financials"])
def test_checkpoint_is_read_only_after_worker_reaped(operation):
    before = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    value = budget.run(operation, "600519", timeout=3, _target=_held_worker)
    assert time.monotonic() - started < 6
    assert value["reason_code"] == "SOURCE_TIMEOUT"
    if operation == "daily_review":
        assert value["sources"]["indices"]["value"] == [{"code": "000001"}]
    else:
        assert value["revenue"] == 0 and value["net_profit"] == -1
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_parallel_sources_keep_all_checkpoint_updates(monkeypatch):
    monkeypatch.setattr(astock, "index_quote", lambda: [{"code": "000001"}])
    monkeypatch.setattr(market, "get_global_indices", lambda: float("nan"))
    monkeypatch.setattr(market, "get_market_breadth", lambda: {"status": "unavailable", "data": None})
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: {})
    monkeypatch.setattr(market, "get_turnover_top", lambda: {"stocks": []})
    monkeypatch.setattr(market, "get_board_ranking", lambda kind, top_n: {"kind": kind})
    snapshots = []
    result = sources.collect(lambda packet: snapshots.append(copy.deepcopy(packet)))
    assert len(snapshots) == 8
    assert [len(p["sources"]) for p in snapshots] == list(range(1, 9))
    assert set(result["sources"]) == set(sources.KEYS)
    assert result["sources"]["global_indices"] == {"status": "unavailable"}
    assert result["sources"]["indices"]["status"] == "complete"


def test_missing_sources_never_fall_through_to_parent_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("missing source attempted parent provider")
    monkeypatch.setattr(astock, "index_quote", forbidden)
    for name in ("get_global_indices", "get_market_breadth", "get_short_term_emotion",
                 "get_turnover_top", "get_board_ranking"):
        monkeypatch.setattr(market, name, forbidden)
    monkeypatch.setattr(budget, "run", lambda *args: {"sources": {}, "reason_code": "SOURCE_TIMEOUT"})
    result = review._build_daily_review()
    assert result["trade_date"] is None
    assert result["collection"]["pending"] == list(sources.KEYS)
    assert result["market_environment"]["breadth"]["data"] is None


@pytest.mark.parametrize("value", ["2026-02-30", "0000-01-01", "2026-13-01"])
def test_invalid_calendar_dates_remain_unknown(value):
    assert review._valid_trade_date(value)[0] is None


def test_cold_and_explicit_share_build(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def build():
        calls.append(1); entered.set()
        assert release.wait(2)
        return {"status": "normal"}
    monkeypatch.setattr(review, "_build_daily_review", build)
    values = []
    first = threading.Thread(target=lambda: values.append(review._shared_build()))
    first.start(); assert entered.wait(2)
    waiting = threading.Event()
    original_wait = review._build_flight.event.wait
    def observed_wait(timeout=None):
        waiting.set()
        return original_wait(timeout)
    review._build_flight.event.wait = observed_wait
    second = threading.Thread(target=lambda: values.append(review._shared_build()))
    second.start(); assert waiting.wait(2)
    release.set(); first.join(2); second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert len(calls) == 1
    assert values == [(1, {"status": "normal"})] * 2


def test_older_cold_completion_cannot_overwrite_new_refresh(monkeypatch):
    stale_ready, resume = threading.Event(), threading.Event()
    disk = []
    def shared():
        if threading.current_thread().name == "old-cold":
            stale_ready.set(); assert resume.wait(2)
            return 1, {"status": "normal", "marker": "old"}
        review._build_generation = 2
        return 2, {"status": "normal", "marker": "new"}
    monkeypatch.setattr(review, "_shared_build", shared)
    monkeypatch.setattr(review, "_cached_review", lambda: review._review_cache.get("test"))
    monkeypatch.setattr(review, "_cached_review_age_seconds", lambda: 0)
    monkeypatch.setattr(review, "_refresh_accepts_result", lambda value: (True, "normal"))
    def store(value):
        disk.append(value["marker"]); review._review_cache["test"] = copy.deepcopy(value)
        return True
    monkeypatch.setattr(review, "_store_review", store)
    monkeypatch.setattr(review, "_store_review_on_refresh", store)
    output = []
    old = threading.Thread(name="old-cold", target=lambda: output.append(review.generate_daily_review()))
    old.start(); assert stale_ready.wait(2)
    assert review._run_explicit_refresh_build()["data"]["marker"] == "new"
    resume.set(); old.join(2); assert not old.is_alive()
    assert disk == ["new"]
    assert output[0]["marker"] == "new"


def test_financial_partial_does_not_hide_next_retry(monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        return {"revenue": 0, "net_profit": -1, **({"status": "partial"} if len(calls) == 1 else {})}
    monkeypatch.setattr(budget, "_run_process", run)
    assert budget.run("financials", "600519")["status"] == "partial"
    assert "status" not in budget.run("financials", "600519")
    budget.run("financials", "600519")
    assert len(calls) == 2


def test_endpoint_partial_does_not_enter_long_cache(monkeypatch):
    import app
    monkeypatch.setattr(app, "_FIN_CACHE", app.TTLCache())
    calls = []
    def run(operation, code):
        calls.append((operation, code))
        return {"revenue": 0, "net_profit": -1, **({"status": "partial"} if len(calls) == 1 else {})}
    monkeypatch.setattr(budget, "run", run)
    assert app.financials("600519")["data"]["status"] == "partial"
    assert "status" not in app.financials("600519")["data"]
    app.financials("600519")
    assert len(calls) == 2


@pytest.mark.parametrize("category,frequency", [(4, 4), (5, 5), (6, 6), (11, 3)])
def test_installed_mootdx_receives_exact_period(monkeypatch, tmp_path, category, frequency):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    from mootdx.quotes import StdQuotes
    calls = []
    client = object.__new__(StdQuotes)
    client.client = SimpleNamespace(get_security_bars=lambda *args, **kwargs: calls.append((args, kwargs)) or [])
    monkeypatch.setattr(astock, "_mootdx_client", lambda: client)
    astock._kline_source("mootdx", "600519", category, 60)
    assert calls
    args, kwargs = calls[0]
    assert (args[0] if args else kwargs["category"]) == frequency


def test_kline_shared_deadline_and_busy_does_not_bypass(monkeypatch):
    import hithink_finance_client as hithink
    monkeypatch.setattr(hithink, "is_configured", lambda: False)
    calls = []
    def stage(source, code, category, offset, timeout):
        calls.append((source, code, category, offset, timeout))
        raise budget.PublicDataUnavailable("SOURCE_BUSY")
    monkeypatch.setattr(astock, "_bounded_kline_source", stage)
    with pytest.raises(budget.PublicDataUnavailable, match="SOURCE_BUSY"):
        astock.kline("600519", 5, 17)
    assert calls[0][:4] == ("mootdx", "600519", 5, 17)
    assert 0 < calls[0][4] <= 4
    assert len(calls) == 1


def test_kline_period_and_count_are_part_of_flight_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(budget, "_run_process",
        lambda operation, code, **kwargs: calls.append((operation, code)) or [])
    budget.run("kline_mootdx", ("600519", 4, 60))
    budget.run("kline_mootdx", ("600519", 5, 17))
    assert calls == [("kline_mootdx", ("600519", 4, 60)), ("kline_mootdx", ("600519", 5, 17))]


def _financial_real_source_worker(path, operation, code):
    def denied(*args, **kwargs):
        raise AssertionError("synthetic child network forbidden")
    class Frame:
        empty = False
        def to_dict(self, mode):
            return [{"报告期": "2025-12-31", "营业总收入": 0, "净利润": -1}]
    class Provider:
        def stock_financial_abstract_ths(self, **kwargs):
            return Frame()
        def stock_financial_benefit_new_ths(self, **kwargs):
            time.sleep(60)
    with patch.object(socket.socket, "connect", denied), patch.object(socket, "getaddrinfo", denied), patch.object(astock, "_akshare", return_value=Provider()):
        budget._child(path, operation, code)


def test_actual_summary_precedes_held_optional_enrichment():
    before = {p.pid for p in multiprocessing.active_children()}
    value = budget.run("financials", "600519", timeout=3, _target=_financial_real_source_worker)
    assert value["status"] == "partial"
    assert value["revenue"] == 0 and value["net_profit"] == -1
    assert value["operating_cash_flow"] is None
    assert value["data_quality"]["point_in_time_supported"] is False
    assert value["data_quality"]["publication_date_known"] is False
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_held_mootdx_is_reaped_before_tencent_starts(monkeypatch, tmp_path):
    import hithink_finance_client as hithink
    monkeypatch.setattr(hithink, "is_configured", lambda: False)
    before = {p.pid for p in multiprocessing.active_children()}
    marker = tmp_path / "child-entered"
    monkeypatch.setenv("VR_P0_SYNTHETIC_MARKER", str(marker))
    calls = []
    def stage(source, code, category, offset, timeout):
        calls.append(source)
        if source == "mootdx":
            # The synthetic hung child writes no Kline final packet.
            return budget.run("kline_mootdx", (code, category, offset),
                              timeout=3, _target=_held_worker)
        assert marker.read_text(encoding="utf-8") == "entered"
        assert {p.pid for p in multiprocessing.active_children()} == before
        return [{"date": "2026-07-31", "close": 10}]
    monkeypatch.setattr(astock, "_bounded_kline_source", stage)
    assert astock.kline("600519", 5, 17) == [{"date": "2026-07-31", "close": 10}]
    assert calls == ["mootdx", "tencent"]


def test_current_shared_cold_commit_does_not_block_explicit_disk_retry(monkeypatch):
    value = {"status": "normal", "marker": "shared"}
    review._build_generation = 1
    monkeypatch.setattr(review, "_shared_build", lambda: (1, copy.deepcopy(value)))
    monkeypatch.setattr(review, "_cached_review", lambda: review._review_cache.get("test"))
    monkeypatch.setattr(review, "_cached_review_age_seconds", lambda: 0)
    monkeypatch.setattr(review, "_refresh_accepts_result", lambda result: (True, "normal"))
    disk_attempts = []
    def cold_store(result):
        review._review_cache["test"] = copy.deepcopy(result)
        disk_attempts.append("cold-failed")
        # Cold storage deliberately retains memory after a failed disk save.
    def explicit_store(result):
        disk_attempts.append("explicit-succeeded")
        review._review_cache["test"] = copy.deepcopy(result)
        return True
    monkeypatch.setattr(review, "_store_review", cold_store)
    monkeypatch.setattr(review, "_store_review_on_refresh", explicit_store)
    assert review.generate_daily_review()["marker"] == "shared"
    assert review._run_explicit_refresh_build()["data"]["marker"] == "shared"
    assert disk_attempts == ["cold-failed", "explicit-succeeded"]


@pytest.mark.parametrize("operation,args", [
    ("kline_hithink", ("600519", 5, 60)),
    ("kline_mootdx", ("920001", 4, 60)),
    ("kline_tencent", ("830001", 4, 60)),
    ("kline_tencent", ("600519", 11, 60)),
])
def test_incompatible_worker_route_never_acquires_slot(monkeypatch, operation, args):
    monkeypatch.setattr(budget, "_SLOTS", SimpleNamespace(acquire=lambda **kw: pytest.fail("invalid route started")))
    with pytest.raises(ValueError, match="unsupported kline source route"):
        budget._run_process(operation, args)


def test_eight_near_limit_sources_fit_and_one_oversized_source_does_not_stop_others(monkeypatch):
    value = "x" * ((budget.MAX_BYTES - 4096) // 8 - 100)
    monkeypatch.setattr(astock, "index_quote", lambda: value)
    monkeypatch.setattr(market, "get_global_indices", lambda: value)
    monkeypatch.setattr(market, "get_market_breadth", lambda: value)
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: value)
    monkeypatch.setattr(market, "get_turnover_top", lambda: value)
    monkeypatch.setattr(market, "get_board_ranking", lambda *args, **kw: value)
    import json
    packets = []
    def checkpoint(packet):
        raw = json.dumps({"data": packet}, ensure_ascii=False, allow_nan=False).encode("utf-8")
        assert len(raw) <= budget.MAX_BYTES
        packets.append(copy.deepcopy(packet))
    result = sources.collect(checkpoint)
    assert len(packets) == 8
    assert all(entry["status"] == "complete" for entry in result["sources"].values())
    monkeypatch.setattr(astock, "index_quote", lambda: "x" * budget.MAX_BYTES)
    packets.clear()
    result = sources.collect(checkpoint)
    assert len(packets) == 8
    assert result["sources"]["indices"] == {"status": "unavailable"}
    assert sum(entry["status"] == "complete" for entry in result["sources"].values()) == 7


def test_pure_assembly_requires_explicit_source_map():
    with pytest.raises(ValueError, match="source map"):
        review._assemble_daily_review(None)


def test_kline_stages_share_remaining_budget_including_cleanup(monkeypatch):
    import hithink_finance_client as hithink
    monkeypatch.setattr(hithink, "is_configured", lambda: True)
    clock = [100.0]
    calls = []
    def stage(source, code, category, offset, timeout):
        calls.append((source, timeout))
        if source == "hithink":
            clock[0] += 5  # Four seconds of work plus one second of cleanup.
            raise budget.PublicDataUnavailable("SOURCE_TIMEOUT")
        if source == "mootdx":
            clock[0] += 6
            raise budget.PublicDataUnavailable("SOURCE_TIMEOUT")
        return [{"close": 10}]
    monkeypatch.setattr(astock, "_bounded_kline_source", stage)
    with monkeypatch.context() as local:
        local.setattr(time, "monotonic", lambda: clock[0])
        assert astock.kline("600519") == [{"close": 10}]
    assert calls == [("hithink", 4), ("mootdx", 4), ("tencent", 1)]


def test_kline_does_not_dispatch_after_total_deadline(monkeypatch):
    import hithink_finance_client as hithink
    monkeypatch.setattr(hithink, "is_configured", lambda: True)
    clock = [100.0]
    calls = []
    def stage(source, code, category, offset, timeout):
        calls.append(source)
        clock[0] += 13
        raise budget.PublicDataUnavailable("SOURCE_TIMEOUT")
    monkeypatch.setattr(astock, "_bounded_kline_source", stage)
    with monkeypatch.context() as local:
        local.setattr(time, "monotonic", lambda: clock[0])
        with pytest.raises(budget.PublicDataUnavailable, match="SOURCE_TIMEOUT"):
            astock.kline("600519")
    assert calls == ["hithink"]
