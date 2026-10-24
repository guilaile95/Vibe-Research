"""DNS-bound model HTTP transports. No global resolver or TLS monkey-patches.

The original hostname remains the HTTP Host, TLS SNI and certificate identity;
only TCP connect uses a validated numeric address. HTTP/HTTPS proxies receive
numeric CONNECT/absolute targets, with independently pinned proxy TCP addresses.
SOCKS and unsupported proxy schemes fail closed; NO_PROXY remains supported.
Local mode supports loopback/private model servers, but never link-local,
unspecified or multicast addresses. Public mode requires globally routable IPs.
"""
from dataclasses import dataclass, field
import ipaddress
import os
import socket
from urllib.parse import urlsplit, urlunsplit

import httpcore
import httpx
import requests
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util.connection import create_connection


class EndpointError(ValueError):
    pass


@dataclass(frozen=True)
class BoundEndpoint:
    host: str
    port: int
    address: str
    scheme: str = "https"
    proxy: "BoundEndpoint | None" = None
    proxy_url: str | None = field(default=None, repr=False)

    def check(self, host, port):
        if host != self.host or port != self.port:
            raise EndpointError("MODEL_ENDPOINT_CHANGED")


def bind_endpoint(url, *, public_mode, _proxy=False):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.scheme not in {"http", "https"} or not host or (not _proxy and (parsed.username is not None or parsed.password is not None)) or parsed.fragment:
            raise ValueError()
        host = host.encode("idna").decode("ascii")
        if "%" in host or any(c.isspace() for c in host):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise EndpointError("MODEL_ENDPOINT_INVALID") from None
    proxy_url = None if _proxy else requests.utils.select_proxy(url, requests.utils.get_environ_proxies(url))
    proxy = None
    if proxy_url:
        if urlsplit(proxy_url).scheme not in {"http", "https"}:
            raise EndpointError("MODEL_PROXY_UNSUPPORTED: 仅支持可绑定地址的 HTTP/HTTPS 代理")
        proxy = bind_endpoint(proxy_url, public_mode=public_mode, _proxy=True)
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError:
        raise EndpointError("MODEL_DNS_UNAVAILABLE") from None
    if not addresses:
        raise EndpointError("MODEL_DNS_UNAVAILABLE")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        ip = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip
        if str(ip) in {"100.100.100.200", "fd00:ec2::254"} or ip.is_link_local or ip.is_unspecified or ip.is_multicast or (public_mode and not ip.is_global):
            raise EndpointError("MODEL_ENDPOINT_BLOCKED: Base URL 指向了不允许的地址")
    return BoundEndpoint(host, port, sorted(addresses)[0], parsed.scheme, proxy, proxy_url)


def _pinned_connection(base, endpoint, tls_host=None):
    class PinnedConnection(base):
        def __init__(self, *args, **kwargs):
            if issubclass(base, HTTPSConnection) and tls_host:
                kwargs.update(server_hostname=tls_host, assert_hostname=tls_host)
            super().__init__(*args, **kwargs)
        def _new_conn(self):
            endpoint.check(self.host, self.port)
            try:
                return create_connection((endpoint.address, endpoint.port), self.timeout,
                                         source_address=self.source_address,
                                         socket_options=self.socket_options)
            except OSError as exc:
                raise NewConnectionError(self, "Model connection failed") from exc
    return PinnedConnection


class BoundAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, endpoint):
        self.endpoint = endpoint
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)
        endpoint = self.endpoint
        class HTTPPool(HTTPConnectionPool):
            ConnectionCls = _pinned_connection(HTTPConnection, endpoint)
        class HTTPSPool(HTTPSConnectionPool):
            ConnectionCls = _pinned_connection(HTTPSConnection, endpoint)
        # Copy: urllib3's default mapping is shared across pool managers.
        self.poolmanager.pool_classes_by_scheme = {"http": HTTPPool, "https": HTTPSPool}

    def cert_verify(self, conn, url, verify, cert):
        if not verify:
            raise EndpointError("MODEL_TLS_VERIFICATION_REQUIRED")
        if self.endpoint.proxy and self.endpoint.proxy.scheme == "https" and self.endpoint.scheme == "http":
            # Requests otherwise sets CERT_NONE based on the HTTP target, even
            # though this pool's actual connection is TLS to an HTTPS proxy.
            url = self.endpoint.proxy_url
        return super().cert_verify(conn, url, verify, cert)

    def proxy_manager_for(self, proxy, **kwargs):
        if proxy != self.endpoint.proxy_url or self.endpoint.proxy is None:
            raise EndpointError("MODEL_PROXY_CHANGED")
        manager = super().proxy_manager_for(proxy, **kwargs)
        endpoint = self.endpoint.proxy
        tls_host = self.endpoint.host if self.endpoint.scheme == "https" else endpoint.host
        class HTTPPool(HTTPConnectionPool):
            ConnectionCls = _pinned_connection(HTTPConnection, endpoint)
        class HTTPSPool(HTTPSConnectionPool):
            ConnectionCls = _pinned_connection(HTTPSConnection, endpoint, tls_host)
        manager.pool_classes_by_scheme = {"http": HTTPPool, "https": HTTPSPool}
        return manager

    def send(self, request, **kwargs):
        p = urlsplit(request.url)
        expected = self.endpoint.address if self.endpoint.proxy else self.endpoint.host
        if p.hostname != expected or (p.port or (443 if p.scheme == "https" else 80)) != self.endpoint.port:
            raise EndpointError("MODEL_ENDPOINT_CHANGED")
        selected = requests.utils.select_proxy(request.url, kwargs.get("proxies", {}))
        if selected != self.endpoint.proxy_url:
            raise EndpointError("MODEL_PROXY_CHANGED")
        return super().send(request, **kwargs)


def proxy_request(url, headers, endpoint):
    if endpoint.proxy is None:
        return url, headers
    p = urlsplit(url)
    endpoint.check(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    address = f"[{endpoint.address}]" if ":" in endpoint.address else endpoint.address
    host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
    if endpoint.port != (443 if p.scheme == "https" else 80):
        host += f":{endpoint.port}"
    url = urlunsplit((p.scheme, f"{address}:{endpoint.port}", p.path, p.query, ""))
    return url, {**headers, "Host": host}


def post(url, *, endpoint, **kwargs):
    session = requests.Session()
    session.mount("https://", BoundAdapter(endpoint))
    session.mount("http://", BoundAdapter(endpoint))
    url, kwargs["headers"] = proxy_request(url, kwargs.get("headers", {}), endpoint)
    # Explicit routing avoids NO_PROXY being re-evaluated against the numeric
    # destination. Certificate validation is never disabled.
    session.trust_env = False
    if "verify" not in kwargs:
        kwargs["verify"] = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE") or True
    if endpoint.proxy_url:
        kwargs["proxies"] = {"http": endpoint.proxy_url, "https": endpoint.proxy_url}
    try:
        response = session.post(url, **kwargs)
    except BaseException:
        session.close()
        raise
    close = response.close
    def close_owned():
        try:
            close()
        finally:
            session.close()
    response.close = close_owned
    return response


class ProxyStream(httpcore.AsyncNetworkStream):
    """Restore TLS identity after numeric CONNECT, including TLS-in-TLS proxies."""
    def __init__(self, stream, endpoint, proxy_tls_done=False):
        self.stream, self.endpoint, self.proxy_tls_done = stream, endpoint, proxy_tls_done

    async def read(self, max_bytes, timeout=None):
        return await self.stream.read(max_bytes, timeout)

    async def write(self, buffer, timeout=None):
        return await self.stream.write(buffer, timeout)

    async def aclose(self):
        await self.stream.aclose()

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        ep = self.endpoint
        if ep.proxy.scheme == "https" and not self.proxy_tls_done:
            if server_hostname != ep.proxy.host:
                raise EndpointError("MODEL_PROXY_TLS_IDENTITY_CHANGED")
            name = ep.proxy.host
        else:
            if server_hostname != ep.address:
                raise EndpointError("MODEL_TLS_IDENTITY_CHANGED")
            name = ep.host
        stream = await self.stream.start_tls(ssl_context, name, timeout)
        return ProxyStream(stream, ep, True)


class BoundAsyncBackend(httpcore.AnyIOBackend):
    def __init__(self, endpoint):
        self.endpoint = endpoint

    async def connect_tcp(self, host, port, **kwargs):
        destination = self.endpoint.proxy or self.endpoint
        destination.check(host, port)
        stream = await super().connect_tcp(destination.address, port, **kwargs)
        return ProxyStream(stream, self.endpoint) if self.endpoint.proxy else stream


def async_transport(endpoint):
    transport = httpx.AsyncHTTPTransport(trust_env=True, retries=0,
        proxy=httpx.Proxy(endpoint.proxy_url) if endpoint.proxy_url else None)
    # httpx 0.25.2's transport has no public network_backend argument. Keep the
    # sole compatibility hook here, regression-tested against the pinned stack.
    transport._pool._network_backend = BoundAsyncBackend(endpoint)
    return transport
