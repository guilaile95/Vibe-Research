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
    assert by_id[FINANCIALS_ID]["authority_refs"] == []
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
