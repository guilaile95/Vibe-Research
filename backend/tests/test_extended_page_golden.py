"""Real registered read API fixtures for the full DailyReview date-ownership lane."""
import json
import socket
from pathlib import Path
from datetime import datetime, timezone
import public_research_archive as archive
import public_research_extended_service as service
import public_research_extended_contract as contract
from fact_lake_store import initialize_fact_lake
from extended_public_fixtures import raw, CAPTURED
from test_extended_public_research import request

GOLDEN = Path(__file__).resolve().parents[2] / 'frontend/tests/fixtures/extended-page-market.golden.json'
DAYS = ('2026-07-31', '2026-07-30', '2026-07-29')

def produce(tmp_path, monkeypatch, scenario="normal"):
    def deny(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None): return cls(2026,10,12,12,tzinfo=timezone.utc)
    monkeypatch.setattr(archive, 'datetime', Frozen)
    monkeypatch.setattr(service, 'datetime', Frozen)
    root=tmp_path/'lake'; lake=initialize_fact_lake(root)
    monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root))
    for day in DAYS:
        for source, keys in [('em_market_trend',contract.INDICES),('index_valuation',['000300']),('chinabond_yield_curve',['treasury'])]:
            for key in keys:
                subject=key+'@'+day
                if scenario == 'normal': archive.persist_capture(lake,raw(source,subject),source,subject,CAPTURED,fixture=True)
                elif scenario == 'failure' and source == 'index_valuation': archive.persist_capture(lake,b'garbage',source,subject,CAPTURED,fixture=True)
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result={}
    for day in DAYS:
        response=request('/api/public-research/market-context?as_of='+day)
        assert response.status_code==200
        value=response.json()['data']
        mapping={b['evidence']['observation_id']:'synthetic-'+b['source_id']+'-'+b['subject'] for b in value['blocks']}
        for block in value['blocks']: block['evidence']['observation_id']=mapping[block['evidence']['observation_id']]
        value['turnover']['evidence_ids']=[mapping[x] for x in value['turnover']['evidence_ids']]
        result[day]=value
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    return result

def test_registered_read_api_exact_dailyreview_dates(tmp_path, monkeypatch):
    assert produce(tmp_path,monkeypatch)==json.loads(GOLDEN.read_text(encoding='utf-8'))

import pytest
@pytest.mark.parametrize("scenario",["failure","missing"])
def test_registered_read_api_missing_failure(tmp_path,monkeypatch,scenario):
    golden=GOLDEN.with_name("extended-page-market-"+scenario+".golden.json")
    assert produce(tmp_path,monkeypatch,scenario)==json.loads(golden.read_text(encoding='utf-8'))
