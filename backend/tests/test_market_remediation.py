"""Offline counterexamples for audit P1-06/07/08; no provider I/O."""
import copy
from types import SimpleNamespace

import pytest
import astock
import market
import public_data_budget as budget


@pytest.fixture(autouse=True)
def clear_caches(monkeypatch):
    monkeypatch.setattr(market, '_CACHE', {})
    monkeypatch.setattr(budget, '_CACHE', {})
    monkeypatch.setattr(budget, '_INFLIGHT', set())
    monkeypatch.setattr(budget, '_OVERVIEW_FLIGHT', None)
    budget.startup()
    yield
    budget.shutdown()
    budget.startup()


@pytest.mark.parametrize('route', ['margin', 'block_trade', 'holders', 'dividend', 'dragon_tiger', 'lockup', 'blocks'])
def test_source_failure_is_not_cached_empty(monkeypatch, route):
    import app
    monkeypatch.setattr(app, '_DC_CACHE', app.TTLCache())
    calls = []
    def unavailable(*a, **kw):
        calls.append(1)
        raise TimeoutError('private source detail')
    monkeypatch.setattr(astock, 'em_get', unavailable)
    for _ in range(2):
        with pytest.raises(app.HTTPException) as caught:
            getattr(app, route)('600000')
        assert caught.value.status_code == 502
        assert 'private' not in caught.value.detail
    assert len(calls) == 2


def test_legal_empty_is_cached(monkeypatch):
    import app
    monkeypatch.setattr(app, '_DC_CACHE', app.TTLCache())
    calls = []
    def empty(*a, **kw):
        calls.append(1)
        return SimpleNamespace(json=lambda: {'result': {'data': []}}, status_code=200)
    monkeypatch.setattr(astock, 'em_get', empty)
    assert app.margin('600000') == {'data': []}
    assert app.margin('600000') == {'data': []}
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['short', 'changed', 'duplicate', 'invalid_count', 'overshoot', 'bad_row'])
def test_incomplete_boards_are_unavailable_and_not_cached(monkeypatch, kind):
    calls = []
    row = {'f12': 'BK1', 'f14': 'fixture', 'f3': 1.0}
    def page(*a, **kw):
        calls.append(1)
        pn = int(kw['params']['pn'])
        total, rows = 500, [row]
        if kind == 'changed':
            total, rows = (501 if pn > 1 else 500), [dict(row, f12=f'BK{pn}')]
        elif kind == 'duplicate': total, rows = 2, [row, row]
        elif kind == 'invalid_count': total = True
        elif kind == 'overshoot': total = 0
        elif kind == 'bad_row': total, rows = 2, [row, None]
        return SimpleNamespace(json=lambda: {'data': {'total': total, 'diff': rows}})
    monkeypatch.setattr(astock, 'em_get', page)
    for _ in range(2):
        result = market.get_board_ranking()
        assert result['status'] == 'unavailable'
        assert result['data'] is None
    assert len(calls) >= 2
    assert not market._CACHE


def qualified_overview():
    pool = {'status': 'partial', 'reason_codes': ['DATE_BINDING_UNVERIFIED'],
            'count': 1, 'observed_row_count': 1, 'observed_empty': False}
    return {'sentiment': {'status': 'partial', 'breadth_status': 'normal', 'date': '2026-10-23',
            'emotion_provenance': {'pool_observations': {k: copy.deepcopy(pool) for k in ('zt','zb','dt','yzt')}}},
            'sectors': [], 'updated': '2026-10-23 15:30'}


def test_qualified_overview_reuses_parent_cache_without_status_upgrade(monkeypatch):
    monkeypatch.setattr(market.trade_calendar, 'observation_trade_date_at', lambda _: '2026-10-23')
    calls = []
    def refresh(*a, **kw):
        calls.append(kw['timeout'])
        return qualified_overview()
    monkeypatch.setattr(budget, '_run_process', refresh)
    first = budget.run('overview')
    first['sentiment']['date'] = 'mutated'
    second = budget.run('overview')
    assert len(calls) == 1
    assert second['sentiment']['status'] == 'partial'
    assert second['sentiment']['date'] == '2026-10-23'
    assert calls[0] >= astock._A_SHARE_SNAPSHOT_BUDGET_SECONDS


def test_failed_partial_and_previous_session_overview_do_not_suppress_retry(monkeypatch):
    session = ['2026-10-23']
    monkeypatch.setattr(market.trade_calendar, 'observation_trade_date_at', lambda _: session[0])
    values = [qualified_overview() for _ in range(4)]
    values[2]['sentiment']['emotion_provenance']['pool_observations']['zt']['reason_codes'] = ['SOURCE_TIMEOUT']
    calls = []
    def refresh(*a, **kw):
        calls.append(1)
        return values[len(calls)-1]
    monkeypatch.setattr(budget, '_run_process', refresh)
    budget.run('overview')
    session[0] = '2026-10-26'
    budget.run('overview')
    # Old-date result cannot be cached in the new session.
    budget.run('overview')
    budget.run('overview')
    assert len(calls) == 4


@pytest.mark.parametrize('payload', [None, {}, {'result': {'data': None}}, {'success': False, 'result': {'data': []}}, {'result': {'data': [{'SCODE': '000001'}]}}])
def test_malformed_or_wrong_identity_is_not_legal_empty(monkeypatch, payload):
    import app
    monkeypatch.setattr(app, '_DC_CACHE', app.TTLCache())
    monkeypatch.setattr(astock, 'em_get', lambda *a, **kw: SimpleNamespace(json=lambda: payload, status_code=200))
    with pytest.raises(app.HTTPException) as caught:
        app.margin('600000')
    assert caught.value.status_code == 502
    assert not app._DC_CACHE._data


def test_completed_market_observation_is_reused_without_new_fetch(monkeypatch):
    import time
    monkeypatch.setattr(market.trade_calendar, 'observation_trade_date_at', lambda _: '2026-10-23')
    value = qualified_overview()
    market._CACHE['overview'] = (time.time(), value, '2026-10-23')
    monkeypatch.setattr(budget, '_run_process', lambda *a, **kw: pytest.fail('must not spawn for completed overview'))
    assert budget.run('overview') == value


def test_snapshot_seed_keeps_observation_age_and_rejects_stale_session(monkeypatch):
    import time
    session = ['2026-10-23']
    monkeypatch.setattr(market.trade_calendar, 'observation_trade_date_at', lambda instant: '2026-10-23' if instant == 'old-observation' else session[0])
    stamp = time.time() - 20
    snapshot = {'rows': [{'code': '600000', 'price': 10}], 'observed_at': 'old-observation', 'fetched_at': 'original'}
    market._CACHE['a_share_snapshot'] = (stamp, snapshot)
    captured = []
    def refresh(op, code, **kw):
        captured.append(code['snapshot_seed'])
        return qualified_overview()
    monkeypatch.setattr(budget, '_run_process', refresh)
    budget.run('overview')
    assert captured[0] == (stamp, snapshot)
    assert captured[0][1] is not snapshot
    session[0] = '2026-10-26'
    budget.run('overview')
    assert captured[1] is None


def synthetic_throttled_overview(path, operation, log_path):
    """Real spawn + real throttle + complete 5001 rows; transport is synthetic."""
    import astock as a, market as m, trade_calendar as cal
    cal.observation_trade_date_at = lambda _: '2026-10-23'
    cal._load_calendar = lambda: ('2026-10-23',)
    a.push2_guard.reserve = lambda: None
    a.push2_guard.record = lambda _: None
    a.random.uniform = lambda *args: .1
    m._sectors = lambda: []
    class Session:
        def get(self, url, params=None, **kw):
            with open(log_path, 'a') as handle:
                handle.write(url.rsplit('/', 1)[-1] + '\n')
            if url.endswith('clist/get'):
                start = (int(params['pn']) - 1) * 500
                rows = [{'f12': str(600000+i), 'f13': 1, 'f14': 'fixture', 'f2': 10, 'f3': 1, 'f6': 1000}
                        for i in range(start, min(start+500, 5001))]
                payload = {'data': {'total': 5001, 'diff': rows}}
            else:
                payload = {'rc': 0, 'data': {'qdate': '20261023', 'pool': [{'c': '600001', 'lbc': 1}]}}
            return SimpleNamespace(status_code=200, json=lambda: payload)
    a._em_session = lambda *args: Session()
    budget._child(path, operation, None)


def test_cold_overview_completes_full_pages_under_real_throttle_and_reaps(monkeypatch, tmp_path):
    import multiprocessing
    import time
    before = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    log = tmp_path / 'requests.txt'
    monkeypatch.setattr(market.trade_calendar, 'observation_trade_date_at', lambda _: '2026-10-23')
    original = budget._run_process
    calls = []
    def refresh(*a, **kw):
        calls.append(1)
        return original('overview', str(log), _target=synthetic_throttled_overview, **kw)
    monkeypatch.setattr(budget, '_run_process', refresh)
    with pytest.raises(budget.PublicDataUnavailable, match='SOURCE_REFRESH_PENDING'):
        budget.run('overview')
    response_elapsed = time.monotonic() - started
    assert 11.5 <= response_elapsed < 13
    with pytest.raises(budget.PublicDataUnavailable, match='SOURCE_REFRESH_PENDING'):
        budget.run('overview', timeout=.01)
    budget._OVERVIEW_THREAD.join(30)
    value = budget.run('overview')
    assert len(calls) == 1
    elapsed = time.monotonic() - started
    assert value['sentiment']['stock_count'] == 5001
    assert value['sentiment']['status'] == 'partial'
    assert len(log.read_text().splitlines()) == 15
    assert 12 < elapsed < budget.OVERVIEW_TIMEOUT
    assert {p.pid for p in multiprocessing.active_children()} == before
    print(f'5001 rows, 15 synthetic calls, real throttle, response {response_elapsed:.2f}s, completion {elapsed:.2f}s, one worker, no remaining children')


def test_two_request_deadlines_share_one_admitted_refresh(monkeypatch):
    import threading
    import time
    monkeypatch.setattr(market.trade_calendar, 'observation_trade_date_at', lambda _: '2026-10-23')
    entered, release = threading.Event(), threading.Event()
    calls = []
    def refresh(*a, **kw):
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return qualified_overview()
    monkeypatch.setattr(budget, '_run_process', refresh)
    try:
        start = time.monotonic()
        for _ in range(3):
            with pytest.raises(budget.PublicDataUnavailable, match='SOURCE_REFRESH_PENDING'):
                budget.run('overview', timeout=.02)
        assert entered.is_set() and len(calls) == 1
        assert time.monotonic() - start < .5
        assert len([t for t in threading.enumerate() if t.name == 'public-overview-refresh']) == 1
    finally:
        release.set()
        budget._OVERVIEW_THREAD.join(2)
    assert budget.run('overview')['sentiment']['status'] == 'partial'
    assert len(calls) == 1


def stalled_overview_child(path, operation, code):
    import time
    # Marker demonstrates actual child execution, not Future cancellation alone.
    with open(code, 'w') as handle:
        handle.write('running')
    time.sleep(60)


def test_shutdown_reaps_active_refresh_and_releases_all_slots(monkeypatch, tmp_path):
    import multiprocessing
    import time
    before = {p.pid for p in multiprocessing.active_children()}
    marker = tmp_path / 'started'
    original = budget._run_process
    def refresh(*a, **kw):
        return original('overview', str(marker), _target=stalled_overview_child, **kw)
    monkeypatch.setattr(budget, '_run_process', refresh)
    with pytest.raises(budget.PublicDataUnavailable, match='SOURCE_REFRESH_PENDING'):
        budget.run('overview', timeout=.02)
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert marker.exists()
    started = time.monotonic()
    budget.shutdown()
    assert time.monotonic() - started < 2
    assert not budget._OVERVIEW_THREAD.is_alive()
    assert {p.pid for p in multiprocessing.active_children()} == before
    assert budget._OVERVIEW_FLIGHT.exception().code == 'SOURCE_CANCELLED'
    for _ in range(4): assert budget._SLOTS.acquire(False)
    for _ in range(4): budget._SLOTS.release()
    with pytest.raises(budget.PublicDataUnavailable, match='SOURCE_CANCELLED'):
        budget.run('overview')
    print('Active overview shutdown: child killed/reaped, supervisor exited, all four slots reusable')


def test_shutdown_during_refresh_startup_never_leaves_provider_work(monkeypatch):
    import threading
    entered = threading.Event()
    def starting(*a, cancel_event, **kw):
        entered.set()
        assert cancel_event.wait(2)
        raise budget.PublicDataUnavailable('SOURCE_CANCELLED')
    monkeypatch.setattr(budget, '_run_process', starting)
    with pytest.raises(budget.PublicDataUnavailable, match='SOURCE_REFRESH_PENDING'):
        budget.run('overview', timeout=.01)
    assert entered.is_set()
    budget.shutdown()
    assert not budget._OVERVIEW_THREAD.is_alive()
    assert budget._OVERVIEW_FLIGHT.exception().code == 'SOURCE_CANCELLED'


def test_refresh_crossing_session_is_explicitly_stale_not_relabelled(monkeypatch):
    session = ['2026-10-23']
    monkeypatch.setattr(market.trade_calendar, 'observation_trade_date_at', lambda _: session[0])
    def refresh(*a, **kw):
        session[0] = '2026-10-26'
        return qualified_overview()
    monkeypatch.setattr(budget, '_run_process', refresh)
    result = budget.run('overview')
    assert result['is_stale'] is True
    assert result['reason_code'] == 'SOURCE_SESSION_CHANGED'
    assert result['sentiment']['status'] == 'partial'
    assert result['sentiment']['date'] == '2026-10-23'
    assert not market.overview_cacheable(result, '2026-10-26')


def test_failed_refresh_releases_supervisor_for_retry(monkeypatch):
    monkeypatch.setattr(market.trade_calendar, 'observation_trade_date_at', lambda _: '2026-10-23')
    calls = []
    def refresh(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise budget.PublicDataUnavailable('SOURCE_UNAVAILABLE')
        return qualified_overview()
    monkeypatch.setattr(budget, '_run_process', refresh)
    with pytest.raises(budget.PublicDataUnavailable, match='SOURCE_UNAVAILABLE'):
        budget.run('overview')
    assert budget.run('overview')['sentiment']['status'] == 'partial'
    assert len(calls) == 2


@pytest.mark.parametrize('route', ['fund_flow', 'hot_concepts'])
def test_remaining_direct_capital_routes_do_not_cache_failure(monkeypatch, route):
    import app
    import requests
    monkeypatch.setattr(app, '_DC_CACHE', app.TTLCache())
    calls = []
    def fail(*a, **kw):
        calls.append(1)
        raise TimeoutError('private detail')
    monkeypatch.setattr(astock, 'em_get', fail)
    monkeypatch.setattr(requests, 'post', fail)
    for _ in range(2):
        with pytest.raises(app.HTTPException) as caught:
            getattr(app, route)('600000')
        assert caught.value.status_code == 502
        assert 'private' not in caught.value.detail
    assert len(calls) == 2


def test_public_overview_read_only_never_starts_refresh(monkeypatch):
    monkeypatch.setattr(budget, '_run_process', lambda *a, **kw: pytest.fail('read only cannot start source work'))
    with market.push2_guard.read_only(), pytest.raises(budget.PublicDataUnavailable, match='SOURCE_READ_ONLY'):
        budget.run('overview')
    assert budget._OVERVIEW_FLIGHT is None
