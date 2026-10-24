"""Independent-review source-state and lifecycle regressions, all offline."""
from types import SimpleNamespace
import threading
import pytest
import astock
import app
import discovery_service as d
import public_data_budget as budget


@pytest.fixture(autouse=True)
def reset_lifecycle():
    budget.startup()
    yield
    budget.shutdown()
    budget.startup()


@pytest.mark.parametrize('payload', [
    {'data': {'klines': ['garbage']}},
    {'rc': 1, 'data': {'klines': []}},
    {'data': {'code':'000001','klines':['2026-10-23,1,2,3,4,5']}},
])
def test_fundflow_invalid_not_cached(monkeypatch,payload):
    monkeypatch.setattr(app,'_DC_CACHE',app.TTLCache())
    monkeypatch.setattr(astock,'em_get',lambda *a,**kw:SimpleNamespace(status_code=200,json=lambda:payload))
    with pytest.raises(app.HTTPException): app.fund_flow('600000')
    assert not app._DC_CACHE._data

@pytest.mark.parametrize('route,payload', [('blocks',{'rc':1,'data':{'diff':[]}}),('hot_concepts',{'code':1,'message':'failed','data':[]})])
def test_business_fail_not_cached(monkeypatch,route,payload):
    import requests
    monkeypatch.setattr(app,'_DC_CACHE',app.TTLCache())
    fake=lambda *a,**kw:SimpleNamespace(status_code=200,json=lambda:payload)
    monkeypatch.setattr(astock,'em_get',fake)
    monkeypatch.setattr(requests,'post',fake)
    with pytest.raises(app.HTTPException): getattr(app,route)('600000')
    assert not app._DC_CACHE._data

@pytest.mark.parametrize("force", [False, True])
def test_cold_miss_race_does_not_refresh_twice(monkeypatch, force):
    d.clear_cache()
    actual=threading.Lock(); entered=threading.Event(); resume=threading.Event(); calls=[]; results=[]
    class DelayedLock:
        def acquire(self,blocking=False):
            if threading.current_thread().name=='delayed-reader':
                entered.set(); assert resume.wait(3)
            return actual.acquire(blocking=blocking)
        def release(self):actual.release()
    monkeypatch.setattr(d,'_REFRESH_LOCK',DelayedLock())
    monkeypatch.setattr(d,'run_discovery',lambda: calls.append(1) or {'status':'normal','cache':{}})
    thread=threading.Thread(name='delayed-reader',target=lambda: results.append(d.get_discovery(force_refresh=force)))
    thread.start()
    try:
        assert entered.wait(3)
        d.get_discovery(force_refresh=force)
    finally:
        resume.set(); thread.join(3)
    assert len(calls)==1

@pytest.mark.parametrize('payload,status', [
    ({'rc':1,'data':{'total':1,'diff':[{'f12':'BK1','f14':'fixture','f3':1.0}]}},200),
    ({'data':{'total':1,'diff':[{'f12':{'wrong':'type'},'f14':'fixture','f3':1.0}]}},200),
    ({'data':{'total':1,'diff':[{'f12':'BK1','f14':'fixture','f3':1.0}]}},404),
])
def test_board_failure_not_normal(monkeypatch,payload,status):
    import market
    monkeypatch.setattr(market,'_CACHE',{})
    monkeypatch.setattr(astock,'em_get',lambda *a,**kw:SimpleNamespace(status_code=status,json=lambda:payload))
    result=market.get_board_ranking()
    assert result['status']=='unavailable'
    assert not market._CACHE

def test_overview_response_budget_includes_snapshot_seed_lock(monkeypatch):
    import market, public_data_budget as b, time
    from concurrent.futures import Future
    monkeypatch.setattr(market,'_CACHE',{})
    monkeypatch.setattr(b,'_CACHE',{})
    monkeypatch.setattr(b,'_OVERVIEW_FLIGHT',None)
    monkeypatch.setattr(market,'observation_session',lambda:'2026-10-23')
    monkeypatch.setattr(market.push2_guard,'is_read_only',lambda:False)
    monkeypatch.setattr(b,'_run_process',lambda *a,**kw: {'sentiment':{'status':'unavailable','date':'2026-10-23'}})
    b.startup()
    market._A_SHARE_SNAPSHOT_LOCK.acquire()
    release=threading.Timer(.25,market._A_SHARE_SNAPSHOT_LOCK.release)
    release.start()
    start=time.monotonic()
    try:
        try: b.run('overview',timeout=.02)
        except b.PublicDataUnavailable: pass
        elapsed=time.monotonic()-start
    finally:
        release.join(); b.shutdown()
    assert elapsed<.15, f'response blocked {elapsed:.3f}s outside requested .02s budget'


def test_later_independent_force_still_refreshes(monkeypatch):
    d.clear_cache()
    calls=[]
    monkeypatch.setattr(d,'run_discovery',lambda: calls.append(1) or {'status':'normal','cache':{}})
    d.get_discovery(force_refresh=True)
    d.get_discovery(force_refresh=True)
    assert len(calls)==2

@pytest.mark.parametrize('route,payload', [
    ('fund_flow', {'rc':0,'data':{'code':'600000','klines':[]}}),
    ('blocks', {'rc':0,'data':{'diff':[]}}),
    ('hot_concepts', {'code':0,'data':[]}),
])
def test_explicit_legal_empty_remains_cacheable(monkeypatch, route, payload):
    import requests
    monkeypatch.setattr(app,'_DC_CACHE',app.TTLCache())
    calls=[]
    def fake(*a, **kw):
        calls.append(1)
        return SimpleNamespace(status_code=200,json=lambda:payload)
    monkeypatch.setattr(astock,'em_get',fake)
    monkeypatch.setattr(requests,'post',fake)
    first=getattr(app,route)('600000')
    assert getattr(app,route)('600000')==first
    assert len(calls)==1
