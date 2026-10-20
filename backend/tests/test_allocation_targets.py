"""Offline private-target contract; no provider, model or real account data."""
from datetime import datetime, timezone, timedelta
import copy
import socket
import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
import allocation_targets as svc
import allocation_targets_router

@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path)); monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)
    def deny(*a, **kw): raise AssertionError('Network prohibited')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)

def body(**kw):
    return dict(expected_version=0, effective_date='2026-10-19', market='CN', currency='CNY', basis='CONFIRMED_ACCOUNT_ASSETS', coverage='FULL', targets={'600000': 60, 'CASH': 40}, **kw)

def account(total=100, cash=40):
    def fact(value): return {'current_fact': {'value': value, 'authority_state': 'CANONICAL', 'confirmation_id': 'synthetic'}}
    return {'account_total_assets': fact(total), 'cash': fact(cash)}

def compare(**kw):
    args = dict(records=[{'version': 1, 'input': body()}], snapshot={'holdings':[{'code':'600000','shares':6}]}, account=account(), quotes={'600000': {'price':10, 'currency':'CNY'}}, today='2026-10-19')
    args.update(kw); return svc.compare(**args)

@pytest.mark.parametrize('targets,coverage', [({'600000':33.33,'600001':33.33,'CASH':33.34},'FULL'), ({'600000':0},'PARTIAL'), ({'600000':60},'PARTIAL')])
def test_valid_weights(targets,coverage):
    data=body(); data.update(targets=targets,coverage=coverage); svc.TargetInput.model_validate(data)

@pytest.mark.parametrize('targets,coverage', [({'CASH':99.99},'FULL'), ({'CASH':100.01},'PARTIAL'), ({'CASH':-1},'PARTIAL'), ({'CASH':True},'PARTIAL'), ({'CASH':float('nan')},'PARTIAL'), ({'CASH':33.333},'PARTIAL'), ({'AAPL':30},'PARTIAL')])
def test_invalid_weights(targets,coverage):
    data=body(); data.update(targets=targets,coverage=coverage)
    with pytest.raises(ValidationError): svc.TargetInput.model_validate(data)

def test_empty_is_not_configured_and_read_does_not_create_store():
    assert svc.current()['status']=='NOT_CONFIGURED'
    assert not svc.store.facts.resolve_db_path().exists()

def test_versions_conflict_effective_dates_and_readonly():
    svc.save(svc.TargetInput.model_validate(body()))
    before={p.name:p.read_bytes() for p in svc.store.facts.resolve_db_path().parent.iterdir() if p.is_file()}
    records=svc.history()
    after={p.name:p.read_bytes() for p in svc.store.facts.resolve_db_path().parent.iterdir() if p.is_file()}
    assert before==after
    with pytest.raises(LookupError): svc.save(svc.TargetInput.model_validate(body()))
    future=body(); future.update(expected_version=1,effective_date='2030-01-01')
    svc.save(svc.TargetInput.model_validate(future))
    result=compare(records=svc.history()); assert result['active_version']==1 and result['latest_version']==2
    assert compare(records=svc.history(),today='2026-01-01')['status']=='NOT_EFFECTIVE'

def test_same_basis_drift_and_partial_does_not_imply_zero():
    result=compare(); assert result['status']=='COMPARABLE'
    assert all(row['drift_pp']==0 for row in result['rows'])
    records=[{'version':1,'input':{**body(),'coverage':'PARTIAL','targets':{'600000':50}}}]
    result=compare(records=records)
    cash=next(x for x in result['rows'] if x['key']=='CASH')
    assert cash['actual_pct']==40 and cash['target_pct'] is None and cash['drift_pp'] is None
    assert result['coverage']['unknown_industry_count']==1

@pytest.mark.parametrize('changes,reason', [({'quotes':{}},'MISSING_OR_STALE_QUOTE:600000'), ({'account':account(120)},'ACCOUNT_ASSET_RECONCILIATION_GAP'), ({'authority':'LEGACY'},'POSITION_AUTHORITY_NOT_CANONICAL'), ({'account':account(0)},'ACCOUNT_CASH_DENOMINATOR_NOT_CONFIRMED'), ({'snapshot':{'holdings':[{'code':'600000','shares':-1}]}},'UNSUPPORTED_HOLDING_OR_CURRENCY'), ({'quotes':{'600000':{'price':10,'currency':'USD'}}},'MISSING_OR_STALE_QUOTE:600000')])
def test_incomplete_no_renormalization(changes,reason):
    result=compare(**changes); assert reason in result['reasons']
    assert all(x['actual_pct'] is None and x['drift_pp'] is None for x in result['rows'])

def test_cash_only_zero_holding_and_missing_confirmation():
    result=compare(snapshot={'holdings':[]},account=account(100,100),quotes={})
    assert result['status']=='COMPARABLE'
    result=compare(snapshot={'holdings':[{'code':'600000','shares':0}]},account=account(100,100),quotes={})
    assert result['status']=='COMPARABLE'
    bad=account(); bad['cash']['current_fact']['confirmation_id']='other'
    assert compare(account=bad)['status']=='UNAVAILABLE'

def test_real_receipts_only_cached(monkeypatch):
    block={'symbol':'600000','fixture':False,'archive_stale':False,'status':'normal','rows':[{'symbol':'600000','source_stale':False,'quote_age_seconds_at_capture':0,'quote':{'symbol':'600000','currency':'CNY','price':10,'source_time':datetime.now(timezone.utc).isoformat()}}]}
    monkeypatch.setattr(svc,'load_blocks',lambda req:([block],None))
    assert svc.cached_quotes(['600000'],'2026-10-19')[0]
    block['rows'][0]['quote']['source_time']=(datetime.now(timezone.utc)-timedelta(seconds=301)).isoformat(); assert not svc.cached_quotes(['600000'],'2026-10-19')[0]
    block['rows'][0]['quote']['source_time']=datetime.now(timezone.utc).isoformat()
    block['fixture']=True; assert not svc.cached_quotes(['600000'],'2026-10-19')[0]
    block['fixture']=False; block['archive_stale']=True; assert not svc.cached_quotes(['600000'],'2026-10-19')[0]
    assert svc.cached_quotes([str(x) for x in range(12)],'2026-10-19')[1]==['QUOTE_ARCHIVE_BUDGET_EXCEEDED']

def test_routes_conflict_and_sanitized(monkeypatch):
    app=FastAPI(); app.include_router(allocation_targets_router.router); client=TestClient(app)
    assert client.get('/api/portfolio/allocation-targets').json()['data']['status']=='NOT_CONFIGURED'
    assert client.put('/api/portfolio/allocation-targets',json=body()).status_code==200
    assert client.put('/api/portfolio/allocation-targets',json=body()).status_code==409
    monkeypatch.setattr(svc,'current',lambda: (_ for _ in ()).throw(RuntimeError('private')))
    assert 'private' not in client.get('/api/portfolio/allocation-targets').text

@pytest.mark.parametrize('value', [None, [], 'bad'])
def test_wrong_target_container(value):
    data=body(); data['targets']=value
    with pytest.raises(ValidationError): svc.TargetInput.model_validate(data)

def test_corrupt_private_history_fails_closed():
    svc.save(svc.TargetInput.model_validate(body()))
    with svc.store.write() as conn:
        conn.execute("UPDATE allocation_targets SET payload=?", ('{"version":1,"version":2}',))
    with pytest.raises(svc.store.StoreError): svc.history()

def test_current_uses_no_live_quote_reader_and_detects_mutation(monkeypatch):
    svc.save(svc.TargetInput.model_validate(body()))
    monkeypatch.setattr(svc.positions,'get_holding_authority_state',lambda:'CANONICAL')
    monkeypatch.setattr(svc.positions,'read_current_holdings_snapshot',lambda:{'holdings':[{'code':'600000','shares':6}]})
    monkeypatch.setattr(svc.accounts,'get_account_reality',lambda:account())
    monkeypatch.setattr(svc,'cached_quotes',lambda codes,today:({'600000':{'price':10,'currency':'CNY'}},[]))
    monkeypatch.setattr(svc.positions,'read_portfolio_authority',lambda **kw:pytest.fail('live reader forbidden'))
    assert svc.current()['status']=='COMPARABLE'
    calls=iter([{'holdings':[{'code':'600000','shares':6}]},{'holdings':[]}])
    monkeypatch.setattr(svc.positions,'read_current_holdings_snapshot',lambda:next(calls))
    result=svc.current(); assert 'ACTUAL_CHANGED_DURING_READ' in result['reasons']
    assert all(row['actual_pct'] is None for row in result['rows'])

def test_latest_effective_version_wins_over_later_backdated_version():
    a={'version':1,'input':body()}
    b=copy.deepcopy(a); b['version']=2; b['input']['effective_date']='2026-10-01'
    c=copy.deepcopy(a); c['version']=3
    assert compare(records=[a,b])['active_version']==1
    assert compare(records=[a,b,c])['active_version']==3

def test_duplicate_holdings_and_zero_price_are_unknown():
    assert compare(snapshot={'holdings':[{'code':'600000','shares':3}]*2})['status']=='UNAVAILABLE'
    assert compare(quotes={'600000':{'price':0,'currency':'CNY'}})['status']=='UNAVAILABLE'

def test_account_currency_declaration_cannot_be_ignored():
    a=account(); a['currency']='USD'
    result=compare(account=a)
    assert 'UNSUPPORTED_ACCOUNT_CURRENCY_NO_FX' in result['reasons']
    assert all(row['actual_pct'] is None for row in result['rows'])
