"""Offline experiment manifest acceptance; existing calculation engines only."""
import copy
import json
from offline_testclient import offline_network
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import experiment_ledger as ledger
import experiment_ledger_router
import research_analytics_router
import factor_validation_router
from research_analytics_examples import example_input
from research_analytics_contract import SimulationRequest
from research_analytics_simulation import simulate


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path, offline_network):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)



def run(body=None):
    body = body or example_input('simulation')
    record = ledger.create('simulation', body)
    ledger.execute(record['id'], 'simulation', body, lambda: simulate(SimulationRequest.model_validate(body)))
    return next(x for x in ledger.records() if x['id'] == record['id'])


def test_same_input_different_run_ids_normalized_and_read_only():
    a, b = run(), run()
    assert a['id'] != b['id'] and a['input_identity'] == b['input_identity']
    path = ledger.store.facts.resolve_db_path()
    before = {str(x): (x.stat().st_mtime_ns, x.read_bytes()) for x in path.parent.iterdir() if x.is_file()}
    result = ledger.compare(a, b)
    assert result['same_input'] and result['changes'] == []
    assert all(x['delta'] in (None, 0) for x in result['metrics'])
    ledger.records()
    after = {str(x): (x.stat().st_mtime_ns, x.read_bytes()) for x in path.parent.iterdir() if x.is_file()}
    assert before == after
    assert 'bars' not in json.dumps(a) and 'initial_cash' not in a


@pytest.mark.parametrize('field,value', [('rules_version', 'changed'), ('subject', 'other'), ('sample', ['other']), ('window', {'from': 'other'}), ('benchmark', 'other'), ('snapshot', '1'*64), ('currency', 'USD'), ('scope', 'WHOLE_ACCOUNT')])
def test_changed_dimension_is_incomparable(field, value):
    a = run(); b = copy.deepcopy(a); b[field] = value
    result = ledger.compare(a, b)
    assert field in result['changes']
    assert all(x['delta'] is None and x['status'] == 'INCOMPARABLE' for x in result['metrics'])


def test_missing_receipt_is_not_same_input_or_zero_metric():
    a = run(); b = copy.deepcopy(a); b.update(receipt='MISSING', input_identity=None, metrics={'total_return': None})
    result = ledger.compare(a, b)
    assert not result['same_input'] and 'MISSING_RECEIPT' in result['reasons']
    assert all(x['delta'] is None for x in result['metrics'])


def test_failed_and_cancelled_retained_and_terminal_race():
    body = example_input('simulation')
    failed = ledger.create('simulation', body)
    def fail():
        raise RuntimeError('private path must not be stored')
    with pytest.raises(RuntimeError):
        ledger.execute(failed['id'], 'simulation', body, fail)
    cancelled = ledger.create('simulation', body)
    def raced():
        ledger.cancel(cancelled['id'])
        return simulate(SimulationRequest.model_validate(body))
    ledger.execute(cancelled['id'], 'simulation', body, raced)
    values = {x['id']: x for x in ledger.records()}
    assert values[failed['id']]['status'] == 'FAILED'
    assert values[cancelled['id']]['status'] == 'CANCELLED'
    assert values[cancelled['id']]['metrics'] == {}
    assert 'private path' not in json.dumps(values)
    with pytest.raises(ValueError):
        ledger.execute(cancelled['id'], 'simulation', body, fail)


def test_changed_request_and_subject_cannot_hijack_pending_run():
    body = example_input('simulation'); record = ledger.create('simulation', body)
    changed = copy.deepcopy(body); changed['initial_cash'] *= 2
    with pytest.raises(ValueError):
        ledger.execute(record['id'], 'simulation', changed, lambda: pytest.fail('must not evaluate'))
    assert ledger.records()[0]['status'] == 'PENDING'


def test_corrupt_read_fails_closed():
    record = run()
    with ledger.store.write() as conn:
        conn.execute('UPDATE experiment_records SET payload=? WHERE id=?', ('{"status":"COMPLETED","status":"FAILED"}', record['id']))
    with pytest.raises(ledger.store.StoreError):
        ledger.records()


def test_manifest_tamper_and_nonfinite_rejected():
    record = run(); record['metrics']['total_return'] = 900
    with pytest.raises(ValueError):
        ledger.validate(record, record['id'])
    record['metrics']['total_return'] = float('nan')
    with pytest.raises(ValueError):
        ledger.seal(record)


def test_api_capture_opt_in_and_request_mismatch(monkeypatch):
    app = FastAPI(); app.include_router(experiment_ledger_router.router); app.include_router(research_analytics_router.router)
    client = TestClient(app)
    body = example_input('simulation')
    assert client.post('/api/research-analytics/simulation', json=body).status_code == 200
    assert client.get('/api/research-experiments').json()['records'] == []
    rec = client.post('/api/research-experiments', json={'kind': 'simulation', 'input': body}).json()
    altered = copy.deepcopy(body); altered['initial_cash'] *= 2
    assert client.post('/api/research-analytics/simulation?record_id='+rec['id'], json=altered).status_code == 422
    assert client.post('/api/research-analytics/simulation?record_id='+rec['id'], json=body).status_code == 200
    comparison = client.get('/api/research-experiments/compare', params={'left': rec['id'], 'right': rec['id']})
    assert comparison.status_code == 200 and comparison.headers['cache-control'] == 'no-store'
    assert comparison.json()['same_input']
    assert client.post('/api/research-analytics/simulation?record_id='+rec['id'], json=body).status_code == 422


def test_factor_receipt_from_actual_report_and_unavailable(monkeypatch):
    body = {'factor_id': 'return_5d'}
    record = ledger.create('factor', body)
    report = {'status': 'normal', 'source': {'snapshot_id': 'a'*64}, 'results': {'5': {'mean_ic': .2}}}
    ledger.execute(record['id'], 'factor', body, lambda: report)
    a = ledger.records()[0]
    assert a['receipt'] == 'SNAPSHOT' and a['snapshot'] == 'a'*64
    record = ledger.create('factor', body)
    ledger.execute(record['id'], 'factor', body, lambda: {'status': 'unavailable', 'results': {}})
    b = ledger.records()[0]
    assert b['status'] == 'INCOMPLETE' and b['receipt'] == 'MISSING'
    assert 'RUN_NOT_COMPLETED' in ledger.compare(a, b)['reasons']


def test_pending_cancel_and_bound_preserve_history(monkeypatch):
    monkeypatch.setattr(ledger, 'LIMIT', 1)
    body = example_input('simulation'); record = ledger.create('simulation', body)
    with pytest.raises(ValueError):
        ledger.create('simulation', body)
    assert ledger.cancel(record['id'])['status'] == 'CANCELLED'
    assert len(ledger.records()) == 1


def test_signal_sample_and_benchmark_pages_pin_original_snapshot(monkeypatch):
    import historical_signal_validation as hsv
    snapshot = 'b'*64
    monkeypatch.setattr(hsv.rdp, 'read_manifest', lambda: {'snapshot_id': snapshot, 'dataset_id': 'synthetic', 'artifact_sha256': 'c'*64})
    calls = []
    def query(**kwargs):
        calls.append(kwargs)
        # A moved latest pointer is irrelevant: only the original immutable receipt is accepted.
        assert kwargs['snapshot_id'] == snapshot
        return {'rows': [], 'snapshot_id': snapshot, 'next_offset': None}
    monkeypatch.setattr(hsv.rdp, 'query_daily_bars', query)
    result = hsv.evaluate_rdp(signal_id=hsv.SIGNAL_ID, codes=['600000'], benchmark_code='000001')
    assert len(calls) == 2 and result['data']['snapshot_id'] == snapshot
    monkeypatch.setattr(hsv.rdp, 'query_daily_bars', lambda **kwargs: {'rows': [], 'snapshot_id': 'd'*64})
    with pytest.raises(hsv.rdp.ResearchDataPlaneValidationError):
        hsv.evaluate_rdp(signal_id=hsv.SIGNAL_ID, codes=['600000'])


def test_api_source_failure_retains_failed_record(monkeypatch):
    app = FastAPI(); app.include_router(experiment_ledger_router.router); app.include_router(research_analytics_router.router)
    client = TestClient(app)
    body = example_input('simulation')
    rec = client.post('/api/research-experiments', json={'kind': 'simulation', 'input': body}).json()
    def fail(_):
        raise ValueError('PRIVATE_SOURCE_PATH')
    monkeypatch.setattr(research_analytics_router, 'simulate', fail)
    response = client.post('/api/research-analytics/simulation?record_id='+rec['id'], json=body)
    assert response.status_code == 422 and 'PRIVATE_SOURCE_PATH' not in response.text
    saved = client.get('/api/research-experiments').json()['records'][0]
    assert saved['status'] == 'FAILED' and saved['receipt'] == 'MISSING'


def test_metric_units_are_explicit_and_not_cross_compared():
    a = run(); result = ledger.compare(a, a)
    units = {x['name']: x['left_unit'] for x in result['metrics']}
    assert units['total_return'] == 'fraction' and units['final_value'] == 'CNY'
    assert units['trade_count'] == 'count'


def test_archive_get_fails_closed_when_execution_transitions_during_snapshot_read(monkeypatch):
    """The mid-execution UI GET can encounter a real source transition, not invalid input."""
    app = FastAPI(); app.include_router(experiment_ledger_router.router)
    client = TestClient(app)
    body = example_input('simulation')
    record = ledger.create('simulation', body)
    assert client.get('/api/research-experiments').status_code == 200
    original = ledger._rows
    transitioned = False
    def rows_with_execution(conn):
        nonlocal transitioned
        rows = original(conn)
        if not transitioned and conn.execute('PRAGMA query_only').fetchone()[0]:
            transitioned = True
            ledger.execute(record['id'], 'simulation', body, lambda: simulate(SimulationRequest.model_validate(body)))
        return rows
    monkeypatch.setattr(ledger, '_rows', rows_with_execution)
    response = client.get('/api/research-experiments')
    assert response.status_code == 422
    assert response.json()['detail'] == '实验记录无法核对；检查输入合同或归档状态，原记录已保留'
    after = client.get('/api/research-experiments')
    assert after.status_code == 200 and after.json()['records'][0]['status'] == 'COMPLETED'
