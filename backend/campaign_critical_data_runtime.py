"""Shared Campaign-scoped Critical Data runtime.

This module owns the deterministic DDA -> capability adapters -> CCD
projection chain.  Decision Inbox and Decision Commit both consume this
runtime so that Critical Data has one authority graph and one literal
``as_of`` contract.  It deliberately does not import either product runtime,
router, or frontend code.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
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


def _capability_results(
    definition: Mapping[str, Any], *, lake: FactLake | None, ports: CriticalDataPorts
) -> list[Mapping[str, Any]]:
    results: list[Mapping[str, Any]] = []
    for dependency_id in definition.get("required_dependency_ids", []):
        if not isinstance(dependency_id, str) or not dependency_id:
            raise CriticalDataRuntimeIntegrityError(
                "required_dependency_ids contains an invalid element"
            )
        try:
            if dependency_id == price_adapter.DEPENDENCY_ID:
                result = (
                    _not_evaluated_result(dependency_id, definition["as_of"])
                    if lake is None
                    else ports.price_evaluator(lake, definition)
                )
            elif dependency_id == market_sector_adapter.DEPENDENCY_ID:
                result = ports.market_sector_evaluator(lake, definition)
            elif dependency_id == disclosures_adapter.DEPENDENCY_ID:
                result = ports.disclosures_evaluator(lake, definition)
            elif dependency_id == financials_adapter.DEPENDENCY_ID:
                result = ports.financials_evaluator(lake, definition)
            else:
                raise CriticalDataRuntimeIntegrityError(f"unknown capability: {dependency_id}")
        except (
            price_adapter.PriceReferenceCapabilityError,
            market_sector_adapter.MarketSectorCapabilityError,
            disclosures_adapter.DisclosuresCapabilityError,
            financials_adapter.FinancialsCapabilityError,
        ):
            result = _error_result(dependency_id, definition["as_of"])
        results.append(
            _validate_capability_result(
                result, dependency_id=dependency_id, as_of=definition["as_of"]
            )
        )
    return results


_UNSET = object()


def project_campaign_critical_data(
    *,
    campaign: Mapping[str, Any],
    as_of: str,
    ports: CriticalDataPorts = PRODUCTION_PORTS,
    lake: FactLake | None | object = _UNSET,
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
    results = _capability_results(definition, lake=lake_value, ports=ports)
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
