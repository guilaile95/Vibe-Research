"""Synthetic temporal-boundary tests; no provider or live PIT claims."""
from dataclasses import replace

import pytest

import financial_asof_admission as admission
from financial_asof_admission import (
    FinancialAsOfUnavailable, FinancialPublicationEvidence,
    evaluate_financial_time_admission,
)
from financial_indicator_shadow import query_financial_indicators
from fact_lake_store import initialize_fact_lake
from test_financial_indicator_shadow import (
    REPORT_PERIOD, TS_CODE, _raw, _row, _capture, _persist_fact,
)
from financial_indicator_shadow import (
    build_provider_observation,
    publish_financial_canonical_fact,
)

CUTOFF = "2026-05-01T00:00:00Z"
AUTHORITY = "synthetic:official-exact-version-release"


def observation():
    return build_provider_observation(_capture(_raw([_row()])))


def evidence(obs, **updates):
    values = {field: getattr(obs, field) for field in (
        "observation_id", "dataset_id", "provider_id", "provider_endpoint",
        "provider_symbol", "report_period", "source_payload_hash", "revision_id", "data_version",
    )}
    return FinancialPublicationEvidence(
        **{**values, "authority_ref": AUTHORITY, "published_at": CUTOFF, **updates}
    )


def evaluate(obs, proof=None, **updates):
    return evaluate_financial_time_admission(obs, **{
        "provider_symbol": TS_CODE, "report_period": REPORT_PERIOD,
        "as_of": CUTOFF, "publication_evidence": proof, **updates,
    })


@pytest.fixture
def trusted(monkeypatch):
    obs = observation()
    monkeypatch.setattr(admission, "_TRUSTED_PUBLICATION_AUTHORITIES", frozenset({
        (AUTHORITY, obs.provider_id, obs.provider_endpoint),
    }))
    return obs


def test_current_view_needs_no_historical_release_authority():
    assert evaluate(observation(), as_of=None).status == "CURRENT_VIEW"


def test_no_authority_can_be_self_declared():
    obs = observation()
    assert evaluate(obs, evidence(obs)).reason_code == "PUBLICATION_AUTHORITY_NOT_TRUSTED"
    with pytest.raises(TypeError):
        evaluate_financial_time_admission(
            obs, provider_symbol=TS_CODE, report_period=REPORT_PERIOD,
            as_of=CUTOFF, trusted_authority_refs=frozenset({AUTHORITY}),
        )


def test_missing_publication_does_not_use_period_fetch_or_observation_times():
    obs = replace(observation(), effective_at="2026-03-31T00:00:00Z",
                  observed_at="2026-04-01T00:00:00Z", fetched_at="2026-04-01T00:00:00Z")
    assert evaluate(obs).reason_code == "AUTHORITATIVE_PUBLICATION_MISSING"
    assert evaluate(obs, as_of="2027-12-31T00:00:00Z").status == "UNKNOWN"


@pytest.mark.parametrize("published,status", [
    ("2026-04-30T23:59:59Z", "TEMPORALLY_ADMISSIBLE"),
    (CUTOFF, "TEMPORALLY_ADMISSIBLE"),
    ("2026-05-01T00:00:00.000001Z", "EXCLUDED"),
    ("2026-06-30T00:00:00Z", "EXCLUDED"),
])
def test_exact_release_boundary(trusted, published, status):
    assert evaluate(trusted, evidence(trusted, published_at=published)).status == status


def test_late_correction_cannot_inherit_original_release(trusted):
    original = evidence(trusted, published_at="2026-04-20T00:00:00Z")
    correction = replace(trusted, observation_id="correction", revision_id="revision-2",
                         source_payload_hash="b" * 64)
    assert evaluate(correction, original).reason_code == "PUBLICATION_VERSION_BINDING_MISMATCH"
    later = evidence(correction, published_at="2026-06-01T00:00:00Z")
    assert evaluate(correction, later).reason_code == "PUBLICATION_AFTER_AS_OF"


@pytest.mark.parametrize("field,value", [
    ("provider_symbol", "000001.SZ"), ("report_period", "2025-12-31"),
    ("observation_id", "other"), ("source_payload_hash", "c" * 64),
    ("dataset_id", "other"), ("provider_id", "other"),
    ("provider_endpoint", "other"), ("revision_id", "other"), ("data_version", "other"),
])
def test_evidence_must_bind_exact_subject_and_version(trusted, field, value):
    assert evaluate(trusted, evidence(trusted, **{field: value})).reason_code \
        == "PUBLICATION_VERSION_BINDING_MISMATCH"


@pytest.mark.parametrize("field,value", [("provider_symbol", "000001.SZ"),
                                          ("report_period", "2025-12-31")])
def test_requested_subject_mismatch(trusted, field, value):
    assert evaluate(trusted, evidence(trusted), **{field: value}).reason_code \
        == "FINANCIAL_SUBJECT_MISMATCH"


@pytest.mark.parametrize("stamp", [None, "", "2026-04-30", "2026-04-30T12:00:00",
    "2026-04-30T20:00:00+08:00", "2026-04-30T12:00:00+00:00",
    "2026-02-30T00:00:00Z", 123, "not-a-time"])
def test_invalid_or_noncanonical_release_is_unknown(trusted, stamp):
    assert evaluate(trusted, evidence(trusted, published_at=stamp)).status == "UNKNOWN"


@pytest.mark.parametrize("stamp", ["bad", "2026-02-30T00:00:00Z",
    "2026-05-01T08:00:00+08:00", "2026-05-01T00:00:00"])
def test_invalid_cutoff_is_unknown(trusted, stamp):
    assert evaluate(trusted, evidence(trusted), as_of=stamp).reason_code == "INVALID_AS_OF_TIMESTAMP"


def test_fetch_time_is_not_release_authority_or_source_release_cutoff(trusted):
    late_capture = replace(trusted, fetched_at="2026-07-01T00:00:00Z")
    # Only release eligibility: does not imply available in an earlier local bundle.
    assert evaluate(late_capture, evidence(late_capture)).status == "TEMPORALLY_ADMISSIBLE"


def test_conflicting_observation_publication_is_excluded(trusted):
    obs = replace(trusted, published_at="2026-04-20T00:00:00Z")
    assert evaluate(obs, evidence(obs)).reason_code == "PUBLICATION_TIMESTAMP_CONFLICT"


def test_empty_historical_query_reports_missing_observation(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    with pytest.raises(FinancialAsOfUnavailable) as error:
        query_financial_indicators(lake, TS_CODE, REPORT_PERIOD, as_of=CUTOFF)
    assert error.value.admissions[0].reason_code == "FINANCIAL_OBSERVATION_MISSING"
    assert query_financial_indicators(lake, TS_CODE, REPORT_PERIOD) == ()


def test_real_shadow_caller_enforces_gate_and_preserves_current_and_frozen_reads(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    stored, normalized, fact = _persist_fact(lake, _raw([_row()]))
    publication = publish_financial_canonical_fact(lake, fact)
    before = query_financial_indicators(lake, TS_CODE, REPORT_PERIOD,
        selection="publication", publication_id=publication.publication_id)
    with pytest.raises(FinancialAsOfUnavailable) as error:
        query_financial_indicators(lake, TS_CODE, REPORT_PERIOD, as_of=CUTOFF)
    assert error.value.admissions[0].reason_code == "AUTHORITATIVE_PUBLICATION_MISSING"
    assert query_financial_indicators(lake, TS_CODE, REPORT_PERIOD) == before
    assert query_financial_indicators(lake, TS_CODE, REPORT_PERIOD,
        selection="publication", publication_id=publication.publication_id) == before


def test_equivalent_canonical_timestamp_precision_is_not_conflict(trusted):
    obs = replace(trusted, published_at="2026-05-01T00:00:00.000000Z")
    assert evaluate(obs, evidence(obs)).status == "TEMPORALLY_ADMISSIBLE"


def test_later_canonical_revision_does_not_rewrite_pinned_publication(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, _, original = _persist_fact(lake, _raw([_row(eps=2.0)]))
    first = publish_financial_canonical_fact(lake, original)
    pinned = query_financial_indicators(lake, TS_CODE, REPORT_PERIOD,
        selection="publication", publication_id=first.publication_id)
    _, _, correction = _persist_fact(lake,
        _raw([_row(eps=3.0, update_flag="1", ann_date="20260601")]), event=2)
    publish_financial_canonical_fact(lake, correction)
    current = query_financial_indicators(lake, TS_CODE, REPORT_PERIOD)
    assert current != pinned
    with pytest.raises(FinancialAsOfUnavailable) as error:
        query_financial_indicators(lake, TS_CODE, REPORT_PERIOD, as_of=CUTOFF)
    assert len(error.value.admissions) == 2
    assert all(item.status == "UNKNOWN" for item in error.value.admissions)
    assert query_financial_indicators(lake, TS_CODE, REPORT_PERIOD,
        selection="publication", publication_id=first.publication_id) == pinned
    assert query_financial_indicators(lake, TS_CODE, REPORT_PERIOD) == current
