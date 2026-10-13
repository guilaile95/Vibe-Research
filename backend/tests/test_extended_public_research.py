"""Eight source families, synthetic transport→FactLake→registered API, no live calls."""
import asyncio
from datetime import datetime, timezone
import json
import socket
from pathlib import Path
import httpx
import pytest
from fact_lake_store import initialize_fact_lake
import public_research_contract as C
import public_research_extended_contract as E
import public_research_extended_adapters as A
import public_research_extended_service as S
from public_research_archive import persist_capture, replay, collect
from extended_public_fixtures import raw,seed,CUTOFF,CAPTURED

SUBJECTS={s:(('sh000001' if s=='em_market_trend' else '000300' if s=='index_valuation' else 'treasury') if s in E.MARKET else 'A:600000' if s in E.CN else 'US:AAPL')+'@'+CUTOFF for s in E.SPECS}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args,**kwargs): raise AssertionError('network prohibited')
    monkeypatch.setattr(socket,'create_connection',deny);monkeypatch.setattr(socket,'getaddrinfo',deny)


def normalize(source,body=None,subject=None):
    subject=subject or SUBJECTS[source]
    return A.normalize_extended(body or raw(source,subject),source,subject,CAPTURED,now=datetime(2026,10,12,tzinfo=timezone.utc))


@pytest.mark.parametrize('source',list(E.SPECS))
def test_real_producer_shapes_and_existing_archive(tmp_path,source):
    lake=initialize_fact_lake(tmp_path/'lake');subject=SUBJECTS[source]
    calls=[]
    def transport(url,**kw): calls.append((url,kw));return 200,raw(source,subject)
    result=collect(lake,source,subject,transport=transport,fixture=True)
    assert result['status']=='partial',result
    block=replay(lake,lake.get_observation(result['observation_id']))
    assert block['rows'] and block['subject']==subject and block['requested_as_of']==CUTOFF
    assert block['point_in_time_claim']=='NONE' and block['fixture']
    assert calls[0][0]==E.request_spec(source,subject)
    assert calls[0][1]=={'max_bytes':C.MAX_BYTES,'timeout':20,'allow_redirects':False}


def test_trend_exact_sessions_and_no_gap_skipping():
    data=normalize('em_market_trend')['rows'][0]
    assert data['metrics']['return_5d_pct']==pytest.approx((399/394-1)*100)
    assert len(data['windows']['250']['expected_dates'])==251
    assert data['metrics']['ytd_basis_date']=='2025-12-31'
    payload=json.loads(raw('em_market_trend',SUBJECTS['em_market_trend']))
    payload['data']['klines'].pop(-3)
    gap=normalize('em_market_trend',C.canonical(payload).encode())['rows'][0]
    assert gap['metrics']['return_5d_pct'] is None and len(gap['windows']['5']['missing_dates'])==1
    assert gap['metrics']['return_250d_pct'] is None and gap['metrics']['ytd_pct'] is None


def test_signed_rates_and_pe_are_not_returns_or_cheapness():
    bond=normalize('chinabond_yield_curve')['rows'][0]
    assert bond['yield_pct']==-.25 and bond['price'] is None and bond['holding_return'] is None
    val=normalize('index_valuation')['rows'][0]
    assert val['pe_total']==-3 and val['pe_calculation']==14
    assert 'never cheapness' in val['pe_interpretation'] and val['pb'] is None


def test_global_quote_exchange_clock_same_response_and_currency():
    us=normalize('global_quote_ref')['rows'][0]
    hk=normalize('global_quote_ref',subject='HK:00700@'+CUTOFF)['rows'][0]
    assert us['quote']['source_time']=='2026-09-30T20:00:00.000000Z'
    assert hk['quote']['source_time']=='2026-09-30T08:00:00.000000Z'
    assert us['quote']['currency']=='USD' and hk['quote']['currency']=='HKD'
    assert us['benchmark']['currency'] is None and us['same_response'] and not us['session_calendar_confirmed']
    body=raw('global_quote_ref',SUBJECTS['global_quote_ref']).replace(b'~AAPL~',b'~MSFT~')
    with pytest.raises(ValueError):normalize('global_quote_ref',body)
    with pytest.raises(ValueError):normalize('global_quote_ref',body.replace(b'v_usINX',b'v_usOTHER'))


def test_financial_periods_currency_and_notice_filter_not_pit():
    got=normalize('global_financials_pit')
    assert got['counters']['dropped_no_notice']==1 and got['counters']['dropped_after_as_of']==1
    row=got['rows'][0]
    assert row['period_kind']=='ytd' and row['period_months']==9 and row['net_profit_parent']==-20000
    assert row['start']=='2025-10-01' and row['currency']=='USD' and row['point_in_time_claim']=='NONE'
    hk=normalize('global_financials_pit',subject='HK:00700@'+CUTOFF)['rows'][0]
    assert hk['currency']=='CNY'
    data=json.loads(raw('global_financials_pit',SUBJECTS['global_financials_pit']))
    data['result']['data'][0]['DATE_TYPE_CODE']='008'
    bad=normalize('global_financials_pit',C.canonical(data).encode())
    assert bad['counters']['unclassified']==1 and bad['rows']==[]
    data['result']['data'][0]['SECURITY_CODE']='MSFT'
    with pytest.raises(ValueError):normalize('global_financials_pit',C.canonical(data).encode())


def test_global_and_cn_consensus_are_exact_fiscal_estimates():
    hk=normalize('yahoo_consensus',subject='HK:00700@'+CUTOFF)['rows']
    assert hk[0]['fiscal_end']=='2026-09-30' and hk[0]['currency']=='CNY' and hk[0]['quote_currency']=='HKD'
    assert hk[0]['eps_avg']==-1 and hk[0]['analyst_count']==5 and hk[0]['rating'] is None
    cn=normalize('cn_consensus')['rows']
    assert [r['fiscal_label'] for r in cn]==['FY2026','FY2027','FY2028']
    assert cn[0]['currency']=='CNY' and cn[0]['fiscal_end']=='2026-12-31'
    with pytest.raises(ValueError):normalize('cn_consensus',raw('cn_consensus',SUBJECTS['cn_consensus']).replace(b'600000',b'600001'))
    financial=normalize('cn_financials_ytd')['rows'][0]
    assert financial['period_kind']=='ytd' and financial['period_months']==6 and financial['net_profit_deducted'] is None


@pytest.mark.parametrize('subject',['US:../../secret@2026-09-30','US:AAPL@2026-02-30','HK:00700@2099-01-01','US:AAPL?key=x@2026-09-30'])
def test_forbidden_request_identity(subject):
    with pytest.raises(ValueError):E.request_spec('global_quote_ref',subject)


def test_excel_expansion_budget():
    import zipfile
    from io import BytesIO
    buff=BytesIO()
    with zipfile.ZipFile(buff,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('big.xml',b'x'*(4*1024*1024+1))
    with pytest.raises(ValueError):A.excel_rows(buff.getvalue())


def request(path):
    from app import app
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8900') as client:return await client.get(path)
    return asyncio.run(go())


def test_registered_api_and_a25_tuple_plan(tmp_path,monkeypatch):
    root=tmp_path/'lake';seed(initialize_fact_lake(root));monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root))
    before={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    data=request('/api/public-research/market-context?as_of='+CUTOFF).json()['data']
    assert len(data['blocks'])==11 and not data['missing_sources'],data
    assert len(data['turnover']['rows'])==60 and data['turnover']['ma60'] is not None
    for market,symbol in [('US','AAPL'),('HK','00700'),('A','600000')]:
        result=request(f'/api/public-research/company-inputs?market={market}&symbol={symbol}&as_of={CUTOFF}')
        assert result.status_code==200
        body=result.json()['data'];assert body['blocks'] and not body['missing_sources'],body
        for key,stages,provider,reader in S.archive_company_plan(market,symbol,CUTOFF):
            item=reader();assert item['qualification']=='QUALIFIED_CURRENT_ARCHIVED_INPUT' and item['subject']=={'market':market,'symbol':symbol}
            assert item['source_artifact_hash'].startswith('sha256:') and item['provider_fetch_performed'] is False
            assert item['point_in_time_claim']=='NONE' and provider=='immutable_public_source_archive' and stages
    assert before=={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('path',['/api/public-research/market-context?as_of=2026-09-30&url=https://localhost','/api/public-research/company-inputs?market=US&symbol=AAPL&as_of=2026-09-30&path=/etc/passwd','/api/public-research/company-inputs?market=X&symbol=AAPL&as_of=2026-09-30'])
def test_no_arbitrary_query_or_private_path(path):assert request(path).status_code==422


def test_cn_consensus_rejects_similar_revenue_table():
    source='cn_consensus'; body=raw(source,SUBJECTS[source]).decode('gbk').replace('每股收益（元/股）','营业收入（元）').encode('gbk')
    with pytest.raises(ValueError):normalize(source,body)


def test_index_returned_exchange_must_match():
    source='em_market_trend';data=json.loads(raw(source,SUBJECTS[source]));data['data']['market']=0
    with pytest.raises(ValueError):normalize(source,C.canonical(data).encode())


def test_a25_plan_freezes_one_shared_image_and_detaches_callbacks(tmp_path,monkeypatch):
    root=tmp_path/'lake';seed(initialize_fact_lake(root));monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root))
    original=S.load_blocks;calls=[]
    def watched(requests):calls.append(requests);return original(requests)
    monkeypatch.setattr(S,'load_blocks',watched)
    plan=S.archive_company_plan('US','AAPL',CUTOFF)
    first=plan[0][3](); first['block']['rows'][0]['quote']['price']=999
    assert plan[0][3]()['block']['rows'][0]['quote']['price']==150
    assert all(reader()['qualification']=='QUALIFIED_CURRENT_ARCHIVED_INPUT' for _,_,_,reader in plan)
    assert len(calls)==1 and len(calls[0])==3


def test_quote_after_cutoff_diagnostic_only_for_a25(tmp_path,monkeypatch):
    root=tmp_path/'lake';lake=initialize_fact_lake(root);monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root))
    source='global_quote_ref';subject='US:AAPL@2026-09-29'
    persist_capture(lake,raw(source,SUBJECTS[source]),source,subject,CAPTURED,fixture=True)
    reader=S.archive_company_plan('US','AAPL','2026-09-29')[0][3]
    result=reader();assert result['status']=='unavailable' and result['block']['rows']
    assert result['reason_codes']==['QUOTE_AFTER_REQUESTED_CUTOFF']


def test_sparse_biff_bounds_before_cell_load():
    import struct
    from extended_public_fixtures import biff_rows
    body=biff_rows([['date','value'],['2026-09-30',12]])
    # Existing number cell moves past the contract bound, even if DIMENSIONS lies.
    marker=struct.pack('<HHHHH',0x203,14,1,1,0)
    assert marker in body
    body=body.replace(marker,struct.pack('<HHHHH',0x203,14,65500,1,0))
    with pytest.raises(ValueError):A.excel_rows(body)


def test_exact_registered_api_golden(tmp_path,monkeypatch):
    import public_research_archive as archive
    class Frozen(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,10,12,12,tzinfo=timezone.utc)
    monkeypatch.setattr(S,'datetime',Frozen);monkeypatch.setattr(archive,'datetime',Frozen)
    root=tmp_path/'lake';seed(initialize_fact_lake(root));monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root))
    actual={'market':request('/api/public-research/market-context?as_of='+CUTOFF).json()['data']}
    for market,symbol in [('US','AAPL'),('HK','00700'),('A','600000')]:
        actual[market]=request(f'/api/public-research/company-inputs?market={market}&symbol={symbol}&as_of={CUTOFF}').json()['data']
    # Only random observation UUIDs are replaced; all clocks, raw hashes and
    # economics compare exactly against the frontend's same synthetic fixture.
    for value in actual.values():
        mapping={b['evidence']['observation_id']:'synthetic-'+b['source_id']+'-'+b['subject'] for b in value['blocks']}
        for b in value['blocks']:b['evidence']['observation_id']=mapping[b['evidence']['observation_id']]
        if 'turnover' in value:value['turnover']['evidence_ids']=[mapping[x] for x in value['turnover']['evidence_ids']]
    golden=Path(__file__).resolve().parents[2]/'frontend/tests/fixtures/extended-public-research.golden.json'
    assert actual==json.loads(golden.read_text(encoding="utf-8"))


def test_cn_quote_reuses_parser_with_raw_identity_and_clock():
    value=normalize('cn_quote_ref'); row=value['rows'][0]
    assert row['quote']['key']=='sh600000' and row['quote']['currency']=='CNY'
    assert row['quote']['source_time']=='2026-09-30T07:00:00.000000Z'
    assert row['benchmark']['key']=='sh000001' and row['benchmark']['symbol']=='000001'
    with pytest.raises(ValueError):normalize('cn_quote_ref',raw('cn_quote_ref',SUBJECTS['cn_quote_ref']).replace(b'~600000~',b'~600001~'))


def test_financial_amount_scale_retains_explicit_unknown():
    for source in ['global_financials_pit','cn_financials_ytd']:
        row=normalize(source)['rows'][0]
        assert row['amount_unit']=='PROVIDER_RAW_SCALE_UNVERIFIED' and row['amount_scale_to_currency_units'] is None


@pytest.mark.parametrize('body',[b'garbage',b'PKgarbage'])
def test_malformed_spreadsheet_raw_failure_receipt(tmp_path,body):
    lake=initialize_fact_lake(tmp_path/'lake');source='index_valuation'
    receipt=persist_capture(lake,body,source,SUBJECTS[source],CAPTURED,fixture=True)
    assert receipt['status']=='unavailable'
    saved=lake.get_observation(receipt['observation_id'])
    assert saved.observation.payload['normalization_failed'] is True
    assert lake.read_payload(receipt['observation_id'],max_payload_bytes=C.MAX_BYTES)==body
    block=replay(lake,saved)
    assert block['status']=='unavailable' and block['rows']==[]
    assert block['reason_codes']==['HTTP_OR_NORMALIZATION_FAILED']


def test_actual_source_failure_api_golden(tmp_path,monkeypatch):
    import public_research_archive as archive
    class Frozen(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,10,12,12,tzinfo=timezone.utc)
    monkeypatch.setattr(S,'datetime',Frozen);monkeypatch.setattr(archive,'datetime',Frozen)
    root=tmp_path/'lake';lake=initialize_fact_lake(root);monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root))
    persist_capture(lake,b'PKgarbage','index_valuation','000300@'+CUTOFF,CAPTURED,fixture=True)
    data=request('/api/public-research/market-context?as_of='+CUTOFF).json()['data']
    for b in data['blocks']:b['evidence']['observation_id']='synthetic-'+b['source_id']+'-'+b['subject']
    expected=Path(__file__).resolve().parents[2]/'frontend/tests/fixtures/extended-public-failure.golden.json'
    assert data==json.loads(expected.read_text(encoding="utf-8"))
    assert data['blocks'][0]['status']=='unavailable' and len(data['turnover']['rows'])==60
