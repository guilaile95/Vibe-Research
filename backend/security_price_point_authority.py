"""CF1 shared, read-only PIT security close authority.

This module extracts the truth-producing part of the existing CCD price
reference adapter.  It proves one completed-session close that was visible by
an explicit ``as_of``.  It never calls a provider, writes Fact Lake, chooses a
provider-revision winner, or claims that local publication order is PIT truth.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import math
import re
from typing import Any, Callable

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


SCHEMA_VERSION = "security_price_point_authority.v0.1"
HEALTH_AUTHORITY_REF = f"health:{HEALTH_SCHEMA_VERSION}"
HEALTH_COLLECTION_AUTHORITY_REF = "health-collection:fact-lake-health-adapter:v0.1"
REPLAY_AUTHORITY_REF = f"replay:{DATASET_ID}:{NORMALIZER_VERSION}"
PROVIDER_ALIAS_AUTHORITY_REF = (
    "critical_data_adapter:tushare_daily_exchange_alias:v0.1"
)

PRICE_POINT_STATES = ("USABLE", "NOT_EVALUATED", "ERROR")
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_SECURITY_CODE_RE = re.compile(r"^[0-9]{6}$")


class PricePointAuthorityError(RuntimeError):
    """Invalid authority input or a non-recoverable authority failure."""


def _parse_utc(value: Any, field: str) -> datetime:
    if type(value) is not str or _UTC_ZERO_OFFSET_RE.fullmatch(value) is None:
        raise PricePointAuthorityError(
            f"{field} must be a canonical zero-offset UTC instant"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PricePointAuthorityError(f"{field} is not a real UTC instant") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise PricePointAuthorityError(f"{field} must be zero-offset UTC")
    return parsed


def _require_inputs(
    lake: FactLake,
    security_code: str,
    as_of: str,
    security_exchange_policy_version: str,
    publication_id: str | None,
) -> datetime:
    if not isinstance(lake, FactLake) or not lake.readonly:
        raise PricePointAuthorityError("price point authority requires a readonly Fact Lake")
    if type(security_code) is not str or _SECURITY_CODE_RE.fullmatch(security_code) is None:
        raise PricePointAuthorityError("security_code must be six ASCII digits")
    if type(security_exchange_policy_version) is not str \
            or not security_exchange_policy_version.strip():
        raise PricePointAuthorityError("security_exchange_policy_version is required")
    if publication_id is not None and (
        type(publication_id) is not str
        or not publication_id.strip()
        or publication_id != publication_id.strip()
    ):
        raise PricePointAuthorityError(
            "publication_id must be canonical non-empty text or None"
        )
    return _parse_utc(as_of, "as_of")


def _provider_alias(security_code: str, exchange: str) -> str | None:
    if exchange == "SSE":
        return f"{security_code}.SH"
    if exchange == "SZSE":
        return f"{security_code}.SZ"
    return None


def _result(
    *,
    state: str,
    security_code: str,
    exchange: str | None,
    provider_alias: str | None,
    as_of: str,
    trade_date: str | None,
    close: float | int | None,
    publication_id: str | None,
    source_observation_id: str | None,
    observation_fetched_at: str | None,
    refs: list[str],
    reasons: list[str],
) -> dict[str, Any]:
    if state not in PRICE_POINT_STATES:
        raise RuntimeError(f"invalid price point state: {state!r}")
    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "security_code": security_code,
        "exchange": exchange,
        "provider_alias": provider_alias,
        "as_of": as_of,
        "trade_date": trade_date,
        "close": close,
        "publication_id": publication_id,
        "source_observation_id": source_observation_id,
        "observation_fetched_at": observation_fetched_at,
        "authority_refs": list(dict.fromkeys(refs)),
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def resolve_authoritative_price_point(
    *,
    lake: FactLake,
    security_code: str,
    as_of: str,
    security_exchange_policy_version: str,
    publication_id: str | None = None,
    replay_verifier: Callable[[FactLake, str], Any] | None = None,
) -> dict[str, Any]:
    """Prove one close visible by ``as_of`` using immutable Fact Lake data.

    Publication visibility is evaluated before publication selection.  Thus a
    later-fetched backfill cannot support an earlier point, while a later
    evaluation may use a publication that was not yet visible at the decision
    boundary.  Unpinned visible publication ambiguity is deliberately left
    ``NOT_EVALUATED`` because Q1 provides no provider-revision winner.
    """
    as_of_dt = _require_inputs(
        lake,
        security_code,
        as_of,
        security_exchange_policy_version,
        publication_id,
    )
    replay_verifier = replay_verifier or verify_tushare_daily_normalization_replay
    refs: list[str] = []
    trade_date = completed_trade_date_at(as_of)
    if trade_date is None:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=None,
            provider_alias=None,
            as_of=as_of,
            trade_date=None,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=["NO_COMPLETED_TRADE_DATE"],
        )
    refs.append(CALENDAR_AUTHORITY_REF)

    try:
        identity = resolve_security_exchange(
            security_code=security_code,
            policy_version=security_exchange_policy_version,
        )
    except Exception as exc:
        raise PricePointAuthorityError("security exchange identity is invalid") from exc
    authority_ref = identity.get("authority_ref")
    if type(authority_ref) is str and authority_ref:
        refs.append(authority_ref)
    if identity.get("exchange_resolution_state") != "RESOLVED":
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=identity.get("exchange"),
            provider_alias=None,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=["UNRESOLVED_SECURITY_EXCHANGE"],
        )
    exchange = identity.get("exchange")
    alias = _provider_alias(security_code, exchange)
    if alias is None:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=exchange,
            provider_alias=None,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=["UNSUPPORTED_EXCHANGE_PROVIDER_PATH"],
        )
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
    except Exception as exc:
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=["FACT_LAKE_PUBLICATION_READ_FAILED"],
        )

    visible: list[Any] = []
    observation_by_publication: dict[str, Any] = {}
    for candidate in candidates:
        try:
            observation = lake.get_observation(candidate.source_observation_id)
        except Exception:
            return _result(
                state="ERROR",
                security_code=security_code,
                exchange=exchange,
                provider_alias=alias,
                as_of=as_of,
                trade_date=trade_date,
                close=None,
                publication_id=None,
                source_observation_id=None,
                observation_fetched_at=None,
                refs=refs,
                reasons=["FACT_LAKE_OBSERVATION_READ_FAILED"],
            )
        if observation is None:
            return _result(
                state="ERROR",
                security_code=security_code,
                exchange=exchange,
                provider_alias=alias,
                as_of=as_of,
                trade_date=trade_date,
                close=None,
                publication_id=None,
                source_observation_id=None,
                observation_fetched_at=None,
                refs=refs,
                reasons=["SOURCE_OBSERVATION_MISSING"],
            )
        fetched_at = observation.observation.fetched_at
        try:
            fetched_dt = _parse_utc(fetched_at, "observation.fetched_at")
        except PricePointAuthorityError:
            return _result(
                state="ERROR",
                security_code=security_code,
                exchange=exchange,
                provider_alias=alias,
                as_of=as_of,
                trade_date=trade_date,
                close=None,
                publication_id=None,
                source_observation_id=None,
                observation_fetched_at=fetched_at,
                refs=refs,
                reasons=["SOURCE_OBSERVATION_TIMESTAMP_INVALID"],
            )
        observation_by_publication[candidate.publication_id] = observation
        if fetched_dt <= as_of_dt:
            visible.append(candidate)

    if publication_id is not None:
        visible = [item for item in visible if item.publication_id == publication_id]
        mode = PublicationSelectionMode.PUBLICATION_ID
    else:
        mode = PublicationSelectionMode.ALL
    if not visible:
        reason = (
            "PUBLICATION_NOT_VISIBLE_BY_AS_OF"
            if publication_id is not None or candidates
            else "NO_VISIBLE_PUBLICATION"
        )
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=[reason],
        )

    try:
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
            tuple(visible),
        )
    except PublicationSelectionNotFoundError:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=["PUBLICATION_NOT_VISIBLE_BY_AS_OF"],
        )
    except Exception:
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=["PUBLICATION_SELECTION_FAILED"],
        )
    selected_ids = selection.selected_publication_ids
    if len(selected_ids) != 1:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=["MULTIPLE_VISIBLE_PUBLICATIONS_NO_WINNER"],
        )
    selected_id = selected_ids[0]
    selected = next(
        (item for item in visible if item.publication_id == selected_id),
        None,
    )
    if selected is None:
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=None,
            source_observation_id=None,
            observation_fetched_at=None,
            refs=refs,
            reasons=["SELECTED_PUBLICATION_MISSING"],
        )
    observation = observation_by_publication[selected_id]
    refs.extend((
        f"selection:{selection.schema_version}:{selection.selection_basis}",
        f"dataset:{DATASET_ID}:{DATASET_CONTRACT_REVISION}",
        f"publication:{selected_id}",
        f"observation:{selected.source_observation_id}",
        f"normalizer:{NORMALIZER_VERSION}",
        f"artifact-schema:{ARTIFACT_SCHEMA_VERSION}",
    ))
    fetched_at = observation.observation.fetched_at
    fetched_completed_date = completed_trade_date_at(fetched_at)
    if fetched_completed_date is None or fetched_completed_date < trade_date:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["SOURCE_OBSERVATION_BEFORE_SESSION_COMPLETION"],
        )

    try:
        replay = replay_verifier(lake, selected.source_observation_id)
        if replay.status != "MATCH":
            return _result(
                state="ERROR",
                security_code=security_code,
                exchange=exchange,
                provider_alias=alias,
                as_of=as_of,
                trade_date=trade_date,
                close=None,
                publication_id=selected_id,
                source_observation_id=selected.source_observation_id,
                observation_fetched_at=fetched_at,
                refs=refs,
                reasons=["NORMALIZATION_REPLAY_FAILED"],
            )
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
            return _result(
                state="ERROR",
                security_code=security_code,
                exchange=exchange,
                provider_alias=alias,
                as_of=as_of,
                trade_date=trade_date,
                close=None,
                publication_id=selected_id,
                source_observation_id=selected.source_observation_id,
                observation_fetched_at=fetched_at,
                refs=refs,
                reasons=["PUBLICATION_HEALTH_BLOCKED"],
            )
        if assessment.canonical_admissibility != "USABLE":
            return _result(
                state="NOT_EVALUATED",
                security_code=security_code,
                exchange=exchange,
                provider_alias=alias,
                as_of=as_of,
                trade_date=trade_date,
                close=None,
                publication_id=selected_id,
                source_observation_id=selected.source_observation_id,
                observation_fetched_at=fetched_at,
                refs=refs,
                reasons=["PUBLICATION_HEALTH_NOT_USABLE"],
            )
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
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["PRICE_POINT_EVIDENCE_READ_FAILED"],
        )
    if len(rows) != 1:
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["CANONICAL_PUBLICATION_ROW_INVALID"],
        )
    payload = rows[0].get("canonical_payload")
    if type(payload) is not dict or payload.get("trade_date") != trade_date:
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["CANONICAL_PAYLOAD_INVALID"],
        )
    payload_rows = payload.get("rows")
    if type(payload_rows) is not list:
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["CANONICAL_PAYLOAD_ROWS_INVALID"],
        )
    target_rows = [
        row for row in payload_rows
        if type(row) is dict and row.get("ts_code") == alias
    ]
    if not target_rows:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["SECURITY_ROW_MISSING"],
        )
    if len(target_rows) != 1:
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["SECURITY_ROW_DUPLICATE"],
        )
    close = target_rows[0].get("close")
    if close is None:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["SECURITY_CLOSE_MISSING"],
        )
    if type(close) not in (int, float) or isinstance(close, bool) \
            or not math.isfinite(close) or close <= 0:
        return _result(
            state="ERROR",
            security_code=security_code,
            exchange=exchange,
            provider_alias=alias,
            as_of=as_of,
            trade_date=trade_date,
            close=None,
            publication_id=selected_id,
            source_observation_id=selected.source_observation_id,
            observation_fetched_at=fetched_at,
            refs=refs,
            reasons=["SECURITY_CLOSE_INVALID"],
        )
    refs.append(f"security-row:{alias}:{trade_date}")
    return _result(
        state="USABLE",
        security_code=security_code,
        exchange=exchange,
        provider_alias=alias,
        as_of=as_of,
        trade_date=trade_date,
        close=close,
        publication_id=selected_id,
        source_observation_id=selected.source_observation_id,
        observation_fetched_at=fetched_at,
        refs=refs,
        reasons=[],
    )


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "DATASET_CONTRACT_REVISION",
    "DATASET_ID",
    "HEALTH_AUTHORITY_REF",
    "HEALTH_COLLECTION_AUTHORITY_REF",
    "NORMALIZER_VERSION",
    "PRICE_POINT_STATES",
    "PricePointAuthorityError",
    "PROVIDER_ALIAS_AUTHORITY_REF",
    "REPLAY_AUTHORITY_REF",
    "SCHEMA_VERSION",
    "resolve_authoritative_price_point",
]
