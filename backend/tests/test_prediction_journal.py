"""Synthetic, offline fixtures only; no real forecast or model-quality evidence."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import copy
import json
from offline_testclient import offline_network

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import prediction_journal as journal
from prediction_journal_router import router

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path, offline_network):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)
    monkeypatch.setattr(journal, 'now', lambda: T0)



def forecast(**changes):
    return journal.Forecast.model_validate(dict(id=str(uuid4()), subject='Synthetic subject', question='Will the fixture meet its criterion by deadline?', probability=0.7,
        deadline=(T0 + timedelta(days=1)).isoformat(), evidence_context='Synthetic initial context', evidence_kind='USER_ASSERTION', outcome_not_known=True, **changes))


def resolution(revision=0, **changes):
    values = dict(expected_revision=revision, outcome='TRUE', available_at=(T0 + timedelta(days=1)).isoformat(), evidence='Manual synthetic evidence', evidence_kind='SOURCE_REFERENCE', correction_reason='First manual adjudication')
    values.update(changes)
    return journal.Resolution.model_validate(values)


def settle(monkeypatch, f=None, outcome='TRUE'):
    f = f or forecast()
    journal.create(f)
    monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=2))
    journal.resolve(str(f.id), resolution(outcome=outcome))
    return f


def test_empty_read_creates_no_database(tmp_path):
    before = list(tmp_path.rglob('*'))
    result = journal.listing()
    assert result['records'] == []
    assert result['summary']['brier'] is None
    assert result['summary']['benchmark_brier'] is None
    assert result['summary']['unresolved'] == 0
    assert len(result['summary']['bins']) == 10
    assert list(tmp_path.rglob('*')) == before


def test_persistent_forecast_immutable_and_duplicate_conflict():
    f = forecast()
    original = journal.create(f)
    assert journal.listing()['records'][0]['forecast'] == original['forecast']
    assert journal.listing()['summary']['unresolved'] == 1
    changed = f.model_copy(update={'probability': 0.1})
    with pytest.raises(journal.Conflict):
        journal.create(changed)
    assert journal.listing()['records'][0]['forecast']['probability'] == 0.7


def test_no_backdating_or_unknown_assertion():
    raw = forecast().model_dump(mode='json')
    for key in ('locked_at', 'created_at', 'issued_at'):
        with pytest.raises(ValidationError):
            journal.Forecast.model_validate({**raw, key: T0.isoformat()})
    for known in (False, 1, 'true'):
        with pytest.raises(ValidationError):
            journal.Forecast.model_validate({**raw, 'outcome_not_known': known})
    with pytest.raises(ValueError):
        journal.create(journal.Forecast.model_validate({**raw, 'deadline': T0.isoformat()}))


def test_capture_timestamp_after_transaction_lock(monkeypatch):
    f = forecast()
    original = journal.store.write
    @contextmanager
    def delayed():
        with original() as conn:
            monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=2))
            yield conn
    monkeypatch.setattr(journal.store, 'write', delayed)
    with pytest.raises(ValueError):
        journal.create(f)
    assert journal.listing()['records'] == []


def test_corrections_are_append_only_and_compare_and_swap(monkeypatch):
    f = settle(monkeypatch)
    old = copy.deepcopy(journal.listing()['records'][0])
    with pytest.raises(journal.Conflict):
        journal.resolve(str(f.id), resolution(0, outcome='FALSE'))
    monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=3))
    journal.resolve(str(f.id), resolution(1, outcome='FALSE', correction_reason='Corrected manual classification'))
    new = journal.listing()['records'][0]
    assert new['forecast'] == old['forecast']
    assert new['history'][0] == old['history'][0]
    assert new['revision'] == 2 and new['outcome'] == 'FALSE'
    assert journal.listing()['summary']['brier'] == pytest.approx(0.49)
    historical = journal.listing((T0 + timedelta(days=2)).isoformat())
    assert historical['records'][0]['outcome'] == 'TRUE'
    assert len(historical['records'][0]['history']) == 1
    assert historical['summary']['brier'] == pytest.approx(0.09)


def test_late_result_cannot_leak_to_earlier_asof(monkeypatch):
    settle(monkeypatch)
    before = journal.listing((T0 - timedelta(seconds=1)).isoformat())
    assert before['records'] == []
    between = journal.listing((T0 + timedelta(days=1, hours=12)).isoformat())
    assert between['records'][0]['history'] == []
    assert between['records'][0]['outcome'] == 'UNRESOLVED'
    assert between['summary']['brier'] is None
    with pytest.raises(ValueError):
        journal.listing((T0 + timedelta(days=3)).isoformat())


def test_early_future_and_naive_timestamps_rejected(monkeypatch):
    f = forecast(); journal.create(f)
    with pytest.raises(ValueError):
        journal.resolve(str(f.id), resolution())
    monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=2))
    for stamp in (T0, T0 + timedelta(days=3)):
        with pytest.raises(ValueError):
            journal.resolve(str(f.id), resolution(available_at=stamp))
    with pytest.raises(ValueError):
        resolution(available_at='2026-01-02T00:00:00')
    with pytest.raises(ValueError):
        journal.listing('2026-01-02T00:00:00')


def test_indeterminate_excluded_unresolved_separate(monkeypatch):
    a, b = forecast(), forecast()
    journal.create(a); journal.create(b)
    monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=2))
    journal.resolve(str(a.id), resolution(outcome='INDETERMINATE'))
    summary = journal.listing()['summary']
    assert summary['total'] == 2 and summary['indeterminate'] == summary['unresolved'] == 1
    assert summary['resolved_binary'] == 0 and summary['brier'] is None


def test_fixed_bins_ties_extremes_and_units():
    records = [dict(forecast={'probability': p, 'benchmark_probability': None}, outcome=y) for p, y in [(0, 'TRUE'), (1, 'FALSE'), (0.1, 'TRUE'), (0.1, 'FALSE'), (0.7, 'TRUE')]]
    summary = journal.summarize(records)
    assert summary['brier'] == pytest.approx((1 + 1 + .81 + .01 + .09) / 5)
    assert summary['bins'][0]['count'] == 1
    assert summary['bins'][1]['count'] == 2
    assert summary['bins'][1]['mean_probability'] == 0.1
    assert summary['bins'][1]['observed_frequency'] == 0.5
    assert summary['bins'][9]['count'] == 1 and summary['bins'][9]['upper_inclusive'] is True
    assert sum(b['count'] for b in summary['bins']) == 5
    assert summary['sample_caution'] is True


def test_benchmark_only_matching_pre_registered_subset(monkeypatch):
    a = forecast(benchmark_probability=0.2, benchmark_context='Synthetic prior population, frozen before result')
    b = forecast()
    journal.create(a); journal.create(b)
    monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=2))
    journal.resolve(str(a.id), resolution())
    journal.resolve(str(b.id), resolution(outcome='FALSE'))
    summary = journal.listing()['summary']
    assert summary['benchmark_count'] == 1
    assert summary['benchmark_brier'] == pytest.approx(0.64)
    assert summary['matched_forecast_brier'] == pytest.approx(0.09)
    assert summary['brier'] == pytest.approx(0.29)
    with pytest.raises(ValidationError):
        forecast(benchmark_probability=0.2)


@pytest.mark.parametrize('probability', [-0.1, 1.1, float('nan'), float('inf'), True, '0.5'])
def test_invalid_probabilities(probability):
    raw = forecast().model_dump(mode='json')
    with pytest.raises(ValidationError):
        journal.Forecast.model_validate({**raw, 'probability': probability})


def test_corrupt_record_fail_closed():
    f = forecast(); journal.create(f)
    with journal.store.write() as conn:
        conn.execute('UPDATE prediction_forecasts SET payload=? WHERE id=?', ('{"digest":"bad"}', str(f.id)))
    with pytest.raises(journal.store.StoreError):
        journal.listing()


def test_http_contract_conflict_unknown_and_no_edit(monkeypatch):
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        f = forecast().model_dump(mode='json')
        response = client.post('/api/prediction-journal', json=f)
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert client.post('/api/prediction-journal', json=f).status_code == 409
        assert client.put('/api/prediction-journal/' + f['id'], json=f).status_code == 404
        assert client.post('/api/prediction-journal', json={**f, 'created_at': T0.isoformat()}).status_code == 422
        monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=2))
        body = resolution().model_dump(mode='json')
        assert client.post('/api/prediction-journal/missing/resolutions', json=body).status_code == 404
        assert client.post('/api/prediction-journal/' + f['id'] + '/resolutions', json=body).status_code == 200
        assert client.post('/api/prediction-journal/' + f['id'] + '/resolutions', json=body).status_code == 409
        assert client.post('/api/prediction-journal/' + f['id'] + '/resolutions', json={**body, 'outcome': 'unknown'}).status_code == 422
        assert client.get('/api/prediction-journal?as_of=2026-01-02T12:00:00Z').json()['summary']['unresolved'] == 1
        assert client.get('/api/prediction-journal?as_of=invalid').status_code == 422


def test_resolution_cannot_edit_forecast_or_timestamp():
    raw = resolution().model_dump(mode='json')
    for field in ('probability', 'recorded_at', 'forecast', 'revision'):
        with pytest.raises(ValidationError):
            journal.Resolution.model_validate({**raw, field: 'forbidden'})


def test_changed_clock_and_record_limits_fail_closed(monkeypatch):
    f = settle(monkeypatch)
    monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=1, hours=1))
    with pytest.raises(ValueError):
        journal.resolve(str(f.id), resolution(1, outcome='FALSE'))
    assert len(journal.listing()['records'][0]['history']) == 0
    monkeypatch.setattr(journal, 'now', lambda: T0)
    monkeypatch.setattr(journal, 'LIMIT', 1)
    with pytest.raises(ValueError):
        journal.create(forecast())


def test_orphan_resolution_rejected():
    with journal.store.write() as conn:
        conn.execute('INSERT INTO prediction_resolutions VALUES(?,?,?)', ('orphan', 1, '{}'))
    with pytest.raises(journal.store.StoreError):
        journal.listing()


def test_concurrent_resolution_only_one_expected_revision_wins(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    f = forecast(); journal.create(f)
    monkeypatch.setattr(journal, 'now', lambda: T0 + timedelta(days=2))
    def attempt(outcome):
        try:
            journal.resolve(str(f.id), resolution(outcome=outcome))
            return 'saved'
        except journal.Conflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ['TRUE', 'FALSE'])) == ['conflict', 'saved']
    assert len(journal.listing()['records'][0]['history']) == 1
