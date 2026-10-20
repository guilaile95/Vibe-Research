"""Safety regression for the portable in-process TestClient guard."""
import asyncio
from contextlib import asynccontextmanager
import socket

import anyio.from_thread
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from offline_testclient import offline_network


@pytest.mark.parametrize('address', [('203.0.113.1', 443), ('127.0.0.1', 12345), ('::1', 12345)])
def test_external_and_arbitrary_loopback_connects_denied(offline_network, address):
    family = socket.AF_INET6 if ':' in address[0] else socket.AF_INET
    with socket.socket(family) as connection:
        for method in [connection.connect, connection.connect_ex]:
            with pytest.raises(AssertionError, match='network prohibited'):
                method(address)
    with pytest.raises(AssertionError, match='network prohibited'):
        socket.create_connection(address)
    with pytest.raises(AssertionError, match='network prohibited'):
        socket.getaddrinfo(*address)


def test_testclient_reuses_initialized_portal_and_guard_covers_application(offline_network, monkeypatch):
    # No TestClient operation may construct a second loop/self-pipe under guard.
    def unexpected_loop(*args, **kwargs):
        raise AssertionError('unexpected event loop initialization')
    monkeypatch.setattr(asyncio, 'new_event_loop', unexpected_loop)
    monkeypatch.setattr(asyncio.get_event_loop_policy(), 'new_event_loop', unexpected_loop)
    lifespan_checks = []
    @asynccontextmanager
    async def lifespan(app):
        with pytest.raises(AssertionError, match='network prohibited'):
            socket.create_connection(('127.0.0.1', 12345))
        lifespan_checks.append('startup')
        try:
            yield
        finally:
            with pytest.raises(AssertionError, match='network prohibited'):
                socket.create_connection(('203.0.113.1', 443))
            lifespan_checks.append('shutdown')
    app = FastAPI(lifespan=lifespan)
    @app.get('/guard')
    def guard():
        with pytest.raises(AssertionError, match='network prohibited'):
            socket.create_connection(('203.0.113.1', 443))
        return {'guarded': True}
    for _ in range(2):
        with TestClient(app) as client:
            assert client.get('/guard').json() == {'guarded': True}
    assert TestClient(app).get('/guard').json() == {'guarded': True}
    assert lifespan_checks == ['startup', 'shutdown', 'startup', 'shutdown']


def test_guard_cannot_request_an_uncontrolled_portal(offline_network):
    for options in [{'backend': 'trio'}, {'backend_options': {'use_uvloop': True}}, {'name': 'other'}]:
        with pytest.raises(AssertionError, match='controlled default'):
            with anyio.from_thread.start_blocking_portal(**options):
                pytest.fail('unsupported portal must not start')
