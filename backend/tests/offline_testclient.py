"""In-process ASGI tests with a pre-initialized loop and unconditional network denial.

Windows' Proactor loop may construct its self-pipe through socket.socketpair's
loopback fallback. Initialize only the controlled portal before the guard; no
application or provider code runs until every connection entrypoint is denied.
"""
from contextlib import contextmanager
import socket

import anyio.from_thread
import pytest


@pytest.fixture
def offline_network(monkeypatch):
    # This portal has no application tasks during initialization. Its own context
    # owns shutdown; TestClient contexts borrow it without closing it early.
    with monkeypatch.context() as patches:
        with anyio.from_thread.start_blocking_portal(backend='asyncio') as portal:
            def deny(*args, **kwargs):
                raise AssertionError('network prohibited')

            @contextmanager
            def existing_portal(backend='asyncio', backend_options=None, *, name=None):
                if backend != 'asyncio' or backend_options or name is not None:
                    raise AssertionError('offline TestClient requires the controlled default asyncio portal')
                yield portal

            patches.setattr(anyio.from_thread, 'start_blocking_portal', existing_portal)
            patches.setattr(socket.socket, 'connect', deny)
            patches.setattr(socket.socket, 'connect_ex', deny)
            patches.setattr(socket, 'create_connection', deny)
            patches.setattr(socket, 'getaddrinfo', deny)
            yield portal
