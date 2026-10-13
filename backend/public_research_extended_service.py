"""Read-only projections and A25 reader plan over existing immutable raw receipts."""
from datetime import datetime, timedelta, timezone
import os
from fact_lake_store import open_existing_fact_lake_snapshot, FactLakeNotInitializedError, FactLakeBusyError
import public_research_contract as C
import public_research_extended_contract as E
from public_research_archive import replay


def load_blocks(requests):
    """One immutable handle; global count/byte budgets precede reads, no networking."""
    if not requests or len(requests)>11 or len(set(requests))!=len(requests): raise ValueError('invalid source request budget')
    for source,subject in requests: E.parse_subject(source,subject)
    root=os.environ.get('VR_FACT_LAKE_ROOT','').strip()
    if not root: return [],'ARCHIVE_NOT_CONNECTED'
    try:
        lake=open_existing_fact_lake_snapshot(root); now=datetime.now(timezone.utc); blocks=[]; remaining=16*1024*1024; count=0
        for source,subject in requests:
            receipts=lake.list_observations(dataset_id=C.dataset_id(source,subject), start_trade_date=(now.date()-timedelta(days=366)).isoformat(),end_trade_date=now.date().isoformat(),limit=128-count,max_payload_bytes=remaining)
            count+=len(receipts)
            if count>=128: raise ValueError('receipt budget')
            chosen=None
            for stored in receipts:
                block=replay(lake,stored,now=now,max_bytes=min(C.MAX_BYTES,remaining)); remaining-=block['raw_bytes']
                if block['source_id']!=source or block['subject']!=subject: raise ValueError('archive identity conflict')
                rank=C.stamp(block['captured_at'])
                if chosen and rank==C.stamp(chosen['captured_at']) and (block['evidence']['raw_payload_hash'],block['fixture'],block['status'])!=(chosen['evidence']['raw_payload_hash'],chosen['fixture'],chosen['status']): raise ValueError('ambiguous latest receipt')
                if chosen is None or rank>C.stamp(chosen['captured_at']): chosen=block
            if chosen is not None: blocks.append(chosen)
        if len({b['fixture'] for b in blocks})>1: raise ValueError('mixed acquired and synthetic evidence')
        lake.assert_unchanged(); return blocks,None
    except FactLakeNotInitializedError: return [],'ARCHIVE_NOT_INITIALIZED'
    except FactLakeBusyError: return [],'ARCHIVE_BUSY'
    except Exception: return [],'ARCHIVE_VALIDATION_FAILED'


def _envelope(requests, kind, cutoff, market=None, symbol=None):
    blocks,error=load_blocks(requests); found={(b['source_id'],b['subject']) for b in blocks}
    return {'schema_version':'extended-public-research.v1','kind':kind,'market':market,'symbol':symbol,'requested_as_of':cutoff,
            'selection_mode':'CURRENT_ARCHIVED_POSTHOC','point_in_time_claim':'NONE','ingestion_enabled':False,'schedule_enabled':False,
            'status':'unavailable' if error else 'partial' if blocks else 'missing','fixture':any(b['fixture'] for b in blocks),
            'blocks':blocks,'missing_sources':[{'source_id':s,'subject':sub} for s,sub in requests if (s,sub) not in found],
            'reason_codes':[error] if error else [],'message':'合成案例，仅验证软件，非真实市场验收' if any(b['fixture'] for b in blocks) else '当前存储版本的事后研究；所选截止日不证明历史当时已知',
            'archive_window_days':366}


def market_context(cutoff):
    C.day(cutoff)
    from public_research_extended_adapters import calendar
    expected=calendar(cutoff)[-60:]
    requests=[('em_market_trend',k+'@'+cutoff) for k in E.INDICES]+[('index_valuation','000300@'+cutoff),('chinabond_yield_curve','treasury@'+cutoff)]
    result=_envelope(requests,'market',cutoff,'CN',None)
    trends={b['subject'].split('@')[0]:b for b in result['blocks'] if b['source_id']=='em_market_trend' and b['rows']}
    sh,sz=trends.get('sh000001'),trends.get('sz399106')
    amount=[]
    left={r['date']:r for r in sh['rows'][0]['amount_rows']} if sh else {}
    right={r['date']:r for r in sz['rows'][0]['amount_rows']} if sz else {}
    if any(block and block['rows'][0]['amount_window']['expected_dates']!=expected for block in (sh,sz)):
        raise ValueError('turnover session mismatch')
    for day in expected:
        a=left.get(day,{}).get('amount'); b=right.get(day,{}).get('amount')
        total=a+b if a is not None and b is not None else None
        amount.append({'date':day,'sh':a,'sz_composite':b,'total':total,'unit':'CNY','currency':'CNY'})
    result['turnover']={'expected_dates':expected,'rows':amount,'missing_dates':[r['date'] for r in amount if r['total'] is None],
                        'ma20':sum(r['total'] for r in amount[-20:])/20 if len(amount)>=20 and all(r['total'] is not None for r in amount[-20:]) else None,
                        'ma60':sum(r['total'] for r in amount)/60 if len(amount)==60 and all(r['total'] is not None for r in amount) else None,
                        'basis':'SH composite amount + SZ composite amount; exact common exchange sessions',
                        'evidence_ids':[b['evidence']['observation_id'] for b in (sh,sz) if b]}
    C.canonical(result); return result


def company_inputs(market,symbol,cutoff):
    sources=E.CN if market=='A' else E.GLOBAL
    subject=f'{market}:{symbol}@{cutoff}'
    for source in sources: E.parse_subject(source,subject)
    return _envelope([(source,subject) for source in sources],'company',cutoff,market,symbol)


def archive_company_plan(market,symbol,as_of=None):
    """A25 tuple interface: callbacks read archives only, never fetch a provider.

    Full source rows/qualifications/raw artifact hashes remain in the frozen
    adapter bundle. A source being present does not certify its numeric claims.
    """
    cutoff=as_of or datetime.now(timezone.utc).date().isoformat()
    sources=E.CN if market=='A' else E.GLOBAL
    subject=f'{market}:{symbol}@{cutoff}'
    stage_map={'cn_quote_ref':('profile','valuation'),'global_quote_ref':('profile','valuation'),'global_financials_pit':('financials','risk'),'yahoo_consensus':('estimates',),'cn_financials_ytd':('financials','risk'),'cn_consensus':('estimates',)}
    # Capture one immutable image before constructing callbacks. Detached copies
    # cannot mix later archive revisions or synthetic/acquired source classes.
    import copy
    blocks,error=load_blocks([(source,subject) for source in sources])
    image={block['source_id']:block for block in blocks}
    plan=[]
    for source in sources:
        E.parse_subject(source,subject)
        def reader(source=source):
            block=copy.deepcopy(image.get(source))
            after_cutoff=bool(block and source in ('global_quote_ref','cn_quote_ref') and any(r.get('after_requested_date') for r in block['rows']))
            available=bool(block and block['rows'] and block['status'] not in ('unavailable','missing') and not after_cutoff)
            return {'schema_version':'company-public-source.v1','subject':{'market':market,'symbol':symbol},'market':market,'symbol':symbol,
                    'source_id':source,'status':'partial' if available else 'unavailable','qualification':'QUALIFIED_CURRENT_ARCHIVED_INPUT' if available else 'MISSING_OR_INVALID_ARCHIVE',
                    'as_of':cutoff,'source_time':None,'capture_time':block['captured_at'] if block else None,
                    'source_artifact_hash':block['evidence']['raw_payload_hash'] if block else None,'point_in_time_claim':'NONE',
                    'provider_fetch_performed':False,'block':block,'reason_codes':[error] if error else ['QUOTE_AFTER_REQUESTED_CUTOFF'] if after_cutoff else []}
        plan.append((source,stage_map[source],'immutable_public_source_archive',reader))
    return plan
