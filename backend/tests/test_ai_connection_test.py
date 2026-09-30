"""Synthetic connection probes: mocked HTTP only, no user state or real models."""
import asyncio
from dataclasses import replace
import json
import threading
from unittest.mock import MagicMock

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

import app as app_module
import chat

URL = "/api/ai/connection-test"
LLM = {"provider": "api-compatible", "model": "synthetic-model",
       "baseURL": "https://example.test/v1", "apiKey": "synthetic-key"}
DONE = {"type": "done", "trace": [], "rounds": 1}
ERROR = {"type": "error", "message": "模型连接测试失败，请检查配置后重试"}


def sse(text="Connected", **choice):
    return ("data: " + json.dumps({"choices": [{"delta": {"content": text}, **choice}]}) + "\n\n").encode()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(chat, "_PUBLIC_MODE", False)
    blocked = MagicMock(side_effect=AssertionError("private/state/runtime access forbidden"))
    for module, name in [(app_module.daily_review, "get_daily_review_for_display"),
                         (app_module.daily_review, "generate_daily_review"),
                         (chat, "prepare_daily_review_analysis"),
                         (app_module.ai_result_service, "save_daily_review_ai"),
                         (app_module.agent_runtime, "status"),
                         (chat.agent_runtime, "stream_chat"),
                         (chat, "_exec_tool"), (chat, "_call_llm_stream"),
                         (app_module.pf, "get_portfolio"),
                         (app_module.pf, "get_portfolio_holdings_snapshot"),
                         (app_module.account_profile, "load_account_profile"),
                         (app_module.account_profile, "save_account_profile"),
                         (app_module.review_history, "save_current_daily_review"),
                         (app_module.review_history, "get_review_history_snapshot") ]:
        monkeypatch.setattr(module, name, blocked)
    network = MagicMock(side_effect=AssertionError("external HTTP forbidden"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", network)
    yield
    blocked.assert_not_called()
    network.assert_not_called()
    assert not list(tmp_path.rglob("*"))


def post(llm=None, **extra):
    return TestClient(app_module.app).post(URL, json={"llm": llm or LLM, **extra})


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines()]


def transport(monkeypatch, chunks, *, status=200, headers=None, keepalive=False):
    seen, closed = [], []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in chunks:
                yield chunk
            if keepalive:
                await asyncio.Event().wait()

        async def aclose(self):
            closed.append(True)

    def handle(request):
        seen.append(request)
        return httpx.Response(status, headers=headers, stream=Body())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(chat.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    return seen, closed


@pytest.mark.parametrize("base", [LLM["baseURL"], "https://opencode.ai/zen/go/v1"])
def test_one_post_fixed_prompt_budget_headers_no_output_or_state(monkeypatch, base):
    seen, closed = transport(monkeypatch, [sse("任意简短回复"), b"data: [DONE]\n\n"], keepalive=True)
    assert events(post({**LLM, "baseURL": base})) == [DONE]
    assert len(seen) == 1 and closed == [True]
    request = seen[0]
    assert request.method == "POST" and str(request.url) == base + "/chat/completions"
    assert json.loads(request.content) == {"model": LLM["model"], "messages": chat.CONNECTION_TEST_MESSAGES,
                                          "temperature": 0.3, "stream": True, "max_tokens": 32}
    assert request.headers["authorization"] == "Bearer synthetic-key"
    assert request.headers["accept-encoding"] == "identity"
    if "opencode.ai" in base:
        assert request.headers["user-agent"] == "Vibe-Research/1.0"
        assert len(request.headers["x-opencode-session"]) == 64
    else:
        assert "x-opencode-session" not in request.headers


@pytest.mark.parametrize("provider", ["cli-codex", " cli-anything "])
def test_cli_rejected_before_readiness_runtime_or_http(provider):
    assert post({**LLM, "provider": provider}).status_code == 400


@pytest.mark.parametrize("field", ["model", "apiKey", "baseURL"])
def test_missing_config_no_http(field):
    assert post({**LLM, field: " "}).status_code == 400


@pytest.mark.parametrize("field", ["messages", "context", "holdings", "history", "max_tokens", "limits"])
def test_top_level_injection_rejected(field):
    assert post(**{field: "private sentinel"}).status_code == 422


def test_auth_failure_is_http_not_model_failure(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "synthetic-app-key")
    assert post().status_code == 401


@pytest.mark.parametrize("base", ["file:///tmp/private", "https://169.254.169.254/v1", "https://[::ffff:169.254.169.254]/v1"])
def test_invalid_url_no_http(base):
    response = post({**LLM, "baseURL": base})
    if base.startswith("file:"):
        assert response.status_code == 400
    else:
        assert events(response) == [ERROR]


@pytest.mark.parametrize("chunks", [
    [b"data: [DONE]\n\n"], [sse("   "), b"data: [DONE]\n\n"],
    [sse(), b""], [b"data: invalid-json\n\n"],
    [sse(), sse("", finish_reason="length"), b"data: [DONE]\n\n"],
    [b'data: {"choices":[{"delta":{"refusal":"private"}}]}\n\n'],
    [b'data: {"choices":[{"delta":{"tool_calls":[{}]}}]}\n\n'],
    [b'data: {"choices":[{"delta":{"function_call":{"name":"x"}}}]}\n\n'],
    [sse("x" * 1025), b"data: [DONE]\n\n"],
    [b":" + b"x" * 16384], [b": x\n" * 17000],
    [b"data: \xff\n\n"], [b'data: {"error":{"message":"PRIVATE KEY URL"}}\n\n'],
])
def test_malformed_refused_oversized_or_incomplete_fail_closed(monkeypatch, chunks):
    seen, closed = transport(monkeypatch, chunks)
    assert events(post()) == [ERROR]
    assert len(seen) == 1 and closed == [True]


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate"])
def test_compression_rejected_before_decoding(monkeypatch, encoding):
    seen, closed = transport(monkeypatch, [b"bad compressed bytes"], headers={"content-encoding": encoding})
    assert events(post()) == [ERROR]
    assert len(seen) == 1 and closed == [True]


@pytest.mark.parametrize("status", [301, 307, 401, 429, 500])
def test_provider_status_is_sanitized_stream_error_no_redirect_or_retry(monkeypatch, status):
    seen, closed = transport(monkeypatch, [b"PRIVATE PROVIDER"], status=status,
                             headers={"location": "https://private.test/redirect"})
    assert events(post()) == [ERROR]
    assert len(seen) == 1 and closed == [True]


def test_utf8_split_across_raw_chunks(monkeypatch):
    raw = sse("好").replace(b"\\u597d", "好".encode()) + b"data: [DONE]\n\n"
    transport(monkeypatch, [bytes([byte]) for byte in raw])
    assert events(post()) == [DONE]


@pytest.mark.parametrize("phase", ["headers", "body", "close"])
def test_deadline_and_cleanup_are_bounded(monkeypatch, phase):
    limits = replace(chat.CONNECTION_TEST_LIMITS, timeout=0.05, cleanup_grace=0.01)
    monkeypatch.setattr(chat, "CONNECTION_TEST_LIMITS", limits)

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            if phase == "body":
                await asyncio.Event().wait()
            yield sse() + b"data: [DONE]\n\n"

        async def aclose(self):
            if phase == "close":
                await asyncio.Event().wait()

    async def handle(request):
        if phase == "headers":
            await asyncio.Event().wait()
        return httpx.Response(200, stream=Body())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(chat.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))

    async def exercise():
        async def run():
            return [event async for event in chat.stream_api_messages(LLM, chat.CONNECTION_TEST_MESSAGES, limits=limits)]
        if phase == "close":
            assert (await asyncio.wait_for(run(), 1))[-1] == DONE
        else:
            with pytest.raises(chat.ModelTransportError):
                await asyncio.wait_for(run(), 1)
    asyncio.run(exercise())


def test_dns_deadline_never_opens_client_after_worker_finishes(monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def resolve(*args):
        started.set()
        try:
            release.wait(2)
            return [(None, None, None, None, ("93.184.216.34", 443))]
        finally:
            finished.set()

    monkeypatch.setattr(chat, "_PUBLIC_MODE", True)
    monkeypatch.setattr(chat.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(chat, "CONNECTION_TEST_LIMITS", replace(chat.CONNECTION_TEST_LIMITS, timeout=0.05))
    try:
        assert events(post()) == [ERROR]
        assert started.is_set() and not finished.is_set()
    finally:
        release.set()
        assert finished.wait(2)


@pytest.mark.parametrize("phase", ["headers", "body", "send_failure"])
def test_asgi_disconnect_cancels_pending_transport_and_closes(monkeypatch, phase):
    async def exercise():
        reading, cancelled, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                if phase == "body":
                    try:
                        reading.set()
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                yield sse() + b"data: [DONE]\n\n"

            async def aclose(self):
                await anyio.sleep(0)
                closed.set()

        async def handle(request):
            if phase == "headers":
                try:
                    reading.set()
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return httpx.Response(200, stream=Body())

        real_client = httpx.AsyncClient
        monkeypatch.setattr(chat.httpx, "AsyncClient",
                            lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
        sent, body_sent = [], False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": json.dumps({"llm": LLM}).encode()}
            await reading.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if phase == "send_failure" and message.get("body"):
                raise OSError("client gone")

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                 "http_version": "1.1", "method": "POST", "scheme": "http", "path": URL,
                 "raw_path": URL.encode(), "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
                 "client": ("127.0.0.1", 1234), "server": ("testserver", 80), "state": {}}
        if phase == "send_failure":
            with pytest.raises(OSError, match="client gone"):
                await asyncio.wait_for(app_module.app(scope, receive, send), 1)
        else:
            await asyncio.wait_for(app_module.app(scope, receive, send), 1)
            assert cancelled.is_set()
            assert not any(message.get("body") for message in sent)
        if phase != "headers":
            assert closed.is_set()
    asyncio.run(exercise())


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout])
def test_network_failure_is_fixed_safe_error(monkeypatch, failure):
    attempts = []

    async def handle(request):
        attempts.append(request)
        raise failure("PRIVATE KEY https://private.test SQL traceback")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(chat.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    assert events(post()) == [ERROR]
    assert len(attempts) == 1


def test_generated_character_budget_is_cumulative(monkeypatch):
    transport(monkeypatch, [sse("x" * 600), sse("y" * 425), b"data: [DONE]\n\n"])
    assert events(post()) == [ERROR]


def test_body_and_line_budgets_are_cumulative(monkeypatch):
    # Repeated small raw chunks must not evade the newline-free line bound.
    transport(monkeypatch, [b":" + b"x" * 4096, b"x" * 4096, b"x" * 4096, b"x" * 4096])
    assert events(post()) == [ERROR]


@pytest.mark.parametrize("url", [
    r"https://trusted.example\@other.example/v1", "https://trusted.example\n@other.example/v1",
    "https://user:password@example.test/v1", "https://@example.test/v1",
    "https://example.test/v1?", "https://example.test/v1#", "https://example.test/v1?key=fixture",
    "http://0xa9fea9fe/v1", "http://2852039166/v1", "http://169.254.169.254./v1",
    "http://0177.0.0.1/v1", "https://%65xample.test/v1", "https://example.test:bad/v1",
])
def test_ambiguous_probe_url_rejected_before_transport(monkeypatch, url):
    source = MagicMock(side_effect=AssertionError("transport must not start"))
    monkeypatch.setattr(chat, "stream_api_messages", source)
    response = post({**LLM, "baseURL": url})
    assert response.status_code == 400
    assert "格式无效" in response.json()["detail"]
    assert url not in response.text
    source.assert_not_called()


def test_cr_only_sse_lines_are_supported_with_the_same_budgets(monkeypatch):
    transport(monkeypatch, [(sse() + b"data: [DONE]\n\n").replace(b"\n", b"\r")])
    assert events(post()) == [DONE]
