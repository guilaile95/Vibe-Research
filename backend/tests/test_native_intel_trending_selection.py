"""Connection reuse optimization must preserve the complete returned trending contract."""
from copy import deepcopy

import pytest

import native_intel_service as service
import native_intel_store as store


@pytest.mark.parametrize('top_n', [0, 1, 20, 100, 200])
def test_full_cohort_rank_history_and_stable_selection_preserved(monkeypatch, top_n):
    # Deliberate tied ordering, previous-title matches, mixed RSS/rank sources.
    rows = [dict(item_id=i, title_key=f'title-{i % 9}', last_seen_at=f'2026-10-24T10:{i % 4:02}:00Z',
                 observation_count=i % 6, has_real_rank=i % 3 != 0)
            for i in range(140, 0, -1)]
    previous = [dict(title_key='title-1'), dict(title_key='title-3')]
    original = deepcopy(rows)
    monkeypatch.setattr(service, 'data_status', lambda _: {'status': 'partial', 'error': None})
    monkeypatch.setattr(store, 'query_items', lambda *a, **k: (previous if k.get('until') else rows, 140))
    monkeypatch.setattr(service, '_entity_trend_rows', lambda *a: [])
    monkeypatch.setattr(store, 'any_source_has_real_rank', lambda _: True)
    loaded = []
    def state(item_id, _path):
        loaded.append(item_id)
        return dict(current_rank=item_id, previous_rank=item_id + 1, rank_delta=1,
                    current_state='UNKNOWN', observations=[{'rank': item_id + 1}, {'rank': item_id}])
    monkeypatch.setattr(store, 'get_item_rank_states', lambda ids, path: {i: state(i, path) for i in ids})
    result = service.trending('unused', top_n=top_n)
    expected = sorted(rows, key=lambda r: (-int(r['title_key'] not in {'title-1', 'title-3'}),
                     -r['observation_count'], r['last_seen_at']))[:max(1, min(top_n, 100))]
    assert [r['item_id'] for r in result['items']] == [r['item_id'] for r in expected]
    assert loaded == [r['item_id'] for r in rows if r['has_real_rank']]
    assert result['item_count'] == 140
    assert result['status'] == 'partial'
    assert rows == original
    for row in result['items']:
        if row['has_real_rank']:
            assert row['current_state'] == 'UNKNOWN'
            assert len(row['rank_history']) == 2
        else:
            assert row['rank'] is None and row['rank_history'] == []


def test_selected_rank_error_still_propagates(monkeypatch):
    monkeypatch.setattr(service, 'data_status', lambda _: {'status': 'normal', 'error': None})
    monkeypatch.setattr(store, 'query_items', lambda *a, **k: ([], 0) if k.get('until') else
                        ([dict(item_id=1, title_key='one', last_seen_at='2026-10-24', observation_count=1, has_real_rank=True)], 1))
    monkeypatch.setattr(service, '_entity_trend_rows', lambda *a: [])
    monkeypatch.setattr(store, 'any_source_has_real_rank', lambda _: True)
    def failure(*a):
        raise store.NativeIntelStoreError()
    monkeypatch.setattr(store, 'get_item_rank_states', failure)
    with pytest.raises(store.NativeIntelStoreError):
        service.trending('unused')


def test_status_reuses_one_operation_local_config_snapshot(tmp_path, monkeypatch):
    path = tmp_path / 'intel.sqlite3'
    original_config = store.get_native_intel_config
    original_directory = store.get_security_directory_size
    calls = {'config': 0, 'directory': 0}
    def config(target):
        calls['config'] += 1
        return original_config(target)
    def directory(target):
        calls['directory'] += 1
        return original_directory(target)
    monkeypatch.setattr(store, 'get_native_intel_config', config)
    monkeypatch.setattr(store, 'get_security_directory_size', directory)
    result = service.status(str(path))
    # count_freshness_excluded_rss_items internally reads config once as before;
    # status's display/proxy/freshness fields share its own consistent snapshot.
    assert calls == {'config': 2, 'directory': 1}
    assert result['store']['item_count'] == 0
    assert result['directory']['size'] == 0
    assert result['status'] == service.STATUS_UNAVAILABLE
    assert result['proxies']['crawler_proxy']['url'] == ''


def _rank_fixture(path):
    stamp = store.utc_now_iso()
    store.upsert_sources([dict(source_id='hotlist-synthetic', name='Synthetic', hint='a-share',
                               url='https://example.invalid', source_type='hotlist', has_real_rank=True)], path)
    store.start_run('test-run', 'test', 1, path, started_at=stamp)
    ids = []
    for i in range(2):
        item_id, _ = store.upsert_observation('test-run', 'hotlist-synthetic',
            dict(item_key=f'item-{i}', title=f'Item {i}', title_key=f'item-{i}', rank=i+1),
            observed_at=stamp, has_real_rank=True, db_path=path)
        ids.append(item_id)
    store.record_source_run('test-run', 'hotlist-synthetic', status=store.SOURCE_RUN_OK, item_count=2, db_path=path)
    store.finish_run('test-run', status=store.RUN_STATUS_OK, source_ok=1, source_failed=0, item_seen=2, item_new=2, db_path=path)
    return ids


@pytest.mark.parametrize('selected', [True, False])
def test_selected_and_unselected_malformed_rank_is_not_suppressed(tmp_path, selected):
    import sqlite3
    path = tmp_path / 'intel.sqlite3'
    ids = _rank_fixture(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE intel_observations SET rank='malformed' WHERE item_id=?", (ids[-1] if selected else ids[0],))
    with pytest.raises(ValueError):
        service.trending(str(path), top_n=1)


def test_database_corruption_is_not_masked_as_empty(tmp_path):
    path = tmp_path / 'intel.sqlite3'
    path.write_bytes(b'not a SQLite database')
    with pytest.raises(store.NativeIntelStoreError):
        service.trending(str(path))


@pytest.mark.parametrize('mode', ['normal', 'failed', 'disabled', 'off_list', 'stale', 're_enabled', 'rss'])
def test_batch_rank_derivation_equals_individual_read(tmp_path, mode):
    from datetime import datetime, timezone
    import sqlite3
    path = tmp_path / 'intel.sqlite3'
    ids = _rank_fixture(path)
    now = datetime.now(timezone.utc)
    with sqlite3.connect(path) as conn:
        if mode == 'failed':
            conn.execute("UPDATE intel_source_runs SET status='failed'")
        elif mode == 'disabled':
            conn.execute('UPDATE intel_sources SET enabled=0')
        elif mode == 'off_list':
            conn.execute("INSERT INTO intel_fetch_runs(run_id,started_at,status,trigger) VALUES ('new',?,'ok','test')", (now.isoformat(),))
            conn.execute("INSERT INTO intel_source_runs(run_id,source_id,status,item_count) VALUES ('new','hotlist-synthetic','empty',0)")
        elif mode == 'stale':
            conn.execute("UPDATE intel_fetch_runs SET started_at='2000-01-01T00:00:00Z'")
        elif mode == 're_enabled':
            conn.execute("UPDATE intel_sources SET re_enabled_after_run_id='test-run'")
        elif mode == 'rss':
            conn.execute('UPDATE intel_sources SET has_real_rank=0')
    for include_history in (True, False):
        expected = {i: store.get_item_rank_state(i, path, now=now, include_history=include_history) for i in ids}
        assert store.get_item_rank_states(ids, path, now=now, include_history=include_history) == expected


def test_unselected_naive_rank_timestamp_still_fails(tmp_path):
    import sqlite3
    path = tmp_path / 'intel.sqlite3'
    _rank_fixture(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE intel_fetch_runs SET started_at='2026-10-24T10:00:00'")
    with pytest.raises(TypeError):
        service.trending(str(path), top_n=1)


def test_rank_batch_bound_and_empty_do_not_initialize(tmp_path):
    path = tmp_path / 'intel.sqlite3'
    assert store.get_item_rank_states([], path) == {}
    assert not path.exists()
    with pytest.raises(ValueError, match='500'):
        store.get_item_rank_states(list(range(501)), path)
    assert not path.exists()
