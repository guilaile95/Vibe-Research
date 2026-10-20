"""Public article transport: validate every hop and connect only to pinned IPs.

No environment proxy, DNS re-resolution during connect, or TLS verification
bypass. Explicit proxies fail closed because their destination cannot be pinned.
"""
from __future__ import annotations

import http.client
import ipaddress
import queue
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit

POLICY_VERSION = "public-pinned-v1"


class UnsafeDestination(ValueError):
    pass


def _public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
        return (ip.is_global and not ip.is_multicast and not ip.is_reserved
                and not ip.is_unspecified and not ip.is_loopback and not ip.is_link_local
                and not (getattr(ip, "ipv4_mapped", None) and not _public_ip(str(ip.ipv4_mapped))))
    except ValueError:
        return False


def _target(url: str):
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise UnsafeDestination("URL_NOT_ALLOWED")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if (parts.scheme not in ("http", "https") or not host or parts.username is not None
                or parts.password is not None or port not in (80, 443) or "%" in host
                or "\\" in url):
            raise ValueError()
        host = host.encode("idna").decode("ascii")
        if host.lower() == "localhost" or host.lower().endswith(".localhost"):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise UnsafeDestination("URL_NOT_ALLOWED") from None
    return parts, host, port


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("FETCH_TIMEOUT")
    return left


def _resolve(host: str, port: int, deadline: float):
    # getaddrinfo has no timeout API. A late resolver result cannot connect or
    # publish bytes; the daemon only puts its result in this private queue.
    result = queue.Queue(maxsize=1)
    def run():
        try:
            result.put((socket.getaddrinfo(host, port, type=socket.SOCK_STREAM), None))
        except Exception as exc:
            result.put((None, exc))
    threading.Thread(target=run, daemon=True, name="deep-read-dns").start()
    try:
        addresses, error = result.get(timeout=_remaining(deadline))
    except queue.Empty:
        raise TimeoutError("FETCH_TIMEOUT") from None
    if error is not None:
        raise UnsafeDestination("DESTINATION_UNAVAILABLE") from None
    if not addresses or any(family not in (socket.AF_INET, socket.AF_INET6) or not _public_ip(address[0])
                            for family, _, _, _, address in addresses):
        raise UnsafeDestination("DESTINATION_NOT_PUBLIC")
    return addresses[0]


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, secure, deadline):
        super().__init__(host, port, timeout=_remaining(deadline))
        self.address, self.secure, self.deadline = address, secure, deadline

    def connect(self):
        family, socktype, proto, _, address = self.address
        sock = socket.socket(family, socktype, proto)
        self.sock = sock
        try:
            sock.settimeout(_remaining(self.deadline))
            sock.connect(address)
            if self.secure:
                # The URL host, not the selected IP, is the certificate/SNI name.
                self.sock = ssl.create_default_context().wrap_socket(
                    sock, server_hostname=self.host, do_handshake_on_connect=False)
                self.sock.settimeout(_remaining(self.deadline))
                self.sock.do_handshake()
            self.sock.settimeout(_remaining(self.deadline))
        except BaseException:
            if self.sock is not None:
                self.sock.close()
            raise


def fetch(url: str, *, timeout: float, accept: str, proxy_url: str | None = None,
          max_bytes: int = 1_000_000) -> bytes:
    if proxy_url:
        raise UnsafeDestination("PROXY_DESTINATION_UNVERIFIABLE")
    deadline = time.monotonic() + timeout
    for hop in range(4):
        parts, host, port = _target(url)
        address = _resolve(host, port, deadline)
        connection = _PinnedConnection(host, port, address, parts.scheme == "https", deadline)
        def expire(connection=connection):
            sock = connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        timer = threading.Timer(_remaining(deadline), expire)
        timer.daemon = True
        timer.start()
        try:
            host_header = f"[{host}]" if ":" in host else host
            if port != (443 if parts.scheme == "https" else 80):
                host_header += f":{port}"
            _remaining(deadline)
            connection.request("GET", (parts.path or "/") + ("?" + parts.query if parts.query else ""),
                               headers={"Host": host_header, "Accept": accept,
                                        "User-Agent": "Vibe-Research deep-read", "Connection": "close"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or hop == 3:
                    raise UnsafeDestination("REDIRECT_NOT_ALLOWED")
                next_url = urljoin(url, location)
                next_parts, _, _ = _target(next_url)
                if parts.scheme == "https" and next_parts.scheme != "https":
                    raise UnsafeDestination("REDIRECT_NOT_ALLOWED")
                url = next_url
                continue
            if response.status < 200 or response.status >= 300:
                raise UnsafeDestination("ARTICLE_UNAVAILABLE")
            data = bytearray()
            while True:
                _remaining(deadline)
                chunk = response.read1(min(65536, max_bytes + 1 - len(data)))
                if not chunk:
                    _remaining(deadline)
                    return bytes(data)
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise UnsafeDestination("RESPONSE_TOO_LARGE")
        finally:
            timer.cancel()
            connection.close()
    raise UnsafeDestination("REDIRECT_NOT_ALLOWED")
