"""P1-PERF1 — CCD runtime 并发评估与有界等待合同测试。

覆盖 ``campaign_critical_data_runtime._capability_results`` 的并发语义：

- 网络型 capability（market_sector/disclosures/financials）互相独立，并发
  执行；结果顺序仍严格等于 required_dependency_ids 声明序；
- 共享 wall-clock 预算到点未返回的 capability 如实记 ERROR（与 provider
  failure 同形），其余 capability 判定不受影响；
- price_reference 内联（本地 Fact Lake 句柄不跨线程），无湖时 NOT_EVALUATED；
- 未知 capability 在建线程前 fail closed。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

import campaign_critical_data_runtime as cdr
import critical_data_market_sector_adapter as market_sector_adapter

AS_OF = "2026-08-22T00:00:00.000000Z"
CAMPAIGN_ID = "campaign_" + "a" * 32

PRICE_ID = "cap.security.price_reference"
SECTOR_ID = "cap.context.market_sector"
DISCLOSURES_ID = "cap.security.disclosures"
FINANCIALS_ID = "cap.security.financials"


def _campaign() -> dict:
    return {
        "campaign_id": CAMPAIGN_ID,
        "security_code": "600519",
        "strategy": "SWING",
        "status": "ACTIVE",
    }


def _definition(dependency_ids: list[str]) -> dict:
    return {
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": CAMPAIGN_ID,
        "as_of": AS_OF,
        "dependency_set_state": "RESOLVED",
        "dependency_set_authority_refs": ["dda:test"],
        "required_dependency_ids": list(dependency_ids),
    }


def _usable(dep_id: str) -> dict:
    return {
        "dependency_id": dep_id,
        "state": "USABLE",
        "as_of": AS_OF,
        "authority_refs": [f"cap:test:{dep_id}"],
    }


def _ports(
    dependency_ids: list[str],
    *,
    sector=None,
    disclosures=None,
    financials=None,
    price=None,
) -> cdr.CriticalDataPorts:
    def _default_usable(dep_id):
        def _evaluate(lake, definition):
            return _usable(dep_id)

        return _evaluate

    return cdr.CriticalDataPorts(
        dependency_resolver=lambda **kwargs: _definition(dependency_ids),
        price_evaluator=price or _default_usable(PRICE_ID),
        market_sector_evaluator=sector or _default_usable(SECTOR_ID),
        disclosures_evaluator=disclosures or _default_usable(DISCLOSURES_ID),
        financials_evaluator=financials or _default_usable(FINANCIALS_ID),
        lake_provider=lambda: None,
    )


def project(ports, campaign=None):
    return cdr.project_campaign_critical_data(
        campaign=campaign or _campaign(),
        as_of=AS_OF,
        ports=ports,
    )


def test_network_capabilities_evaluate_concurrently():
    sleep_seconds = 0.6

    def slow(lake, definition):
        time.sleep(sleep_seconds)
        return _usable(SECTOR_ID)

    ids = [PRICE_ID, SECTOR_ID, DISCLOSURES_ID, FINANCIALS_ID]
    ports = _ports(ids, sector=slow)

    start = time.monotonic()
    ccd = project(ports)
    elapsed = time.monotonic() - start

    # 串行时三个 0.6s 网络 capability 至少 1.8s；并发后应接近单个耗时。
    assert elapsed < 1.5, f"network capabilities did not run concurrently: {elapsed:.2f}s"
    assert [r["dependency_id"] for r in ccd["dependency_results"]] == ids
    states = {r["dependency_id"]: r["state"] for r in ccd["dependency_results"]}
    assert states[PRICE_ID] == "NOT_EVALUATED"  # 无湖：内联 NOT_EVALUATED
    assert states[SECTOR_ID] == "USABLE"
    assert states[DISCLOSURES_ID] == "USABLE"
    assert states[FINANCIALS_ID] == "USABLE"


def test_shared_budget_timeout_records_error_without_blocking_others(monkeypatch):
    monkeypatch.setattr(cdr, "_CAPABILITY_WALL_CLOCK_BUDGET_SECONDS", 0.6)

    def hang(lake, definition):
        time.sleep(5.0)
        return _usable(FINANCIALS_ID)

    ids = [SECTOR_ID, DISCLOSURES_ID, FINANCIALS_ID]
    ports = _ports(ids, financials=hang)

    start = time.monotonic()
    ccd = project(ports)
    elapsed = time.monotonic() - start

    # 不等待迟到的 worker：远小于其 5s 睡眠。
    assert elapsed < 3.0, f"timeout budget did not bound the wait: {elapsed:.2f}s"
    by_id = {r["dependency_id"]: r for r in ccd["dependency_results"]}
    assert by_id[FINANCIALS_ID]["state"] == "ERROR"
    assert by_id[FINANCIALS_ID]["authority_refs"] == [cdr.NETWORK_BUDGET_EXHAUSTED_REF]
    assert by_id[SECTOR_ID]["state"] == "USABLE"
    assert by_id[DISCLOSURES_ID]["state"] == "USABLE"


def test_result_order_is_declaration_order_not_completion_order():
    def make_slow(dep_id, seconds):
        def _evaluate(lake, definition):
            time.sleep(seconds)
            return _usable(dep_id)

        return _evaluate

    # 声明序靠后的 capability 更早完成。
    ids = [SECTOR_ID, DISCLOSURES_ID, FINANCIALS_ID]
    ports = _ports(
        ids,
        sector=make_slow(SECTOR_ID, 0.5),
        disclosures=make_slow(DISCLOSURES_ID, 0.3),
        financials=make_slow(FINANCIALS_ID, 0.05),
    )
    ccd = project(ports)
    assert [r["dependency_id"] for r in ccd["dependency_results"]] == ids


def test_unknown_capability_fails_closed_before_threads():
    ids = [SECTOR_ID, "cap.unknown"]
    ports = _ports(ids)
    with pytest.raises(cdr.CriticalDataRuntimeIntegrityError, match="unknown capability"):
        project(ports)


def test_adapter_error_maps_to_error_result_through_pool_path():
    def boom(lake, definition):
        raise market_sector_adapter.MarketSectorCapabilityError("provider down")

    ids = [SECTOR_ID, DISCLOSURES_ID]
    ports = _ports(ids, sector=boom)
    ccd = project(ports)
    by_id = {r["dependency_id"]: r for r in ccd["dependency_results"]}
    assert by_id[SECTOR_ID]["state"] == "ERROR"
    assert by_id[SECTOR_ID]["as_of"] == AS_OF
    assert by_id[DISCLOSURES_ID]["state"] == "USABLE"


def test_single_network_capability_still_evaluated():
    ids = [DISCLOSURES_ID]
    ccd = project(_ports(ids))
    assert [r["dependency_id"] for r in ccd["dependency_results"]] == ids
    assert ccd["dependency_results"][0]["state"] == "USABLE"


def test_empty_dependency_set_returns_empty_results():
    ccd = project(_ports([]))
    assert ccd["dependency_results"] == []


def test_expired_shared_deadline_starts_no_provider_but_evaluates_local_price():
    calls = []

    def network(*args):
        pytest.fail("expired request started a provider")

    def local_price(lake, definition):
        calls.append(lake)
        return _usable(PRICE_ID)

    ids = [PRICE_ID, SECTOR_ID, DISCLOSURES_ID, FINANCIALS_ID]
    result = cdr._capability_results(
        _definition(ids), lake="local", ports=_ports(
            ids, price=local_price, sector=network, disclosures=network, financials=network
        ), network_deadline=time.monotonic() - 1,
    )
    assert calls == ["local"]
    assert result[0]["state"] == "USABLE"
    assert [r["dependency_id"] for r in result] == ids
    for item in result[1:]:
        assert item["state"] == "NOT_EVALUATED"
        assert item["authority_refs"] == [cdr.NETWORK_BUDGET_EXHAUSTED_REF]


def test_expired_shared_deadline_still_validates_dependency_contract():
    with pytest.raises(cdr.CriticalDataRuntimeIntegrityError, match="unknown capability"):
        cdr._capability_results(
            _definition(["cap.unknown"]), lake=None, ports=_ports([]),
            network_deadline=time.monotonic() - 1,
        )


def test_shared_deadline_accounts_for_earlier_campaign_time(monkeypatch):
    # A deterministic clock proves the second projection cannot reset its budget.
    clock = [10.0]
    monkeypatch.setattr(cdr.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cdr, "_CAPABILITY_WALL_CLOCK_BUDGET_SECONDS", 25.0)
    deadline = cdr.network_capability_deadline()
    assert deadline == 35.0
    first = cdr._capability_results(
        _definition([DISCLOSURES_ID]), lake=None, ports=_ports([DISCLOSURES_ID]),
        network_deadline=deadline,
    )
    assert first[0]["state"] == "USABLE"
    clock[0] = 35.0
    second = cdr._capability_results(
        _definition([DISCLOSURES_ID]), lake=None, ports=_ports([DISCLOSURES_ID]),
        network_deadline=deadline,
    )
    assert second[0]["state"] == "NOT_EVALUATED"


def test_late_worker_preserves_existing_diagnostic_observation_contract(monkeypatch, tmp_path):
    import threading
    import data_health_event_store as events
    import push2_guard

    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cdr, "_CAPABILITY_WALL_CLOCK_BUDGET_SECONDS", 0.05)
    release = threading.Event()
    finished = threading.Event()
    contexts = []

    def delayed(_lake, definition):
        release.wait(2)
        contexts.append(push2_guard.is_read_only())
        cdr.record_observation_event("announcements", "SUCCESS")
        finished.set()
        return _usable(DISCLOSURES_ID)

    try:
        with push2_guard.read_only():
            result = cdr._capability_results(
                _definition([DISCLOSURES_ID]), lake=None,
                ports=_ports([DISCLOSURES_ID], disclosures=delayed),
            )
        assert result[0]["state"] == "ERROR"
        assert not Path(events.events_path()).exists()
    finally:
        release.set()
    assert finished.wait(1)
    assert contexts == [True]
    # Existing observability is explicitly preserved; it is not decision authority.
    assert events.load_events_readonly()["announcements"]["last_success_at"]
    assert result[0]["state"] == "ERROR"
    assert not push2_guard.is_read_only()


@pytest.mark.parametrize("admitted", [False, True])
def test_snapshot_closure_atomically_owns_preempted_workers(monkeypatch, admitted):
    import linecache
    import threading

    paused, release, invoked = (threading.Event() for _ in range(3))
    worker_threads = []
    original_thread = threading.Thread

    class TracedThread(original_thread):
        def run(self):
            import sys

            def trace(frame, event, arg):
                if frame.f_code.co_name == "_worker" and event == "line":
                    line = linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip()
                    boundary = "result = _evaluate_capability(" if admitted else "with state_lock:"
                    if line == boundary and not paused.is_set():
                        paused.set()
                        release.wait(2)
                return trace

            sys.settrace(trace)
            try:
                super().run()
            finally:
                sys.settrace(None)

    def thread_factory(*args, **kwargs):
        thread = TracedThread(*args, **kwargs)
        worker_threads.append(thread)
        return thread

    def provider(_lake, definition):
        invoked.set()
        return _usable(DISCLOSURES_ID)

    monkeypatch.setattr(cdr.threading, "Thread", thread_factory)
    started = time.monotonic()
    try:
        result = cdr._capability_results(
            _definition([DISCLOSURES_ID]), lake=None,
            ports=_ports([DISCLOSURES_ID], disclosures=provider),
            network_deadline=started + 0.05,
        )
        assert time.monotonic() - started < 0.3
        assert paused.is_set()
        assert result[0]["state"] == ("ERROR" if admitted else "NOT_EVALUATED")
        assert not invoked.is_set()
    finally:
        release.set()
        for thread in worker_threads:
            thread.join(1)
            assert not thread.is_alive()
    # An admitted read can finish late; a closed, unadmitted worker cannot start.
    assert invoked.is_set() == admitted
    assert result[0]["state"] == ("ERROR" if admitted else "NOT_EVALUATED")


def test_early_join_return_keeps_remaining_budget_for_valid_completion(monkeypatch):
    import threading

    release = threading.Event()
    finished = threading.Event()
    join_calls = []
    original_join = threading.Thread.join

    def provider(_lake, definition):
        try:
            assert release.wait(2)
            return _usable(DISCLOSURES_ID)
        finally:
            finished.set()

    def early_then_complete(thread, timeout=None):
        if thread.name == "ccd-capability-cap.security.disclosures" and timeout is not None:
            join_calls.append(timeout)
            if len(join_calls) == 1:
                return  # A timed wait alone cannot prove the deadline elapsed.
            release.set()
        return original_join(thread, timeout)

    monkeypatch.setattr(threading.Thread, "join", early_then_complete)
    try:
        result = cdr._capability_results(
            _definition([DISCLOSURES_ID]), lake=None,
            ports=_ports([DISCLOSURES_ID], disclosures=provider),
            network_deadline=time.monotonic() + 0.5,
        )
        assert len(join_calls) >= 2
        assert result[0]["state"] == "USABLE"
        assert cdr.NETWORK_BUDGET_EXHAUSTED_REF not in result[0]["authority_refs"]
    finally:
        release.set()
        assert finished.wait(1)
