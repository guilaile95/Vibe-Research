from __future__ import annotations

import copy
import json

import pytest

from data_contracts import CoverageMode
from fact_lake_coverage import (
    CoverageState,
    CoverageValidationError,
    REASON_COVERAGE_INTERIOR_GAP,
    REASON_COVERAGE_UNKNOWN,
    assess_coverage,
)


SESSIONS = ("2026-07-20", "2026-07-21", "2026-07-22")


def test_dense_watermark_stops_before_interior_trading_day_gap():
    result = assess_coverage(
        dataset_id="daily-bars",
        coverage_mode=CoverageMode.SESSION_DENSE,
        sessions=SESSIONS,
        observed_dates=("2026-07-20", "2026-07-22"),
        expected_through="2026-07-22",
    )
    assert result.safe_watermark == "2026-07-20"
    assert result.state is CoverageState.PARTIAL
    assert result.reason_codes == (REASON_COVERAGE_INTERIOR_GAP,)


def test_dense_complete_prefix_is_complete():
    result = assess_coverage(
        dataset_id="daily-bars",
        coverage_mode=CoverageMode.SESSION_DENSE,
        sessions=SESSIONS,
        observed_dates=SESSIONS,
    )
    assert result.safe_watermark == "2026-07-22"
    assert result.state is CoverageState.COMPLETE
    assert result.reason_codes == ()


def test_sparse_quiet_day_is_not_a_dense_gap():
    result = assess_coverage(
        dataset_id="corporate-events",
        coverage_mode=CoverageMode.SPARSE,
        sessions=SESSIONS,
        observed_dates=("2026-07-20", "2026-07-22"),
    )
    assert result.safe_watermark is None
    assert result.state is CoverageState.NOT_APPLICABLE
    assert result.reason_codes == ()


def test_sparse_explicit_boundary_without_observation_remains_unknown():
    result = assess_coverage(
        dataset_id="corporate-events",
        coverage_mode=CoverageMode.SPARSE,
        sessions=SESSIONS,
        observed_dates=("2026-07-20",),
        expected_through="2026-07-22",
    )
    assert result.state is CoverageState.UNKNOWN
    assert result.reason_codes == (REASON_COVERAGE_UNKNOWN,)


@pytest.mark.parametrize("sessions", [
    (),
    ("2026-07-21", "2026-07-20"),
    ("2026-07-20", "2026-07-20"),
    ("2026-02-30",),
])
def test_invalid_sessions_fail_closed(sessions):
    with pytest.raises(CoverageValidationError):
        assess_coverage(
            dataset_id="daily-bars",
            coverage_mode=CoverageMode.SESSION_DENSE,
            sessions=sessions,
            observed_dates=(),
        )


def test_assessment_round_trip_and_input_is_not_mutated():
    sessions = list(SESSIONS)
    observed = ["2026-07-20", "2026-07-22"]
    before = copy.deepcopy((sessions, observed))
    result = assess_coverage(
        dataset_id="daily-bars",
        coverage_mode=CoverageMode.SESSION_DENSE,
        sessions=sessions,
        observed_dates=observed,
    )
    assert (sessions, observed) == before
    encoded = json.loads(json.dumps(result.to_dict()))
    assert result.from_dict(encoded) == result


def test_no_time_or_io_imports():
    import inspect
    import fact_lake_coverage as module

    source = inspect.getsource(module)
    assert "datetime.now" not in source
    assert "open(" not in source
    assert "sqlite" not in source.lower()
    assert "requests" not in source.lower()
