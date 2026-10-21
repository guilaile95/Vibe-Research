"""Synthetic transport tests: no sockets, external DNS, or model provider."""
import socket
from unittest.mock import Mock

import pytest
import safe_deep_read_fetch as safe

PUBLIC = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://2130706433", "http://[::ffff:127.0.0.1]", "http://internal.example"])
def test_resolved_private_and_numeric_addresses_rejected(monkeypatch, url):
    monkeypatch.setattr(safe.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))])
    monkeypatch.setattr(safe.socket, "socket", lambda *a: pytest.fail("private socket forbidden"))
    with pytest.raises(safe.UnsafeDestination):
        safe.fetch(url, timeout=1, accept="text/plain")


def test_mixed_answers_fail_closed(monkeypatch):
    monkeypatch.setattr(safe.socket, "getaddrinfo", lambda *a, **k: [PUBLIC, (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0))])
    with pytest.raises(safe.UnsafeDestination):
        safe.fetch("https://public.example", timeout=1, accept="text/plain")


@pytest.mark.parametrize("url", ["https://user:password@public.example", "https://public.example:8080", "https://public.example/\r\nHost:evil", "http://[fe80::1%25eth0]", "file:///etc/passwd"])
def test_url_syntax_rejected_before_dns(monkeypatch, url):
    monkeypatch.setattr(safe.socket, "getaddrinfo", lambda *a, **k: pytest.fail("unexpected DNS"))
    with pytest.raises(safe.UnsafeDestination):
        safe.fetch(url, timeout=1, accept="text/plain")


def test_explicit_proxy_rejected_without_dns(monkeypatch):
    monkeypatch.setattr(safe.socket, "getaddrinfo", lambda *a, **k: pytest.fail("unexpected DNS"))
    with pytest.raises(safe.UnsafeDestination, match="PROXY"):
        safe.fetch("https://public.example", timeout=1, accept="text/plain", proxy_url="http://127.0.0.1:9")


def test_connect_uses_pinned_address_and_original_tls_hostname(monkeypatch):
    sock = Mock()
    monkeypatch.setattr(safe.socket, "socket", lambda *a: sock)
    monkeypatch.setattr(safe.socket, "getaddrinfo", lambda *a, **k: pytest.fail("connect must not resolve"))
    tls = Mock()
    monkeypatch.setattr(safe.ssl, "create_default_context", lambda: tls)
    connection = safe._PinnedConnection("public.example", 443, PUBLIC, True, safe.time.monotonic() + 10)
    connection.connect()
    sock.connect.assert_called_once_with(PUBLIC[-1])
    tls.wrap_socket.assert_called_once_with(sock, server_hostname="public.example", do_handshake_on_connect=False)
    tls.wrap_socket.return_value.do_handshake.assert_called_once()


def _responses(monkeypatch, responses):
    seen = []
    class Connection:
        sock = None
        def __init__(self, host, port, address, secure, deadline):
            seen.append((host, address))
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return responses.pop(0)
        def close(self):
            pass
    monkeypatch.setattr(safe, "_PinnedConnection", Connection)
    return seen


def response(status=200, location=None, body=b"public article"):
    item = Mock(status=status)
    item.getheader.return_value = location
    item.read1.side_effect = [body, b""]
    return item


def test_redirect_revalidates_private_destination_before_connection(monkeypatch):
    def resolve(host, *a, **k):
        return [PUBLIC] if host == "public.example" else [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]
    monkeypatch.setattr(safe.socket, "getaddrinfo", resolve)
    seen = _responses(monkeypatch, [response(302, "https://169.254.169.254/latest/meta-data")])
    with pytest.raises(safe.UnsafeDestination):
        safe.fetch("https://public.example", timeout=2, accept="text/plain")
    assert len(seen) == 1


def test_public_relative_redirect_and_byte_budget(monkeypatch):
    calls = []
    def resolve(*a, **k):
        calls.append(a)
        return [PUBLIC]
    monkeypatch.setattr(safe.socket, "getaddrinfo", resolve)
    seen = _responses(monkeypatch, [response(302, "/article"), response()])
    assert safe.fetch("https://public.example", timeout=2, accept="text/plain") == b"public article"
    assert len(seen) == len(calls) == 2  # exactly one resolution per hop
    _responses(monkeypatch, [response(body=b"123456")])
    with pytest.raises(safe.UnsafeDestination, match="TOO_LARGE"):
        safe.fetch("https://public.example", timeout=2, accept="text/plain", max_bytes=5)


def test_downgrade_and_redirect_loop_rejected(monkeypatch):
    monkeypatch.setattr(safe.socket, "getaddrinfo", lambda *a, **k: [PUBLIC])
    _responses(monkeypatch, [response(302, "http://public.example")])
    with pytest.raises(safe.UnsafeDestination, match="REDIRECT"):
        safe.fetch("https://public.example", timeout=2, accept="text/plain")
    seen = _responses(monkeypatch, [response(302, "/again") for _ in range(4)])
    with pytest.raises(safe.UnsafeDestination, match="REDIRECT"):
        safe.fetch("https://public.example", timeout=2, accept="text/plain")
    assert len(seen) == 4


def test_tls_verification_failure_cannot_return_body(monkeypatch):
    sock = Mock()
    monkeypatch.setattr(safe.socket, "socket", lambda *a: sock)
    tls = Mock()
    tls.wrap_socket.side_effect = safe.ssl.SSLCertVerificationError("synthetic mismatch")
    monkeypatch.setattr(safe.ssl, "create_default_context", lambda: tls)
    connection = safe._PinnedConnection("public.example", 443, PUBLIC, True, safe.time.monotonic() + 1)
    with pytest.raises(safe.ssl.SSLCertVerificationError):
        connection.connect()
    sock.close.assert_called_once()


def test_total_budget_and_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(safe.socket, "getaddrinfo", lambda *a, **k: [PUBLIC])
    _responses(monkeypatch, [response()])
    assert safe.fetch("https://public.example", timeout=1, accept="text/plain") == b"public article"
    with pytest.raises(TimeoutError):
        safe.fetch("https://public.example", timeout=0, accept="text/plain")


def test_blocked_destination_retains_only_existing_summary(monkeypatch):
    import native_intel_ext_sources as ext
    monkeypatch.setattr(safe.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))])
    monkeypatch.setattr(safe.socket, "socket", lambda *a: pytest.fail("private transport forbidden"))
    result = ext.read_source_content({"url": "https://public.example", "title": "synthetic", "summary": "existing summary"})
    assert result["status"] == "partial"
    assert result["content"] == "existing summary"
    assert result["failure"] == {"kind": "security", "detail": "DESTINATION_NOT_PUBLIC"}
    assert result["source_url"] is None


@pytest.mark.parametrize("address", ["224.0.0.1", "239.255.255.255", "ff02::1", "ff0e::1", "0.0.0.0", "::", "240.0.0.1", "100.64.0.1", "192.0.2.1", "::ffff:127.0.0.1"])
def test_only_global_unicast_is_eligible(address):
    assert not safe._public_ip(address)


def test_explicit_zero_port_is_rejected():
    with pytest.raises(safe.UnsafeDestination):
        safe._target("https://public.example:0/article")


def test_tls_socket_owned_before_handshake_and_deadline_rechecked(monkeypatch):
    sock, wrapped = Mock(), Mock()
    monkeypatch.setattr(safe.socket, "socket", lambda *a: sock)
    tls = Mock()
    tls.wrap_socket.return_value = wrapped
    monkeypatch.setattr(safe.ssl, "create_default_context", lambda: tls)
    clock = [100.0]
    monkeypatch.setattr(safe.time, "monotonic", lambda: clock[0])
    connection = safe._PinnedConnection("public.example", 443, PUBLIC, True, 101.0)
    def handshake():
        assert connection.sock is wrapped
        clock[0] = 102.0
    wrapped.do_handshake.side_effect = handshake
    with pytest.raises(TimeoutError):
        connection.connect()
    wrapped.close.assert_called_once()
