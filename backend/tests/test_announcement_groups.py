from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import announcement_groups as groups
import announcement_groups_router as router
import evidence_thesis_service as svc
import evidence_thesis_store as store
from test_evidence_thesis_service import _make_evidence_payload

@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / 'evidence.db'
    monkeypatch.setenv('VIBE_RESEARCH_EVIDENCE_THESIS_DB', str(path))
    anchor = svc.create_evidence(path, _make_evidence_payload(evidence_type='announcement'))
    report = svc.create_evidence(path, _make_evidence_payload(evidence_type='news'))
    def member(e, role='unknown', relates_to=None):
        return dict(evidence_id=e['id'], expected_edit_token=e['edit_token'], role=role, relates_to=relates_to)
    payload = dict(request_id='first', group_id=None, anchor_id=anchor['id'], period='FY2025 result announcement', expected_revision=0,
                   members=[member(anchor, 'original'), member(report, 'commentary')])
    return path, anchor, report, payload, member

def test_manual_snapshots_idempotency_and_no_evidence_mutation(setup):
    path, anchor, report, payload, member = setup
    original = [svc.get_evidence(path, e['id']) for e in (anchor,report)]
    before = path.read_bytes()
    files_before = {p.name for p in path.parent.iterdir()}
    assert groups.context(anchor['id'],path)['groups'] == []
    assert before == path.read_bytes()
    assert files_before == {p.name for p in path.parent.iterdir()}
    assert not store.read_transaction(path, lambda c: store._table_exists(c,groups.TABLE))
    first = groups.save(payload,path)
    assert groups.save(payload,path) == first
    assert first['relationship_basis'] == 'USER_DECLARED_UNVERIFIED'
    assert first['strict_asof_eligible'] is False
    assert [m['evidence_snapshot'] for m in first['members']] == original
    assert [svc.get_evidence(path,e['id']) for e in (anchor,report)] == original
    ctx = groups.context(report['id'],path)
    assert len(ctx['history']) == 1
    assert ctx['ownership_change']['status'] == 'NOT_IMPLEMENTED_PREREQUISITE_MISSING'
    assert ctx['automatic_grouping'] == 'UNAVAILABLE_NO_VERIFIED_DOCUMENT_ID'
    with pytest.raises(groups.Conflict): groups.save({**payload,'period':'FY2026'},path)

def test_missing_wrong_subject_duplicate_and_no_title_merges(setup):
    path, anchor, report, payload, member = setup
    same_title_other_period = svc.create_evidence(path,_make_evidence_payload(evidence_type='announcement'))
    assert groups.context(anchor['id'],path)['groups'] == []
    wrong = svc.create_evidence(path,_make_evidence_payload(subject_id='000001'))
    for members in ([member(anchor),member(wrong)], [member(anchor),{**member(report),'evidence_id':'missing'}], [member(anchor),member(anchor)]):
        with pytest.raises(ValueError): groups.save({**payload,'members':members},path)
    first = groups.save(payload,path)
    assert same_title_other_period['id'] not in [m['evidence_id'] for m in first['members']]
    assert groups.context(same_title_other_period['id'],path)['groups'] == []

def test_overlap_and_concurrent_cas(setup):
    path, anchor, report, payload, member = setup
    first = groups.save(payload,path)
    another = svc.create_evidence(path,_make_evidence_payload(evidence_type='announcement'))
    with pytest.raises(groups.Conflict):
        groups.save({**payload,'request_id':'overlap','anchor_id':another['id'],'members':[member(another),member(report)]},path)
    update = {**payload,'group_id':first['group_id'],'expected_revision':1}
    def run(i):
        try: return groups.save({**update,'request_id':f'race-{i}'},path)
        except groups.Conflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run,range(2)))
    assert sum(r == 'conflict' for r in results) == 1
    assert len(groups.context(anchor['id'],path)['history']) == 2

def test_corrections_retained_revisions_cycles_and_stale_tokens(setup):
    path, anchor, report, payload, member = setup
    first = groups.save(payload,path)
    correction = svc.create_evidence(path,_make_evidence_payload(evidence_type='announcement',claim='Correction'))
    update = {**payload,'request_id':'corrected','group_id':first['group_id'],'expected_revision':1,
              'members':payload['members']+[member(correction,'correction',anchor['id'])]}
    second = groups.save(update,path)
    ctx = groups.context(anchor['id'],path)
    assert ctx['history'] == [first,second]
    assert len(second['members']) == 3
    assert second['members'][-1]['relates_to'] == anchor['id']
    assert ctx['history'][0]['members'] == first['members']
    for changes in ({'period':'FY2026'}, {'members':[payload['members'][0],member(correction)]},
                    {'members':[dict(m,expected_edit_token='stale') for m in update['members']]}):
        with pytest.raises(groups.Conflict): groups.save({**update,'request_id':'bad','expected_revision':2,**changes},path)
    cycle = [member(anchor,'amendment',report['id']),member(report,'correction',anchor['id'])]
    with pytest.raises(ValueError): groups.save({**payload,'request_id':'cycle','members':cycle},path)
    with pytest.raises(ValueError): groups.save({**payload,'request_id':'missing-target','members':[member(anchor),member(report,'correction')]},path)

def test_api_schema_errors_and_get_is_readonly(setup):
    path, anchor, report, payload, member = setup
    app = FastAPI(); app.include_router(router.router)
    client = TestClient(app)
    assert client.get('/api/announcement-groups/context/'+anchor['id']).status_code == 200
    assert client.post('/api/announcement-groups',json={**payload,'provenance':'VERIFIED'}).status_code == 422
    assert client.post('/api/announcement-groups',json=payload).status_code == 200
    assert client.post('/api/announcement-groups',json=payload).status_code == 200
    assert client.post('/api/announcement-groups',json={**payload,'period':'different'}).status_code == 409
    assert client.get('/api/announcement-groups/context/missing').status_code == 422


def _bury_members(path):
    def write(conn):
        conn.execute("UPDATE evidence_records SET created_at='2020-01-01T00:00:00+00:00'")
        for i in range(205):
            store._insert_evidence(conn, {**_make_evidence_payload(), 'id': store.new_id(),
                'created_at': f'2026-01-01T00:00:00.{i:06d}+00:00', 'updated_at': '2026-01-01T00:00:00+00:00'})
    store.write_transaction(path, write)


@pytest.mark.parametrize('already_grouped', [False, True])
def test_old_anchor_and_members_outside_candidates_use_current_tokens(setup, already_grouped):
    path, anchor, report, payload, member = setup
    first = groups.save(payload, path) if already_grouped else None
    _bury_members(path)
    changed = svc.update_evidence(path, anchor['id'], {**_make_evidence_payload(evidence_type='announcement'),
        'claim': 'Updated current anchor', 'expected_edit_token': svc.get_evidence(path, anchor['id'])['edit_token']})
    ctx = groups.context(anchor['id'], path)
    assert len(ctx['candidates']) == 200 and ctx['has_more']
    assert anchor['id'] not in {e['id'] for e in ctx['candidates']}
    current = {e['id']: e for e in ctx['current_members']}
    assert current[anchor['id']]['claim'] == 'Updated current anchor'
    assert not ctx['member_conflicts']
    members = [dict(m, expected_edit_token=current[m['evidence_id']]['edit_token']) for m in payload['members']] if first else [member(current[anchor['id']], 'original')]
    update = {**payload, 'request_id': 'append-old', 'group_id': first['group_id'] if first else None,
        'expected_revision': 1 if first else 0, 'members': members + [member(ctx['candidates'][0])]}
    saved = groups.save(update, path)
    assert saved['revision'] == (2 if first else 1)
    assert groups.save(update, path) == saved
    if first:
        assert ctx['history'][0]['members'][0]['evidence_snapshot']['claim'] != 'Updated current anchor'
    # A subsequent edit must still invalidate the freshly loaded token.
    stale = {**update, 'request_id': 'stale', 'group_id': saved['group_id'], 'expected_revision': saved['revision']}
    svc.update_evidence(path, anchor['id'], {**_make_evidence_payload(evidence_type='announcement'),
        'claim': 'Concurrent edit', 'expected_edit_token': current[anchor['id']]['edit_token']})
    with pytest.raises(groups.Conflict): groups.save(stale, path)


@pytest.mark.parametrize('change', ['deleted', 'subject'])
def test_missing_or_changed_existing_member_is_explicit_conflict(setup, change):
    path, anchor, report, payload, member = setup
    groups.save(payload, path)
    def alter(conn):
        if change == 'deleted': conn.execute('UPDATE evidence_records SET deleted=1 WHERE id=?', (report['id'],))
        else: conn.execute("UPDATE evidence_records SET subject_id='000001' WHERE id=?", (report['id'],))
    store.write_transaction(path, alter)
    ctx = groups.context(anchor['id'], path)
    assert [c['evidence_id'] for c in ctx['member_conflicts']] == [report['id']]
    assert len(ctx['groups'][0]['members']) == 2  # Never silently prune history.


def test_kline_browser_empty_group_fixture_matches_real_service(tmp_path, monkeypatch):
    """Prevent a successful-but-malformed generic {} fixture from masking crashes."""
    import json
    from pathlib import Path
    golden = json.loads((Path(__file__).parents[2] / 'frontend/tests/e2e/kline-announcement-context.golden.json').read_text(encoding='utf-8'))
    monkeypatch.setattr(store, 'new_id', lambda: '000001-exact')
    monkeypatch.setattr(svc, '_utc_now_iso', lambda: '2026-07-24T00:00:00Z')
    db = tmp_path / 'synthetic-evidence.db'
    record = svc.create_evidence(db, dict(subject_type='stock', subject_id='000001', evidence_type='report',
        claim='Synthetic evidence only', source_title='合成证据 000001-exact', source_date='2026-07-20',
        source_url=None, accessed_at='2026-07-24T00:00:00Z', classification='fact', confidence='high'))
    assert groups.context(record['id'], db) == golden
