"""Explicit executed costs through the real API, with synthetic isolated storage."""
import asyncio
import json
import socket

import httpx
import pytest

import app
import trade_ledger_service as svc

ABSENT = object()


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('VIBE_RESEARCH_TRADE_LEDGER_DB', str(tmp_path / 'trades.sqlite3'))
    # Initialize the stdlib wakeup socketpair before guarding on Windows too.
    loop = asyncio.new_event_loop()
    def forbidden(*args, **kwargs):
        raise AssertionError('Synthetic trade tests forbid all network access')
    for method in ('connect', 'connect_ex'):
        monkeypatch.setattr(socket.socket, method, forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(asyncio, 'new_event_loop', forbidden)
    monkeypatch.setattr(asyncio.events, 'new_event_loop', forbidden)

    async def request(method, path, payload):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),
                                    base_url='http://testserver') as client:
            # Raw encoding intentionally exercises non-finite input rejection.
            return await client.request(method, path, content=json.dumps(payload) if payload is not None else None,
                                        headers={'Content-Type': 'application/json'})
    try:
        yield lambda method, path='/api/trades', payload=None: loop.run_until_complete(request(method, path, payload))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


def trade(status='full'):
    payload = dict(code='600000', name='SYNTHETIC', operation='buy',
                   execution_status=status, actual_price=10, actual_quantity=100,
                   executed_at='2026-10-09T02:00:00Z', fee=0, other_cost=0)
    if status == 'partial':
        payload.update(planned_quantity=200, unexecuted_reason='Synthetic partial execution')
    elif status == 'not_executed':
        payload['unexecuted_reason'] = 'Synthetic cancellation'
    return payload


@pytest.mark.parametrize('status', ['full', 'partial'])
@pytest.mark.parametrize('field', ['fee', 'other_cost'])
@pytest.mark.parametrize('value', [ABSENT, None, '', '0', 'invalid', True, False, -1,
                                   float('nan'), float('inf'), float('-inf'), 10**400])
def test_invalid_cost_rejected_without_write(api, monkeypatch, status, field, value):
    payload = trade(status)
    if value is ABSENT:
        del payload[field]
    else:
        payload[field] = value
    def forbidden_insert(*args, **kwargs):
        raise AssertionError('Invalid costs must not reach storage')
    monkeypatch.setattr(svc.store, 'insert_record', forbidden_insert)
    response = api('POST', payload=payload)
    assert response.status_code == 422
    assert field in response.json()['detail']
    assert all(secret not in response.text.lower() for secret in ('traceback', 'sqlite', 'overflow', 'insert'))
    assert not svc.resolve_db_path().exists()


@pytest.mark.parametrize('status', ['full', 'partial'])
@pytest.mark.parametrize('fee,other_cost', [(0, 0), (5, 1), (0, 2.5), (3.5, 0)])
def test_explicit_costs_persist_and_read_back(api, status, fee, other_cost):
    payload = dict(trade(status), fee=fee, other_cost=other_cost)
    response = api('POST', payload=payload)
    assert response.status_code == 200
    row = response.json()['data']
    reread = api('GET', '/api/trades/' + row['trade_id']).json()['data']
    assert reread['fee'] == fee and reread['other_cost'] == other_cost
    assert reread['total_cost'] == fee + other_cost
    assert reread['net_cash_flow'] == -1000 - fee - other_cost


@pytest.mark.parametrize('value', [ABSENT, None, 0, 5, -1])
def test_unexecuted_cost_normalization_unchanged(api, value):
    payload = trade('not_executed')
    for field in ('fee', 'other_cost'):
        if value is ABSENT:
            del payload[field]
        else:
            payload[field] = value
    response = api('POST', payload=payload)
    assert response.status_code == 200
    row = response.json()['data']
    assert (row['fee'], row['other_cost'], row['actual_quantity'], row['executed_at']) == (0, 0, 0, None)


@pytest.mark.parametrize('host', ['127.0.0.1', '192.0.2.1'])
@pytest.mark.parametrize('method', ['connect', 'connect_ex', 'create_connection'])
def test_network_guard_blocks_loopback_and_external(api, host, method):
    with pytest.raises(AssertionError, match='forbid all network'):
        if method == 'create_connection':
            socket.create_connection((host, 443))
        else:
            with socket.socket() as sock:
                getattr(sock, method)((host, 443))


@pytest.mark.parametrize('status', ['full', 'partial'])
@pytest.mark.parametrize('field', ['fee', 'other_cost'])
@pytest.mark.parametrize('value', [ABSENT, None])
def test_rejected_write_preserves_existing_zero_cost_record(api, status, field, value):
    # Seed directly through the existing store, representing a historical row.
    # Old zero costs have no recoverable known/unknown provenance.
    legacy = svc.validate_and_build_record(trade())
    db = svc.resolve_db_path()
    svc.store.insert_record(db, legacy)
    before = db.read_bytes()
    payload = trade(status)
    if value is ABSENT:
        del payload[field]
    else:
        payload[field] = value
    assert api('POST', payload=payload).status_code == 422
    assert db.read_bytes() == before
    row = api('GET', '/api/trades/' + legacy['trade_id']).json()['data']
    assert row['fee'] == 0 and row['other_cost'] == 0
    assert row['total_cost'] == 0
