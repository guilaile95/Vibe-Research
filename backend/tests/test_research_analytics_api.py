import asyncio
import copy
import hashlib
import json
import math
import sqlite3

import httpx
import pytest
from fastapi import FastAPI

from research_analytics_router import router
from research_analytics_examples import example_input
from research_analytics_adapters import ledger_performance
from research_analytics_contract import LedgerPerformanceRequest
from test_research_analytics import compact


def call(path, body=None):
    app = FastAPI()
    app.include_router(router)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            return await (client.get(path) if body is None else client.post(path, json=body))
    return asyncio.run(run())


def test_all_api_modes_and_explicit_missing_ledger():
    for mode in ['simulation', 'scenario', 'performance', 'ledger-performance']:
        example = call('/api/research-analytics/example/' + mode)
        assert example.status_code == 200 and example.json()['synthetic']
        response = call('/api/research-analytics/' + mode, example.json()['input'])
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        report = response.json()
        assert report['formal_writes'] == 0 and report['research_only']
        assert report['status'] == ('MISSING_INPUTS' if mode == 'ledger-performance' else 'CALCULATED')


def test_error_no_private_input_or_code_echo_and_no_execution():
    body = example_input('simulation')
    body['private_note'] = 'PRIVATE_CANARY_123'
    body['python_code'] = '__import__("os").system("do not execute")'
    response = call('/api/research-analytics/simulation', body)
    assert response.status_code == 422
    assert 'PRIVATE_CANARY' not in response.text and '__import__' not in response.text
    assert 'traceback' not in response.text.lower()


def test_input_budget_rejected_before_calculation():
    body = example_input('simulation')
    body['instruments'] *= 21
    assert call('/api/research-analytics/simulation', body).status_code == 422


def test_real_readonly_ledger_adapter_binds_exact_ids_and_actual_dates(tmp_path, monkeypatch):
    import trade_ledger_store as store
    import account_event_store
    import trade_ledger_service as ledger
    db = tmp_path / 'ledger.sqlite3'
    conn = sqlite3.connect(db)
    conn.execute(store._CREATE_TABLE_SQL)
    conn.execute(account_event_store._CREATE_TABLE_SQL)
    conn.execute("INSERT INTO trade_records(trade_id,code,name,operation,execution_status,actual_price,actual_quantity,executed_at,fee,other_cost,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 ('a' * 32, '000001', 'SYNTHETIC', 'buy', 'full', 11, 100, '2025-01-03T06:00:00+00:00', 1, 0, '2025-01-03T06:00:00+00:00'))
    conn.commit(); conn.close()
    before = db.read_bytes()
    monkeypatch.setattr(ledger, 'resolve_db_path', lambda: db)
    body = compact()
    for k in ('strategy', 'initial_cash', 'benchmark', 'terminal_liquidation', 'robustness'): body.pop(k)
    body['instruments'][0]['code'] = '000001'
    body.update(opening=[{'code': '000001', 'quantity': 100.0}], ledger_fees_confirmed=True, opening_positions_complete=True)
    report = ledger_performance(LedgerPerformanceRequest.model_validate(body))
    assert report['status'] == 'CALCULATED'
    assert report['selected_trade_ids'] == ['a' * 32]
    assert report['whole_account_performance'] is False
    assert db.read_bytes() == before
    assert 'actual execution/payment dates' in report['flow_convention']
    assert report['curve'][1]['value'] == 2200
    # Different authoritative ledger fee changes fingerprint, even same request.
    conn = sqlite3.connect(db); conn.execute('UPDATE trade_records SET fee=2'); conn.commit(); conn.close()
    second = ledger_performance(LedgerPerformanceRequest.model_validate(body))
    assert second['input_fingerprint'] != report['input_fingerprint']


def test_rdp_adapter_preserves_missing_constraints_and_receipts(monkeypatch):
    import research_analytics_adapters as adapters
    monkeypatch.setattr(adapters, '_current_rdp_snapshot', lambda _: 'FIXED')
    import research_data_plane as rdp
    seen = []
    def query(**kwargs):
        seen.append(kwargs)
        return {'rows': [{'trade_date': '2025-01-02', 'open': 10, 'close': 11}],
                'provenance': {'artifact_sha256': 'a' * 64}, 'replay_receipt': {'snapshot_id': 'fixture'}, 'next_offset': None}
    monkeypatch.setattr(rdp, 'query_daily_bars', query)
    response = call('/api/research-analytics/rdp-inputs', {'codes': ['000001'], 'date_from': '2025-01-02', 'date_to': '2025-01-03'})
    report = response.json()
    assert response.status_code == 200 and len(seen) == 1
    assert report['instruments'][0]['fee_bps'] is None
    assert report['instruments'][0]['bars'][0]['suspended'] is None
    assert report['instruments'][0]['corporate_actions_complete'] is False
    assert report['receipts'][0]['provenance']['artifact_sha256'] == 'a' * 64
    assert 'sessions' not in report  # observed dates never masquerade as calendar


def test_missing_rdp_private_exception_redacted(monkeypatch):
    import research_analytics_adapters as adapters
    monkeypatch.setattr(adapters, '_current_rdp_snapshot', lambda _: 'FIXED')
    import research_data_plane as rdp
    def unavailable(**kwargs):
        raise rdp.ResearchDataPlaneUnavailableError('/private/path/CANARY')
    monkeypatch.setattr(rdp, 'query_daily_bars', unavailable)
    response = call('/api/research-analytics/rdp-inputs', {'codes': ['000001'], 'date_from': '2025-01-02', 'date_to': '2025-01-03'})
    assert response.status_code == 200
    assert 'CANARY' not in response.text and '/private' not in response.text
    assert response.json()['missing'][0]['reason'] == 'RDP_UNAVAILABLE_OR_INVALID'


def test_catalog_actual_inventory_not_invented_43():
    result = call('/api/research-analytics/catalog').json()
    assert len(result['metric_inventory']) == 20
    assert 'withdrawn' in result['inventory_correction']
    assert all(row.get('value') is None for row in result['supplemental_inventory'] if row['status'] == 'UNSUPPORTED')


def _result_difference_paths(actual, expected, path='result'):
    """Diagnostic only: never decides which differences the comparator accepts."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        paths = [f'{path}.{key} (missing/extra)' for key in sorted(actual.keys() ^ expected.keys())]
        for key in sorted(actual.keys() & expected.keys()):
            paths.extend(_result_difference_paths(actual[key], expected[key], f'{path}.{key}'))
        return paths
    if isinstance(actual, list) and isinstance(expected, list):
        paths = [f'{path}.length'] if len(actual) != len(expected) else []
        for index, (a, e) in enumerate(zip(actual, expected)):
            paths.extend(_result_difference_paths(a, e, f'{path}[{index}]'))
        return paths
    return [] if actual == expected else [path]


def _assert_browser_fixture_result(mode, actual, expected):
    # Windows CPython 3.12 produced 0.315221110334431 rather than the stored
    # 0.31522111033443095: exactly one binary64 ULP. This sole dimensionless
    # statistic is covariance(returns, benchmark) / variance(benchmark), whose
    # floating reduction may round differently across supported runtimes.
    # Do not approximate cash, fees, counts, currencies, or fingerprints.
    # Derived returns remain exact except for the observed performance MWR leaf below.
    if mode == 'simulation':
        actual_beta = actual['metrics']['benchmark_beta']['value']
        expected_beta = expected['metrics']['benchmark_beta']['value']
        assert type(actual_beta) is float and type(expected_beta) is float
        assert math.isfinite(actual_beta) and math.isfinite(expected_beta)
        assert abs(actual_beta - expected_beta) <= math.ulp(expected_beta), (
            'simulation.metrics.benchmark_beta.value differs by more than one ULP',
            actual_beta, expected_beta,
        )
        actual = copy.deepcopy(actual)
        actual['metrics']['benchmark_beta']['value'] = expected_beta
    elif mode == 'performance':
        # Windows CPython 3.12: 0.2097667950891632 vs 0.20976679508916318,
        # also exactly one ULP. xirr's bounded exp/fsum bisection ends with
        # expm1(log_rate * span); this leaf is a dimensionless period return.
        # The annual rate, root contract, valuations, and cash flows stay exact.
        actual_return = actual['mwr']['period_return']
        expected_return = expected['mwr']['period_return']
        assert type(actual_return) is float and type(expected_return) is float
        assert math.isfinite(actual_return) and math.isfinite(expected_return)
        assert abs(actual_return - expected_return) <= math.ulp(expected_return), (
            'performance.result.mwr.period_return differs by more than one ULP',
            actual_return, expected_return,
        )
        actual = copy.deepcopy(actual)
        actual['mwr']['period_return'] = expected_return
    assert actual == expected, _result_difference_paths(actual, expected, mode + '.result')


def _browser_fixture():
    from pathlib import Path
    return json.loads((Path(__file__).parents[2] / 'frontend/tests/e2e/research-analytics.fixture.json').read_text(encoding="utf-8"))


@pytest.mark.parametrize('mode', ['simulation', 'scenario', 'performance', 'ledger-performance', 'cost-comparison'])
def test_browser_fixture_exact_current_source_parity(mode):
    from research_analytics_contract import SimulationRequest, ScenarioRequest, PerformanceRequest
    from research_analytics import performance, scenario
    from research_analytics_simulation import simulate
    from research_cost_comparison import CostComparisonRequest, compare_costs
    fixture = _browser_fixture()
    model, fn = {
        'simulation': (SimulationRequest, simulate), 'scenario': (ScenarioRequest, scenario),
        'performance': (PerformanceRequest, performance),
        'ledger-performance': (LedgerPerformanceRequest, ledger_performance),
        'cost-comparison': (CostComparisonRequest, compare_costs),
    }[mode]
    _assert_browser_fixture_result(mode, fn(model.model_validate(fixture[mode]['input'])), fixture[mode]['result'])


@pytest.mark.parametrize('toward', [math.inf, -math.inf])
def test_browser_parity_allows_only_one_beta_ulp_without_mutating_results(toward):
    expected = _browser_fixture()['simulation']['result']
    actual = copy.deepcopy(expected)
    actual['metrics']['benchmark_beta']['value'] = math.nextafter(expected['metrics']['benchmark_beta']['value'], toward)
    before = copy.deepcopy(actual)
    _assert_browser_fixture_result('simulation', actual, expected)
    assert actual == before
    # The same numeric path in any other mode has no exemption.
    with pytest.raises(AssertionError):
        _assert_browser_fixture_result('scenario', actual, expected)


@pytest.mark.parametrize('change', ['two_ulps', 'basis_point', 'nan', 'infinity', 'boolean',
                                  'cash_ulp', 'fees_ulp', 'trade_count', 'currency',
                                  'fingerprint', 'status', 'missing_key', 'extra_key'])
def test_browser_parity_rejects_substantive_or_unrelated_changes(change):
    expected = _browser_fixture()['simulation']['result']
    actual = copy.deepcopy(expected)
    beta = actual['metrics']['benchmark_beta']
    if change == 'two_ulps': beta['value'] = math.nextafter(math.nextafter(beta['value'], math.inf), math.inf)
    elif change == 'basis_point': beta['value'] += 0.0001
    elif change == 'nan': beta['value'] = math.nan
    elif change == 'infinity': beta['value'] = math.inf
    elif change == 'boolean': beta['value'] = True
    elif change == 'cash_ulp': actual['metrics']['final_value']['value'] = math.nextafter(actual['metrics']['final_value']['value'], math.inf)
    elif change == 'fees_ulp': actual['total_fees'] = math.nextafter(actual['total_fees'], math.inf)
    elif change == 'trade_count': actual['metrics']['trade_count']['value'] += 1
    elif change == 'currency': actual['currency'] = 'USD'
    elif change == 'fingerprint': actual['input_fingerprint'] = '0' * 64
    elif change == 'status': beta['status'] = 'UNSUPPORTED'
    elif change == 'missing_key': del actual['currency']
    elif change == 'extra_key': actual['unknown'] = None
    with pytest.raises(AssertionError):
        _assert_browser_fixture_result('simulation', actual, expected)


def test_rdp_snapshot_is_pinned_across_pages_and_codes(monkeypatch):
    import research_analytics_adapters as adapters
    monkeypatch.setattr(adapters, '_current_rdp_snapshot', lambda _: 'FIXED')
    import research_data_plane as rdp
    seen = []
    def query(**kwargs):
        seen.append(kwargs)
        return {'rows': [], 'provenance': {}, 'snapshot_id': 'FIXED', 'replay_receipt': {}, 'next_offset': None}
    monkeypatch.setattr(rdp, 'query_daily_bars', query)
    call('/api/research-analytics/rdp-inputs', {'codes': ['000001', '000002'], 'date_from': '2025-01-02', 'date_to': '2025-01-03'})
    assert seen[0]['snapshot_id'] == 'FIXED'
    assert seen[1]['snapshot_id'] == 'FIXED'


def test_correction_events_fail_closed_on_same_frozen_image(tmp_path, monkeypatch):
    import account_event_store
    import trade_ledger_service as ledger
    db = tmp_path / 'ledger.sqlite3'
    conn = sqlite3.connect(db)
    conn.execute(account_event_store._CREATE_TABLE_SQL)
    import trade_ledger_store
    conn.execute(trade_ledger_store._CREATE_TABLE_SQL)
    conn.execute("INSERT INTO account_events(event_id,event_type,provenance,created_at,target_event_id,target_event_type,before_payload,after_payload) VALUES(?,?,?,?,?,?,?,?)",
                 ('c' * 32, 'CORRECTION', 'SYNTHETIC', '2025-01-03T06:00:00Z', 'a' * 32, 'trade', '{}', '{}'))
    conn.commit(); conn.close()
    before = db.read_bytes()
    monkeypatch.setattr(ledger, 'resolve_db_path', lambda: db)
    body = compact()
    for k in ('strategy', 'initial_cash', 'benchmark', 'terminal_liquidation', 'robustness'): body.pop(k)
    body.update(opening=[{'code': 'SYNTH_A', 'quantity': 100.0}], ledger_fees_confirmed=True, opening_positions_complete=True)
    result = ledger_performance(LedgerPerformanceRequest.model_validate(body))
    assert result['status'] == 'MISSING_INPUTS'
    assert 'ACTIVE_CORRECTION_REQUIRES_GOVERNED_RECONCILIATION' in result['missing']
    assert db.read_bytes() == before
    assert list(tmp_path.iterdir()) == [db]


def test_rdp_legacy_manifest_cannot_autoarchive(tmp_path, monkeypatch):
    import research_data_plane as rdp
    import research_analytics_adapters as adapters
    from research_analytics_contract import RdpRequest
    monkeypatch.setattr(rdp, 'resolve_root', lambda *args: tmp_path)
    manifest = rdp._manifest_path(tmp_path)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"legacy":"unarchived"}')
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = adapters.rdp_inputs(RdpRequest(codes=['000001'], date_from='2025-01-02', date_to='2025-01-03'))
    assert result['status'] == 'MISSING_INPUTS'
    assert result['missing'][0]['reason'] == 'RDP_ARCHIVED_SNAPSHOT_REQUIRED'
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize('kind', ['absent', 'missing_tables', 'malformed_schema', 'duplicate_ids'])
def test_unavailable_or_malformed_ledger_never_authoritative_empty(tmp_path, monkeypatch, kind):
    import trade_ledger_service as ledger
    import account_event_store
    db = tmp_path / 'bad.sqlite3'
    if kind != 'absent':
        conn = sqlite3.connect(db)
        conn.execute(account_event_store._CREATE_TABLE_SQL)
        if kind == 'malformed_schema':
            conn.execute('CREATE TABLE trade_records (trade_id TEXT PRIMARY KEY, code TEXT)')
        if kind == 'duplicate_ids':
            conn.execute('CREATE TABLE trade_records (trade_id TEXT,code TEXT,operation TEXT,execution_status TEXT,actual_price REAL,actual_quantity REAL,executed_at TEXT,fee REAL,other_cost REAL,created_at TEXT,voided_at TEXT)')
        conn.commit(); conn.close()
    monkeypatch.setattr(ledger, 'resolve_db_path', lambda: db)
    body = compact()
    for k in ('strategy', 'initial_cash', 'benchmark', 'terminal_liquidation', 'robustness'): body.pop(k)
    body.update(opening=[{'code': 'SYNTH_A', 'quantity': 100.0}], ledger_fees_confirmed=True, opening_positions_complete=True)
    report = ledger_performance(LedgerPerformanceRequest.model_validate(body))
    assert report['status'] == 'MISSING_INPUTS'
    assert report['missing'] == ['AUTHORITATIVE_LEDGER_UNAVAILABLE']
    assert 'authority' not in report


def test_simulation_plan_is_separate_validation_only(monkeypatch):
    import research_analytics_simulation as simulator
    monkeypatch.setattr(simulator, '_simulate', lambda *args: pytest.fail('plan must not execute simulation'))
    result = call('/api/research-analytics/simulation-plan', example_input('simulation'))
    assert result.status_code == 200
    assert result.json()['status'] == 'READY_TO_CALCULATE'
    assert result.json()['maximum_runs'] == 12
    assert result.json()['formal_writes'] == 0


def test_browser_parity_diagnostics_identify_all_exact_mismatch_paths():
    expected = {'currency': 'CNY', 'rows': [{'cash': 1.0, 'count': 2}], 'identity': 'original'}
    actual = {'currency': 'USD', 'rows': [{'cash': 1.01, 'count': 3}], 'extra': True}
    assert _result_difference_paths(actual, expected, 'cost-comparison.result') == [
        'cost-comparison.result.extra (missing/extra)', 'cost-comparison.result.identity (missing/extra)',
        'cost-comparison.result.currency', 'cost-comparison.result.rows[0].cash',
        'cost-comparison.result.rows[0].count',
    ]
    with pytest.raises(AssertionError, match=r'cost-comparison.result.rows\[0\].cash'):
        _assert_browser_fixture_result('cost-comparison', actual, expected)


@pytest.mark.parametrize('toward', [math.inf, -math.inf])
def test_browser_parity_allows_only_one_mwr_ulp_without_mutation(toward):
    expected = _browser_fixture()['performance']['result']
    actual = copy.deepcopy(expected)
    actual['mwr']['period_return'] = math.nextafter(expected['mwr']['period_return'], toward)
    before = copy.deepcopy(actual)
    _assert_browser_fixture_result('performance', actual, expected)
    assert actual == before
    # A ledger-derived response with this same path has no new exemption.
    with pytest.raises(AssertionError):
        _assert_browser_fixture_result('ledger-performance', actual, expected)


@pytest.mark.parametrize('change', ['two_ulps', 'basis_point', 'nan', 'infinity', 'boolean',
                                  'valuation_ulp', 'annual_rate_ulp', 'twr_ulp', 'root_contract',
                                  'currency', 'fingerprint', 'status', 'date', 'curve_count'])
def test_browser_parity_rejects_mwr_or_adjacent_contract_changes(change):
    expected = _browser_fixture()['performance']['result']
    actual = copy.deepcopy(expected)
    mwr = actual['mwr']
    if change == 'two_ulps': mwr['period_return'] = math.nextafter(math.nextafter(mwr['period_return'], math.inf), math.inf)
    elif change == 'basis_point': mwr['period_return'] += 0.0001
    elif change == 'nan': mwr['period_return'] = math.nan
    elif change == 'infinity': mwr['period_return'] = math.inf
    elif change == 'boolean': mwr['period_return'] = True
    elif change == 'valuation_ulp': actual['curve'][0]['value'] = math.nextafter(actual['curve'][0]['value'], math.inf)
    elif change == 'annual_rate_ulp': mwr['annual_rate'] = math.nextafter(mwr['annual_rate'], math.inf)
    elif change == 'twr_ulp': actual['twr'] = math.nextafter(actual['twr'], math.inf)
    elif change == 'root_contract': mwr['root_contract'] = 'MULTIPLE_ROOTS'
    elif change == 'currency': actual['currency'] = 'USD'
    elif change == 'fingerprint': actual['input_fingerprint'] = '0' * 64
    elif change == 'status': mwr['status'] = 'UNDEFINED'
    elif change == 'date': actual['curve'][0]['date'] = '2024-01-03'
    elif change == 'curve_count': actual['curve'].pop()
    with pytest.raises(AssertionError):
        _assert_browser_fixture_result('performance', actual, expected)
