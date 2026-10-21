from concurrent.futures import ThreadPoolExecutor
import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import research_event_review as review
import research_event_calendar_router as router
import evidence_thesis_service as svc
import evidence_thesis_store as store
from test_evidence_thesis_service import _make_thesis_payload, _make_evidence_payload


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / 'evidence.db'
    thesis = svc.create_thesis(path, _make_thesis_payload())
    evidence = svc.create_evidence(path, _make_evidence_payload())
    tid = thesis['thesis']['id']
    monkeypatch.setattr(review.campaign_service, 'get_campaign', lambda _: {'security_code': '600519', 'status': 'ACTIVE'})
    monkeypatch.setattr(review.campaign_service, 'get_campaign_thesis_binding', lambda _: {'thesis_id': tid})
    monkeypatch.setenv('VIBE_RESEARCH_EVIDENCE_THESIS_DB', str(path))
    event = dict(event_id='event-1', event_type='PERIODIC_REPORT', security_code='600519',
        event_date='2026-10-19', state='CONFIRMED', title='Report', details={'actual_date': '2026-10-19'},
        source='verified-provider', source_record_identity='period-1', date_semantics='DATE_ONLY')
    payload = dict(campaign_id='campaign-a', thesis_id=tid, expected_thesis_revision=1,
        event_id=event['event_id'], event_type=event['event_type'], expected_observation_hash=review.fingerprint(event),
        observation_receipt=review.issue_receipt(event), expectation='Revenue grows')
    judgment = dict(expected_version=1, outcome='support', reason='Reviewed the report',
        evidence=[{'id': evidence['id'], 'edit_token': evidence['edit_token']}])
    return path, thesis, evidence, event, payload, judgment


def test_bind_judge_duplicate_and_readonly_refresh(setup, monkeypatch):
    path, thesis, evidence, event, payload, judgment = setup
    monkeypatch.setattr(review.calendar, 'build_research_event_calendar', lambda **_: pytest.fail('write must not request provider'))
    before = svc.get_thesis(path, thesis['thesis']['id'])
    first = review.bind(payload, path)
    assert first['status'] == 'review_required'
    assert review.bind(payload, path) == first
    original = store.read_transaction(path, lambda c: c.execute('SELECT payload FROM event_research_reviews').fetchone()[0])
    final = review.judge(first['id'], judgment, path)
    assert final['status'] == 'support'
    assert review.bind(payload, path) == final
    assert review.context('campaign-a', path)['reviews'] == [final]
    assert store.read_transaction(path, lambda c: c.execute('SELECT payload FROM event_research_reviews').fetchone()[0]) == original
    assert svc.get_thesis(path, thesis['thesis']['id']) == before
    with pytest.raises(review.ReviewConflict): review.judge(first['id'], judgment, path)


@pytest.mark.parametrize('field,value', [('thesis_id','forged'), ('expected_thesis_revision',2), ('event_id','forged'), ('expected_observation_hash','forged'), ('observation_receipt','forged')])
def test_forged_or_stale_binding_rejected(setup, field, value):
    path, _, _, _, payload, _ = setup
    with pytest.raises(review.ReviewConflict): review.bind({**payload, field:value}, path)
    assert review.list_reviews('campaign-a', path) == []


def test_wrong_subject_receipt_and_evidence(setup):
    path, _, _, event, payload, judgment = setup
    wrong = {**event, 'security_code':'000001'}
    with pytest.raises(review.ReviewConflict):
        review.bind({**payload, 'observation_receipt': review.issue_receipt(wrong), 'expected_observation_hash':review.fingerprint(wrong)}, path)
    first = review.bind(payload, path)
    evidence = svc.create_evidence(path, _make_evidence_payload(subject_id='000001'))
    with pytest.raises(review.ReviewConflict):
        review.judge(first['id'], {**judgment, 'evidence':[{'id':evidence['id'], 'edit_token':evidence['edit_token']}]}, path)


def test_changed_observation_new_review_preserves_original(setup):
    path, _, _, event, payload, judgment = setup
    first = review.bind(payload, path)
    final = review.judge(first['id'], judgment, path)
    changed = {**event, 'details': {'actual_date':'2026-10-20'}}
    second = review.bind({**payload, 'expected_observation_hash':review.fingerprint(changed), 'observation_receipt':review.issue_receipt(changed)}, path)
    assert second['id'] != first['id'] and second['status'] == 'review_required'
    assert review.list_reviews('campaign-a', path) == [second, final]


@pytest.mark.parametrize('mode',['expired','restart','tamper'])
def test_receipt_fail_closed(setup, monkeypatch, mode):
    path, _, _, _, payload, _ = setup
    if mode == 'expired': monkeypatch.setattr(review.time, 'time', lambda: 99999999999)
    elif mode == 'restart': monkeypatch.setattr(review, '_RECEIPT_KEY', b'another-process-key')
    else: payload['observation_receipt'] = 'x' + payload['observation_receipt']
    with pytest.raises(review.ReviewConflict): review.bind(payload, path)


def test_read_does_not_initialize_extension(setup):
    path, _, _, _, _, _ = setup
    before = path.read_bytes()
    assert review.list_reviews('campaign-a', path) == []
    assert not store.read_transaction(path, lambda c: store._table_exists(c,'event_research_reviews'))
    assert path.read_bytes() == before


def test_stale_evidence_and_concurrent_judgment(setup):
    path, _, evidence, _, payload, judgment = setup
    row = review.bind(payload, path)
    stale = copy.deepcopy(judgment); stale['evidence'][0]['edit_token'] = 'forged'
    with pytest.raises(review.ReviewConflict): review.judge(row['id'], stale, path)
    def run(_):
        try: return review.judge(row['id'], judgment, path)['status']
        except review.ReviewConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(run, range(2)))
    assert sorted(results) == ['conflict','support']
    assert store.read_transaction(path, lambda c:c.execute('SELECT count(*) FROM event_research_judgments').fetchone()[0]) == 1


def test_api_reachable_strict_revision_and_safe_errors(setup):
    _, _, _, _, payload, judgment = setup
    app = FastAPI(); app.include_router(router.router)
    client = TestClient(app)
    assert client.get('/api/research-events/reviews/context/campaign-a').status_code == 200
    assert client.post('/api/research-events/reviews', json={**payload,'expected_thesis_revision':True}).status_code == 422
    response = client.post('/api/research-events/reviews',json=payload)
    assert response.status_code == 200
    row = response.json()['data']
    assert client.post(f"/api/research-events/reviews/{row['id']}/judgment",json=judgment).status_code == 200
    assert client.post(f"/api/research-events/reviews/{row['id']}/judgment",json=judgment).status_code == 409


def test_frozen_thesis_and_evidence_history_unchanged(setup):
    path, thesis, evidence, _, payload, judgment = setup
    tid = thesis['thesis']['id']
    svc.begin_formalization(path, tid)
    data = {**_make_thesis_payload(), 'status':'active', 'core_claims':['a','b','c'], 'strategy':'SWING',
        'expected_horizon':{'unit':'TRADING_DAY','min':5,'max':20,'anchor':'FREEZE_AT'}}
    svc.update_thesis(path, tid, data, expected_revision=1)
    svc.confirm_formalization(path, tid, expected_revision=2)
    svc.freeze_formalization(path, tid, expected_revision=2)
    frozen = svc.get_thesis(path, tid)
    payload['expected_thesis_revision'] = frozen['thesis']['current_revision']
    row = review.bind(payload,path)
    done = review.judge(row['id'],judgment,path)
    changed = {**_make_evidence_payload(), 'claim':'later correction', 'expected_edit_token':evidence['edit_token']}
    svc.update_evidence(path,evidence['id'],changed)
    assert svc.get_thesis(path, tid) == frozen
    assert review.list_reviews('campaign-a',path)[0] == done
    assert done['judgment']['evidence'][0]['claim'] != 'later correction'


def test_duplicate_bind_concurrent(setup):
    path, _, _, _, payload, _ = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: review.bind(payload,path), range(2)))
    assert rows[0] == rows[1]
    assert len(review.list_reviews('campaign-a',path)) == 1


def test_calendar_receipt_issued_without_ledger_write(setup, monkeypatch):
    path, _, _, event, payload, _ = setup
    monkeypatch.setattr(router.service, 'build_research_event_calendar', lambda **_: {'events':[dict(event)]})
    app = FastAPI(); app.include_router(router.router)
    client = TestClient(app)
    before = path.read_bytes()
    response = client.get('/api/research-events')
    assert response.status_code == 200
    observed = response.json()['data']['events'][0]
    assert review.verify_receipt(observed['observation_receipt']) == review.observation(event)
    assert observed['observation_hash'] == review.fingerprint(event)
    assert not store.read_transaction(path, lambda c: store._table_exists(c, 'event_research_reviews'))
    assert path.read_bytes() == before


@pytest.mark.parametrize('status', ['CLOSED', 'REJECTED', 'EXPIRED'])
def test_terminal_campaign_history_survives_without_active_universe(setup, monkeypatch, status):
    path, _, _, _, payload, judgment = setup
    saved = review.bind(payload, path)
    final = review.judge(saved['id'], judgment, path)
    monkeypatch.setattr(review.campaign_service, 'get_campaign', lambda _: {'security_code': '600519', 'status': status})
    monkeypatch.setattr(review.calendar, 'build_research_event_calendar', lambda **_: pytest.fail('history must not scan'))
    before = path.read_bytes()
    assert review.history(security_code='600519', db_path=path)['items'] == [final]
    assert review.history(security_code='000001', db_path=path)['items'] == []
    assert path.read_bytes() == before
    with pytest.raises(review.ReviewConflict):
        review.bind(payload, path)
    assert review.campaign_service.get_campaign('campaign-a')['status'] == status


def test_history_pagination_scope_and_insert_stability(setup, monkeypatch):
    path, _, _, _, payload, _ = setup
    ids = [review.bind({**payload, 'campaign_id': f'campaign-{i}'}, path)['id'] for i in range(5)]
    first = review.history(security_code='600519', limit=2, db_path=path)
    assert [r['id'] for r in first['items']] == ids[-1:-3:-1]
    review.bind({**payload, 'campaign_id': 'new-campaign'}, path)
    rest, cursor = [], first['next_cursor']
    while cursor:
        page = review.history(security_code='600519', limit=2, cursor=cursor, db_path=path)
        rest.extend(r['id'] for r in page['items']); cursor = page['next_cursor']
    assert rest == ids[-3::-1]
    assert len(review.history(campaign_id='campaign-0', db_path=path)['items']) == 1
    with pytest.raises(ValueError):
        review.history(security_code='000001', cursor=first['next_cursor'], db_path=path)
    monkeypatch.setattr(review.campaign_service, 'get_campaign', lambda _: pytest.fail('archive must not require live Campaign'))
    app = FastAPI(); app.include_router(router.router)
    response = TestClient(app).get('/api/research-events/reviews/history?security_code=600519&limit=2')
    assert response.status_code == 200 and len(response.json()['data']['items']) == 2


def test_history_missing_database_is_readonly(tmp_path):
    path = tmp_path / 'missing.db'
    assert review.history(db_path=path) == {'items': [], 'next_cursor': None}
    assert not path.exists()


def test_pending_terminal_review_can_use_existing_judgment_rules(setup, monkeypatch):
    path, _, _, _, payload, judgment = setup
    pending = review.bind(payload, path)
    monkeypatch.setattr(review.campaign_service, 'get_campaign', lambda _: {'security_code': '600519', 'status': 'CLOSED'})
    assert review.history(db_path=path)['items'] == [pending]
    assert review.context('campaign-a', path)['reviews'] == [pending]
    assert review.judge(pending['id'], judgment, path)['status'] == 'support'
    assert review.campaign_service.get_campaign('campaign-a')['status'] == 'CLOSED'
