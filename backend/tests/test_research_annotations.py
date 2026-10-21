"""Offline annotation persistence and boundaries; all writes confined to tmp_path."""
import copy
import json
from offline_testclient import offline_network
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import research_annotations as notes
import research_annotations_router as router

BAR = {'date': '2026-10-16', 'open': 10, 'high': 12, 'low': 9, 'close': 11, 'volume': 20}

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, offline_network):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)


@pytest.fixture
def client():
    app = FastAPI(); app.include_router(router.router)
    return TestClient(app)


def payload(**kwargs):
    return {'context': notes.snapshot_context('000001', [BAR]), 'date': BAR['date'], 'text': '<script>untrusted</script>', **kwargs}


def test_roundtrip_append_read_restart_and_no_formal_store(client, monkeypatch):
    a = client.post('/api/research-annotations', json=payload(price=0)).json()
    b = client.post('/api/research-annotations', json=payload(text='second')).json()
    assert a['id'] != b['id'] and a['text'] == '<script>untrusted</script>'
    path = notes.store.facts.resolve_db_path()
    before = path.read_bytes()
    monkeypatch.setattr(notes, '_SECRET', b'new process')
    response = client.get('/api/research-annotations?code=000001')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['records'] == [b, a]
    assert path.read_bytes() == before
    assert client.get('/api/research-annotations?code=000002').json()['records'] == []
    import evidence_thesis_service as svc
    assert not svc.resolve_db_path().exists()


@pytest.mark.parametrize('field,value', [('code', '000002'), ('bar_period', 'week'), ('snapshot_id', '0'*64), ('points', [['2026-10-18', '1','2','1','1',None]])])
def test_forged_context_rejected(client, field, value):
    body = payload(); body['context'][field] = value
    assert client.post('/api/research-annotations', json=body).status_code == 422
    assert not notes.store.facts.resolve_db_path().exists()


def test_restart_rejects_new_save_but_does_not_overwrite(client, monkeypatch):
    body = payload(); saved = client.post('/api/research-annotations', json=body).json()
    monkeypatch.setattr(notes, '_SECRET', b'restarted')
    assert client.post('/api/research-annotations', json=body).status_code == 422
    assert notes.records('000001') == [saved]


@pytest.mark.parametrize('changes', [{'date':'2026-10-17'}, {'date':'2026-02-30'}, {'text':' '*10}, {'text':'x'*2001}, {'price':'NaN'}, {'price':True}, {'link_kind':'thesis'}, {'extra':'unknown'}])
def test_invalid_inputs_never_write(client, changes):
    assert client.post('/api/research-annotations', json=payload(**changes)).status_code == 422
    assert not notes.store.facts.resolve_db_path().exists()


def test_nonfinite_rejected_before_storage():
    for n in [float('nan'), float('inf'), -float('inf')]:
        with pytest.raises(ValueError):
            notes.AnnotationInput.model_validate(payload(price=n))


def test_snapshot_identity_changes_with_values_subject_period_and_duplicates():
    a = notes.snapshot_context('000001', [BAR])
    assert a['snapshot_id'] == notes.snapshot_context('000001', [BAR, BAR])['snapshot_id']
    assert a['snapshot_id'] != notes.snapshot_context('000001', [{**BAR, 'volume':21}])['snapshot_id']
    assert a['snapshot_id'] != notes.snapshot_context('000002', [BAR])['snapshot_id']
    assert notes.snapshot_context('000001', [BAR, {**BAR, 'close':10}]) is None
    assert notes.snapshot_context('000001', [{**BAR,'date':'2026-02-30'}]) is None
    assert notes.snapshot_context('bad', [BAR]) is None


def test_links_verify_subject_capture_revision_and_never_mutate_formal(client):
    import evidence_thesis_service as svc
    import evidence_thesis_store as store
    path = svc.resolve_db_path(); store.initialize_store(path)
    thesis = svc.create_thesis(path, {'subject_type':'stock','subject_id':'000001','title':'t','summary':'s','core_claims':['c'],'catalysts':[],'risks':[],'invalidation_conditions':[],'change_summary':'created'})['thesis']
    foreign = svc.create_thesis(path, {'subject_type':'stock','subject_id':'000002','title':'other','summary':'s','core_claims':['c'],'catalysts':[],'risks':[],'invalidation_conditions':[],'change_summary':'created'})['thesis']
    before = svc.get_thesis(path, thesis['id'])
    result = client.post('/api/research-annotations', json=payload(link_kind='thesis',link_id=thesis['id']))
    assert result.status_code == 200, result.text
    assert result.json()['link_revision'] == str(before['thesis']['current_revision'])
    assert svc.get_thesis(path, thesis['id']) == before
    for identity in [foreign['id'], 'missing']:
        assert client.post('/api/research-annotations', json=payload(link_kind='thesis',link_id=identity)).status_code == 422


def test_corrupt_record_fails_closed_and_preserves_bytes(client):
    client.post('/api/research-annotations', json=payload())
    path = notes.store.facts.resolve_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE research_annotations SET payload='{}'")
    before = path.read_bytes()
    assert client.get('/api/research-annotations?code=000001').status_code == 422
    assert client.post('/api/research-annotations', json=payload()).status_code == 422
    assert path.read_bytes() == before


def test_no_edit_or_delete_surface(client):
    saved = client.post('/api/research-annotations', json=payload()).json()
    for method in ['put','patch','delete']:
        assert getattr(client,method)('/api/research-annotations/'+saved['id']).status_code in (404,405)
    assert notes.records('000001') == [saved]


def test_expired_context_rejected(client):
    body = payload()
    body['context']['expires_at'] = '2000-01-01T00:00:00+00:00'
    body['context']['token'] = notes._signature({k:v for k,v in body['context'].items() if k != 'token'})
    assert client.post('/api/research-annotations', json=body).status_code == 422


def test_evidence_link_verifies_same_stock_and_deleted(client):
    import evidence_thesis_service as svc
    import evidence_thesis_store as store
    path = svc.resolve_db_path(); store.initialize_store(path)
    evidence = svc.create_evidence(path, {'subject_type':'stock','subject_id':'000001','evidence_type':'research_note','claim':'manual','source_title':'fixture','source_date':'2026-10-16','accessed_at':'2026-10-19T00:00:00+00:00','classification':'inference','confidence':'low'})
    result = client.post('/api/research-annotations', json=payload(link_kind='evidence',link_id=evidence['id']))
    assert result.status_code == 200, result.text
    assert result.json()['link_revision'] == evidence['updated_at']
    before = svc.get_evidence(path,evidence['id'])
    assert before['claim'] == 'manual'
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE evidence_records SET deleted=1 WHERE id=?', (evidence['id'],))
    assert client.post('/api/research-annotations', json=payload(link_kind='evidence',link_id=evidence['id'])).status_code == 422


def test_kline_opt_in_envelope_preserves_array_and_uses_single_source_read(monkeypatch):
    import app as app_module
    calls = []
    def source(code, category, offset):
        calls.append((code, category, offset))
        return [copy.deepcopy(BAR)]
    monkeypatch.setattr(app_module.astock, 'kline', source)
    assert app_module.kline('000001',4,60,False) == {'data':[BAR]}
    enriched = app_module.kline('000001',4,60,True)
    assert enriched['data'] == [BAR]
    assert notes.verify_context(enriched['annotation_context'])['code'] == '000001'
    assert app_module.kline('000001',5,60,True)['annotation_context'] is None
    assert len(calls) == 3
