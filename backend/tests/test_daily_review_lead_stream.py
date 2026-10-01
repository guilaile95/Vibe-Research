"""Exercise real lead ASGI -> HTTPX -> local TCP cancellation and SSE failures."""
import asyncio
import json
import threading
from types import SimpleNamespace

import anyio
import httpx
import pytest

import app as app_module
import chat
from test_chat_sse_stream import sse
from test_daily_review_lead_api import LLM, URL, events, isolated, post  # noqa: F401


_REAL_HTTP_REQUEST = httpx.AsyncHTTPTransport.handle_async_request


def scope():
    return {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "POST", "scheme": "http", "path": URL,
            "raw_path": URL.encode(), "query_string": b"", "root_path": "",
            "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1234), "server": ("testserver", 80), "state": {}}


@pytest.mark.parametrize("phase", ["before_headers", "body_pause", "done_keepalive"])
def test_loopback_closes_upstream_on_disconnect_or_done(monkeypatch, phase):
    """Peer EOF proves the network read stopped, not just the browser output."""
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _REAL_HTTP_REQUEST)
    monkeypatch.setattr(chat, "_PUBLIC_MODE", False)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(chat.httpx, "AsyncClient", lambda **kw: real_client(trust_env=False, **kw))

    async def exercise():
        request_received = asyncio.Event()
        delta_sent = asyncio.Event()
        peer_closed = asyncio.Event()
        server_tasks = []
        sent = []

        async def upstream(reader, writer):
            server_tasks.append(asyncio.current_task())
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                size = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                            if line.lower().startswith(b"content-length:"))
                payload = json.loads(await reader.readexactly(size))
                assert "tools" not in payload and payload["stream"] is True
                request_received.set()
                if phase != "before_headers":
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                                 b"Transfer-Encoding: chunked\r\nConnection: keep-alive\r\n\r\n")
                    data = sse({"choices": [{"delta": {"content": "partial"}}]})
                    if phase == "done_keepalive":
                        data += b"data: [DONE]\n\n"
                    writer.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                    await writer.drain()
                # Intentionally never finish HTTP body or respond with headers.
                # Only cancellation / [DONE] may make the client close the socket.
                assert await reader.read() == b""
                peer_closed.set()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        body = json.dumps({"kind": "emotion", "llm": {**LLM, "baseURL": f"http://127.0.0.1:{port}"}}).encode()
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            if phase == "before_headers":
                await request_received.wait()
            elif phase == "body_pause":
                await delta_sent.wait()
            else:
                await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if b'"type": "delta"' in message.get("body", b""):
                delta_sent.set()

        try:
            await asyncio.wait_for(app_module.app(scope(), receive, send), timeout=3)
            await asyncio.wait_for(peer_closed.wait(), timeout=3)
            await asyncio.gather(*server_tasks)
        finally:
            server.close()
            await server.wait_closed()
            for task in server_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*server_tasks, return_exceptions=True)
        result = [json.loads(line) for message in sent
                  for line in message.get("body", b"").splitlines()]
        assert result[0]["type"] == "lead_context"
        assert all(event["type"] != "error" for event in result)
        if phase == "done_keepalive":
            assert [event["type"] for event in result] == ["lead_context", "delta", "done"]
        else:
            assert all(event["type"] != "done" for event in result)
        if phase == "before_headers":
            assert len(result) == 1

    asyncio.run(exercise())


def test_async_transport_preserves_go_headers_and_no_tools(monkeypatch):
    cfg = {**LLM, "baseURL": "https://opencode.ai/zen/go/v1", "_session": "lead-session"}
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://opencode.ai/zen/go/v1/chat/completions"
        assert request.headers["user-agent"] == "Vibe-Research/1.0"
        assert request.headers["x-opencode-session"] == chat._request_headers(cfg)["x-opencode-session"]
        assert request.headers["x-opencode-session"] != cfg["_session"]
        payload = json.loads(request.content)
        assert "tools" not in payload and "tool_choice" not in payload
        assert request.extensions["timeout"]["connect"] == chat._CONNECT_TIMEOUT
        assert request.extensions["timeout"]["read"] == chat._READ_TIMEOUT
        return httpx.Response(200, content=sse({"choices": [{"delta": {"content": "answer"}}]})
                              + b"data: [DONE]\n\n")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(chat.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    async def exercise():
        return [event async for event in chat.stream_api_messages(cfg, [])]

    assert [event["type"] for event in asyncio.run(exercise())] == ["delta", "done"]
    assert len(requests) == 1


@pytest.mark.parametrize("phase", ["before_headers", "body_pause", "trickling"])
def test_async_total_deadline_bounds_headers_body_and_trickling(monkeypatch, phase):
    monkeypatch.setattr(chat, "_TURN_TIMEOUT", 0.05)
    started = asyncio.Event()
    reading = asyncio.Event()
    closed = []
    interrupted = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                started.set()
                while True:
                    yield sse({"choices": [{"delta": {"content": "partial"}}]})
                    if phase == "body_pause":
                        await asyncio.Event().wait()
                    reading.set()
                    # 50 ms expires inside a read, not between 7 ms chunks.
                    await anyio.sleep(0.007)
            finally:
                interrupted.append(True)

        async def aclose(self):
            await anyio.sleep(0)
            closed.append(True)

    async def handler(request):
        if phase == "before_headers":
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                interrupted.append(True)
        return httpx.Response(200, stream=Body())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(chat.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    async def exercise():
        loop = asyncio.get_running_loop()
        ticks = 0
        # Freeze elapsed time until the phase under test is entered. Request
        # preparation / client setup may take longer than 50 ms on a busy runner;
        # their cancellation is covered separately below. Keep real AnyIO cancel
        # scopes and HTTPX cleanup, driven by the same clock as _check_active.
        monkeypatch.setattr(loop, "time", lambda: ticks / 1000)
        monkeypatch.setattr(chat, "time", SimpleNamespace(monotonic=loop.time))

        async def advance_clock():
            nonlocal ticks
            await started.wait()
            while True:
                if phase == "trickling":
                    # Only advance while reading, preserving the cancellation
                    # assertion instead of expiring between yielded deltas.
                    await reading.wait()
                    reading.clear()
                for _ in range(7):
                    await asyncio.sleep(0)
                    ticks += 1

        result = []

        async def consume():
            async for event in chat.stream_api_messages(LLM, []):
                result.append(event)

        ticker = asyncio.create_task(advance_clock())
        try:
            with pytest.raises(chat.ModelTransportError, match="超时"):
                await asyncio.wait_for(consume(), timeout=1)
        finally:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
        assert started.is_set()
        assert all(event["type"] != "done" for event in result)
        if phase == "trickling":
            assert len(result) > 1
        assert interrupted == [True]
        assert closed == ([] if phase == "before_headers" else [True])

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["http", "connect", "read"])
def test_async_transport_failure_remains_sanitized(monkeypatch, failure):
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadError("PRIVATE-PROVIDER-SENTINEL")
            yield b""  # Keep the failing body an async iterator.

        async def aclose(self):
            closed.append(True)

    def handler(request):
        if failure == "connect":
            raise httpx.ConnectError("PRIVATE-PROVIDER-SENTINEL")
        return httpx.Response(401 if failure == "http" else 200, stream=Body())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(chat.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    async def exercise():
        with pytest.raises(chat.ModelTransportError) as caught:
            _ = [event async for event in chat.stream_api_messages(LLM, [])]
        assert "PRIVATE" not in str(caught.value)

    asyncio.run(exercise())
    assert closed == ([] if failure == "connect" else [True])


def test_async_pre_cancel_never_constructs_http_client(monkeypatch):
    cancelled = threading.Event()
    cancelled.set()
    monkeypatch.setattr(chat.httpx, "AsyncClient",
                        lambda **kw: pytest.fail("cancelled request must not open a client"))

    async def exercise():
        with pytest.raises(chat.ModelTransportError, match="停止"):
            _ = [event async for event in chat.stream_api_messages({**LLM, "_cancel_event": cancelled}, [])]

    asyncio.run(exercise())


@pytest.mark.parametrize("stop", ["disconnect", "deadline"])
def test_public_dns_preparation_does_not_block_cancellation(monkeypatch, stop):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def resolve(*args):
        try:
            started.set()
            assert release.wait(3)
            return [(None, None, None, None, ("93.184.216.34", 443))]
        finally:
            finished.set()

    monkeypatch.setattr(chat, "_PUBLIC_MODE", True)
    monkeypatch.setattr(chat.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(chat.httpx, "AsyncClient",
                        lambda **kw: pytest.fail("cancelled preparation must not open a client"))
    if stop == "deadline":
        monkeypatch.setattr(chat, "_TURN_TIMEOUT", 0.1)

    async def exercise():
        body_sent = False
        sent = []

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": json.dumps({"kind": "emotion", "llm": LLM}).encode()}
            if stop == "deadline":
                await asyncio.Event().wait()
            while not started.is_set():
                await anyio.sleep(0.001)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        await asyncio.wait_for(app_module.app(scope(), receive, send), timeout=2)
        result = [json.loads(line) for message in sent
                  for line in message.get("body", b"").splitlines()]
        expected = ["lead_context"] + (["error"] if stop == "deadline" else [])
        assert [event["type"] for event in result] == expected
        assert started.is_set() and not finished.is_set()

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        assert finished.wait(2)


@pytest.mark.parametrize("tail", [
    sse({"choices": [{"delta": {}, "finish_reason": "length"}]}),
    sse({"choices": [{"delta": {}, "finish_reason": "content_filter"}]}),
    sse({"choices": [{"delta": {}, "finish_reason": "error"}]}),
    sse({"error": {"message": "secret-key https://private.test SQL"}}),
    b"data: {broken JSON\n\n",
    sse({"choices": [{"delta": {"tool_calls": [{"id": "tool"}]}}]}),
    sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
    b"",  # EOF without [DONE], even with valid partial text
])
def test_real_async_sse_failure_is_safe_and_never_success(monkeypatch, tail):
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse({"choices": [{"delta": {"content": "partial"}}]})
            if tail:
                yield tail
                yield b"data: [DONE]\n\n"

        async def aclose(self):
            closed.append(True)

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))
    monkeypatch.setattr(chat.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    response = post()
    result = events(response)
    assert [event["type"] for event in result] == ["lead_context", "delta", "error"]
    assert result[-1]["message"] == "单条线索AI解读失败，请稍后重试"
    assert not any(secret in response.text for secret in ("secret-key", "private.test", "SQL"))
    assert closed == [True]


@pytest.mark.parametrize("stop", ["disconnect_during_read", "send_failure"])
def test_async_body_read_and_awaitable_close_finish_on_cancellation(monkeypatch, stop):
    async def exercise():
        reading = asyncio.Event()
        closed = asyncio.Event()
        read_cancelled = asyncio.Event()

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield sse({"choices": [{"delta": {"content": "partial"}}]})
                try:
                    reading.set()
                    await asyncio.Event().wait()
                finally:
                    read_cancelled.set()

            async def aclose(self):
                await anyio.sleep(0)  # Cleanup must survive an active ASGI cancel scope.
                closed.set()

        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(lambda req: httpx.Response(200, stream=Body()))
        monkeypatch.setattr(chat.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
        body_sent = False
        sent = []

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": json.dumps({"kind": "emotion", "llm": LLM}).encode()}
            await reading.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if stop == "send_failure" and b'"type": "delta"' in message.get("body", b""):
                raise OSError("client socket closed")

        if stop == "send_failure":
            # Starlette's outer middleware may surface the network send error.
            with pytest.raises(OSError, match="client socket closed"):
                await asyncio.wait_for(app_module.app(scope(), receive, send), 3)
        else:
            await asyncio.wait_for(app_module.app(scope(), receive, send), 3)
        assert closed.is_set()
        if stop == "disconnect_during_read":
            assert read_cancelled.is_set()
        chunks = b"".join(message.get("body", b"") for message in sent)
        assert b'"type": "done"' not in chunks and b'"type": "error"' not in chunks

    asyncio.run(exercise())
