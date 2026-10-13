"""Real inert provider bytes → accepted archive readers → owned six-stage runtime."""
import asyncio
import json
import threading
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
import app
import company_research as R
import public_research_extended_service as S
import public_research_extended_contract as E
import public_research_contract as C
from public_research_archive import persist_capture
from fact_lake_store import initialize_fact_lake
from extended_public_fixtures import raw, CUTOFF, CAPTURED

@pytest.fixture
def lake(tmp_path,monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR',str(tmp_path/'private'))
    monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(tmp_path/'lake'))
    # Native inputs are independent optional sources; never call providers.
    monkeypatch.setattr(R.astock,'individual_info',lambda code:{'股票代码':code,'行业':'synthetic'})
    monkeypatch.setattr(R.astock,'financials',lambda *a,**k:{'period_end':'2026-06-30'})
    monkeypatch.setattr(R.astock,'full_valuation',lambda code:{'code':code,'price':0})
    monkeypatch.setattr(R.astock,'tencent_quote',lambda codes:{c:{'code':c,'price':0} for c in codes})
    monkeypatch.setattr(R.astock,'announcements',lambda *a,**k:[])
    monkeypatch.setattr(R.astock,'lockup_expiry',lambda *a,**k:{})
    monkeypatch.setattr(R.gstock,'us_hk_stock',lambda symbol:{'code':symbol,'market':'HK' if symbol.isdigit() else 'US','metrics':{'label':'latest only'}})
    monkeypatch.setattr(R.gstock,'hk_cashflow',lambda *a,**k:{})
    return initialize_fact_lake(tmp_path/'lake')

def seed(lake,market,symbol,sources=None,transform=None):
    for source in sources or (E.CN if market=='A' else E.GLOBAL):
        subject=f'{market}:{symbol}@{CUTOFF}';body=raw(source,subject)
        if transform:body=transform(source,body)
        persist_capture(lake,body,source,subject,CAPTURED,fixture=True)

async def model(cfg,messages,*,limits):
    context=json.loads(messages[-1]['content']);available=[x['evidence_id'] for x in context['SOURCE_DATA'] if x['status']=='AVAILABLE']
    assert all(x['payload'].get('point_in_time_claim')=='NONE' for x in context['SOURCE_DATA'] if x['source']=='immutable_public_source_archive' and x['status']=='AVAILABLE')
    yield {'type':'delta','text':json.dumps({'stage':context['stage'],'summary':'Synthetic qualified current-vintage research; raw amount scales unverified.','evidence_ids':available,'gaps':['Current-vintage only, no historical PIT or verified monetary arithmetic']})}
    yield {'type':'done'}

@pytest.mark.parametrize('market,symbol',[('A','600000'),('US','AAPL'),('HK','00700')])
def test_real_archive_bundle_sixstage_restore_and_no_refetch(lake,monkeypatch,market,symbol):
    seed(lake,market,symbol)
    calls=[];original=S.load_blocks
    def count(requests):calls.append(requests);return original(requests)
    monkeypatch.setattr(S,'load_blocks',count)
    b=R.capture(market,symbol,as_of=CUTOFF)
    archive=[x for x in b['sources'] if x['source']=='immutable_public_source_archive']
    assert len(calls)==1 and len(archive)==len(E.CN if market=='A' else E.GLOBAL)
    assert all(x['status']=='AVAILABLE' for x in archive)
    for row in archive:
        v=row['payload'];assert v['source_artifact_hash'].startswith('sha256:') and v['block']['fixture']
        assert v['block']['subject']==f'{market}:{symbol}@{CUTOFF}'
        assert row['source_as_of'] is None # cutoff is not source publication time
    monkeypatch.setattr(S,'load_blocks',lambda *_:pytest.fail('generation must not re-read archives'))
    events=asyncio.run(_collect(b));assert events[-1]['type']=='done'
    record=events[-1]['record'];assert len(record['stages'])==6 and R.list_runs()==[record]
    assert any(x['source']=='immutable_public_source_archive' for x in R.read_bundle(b['bundle_id'])['sources'])

async def _collect(bundle,cancel=None,stream=model):
    return [x async for x in R.generate(bundle,{'provider':'fixture','model':'fixture'},cancel or threading.Event(),stream=stream)]

@pytest.mark.parametrize('market,symbol,variant',[('A','600000',''),('US','AAPL',''),('HK','00700',''),('US','AAPL','failed-quote')])
def test_registered_capture_and_generation_use_real_archived_families(lake,monkeypatch,market,symbol,variant):
    import uuid,itertools
    import public_research_archive as PA
    sequence=itertools.count(1)
    monkeypatch.setattr(uuid,'uuid4',lambda:uuid.UUID(int=next(sequence)))
    class FixedDate(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,10,12,12,0,0,tzinfo=timezone.utc)
    monkeypatch.setattr(PA,'datetime',FixedDate);monkeypatch.setattr(S,'datetime',FixedDate)
    monkeypatch.setattr(R,'now',lambda:'2026-10-12T12:00:00.000000Z')
    seed(lake,market,symbol,transform=(lambda source,body:b'not-a-quote' if source=='global_quote_ref' else body) if variant else None);client=TestClient(app.app)
    response=client.post('/api/company-research/capture',json={'market':market,'symbol':symbol,'as_of':CUTOFF,'confirm_public_fetch':True})
    assert response.status_code==200,response.text
    b=response.json()['data'];monkeypatch.setattr(app,'_require_llm_ready',lambda *_:False);monkeypatch.setattr(R.chat,'stream_api_messages',model)
    result=client.post('/api/company-research/generate',json={'market':market,'symbol':symbol,'bundle_id':b['bundle_id'],'expected_bundle_sha256':b['bundle_sha256'],'confirm_model_calls':True,'llm':{'provider':'fixture','model':'fixture','baseURL':'https://fixture.example'}})
    assert json.loads(result.text.splitlines()[-1])['type']=='done'
    import os
    from pathlib import Path
    golden={'fixture_only':True,'authority':'registered FastAPI capture/generate with synthetic raw FactLake evidence and offline model stub','subject':{'market':market,'symbol':symbol},'as_of':CUTOFF,'bundle':b,'events':[json.loads(line) for line in result.text.splitlines()]}
    filename=f'{market}-{symbol}'+(f'-{variant}' if variant else '')+'.json'
    committed=Path(__file__).parent/'fixtures'/'company_research'/filename
    if committed.exists():
        assert json.loads(committed.read_text(encoding='utf-8'))==golden
    elif not os.environ.get('COMPANY_RESEARCH_GOLDEN_DIR'):
        pytest.fail(f'Missing committed registered-API golden: {filename}')
    if os.environ.get('COMPANY_RESEARCH_GOLDEN_DIR'):
        from pathlib import Path
        path=Path(os.environ['COMPANY_RESEARCH_GOLDEN_DIR']);path.mkdir(parents=True,exist_ok=True)
        (path/filename).write_text(json.dumps(golden,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def test_missing_family_retains_exact_gap_without_fake_available(lake):
    seed(lake,'US','AAPL',sources=['global_quote_ref'])
    b=R.capture('US','AAPL',as_of=CUTOFF);rows={r['evidence_id']:r for r in b['sources']}
    assert rows['global_quote_ref']['status']=='AVAILABLE'
    assert rows['global_financials_pit']['status']=='ERROR' and rows['yahoo_consensus']['status']=='ERROR'
    record=asyncio.run(_collect(b))[-1]['record']
    assert {'evidence_id':'yahoo_consensus','status':'ERROR'} in record['stages'][2]['source_gaps']

@pytest.mark.parametrize('variant',['wrongidentity','late','fiscal'])
def test_invalid_raw_identity_late_quote_and_fiscal_period_not_qualified(lake,variant):
    def change(source,body):
        if variant=='wrongidentity' and source=='global_quote_ref':return body.replace(b'~AAPL~',b'~MSFT~')
        if variant=='late' and source=='global_quote_ref':return body.replace(b'2026-09-30 16:00:00',b'2026-10-01 16:00:00')
        if variant=='fiscal' and source=='global_financials_pit':
            v=json.loads(body);v['result']['data'][0]['DATE_TYPE_CODE']='008';return C.canonical(v).encode()
        return body
    seed(lake,'US','AAPL',transform=change)
    b=R.capture('US','AAPL',as_of=CUTOFF);rows={r['evidence_id']:r for r in b['sources']}
    key='global_financials_pit' if variant=='fiscal' else 'global_quote_ref'
    assert rows[key]['status']!='AVAILABLE'

@pytest.mark.parametrize('field,value',[('symbol','MSFT'),('provider_fetch_performed',True),('point_in_time_claim','HISTORICAL'),('source_artifact_hash','sha256:'+'f'*64)])
def test_archive_envelope_corruption_never_becomes_available(lake,field,value):
    seed(lake,'US','AAPL');plan=S.archive_company_plan('US','AAPL',CUTOFF);key,stages,provider,reader=plan[0];receipt=reader();receipt[field]=value
    with pytest.raises(ValueError):R.capture('US','AAPL',reader_plan=[(key,stages,provider,lambda:receipt)],as_of=CUTOFF)

def test_cancel_after_archive_model_stage_prevents_later_calls(lake):
    seed(lake,'HK','00700');b=R.capture('HK','00700',as_of=CUTOFF);stop=threading.Event();calls=[]
    async def cancel(*args,**kwargs):
        calls.append(1);stop.set();yield {'type':'delta','text':'partial'}
    with pytest.raises(asyncio.CancelledError):asyncio.run(_collect(b,stop,cancel))
    assert len(calls)==1 and R.list_runs()[0]['stages']==[]

def test_historical_selection_never_substitutes_native_latest_and_empty_blocks_models(lake,monkeypatch):
    for name in ('individual_info','financials','full_valuation','tencent_quote','announcements','lockup_expiry'):
        monkeypatch.setattr(R.astock,name,lambda *a,**k:pytest.fail('historical capture cannot fetch latest native source'))
    b=R.capture('A','600000',as_of=CUTOFF)
    assert not any(x['status']=='AVAILABLE' for x in b['sources'])
    with pytest.raises(ValueError,match='NO_USABLE_EVIDENCE'):asyncio.run(_collect(b))

def test_all_six_critical_families_have_frozen_raw_receipts_and_honest_financial_scale(lake):
    keys=set()
    for market,symbol in [('A','600000'),('US','AAPL')]:
        seed(lake,market,symbol);b=R.capture(market,symbol,as_of=CUTOFF)
        for row in b['sources']:
            if row['source']!='immutable_public_source_archive':continue
            keys.add(row['evidence_id']);assert row['status']=='AVAILABLE'
            if 'financials' in row['evidence_id']:
                for raw_row in row['payload']['block']['rows']:
                    assert raw_row['amount_unit']=='PROVIDER_RAW_SCALE_UNVERIFIED'
                    assert raw_row['amount_scale_to_currency_units'] is None
    assert keys=={'cn_quote_ref','cn_financials_ytd','cn_consensus','global_quote_ref','global_financials_pit','yahoo_consensus'}

def test_returned_archive_cutoff_must_equal_explicit_request(lake):
    seed(lake,'US','AAPL');plan=S.archive_company_plan('US','AAPL',CUTOFF)
    with pytest.raises(ValueError):R.capture('US','AAPL',reader_plan=plan,as_of='2026-09-29')

def test_restored_mixed_cutoff_and_missing_machine_cutoff_fail_even_rehashed(lake):
    seed(lake,'US','AAPL');b=R.capture('US','AAPL',as_of=CUTOFF)
    for missing in (False,True):
        v=json.loads(json.dumps(b))
        if missing:v.pop('archive_cutoff')
        else:
            row=v['sources'][0];row['payload']['as_of']='2026-09-29';row['payload']['block']['requested_as_of']='2026-09-29';row['payload']['block']['subject']='US:AAPL@2026-09-29';row['payload_sha256']=R.digest(row['payload'])
        v.pop('bundle_sha256');v['bundle_sha256']=R.digest(v)
        with pytest.raises(ValueError):R.validate_bundle(v)

def test_rejected_future_quote_value_never_enters_any_model_stage(lake):
    canary='987654321.123456'
    def change(source,body):
        return body.replace(b'~150~',('~'+canary+'~').encode()).replace(b'2026-09-30 16:00:00',b'2026-10-01 04:00:00') if source=='global_quote_ref' else body
    seed(lake,'US','AAPL',transform=change);b=R.capture('US','AAPL',as_of=CUTOFF)
    assert canary in R.canonical(b)
    seen=[]
    async def checked(cfg,messages,**kwargs):
        seen.append(messages);assert canary not in R.canonical(messages)
        async for event in model(cfg,messages,**kwargs):yield event
    # Rejected source metadata is intentionally payload-less in prompt projections.
    async def safe(cfg,messages,**kwargs):
        seen.append(messages);assert canary not in R.canonical(messages)
        c=json.loads(messages[-1]['content']);yield {'type':'delta','text':json.dumps({'stage':c['stage'],'summary':'Bounded research','evidence_ids':[r['evidence_id'] for r in c['SOURCE_DATA'] if r['status']=='AVAILABLE'],'gaps':['Quote unqualified']})};yield {'type':'done'}
    assert asyncio.run(_collect(b,stream=safe))[-1]['type']=='done' and len(seen)==6
