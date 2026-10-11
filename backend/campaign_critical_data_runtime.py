"""Shared Campaign-scoped Critical Data runtime.

This module owns the deterministic DDA -> capability adapters -> CCD
projection chain.  Decision Inbox and Decision Commit both consume this
runtime so that Critical Data has one authority graph and one literal
``as_of`` contract.  It deliberately does not import either product runtime,
router, or frontend code.
"""

from __future__ import annotations

from contextvars import copy_context
from dataclasses import dataclass
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping

import critical_data_dependency_policy as dda
import critical_data_disclosures_adapter as disclosures_adapter
import critical_data_financials_adapter as financials_adapter
import critical_data_market_sector_adapter as market_sector_adapter
import critical_data_price_reference_adapter as price_adapter
from campaign_critical_data_projection import (
    project_campaign_critical_data as project_campaign_critical_data_projection,
)
from fact_lake_store import FactLake, open_existing_fact_lake
from security_exchange_policy import POLICY_VERSION_V01 as SER_POLICY_VERSION


DDA_POLICY_VERSION = dda.POLICY_VERSION_V01
_FACT_LAKE_ROOT_ENV = "VR_FACT_LAKE_ROOT"
_FACT_LAKE_CONTROL_FILE = "fact_lake_control.sqlite3"


class CriticalDataRuntimeError(RuntimeError):
    """Base shared Critical Data runtime error."""


class CriticalDataRuntimeIntegrityError(CriticalDataRuntimeError):
    """A DDA, capability, or CCD result violated its identity contract."""


CapabilityEvaluator = Callable[
    [FactLake | None, Mapping[str, Any]], Mapping[str, Any]
]


def _not_evaluated_result(dependency_id: str, as_of: str) -> dict[str, Any]:
    return {
        "dependency_id": dependency_id,
        "state": "NOT_EVALUATED",
        "as_of": as_of,
        "authority_refs": [],
    }


def _error_result(dependency_id: str, as_of: str) -> dict[str, Any]:
    return {
        "dependency_id": dependency_id,
        "state": "ERROR",
        "as_of": as_of,
        "authority_refs": [],
    }


def production_lake_provider() -> FactLake | None:
    """Return the existing readonly Fact Lake, or None when unavailable."""

    raw = os.environ.get(_FACT_LAKE_ROOT_ENV, "").strip()
    if not raw:
        return None
    root = Path(raw)
    if not (root / _FACT_LAKE_CONTROL_FILE).exists():
        return None
    return open_existing_fact_lake(root, readonly=True)


def production_price_evaluator(
    lake: FactLake, definition: Mapping[str, Any]
) -> dict[str, Any]:
    return price_adapter.evaluate_price_reference_capability(
        lake=lake,
        security_code=definition["security_code"],
        campaign_id=definition["campaign_id"],
        as_of=definition["as_of"],
        security_exchange_policy_version=SER_POLICY_VERSION,
    )


def record_observation_event(source_id: str, event: str) -> None:
    """Update existing Data Health observation state on production reads."""

    try:
        import data_health_event_store as event_store

        if event == "FAILURE":
            event_store.safe_call(
                event_store.record_failure, source_id, "SOURCE_UNAVAILABLE"
            )
        elif event == "PARTIAL":
            event_store.safe_call(event_store.record_partial, source_id)
        else:
            event_store.safe_call(event_store.record_success, source_id)
    except Exception:
        # Data Health is an observation side effect, never a CCD authority.
        pass


def production_market_sector_evaluator(
    lake: FactLake | None, definition: Mapping[str, Any]
) -> dict[str, Any]:
    result = market_sector_adapter.evaluate_market_sector_capability(
        security_code=definition["security_code"],
        campaign_id=definition["campaign_id"],
        as_of=definition["as_of"],
    )
    state = result["state"]
    record_observation_event(
        "sector_research",
        "FAILURE" if state == "ERROR" else "SUCCESS" if state == "USABLE" else "PARTIAL",
    )
    return result


def production_disclosures_evaluator(
    lake: FactLake | None, definition: Mapping[str, Any]
) -> dict[str, Any]:
    result = disclosures_adapter.evaluate_disclosures_capability(
        security_code=definition["security_code"],
        campaign_id=definition["campaign_id"],
        as_of=definition["as_of"],
    )
    state = result["state"]
    record_observation_event(
        "announcements",
        "FAILURE" if state == "ERROR" else "PARTIAL" if state == "UNKNOWN" else "SUCCESS",
    )
    return result


def production_financials_evaluator(
    lake: FactLake | None, definition: Mapping[str, Any]
) -> dict[str, Any]:
    result = financials_adapter.evaluate_financials_capability(
        security_code=definition["security_code"],
        campaign_id=definition["campaign_id"],
        as_of=definition["as_of"],
    )
    state = result["state"]
    record_observation_event(
        "financials",
        "FAILURE" if state == "ERROR" else "PARTIAL" if state == "UNKNOWN" else "SUCCESS",
    )
    return result


@dataclass(frozen=True)
class CriticalDataPorts:
    dependency_resolver: Callable[..., Mapping[str, Any]]
    price_evaluator: CapabilityEvaluator = production_price_evaluator
    market_sector_evaluator: CapabilityEvaluator = production_market_sector_evaluator
    disclosures_evaluator: CapabilityEvaluator = production_disclosures_evaluator
    financials_evaluator: CapabilityEvaluator = production_financials_evaluator
    lake_provider: Callable[[], FactLake | None] = production_lake_provider


PRODUCTION_PORTS = CriticalDataPorts(dependency_resolver=dda.resolve_strategy_dependencies)


def critical_data_ports_from(ports: Any) -> CriticalDataPorts:
    """Adapt an assembler-like runtime port object without importing it."""

    return CriticalDataPorts(
        dependency_resolver=ports.dependency_resolver,
        price_evaluator=ports.price_evaluator,
        market_sector_evaluator=ports.market_sector_evaluator,
        disclosures_evaluator=ports.disclosures_evaluator,
        financials_evaluator=ports.financials_evaluator,
        lake_provider=ports.lake_provider,
    )


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CriticalDataRuntimeIntegrityError(f"{label} must be a Mapping")
    return value


def _assert_identity(left: Mapping[str, Any], right: Mapping[str, Any], label: str) -> None:
    for key in ("security_code", "strategy", "campaign_id"):
        if left.get(key) != right.get(key):
            raise CriticalDataRuntimeIntegrityError(f"{label} identity mismatch on {key}")


def _assert_as_of(left: Any, right: str, label: str) -> None:
    if left != right:
        raise CriticalDataRuntimeIntegrityError(f"{label} as_of mismatch")


def _validate_capability_result(
    result: Any, *, dependency_id: str, as_of: str
) -> Mapping[str, Any]:
    result = _require_mapping(result, "capability result")
    if result.get("dependency_id") != dependency_id:
        raise CriticalDataRuntimeIntegrityError("capability dependency_id mismatch")
    _assert_as_of(result.get("as_of"), as_of, "capability result")
    return result


# 网络型 capability 共享的有界等待预算（秒）。外部 provider 决定下限时不许
# 无界挂起：共享截止时间到点仍未返回的 capability 如实记 ERROR（UNAVAILABLE
# 语义，与 provider failure 同形），其余 capability 判定不受影响。
_CAPABILITY_WALL_CLOCK_BUDGET_SECONDS = 25.0
NETWORK_BUDGET_EXHAUSTED_REF = "critical-data:network-budget-exhausted"


def network_capability_deadline() -> float:
    """One existing network wait budget, optionally shared by an Inbox snapshot."""
    return time.monotonic() + _CAPABILITY_WALL_CLOCK_BUDGET_SECONDS


_NETWORK_DEPENDENCY_IDS = (
    market_sector_adapter.DEPENDENCY_ID,
    disclosures_adapter.DEPENDENCY_ID,
    financials_adapter.DEPENDENCY_ID,
)


def _evaluate_capability(
    dependency_id: str,
    definition: Mapping[str, Any],
    *,
    lake: FactLake | None,
    ports: CriticalDataPorts,
) -> Mapping[str, Any]:
    try:
        if dependency_id == price_adapter.DEPENDENCY_ID:
            return (
                _not_evaluated_result(dependency_id, definition["as_of"])
                if lake is None
                else ports.price_evaluator(lake, definition)
            )
        if dependency_id == market_sector_adapter.DEPENDENCY_ID:
            return ports.market_sector_evaluator(lake, definition)
        if dependency_id == disclosures_adapter.DEPENDENCY_ID:
            return ports.disclosures_evaluator(lake, definition)
        return ports.financials_evaluator(lake, definition)
    except (
        price_adapter.PriceReferenceCapabilityError,
        market_sector_adapter.MarketSectorCapabilityError,
        disclosures_adapter.DisclosuresCapabilityError,
        financials_adapter.FinancialsCapabilityError,
    ):
        return _error_result(dependency_id, definition["as_of"])


def _capability_results(
    definition: Mapping[str, Any], *, lake: FactLake | None, ports: CriticalDataPorts,
    network_deadline: float | None = None,
) -> list[Mapping[str, Any]]:
    """评估本 Campaign 全部 capability；网络型并发，结果顺序保持声明序。

    price_reference 读本地 Fact Lake（DuckDB 句柄不可跨线程共享），在调用
    线程内联评估；market_sector / disclosures / financials 是互相独立的真实
    外部读取，串行时端到端延迟为三者之和（慢网下可达分钟级），因此并发执行，
    共享同一 wall-clock 预算。到点未返回的 capability 记 ERROR；迟到的 worker
    结果被丢弃（既有 Data Health 诊断事件仍可能晚到，但不是 CCD authority）。
    调用方可共享 network_deadline；到期或关闭后不再接纳新读取，明确 NOT_EVALUATED。
    """
    dependency_ids: list[Any] = definition.get("required_dependency_ids", [])
    known_ids = {price_adapter.DEPENDENCY_ID, *_NETWORK_DEPENDENCY_IDS}
    for dependency_id in dependency_ids:
        if not isinstance(dependency_id, str) or not dependency_id:
            raise CriticalDataRuntimeIntegrityError(
                "required_dependency_ids contains an invalid element"
            )
        if dependency_id not in known_ids:
            raise CriticalDataRuntimeIntegrityError(f"unknown capability: {dependency_id}")

    results: dict[str, Mapping[str, Any]] = {}
    network_ids = [d for d in dependency_ids if d in _NETWORK_DEPENDENCY_IDS]
    deadline = network_capability_deadline() if network_deadline is None else network_deadline

    # daemon 线程：预算耗尽后被放弃的 provider 读取不得阻塞解释器退出。
    worker_errors: list[BaseException] = []
    threads: list[threading.Thread] = []
    started_ids: set[str] = set()
    state_lock = threading.Lock()
    closed = False

    def _worker(dependency_id: str) -> None:
        # Admission and snapshot closure share one ownership boundary. An
        # admitted worker is pending/ERROR if late; a closed request cannot
        # admit an unstarted worker. Never hold this lock during provider I/O.
        with state_lock:
            if closed or time.monotonic() >= deadline:
                return
            started_ids.add(dependency_id)
        try:
            result = _evaluate_capability(
                dependency_id, definition, lake=None, ports=ports
            )
            with state_lock:
                if not closed and time.monotonic() <= deadline:
                    results[dependency_id] = result
        except BaseException as exc:  # noqa: BLE001 - 与串行路径同语义向上传播
            with state_lock:
                if not closed and time.monotonic() <= deadline:
                    worker_errors.append(exc)

    for network_id in network_ids:
        if time.monotonic() >= deadline:
            break
        thread = threading.Thread(
            # Each worker gets its own copy: preserve request-local source
            # read-only scope without leaking it to concurrent writable requests.
            target=copy_context().run,
            args=(_worker, network_id),
            name=f"ccd-capability-{network_id}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            thread.join(timeout=remaining)
    with state_lock:
        closed = True
        completed_results = dict(results)
        admitted_ids = frozenset(started_ids)
        completed_errors = list(worker_errors)
    if completed_errors:
        raise completed_errors[0]

    ordered: list[Mapping[str, Any]] = []
    for dependency_id in dependency_ids:
        if dependency_id == price_adapter.DEPENDENCY_ID:
            result = _evaluate_capability(
                dependency_id, definition, lake=lake, ports=ports
            )
        elif dependency_id in completed_results:
            result = completed_results[dependency_id]
        else:
            # 共享预算内未返回：如实 UNAVAILABLE，不等待迟到 worker。
            result = (
                _error_result(dependency_id, definition["as_of"])
                if dependency_id in admitted_ids
                else _not_evaluated_result(dependency_id, definition["as_of"])
            )
            result["authority_refs"] = [NETWORK_BUDGET_EXHAUSTED_REF]
        ordered.append(
            _validate_capability_result(
                result, dependency_id=dependency_id, as_of=definition["as_of"]
            )
        )
    return ordered


_UNSET = object()


def project_campaign_critical_data(
    *,
    campaign: Mapping[str, Any],
    as_of: str,
    ports: CriticalDataPorts = PRODUCTION_PORTS,
    lake: FactLake | None | object = _UNSET,
    network_deadline: float | None = None,
) -> Mapping[str, Any]:
    """Resolve and project the real Campaign-scoped CCD authority."""

    campaign = _require_mapping(campaign, "campaign")
    definition = _require_mapping(
        ports.dependency_resolver(
            security_code=campaign["security_code"],
            strategy=campaign["strategy"],
            campaign_id=campaign["campaign_id"],
            as_of=as_of,
            policy_version=DDA_POLICY_VERSION,
        ),
        "DDA definition",
    )
    _assert_identity(definition, campaign, "DDA")
    _assert_as_of(definition.get("as_of"), as_of, "DDA")
    lake_value = ports.lake_provider() if lake is _UNSET else lake
    results = _capability_results(
        definition, lake=lake_value, ports=ports, network_deadline=network_deadline
    )
    ccd = _require_mapping(
        project_campaign_critical_data_projection(
            security_code=definition["security_code"],
            strategy=definition["strategy"],
            campaign_id=definition["campaign_id"],
            as_of=definition["as_of"],
            dependency_set_state=definition["dependency_set_state"],
            dependency_set_authority_refs=definition["dependency_set_authority_refs"],
            required_dependency_ids=definition["required_dependency_ids"],
            dependency_results=results,
        ),
        "CCD projection",
    )
    _assert_identity(ccd, campaign, "CCD")
    _assert_as_of(ccd.get("as_of"), as_of, "CCD")
    return ccd


__all__ = [
    "CapabilityEvaluator",
    "CriticalDataPorts",
    "CriticalDataRuntimeError",
    "CriticalDataRuntimeIntegrityError",
    "DDA_POLICY_VERSION",
    "PRODUCTION_PORTS",
    "critical_data_ports_from",
    "project_campaign_critical_data",
]
