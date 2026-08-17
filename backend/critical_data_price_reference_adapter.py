"""P0-CDA1A — deterministic price-reference capability adapter.

This module composes existing authorities.  It does not select a provider,
invent market dates, infer suspension, or claim point-in-time reconstruction.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import math
import re
from typing import Any

from critical_data_dependency_policy import CAP_SECURITY_PRICE_REFERENCE
from data_contracts import TemporalSemantics
from fact_lake_health import SCHEMA_VERSION as HEALTH_SCHEMA_VERSION
from fact_lake_health import assess_publication_health
from fact_lake_health_adapter import (
    HealthCollectionRequest,
    collect_fact_lake_health_evidence,
)
from fact_lake_publication_selection import (
    PublicationSelectionMode,
    PublicationSelectionNotFoundError,
    PublicationSelectionRequest,
    select_canonical_publications,
)
from fact_lake_store import FactLake
from security_price_point_authority import (
    PricePointAuthorityError,
    resolve_authoritative_price_point,
)
from security_exchange_policy import resolve_security_exchange
from trade_calendar import CALENDAR_AUTHORITY_REF, completed_trade_date_at
from tushare_daily_shadow import (
    ARTIFACT_SCHEMA_VERSION,
    DATASET_CONTRACT_REVISION,
    DATASET_ID,
    NORMALIZER_VERSION,
    TUSHARE_DAILY_DATASET_SPEC,
    query_tushare_daily,
    verify_tushare_daily_normalization_replay,
)


DEPENDENCY_ID = CAP_SECURITY_PRICE_REFERENCE
ADAPTER_AUTHORITY_REF = "critical_data:price_reference:v0.1"
PROVIDER_ALIAS_AUTHORITY_REF = (
    "critical_data_adapter:tushare_daily_exchange_alias:v0.1"
)
HEALTH_AUTHORITY_REF = f"health:{HEALTH_SCHEMA_VERSION}"
HEALTH_COLLECTION_AUTHORITY_REF = "health-collection:fact-lake-health-adapter:v0.1"
REPLAY_AUTHORITY_REF = f"replay:{DATASET_ID}:{NORMALIZER_VERSION}"
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)


class PriceReferenceCapabilityError(RuntimeError):
    """The capability evaluation input or authority chain is invalid."""


def _result(state: str, as_of: str, refs: list[str]) -> dict[str, Any]:
    return {
        "dependency_id": DEPENDENCY_ID,
        "state": state,
        "as_of": as_of,
        "authority_refs": list(dict.fromkeys(refs)),
    }


def _require_inputs(security_code: str, campaign_id: str, as_of: str) -> None:
    if type(security_code) is not str \
            or re.fullmatch(r"[0-9]{6}", security_code) is None:
        raise PriceReferenceCapabilityError("security_code must be six ASCII digits")
    if type(campaign_id) is not str \
            or _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise PriceReferenceCapabilityError("campaign_id is invalid")
    if type(as_of) is not str:
        raise PriceReferenceCapabilityError("as_of must be a UTC instant")


def _parse_utc(as_of: str) -> datetime:
    if _UTC_ZERO_OFFSET_RE.fullmatch(as_of) is None:
        raise PriceReferenceCapabilityError("as_of must be a canonical UTC instant")
    try:
        parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PriceReferenceCapabilityError("as_of must be a UTC instant") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise PriceReferenceCapabilityError("as_of must be zero-offset UTC")
    return parsed


def _provider_alias(security_code: str, exchange: str) -> str | None:
    if exchange == "SSE":
        return f"{security_code}.SH"
    if exchange == "SZSE":
        return f"{security_code}.SZ"
    return None


def _legacy_selection_preflight(
    *,
    lake: FactLake,
    security_code: str,
    trade_date: str,
    publication_id: str | None,
) -> tuple[str, str | None]:
    """Preserve CCD/Q1 selection before CF1 visibility filtering.

    CCD's frozen contract selects over every committed publication at the
    coordinate.  CF1's shared authority intentionally filters by
    ``fetched_at <= as_of`` first, so the adapter must keep this preflight
    separate rather than inherit the stronger CF1 ambiguity semantics.
    """
    canonical_key = f"{DATASET_ID}:{trade_date}"
    try:
        candidates = tuple(
            item for item in lake.list_canonical_publications(
                dataset_id=DATASET_ID,
                primary_temporal_field=TemporalSemantics.TRADE_DATE,
                primary_temporal_value=trade_date,
            )
            if item.canonical_key == canonical_key
        )
        mode = (
            PublicationSelectionMode.PUBLICATION_ID
            if publication_id is not None
            else PublicationSelectionMode.ALL
        )
        selection = select_canonical_publications(
            TUSHARE_DAILY_DATASET_SPEC,
            PublicationSelectionRequest(
                dataset_id=DATASET_ID,
                canonical_key=canonical_key,
                primary_temporal_field=TemporalSemantics.TRADE_DATE,
                primary_temporal_value=trade_date,
                mode=mode,
                publication_id=publication_id,
                as_of=None,
            ),
            candidates,
        )
    except PublicationSelectionNotFoundError:
        return "NOT_EVALUATED", None
    except Exception:
        return "ERROR", None
    if len(selection.selected_publication_ids) != 1:
        return "NOT_EVALUATED", None
    return "SELECTED", selection.selected_publication_ids[0]


def evaluate_price_reference_capability(
    *,
    lake: FactLake,
    security_code: str,
    campaign_id: str,
    as_of: str,
    security_exchange_policy_version: str,
    publication_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate one CCD1 dependency result using positive proof only."""
    if not isinstance(lake, FactLake):
        raise PriceReferenceCapabilityError("lake must be FactLake")
    if not lake.readonly:
        raise PriceReferenceCapabilityError(
            "capability evaluation requires a readonly lake"
        )
    if publication_id is not None and (
            type(publication_id) is not str or not publication_id.strip()
            or publication_id != publication_id.strip()):
        raise PriceReferenceCapabilityError(
            "publication_id must be canonical non-empty text or None"
        )
    _require_inputs(security_code, campaign_id, as_of)
    _parse_utc(as_of)
    refs = [ADAPTER_AUTHORITY_REF]
    trade_date = completed_trade_date_at(as_of)
    if trade_date is None:
        return _result("NOT_EVALUATED", as_of, refs)
    try:
        identity = resolve_security_exchange(
            security_code=security_code,
            policy_version=security_exchange_policy_version,
        )
    except Exception as exc:
        raise PriceReferenceCapabilityError(
            "security exchange identity is invalid"
        ) from exc
    authority_ref = identity.get("authority_ref")
    if type(authority_ref) is str and authority_ref:
        refs.append(authority_ref)
    if identity.get("exchange_resolution_state") != "RESOLVED":
        return _result("NOT_EVALUATED", as_of, refs)
    alias = _provider_alias(security_code, identity.get("exchange"))
    if alias is None:
        return _result("NOT_EVALUATED", as_of, refs)
    refs.insert(1, CALENDAR_AUTHORITY_REF)
    refs.append(PROVIDER_ALIAS_AUTHORITY_REF)
    selection_state, selected_publication_id = _legacy_selection_preflight(
        lake=lake,
        security_code=security_code,
        trade_date=trade_date,
        publication_id=publication_id,
    )
    if selection_state != "SELECTED":
        return _result(selection_state, as_of, refs)
    try:
        point = resolve_authoritative_price_point(
            lake=lake,
            security_code=security_code,
            as_of=as_of,
            security_exchange_policy_version=security_exchange_policy_version,
            publication_id=selected_publication_id,
            replay_verifier=verify_tushare_daily_normalization_replay,
        )
    except PricePointAuthorityError as exc:
        raise PriceReferenceCapabilityError(str(exc)) from exc
    point_refs = list(point["authority_refs"])
    # Preserve the established CCD outward contract: unresolved/BSE routing
    # stops before CCD claims the calendar authority, even though the shared
    # primitive may use the calendar to establish its neutral boundary.
    if point.get("provider_alias") is None and point["state"] == "NOT_EVALUATED":
        point_refs = [ref for ref in point_refs if ref != CALENDAR_AUTHORITY_REF]
    if publication_id is None:
        point_refs = [
            ref.replace(":exact_publication_id", ":all_committed")
            if ref.startswith("selection:")
            else ref
            for ref in point_refs
        ]
    return _result(point["state"], as_of, [ADAPTER_AUTHORITY_REF, *point_refs])


__all__ = [
    "ADAPTER_AUTHORITY_REF",
    "DEPENDENCY_ID",
    "HEALTH_COLLECTION_AUTHORITY_REF",
    "HEALTH_AUTHORITY_REF",
    "PROVIDER_ALIAS_AUTHORITY_REF",
    "PriceReferenceCapabilityError",
    "REPLAY_AUTHORITY_REF",
    "evaluate_price_reference_capability",
]
