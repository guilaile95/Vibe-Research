"""Focused contracts for the P0-CDA1A price-reference capability adapter."""

from __future__ import annotations

import json

import pytest

import critical_data_price_reference_adapter as adapter
from critical_data_price_reference_adapter import (
    ADAPTER_AUTHORITY_REF,
    DEPENDENCY_ID,
    HEALTH_COLLECTION_AUTHORITY_REF,
    HEALTH_AUTHORITY_REF,
    PriceReferenceCapabilityError,
    PROVIDER_ALIAS_AUTHORITY_REF,
    REPLAY_AUTHORITY_REF,
    evaluate_price_reference_capability,
)
from fact_lake_publication_selection import SELECTION_SCHEMA_VERSION
from fact_lake_store import (
    initialize_fact_lake,
    open_existing_fact_lake,
    payload_sha256,
)
from security_exchange_policy import (
    POLICY_AUTHORITY_REF_V01,
    POLICY_VERSION_V01,
)
from trade_calendar import CALENDAR_AUTHORITY_REF
from tushare_daily_shadow import (
    ARTIFACT_SCHEMA_VERSION,
    DAILY_FIELD_MANIFEST,
    DATASET_CONTRACT_REVISION,
    DATASET_ID,
    NORMALIZER_VERSION,
    TushareDailyRawResponseCapture,
    TushareDailyReplayMismatchError,
    TushareDailyRequestContract,
    build_tushare_daily_canonical_fact,
    build_request_fingerprint,
    persist_tushare_daily_evidence,
    publish_tushare_daily_canonical_fact,
)


TRADE_DATE = "2026-07-30"
AS_OF = "2026-07-30T08:30:00Z"  # 16:30 Asia/Shanghai, after session close.
CAMPAIGN_ID = "campaign_" + "a" * 32


def _raw_daily(rows: list[dict[str, object]]) -> bytes:
    defaults = {
        "open": 1780.0,
        "high": 1810.0,
        "low": 1775.0,
        "close": 1800.0,
        "pre_close": 1773.4,
        "change": 26.6,
        "pct_chg": 1.5,
        "vol": 35000.0,
        "amount": 6280000.0,
    }
    items = []
    for row in rows:
        value = {
            **defaults,
            "trade_date": "20260730",
            **row,
        }
        items.append([value[field] for field in DAILY_FIELD_MANIFEST])
    return json.dumps(
        {
            "code": 0,
            "msg": "synthetic",
            "data": {"fields": list(DAILY_FIELD_MANIFEST), "items": items},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _publish(
    lake,
    *,
    rows: list[dict[str, object]] | None = None,
    event: int = 1,
    fetched_at: str = "2026-07-30T08:00:00.000000Z",
):
    raw = _raw_daily(rows or [{"ts_code": "600519.SH"}])
    contract = TushareDailyRequestContract(TRADE_DATE)
    capture = TushareDailyRawResponseCapture(
        capture_event_id=f"capture-{event:032x}",
        contract=contract,
        raw_bytes=raw,
        request_fingerprint=build_request_fingerprint(contract),
        source_payload_hash=payload_sha256(raw),
        http_status=200,
        content_type="application/json; charset=utf-8",
        fetched_at=fetched_at,
    )
    observation, normalization = persist_tushare_daily_evidence(lake, capture)
    fact = build_tushare_daily_canonical_fact(observation.observation, normalization)
    return observation, publish_tushare_daily_canonical_fact(lake, fact)


def _evaluate(lake, *, security_code="600519", publication_id=None, as_of=AS_OF):
    return evaluate_price_reference_capability(
        lake=lake,
        security_code=security_code,
        campaign_id=CAMPAIGN_ID,
        as_of=as_of,
        security_exchange_policy_version=POLICY_VERSION_V01,
        publication_id=publication_id,
    )


def _readonly(lake):
    return open_existing_fact_lake(lake.root, readonly=True)


@pytest.mark.parametrize(
    ("security_code", "ts_code"),
    [("600519", "600519.SH"), ("000001", "000001.SZ")],
)
def test_sse_and_szse_positive_proof_has_exact_shape_as_of_and_refs(
    tmp_path, security_code, ts_code
):
    lake = initialize_fact_lake(tmp_path / "lake")
    observation, publication = _publish(lake, rows=[{"ts_code": ts_code}])

    result = _evaluate(_readonly(lake), security_code=security_code, publication_id=publication.publication_id)

    assert set(result) == {"dependency_id", "state", "as_of", "authority_refs"}
    assert result["dependency_id"] == DEPENDENCY_ID
    assert result["state"] == "USABLE"
    assert result["as_of"] == AS_OF
    assert result["authority_refs"] == [
        ADAPTER_AUTHORITY_REF,
        CALENDAR_AUTHORITY_REF,
        POLICY_AUTHORITY_REF_V01,
        PROVIDER_ALIAS_AUTHORITY_REF,
        f"selection:{SELECTION_SCHEMA_VERSION}:exact_publication_id",
        f"dataset:{DATASET_ID}:{DATASET_CONTRACT_REVISION}",
        f"publication:{publication.publication_id}",
        f"observation:{observation.observation.observation_id}",
        f"normalizer:{NORMALIZER_VERSION}",
        f"artifact-schema:{ARTIFACT_SCHEMA_VERSION}",
        HEALTH_COLLECTION_AUTHORITY_REF,
        HEALTH_AUTHORITY_REF,
        REPLAY_AUTHORITY_REF,
        f"security-row:{ts_code}:{TRADE_DATE}",
    ]


@pytest.mark.parametrize("security_code", ["920001", "430017"])
def test_current_and_legacy_bse_remain_not_evaluated_without_provider_alias(
    tmp_path, security_code
):
    result = _evaluate(_readonly(initialize_fact_lake(tmp_path / "lake")), security_code=security_code)

    assert result == {
        "dependency_id": DEPENDENCY_ID,
        "state": "NOT_EVALUATED",
        "as_of": AS_OF,
        "authority_refs": [
            ADAPTER_AUTHORITY_REF,
            POLICY_AUTHORITY_REF_V01,
        ],
    }


def test_calendar_none_stops_without_other_authority_claims(tmp_path):
    # Valid UTC but outside the frozen calendar support range.
    as_of = "1970-01-01T00:00:00Z"
    result = _evaluate(_readonly(initialize_fact_lake(tmp_path / "lake")), as_of=as_of)

    assert result == {
        "dependency_id": DEPENDENCY_ID,
        "state": "NOT_EVALUATED",
        "as_of": as_of,
        "authority_refs": [ADAPTER_AUTHORITY_REF],
    }


def test_no_publication_and_missing_explicit_publication_are_not_evaluated(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")

    readonly = _readonly(lake)
    assert _evaluate(readonly)["state"] == "NOT_EVALUATED"
    assert _evaluate(readonly, publication_id="publication-does-not-exist")["state"] == "NOT_EVALUATED"


def test_multiple_unpinned_publications_do_not_claim_latest_wins(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, first = _publish(lake, event=1)
    _, second = _publish(lake, event=2, rows=[{"ts_code": "600519.SH", "close": 1801.0}])

    readonly = _readonly(lake)
    unpinned = _evaluate(readonly)
    pinned = _evaluate(readonly, publication_id=first.publication_id)

    assert second.vintage_sequence > first.vintage_sequence
    assert unpinned["state"] == "NOT_EVALUATED"
    assert all(not ref.startswith("publication:") for ref in unpinned["authority_refs"])
    assert pinned["state"] == "USABLE"
    assert f"publication:{first.publication_id}" in pinned["authority_refs"]


def test_future_evidence_and_missing_security_row_are_not_evaluated(tmp_path):
    future_lake = initialize_fact_lake(tmp_path / "future")
    _, future = _publish(future_lake, fetched_at="2026-07-30T08:31:00.000000Z")
    missing_lake = initialize_fact_lake(tmp_path / "missing")
    _, missing = _publish(missing_lake, rows=[{"ts_code": "000001.SZ"}])

    assert _evaluate(_readonly(future_lake), publication_id=future.publication_id)["state"] == "NOT_EVALUATED"
    assert _evaluate(_readonly(missing_lake), publication_id=missing.publication_id)["state"] == "NOT_EVALUATED"


@pytest.mark.parametrize(
    ("fetched_at", "expected_state"),
    [
        ("2026-07-30T06:59:59.000000Z", "NOT_EVALUATED"),
        ("2026-07-30T07:00:00.000000Z", "USABLE"),
        ("2026-07-30T08:00:00.000000Z", "USABLE"),
    ],
)
def test_receipt_must_follow_target_session_close(
    tmp_path, fetched_at, expected_state
):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, publication = _publish(lake, fetched_at=fetched_at)

    assert _evaluate(
        _readonly(lake),
        publication_id=publication.publication_id,
    )["state"] == expected_state


def test_invalid_close_is_an_integrity_error(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, publication = _publish(lake, rows=[{"ts_code": "600519.SH", "close": 0.0}])

    assert _evaluate(_readonly(lake), publication_id=publication.publication_id)["state"] == "ERROR"


def test_null_close_is_missing_positive_proof_not_integrity_error(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, publication = _publish(
        lake,
        rows=[{"ts_code": "600519.SH", "close": None}],
    )

    assert _evaluate(
        _readonly(lake),
        publication_id=publication.publication_id,
    )["state"] == "NOT_EVALUATED"


def test_replay_mismatch_and_corrupt_publication_fail_closed_as_error(tmp_path, monkeypatch):
    replay_lake = initialize_fact_lake(tmp_path / "replay")
    _, replay_publication = _publish(replay_lake)
    monkeypatch.setattr(
        adapter,
        "verify_tushare_daily_normalization_replay",
        lambda *_: (_ for _ in ()).throw(TushareDailyReplayMismatchError("test mismatch")),
    )
    assert _evaluate(_readonly(replay_lake), publication_id=replay_publication.publication_id)["state"] == "ERROR"

    corrupt_lake = initialize_fact_lake(tmp_path / "corrupt")
    _, corrupt_publication = _publish(corrupt_lake)
    corrupt_lake.canonical_artifact_path(corrupt_publication.artifact_relpath).write_bytes(b"corrupt")
    assert _evaluate(_readonly(corrupt_lake), publication_id=corrupt_publication.publication_id)["state"] == "ERROR"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"security_code": "60051"},
        {"security_code": 600519},
        {"campaign_id": "campaign_not-a-valid-id"},
        {"campaign_id": None},
        {"as_of": "2026-07-30T08:30:00+08:00"},
        {"as_of": None},
        {"security_exchange_policy_version": None},
    ],
)
def test_malformed_inputs_raise_capability_error(tmp_path, kwargs):
    values = {
        "lake": _readonly(initialize_fact_lake(tmp_path / "lake")),
        "security_code": "600519",
        "campaign_id": CAMPAIGN_ID,
        "as_of": AS_OF,
        "security_exchange_policy_version": POLICY_VERSION_V01,
    }
    values.update(kwargs)

    with pytest.raises(PriceReferenceCapabilityError):
        evaluate_price_reference_capability(**values)
