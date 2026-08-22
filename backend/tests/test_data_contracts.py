from __future__ import annotations

import json
from dataclasses import replace

import pytest

from data_contracts import (
    AdjustmentSemantics,
    CanonicalFact,
    CoverageMode,
    DataContractError,
    DatasetSpec,
    FetchSemantics,
    HistoryMode,
    ProviderObservation,
    ProviderRole,
    ProviderRoute,
    ProvenanceLink,
    QualityStatus,
    ReconciliationResult,
    ReconciliationStatus,
    RevisionSemantics,
    TemporalSemantics,
    attach_reconciliation,
    canonicalize_observation,
    reconcile_pair,
)


def _routes(*, fallback: bool = False, backfill: bool = False):
    routes = [
        ProviderRoute(
            "limit-up:tushare", "tushare", "/daily",
            ProviderRole.CANONICAL, "limit-up-v1"),
        ProviderRoute(
            "limit-up:eastmoney", "eastmoney", "/getTopicZTPool",
            ProviderRole.VERIFIER, "eastmoney-limit-up-v1"),
    ]
    if fallback:
        routes.append(ProviderRoute(
            "limit-up:equivalent-cache", "equivalent-cache", "/cache",
            ProviderRole.FALLBACK,
            "limit-up-v1",
            equivalent_to_route_id="limit-up:tushare",
            automatic_routing_allowed=True,
        ))
    if backfill:
        routes.append(ProviderRoute(
            "limit-up:historical", "historical-source", "/history",
            ProviderRole.HISTORICAL_BACKFILL,
            "limit-up-history-v1",
        ))
    return tuple(routes)


def _spec(**overrides) -> DatasetSpec:
    values = {
        "dataset_id": "limit_up_count",
        "fetch_semantics": FetchSemantics.BY_DATE,
        "history_mode": HistoryMode.BY_DATE,
        "routes": _routes(),
        "governance_revision_id": "gov-1",
        "required_temporal_fields": (TemporalSemantics.TRADE_DATE,),
        "coverage_mode": CoverageMode.SESSION_DENSE,
        "point_in_time_supported": True,
        "revision_semantics": RevisionSemantics.VERSIONED,
        "adjustment_semantics": AdjustmentSemantics.NOT_APPLICABLE,
        "survivorship_semantics": "historical_universe_preserved",
    }
    values.update(overrides)
    return DatasetSpec(**values)


def _observation(provider_id: str = "tushare", **overrides) -> ProviderObservation:
    values = {
        "observation_id": f"obs-{provider_id}",
        "dataset_id": "limit_up_count",
        "provider_id": provider_id,
        "provider_endpoint": {
            "tushare": "/daily",
            "eastmoney": "/getTopicZTPool",
            "equivalent-cache": "/cache",
            "manual-fallback": "/manual-cache",
            "random-provider": "/random",
        }.get(provider_id, "/daily"),
        "provider_symbol": "CN-A",
        "request_fingerprint": "sha256:req",
        "source_payload_hash": "sha256:payload",
        "normalizer_version": "normalizer-v1",
        "payload": {"count": 32},
        "fetch_semantics": FetchSemantics.BY_DATE,
        "history_mode": HistoryMode.BY_DATE,
        "effective_at": "2026-08-10T00:00:00Z",
        "published_at": "2026-08-10T07:00:00Z",
        "observed_at": "2026-08-10T07:01:00Z",
        "fetched_at": "2026-08-10T07:02:00Z",
        "trade_date": "2026-08-10",
        "report_period": None,
        "revision_id": "rev-1",
        "data_version": "vintage-1",
        "revision_semantics": RevisionSemantics.VERSIONED,
        "adjustment_semantics": AdjustmentSemantics.NOT_APPLICABLE,
        "quality_status": QualityStatus.VALID,
        "reason_codes": ("SOURCE_CONTRACT_VALID",),
    }
    values.update(overrides)
    return ProviderObservation(**values)


def test_observation_is_not_a_canonical_fact_and_fact_requires_provenance():
    observation = _observation()
    assert not isinstance(observation, CanonicalFact)

    with pytest.raises(DataContractError, match="provenance_chain"):
        CanonicalFact(
            fact_id="fact-1",
            dataset_id="limit_up_count",
            canonical_key="2026-08-10",
            canonical_payload=32,
            canonical_source="tushare",
            dataset_contract_revision="gov-1",
            revision_semantics=RevisionSemantics.VERSIONED,
            adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
            source_observation_ids=("obs-tushare",),
            provenance_chain=(),
            quality_status=QualityStatus.VALID,
        )


def test_missing_required_observation_provenance_is_rejected():
    with pytest.raises(DataContractError, match="source_payload_hash"):
        _observation(source_payload_hash="")
    with pytest.raises(DataContractError, match="normalizer_version"):
        _observation(normalizer_version="")


def test_unknown_and_null_are_not_coerced_and_json_round_trip_is_exact():
    observation = _observation(
        payload=None,
        effective_at=None,
        published_at=None,
        observed_at=None,
        trade_date=None,
        report_period=None,
        revision_id=None,
        quality_status=QualityStatus.UNKNOWN,
        reason_codes=("TIME_UNKNOWN",),
    )
    encoded = json.loads(json.dumps(observation.to_dict()))
    restored = ProviderObservation.from_dict(encoded)

    assert restored == observation
    assert restored.payload is None
    assert restored.effective_at is None
    assert restored.quality_status is QualityStatus.UNKNOWN
    assert restored.reason_codes == ("TIME_UNKNOWN",)


def test_temporal_fields_remain_distinct_and_have_explicit_semantics():
    observation = _observation()
    assert observation.effective_at == "2026-08-10T00:00:00Z"
    assert observation.published_at == "2026-08-10T07:00:00Z"
    assert observation.observed_at == "2026-08-10T07:01:00Z"
    assert observation.fetched_at == "2026-08-10T07:02:00Z"
    assert {item.value for item in TemporalSemantics} == {
        "effective_at", "published_at", "observed_at", "fetched_at",
        "trade_date", "report_period",
    }


@pytest.mark.parametrize("field,value", [
    ("fetched_at", None),
    ("fetched_at", "2026-08-10T07:02:00+00:00"),
    ("effective_at", "2026-08-10"),
    ("published_at", "not-a-time"),
    ("observed_at", "2026-02-30T00:00:00Z"),
    ("trade_date", "2026-02-30"),
])
def test_temporal_values_are_strict_utc_and_real_calendar_dates(field, value):
    with pytest.raises(DataContractError):
        _observation(**{field: value})


def test_non_valid_quality_requires_reason_and_duplicate_reasons_are_rejected():
    with pytest.raises(DataContractError, match="requires at least one"):
        _observation(quality_status=QualityStatus.UNKNOWN, reason_codes=())
    with pytest.raises(DataContractError, match="duplicates"):
        _observation(reason_codes=("SAME", "SAME"))


def test_snapshot_is_fetch_semantics_not_a_history_mode():
    assert FetchSemantics.SNAPSHOT.value == "snapshot"
    with pytest.raises(ValueError):
        HistoryMode("snapshot")


def test_snapshot_only_rejects_backfill_and_historical_fabrication():
    with pytest.raises(DataContractError, match="historical backfill"):
        _spec(
            fetch_semantics=FetchSemantics.SNAPSHOT,
            history_mode=HistoryMode.SNAPSHOT_ONLY,
            routes=_routes(backfill=True),
        )

    spec = _spec(
        fetch_semantics=FetchSemantics.SNAPSHOT,
        history_mode=HistoryMode.SNAPSHOT_ONLY,
    )
    observation = _observation(
        fetch_semantics=FetchSemantics.SNAPSHOT,
        history_mode=HistoryMode.SNAPSHOT_ONLY,
        effective_at="2026-08-10T07:00:00Z",
    )
    with pytest.raises(DataContractError, match="fabricate historical truth"):
        canonicalize_observation(
            spec,
            observation,
            fact_id="fact-1",
            canonical_key="CN-A",
            requested_effective_at="2020-01-01T00:00:00Z",
        )
    with pytest.raises(DataContractError, match="unavailable at requested as_of"):
        canonicalize_observation(
            spec,
            observation,
            fact_id="fact-as-of",
            canonical_key="CN-A",
            as_of="2026-08-10T07:01:59Z",
        )


def test_snapshot_with_backfill_requires_an_explicit_backfill_route():
    with pytest.raises(DataContractError, match="requires a historical_backfill"):
        _spec(
            fetch_semantics=FetchSemantics.SNAPSHOT,
            history_mode=HistoryMode.SNAPSHOT_WITH_BACKFILL,
        )


def test_snapshot_with_backfill_requires_snapshot_fetch_semantics():
    with pytest.raises(DataContractError, match="requires snapshot fetch"):
        _spec(
            fetch_semantics=FetchSemantics.BY_DATE,
            history_mode=HistoryMode.SNAPSHOT_WITH_BACKFILL,
            routes=_routes(backfill=True),
        )


def test_required_temporal_fields_are_explicit_unique_enum_values():
    with pytest.raises(DataContractError, match="TemporalSemantics"):
        _spec(required_temporal_fields=("trade_date",))
    with pytest.raises(DataContractError, match="duplicates"):
        _spec(required_temporal_fields=(
            TemporalSemantics.TRADE_DATE,
            TemporalSemantics.TRADE_DATE,
        ))
    with pytest.raises(DataContractError, match="business temporal coordinate"):
        _spec(required_temporal_fields=(TemporalSemantics.FETCHED_AT,))


def test_by_date_explicitly_rejects_empty_required_temporal_fields():
    with pytest.raises(DataContractError, match="business temporal coordinate"):
        _spec(required_temporal_fields=())


def test_canonicalization_rejects_missing_required_temporal_field():
    spec = _spec(required_temporal_fields=(
        TemporalSemantics.TRADE_DATE,
        TemporalSemantics.PUBLISHED_AT,
    ))
    with pytest.raises(DataContractError, match="published_at"):
        canonicalize_observation(
            spec,
            _observation(published_at=None),
            fact_id="fact-missing-published-at",
            canonical_key="2026-08-10",
        )


@pytest.mark.parametrize(
    ("required_field", "observation_override"),
    [
        (TemporalSemantics.TRADE_DATE, {"trade_date": None}),
        (TemporalSemantics.REPORT_PERIOD, {"report_period": None}),
    ],
)
def test_required_business_temporal_field_missing_is_explicitly_rejected(
    required_field,
    observation_override,
):
    with pytest.raises(DataContractError, match=required_field.value):
        canonicalize_observation(
            _spec(required_temporal_fields=(required_field,)),
            _observation(**observation_override),
            fact_id=f"fact-missing-{required_field.value}",
            canonical_key="2026-08-10",
        )


def test_pit_staleness_and_history_bounds_fail_closed():
    with pytest.raises(DataContractError, match="revision and survivorship"):
        _spec(revision_semantics=RevisionSemantics.UNKNOWN)
    with pytest.raises(DataContractError, match="non-negative int"):
        _spec(max_staleness_seconds=True)
    with pytest.raises(DataContractError, match="non-negative int"):
        _spec(max_staleness_seconds=-1)
    with pytest.raises(DataContractError, match="must not exceed"):
        _spec(history_floor="2026-08-11", history_horizon="2026-08-10")


def test_dataset_requires_one_canonical_and_unique_provider_routes():
    with pytest.raises(DataContractError, match="exactly one canonical"):
        _spec(routes=(
            ProviderRoute("route-a", "a", "/a", ProviderRole.VERIFIER, "a-v1"),
            ProviderRoute("route-b", "b", "/b", ProviderRole.VERIFIER, "b-v1"),
        ))
    with pytest.raises(DataContractError, match="must be unique"):
        _spec(routes=(
            ProviderRoute("same", "a", "/a", ProviderRole.CANONICAL, "a-v1"),
            ProviderRoute("same", "a", "/b", ProviderRole.VERIFIER, "a-v1"),
        ))


def test_fallback_must_be_explicit_and_semantically_equivalent():
    with pytest.raises(DataContractError, match="semantically equivalent"):
        _spec(routes=(
            ProviderRoute(
                "route-tushare", "tushare", "/daily",
                ProviderRole.CANONICAL, "v1"),
            ProviderRoute(
                "route-other", "other", "/other",
                ProviderRole.FALLBACK, "different-v1",
                equivalent_to_route_id="route-tushare",
                automatic_routing_allowed=True,
            ),
        ))
    with pytest.raises(DataContractError, match="only permitted"):
        ProviderRoute(
            "route-verifier", "verifier", "/verify",
            ProviderRole.VERIFIER, "v1",
            automatic_routing_allowed=True,
        )


def test_dataset_spec_and_routes_are_strict_json_round_trip_contracts():
    spec = _spec(routes=_routes(fallback=True))
    encoded = json.loads(json.dumps(spec.to_dict()))
    assert DatasetSpec.from_dict(encoded) == spec
    encoded["history_mode"] = "snapshot"
    with pytest.raises(ValueError):
        DatasetSpec.from_dict(encoded)


def test_verifier_cannot_become_canonical_and_explicit_fallback_can():
    spec = _spec(routes=_routes(fallback=True))
    with pytest.raises(DataContractError, match="cannot become canonical"):
        canonicalize_observation(
            spec,
            _observation("eastmoney"),
            fact_id="fact-em",
            canonical_key="2026-08-10",
        )

    fact = canonicalize_observation(
        spec,
        _observation("equivalent-cache"),
        fact_id="fact-fallback",
        canonical_key="2026-08-10",
    )
    assert fact.canonical_source == "equivalent-cache"


def test_fallback_canonicalization_requires_automatic_routing_permission():
    spec = _spec(routes=(
        ProviderRoute(
            "limit-up:tushare", "tushare", "/daily",
            ProviderRole.CANONICAL, "limit-up-v1"),
        ProviderRoute(
            "limit-up:manual", "manual-fallback", "/manual-cache",
            ProviderRole.FALLBACK, "limit-up-v1",
            equivalent_to_route_id="limit-up:tushare",
            automatic_routing_allowed=False,
        ),
    ))
    with pytest.raises(DataContractError, match="explicit automatic routing"):
        canonicalize_observation(
            spec,
            _observation("manual-fallback"),
            fact_id="fact-manual",
            canonical_key="2026-08-10",
        )


def test_canonical_fact_has_explicit_traceable_provenance_and_round_trip():
    observation = _observation(reason_codes=("SOURCE_VALID", "PIT_BOUND"))
    fact = canonicalize_observation(
        _spec(), observation, fact_id="fact-1", canonical_key="2026-08-10")

    assert fact.source_observation_ids == (observation.observation_id,)
    assert fact.provenance_chain[0].source_payload_hash == \
        observation.source_payload_hash
    assert fact.reason_codes == ("SOURCE_VALID", "PIT_BOUND")
    encoded = json.loads(json.dumps(fact.to_dict()))
    assert CanonicalFact.from_dict(encoded) == fact
    assert fact.dataset_contract_revision == "gov-1"
    assert fact.revision_semantics is RevisionSemantics.VERSIONED

    with pytest.raises(DataContractError, match="contract revision"):
        _spec().validate_fact(
            replace(fact, dataset_contract_revision="other-governance-revision"))
    del encoded["dataset_contract_revision"]
    with pytest.raises(DataContractError, match="fields mismatch"):
        CanonicalFact.from_dict(encoded)


def test_canonical_fact_preserves_trade_date_and_report_period_round_trip():
    observation = _observation(
        trade_date="2026-08-10",
        report_period="2026-Q2",
    )
    fact = canonicalize_observation(
        _spec(required_temporal_fields=(
            TemporalSemantics.TRADE_DATE,
            TemporalSemantics.REPORT_PERIOD,
        )),
        observation,
        fact_id="fact-temporal-business-fields",
        canonical_key="2026-Q2",
    )
    assert fact.trade_date == "2026-08-10"
    assert fact.report_period == "2026-Q2"
    assert CanonicalFact.from_dict(
        json.loads(json.dumps(fact.to_dict()))) == fact


def test_optional_temporal_nulls_remain_null_in_fact_round_trip():
    fact = canonicalize_observation(
        _spec(),
        _observation(
            effective_at=None,
            published_at=None,
            observed_at=None,
            report_period=None,
        ),
        fact_id="fact-optional-temporal-nulls",
        canonical_key="2026-08-10",
    )
    restored = CanonicalFact.from_dict(
        json.loads(json.dumps(fact.to_dict())))
    assert restored.effective_at is None
    assert restored.published_at is None
    assert restored.observed_at is None
    assert restored.report_period is None


def test_validate_fact_rejects_required_temporal_field_missing_after_factory():
    spec = _spec(required_temporal_fields=(TemporalSemantics.TRADE_DATE,))
    fact = canonicalize_observation(
        spec, _observation(), fact_id="fact-required-trade-date",
        canonical_key="2026-08-10")
    with pytest.raises(DataContractError, match="fact required.*trade_date"):
        spec.validate_fact(replace(fact, trade_date=None))


def test_dataset_spec_rejects_non_spec_canonical_source():
    verifier_fact = CanonicalFact(
        fact_id="fact-verifier",
        dataset_id="limit_up_count",
        canonical_key="2026-08-10",
        canonical_payload={"count": 32},
        canonical_source="eastmoney",
        dataset_contract_revision="gov-1",
        revision_semantics=RevisionSemantics.VERSIONED,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
        source_observation_ids=("obs-eastmoney",),
        provenance_chain=(ProvenanceLink(
            "obs-eastmoney", "limit_up_count", "eastmoney",
            "/getTopicZTPool", "sha256:payload", "normalizer-v1"),),
        trade_date="2026-08-10",
        quality_status=QualityStatus.VALID,
    )
    with pytest.raises(DataContractError, match="cannot become canonical"):
        _spec().validate_fact(verifier_fact)


def test_explicit_null_canonical_payload_is_not_replaced_by_current_value():
    fact = canonicalize_observation(
        _spec(),
        _observation(payload={"current": 32}),
        fact_id="fact-null",
        canonical_key="2026-08-10",
        canonical_payload=None,
    )
    assert fact.canonical_payload is None


def test_invalid_or_unrouted_observation_fails_closed():
    with pytest.raises(DataContractError, match="invalid observations"):
        canonicalize_observation(
            _spec(), _observation(quality_status=QualityStatus.INVALID),
            fact_id="fact-1", canonical_key="2026-08-10")
    with pytest.raises(DataContractError, match="not configured"):
        canonicalize_observation(
            _spec(), _observation("random-provider"),
            fact_id="fact-2", canonical_key="2026-08-10")


@pytest.mark.parametrize("spec,observation", [
    (_spec(), _observation()),
    (
        _spec(
            fetch_semantics=FetchSemantics.SNAPSHOT,
            history_mode=HistoryMode.SNAPSHOT_WITH_BACKFILL,
            routes=_routes(backfill=True),
        ),
        _observation(
            fetch_semantics=FetchSemantics.SNAPSHOT,
            history_mode=HistoryMode.SNAPSHOT_WITH_BACKFILL,
        ),
    ),
])
def test_all_history_modes_reject_as_of_before_fetched_at(spec, observation):
    with pytest.raises(DataContractError, match="unavailable at requested as_of"):
        canonicalize_observation(
            spec,
            observation,
            fact_id="fact-as-of-all-modes",
            canonical_key="2026-08-10",
            as_of="2026-08-10T07:01:59Z",
        )


def test_requested_effective_at_must_be_canonical_utc():
    with pytest.raises(DataContractError, match="canonical UTC"):
        canonicalize_observation(
            _spec(), _observation(), fact_id="fact-effective",
            canonical_key="2026-08-10", requested_effective_at="2026-08-10")


def test_dataset_and_route_retirement_are_strict_and_fail_closed():
    with pytest.raises(DataContractError, match="source_retired_at"):
        _spec(source_retired_at="2026-08-10")
    with pytest.raises(DataContractError, match="retired_at"):
        ProviderRoute(
            "bad-retired", "tushare", "/daily", ProviderRole.CANONICAL,
            "limit-up-v1", retired_at="not-utc")

    with pytest.raises(DataContractError, match="dataset source retirement"):
        canonicalize_observation(
            _spec(source_retired_at="2026-08-10T07:01:59Z"),
            _observation(), fact_id="fact-retired-dataset",
            canonical_key="2026-08-10")

    route_spec = _spec(routes=(
        ProviderRoute(
            "limit-up:tushare", "tushare", "/daily",
            ProviderRole.CANONICAL, "limit-up-v1",
            retired_at="2026-08-10T07:01:59Z"),
    ))
    with pytest.raises(DataContractError, match="route retirement"):
        canonicalize_observation(
            route_spec, _observation(), fact_id="fact-retired-route",
            canonical_key="2026-08-10")


def test_same_provider_can_have_distinct_endpoint_routes():
    spec = _spec(routes=(
        ProviderRoute(
            "canonical-endpoint", "same-provider", "/canonical",
            ProviderRole.CANONICAL, "v1"),
        ProviderRoute(
            "verifier-endpoint", "same-provider", "/verifier",
            ProviderRole.VERIFIER, "verify-v1"),
    ))
    fact = canonicalize_observation(
        spec,
        _observation(
            "same-provider", provider_endpoint="/canonical"),
        fact_id="fact-route-identity",
        canonical_key="2026-08-10",
    )
    assert fact.canonical_source == "same-provider"


def test_forged_provenance_dataset_is_rejected():
    spec = _spec()
    fact = canonicalize_observation(
        spec, _observation(), fact_id="fact-provenance-dataset",
        canonical_key="2026-08-10")
    forged = replace(
        fact,
        provenance_chain=(replace(
            fact.provenance_chain[0], dataset_id="other_dataset"),),
    )
    with pytest.raises(DataContractError, match="provenance dataset"):
        spec.validate_fact(forged)


def test_reconciliation_match_preserves_both_values_ids_and_reasons():
    result = reconcile_pair(
        _observation(reason_codes=("LEFT_OK",)),
        _observation(
            "eastmoney", observation_id="obs-eastmoney",
            reason_codes=("RIGHT_OK",)),
    )
    assert result.status is ReconciliationStatus.MATCH
    assert result.left_observation_id == "obs-tushare"
    assert result.right_observation_id == "obs-eastmoney"
    assert result.left_value == result.right_value == {"count": 32}
    assert result.dataset_id == "limit_up_count"
    assert result.reason_codes == ("LEFT_OK", "RIGHT_OK", "VALUES_MATCH")
    encoded = json.loads(json.dumps(result.to_dict()))
    assert ReconciliationResult.from_dict(encoded) == result


def test_reconciliation_mismatch_preserves_disagreement():
    result = reconcile_pair(
        _observation(payload={"count": 32}),
        _observation("eastmoney", payload={"count": 31}),
    )
    assert result.status is ReconciliationStatus.MISMATCH
    assert result.left_value == {"count": 32}
    assert result.right_value == {"count": 31}


def test_reconciliation_partial_preserves_both_payloads():
    result = reconcile_pair(
        _observation(payload={"count": 32, "coverage": 5000}),
        _observation("eastmoney", payload={"count": 32}),
    )
    assert result.status is ReconciliationStatus.PARTIAL
    assert result.left_value == {"count": 32, "coverage": 5000}
    assert result.right_value == {"count": 32}


def test_reconciliation_unknown_for_unknown_value():
    result = reconcile_pair(
        _observation(payload=None),
        _observation("eastmoney", payload={"count": 32}),
    )
    assert result.status is ReconciliationStatus.UNKNOWN
    assert result.reason_codes[-1] == "VALUE_UNKNOWN"


def test_two_explicit_null_values_are_unknown_not_match():
    result = reconcile_pair(
        _observation(payload=None),
        _observation("eastmoney", payload=None),
    )
    assert result.status is ReconciliationStatus.UNKNOWN
    assert result.reason_codes[-1] == "BOTH_VALUES_UNKNOWN"


def test_untrusted_quality_cannot_produce_match_or_mismatch():
    partial = reconcile_pair(
        _observation(payload={"count": 32}),
        _observation(
            "eastmoney", payload={"count": 99},
            quality_status=QualityStatus.INVALID,
            reason_codes=("INVALID_ROW",)),
    )
    unknown = reconcile_pair(
        _observation(
            payload={"count": 32}, quality_status=QualityStatus.UNKNOWN,
            reason_codes=("LEFT_UNKNOWN",)),
        _observation(
            "eastmoney", payload={"count": 32},
            quality_status=QualityStatus.UNKNOWN,
            reason_codes=("RIGHT_UNKNOWN",)),
    )
    assert partial.status is ReconciliationStatus.PARTIAL
    assert unknown.status is ReconciliationStatus.UNKNOWN


@pytest.mark.parametrize("right_payload", [
    {"count": 32},
    {"count": 99},
])
def test_degraded_quality_is_always_partial(right_payload):
    result = reconcile_pair(
        _observation(
            quality_status=QualityStatus.DEGRADED,
            reason_codes=("COVERAGE_WARNING",)),
        _observation("eastmoney", payload=right_payload),
    )
    assert result.status is ReconciliationStatus.PARTIAL
    assert result.reason_codes[-1] == "SOURCE_QUALITY_DEGRADED"


def test_source_unavailable_is_not_coerced_to_zero():
    result = reconcile_pair(_observation(payload={"count": 0}), None)
    assert result.status is ReconciliationStatus.SOURCE_UNAVAILABLE
    assert result.left_value == {"count": 0}
    assert result.right_value is None


def test_reconciliation_requires_one_dataset_and_at_least_one_observation():
    with pytest.raises(DataContractError, match="at least one"):
        reconcile_pair(None, None)
    with pytest.raises(DataContractError, match="one dataset"):
        reconcile_pair(
            _observation(),
            _observation("eastmoney", dataset_id="other_dataset"),
        )


def test_temporal_incomparable_is_not_reported_as_mismatch():
    result = reconcile_pair(
        _observation(trade_date="2026-08-10"),
        _observation("eastmoney", trade_date="2026-08-09"),
    )
    assert result.status is ReconciliationStatus.TEMPORAL_INCOMPARABLE
    assert result.status is not ReconciliationStatus.MISMATCH
    assert "TRADE_DATE_MISMATCH" in result.reason_codes


@pytest.mark.parametrize("right_overrides,reason", [
    ({"effective_at": None}, "EFFECTIVE_AT_AVAILABILITY_MISMATCH"),
    ({"revision_id": "rev-2"}, "REVISION_ID_MISMATCH"),
    ({"data_version": "vintage-2"}, "DATA_VERSION_MISMATCH"),
    ({"adjustment_semantics": AdjustmentSemantics.UNADJUSTED},
     "ADJUSTMENT_SEMANTICS_MISMATCH"),
])
def test_temporal_vintage_or_adjustment_difference_is_incomparable(
    right_overrides, reason,
):
    result = reconcile_pair(
        _observation(), _observation("eastmoney", **right_overrides))
    assert result.status is ReconciliationStatus.TEMPORAL_INCOMPARABLE
    assert reason in result.reason_codes


def test_unknown_temporal_basis_remains_unknown():
    result = reconcile_pair(
        _observation(effective_at=None, trade_date=None, report_period=None),
        _observation(
            "eastmoney", effective_at=None, trade_date=None,
            report_period=None),
    )
    assert result.status is ReconciliationStatus.UNKNOWN
    assert result.reason_codes[-1] == "TEMPORAL_BASIS_UNKNOWN"


def test_reconciliation_attachment_never_switches_canonical_source_or_value():
    fact = canonicalize_observation(
        _spec(), _observation(), fact_id="fact-1",
        canonical_key="2026-08-10")
    result = reconcile_pair(
        _observation(), _observation("eastmoney", payload={"count": 99}))
    attached = attach_reconciliation(fact, result)

    assert attached.canonical_source == "tushare"
    assert attached.canonical_payload == {"count": 32}
    assert attached.reconciliation_status is ReconciliationStatus.MISMATCH
    assert attached.quality_status is QualityStatus.DEGRADED
    assert "VALUES_MISMATCH" in attached.reason_codes


def test_attach_reconciliation_rejects_dataset_or_observation_id_mismatch():
    fact = canonicalize_observation(
        _spec(), _observation(), fact_id="fact-bound",
        canonical_key="2026-08-10")
    result = reconcile_pair(
        _observation(), _observation("eastmoney", payload={"count": 99}))

    with pytest.raises(DataContractError, match="dataset does not match"):
        attach_reconciliation(
            fact, replace(result, dataset_id="other_dataset"))
    with pytest.raises(DataContractError, match="not bound"):
        attach_reconciliation(
            fact,
            replace(
                result,
                left_observation_id="unrelated-left",
                right_observation_id="unrelated-right",
            ),
        )

    attached = attach_reconciliation(
        fact,
        replace(result, right_observation_id="unrelated-right"),
    )
    assert attached.canonical_source == fact.canonical_source
    assert attached.canonical_payload == fact.canonical_payload


def test_non_json_payload_and_extra_serialized_fields_are_rejected():
    with pytest.raises(DataContractError, match="not JSON-safe"):
        _observation(payload={"bad": object()})
    payload = _observation().to_dict()
    payload["unexpected"] = True
    with pytest.raises(DataContractError, match="fields mismatch"):
        ProviderObservation.from_dict(payload)


def test_from_dict_rejects_string_where_json_array_is_required():
    payload = _observation().to_dict()
    payload["reason_codes"] = "NOT_AN_ARRAY"
    with pytest.raises(DataContractError, match="JSON array"):
        ProviderObservation.from_dict(payload)

    fact_payload = canonicalize_observation(
        _spec(), _observation(), fact_id="fact-list",
        canonical_key="2026-08-10").to_dict()
    fact_payload["source_observation_ids"] = "obs-tushare"
    with pytest.raises(DataContractError, match="JSON array"):
        CanonicalFact.from_dict(fact_payload)
