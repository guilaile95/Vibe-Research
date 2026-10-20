from datetime import date, timedelta
import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import historical_signal_validation as hsv
import historical_signal_validation_router as router
import rolling_signal_validation as rolling

DAYS = [(date(2023, 1, 1) + timedelta(days=i)).isoformat() for i in range(360)]
SNAPSHOT = 'a' * 64


def body(**changes):
    return rolling.RollingSignalValidationRequest(**{
        'codes': ['600001'], 'selection_from': DAYS[60], 'selection_to': DAYS[179],
        'holdout_from': DAYS[180], 'holdout_to': DAYS[-1], 'rolling_calendar_days': 60, **changes})


def series():
    return {'600001': (DAYS, [100 + 10 * math.sin(i / 10) for i in range(len(DAYS))])}


def test_full_selection_is_invariant_to_future_price_and_benchmark_changes():
    sample = series()
    benchmark = (DAYS, [100 + i / 10 for i in range(len(DAYS))])
    request = body(benchmark_code='000300', selection_to=DAYS[146], holdout_from=DAYS[147])
    original = rolling.evaluate_series(request, sample, benchmark, SNAPSHOT)
    changed = {'600001': (DAYS, [v if i < 147 else 1000 + i for i, v in enumerate(sample['600001'][1])])}
    changed_bench = (DAYS, [v if i < 147 else None for i, v in enumerate(benchmark[1])])
    result = rolling.evaluate_series(request, changed, changed_bench, SNAPSHOT)
    for before, after in zip(original['trials'], result['trials']):
        assert [s for s in before['segments'] if s['role'] == 'selection'] == [s for s in after['segments'] if s['role'] == 'selection']
    assert original['input_fingerprint'] == result['input_fingerprint']  # snapshot is byte identity authority


def test_boundary_purge_retains_event_but_never_scores_it():
    report = rolling.evaluate_series(body(selection_to=DAYS[146], holdout_from=DAYS[147]), series(), None, SNAPSHOT)
    purged = []
    for trial in report['trials']:
        for segment in trial['segments']:
            for bucket in segment['results'].values():
                assert bucket['events_total'] == sum(bucket[k] for k in ('events_evaluated', 'events_immature', 'events_missing_exit', 'events_purged_label_end'))
                for row in bucket['rows']:
                    if row['status'] == 'PURGED_LABEL_END':
                        purged.append(row)
                        assert row['label_end_date'] > segment['to']
                        assert row['return_pct'] is row['excess_return_pct'] is row['benchmark_missing_reason'] is None
                        assert row['is_worst'] is row['is_failure'] is False
                    elif row['status'] == 'EVALUATED':
                        assert segment['from'] <= row['signal_date'] <= row['exit_date'] <= segment['to']
    assert purged


def test_endpoint_exactly_on_boundary_is_evaluated():
    dates, closes = series()['600001']
    raw = hsv.run_study(series(), None)['windows']['5']['rows']
    event = next(row for row in raw if row['status'] == 'EVALUATED')
    request = body(selection_to=event['exit_date'], holdout_from=dates[dates.index(event['exit_date']) + 1])
    report = rolling.evaluate_series(request, series(), None, SNAPSHOT)
    selection = report['trials'][1]['segments'][0]
    assert next(row for row in selection['results']['5']['rows'] if row['signal_date'] == event['signal_date'])['status'] == 'EVALUATED'


def test_missing_exit_immature_unknown_prior_and_calendar_gaps():
    closes = [100.0] * 360
    closes[80] = 101
    closes[85] = None
    closes[355] = 101
    dates = DAYS.copy()
    sample = {'600001': (dates, closes)}
    report = rolling.evaluate_series(body(), sample, None, SNAPSHOT)
    primary = report['trials'][1]
    selection = primary['segments'][0]['results']['5']
    assert selection['events_missing_exit'] == 1
    holdout = next(s for s in primary['segments'] if s['id'] == 'holdout')['results']['5']
    assert holdout['events_immature'] == 1
    gappy = {'600001': (DAYS[::2], [100 + i for i in range(180)])}
    gaps = rolling.evaluate_series(body(), gappy, None, SNAPSHOT)['trials'][1]['segments'][0]
    assert gaps['coverage']['600001']['calendar_gap_count'] > 20
    assert len(gaps['coverage']['600001']['calendar_gaps']) == 20
    assert gaps['results']['5']['events_excluded_unknown_prior'] == 1


def test_warmup_uses_same_full_history_not_segment_reset():
    report = rolling.evaluate_series(body(), series(), None, SNAPSHOT)
    for trial in report['trials']:
        for segment in trial['segments']:
            coverage = segment['coverage']['600001']
            assert coverage['warmup_observations_before_segment'] == DAYS.index(segment['from'])
            assert coverage['evaluable_observations'] == coverage['stored_observations']
    fresh = rolling.evaluate_series(body(), {'600001': (DAYS[60:], series()['600001'][1][60:])}, None, SNAPSHOT)
    assert fresh['trials'][0]['segments'][0]['coverage']['600001']['evaluable_observations'] < report['trials'][0]['segments'][0]['coverage']['600001']['evaluable_observations']


def test_all_tries_and_seed_identity():
    request = body()
    report = rolling.evaluate_series(request, series(), None, SNAPSHOT)
    assert [t['parameter'] for t in report['trials']] == ['15/60', '20/60', '25/60']
    assert sum(t['frozen_primary'] for t in report['trials']) == 1
    assert rolling.identity(request, SNAPSHOT) == rolling.identity(body(), SNAPSHOT)
    assert rolling.identity(request, SNAPSHOT) != rolling.identity(body(frozen_parameter='15/60'), SNAPSHOT)
    assert rolling.identity(request, SNAPSHOT) != rolling.identity(request, 'b' * 64)
    assert report['historical_validity']['corporate_actions'] == 'NOT_EVALUATED'


@pytest.mark.parametrize('changes', [
    {'holdout_from': DAYS[179]}, {'selection_from': '20230101'}, {'rolling_calendar_days': 1},
    {'rolling_calendar_days': 30.5}, {'frozen_parameter': '5/10'}, {'parameter_preset': 'custom'},
    {'benchmark_code': '600001'}, {'codes': ['123']}, {'code': '600001'},
    {'selection_from': '2000-01-01'}, {'selection_from': '2020-01-01', 'rolling_calendar_days': 30},
])
def test_reject_invalid_contract(changes):
    with pytest.raises(ValidationError):
        body(**changes)


def test_no_data_and_benchmark_date_mismatch_are_not_zero_success():
    empty = rolling.evaluate_series(body(), {}, None, SNAPSHOT)
    assert empty['status'] == 'unavailable'
    assert empty['data']['missing_codes'] == ['600001']
    report = rolling.evaluate_series(body(benchmark_code='000300'), series(), ([], []), SNAPSHOT)
    scored = [b for t in report['trials'] for s in t['segments'] for b in s['results'].values() if b['events_evaluated']]
    assert scored and all(b['excess_return'] is None and b['benchmark_events_missing'] == b['events_evaluated'] for b in scored)


def test_cap_and_cancel():
    with pytest.raises(ValueError, match='work cap'):
        rolling.evaluate_series(body(), {'600001': (DAYS * 100, [100.] * (len(DAYS) * 100))}, None, SNAPSHOT)
    calls = 0
    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 3
    result = rolling.evaluate_series(body(), series(), None, SNAPSHOT, cancelled)
    assert result['status'] == 'cancelled'
    assert len(result['trials']) < 3
    assert result['metrics']['segment_count']['value'] == 2


def test_snapshot_is_pinned_and_cancel_prevents_reads(monkeypatch):
    monkeypatch.setattr(rolling.rdp, 'read_manifest', lambda: {'snapshot_id': SNAPSHOT})
    seen = []
    def page(**kwargs):
        seen.append(kwargs)
        return {'snapshot_id': SNAPSHOT, 'rows': [], 'next_offset': None}
    monkeypatch.setattr(rolling.rdp, 'query_daily_bars', page)
    rolling.evaluate_rdp(body(benchmark_code='000300'))
    assert len(seen) == 2 and all(v['snapshot_id'] == SNAPSHOT and v['date_to'] == DAYS[-1] and 'date_from' not in v for v in seen)
    seen.clear()
    assert rolling.evaluate_rdp(body(), lambda: True)['status'] == 'cancelled'
    assert seen == []
    monkeypatch.setattr(rolling.rdp, 'query_daily_bars', lambda **kwargs: {'snapshot_id': 'b' * 64, 'rows': []})
    with pytest.raises(rolling.rdp.ResearchDataPlaneValidationError):
        rolling.evaluate_rdp(body())


def test_router_unavailable_and_no_unchecked_parameter_grid(monkeypatch):
    app = FastAPI(); app.include_router(router.router)
    client = TestClient(app)
    def unavailable():
        raise rolling.rdp.ResearchDataPlaneUnavailableError('fixture')
    monkeypatch.setattr(rolling.rdp, 'read_manifest', unavailable)
    result = client.post('/api/signals/validation/rolling', json=body().model_dump())
    assert result.status_code == 200 and result.json()['status'] == 'unavailable'
    assert client.post('/api/signals/validation/rolling', json={**body().model_dump(), 'grid': [1, 2, 3]}).status_code == 422


def test_recorded_cancel_mid_compute_stays_cancelled(monkeypatch, tmp_path):
    import experiment_ledger as ledger
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)
    request = body()
    record = ledger.create('rolling-signal', request.model_dump())
    monkeypatch.setattr(rolling.rdp, 'read_manifest', lambda: {'snapshot_id': SNAPSHOT})
    monkeypatch.setattr(rolling, '_load', lambda *args: series())
    original = hsv.run_study
    def cancel_during_study(*args, **kwargs):
        result = original(*args, **kwargs)
        ledger.cancel(record['id'])
        return result
    monkeypatch.setattr(hsv, 'run_study', cancel_during_study)
    report = router.evaluate_rolling(request, record['id'])
    assert report['status'] == 'cancelled'
    assert report['metrics']['segment_count']['value'] == 0
    assert ledger.records()[0]['status'] == 'CANCELLED'
    with pytest.raises(Exception) as exc:
        router.evaluate_rolling(request, record['id'])
    assert exc.value.status_code == 422


def test_partial_sample_and_work_cap_fail_closed():
    report = rolling.evaluate_series(body(codes=['600001', '600002']), series(), None, SNAPSHOT)
    missing = report['trials'][0]['segments'][0]['coverage']['600002']
    assert missing['stored_observations'] == 0
    assert missing['first_date'] is None
    # Structurally valid sequences can still exceed the declared execution budget.
    many = {f'{i:06d}': series()['600001'] for i in range(20)}
    with pytest.raises(ValueError, match='work cap'):
        rolling.evaluate_series(body(selection_from=DAYS[0], rolling_calendar_days=30), many, None, SNAPSHOT)
