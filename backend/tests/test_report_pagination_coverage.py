"""Actual report pages through public/API/AI/sector consumers, offline only."""
import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import json
import socket

import httpx
import pytest

import app
import astock
import ai_tools
import chat
import debate
import sector_research_data as srd


ROW = {'title': 'Synthetic report', 'publishDate': datetime.now(timezone.utc).date().isoformat(),
       'orgSName': 'Synthetic', 'emRatingName': 'neutral', 'infoCode': 'fixture', 'stockCode': '000001'}


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    # Windows asyncio creates its internal wakeup socketpair via loopback.
    # Initialize only the stdlib loop before denying ALL application connects.
    loop = asyncio.new_event_loop()
    def denied(*args, **kwargs):
        raise AssertionError('network prohibited')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    # Reject hidden TestClient/portal loops rather than exempting localhost.
    monkeypatch.setattr(asyncio, 'new_event_loop', denied)
    monkeypatch.setattr(asyncio.events, 'new_event_loop', denied)
    monkeypatch.setattr(astock.time, 'sleep', lambda *_: None)
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(app, '_DISCOVERY_CACHE', OrderedDict())
    monkeypatch.setattr(srd, 'get_sector_source', lambda _: srd.SectorDataSource(
        key='fixture', label='Synthetic', report_keywords=['Synthetic'],
        representative_company_codes=['000001', '000002']))

    async def get(endpoint):
        # Exercise routing and serialization in process on the prepared loop.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),
                                     base_url='http://testserver') as client:
            return await client.get(endpoint)

    try:
        yield lambda endpoint: loop.run_until_complete(get(endpoint))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


def feed(monkeypatch, pages):
    calls = []
    class Response:
        status_code = 200
        def __init__(self, payload):
            self.payload = payload
        def json(self):
            return self.payload
    class Session:
        def get(self, url, params, **kwargs):
            pn = int(params['pageNo'])
            calls.append((params['qType'], params['code'], pn))
            selected = pages(params, pn) if callable(pages) else pages[pn - 1]
            if isinstance(selected, Exception):
                raise selected
            return selected if hasattr(selected, 'status_code') else Response(selected)
    monkeypatch.setattr(astock, '_report_session', Session)
    return calls


@pytest.mark.parametrize('second,reason', [
    ({'data': [], 'TotalPage': 2}, 'EMPTY_BEFORE_EXPECTED'),
    ({}, 'MALFORMED_RESPONSE'), ({'data': None}, 'MALFORMED_RESPONSE'),
    ({'data': [None]}, 'MALFORMED_RESPONSE'),
    ({'data': [{'title': 123}]}, 'MALFORMED_RESPONSE'),
    ({'data': [{'title': ''}]}, 'MALFORMED_RESPONSE'),
    (OSError('SYNTHETIC_PRIVATE https://provider.invalid?secret=x'), 'SOURCE_ERROR'),
])
def test_second_page_failure_retains_first_rows_and_public_partial(monkeypatch, offline, second, reason):
    calls = feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': 2}, second])
    response = offline('/api/reports?code=000001&pages=2')
    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'partial' and len(payload['data']) == 1
    assert payload['source_coverage']['reason'] == reason
    assert payload['source_coverage']['expected_pages'] == 2
    assert payload['source_coverage']['attempted_pages'] == 2
    assert payload['source_coverage']['received_pages'] == (2 if reason == 'EMPTY_BEFORE_EXPECTED' else 1)
    assert payload['source_coverage']['returned_rows'] == 1
    assert 'SYNTHETIC_PRIVATE' not in response.text and 'secret=x' not in response.text
    assert calls == [('0', '000001', 1), ('0', '000001', 2)]


@pytest.mark.parametrize('first', [{}, {'data': [None]}, {'data': [], 'TotalPage': 2}, OSError('private')])
def test_first_page_failure_never_successful_empty(monkeypatch, offline, first):
    calls = feed(monkeypatch, [first])
    response = offline('/api/reports?code=000001&pages=2')
    assert response.status_code == 502
    assert 'private' not in response.text
    assert len(calls) == 1


@pytest.mark.parametrize('total', [0, 1, '0'])
def test_confirmed_empty_remains_normal_empty(monkeypatch, offline, total):
    calls = feed(monkeypatch, [{'data': [], 'TotalPage': total}])
    response = offline('/api/reports?code=000001&pages=2')
    assert response.status_code == 200
    assert response.json()['data'] == [] and response.json()['status'] == 'normal'
    assert response.json()['source_coverage']['expected_pages'] == 1
    assert len(calls) == 1
    assert ai_tools.exec_tool('query_reports', {'code': '000001'}) == []


def test_default_list_controls_and_transport_exception_are_preserved(monkeypatch):
    calls = feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': 2}, {'data': [{**ROW, 'infoCode': 'two'}], 'TotalPage': 2}])
    assert len(astock.eastmoney_reports('000001', max_pages=2)) == 2
    assert len(calls) == 2
    feed(monkeypatch, [{'data': [], 'TotalPage': 0}])
    assert astock.eastmoney_reports('000001') == []
    failure = OSError('synthetic transport')
    feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': 2}, failure])
    with pytest.raises(OSError) as exc:
        astock.eastmoney_reports('000001', max_pages=2)
    assert exc.value is failure
    feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': 2}, {'data': [], 'TotalPage': 2}])
    with pytest.raises(ValueError, match='incomplete'):
        astock.eastmoney_reports('000001', max_pages=2)


@pytest.mark.parametrize('first_total,second_total', [(2, 3), (3, 1), (2, None)])
def test_changing_totals_never_claim_complete(monkeypatch, first_total, second_total):
    calls = feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': first_total},
                              {'data': [{**ROW, 'infoCode': 'two'}], 'TotalPage': second_total}])
    result = astock.eastmoney_reports('000001', max_pages=3, with_coverage=True)
    assert result['status'] == 'partial'
    assert result['source_coverage']['reason'] == 'TOTAL_CHANGED'
    assert result['source_coverage']['reported_total_pages'] == first_total
    assert len(result['rows']) == len(calls) == 2


@pytest.mark.parametrize('total', [None, 'unknown', True, -1, 1.5])
def test_unknown_totals_and_bounded_single_page_ai_are_limited(monkeypatch, total):
    calls = feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': total}])
    result = ai_tools.exec_tool('query_reports', {'code': '000001'})
    assert result[0]['source_coverage']['reason'] == 'UNKNOWN_TOTAL'
    assert result[0]['source_coverage']['expected_pages'] is None
    assert chat._serialize_tool_result(result)[1] == 'partial'
    assert len(calls) == 1


def test_requested_cap_is_window_limit_not_failure_and_compacts_honestly(monkeypatch):
    row = {**ROW, 'title': 'Synthetic' * 500}
    calls = feed(monkeypatch, [{'data': [row] * 15, 'TotalPage': 2}])
    payload = ai_tools.exec_tool('query_reports', {'code': '000001'})
    coverage = payload[0]['source_coverage']
    assert coverage['reason'] == 'REQUEST_LIMIT' and coverage['expected_pages'] == 1
    assert coverage['reported_total_pages'] == 2 and coverage['historical_complete'] is False
    body, status, truncated = chat._serialize_tool_result(payload)
    assert status == 'partial' and truncated
    assert json.loads(body)['data'][0]['source_coverage'] == coverage
    section = debate._fetch_section(('query_reports', {}, 'Reports', False, True), '000001')
    assert section['status'] == 'partial' and not section['ok']
    assert len(calls) == 2  # One bounded request per consumer, no follow-up page.


def test_maximum_bound_and_no_request_beyond_cap(monkeypatch, offline):
    calls = feed(monkeypatch, lambda params, pn: {'data': [{**ROW, 'infoCode': str(pn)}], 'TotalPage': 11})
    result = astock.eastmoney_reports('000001', max_pages=10, with_coverage=True)
    assert len(calls) == 10 and result['source_coverage']['expected_pages'] == 10
    assert result['source_coverage']['reason'] == 'REQUEST_LIMIT'
    for invalid in [0, -1, 11, True, 1.5]:
        with pytest.raises(ValueError):
            astock.eastmoney_reports('000001', max_pages=invalid, with_coverage=True)
    assert len(calls) == 10
    assert offline('/api/reports?code=000001&pages=6').status_code == 422
    assert len(calls) == 10


def test_sector_partial_keeps_exact_returned_row_authority_and_failure_reuses_no_fake_metadata(monkeypatch, offline):
    calls = feed(monkeypatch, lambda params, pn: (
        {'data': [{**ROW, 'infoCode': 'good'}], 'TotalPage': 2} if params['code'] == '000001' and pn == 1 else {}))
    response = offline('/api/sector-research/reports/fixture?scope=company&max_pages=2')
    result = response.json()['data']
    assert result['status'] == 'partial' and result['error'] is None
    assert len(result['source_coverage']) == 2
    assert result['source_coverage'][0]['reason'] == 'MALFORMED_RESPONSE'
    assert result['source_coverage'][1]['status'] == 'unavailable'
    assert [r['external_id'] for r in result['discovered']] == ['good']
    assert set(app._DISCOVERY_CACHE) == {('fixture', 'good')}
    before = dict(app._DISCOVERY_CACHE)
    cached = app._get_cached_discovery('fixture', 'good')
    assert cached is before[('fixture', 'good')]
    assert cached.title == result['discovered'][0]['title']
    # Failure cannot replace a previously authorized cached row or invent records.
    feed(monkeypatch, [{}])
    failed = offline('/api/sector-research/reports/fixture?scope=company&max_pages=2').json()['data']
    assert failed['status'] == 'unavailable' and failed['error']
    assert failed['discovered'] == []
    assert dict(app._DISCOVERY_CACHE) == before
    assert len(calls) == 3


def test_industry_filter_cannot_erase_source_limitations(monkeypatch):
    calls = feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': 2}])
    result = ai_tools.exec_tool('query_industry_reports', {'keywords': ['not-matched']})
    assert result['status'] == 'unavailable'
    assert result['source_coverage']['reason'] == 'REQUEST_LIMIT'
    assert result['source_coverage']['returned_rows'] == 1
    assert chat._serialize_tool_result(result)[1] == 'error'
    assert len(calls) == 1


def test_unknown_company_total_does_not_expand_fetches(monkeypatch):
    calls = feed(monkeypatch, [{'data': [dict(ROW)]}])
    result = astock.eastmoney_reports('000001', max_pages=3, with_coverage=True)
    assert result['status'] == 'partial' and result['source_coverage']['reason'] == 'UNKNOWN_TOTAL'
    assert result['source_coverage']['expected_pages'] is None
    assert len(calls) == 1


@pytest.mark.parametrize('status_code,json_raises', [(503, False), (200, True)])
def test_http_and_json_failures_preserve_prior_rows_without_leaking(monkeypatch, offline, status_code, json_raises):
    class FailedResponse:
        def json(self):
            if json_raises:
                raise ValueError('synthetic secret provider body')
            return {'data': [], 'TotalPage': 0}
    response = FailedResponse()
    response.status_code = status_code
    feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': 2}, response])
    result = offline('/api/reports?code=000001&pages=2')
    assert result.status_code == 200 and result.json()['status'] == 'partial'
    assert result.json()['source_coverage']['received_pages'] == 1
    assert len(result.json()['data']) == 1
    assert 'secret' not in result.text


def test_reported_zero_with_rows_is_contradictory_not_complete(monkeypatch):
    calls = feed(monkeypatch, [{'data': [dict(ROW)], 'TotalPage': 0}])
    result = astock.eastmoney_reports('000001', max_pages=2, with_coverage=True)
    assert result['status'] == 'partial'
    assert result['source_coverage']['reason'] == 'TOTAL_CHANGED'
    assert len(calls) == 1


def test_sector_complete_empty_and_unknown_legacy_are_distinct(monkeypatch, offline):
    feed(monkeypatch, [{'data': [], 'TotalPage': 0}])
    complete = offline('/api/sector-research/reports/fixture?scope=industry').json()['data']
    assert complete['status'] == 'normal' and complete['error'] is None and complete['discovered'] == []
    monkeypatch.setattr(astock, 'eastmoney_industry_reports', lambda **kwargs: [])
    unknown = offline('/api/sector-research/reports/fixture?scope=industry').json()['data']
    assert unknown['status'] == 'unavailable' and unknown['source_coverage'][0]['reason'] == 'UNKNOWN_TOTAL'
    assert app._DISCOVERY_CACHE == {}


@pytest.mark.parametrize('address', [('192.0.2.1', 443), ('127.0.0.1', 443)])
@pytest.mark.parametrize('method', ['connect', 'connect_ex', 'create_connection'])
def test_socket_guard_blocks_external_and_loopback(address, method):
    with pytest.raises(AssertionError, match='network prohibited'):
        if method == 'create_connection':
            socket.create_connection(address)
        else:
            with socket.socket() as sock:
                getattr(sock, method)(address)


def test_socket_guard_remains_active_inside_asgi_provider(monkeypatch, offline):
    blocked = []

    class UnexpectedSession:
        def get(self, *args, **kwargs):
            try:
                socket.create_connection(('127.0.0.1', 443))
            except AssertionError:
                blocked.append(True)
                raise
            raise AssertionError('Provider unexpectedly escaped the socket guard')

    monkeypatch.setattr(astock, '_report_session', UnexpectedSession)
    response = offline('/api/reports?code=000001&pages=2')
    assert blocked == [True]
    assert response.status_code == 502
    assert 'network prohibited' not in response.text


def test_api_fixture_rejects_late_event_loop_creation():
    for factory in (asyncio.new_event_loop, asyncio.events.new_event_loop):
        with pytest.raises(AssertionError, match='network prohibited'):
            factory()
