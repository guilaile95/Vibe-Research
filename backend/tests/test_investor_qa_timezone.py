"""CNINFO millisecond epochs must not inherit the deployment host's timezone."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import ai_tools
import app
import astock
import chat


# 2026-10-05 16:30 UTC == 2026-10-06 00:30 Asia/Shanghai.
EPOCH_MS = 1791217800000
EXPECTED = '2026-10-06 00:30'


def provider(monkeypatch, value):
    import requests
    calls = []
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def json(self):
            return self.payload
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response({'data': [{'secid': 'fixture-org'}]} if url.endswith('queryKeyboardInfo') else
                        {'rows': [{'pubDate': value, 'companyShortName': 'fixture company',
                                   'mainContent': 'fixture question', 'attachedContent': 'fixture answer',
                                   'attachedAuthor': 'fixture answerer'}]})
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(app, '_cached', lambda _kind, _key, _ttl, fn: fn())
    return calls


@pytest.mark.skipif(not hasattr(time, 'tzset'), reason='process TZ selection requires POSIX tzset')
@pytest.mark.parametrize('zone', ['UTC', 'Asia/Shanghai', 'Etc/GMT+5'])
def test_actual_reader_http_and_ai_are_identical_across_process_timezones(zone):
    # TZ belongs only to this child. Never call tzset or change os.environ in the
    # pytest process, host or sibling agents; all provider calls are synthetic.
    script = '''
import json, os, time
from unittest.mock import patch
import ai_tools, app, astock, chat
if hasattr(time, 'tzset'):
    time.tzset()
calls = []
class Response:
    def __init__(self, payload): self.payload = payload
    def json(self): return self.payload
def post(url, **kwargs):
    calls.append((url, kwargs))
    if url.endswith('queryKeyboardInfo'):
        return Response({'data': [{'secid': 'fixture-org'}]})
    return Response({'rows': [{'pubDate': 1791217800000, 'mainContent': 'fixture question',
                              'attachedContent': 'fixture answer'}]})
with patch('requests.post', post), patch.object(app, '_cached', lambda k, c, t, fn: fn()):
    raw = astock.investor_qa('000001')
    http = app.investor_qa(code='000001')['data']
    model = json.loads(chat._serialize_tool_result(ai_tools.exec_tool('query_investor_qa', {'code': '000001'}))[0])['data']
    print(json.dumps({'times': [raw[0]['ask_time'], http[0]['ask_time'], model[0]['ask_time']],
                      'calls': len(calls), 'page_sizes': [kw['params']['pageSize'] for _, kw in calls if 'params' in kw]}))
'''
    backend = str(Path(astock.__file__).parent)
    env = {**os.environ, 'TZ': zone, 'PYTHONPATH': backend}
    result = subprocess.run([sys.executable, '-c', script], env=env, cwd=backend,
                            capture_output=True, text=True, check=True, timeout=30)
    payload = json.loads(result.stdout)
    assert payload['times'] == [EXPECTED] * 3
    assert payload['calls'] == 6
    assert payload['page_sizes'] == [30] * 3


@pytest.mark.parametrize('value', [EPOCH_MS, float(EPOCH_MS), EPOCH_MS + 59999])
def test_numeric_milliseconds_keep_minute_string_format(monkeypatch, value):
    calls = provider(monkeypatch, value)
    row = astock.investor_qa('000001')[0]
    assert row == {'company': 'fixture company', 'question': 'fixture question',
                   'answer': 'fixture answer', 'answerer': 'fixture answerer', 'ask_time': EXPECTED}
    assert len(calls) == 2


@pytest.mark.parametrize('value', [None, 0, '', False])
def test_existing_missing_time_behavior_stays_unknown(monkeypatch, value):
    provider(monkeypatch, value)
    assert astock.investor_qa('000001')[0]['ask_time'] == ''


@pytest.mark.parametrize('value,exception', [
    ('1791217800000', TypeError), ('2026-10-06 00:30', TypeError), ('malformed', TypeError),
    ({'date': 'fixture'}, TypeError), (float('nan'), ValueError), (float('inf'), OverflowError),
])
def test_existing_malformed_source_behavior_stays_failed(monkeypatch, value, exception):
    provider(monkeypatch, value)
    with pytest.raises(exception):
        astock.investor_qa('000001')
    with pytest.raises(app.HTTPException) as error:
        app.investor_qa(code='000001')
    assert error.value.status_code == 502
    assert 'error' in ai_tools.exec_tool('query_investor_qa', {'code': '000001'})


def test_existing_valid_reader_strings_are_not_reparsed_by_ai(monkeypatch):
    monkeypatch.setattr(astock, 'investor_qa', lambda code: [
        {'ask_time': EXPECTED, 'question': 'fixture', 'answer': 'fixture'}])
    payload = ai_tools.exec_tool('query_investor_qa', {'code': '000001'})
    assert json.loads(chat._serialize_tool_result(payload)[0])['data'][0]['ask_time'] == EXPECTED
