"""Real Q1 → H2 → H1 → H3 cross-chain integration (tmp FactLake only).

Proves selected publication identity flows into health collection/assessment
and legacy projection without inventing publication_ids or washing semantics.
"""

from __future__ import annotations

import json

import pytest

import fact_lake_health_adapter as flha
import fact_lake_health_legacy_projection as flhp
from data_contracts import TemporalSemantics
from fact_lake_health import assess_publication_health
from fact_lake_publication_selection import (
    PublicationSelectionMode,
    PublicationSelectionRequest,
    select_canonical_publications,
)
from fact_lake_store import initialize_fact_lake, open_existing_fact_lake, payload_sha256
from tushare_daily_shadow import (
    DAILY_FIELD_MANIFEST,
    DATASET_ID,
    TUSHARE_DAILY_DATASET_SPEC,
    TushareDailyRawResponseCapture,
    TushareDailyRequestContract,
    build_request_fingerprint,
    build_tushare_daily_canonical_fact,
    persist_tushare_daily_evidence,
    publish_tushare_daily_canonical_fact,
)


TRADE_DATE = "2026-07-30"


def _row(
    *,
    ts_code: str = "600519.SH",
    trade_date: str = "20260730",
    close: object = 1800.0,
    pct_chg: object = 1.5,
    **overrides,
) -> list[object]:
    values = {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": 1780.0,
        "high": 1810.0,
        "low": 1775.0,
        "close": close,
        "pre_close": 1773.4,
        "change": 26.6,
        "pct_chg": pct_chg,
        "vol": 35000.0,
        "amount": 6280000.0,
    }
    values.update(overrides)
    return [values[field] for field in DAILY_FIELD_MANIFEST]


def _raw(
    rows: list[list[object]] | None = None,
    *,
    fields: tuple[str, ...] = DAILY_FIELD_MANIFEST,
    code: int = 0,
) -> bytes:
    return json.dumps(
        {
            "code": code,
            "msg": "synthetic",
            "data": {
                "fields": list(fields),
                "items": [_row()] if rows is None else rows,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _capture(raw: bytes, event: int = 1) -> TushareDailyRawResponseCapture:
    contract = TushareDailyRequestContract(TRADE_DATE)
    return TushareDailyRawResponseCapture(
        capture_event_id=f"capture-{event:032x}",
        contract=contract,
        raw_bytes=raw,
        request_fingerprint=build_request_fingerprint(contract),
        source_payload_hash=payload_sha256(raw),
        http_status=200,
        content_type="application/json; charset=utf-8",
        fetched_at="2026-07-30T08:00:00.000000Z",
    )


def _persist_and_publish(lake, raw: bytes, event: int):
    observation, normalization = persist_tushare_daily_evidence(
        lake,
        _capture(raw, event),
    )
    fact = build_tushare_daily_canonical_fact(
        observation.observation,
        normalization,
    )
    return publish_tushare_daily_canonical_fact(lake, fact)


def _selection_request(mode: PublicationSelectionMode, publication_id=None):
    return PublicationSelectionRequest(
        dataset_id=DATASET_ID,
        canonical_key=f"{DATASET_ID}:{TRADE_DATE}",
        primary_temporal_field=TemporalSemantics.TRADE_DATE,
        primary_temporal_value=TRADE_DATE,
        mode=mode,
        publication_id=publication_id,
        as_of=None,
    )


def test_q1_local_latest_to_h2_h1_h3_selected_publication_chain(tmp_path):
    """Case A: multi-vintage COMMITTED → LOCAL_LATEST → H2/H1/H3 on selected id."""
    root = tmp_path / "lake"
    write_lake = initialize_fact_lake(root)

    first = _persist_and_publish(write_lake, _raw([_row()]), event=1)
    second = _persist_and_publish(
        write_lake,
        _raw([_row(), _row(ts_code="000001.SZ", close=12.5)]),
        event=2,
    )
    third = _persist_and_publish(
        write_lake,
        _raw([_row(ts_code="000001.SZ", close=12.5)]),
        event=3,
    )
    assert first.vintage_sequence == 1
    assert second.vintage_sequence == 2
    assert third.vintage_sequence == 3
    assert third.vintage_sequence > second.vintage_sequence > first.vintage_sequence

    # Re-open read-only for health path (H2 requires non-writable handle).
    lake = open_existing_fact_lake(root)
    candidates = lake.list_canonical_publications(
        dataset_id=DATASET_ID,
        primary_temporal_field=TemporalSemantics.TRADE_DATE,
        primary_temporal_value=TRADE_DATE,
    )
    assert len(candidates) == 3
    assert {c.vintage_sequence for c in candidates} == {1, 2, 3}
    assert TUSHARE_DAILY_DATASET_SPEC.revision_semantics.value.lower() == "unknown"

    selection = select_canonical_publications(
        TUSHARE_DAILY_DATASET_SPEC,
        _selection_request(PublicationSelectionMode.LOCAL_LATEST),
        candidates,
    )
    assert selection.selected_publication_ids == (third.publication_id,)
    assert selection.selected_vintage_sequences == (3,)
    assert selection.provider_revision_claim == "NONE"
    assert selection.point_in_time_claim == "NONE"
    assert selection.revision_semantics.lower() == "unknown"
    # Local vintage selection is not a provider-revision or PIT authority claim.
    assert selection.selection_basis == "local_vintage_sequence"

    selected_id = selection.selected_publication_ids[0]
    assert selected_id == third.publication_id
    assert selected_id != first.publication_id

    request = flha.HealthCollectionRequest(publication_id=selected_id)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=lake,
        dataset_spec=TUSHARE_DAILY_DATASET_SPEC,
        request=request,
    )
    assert evidence.publication_id == selected_id

    assessment = assess_publication_health(
        dataset_spec=TUSHARE_DAILY_DATASET_SPEC,
        evidence=evidence,
    )
    assert assessment.publication_id == selected_id
    assert assessment.dataset_id == DATASET_ID
    assert assessment.canonical_admissibility in {
        "USABLE",
        "USABLE_WITH_WARNING",
        "BLOCKED",
    }

    legacy = flhp.project_fact_lake_health(assessment=assessment)
    assert legacy.legacy_status in {"normal", "partial", "unavailable"}
    assert legacy.fact_lake_canonical_admissibility == assessment.canonical_admissibility
    assert legacy.source_kind == flhp.SOURCE_KIND_ASSESSMENT


def test_q1_local_latest_empty_selection_does_not_fabricate_publication(tmp_path):
    """Case B: empty LOCAL_LATEST → no publication_id, no implicit healthy H2 path."""
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    # Empty lake at target coordinate: no COMMITTED publications for TRADE_DATE.
    lake = open_existing_fact_lake(root)
    candidates = lake.list_canonical_publications(
        dataset_id=DATASET_ID,
        primary_temporal_field=TemporalSemantics.TRADE_DATE,
        primary_temporal_value=TRADE_DATE,
    )
    assert candidates == ()

    selection = select_canonical_publications(
        TUSHARE_DAILY_DATASET_SPEC,
        _selection_request(PublicationSelectionMode.LOCAL_LATEST),
        candidates,
    )
    assert selection.selected_publication_ids == ()
    assert selection.selected_vintage_sequences == ()
    assert selection.provider_revision_claim == "NONE"
    assert selection.point_in_time_claim == "NONE"
    assert len(selection.selected_publication_ids) == 0
    # Empty selection is not a publication_id and must not be used to invent
    # H2 health input. Explicit missing-id visibility is covered separately.
    assert not selection.selected_publication_ids


def test_h2_explicit_nonexistent_publication_not_visible(tmp_path):
    """Independent boundary: explicit missing publication_id → PUBLICATION_NOT_VISIBLE."""
    root = tmp_path / "lake"
    write_lake = initialize_fact_lake(root)
    _persist_and_publish(write_lake, _raw([_row()]), event=1)
    lake = open_existing_fact_lake(root)

    missing_id = "pub_" + "f" * 32
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=lake,
            dataset_spec=TUSHARE_DAILY_DATASET_SPEC,
            request=flha.HealthCollectionRequest(publication_id=missing_id),
        )
    assert exc.value.failure.code == flha.FAILURE_PUBLICATION_NOT_VISIBLE
