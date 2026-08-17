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
    if publication_id is not None and (
            type(publication_id) is not str or not publication_id.strip()
            or publication_id != publication_id.strip()):
        raise PriceReferenceCapabilityError(
            "publication_id must be canonical non-empty text or None"
        )
    _require_inputs(security_code, campaign_id, as_of)
    try:
        point = resolve_authoritative_price_point(
            lake=lake,
            security_code=security_code,
            as_of=as_of,
            security_exchange_policy_version=security_exchange_policy_version,
            publication_id=publication_id,
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
