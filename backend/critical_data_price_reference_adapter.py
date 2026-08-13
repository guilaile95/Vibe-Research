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
    as_of_dt = _parse_utc(as_of)
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
        raise PriceReferenceCapabilityError("security exchange identity is invalid") from exc
    authority_ref = identity.get("authority_ref")
    if type(authority_ref) is str and authority_ref:
        refs.append(authority_ref)
    if identity.get("exchange_resolution_state") != "RESOLVED":
        return _result("NOT_EVALUATED", as_of, refs)
    exchange = identity.get("exchange")
    alias = _provider_alias(security_code, exchange)
    # SER1 proves routing only.  TCA1 currently proves SSE/SZSE sessions only;
    # legacy/current BSE aliases must therefore remain NOT_EVALUATED.
    if alias is None:
        return _result("NOT_EVALUATED", as_of, refs)
    refs.insert(1, CALENDAR_AUTHORITY_REF)
    refs.append(PROVIDER_ALIAS_AUTHORITY_REF)

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
        # A missing explicitly pinned id is absence of selection authority;
        # corrupt/ambiguous candidates remain an integrity error.
        return _result("NOT_EVALUATED", as_of, refs)
    except Exception:
        return _result("ERROR", as_of, refs)
    selected_ids = selection.selected_publication_ids
    if len(selected_ids) != 1:
        return _result("NOT_EVALUATED", as_of, refs)
    selected_id = selected_ids[0]
    selected = next(
        (item for item in candidates if item.publication_id == selected_id),
        None,
    )
    if selected is None:
        return _result("ERROR", as_of, refs)
    refs.extend((
        f"selection:{selection.schema_version}:{selection.selection_basis}",
        f"dataset:{DATASET_ID}:{DATASET_CONTRACT_REVISION}",
        f"publication:{selected_id}",
        f"observation:{selected.source_observation_id}",
        f"normalizer:{NORMALIZER_VERSION}",
        f"artifact-schema:{ARTIFACT_SCHEMA_VERSION}",
    ))

    observation = lake.get_observation(selected.source_observation_id)
    if observation is None:
        return _result("ERROR", as_of, refs)
    try:
        fetched_at = _parse_utc(observation.observation.fetched_at)
    except PriceReferenceCapabilityError:
        return _result("ERROR", as_of, refs)
    if fetched_at > as_of_dt:
        return _result("NOT_EVALUATED", as_of, refs)
    fetched_completed_date = completed_trade_date_at(
        observation.observation.fetched_at
    )
    if fetched_completed_date is None or fetched_completed_date < trade_date:
        # A completed-session close cannot be supported by a receipt captured
        # before that session completed.  This is a TCA1 chronology gate, not
        # a provider revision or PIT claim; later historical backfill remains
        # admissible when its receipt is visible by the caller's as_of.
        return _result("NOT_EVALUATED", as_of, refs)

    try:
        replay = verify_tushare_daily_normalization_replay(
            lake, selected.source_observation_id
        )
        if replay.status != "MATCH":
            return _result("ERROR", as_of, refs)
        evidence = collect_fact_lake_health_evidence(
            lake=lake,
            dataset_spec=TUSHARE_DAILY_DATASET_SPEC,
            request=HealthCollectionRequest(
                publication_id=selected_id,
                expected_primary_temporal_value=trade_date,
            ),
        )
        assessment = assess_publication_health(
            dataset_spec=TUSHARE_DAILY_DATASET_SPEC,
            evidence=replace(evidence, replay_state="MATCH"),
        )
        if assessment.canonical_admissibility == "BLOCKED":
            return _result("ERROR", as_of, refs)
        if assessment.canonical_admissibility != "USABLE":
            return _result("NOT_EVALUATED", as_of, refs)
        refs.extend((
            HEALTH_COLLECTION_AUTHORITY_REF,
            HEALTH_AUTHORITY_REF,
            REPLAY_AUTHORITY_REF,
        ))
        rows = query_tushare_daily(
            lake,
            trade_date,
            selection="publication",
            publication_id=selected_id,
        )
    except Exception:
        return _result("ERROR", as_of, refs)
    if len(rows) != 1:
        return _result("ERROR", as_of, refs)
    payload = rows[0].get("canonical_payload")
    if type(payload) is not dict or payload.get("trade_date") != trade_date:
        return _result("ERROR", as_of, refs)
    payload_rows = payload.get("rows")
    if type(payload_rows) is not list:
        return _result("ERROR", as_of, refs)
    target_rows = [
        row for row in payload_rows
        if type(row) is dict and row.get("ts_code") == alias
    ]
    if not target_rows:
        return _result("NOT_EVALUATED", as_of, refs)
    if len(target_rows) != 1:
        return _result("ERROR", as_of, refs)
    close = target_rows[0].get("close")
    if close is None:
        return _result("NOT_EVALUATED", as_of, refs)
    if type(close) not in (int, float) or isinstance(close, bool) \
            or not math.isfinite(close) or close <= 0:
        return _result("ERROR", as_of, refs)

    refs.append(f"security-row:{alias}:{trade_date}")
    return _result("USABLE", as_of, refs)


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
