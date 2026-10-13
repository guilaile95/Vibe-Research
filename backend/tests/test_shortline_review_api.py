"""Manual P5 HTTP protocol with mocked runtime and real temporary version store."""
import json
import threading
from fastapi.testclient import TestClient
import pytest
import app
import shortline_review_sources as sources
import shortline_review_service as service
import shortline_review_store as store
from test_shortline_review import bundle,model,DAY

LLM={"provider":"fixture","model":"fixture","apiKey":"synthetic","baseURL":"https://example.invalid"}

@pytest.fixture
def setup(tmp_path,monkeypatch):
    path=tmp_path/"review.sqlite3";b=bundle()
    monkeypatch.setattr(store.review_history,"resolve_review_db_path",lambda:path)
    monkeypatch.setattr(sources,"build_bundle",lambda *_:b)
    monkeypatch.setattr(app,"_require_llm_ready",lambda _:True)
    calls=[];original=service.generate
    monkeypatch.setattr(service,"generate",lambda b,i,c,x:original(b,i,c,x,stream=model(calls)))
    return TestClient(app.app),b,calls,path


def test_preview_generation_append_and_restore_are_one_identity(setup):
    client,b,calls,path=setup
    p=client.get(f"/api/shortline-review/preview?trade_date={DAY}&mode=daily")
    assert p.status_code==200 and p.json()["data"]["model_calls_performed"]==0 and calls==[] and not path.exists()
    body={"trade_date":DAY,"mode":"daily","bundle_id":b["bundle_id"],"generation_id":"a"*32,"llm":LLM}
    response=client.post("/api/shortline-review/generate",json=body)
    assert response.status_code==200
    events=[json.loads(x)for x in response.text.splitlines()];assert events[-1]["type"]=="done" and len(calls)==6
    detail=client.get("/api/shortline-review/version/"+"a"*32)
    assert detail.status_code==200 and detail.json()["data"]["bundle"]["bundle_id"]==b["bundle_id"]
    retry=client.post("/api/shortline-review/generate",json=body)
    assert json.loads(retry.text)["model_calls"]==0 and len(calls)==6
    versions=client.get(f"/api/shortline-review/versions?trade_date={DAY}&mode=daily").json()["data"]
    assert len(versions)==1
    assert "synthetic" not in detail.text


def test_hash_mismatch_and_client_evidence_rejected_without_cost(setup):
    client,b,calls,_=setup
    body={"trade_date":DAY,"mode":"daily","bundle_id":"0"*64,"generation_id":"b"*32,"llm":LLM}
    assert client.post("/api/shortline-review/generate",json=body).status_code==409
    body["evidence"]={"private":1}
    assert client.post("/api/shortline-review/generate",json=body).status_code==422
    assert calls==[]
    assert client.get(f"/api/shortline-review/preview?trade_date={DAY}&mode=daily&path=x").status_code==400


def test_stream_cancel_after_section_never_saves(setup):
    _,b,_,path=setup;cancel=threading.Event();events=service.generate(b,"c"*32,LLM,cancel)
    for e in events:
        if e["type"]=="stage_done":cancel.set()
    assert store.get_version("c"*32)is None and not path.exists()


def test_query_contract_rejects_duplicates_and_detail_parameters(setup):
    client,*_=setup
    for endpoint in ('preview','versions'):
        assert client.get(f'/api/shortline-review/{endpoint}?trade_date={DAY}&trade_date={DAY}').status_code==400
    assert client.get('/api/shortline-review/version/'+'a'*32+'?extra=1').status_code==400


def test_task_cancel_during_prepare_releases_capacity(monkeypatch):
    import asyncio
    async def run():
        entered=asyncio.Event()
        async def blocked(*args):entered.set();await asyncio.Event().wait()
        monkeypatch.setattr(app,'run_in_threadpool',blocked)
        monkeypatch.setattr(app,'_require_llm_ready',lambda _:True)
        request=app.ShortlineReviewRequest(trade_date=DAY,mode='daily',bundle_id='a'*64,generation_id='f'*32,llm=LLM)
        task=asyncio.create_task(app.shortline_review_generate(request))
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert 'f'*32 not in service._ACTIVE
    asyncio.run(run())


def test_actual_asgi_disconnect_sets_shared_cancel_before_any_commit(setup,monkeypatch):
    import asyncio
    _,b,_,path=setup
    observed=threading.Event();waiting=threading.Event();saved=[]
    def generate(_bundle,_id,_cfg,cancel):
        yield {'type':'basis','bundle_id':b['bundle_id']}
        waiting.set()
        assert cancel.wait(2), 'ASGI disconnect must reach shared cancellation event'
        observed.set()
        if not cancel.is_set():saved.append(True)
    monkeypatch.setattr(service,'generate',generate)
    async def run():
        body_sent=asyncio.Event()
        req=app.ShortlineReviewRequest(trade_date=DAY,mode='daily',bundle_id=b['bundle_id'],generation_id='e'*32,llm=LLM)
        response=await app.shortline_review_generate(req)
        async def receive():
            await body_sent.wait()
            for _ in range(2000):
                if waiting.is_set():break
                await asyncio.sleep(0.001)
            assert waiting.is_set()
            return {'type':'http.disconnect'}
        async def send(message):
            if message['type']=='http.response.body' and message.get('body'):body_sent.set()
        await response({'type':'http','asgi':{'version':'3.0','spec_version':'2.3'}},receive,send)
    asyncio.run(run())
    assert observed.wait(2) and saved==[] and not path.exists()
    assert 'e'*32 not in service._ACTIVE
