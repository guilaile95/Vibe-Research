"""Offline socket guard that preserves only CPython's internal socketpair setup."""
import ipaddress
import socket
import sys


def block_external_connections(monkeypatch):
    """Deny application TCP, including loopback, without breaking Windows asyncio.

    Windows implements socketpair with a private loopback listener. Permit only
    its direct connect call, from the real stdlib function, on that function's
    client socket and exact listener endpoint. No address-wide exemption exists.
    """
    original_connect = socket.socket.connect
    fallback = getattr(socket, "_fallback_socketpair", None)
    fallback_code = getattr(fallback, "__code__", None)

    def denied(*args, **kwargs):
        raise AssertionError("Real network connections prohibited in offline tests")

    def guarded_connect(client, address):
        caller = sys._getframe(1)
        try:
            if fallback_code is not None and caller.f_code is fallback_code:
                local = caller.f_locals
                listener = local.get("lsock")
                if local.get("csock") is client and isinstance(listener, socket.socket):
                    endpoint = listener.getsockname()[:2]
                    if (address == endpoint and endpoint[1] != 0
                            and ipaddress.ip_address(endpoint[0]).is_loopback):
                        return original_connect(client, address)
        finally:
            del caller
        return denied()

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
