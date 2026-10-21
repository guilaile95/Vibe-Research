"""Offline native-boundary, persistence and history regression evidence."""
import asyncio
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
import company_research as service
from test_company_research import bundle, good_stream
from offline_testclient import offline_network

@pytest.fixture
def run_async(request):
    # Initialize only an empty loop before the unconditional network guard.
    # Windows creates a loopback self-pipe here; application work starts below it.
    with asyncio.Runner() as runner:
        runner.get_loop()
        request.getfixturevalue('offline_network')
        yield runner.run

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, run_async):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))

async def run(b, cfg=None, stream=good_stream):
    return [event async for event in service.generate(b, cfg or {'model':'fixture'}, threading.Event(), stream=stream)]

class Frame:
    empty = False
    def __init__(self, rows): self.rows = rows
    def to_dict(self, *args): return self.rows


def native(monkeypatch, wrong=None, empty=False):
    import public_research_extended_service as archive
    monkeypatch.setattr(archive, 'archive_company_plan', lambda *args: [])
    summary = {'报告期':'2026-06-30','营业总收入':'100亿','净利润':'10亿'}
    if wrong == 'financials': summary['股票代码']='000001'
    frame = SimpleNamespace(empty=True) if empty else Frame([summary])
    ak = SimpleNamespace(stock_financial_abstract_ths=lambda **kw: frame)
    for name in ('stock_financial_benefit_new_ths','stock_financial_debt_new_ths','stock_financial_cash_new_ths'):
        setattr(ak,name,lambda **kw:SimpleNamespace(empty=True))
    monkeypatch.setattr(service.astock, '_akshare', lambda:ak)
    announcement = {'notice_date':'2026-10-19 00:00:00','title':'Synthetic filing','art_code':'synthetic'}
    if wrong == 'announcements': announcement['codes']=[{'stock_code':'000001'}]
    monkeypatch.setattr(service.astock, '_em_session', lambda *args:SimpleNamespace(get=lambda *a,**kw:SimpleNamespace(status_code=200,json=lambda:{'data':{'list':[] if empty else [announcement]}})))
    lockup = {'FREE_DATE':'2026-11-01','FREE_SHARES':100}
    if wrong == 'lockup': lockup['SECURITY_CODE']='000001'
    monkeypatch.setattr(service.astock,'eastmoney_datacenter',lambda *a,**kw:[] if empty else [lockup])
    monkeypatch.setattr(service.astock,'individual_info',lambda code:{'股票代码':code})
    monkeypatch.setattr(service.astock,'full_valuation',lambda code:{'code':code})
    monkeypatch.setattr(service.astock,'tencent_quote',lambda codes:{c:{'code':c} for c in codes})


def test_real_native_adapters_to_frozen_context(monkeypatch):
    native(monkeypatch)
    b=service.capture('A','600519')
    saved=service.read_bundle(b['bundle_id'])
    rows={r['evidence_id']:r for r in saved['sources']}
    for key in ('financials','announcements','lockup'):
        assert rows[key]['status']=='AVAILABLE'
        assert rows[key]['payload']['identity_basis']=='ADAPTER_REQUEST_CONTRACT_NOT_PROVIDER_IDENTITY'
        assert rows[key]['source_as_of'] is None  # reporting period is not disclosure time
    context=json.loads(service.stage_messages('risk',saved,[])[1]['content'])
    assert all(row['payload']['payload'] for row in context['SOURCE_DATA'])
    assert rows['financials']['payload']['payload']['revenue']=='100亿'

@pytest.mark.parametrize('source',['financials','announcements','lockup'])
def test_provider_wrong_identity_is_not_hidden_by_mapping(monkeypatch,source):
    native(monkeypatch,wrong=source)
    rows={r['evidence_id']:r for r in service.capture('A','600519')['sources']}
    assert rows[source]['status']=='ERROR'


def test_native_empty_is_missing(monkeypatch):
    native(monkeypatch,empty=True)
    rows={r['evidence_id']:r for r in service.capture('A','600519')['sources']}
    assert all(rows[k]['status']=='MISSING' and rows[k]['payload'] is None for k in ('financials','announcements','lockup'))

@pytest.mark.parametrize('provider',[None,'','  ','api','custom-api'])
def test_metadata_normalized_before_run_and_readable(provider, run_async):
    cfg={'model':'fixture'}
    if provider is not None: cfg['provider']=provider
    result=run_async(run(bundle(),cfg))[-1]['record']
    assert result['model']['provider']==(provider if provider and provider.strip() else 'api')
    assert service.list_runs()==[result]

@pytest.mark.parametrize('cfg',[{'provider':9,'model':'m'},{'provider':'x'*201,'model':'m'},{'provider':'cli-tool','model':'m'},{'provider':'a\nb','model':'m'},{'model':' '},{'model':'secret','apiKey':'secret'}])
def test_bad_metadata_creates_no_run(cfg, run_async):
    b=bundle()
    with pytest.raises(ValueError):run_async(run(b,cfg))
    assert service.list_runs()==[]


def test_completion_commit_ack_loss_reads_back_without_fallback(monkeypatch, run_async):
    original=service._terminal
    calls=[]
    def lost(*args,**kwargs):
        calls.append(args[2]);original(*args,**kwargs)
        raise sqlite3.OperationalError('synthetic acknowledgement lost')
    monkeypatch.setattr(service,'_terminal',lost)
    events=run_async(run(bundle()))
    assert events[-1]['type']=='done'
    assert calls==['COMPLETED']
    assert service.list_runs()==[events[-1]['record']]


def test_completion_write_failure_clean_failed_record(monkeypatch, run_async):
    original=service._terminal
    def fail(*args,**kwargs):
        if args[2]=='COMPLETED':raise sqlite3.OperationalError('synthetic failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(service,'_terminal',fail)
    assert run_async(run(bundle()))[-1]['type']=='error'
    result=service.list_runs()[0]
    assert result['status']=='FAILED' and result['stages']==[] and 'result_sha256' not in result


def test_both_writes_fail_no_fake_completion(monkeypatch, run_async):
    monkeypatch.setattr(service,'_terminal',lambda *a,**k:(_ for _ in ()).throw(sqlite3.OperationalError('synthetic failure')))
    with pytest.raises(sqlite3.OperationalError):run_async(run(bundle()))
    assert service.list_runs()[0]['status']=='RUNNING'


def test_real_sqlite_contention_readback(run_async):
    b=bundle(); locked=threading.Event(); release=threading.Event(); worker=None
    def lock():
        with sqlite3.connect(service.db_path(),timeout=10) as conn:
            conn.execute('BEGIN IMMEDIATE');locked.set();release.wait(5.3)
    async def generate():
        nonlocal worker
        events=[]
        async for event in service.generate(b,{'model':'fixture'},threading.Event(),stream=good_stream):
            events.append(event)
            if event.get('type')=='stage_done' and event['stage']=='report':
                worker=threading.Thread(target=lock);worker.start();assert locked.wait(2)
        return events
    try: events=run_async(generate())
    finally:
        release.set()
        if worker:worker.join()
    assert events[-1]['type']=='error'
    saved=service.list_runs()[0]
    assert saved['status']=='FAILED' and 'result_sha256' not in saved


def seed(b, count, status='FAILED'):
    """Persist schema-valid fixture records without calling a model."""
    import uuid
    result=[]
    with service._connect(True) as conn:
        for _ in range(count):
            run_id=uuid.uuid4().hex;owner=uuid.uuid4().hex
            record={'schema_version':service.SCHEMA,'run_id':run_id,'bundle_id':b['bundle_id'],'bundle_sha256':b['bundle_sha256'],'subject':b['subject'],'status':status,'started_at':service.now(),'finished_at':service.now(),'model':{'provider':'api','name':'fixture'},'classification':'NON_AUTHORITATIVE_AI_DRAFT','stages':[],'completed_stage_count':0,'numeric_claim_verification':'NOT_EVALUATED'}
            service.validate_record(record,{'id':run_id,'bundle_id':b['bundle_id'],'owner':owner,'status':status},b)
            conn.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(run_id,b['bundle_id'],owner,status,service.canonical(record)))
            result.append(record)
    return result


def test_subject_pages_insert_stability_exact_read_and_corrupt_diagnostics():
    a=bundle(); originals=seed(a,53)
    other=service.capture('US','AAPL',reader_plan=[('facts',service.STAGES[:-1],'synthetic',lambda:{'value':1})])
    seed(other,60)
    first=service.list_run_page('A','600519',limit=20)
    assert first['records']==list(reversed(originals[-20:]))
    seed(a,5)
    second=service.list_run_page('A','600519',cursor=first['next_cursor'],limit=20)
    third=service.list_run_page('A','600519',cursor=second['next_cursor'],limit=20)
    assert first['records']+second['records']+third['records']==list(reversed(originals))
    assert third['next_cursor'] is None
    assert service.read_run(originals[0]['run_id'],'A','600519')==originals[0]
    with pytest.raises(ValueError):service.read_run(originals[0]['run_id'],'US','AAPL')
    with pytest.raises(ValueError):service.list_run_page('US','AAPL',cursor=first['next_cursor'])
    with service._connect(True) as conn:
        damaged=dict(originals[-1]);damaged['model']={'provider':'','name':'fixture'}
        conn.execute('UPDATE runs SET payload=? WHERE id=?',(service.canonical(damaged),damaged['run_id']))
    page=service.list_run_page('A','600519')
    assert page['diagnostics']==[{'run_id':damaged['run_id'],'status':'CORRUPTED_OR_UNSUPPORTED'}]
    assert service.list_run_page('US','AAPL')['diagnostics']==[]
    with pytest.raises(ValueError):service.read_run(damaged['run_id'],'A','600519')
    with service._snapshot() as conn:
        assert conn.execute('SELECT payload FROM runs WHERE id=?',(damaged['run_id'],)).fetchone()[0]==service.canonical(damaged)


def test_registered_native_capture_generate_and_history(monkeypatch):
    from fastapi.testclient import TestClient
    import app
    native(monkeypatch)
    seen=[]
    async def model(cfg,messages,**kwargs):
        context=json.loads(messages[-1]['content']);seen.append(context)
        yield {'type':'delta','text':json.dumps({'stage':context['stage'],'summary':'Synthetic report','evidence_ids':[r['evidence_id'] for r in context['SOURCE_DATA'] if r['status']=='AVAILABLE'],'gaps':['Synthetic unverified data']})}
        yield {'type':'done'}
    monkeypatch.setattr(service.chat,'stream_api_messages',model)
    monkeypatch.setattr(app,'_require_llm_ready',lambda _:None)
    client=TestClient(app.app)
    response=client.post('/api/company-research/capture',json={'market':'A','symbol':'600519','confirm_public_fetch':True})
    assert response.status_code==200
    b=response.json()['data']
    body={'market':'A','symbol':'600519','bundle_id':b['bundle_id'],'expected_bundle_sha256':b['bundle_sha256'],'confirm_model_calls':True,'llm':{'model':'fixture','baseURL':'https://fixture.example/v1'}}
    response=client.post('/api/company-research/generate',json=body)
    record=json.loads(response.text.splitlines()[-1])['record']
    assert record['model']['provider']=='api'
    risk=next(c for c in seen if c['stage']=='risk')
    assert {r['evidence_id'] for r in risk['SOURCE_DATA'] if r['payload']}=={'financials','announcements','lockup'}
    page=client.get('/api/company-research/history?market=A&symbol=600519').json()['data']
    assert page['records']==[record]
    assert client.get('/api/company-research/runs/'+record['run_id']+'?market=A&symbol=600519').json()['data']==record
    assert client.get('/api/company-research/runs/'+record['run_id']+'?market=US&symbol=AAPL').status_code==409
    assert client.post('/api/company-research/generate',json={**body,'llm':{**body['llm'],'provider':'x'*201}}).status_code==422
    assert len(service.list_runs())==1


def test_cancel_before_completed_transition_is_readable(run_async):
    stop=threading.Event()
    async def generate():
        async for event in service.generate(bundle(),{'model':'fixture'},stop,stream=good_stream):
            if event.get('type')=='stage_done' and event['stage']=='report': stop.set()
    with pytest.raises(asyncio.CancelledError):run_async(generate())
    saved=service.list_runs()[0]
    assert saved['status']=='CANCELLED' and saved['completed_stage_count']==6 and saved['stages']==[]
    assert 'result_sha256' not in saved


def test_terminal_validation_before_write_and_late_owner_rejected():
    b=bundle();saved=seed(b,1)[0]
    with service._snapshot() as conn: row=dict(conn.execute('SELECT * FROM runs').fetchone())
    with pytest.raises(ValueError):service._terminal(saved['run_id'],row['owner'],'FAILED',{**saved,'result_sha256':'a'*64})
    with pytest.raises(ValueError):service._terminal(saved['run_id'],'a'*32,'FAILED',saved)
    assert service.read_run(saved['run_id'],'A','600519')==saved


def test_malformed_native_shapes_do_not_become_available(monkeypatch):
    native(monkeypatch)
    monkeypatch.setattr(service.astock,'financials',lambda *a,**kw:{'history':[{}],'data_quality':{}})
    monkeypatch.setattr(service.astock,'announcements',lambda *a,**kw:[{'title':'missing date'}])
    monkeypatch.setattr(service.astock,'lockup_expiry',lambda *a,**kw:{'history':'bad','upcoming':[]})
    rows={r['evidence_id']:r for r in service.capture('A','600519')['sources']}
    assert all(rows[k]['status']=='ERROR' for k in ('financials','announcements','lockup'))


def test_readonly_diagnostics_preserve_legacy_bytes_and_hashes():
    b=bundle();records=seed(b,3)
    with service._connect(True) as conn:
        blank=dict(records[0]);blank['model']={'provider':'','name':'fixture'}
        extra={**records[1],'result_sha256':'a'*64}
        for value in (blank,extra):conn.execute('UPDATE runs SET payload=? WHERE id=?',(service.canonical(value),value['run_id']))
    before=service.db_path().read_bytes()
    assert service.diagnose_runs()=={'schema_version':'company-research-diagnostics.v1','counts':{'VALID':1,'MODEL_METADATA_INVALID':1,'TERMINAL_SCHEMA_INVALID':1,'BUNDLE_INVALID_OR_UNAVAILABLE':0,'OTHER_INVALID_OR_UNSUPPORTED':0},'repair_performed':False}
    assert service.db_path().read_bytes()==before


def test_old_completed_report_and_original_evidence_survive_failed_history_pages(run_async):
    b=bundle();completed=run_async(run(b))[-1]['record']
    seed(b,51)
    first=service.list_run_page('A','600519')
    assert completed not in first['records'] and first['next_cursor']
    older=service.list_run_page('A','600519',cursor=first['next_cursor'])
    assert completed in older['records']
    reopened=service.read_run(completed['run_id'],'A','600519')
    assert service.read_bundle(reopened['bundle_id'])==b
    assert reopened['result_sha256']==completed['result_sha256']


@pytest.mark.parametrize('variant',['invalid_market','invalid_symbol','noncanonical_symbol','duplicate_subject','duplicate_symbol','oversized','malformed_json','nonobject_subject'])
def test_invalid_or_ambiguous_archive_subject_is_unassigned_not_invisible(variant):
    b=bundle();record=seed(b,1)[0]
    damaged=json.loads(service.canonical(b))
    if variant=='invalid_market': damaged['subject']['market']='INVALID'
    if variant=='invalid_symbol': damaged['subject']['symbol']='bad'
    if variant=='noncanonical_symbol': damaged['subject']['symbol']=' 600519 '
    if variant=='nonobject_subject': damaged['subject']=[]
    raw=service.canonical(damaged)
    if variant=='duplicate_subject': raw=raw[:-1]+',"subject":{"market":"US","symbol":"AAPL"}}'
    if variant=='duplicate_symbol': raw=raw.replace('"symbol":"600519"','"symbol":"600519","symbol":"000001"')
    if variant=='oversized': raw=raw[:-1]+',"extra":"'+'x'*(service.MAX_BUNDLE_BYTES+100)+'"}'
    if variant=='malformed_json': raw='{bad'
    with service._connect(True) as conn:
        conn.execute('UPDATE bundles SET payload=? WHERE id=?',(raw,b['bundle_id']))
    before=service.db_path().read_bytes()
    for market,symbol in [('A','600519'),('A','000001'),('US','AAPL')]:
        page=service.list_run_page(market,symbol)
        assert page=={'records':[],'diagnostics':[],'unassigned_corrupt_count':1,'next_cursor':None}
    with pytest.raises(ValueError):service.read_run(record['run_id'],'A','600519')
    assert service.db_path().read_bytes()==before


def test_async_audit_runner_reuses_initialized_loop_under_guard(run_async, monkeypatch):
    import socket
    def unexpected_loop(*args, **kwargs):
        raise AssertionError('unexpected event loop initialization')
    monkeypatch.setattr(asyncio, 'new_event_loop', unexpected_loop)
    monkeypatch.setattr(asyncio.get_event_loop_policy(), 'new_event_loop', unexpected_loop)
    async def guarded():
        for address in [('203.0.113.1', 443), ('127.0.0.1', 12345), ('::1', 12345)]:
            with pytest.raises(AssertionError, match='network prohibited'):
                socket.create_connection(address)
        return 'guarded'
    assert run_async(guarded()) == 'guarded'
    assert run_async(guarded()) == 'guarded'
