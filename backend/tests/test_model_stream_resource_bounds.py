"""Bounded synthetic provider streams; no real model, credential or user data."""
import asyncio
from dataclasses import replace
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock

import httpx
import pytest

import chat
from model_stream_phase_fixtures import isolate_stream_phase


CFG = {"provider": "openai-compatible", "baseURL": "https://example.test/v1",
       "model": "synthetic", "apiKey": "synthetic-not-a-key"}
ANSWER = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
DONE = b"data: [DONE]\n\n"


class SyncResponse:
    headers = {}

    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.chunk_size = None

    def iter_content(self, chunk_size=None):
        self.chunk_size = chunk_size
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    def close(self):
        pass


def oversized_comment():
    # No answer text to consume the existing parsed-output budget.
    yield b":"
    for _ in range(258):
        yield b"x" * 4096
    yield b"\n"
    yield ANSWER
    yield DONE


def test_sync_unterminated_raw_line_is_bounded_before_answer():
    response = SyncResponse(oversized_comment())
    with pytest.raises(chat.ModelTransportError, match="限制"):
        list(chat._iter_sse_deltas(response))
    assert response.reads <= 258


def test_normal_async_unterminated_raw_line_is_bounded(monkeypatch):
    closed = []
    reads = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for raw in oversized_comment():
                reads.append(len(raw))
                yield raw

        async def aclose(self):
            closed.append(True)

    def handler(request):
        return httpx.Response(200, stream=Body())

    isolate_stream_phase(monkeypatch, handler)
    monkeypatch.setattr(chat, "_dispatch_config", lambda cfg: cfg)
    monkeypatch.setattr(chat, "_check_base_url", lambda *_: None)
    monkeypatch.setattr(chat.model_transport, "proxy_request", lambda url, headers, endpoint: (url, headers))
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(chat, "_TASK_STREAM_SLOTS", slots)

    async def run():
        events = []
        with pytest.raises(chat.ModelTransportError, match="限制"):
            async for event in chat.stream_api_messages(CFG, []):
                events.append(event)
        assert events == []

    asyncio.run(run())
    assert len(reads) <= 258
    assert closed == [True]
    assert slots.acquire(blocking=False)
    slots.release()


@pytest.mark.parametrize("kind", ["oversized_line", "heartbeat_body", "invalid_utf8", "compressed"])
def test_sync_raw_resource_failures_are_sanitized(monkeypatch, kind):
    monkeypatch.setattr(chat, "MODEL_STREAM_LIMITS", replace(chat.MODEL_STREAM_LIMITS,
                        body_bytes=128, line_bytes=64))
    chunks = {
        "oversized_line": [b":" + b"x" * 64],
        "heartbeat_body": [b": heartbeat\n" * 12],
        "invalid_utf8": [b"data: \xff\n"],
        "compressed": [b"private upstream compressed bytes"],
    }[kind]
    response = SyncResponse(chunks)
    if kind == "compressed":
        response.headers = {"content-encoding": "gzip"}
    with pytest.raises(chat.ModelTransportError) as error:
        list(chat._iter_sse_deltas(response))
    assert "private" not in str(error.value)
    if kind == "compressed":
        assert response.reads == 0


def test_line_and_body_boundaries_preserve_utf8_and_done(monkeypatch):
    answer = ("data: " + json.dumps({"choices": [{"delta": {"content": "中🙂"}}]},
                                  ensure_ascii=False) + "\r\n\r\n").encode()
    wire = answer + DONE
    monkeypatch.setattr(chat, "MODEL_STREAM_LIMITS", replace(chat.MODEL_STREAM_LIMITS,
                        body_bytes=len(wire), line_bytes=len(answer.rstrip(b"\r\n"))))
    response = SyncResponse(bytes([byte]) for byte in wire)
    assert list(chat._iter_sse_deltas(response)) == [{"content": "中🙂"}]
    assert response.chunk_size == 4096


def test_largest_existing_answer_budget_fits_single_escaped_json_event():
    # Worst-case JSON representation of one 48,000-character ordinary answer:
    # supplementary Unicode uses two six-byte surrogate escapes per character.
    text = "🙂" * 48000
    payload = ("data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n").encode()
    assert 576000 < len(payload) < chat.MODEL_STREAM_LIMITS.line_bytes
    response = SyncResponse([payload, DONE])
    assert list(chat._iter_sse_deltas(response)) == [{"content": text}]


def test_partial_then_raw_limit_never_saves_daily_review_result(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import app
    from test_daily_review_ai_api import _prepared

    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(chat, "_dispatch_config", lambda cfg: cfg)
    monkeypatch.setattr(chat, "prepare_daily_review_analysis", lambda *_: _prepared())
    monkeypatch.setattr(chat, "MODEL_STREAM_LIMITS", replace(chat.MODEL_STREAM_LIMITS, line_bytes=128))
    response = SyncResponse([ANSWER, b":" + b"x" * 128, DONE])
    monkeypatch.setattr(chat, "_call_llm_stream", lambda *_: response)
    save = MagicMock(side_effect=AssertionError("incomplete response must not be saved"))
    monkeypatch.setattr(app.ai_result_service, "save_daily_review_ai", save)
    result = TestClient(app.app).post("/api/daily-review/analyze", json={"llm": CFG})
    assert result.status_code == 200
    events = [json.loads(line) for line in result.text.splitlines()]
    assert [event["type"] for event in events] == ["delta", "error"]
    assert events[0]["text"] == "ok"
    assert events[-1]["message"] == "对话失败：每日复盘AI生成或保存失败"
    save.assert_not_called()
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("finish", ["cancel", "deadline", "oversized"])
def test_real_loopback_http_transport_closes_socket_and_releases_slot(monkeypatch, finish):
    """Exercise pinned HTTPX/httpcore/AnyIO, not a fake response's aclose."""
    monkeypatch.setattr(chat, "_dispatch_config", lambda cfg: cfg)
    monkeypatch.setattr(chat, "_PUBLIC_MODE", False)
    monkeypatch.setattr(chat.model_transport.requests.utils, "get_environ_proxies", lambda *_: {})
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(chat, "_TASK_STREAM_SLOTS", slots)
    if finish == "oversized":
        monkeypatch.setattr(chat, "MODEL_STREAM_LIMITS", replace(chat.MODEL_STREAM_LIMITS,
                            line_bytes=128))

    async def run():
        peer_closed = asyncio.Event()
        body_sent = asyncio.Event()
        handler_done = asyncio.Event()
        requests = []

        async def handle(reader, writer):
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                requests.append(headers)
                content_length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                                      if line.lower().startswith(b"content-length:"))
                await reader.readexactly(content_length)
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                             b"Connection: close\r\n\r\n")
                writer.write(b":" + b"x" * 256 if finish == "oversized" else ANSWER)
                await writer.drain()
                body_sent.set()
                # Keep the stream open without DONE to exercise actual read
                # cancellation/timeout and peer-visible socket shutdown.
                if await reader.read() == b"":
                    peer_closed.set()
            finally:
                writer.close()
                await writer.wait_closed()
                handler_done.set()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        task_budget = chat.ModelTaskBudget(timeout=0.25 if finish == "deadline" else 2,
                                         max_calls=1, max_tokens=32, max_chars=1024)
        cfg = {**CFG, "baseURL": f"http://127.0.0.1:{port}/v1", "_task_budget": task_budget}
        events = []

        async def consume():
            async for event in chat.stream_api_messages(cfg, []):
                events.append(event)

        try:
            started = time.monotonic()
            task = asyncio.create_task(consume())
            await asyncio.wait_for(body_sent.wait(), 2)
            if finish == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(chat.ModelTransportError):
                    await task
            await asyncio.wait_for(peer_closed.wait(), 1)
            await asyncio.wait_for(handler_done.wait(), 1)
            assert time.monotonic() - started < 2
            assert all(event["type"] != "done" for event in events)
            assert len(requests) == 1
            assert b"accept-encoding: identity\r\n" in requests[0].lower()
            assert slots.acquire(blocking=False)
            slots.release()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


@pytest.mark.parametrize("chunked", [False, True])
def test_real_requests_exposes_small_token_before_next_network_chunk(monkeypatch, chunked):
    """A byte cap must not turn token streaming into 4 KiB/EOF buffering."""
    monkeypatch.setattr(chat, "_dispatch_config", lambda cfg: cfg)
    monkeypatch.setattr(chat, "_PUBLIC_MODE", False)
    monkeypatch.setattr(chat.model_transport.requests.utils, "get_environ_proxies", lambda *_: {})
    continue_stream = threading.Event()
    peer_done = threading.Event()
    received = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            received.append(self.headers.get("Accept-Encoding"))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            def send(raw):
                self.wfile.write((f"{len(raw):x}\r\n".encode() + raw + b"\r\n") if chunked else raw)
                self.wfile.flush()
            try:
                send(ANSWER)
                continue_stream.wait(1)
                send(DONE)
                if chunked:
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
            finally:
                peer_done.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = {**CFG, "baseURL": f"http://127.0.0.1:{server.server_port}/v1"}
    response = chat._call_llm_stream(cfg, [], False)
    source = chat._iter_sse_deltas(response)
    try:
        started = time.monotonic()
        assert next(source) == {"content": "ok"}
        assert time.monotonic() - started < 0.5
        assert not peer_done.is_set()
        continue_stream.set()
        assert list(source) == []
        assert received == ["identity"]
    finally:
        continue_stream.set()
        source.close()
        response.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
