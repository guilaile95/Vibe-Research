"""Synthetic margin/holder source-to-sink contracts; no provider/model requests."""
import asyncio
import json
import socket

import httpx
import pytest

import ai_tools
import app
import astock
import chat
from top_risk_evaluators import crowding
from top_risk_schema import TopRiskFact

MARGIN = dict(zip(('RZYE', 'RZMRE', 'RZCHE', 'RQYE', 'RQMCL', 'RZRQYE'),
                  ('rzye', 'rzmre', 'rzche', 'rqye', 'rqmcl', 'rzrqye')))
HOLDERS = {'HOLDER_NUM': 'holder_num', 'HOLDER_NUM_RATIO': 'change_ratio', 'AVG_FREE_SHARES': 'avg_shares'}
ABSENT = object()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    # Windows asyncio builds its internal wakeup socketpair with a loopback
    # connect. Prepare only the stdlib loop before denying ALL connects; never
    # exempt localhost or relax the guard while application code is running.
    loop = asyncio.new_event_loop()
    def forbidden(*args, **kwargs):
        raise AssertionError('No external sockets allowed in synthetic capital tests')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    # A hidden portal/runner must not create a second loop during API execution.
    monkeypatch.setattr(asyncio, 'new_event_loop', forbidden)
    monkeypatch.setattr(asyncio.events, 'new_event_loop', forbidden)
    monkeypatch.setattr(app, '_cached', lambda endpoint, code, ttl, fetch: fetch())

    async def get(endpoint):
        # In-process ASGI transport exercises routing and JSON serialization
        # without TestClient constructing another event loop under the guard.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),
                                     base_url="http://testserver") as client:
            return await client.get('/api/' + endpoint, params={'code': '000001'})

    try:
        yield lambda endpoint: loop.run_until_complete(get(endpoint))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


@pytest.mark.parametrize('endpoint,adapter,tool,report,date_key,fields', [
    ('margin', astock.margin_trading, 'query_margin', 'RPTA_WEB_RZRQ_GGMX', 'DATE', MARGIN),
    ('holders', astock.holder_num_change, 'query_holders', 'RPT_HOLDERNUMLATEST', 'END_DATE', HOLDERS),
])
@pytest.mark.parametrize('value,expected', [
    (ABSENT, None), (None, None), (0, 0), ('0', 0), (123.5, 123.5), (' 123.5 ', 123.5),
    (-12.5, -12.5), ('', None), ('  ', None), ('-', None), ('--', None), ('bad', None),
    (float('nan'), None), (float('inf'), None), (float('-inf'), None),
    ('NaN', None), ('Infinity', None), (False, None), (True, None), (10**400, None),
])
def test_numbers_survive_adapter_api_and_model(monkeypatch, isolated, endpoint, adapter, tool, report, date_key, fields, value, expected):
    row = {date_key: '2026-10-09 00:00:00'}
    if value is not ABSENT:
        row.update({field: value for field in fields})
    def provider(actual_report, **kwargs):
        assert actual_report == report
        return [dict(row)]
    monkeypatch.setattr(astock, 'eastmoney_datacenter', provider)
    direct = adapter('000001')
    assert direct == [{'date': '2026-10-09', **{field: expected for field in fields.values()}}]
    response = isolated(endpoint)
    assert response.status_code == 200
    assert response.json() == {'data': direct}
    tool_data = ai_tools.exec_tool(tool, {'code': '000001'})
    # Margin's pre-existing token projection omits rqmcl; all other fields survive.
    expected_tool = [{k: v for k, v in direct[0].items() if tool != 'query_margin' or k != 'rqmcl'}]
    assert tool_data == expected_tool
    serialized, _, _ = chat._serialize_tool_result(tool_data)
    assert json.loads(serialized)['data'] == expected_tool
    assert 'NaN' not in serialized and 'Infinity' not in serialized


def test_missing_one_field_does_not_hide_known_values(monkeypatch):
    monkeypatch.setattr(astock, 'eastmoney_datacenter', lambda *a, **kw: [
        {'DATE': '2026-10-09', 'RZYE': '100000000', 'RQYE': 0}])
    row = astock.margin_trading('000001')[0]
    assert row['rzye'] == 100000000 and row['rqye'] == 0 and row['rzmre'] is None


@pytest.mark.parametrize('latest,expected_direction,skipped', [
    ({}, 'NEUTRAL', True), ({'RZYE': None}, 'NEUTRAL', True),
    ({'RZYE': ''}, 'NEUTRAL', True), ({'RZYE': float('nan')}, 'NEUTRAL', True),
    ({'RZYE': False}, 'NEUTRAL', True), ({'RZYE': 0}, 'SAFE', False),
    ({'RZYE': '0'}, 'SAFE', False), ({'RZYE': 150}, 'RISK', False),
])
def test_missing_balance_never_manufactures_deleveraging(monkeypatch, latest, expected_direction, skipped):
    monkeypatch.setattr(astock, 'eastmoney_datacenter', lambda *a, **kw: [
        {'DATE': '2026-10-09', **latest}, {'DATE': '2026-10-08', 'RZYE': 100}])
    # Same ascending chronology used by top_risk_service.
    rows = sorted(astock.margin_trading('000001'), key=lambda r: r['date'])
    result = crowding(TopRiskFact(code='000001', margin_trading=rows), {})
    assert result.direction == expected_direction and result.skipped is skipped
    if skipped:
        assert result.step_risk == 0 and result.confidence == 0
        assert not any('杠杆去化' in reason for reason in result.reasons)
    elif expected_direction == 'SAFE':
        assert result.step_risk == -0.2 and result.details['margin_rise_ratio'] == -1


def test_existing_empty_and_projection_limits(monkeypatch):
    monkeypatch.setattr(astock, 'eastmoney_datacenter', lambda *a, **kw: [])
    for tool in ('query_margin', 'query_holders'):
        assert ai_tools.exec_tool(tool, {'code': '000001'}) == []
    monkeypatch.setattr(astock, 'eastmoney_datacenter', lambda *a, **kw: [
        {'DATE': str(i), 'END_DATE': str(i), 'RZYE': i, 'HOLDER_NUM': i} for i in range(20)])
    assert [r['rzye'] for r in ai_tools.exec_tool('query_margin', {'code': '000001'})] == list(range(15))
    assert [r['holder_num'] for r in ai_tools.exec_tool('query_holders', {'code': '000001'})] == list(range(10))


@pytest.mark.parametrize('address', [('192.0.2.1', 443), ('127.0.0.1', 443)])
@pytest.mark.parametrize('method', ['connect', 'connect_ex', 'create_connection'])
def test_socket_guard_still_blocks_external_and_loopback(address, method):
    with pytest.raises(AssertionError, match='No external sockets allowed'):
        if method == 'create_connection':
            socket.create_connection(address)
        else:
            with socket.socket() as sock:
                getattr(sock, method)(address)


@pytest.mark.parametrize('endpoint', ['margin', 'holders'])
def test_socket_guard_remains_active_inside_asgi_provider(monkeypatch, isolated, endpoint):
    blocked = []
    def unexpected_provider(*args, **kwargs):
        try:
            socket.create_connection(('192.0.2.1', 443))
        except AssertionError:
            blocked.append(True)
            raise
        raise AssertionError('Provider unexpectedly escaped the socket guard')
    monkeypatch.setattr(astock, 'eastmoney_datacenter', unexpected_provider)
    response = isolated(endpoint)
    assert blocked == [True]
    assert response.status_code == 502
    assert 'No external sockets allowed' not in response.text


def test_api_fixture_rejects_late_event_loop_creation():
    for factory in (asyncio.new_event_loop, asyncio.events.new_event_loop):
        with pytest.raises(AssertionError, match='No external sockets allowed'):
            factory()
