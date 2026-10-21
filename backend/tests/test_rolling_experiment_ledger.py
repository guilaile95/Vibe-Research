"""The rolling evaluator owns receipts; ledger stores compact identity only."""
import copy
import pytest
import experiment_ledger as ledger

@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)


def request():
    return {'codes': ['000002', '000001'], 'selection_from': '2024-01-01',
            'selection_to': '2024-06-30', 'holdout_from': '2024-07-01', 'holdout_to': '2024-12-31'}


def test_rolling_identity_compact_receipt_and_count_units():
    body = request()
    record = ledger.create('rolling-signal', body)
    assert record['sample'] == ['000001', '000002']
    assert record['window']['holdout_from'] == body['holdout_from']
    assert record['window']['frozen_parameter'] == '20/60'
    normalized = copy.deepcopy(body); normalized['codes'].reverse()
    report = {'status': 'normal', 'data': {'snapshot_id': 'a' * 64},
              'input_fingerprint': 'b' * 64,
              'metrics': {'trial_count': {'status': 'SUPPORTED', 'value': 3}}}
    ledger.execute(record['id'], 'rolling-signal', normalized, lambda: report)
    saved = ledger.records()[0]
    assert saved['receipt'] == 'SNAPSHOT' and saved['snapshot'] == 'a' * 64
    assert saved['input_identity'] == 'b' * 64 and saved['status'] == 'COMPLETED'
    assert saved['metrics'] == {'trial_count': 3}
    assert ledger.metric_unit(saved, 'trial_count') == 'count'
    assert 'trials' not in saved


def test_changed_frozen_holdout_cannot_execute_record():
    body = request(); record = ledger.create('rolling-signal', body)
    body['holdout_to'] = '2025-01-01'
    with pytest.raises(ValueError):
        ledger.execute(record['id'], 'rolling-signal', body, lambda: pytest.fail('must not run'))
    assert ledger.records()[0]['status'] == 'PENDING'


def test_fingerprint_does_not_substitute_missing_snapshot():
    body = request(); record = ledger.create('rolling-signal', body)
    ledger.execute(record['id'], 'rolling-signal', body, lambda: {
        'status': 'unavailable', 'input_fingerprint': 'b' * 64, 'metrics': {}})
    saved = ledger.records()[0]
    assert saved['receipt'] == 'MISSING' and saved['status'] == 'INCOMPLETE'
    assert 'MISSING_RECEIPT' in ledger.compare(saved, saved)['reasons']
