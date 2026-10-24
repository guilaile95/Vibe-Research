"""One-operation snapshot reuse must not turn into persistent eligibility caching."""
from __future__ import annotations

import hashlib
import sqlite3

import pytest

import myreports_fulltext as ft


@pytest.fixture
def catalog(tmp_path):
    text = b'semiconductor evidence for a synthetic report'
    sha = hashlib.sha256(text).hexdigest()
    (tmp_path / 'selected.txt').write_bytes(text)
    report = {'id': 'selected', 'ext': '.txt', 'file_sha256': sha, 'title': 'Synthetic'}
    conn = ft._connect_write(tmp_path)
    conn.execute('INSERT INTO report_text_index VALUES (?,?,?,?,?,?)',
                 ('selected', sha, ft.STATUS_SEARCHABLE, '2026-10-24T00:00:00Z', None, ''))
    conn.execute('INSERT INTO report_text_chunks VALUES (?,?,?)', ('selected', 1, text.decode()))
    conn.close()
    return tmp_path, report


def search(catalog, query='semiconductor'):
    directory, report = catalog
    return ft.search(directory, [report], query, report_ids=['selected'])


def track_connections(monkeypatch):
    original = ft._connect_readonly
    connections = []
    def open_tracked(directory):
        conn = original(directory)
        connections.append(conn)
        return conn
    monkeypatch.setattr(ft, '_connect_readonly', open_tracked)
    return connections


def test_one_image_for_eligibility_and_chunks_but_new_image_next_query(catalog, monkeypatch):
    connections = track_connections(monkeypatch)
    first = search(catalog)
    assert len(first) == 1
    assert len(connections) == 1 and connections[0].closed
    directory, _ = catalog
    with sqlite3.connect(ft._path(directory)) as writer:
        writer.execute('UPDATE report_text_chunks SET text=?', ('semiconductor corrected text',))
    second = search(catalog)
    assert len(connections) == 2 and connections[1].closed
    assert second[0]['chunk_sha256'] != first[0]['chunk_sha256']
    assert second[0]['snippet'] == 'semiconductor corrected text'


@pytest.mark.parametrize('case', ['source_changed', 'source_removed', 'not_searchable', 'no_match', 'query_error'])
def test_early_returns_and_query_error_close_snapshot(catalog, monkeypatch, case):
    directory, _ = catalog
    if case == 'source_changed':
        (directory / 'selected.txt').write_text('new source')
    elif case == 'source_removed':
        (directory / 'selected.txt').unlink()
    elif case == 'not_searchable':
        with sqlite3.connect(ft._path(directory)) as writer:
            writer.execute('UPDATE report_text_index SET status=?', (ft.STATUS_NOT_INDEXED,))
    connections = track_connections(monkeypatch)
    if case == 'query_error':
        def fail_terms(*args, **kwargs):
            raise ValueError('synthetic parser failure')
        monkeypatch.setattr(ft, '_search_terms', fail_terms)
        with pytest.raises(ValueError):
            search(catalog)
    else:
        assert search(catalog, 'unmatched' if case == 'no_match' else 'semiconductor') == []
    assert len(connections) == 1 and connections[0].closed


@pytest.mark.parametrize('empty_result', [False, True])
def test_changed_index_during_source_verification_fails_closed(catalog, monkeypatch, empty_result):
    directory, _ = catalog
    original = ft._source_sha256
    def source_hash_then_mutate(path):
        sha = original(path)
        with sqlite3.connect(ft._path(directory)) as writer:
            writer.execute('UPDATE report_text_chunks SET text=?', ('semiconductor updated mid-read',))
        return '0' * 64 if empty_result else sha
    monkeypatch.setattr(ft, '_source_sha256', source_hash_then_mutate)
    connections = track_connections(monkeypatch)
    with pytest.raises(ft.ReportTextIndexCorruptedError):
        search(catalog)
    assert len(connections) == 1 and connections[0].closed


def test_public_status_map_still_rechecks_snapshot_after_source_verification(catalog, monkeypatch):
    directory, report = catalog
    original = ft._source_sha256
    def source_hash_then_mutate(path):
        sha = original(path)
        with sqlite3.connect(ft._path(directory)) as writer:
            writer.execute("UPDATE report_text_index SET indexed_at='changed'")
        return sha
    monkeypatch.setattr(ft, '_source_sha256', source_hash_then_mutate)
    with pytest.raises(ft.ReportTextIndexCorruptedError):
        ft.status_map(directory, [report], verify_source=True)


def test_missing_index_retains_sidecar_rejection(tmp_path):
    (tmp_path / (ft.INDEX_NAME + '-wal')).write_bytes(b'pending')
    with pytest.raises(ft.ReportTextIndexCorruptedError):
        ft.search(tmp_path, [{'id': 'selected', 'ext': '.txt'}], 'semiconductor', report_ids=['selected'])


def test_context_qualification_uses_one_new_image_and_preserves_supplied_objects(catalog, monkeypatch):
    directory, report = catalog
    hits = search(catalog)
    connections = track_connections(monkeypatch)
    statuses, current = ft.qualify_search_hits(directory, [report], hits)
    assert statuses['selected']['text_index_status'] == ft.STATUS_SEARCHABLE
    assert current == hits and current[0] is hits[0]
    assert len(connections) == 1 and connections[0].closed
    with sqlite3.connect(ft._path(directory)) as writer:
        writer.execute('UPDATE report_text_chunks SET text=?', ('semiconductor changed extraction',))
    _, current = ft.qualify_search_hits(directory, [report], hits)
    assert current == []
    assert len(connections) == 2 and connections[1].closed


def test_context_qualification_rejects_mid_operation_index_change(catalog, monkeypatch):
    directory, report = catalog
    hits = search(catalog)
    original = ft._current_search_hits_in_snapshot
    def verified_then_mutate(conn, hits):
        result = original(conn, hits)
        with sqlite3.connect(ft._path(directory)) as writer:
            writer.execute('UPDATE report_text_chunks SET text=?', ('semiconductor changed extraction',))
        return result
    monkeypatch.setattr(ft, '_current_search_hits_in_snapshot', verified_then_mutate)
    connections = track_connections(monkeypatch)
    with pytest.raises(ft.ReportTextIndexCorruptedError):
        ft.qualify_search_hits(directory, [report], hits)
    assert len(connections) == 1 and connections[0].closed
