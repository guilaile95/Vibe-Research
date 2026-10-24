"""Exercise the Windows socketpair fallback on every platform, without egress."""
import socket
import asyncio

import pytest

from offline_network_fixtures import block_external_connections


def test_stdlib_fallback_socketpair_remains_usable(monkeypatch):
    block_external_connections(monkeypatch)
    left, right = socket._fallback_socketpair()
    try:
        left.settimeout(1)
        right.settimeout(1)
        left.sendall(b"socketpair-only")
        assert right.recv(64) == b"socketpair-only"
        assert left.getsockname() == right.getpeername()
        assert right.getsockname() == left.getpeername()
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("address", [("127.0.0.1", 80), ("8.8.8.8", 443), ("169.254.169.254", 80)])
@pytest.mark.parametrize("method", ["connect", "connect_ex", "create_connection"])
def test_application_connections_are_denied(monkeypatch, address, method):
    block_external_connections(monkeypatch)
    with socket.socket() as client, pytest.raises(AssertionError, match="Real network connections prohibited"):
        if method == "create_connection":
            socket.create_connection(address)
        else:
            getattr(client, method)(address)


def test_named_imitation_cannot_connect_to_real_loopback_listener(monkeypatch):
    block_external_connections(monkeypatch)
    with socket.socket() as lsock, socket.socket() as csock:
        lsock.bind(("127.0.0.1", 0))
        lsock.listen()
        # Matching local variable names and a live listener are insufficient:
        # the call must originate inside the actual stdlib code object.
        def _fallback_socketpair(lsock, csock):
            csock.connect(lsock.getsockname())
        with pytest.raises(AssertionError, match="Real network connections prohibited"):
            _fallback_socketpair(lsock, csock)


def test_event_loop_self_socket_uses_only_stdlib_pair(monkeypatch):
    monkeypatch.setattr(socket, "socketpair", socket._fallback_socketpair)
    block_external_connections(monkeypatch)
    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(asyncio.sleep(0, result="in-process")) == "in-process"
    finally:
        loop.close()
