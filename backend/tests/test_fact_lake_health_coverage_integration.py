from __future__ import annotations

import fact_lake_health as flh
from data_contracts import CoverageMode
from fact_lake_coverage import CoverageState, assess_coverage
from test_fact_lake_health import _evidence, _limit_up_spec


def test_dense_interior_gap_blocks_current_health():
    spec = _limit_up_spec()
    coverage = assess_coverage(
        dataset_id=spec.dataset_id,
        coverage_mode=CoverageMode.SESSION_DENSE,
        sessions=("2026-08-08", "2026-08-09", "2026-08-10"),
        observed_dates=("2026-08-08", "2026-08-10"),
        expected_through="2026-08-10",
    )
    evidence = _evidence(
        spec=spec,
        primary_field=__import__("data_contracts").TemporalSemantics.TRADE_DATE,
        primary_value="2026-08-10",
        expected="2026-08-10",
        coverage=coverage,
    )
    assessment = flh.assess_publication_health(dataset_spec=spec, evidence=evidence)
    assert coverage.state is CoverageState.PARTIAL
    assert assessment.freshness != "CURRENT"
    assert assessment.canonical_admissibility == "BLOCKED"
    assert "COVERAGE_INTERIOR_GAP" in assessment.reason_codes


def test_sparse_quiet_day_does_not_create_dense_gap():
    spec = _limit_up_spec()
    sparse = assess_coverage(
        dataset_id=spec.dataset_id,
        coverage_mode=CoverageMode.SPARSE,
        sessions=("2026-08-08", "2026-08-09", "2026-08-10"),
        observed_dates=("2026-08-08", "2026-08-10"),
    )
    assessment = flh.assess_publication_health(
        dataset_spec=spec,
        evidence=_evidence(spec=spec, coverage=sparse),
    )
    assert sparse.state is CoverageState.NOT_APPLICABLE
    assert "COVERAGE_INTERIOR_GAP" not in assessment.reason_codes
