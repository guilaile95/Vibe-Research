"""Deterministic actual-router/store outputs; synthetic model stream only."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import httpx
import app
import shortline_review_sources as sources
import shortline_review_service as service
import shortline_review_store as store
from test_shortline_review import inputs, model

DAY = '2026-07-31'
class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 8, 3, tzinfo=timezone.utc)

def create_golden(monkeypatch, root, loop):
    original = service.generate
    build_bundle = sources.build_bundle
    monkeypatch.setattr(app, '_require_llm_ready', lambda _: True)
    monkeypatch.setattr(service, 'datetime', Clock)
    result = {}
    async def invoke(method, path, body=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://testserver') as client:
            response = await client.request(method, path, json=body)
            assert response.status_code == 200, response.text
            return response
    for name, mode, missing in [('daily','daily',False),('weekly','weekly',False),('partial','daily',True),('empty','daily','all')]:
        raw = inputs(DAY)
        if missing: raw = {} if missing == 'all' else {k:v for k,v in raw.items() if k != 'dragon_tiger'}
        bundle = build_bundle(DAY, mode, sources=lambda _:raw, verify=lambda _:('b'*64,{'decided':2},'normal'), dates=lambda *_:[DAY])
        monkeypatch.setattr(sources, 'build_bundle', lambda *_, b=bundle:b)
        monkeypatch.setattr(store.review_history, 'resolve_review_db_path', lambda n=name: root/(n+'.sqlite3'))
        calls=[]
        monkeypatch.setattr(service,'generate',lambda b,i,c,x:original(b,i,c,x,stream=model(calls)))
        preview=loop.run_until_complete(invoke('GET',f'/api/shortline-review/preview?trade_date={DAY}&mode={mode}')).json()['data']
        row={'preview':preview}
        if preview['available']:
            generation=('a' if name=='daily' else 'b' if name=='weekly' else 'c')*32
            body={'trade_date':DAY,'mode':mode,'bundle_id':bundle['bundle_id'],'generation_id':generation,'llm':{'provider':'cli-codex','model':'SYNTHETIC_OFFLINE'}}
            response=loop.run_until_complete(invoke('POST','/api/shortline-review/generate',body))
            row['events']=[json.loads(line) for line in response.text.splitlines()]
            row['version']=loop.run_until_complete(invoke('GET','/api/shortline-review/version/'+generation)).json()['data']
            row['versions']=loop.run_until_complete(invoke('GET',f'/api/shortline-review/versions?trade_date={DAY}&mode={mode}')).json()['data']
            row['synthetic_model_calls']=len(calls)
        result[name]=row
    return result
