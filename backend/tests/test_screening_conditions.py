import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import research_data_plane as rdp
import screening_conditions as s
import observation_workflow_store as store

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('VIBE_RESEARCH_FACT_DB', str(tmp_path / 'facts.sqlite3'))
    root = tmp_path / 'rdp'
    source = tmp_path / 'daily.csv'
    source.write_text('code,trade_date,open,high,low,close,volume\n000001,2026-08-20,10,12,9,11,100\n000001,2026-08-21,11,13,10,12,100\n600519,2026-08-20,10,12,9,11,100\n')
    rdp.import_csv(source, root=root)
    return root


def test_saved_workflow_and_read_only_comparison(setup):
    card = s.save_card('价格条件', [dict(metric='latest_close', operator='gte', value=11)])
    a = s.execute(card['id'], '2026-08-20', root=setup)
    b = s.execute(card['id'], '2026-08-21', root=setup)
    assert a['counts'] == dict(PASS=2, FAIL=0, UNKNOWN=0)
    assert b['counts'] == dict(PASS=1, FAIL=0, UNKNOWN=1)
    diff = s.compare(a['id'], b['id'])
    assert diff['data_changed'] and not diff['rule_changed']
    assert diff['changes'][-1]['transition'] == 'EXITED'
    assert 'COVERAGE_MISSING_OR_STALE' in diff['changes'][-1]['reasons']
    assert s.get('screening_runs', a['id']) == a
    assert len(s.catalog()['runs']) == 2
    newer = s.save_card('价格条件', [dict(metric='latest_close', operator='gte', value=13)])
    assert newer['version'] == 2
    c = s.execute(newer['id'], '2026-08-21', root=setup)
    diff = s.compare(b['id'], c['id'])
    assert diff['rule_changed'] and not diff['data_changed']
    assert diff['changes'][0]['transition'] == 'EXITED'


def test_null_and_stale_not_failure():
    rule = [dict(metric='return_20d', operator='gte', value=0)]
    for row in [dict(code='000001', return_20d=None), dict(code='000001', return_20d=1, status='stale')]:
        assert s.explain(row, rule)['status'] == 'UNKNOWN'
    assert s.explain(dict(code='000001', return_20d=-0.1), rule)['status'] == 'FAIL'


def test_unsafe_filters_rejected(setup):
    for filters in [[dict(metric='eval(x)', operator='gte', value=1)], [dict(metric='latest_close', operator='gte', value=float('nan'))], []]:
        with pytest.raises((ValueError, rdp.ResearchDataPlaneValidationError)): s.save_card('bad', filters)
    assert s.catalog()['cards'] == []


def test_tampered_saved_rows_fail_closed(setup):
    card = s.save_card('card', [dict(metric='latest_close', operator='gte', value=1)])
    run = s.execute(card['id'], root=setup)
    run['rows'][0]['conditions'][0]['status'] = 'FAIL'
    run['integrity'] = s.digest({k:v for k,v in run.items() if k != 'integrity'})
    with store.write() as conn: conn.execute('UPDATE screening_runs SET payload=?', (store.encode(run),))
    with pytest.raises(store.StoreError): s.catalog()


def test_duplicate_json_and_index_mismatch(setup):
    card = s.save_card('card', [dict(metric='latest_close', operator='gte', value=1)])
    with store.write() as conn: conn.execute('UPDATE screening_cards SET name=?', ('different',))
    with pytest.raises(store.StoreError): s.catalog()
    with pytest.raises(ValueError, match='Duplicate'): s.strict_json('{"x":1,"x":2}')


def test_truncated_page_does_not_save(setup, monkeypatch):
    card = s.save_card('card', [dict(metric='latest_close', operator='gte', value=1)])
    query = rdp.query_full_market
    def truncated(**kw):
        page = query(**kw); page['rows'] = page['rows'][:1]; page['returned_rows'] = 1; return page
    monkeypatch.setattr(rdp, 'query_full_market', truncated)
    with pytest.raises(ValueError, match='incomplete'): s.execute(card['id'], root=setup)
    assert s.catalog()['runs'] == []


def test_router_errors_sanitized(setup, monkeypatch):
    import screener_router
    app = FastAPI(); app.include_router(screener_router.router)
    client = TestClient(app)
    assert client.post('/api/screener/condition-cards', json={'name':'card', 'filters':[]}).status_code == 422
    monkeypatch.setattr(s, 'catalog', lambda: (_ for _ in ()).throw(RuntimeError('secret /private SQL')))
    response = client.get('/api/screener/condition-cards')
    assert response.status_code == 503 and 'secret' not in response.text

@pytest.mark.parametrize('op', ['gt','gte','lt','lte','eq','neq'])
def test_condition_result_matches_existing_full_market_sql(setup, op):
    rule = dict(metric='latest_close', operator=op, value=11)
    card = s.save_card(op, [rule])
    saved = s.execute(card['id'], '2026-08-20', root=setup)
    existing = rdp.query_full_market(root=setup, as_of='2026-08-20', filters=[rule])
    assert [r['code'] for r in saved['rows'] if r['status'] == 'PASS'] == [r['code'] for r in existing['rows']]
