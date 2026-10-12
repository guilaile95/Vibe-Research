import asyncio
import copy
import hashlib
import json
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


def test_browser_fixture_exact_current_source_parity():
    from pathlib import Path
    from research_analytics_contract import SimulationRequest, ScenarioRequest, PerformanceRequest
    from research_analytics import performance, scenario
    from research_analytics_simulation import simulate
    from research_cost_comparison import CostComparisonRequest, compare_costs
    fixture = json.loads((Path(__file__).parents[2] / 'frontend/tests/e2e/research-analytics.fixture.json').read_text(encoding="utf-8"))
    for mode, model, fn in [('simulation', SimulationRequest, simulate), ('scenario', ScenarioRequest, scenario), ('performance', PerformanceRequest, performance), ('ledger-performance', LedgerPerformanceRequest, ledger_performance), ('cost-comparison', CostComparisonRequest, compare_costs)]:
        assert fn(model.model_validate(fixture[mode]['input'])) == fixture[mode]['result']


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
