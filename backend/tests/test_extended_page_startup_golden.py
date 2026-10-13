"""Exact incidental page reads at the extended harness clock; no live providers."""
import asyncio
from datetime import date, datetime
import json
from pathlib import Path
import socket
import httpx
import next_day_verification as journal
import research_event_calendar as calendar

GOLDEN=Path(__file__).resolve().parents[2]/'frontend/tests/fixtures/extended-page-startup.golden.json'
CLOCK='2026-10-12T23:00:00+00:00'

def produce(tmp_path, monkeypatch):
    # Construct the event-loop wakeup sockets before denying network (Windows too).
    loop=asyncio.new_event_loop()
    attempted=[]; provider_stubs=[]
    def deny(*args,**kwargs):
        attempted.append('network'); raise AssertionError('outbound network forbidden')
    def unavailable(name):
        def read(code,*args,**kwargs):
            assert code=='600000'
            provider_stubs.append(name)
            raise RuntimeError('synthetic unavailable source')
        return read
    monkeypatch.setenv('VR_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(tmp_path/'unconfigured-lake'))
    monkeypatch.setattr(socket.socket,'connect',deny)
    monkeypatch.setattr(socket.socket,'connect_ex',deny)
    monkeypatch.setattr(socket,'create_connection',deny)
    monkeypatch.setattr(socket,'getaddrinfo',deny)
    monkeypatch.setattr(journal,'_now',lambda:datetime.fromisoformat(CLOCK))
    monkeypatch.setattr(calendar,'_today',lambda:date(2026,10,13))
    monkeypatch.setattr(calendar,'_fetched_at',lambda:'2026-10-12T23:00:00.000000Z')
    monkeypatch.setattr(calendar.research_continuity_service,'_calendar',unavailable('periodic'))
    for name in ['lockup_expiry','dividend_history','announcements']:
        monkeypatch.setattr(calendar.astock,name,unavailable(name))
    # Actual application route registration; real journal and calendar projection.
    from app import app
    paths={'journal':'/api/next-day-verification/2026-10-13','calendar':'/api/research-events?security_code=600000'}
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            out={}
            for key,path in paths.items():
                response=await client.get(path);assert response.status_code==200
                out[key]=response.json()
            return out
    try:
        actual=loop.run_until_complete(run())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor());loop.close()
    assert attempted==[]
    assert provider_stubs==['periodic','lockup_expiry','dividend_history','announcements']
    assert before=={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert actual['calendar']['data']['status']=='UNAVAILABLE'
    assert actual['calendar']['data']['events']==[]
    assert all(value==0 for value in actual['calendar']['data']['writes'].values())
    return actual

def test_registered_startup_reads_are_exact_offline_and_readonly(tmp_path,monkeypatch):
    assert produce(tmp_path,monkeypatch)==json.loads(GOLDEN.read_text(encoding='utf-8'))
