"""Approved remediation regressions. Synthetic DNS/TCP/SDK only, never live models."""
import asyncio
import json
import socket
from dataclasses import replace
from pathlib import Path

import httpcore
import httpx
import pytest

import ai_credential_store as credentials
import ai_providers
import chat
import model_transport as transport
import native_intel_ai
import native_intel_filter


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("real TCP forbidden"))
    monkeypatch.setattr(transport.requests.utils, "get_environ_proxies", lambda *_: {})
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **_: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host if host[0].isdigit() else "8.8.8.8", port))])


def configured(provider="openai-compatible"):
    cfg = {"provider": provider, "model": "codex" if provider == "cli-codex" else "synthetic",
           "baseURL": "" if provider == "cli-codex" else "https://model.invalid/v1",
           "apiKey": "" if provider == "cli-codex" else "SYNTHETIC"}
    status = credentials.save(cfg, expected_revision=credentials.status()["revision"])
    return {**cfg, "revision": status["revision"]}


@pytest.mark.parametrize("provider", sorted(ai_providers.API_PROVIDERS | {"cli-codex"}))
def test_every_settings_provider_reaches_filter_dispatch(monkeypatch, provider):
    cfg = configured(provider)
    observed = []
    monkeypatch.setattr(chat, "stream_messages", lambda value, *a, **k: observed.append(value) or iter([{"type": "delta", "text": "[]"}, {"type": "done"}]))
    assert native_intel_filter._invoke_llm_text(cfg, []) == "[]"
    assert observed[0]["provider"] == provider
    assert credentials.dispatch_config(observed[0])["revision"] == cfg["revision"]


def test_provider_registry_matches_actual_frontend_options():
    text = (Path(__file__).parents[2] / "frontend/src/lib/ai-models.ts").read_text()
    import re
    values = set(re.findall(r'^  \| "([^"]+)"', text, re.M))
    assert values == ai_providers.API_PROVIDERS | {"cli-codex"}


def test_stale_clear_tamper_and_revisionless_dispatch_fail_closed():
    cfg = configured()
    assert credentials.dispatch_config(cfg)["apiKey"] == "SYNTHETIC"
    for candidate in [{**cfg, "revision": None}, {**cfg, "model": "different"}]:
        with pytest.raises(credentials.CredentialStoreError): credentials.dispatch_config(candidate)
    credentials.delete(observed_revision=cfg["revision"])
    with pytest.raises(credentials.CredentialConflict): credentials.dispatch_config(cfg)


def test_clear_during_dns_preparation_prevents_transport(monkeypatch):
    cfg = configured()
    original = chat._stream_request
    def prepare(*args):
        request = original(*args)
        credentials.delete(observed_revision=cfg["revision"])
        return request
    monkeypatch.setattr(chat, "_stream_request", prepare)
    monkeypatch.setattr(transport, "post", lambda *a, **k: pytest.fail("stale dispatch"))
    with pytest.raises(chat.ModelTransportError, match="配置已变化"):
        chat._call_llm_stream(cfg, [], False)


def test_scheduled_config_retains_generation_and_unknown_codex_identity():
    cfg = configured("cli-codex")
    effective = native_intel_ai.get_effective_ai_config()
    assert effective["revision"] == cfg["revision"]
    assert effective["_task_budget"].max_calls == 2
    identity = ai_providers.execution_identity(effective)
    assert identity == {"runtimeFamily": "codex-subscription", "requestedModel": None, "resolvedModel": None, "model": "unknown/default"}


@pytest.mark.parametrize("public_mode,address,allowed", [
    (False, "127.0.0.1", True), (False, "192.168.0.2", True),
    (True, "127.0.0.1", False), (False, "169.254.169.254", False),
    (False, "::ffff:169.254.169.254", False), (False, "fe80::1", False),
    (False, "0.0.0.0", False), (True, "8.8.8.8", True),
])
def test_dns_alias_policy_in_both_deployment_modes(monkeypatch, public_mode, address, allowed):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (address, 443))])
    if allowed:
        assert transport.bind_endpoint("https://alias.invalid", public_mode=public_mode).address == address
    else:
        with pytest.raises(transport.EndpointError, match="BLOCKED"):
            transport.bind_endpoint("https://alias.invalid", public_mode=public_mode)


def test_all_dns_answers_validated_and_userinfo_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (ip, 443)) for ip in ["8.8.8.8", "169.254.169.254"]])
    with pytest.raises(transport.EndpointError): transport.bind_endpoint("https://mixed.invalid", public_mode=False)
    with pytest.raises(transport.EndpointError): transport.bind_endpoint("https://u:secret@model.invalid", public_mode=False)


def test_requests_tcp_is_numeric_but_tls_identity_is_original(monkeypatch):
    endpoint = transport.bind_endpoint("https://model.invalid", public_mode=True)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("second DNS lookup"))
    seen = []
    monkeypatch.setattr(transport, "create_connection", lambda addr, *a, **k: seen.append(addr) or object())
    adapter = transport.BoundAdapter(endpoint)
    pool = adapter.poolmanager.connection_from_url("https://model.invalid")
    connection = pool._new_conn()
    connection._new_conn()
    assert seen == [("8.8.8.8", 443)]
    assert connection.host == "model.invalid"
    assert connection.server_hostname is None  # urllib3 uses unchanged host for TLS/verification.


def test_proxy_policy_and_requests_numeric_connect(monkeypatch):
    monkeypatch.setattr(transport.requests.utils, "get_environ_proxies", lambda *_: {"https": "http://proxy.invalid:8080"})
    endpoint = transport.bind_endpoint("https://model.invalid", public_mode=True)
    url, headers = transport.proxy_request("https://model.invalid/v1/chat/completions", {}, endpoint)
    assert url == "https://8.8.8.8:443/v1/chat/completions"
    assert headers["Host"] == "model.invalid"
    manager = transport.BoundAdapter(endpoint).proxy_manager_for(endpoint.proxy_url)
    pool = manager.connection_from_url(url)
    conn = pool._new_conn()
    monkeypatch.setattr(conn, "connect", lambda: None)
    pool._prepare_proxy(conn)
    assert conn._tunnel_host == endpoint.address
    assert conn.server_hostname == conn.assert_hostname == "model.invalid"
    seen = []
    monkeypatch.setattr(transport, "create_connection", lambda addr, *a, **k: seen.append(addr) or object())
    conn._new_conn()
    assert seen == [(endpoint.proxy.address, 8080)]


@pytest.mark.parametrize("proxy_scheme", ["http", "https"])
def test_actual_httpcore_proxy_protocol_pins_connect_and_preserves_tls(monkeypatch, proxy_scheme):
    monkeypatch.setattr(transport.requests.utils, "get_environ_proxies", lambda *_: {"https": f"{proxy_scheme}://proxy.invalid:8080"})
    endpoint = transport.bind_endpoint("https://model.invalid/v1", public_mode=True)
    writes, names, connects = [], [], []
    class FakeStream(httpcore.AsyncNetworkStream):
        responses = [b"HTTP/1.1 200 Connection established\r\n\r\n", b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"]
        async def read(self, *args): return self.responses.pop(0)
        async def write(self, buffer, *args): writes.append(buffer)
        async def aclose(self): pass
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            names.append(server_hostname)
            assert ssl_context.check_hostname
            return self
        def get_extra_info(self, info): return None
    async def connect(self, host, port, **kwargs):
        connects.append((host, port))
        return FakeStream()
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    async def run():
        wire, headers = transport.proxy_request("https://model.invalid/v1/chat/completions", {}, endpoint)
        async with httpx.AsyncClient(transport=transport.async_transport(endpoint), trust_env=False) as client:
            response = await client.post(wire, headers=headers, json={"model": "synthetic"})
            assert response.json() == {}
    asyncio.run(run())
    assert connects == [(endpoint.proxy.address, 8080)]
    assert names == (["proxy.invalid"] if proxy_scheme == "https" else []) + ["model.invalid"]
    assert b"CONNECT 8.8.8.8:443 HTTP/1.1" in b"".join(writes)
    assert b"Host: model.invalid" in b"".join(writes)


def test_tool_budget_exhaustion_is_sticky():
    budget = chat.ModelTaskBudget(timeout=3, max_calls=2, max_tokens=10, max_chars=100, max_tools=1)
    budget.reserve_tool()
    with pytest.raises(chat.ModelTaskBudgetError): budget.reserve_tool()
    with pytest.raises(chat.ModelTaskBudgetError): budget.reserve_dispatch()


def test_request_json_cannot_grant_draft_probe_exemption():
    cfg = configured()
    credentials.delete(observed_revision=cfg["revision"])
    with pytest.raises(chat.ModelTransportError):
        chat._dispatch_config({**cfg, "_draft_connection_probe": True})


@pytest.mark.parametrize("proxy_scheme", ["http", "https"])
def test_actual_requests_proxy_protocol_uses_numeric_connect_and_verified_host(monkeypatch, proxy_scheme):
    import io
    from types import SimpleNamespace
    import urllib3.connection
    monkeypatch.setattr(transport.requests.utils, "get_environ_proxies", lambda *_: {"https": f"{proxy_scheme}://proxy.invalid:8080"})
    endpoint = transport.bind_endpoint("https://model.invalid/v1", public_mode=True)
    writes, names, connects = [], [], []
    class FakeSocket:
        def settimeout(self, value): pass
        def sendall(self, value): writes.append(value)
        def makefile(self, *_a, **_k):
            if writes[-1].startswith(b"CONNECT"):
                return io.BytesIO(b"HTTP/1.1 200 Connection established\r\n\r\n")
            return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        def close(self): pass
    def connect(address, *a, **k):
        connects.append(address)
        return FakeSocket()
    def tls(*args, **kwargs):
        if args: kwargs["sock"] = args[0]
        names.append(kwargs["server_hostname"])
        assert kwargs["cert_reqs"] in ("CERT_REQUIRED", 2)
        if kwargs["server_hostname"] == "model.invalid":
            assert kwargs["assert_hostname"] == "model.invalid"
        return SimpleNamespace(socket=kwargs["sock"], is_verified=True)
    monkeypatch.setattr(transport, "create_connection", connect)
    monkeypatch.setattr(urllib3.connection, "_ssl_wrap_socket_and_match_hostname", tls)
    response = transport.post("https://model.invalid/v1/chat/completions", endpoint=endpoint,
                              json={"model": "synthetic"}, timeout=1, allow_redirects=False)
    assert response.json() == {}
    response.close()
    assert connects == [(endpoint.proxy.address, 8080)]
    assert names == (["proxy.invalid"] if proxy_scheme == "https" else []) + ["model.invalid"]
    assert b"CONNECT 8.8.8.8:443 HTTP/1.0" in b"".join(writes)
    assert b"Host: model.invalid" in b"".join(writes)

@pytest.mark.parametrize('events', [[{'type': 'done'}, {'type': 'done'}], [{'type': 'done'}, {'type': 'delta', 'text': 'late'}]])
def test_runtime_does_not_publish_success_before_clean_eof(monkeypatch, events):
    import agent_runtime
    import threading
    from contextlib import contextmanager
    cfg = configured('cli-codex')
    class Response:
        status_code = 200
        def iter_lines(self):
            return iter(json.dumps(event).encode() for event in events)
    @contextmanager
    def request(*a, **kw): yield Response()
    monkeypatch.setattr(agent_runtime, '_request', request)
    observed = []
    with pytest.raises(agent_runtime.AgentRuntimeError):
        for event in agent_runtime.stream_chat(session='synthetic', message='test', context='', cancel_event=threading.Event(), config=cfg):
            observed.append(event)
    assert observed == []


def test_model_cache_identity_tracks_model_endpoint_and_generation():
    cfg = configured()
    base = native_intel_filter.get_provider_identity(cfg)
    for change in ({'model': 'different'}, {'baseURL': 'https://other.invalid/v1'}, {'revision': '999'}):
        assert native_intel_filter.get_provider_identity({**cfg, **change}) != base
    assert cfg['baseURL'] not in base and cfg['apiKey'] not in base
