"""Offline RSS fetch -> response/cache -> AI grounding contracts."""
import io
import json
import socket

import pytest

import ai_tools
import app
import chat
import debate
import newsradar


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        raise AssertionError('No network allowed')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('VIBE_RESEARCH_NEWS_RADAR_CACHE', str(tmp_path / 'radar.json'))
    cfg = {'industries': [{'key': 'x', 'name': 'Synthetic', 'accent': 'blue'}],
           'sources': [{'hint': 'x', 'name': name, 'url': f'https://{name}.invalid'} for name in ['a', 'b']]}
    config = tmp_path / 'sources.json'
    config.write_text(json.dumps(cfg))
    monkeypatch.setattr(newsradar, 'SOURCES_FILE', str(config))


@pytest.mark.parametrize('outcomes,status,chat_status,succeeded', [
    (['item', 'fail'], 'partial', 'partial', 1),
    (['fail', 'fail'], 'unavailable', 'error', 0),
    (['empty', 'empty'], 'normal', 'empty', 2),
    (['item', 'empty'], 'normal', 'success', 2),
    (['empty', 'fail'], 'partial', 'error', 1),
])
def test_actual_fetch_cache_api_and_ai_preserve_source_outcome(monkeypatch, outcomes, status, chat_status, succeeded):
    calls = []
    def open_feed(request, **kwargs):
        host = request.full_url.split('//')[1].split('.')[0]
        calls.append(host)
        outcome = outcomes[['a', 'b'].index(host)]
        if outcome == 'fail':
            raise OSError('synthetic private error')
        item = '<item><title>Synthetic</title><link>https://example.invalid/item</link></item>' if outcome == 'item' else ''
        return io.BytesIO(f'<rss><channel>{item}</channel></rss>'.encode())
    monkeypatch.setattr(newsradar.urllib.request, 'urlopen', open_feed)
    result = app.radar_refresh()['data']
    assert result['status'] == status
    assert result['source_coverage'] == {
        'scope': 'cached_fetch_all_configured_sources', 'state': status,
        'expected_sources': 2, 'attempted_sources': 2,
        'succeeded_sources': succeeded, 'failed_sources': 2 - succeeded,
    }
    # Response metadata is additive, never written to the cache schema.
    cache_before = open(newsradar.get_cache_file(), 'rb').read()
    stored = json.loads(cache_before)
    assert 'status' not in stored and 'source_coverage' not in stored
    assert app.radar()['data'] == result
    payload = ai_tools.exec_tool('query_news_radar', {'track': 'Synthetic'})
    serialized, outcome, _ = chat._serialize_tool_result(payload)
    assert outcome == chat_status
    assert json.loads(serialized)['data']['source_coverage'] == result['source_coverage']
    assert payload['status'] == status
    section = debate._fetch_section(('query_news_radar', {}, 'Synthetic RSS', False, True), '000001')
    assert section['status'] == chat_status
    assert '筛选赛道' in payload['note']
    assert sorted(calls) == ['a', 'b']  # API read and AI projection never refresh.
    assert open(newsradar.get_cache_file(), 'rb').read() == cache_before


@pytest.mark.parametrize('stats', [{}, {'total_sources': 2}, {'total_sources': 2, 'failed_sources': None},
                                    {'total_sources': 2, 'failed_sources': -1},
                                    {'total_sources': 2, 'failed_sources': 3},
                                    {'total_sources': True, 'failed_sources': 0}])
def test_legacy_missing_or_invalid_counts_are_unknown_not_success(monkeypatch, stats):
    data = {'generated_at': '2026-10-11 12:00', 'stats': stats,
            'industries': [{'name': 'Synthetic', 'total': 2, 'items': []}]}
    monkeypatch.setattr(newsradar, 'get_radar', lambda **kw: data)
    result = ai_tools.exec_tool('query_news_radar', {})
    assert result['status'] == 'partial'
    assert result['source_coverage']['state'] == 'unknown'
    assert result['source_coverage']['succeeded_sources'] is None
    assert chat._serialize_tool_result(result)[1] == 'error'


def test_configured_but_unattempted_source_is_not_complete():
    data = {'generated_at': 'fixture', 'stats': {'total_sources': 3, 'failed_sources': 0},
            'industries': [{'total': 2, 'items': []}]}
    result = newsradar.with_source_coverage(data)
    assert result['status'] == 'partial'
    assert result['source_coverage']['expected_sources'] == 3
    assert result['source_coverage']['attempted_sources'] == 2
    assert result['source_coverage']['succeeded_sources'] == 2
    assert 'status' not in data


def test_uninitialized_and_compacted_results_do_not_claim_success(monkeypatch):
    assert newsradar.get_radar()['source_coverage']['state'] == 'unknown'
    data = {'generated_at': 'fixture', 'stats': {'total_sources': 2, 'failed_sources': 1},
            'industries': [{'name': 'Synthetic', 'total': 2, 'items': [
                {'title': '长' * 2000, 'time': '—', 'source': 'Synthetic'} for _ in range(10)]}]}
    monkeypatch.setattr(newsradar, 'get_radar', lambda **kw: data)
    payload = ai_tools.exec_tool('query_news_radar', {'per_track': 10})
    serialized, status, truncated = chat._serialize_tool_result(payload)
    assert status == 'partial' and truncated
    assert json.loads(serialized)['data']['source_coverage'] == payload['source_coverage']
