"""Shared API SSE contract; no external model or market access."""
import json

import pytest

import chat


def sse(value):
    return ("data: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode()


class Response:
    def __init__(self, *chunks):
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size=None):
        yield from self.chunks

    def close(self):
        self.closed = True


@pytest.mark.parametrize("failure", [
    sse({"choices": [{"delta": {}, "finish_reason": "length"}]}),
    sse({"choices": [{"delta": {}, "finish_reason": "content_filter"}]}),
    sse({"error": {"message": "secret-key https://private.test SQL"}}),
    b"data: {broken JSON\n\n",
])
def test_partial_then_failure_then_done_must_not_succeed(monkeypatch, failure):
    response = Response(sse({"choices": [{"delta": {"content": "partial"}}]}),
                        failure, b"data: [DONE]\n\n")
    monkeypatch.setattr(chat, "_call_llm_stream", lambda *a, **kw: response)
    events = []
    with pytest.raises(RuntimeError):
        for event in chat.stream_messages({}, [], use_tools=False):
            events.append(event)
    assert events == [{"type": "delta", "text": "partial"}]
    assert response.closed


def test_usage_heartbeat_utf8_split_and_done_without_finish_reason():
    payload = sse({"choices": [{"delta": {"content": "中文"}}]})
    split = payload.index("中".encode()) + 1
    response = Response(b": heartbeat\n\n", payload[:split], payload[split:],
                        sse({"choices": [], "usage": {"total_tokens": 2}}), b"data: [DONE]")
    assert list(chat._iter_sse_deltas(response)) == [{"content": "中文"}]
    assert response.closed


@pytest.mark.parametrize("choice", [
    {"delta": {"tool_calls": [{"id": "call"}]}},
    {"delta": {"function_call": {"name": "query_quote"}}},
    {"delta": {}, "finish_reason": "tool_calls"},
    {"delta": {}, "finish_reason": "function_call"},
])
def test_sync_no_tools_rejects_tool_requests(monkeypatch, choice):
    response = Response(sse({"choices": [choice]}), b"data: [DONE]\n")
    monkeypatch.setattr(chat, "_call_llm_stream", lambda *a, **kw: response)
    with pytest.raises(RuntimeError):
        list(chat.stream_messages({}, [], use_tools=False))
    assert response.closed


def test_generic_tool_round_still_executes_and_closes_each_response(monkeypatch):
    first = Response(sse({"choices": [{"delta": {"tool_calls": [
        {"id": "a", "function": {"name": "query_quote", "arguments": '{"codes":["000001"]}'}}
    ]}}]}), sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}), b"data: [DONE]\n")
    second = Response(sse({"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}),
                      b"data: [DONE]\n")
    responses = iter([first, second])
    executed = []
    monkeypatch.setattr(chat, "_call_llm_stream", lambda *a, **kw: next(responses))
    monkeypatch.setattr(chat, "_exec_tool", lambda name, args: executed.append((name, args)))
    result = list(chat.run_chat_stream({}, [{"role": "user", "content": "question"}]))
    assert executed == [("query_quote", {"codes": ["000001"]})]
    assert [event["type"] for event in result] == ["tool", "delta", "done"]
    assert result[-1]["rounds"] == 2
    assert first.closed and second.closed


@pytest.mark.parametrize("use_tools", [False, True])
def test_sync_generator_close_releases_response(monkeypatch, use_tools):
    response = Response(sse({"choices": [{"delta": {"content": "partial"}}]}))
    monkeypatch.setattr(chat, "_call_llm_stream", lambda *a, **kw: response)
    source = chat.stream_messages({}, [], use_tools=use_tools)
    assert next(source)["type"] == "delta"
    source.close()
    assert response.closed


def test_sync_done_does_not_read_keepalive(monkeypatch):
    class KeepaliveResponse(Response):
        def iter_content(self, chunk_size=None):
            yield sse({"choices": [{"delta": {"content": "complete"}}]})
            yield b"data: [DONE]\n\n"
            raise AssertionError("must not wait for server EOF after DONE")

    response = KeepaliveResponse()
    monkeypatch.setattr(chat, "_call_llm_stream", lambda *a, **kw: response)
    assert [event["type"] for event in chat.stream_messages({}, [])] == ["delta", "done"]
    assert response.closed


def test_sync_http_failure_closes_response(monkeypatch):
    response = Response()
    response.status_code = 500
    response.text = "upstream failure"
    monkeypatch.setattr(chat.requests, "post", lambda **kw: response)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        chat._call_llm_stream({"baseURL": "https://example.test", "model": "test", "apiKey": "test"}, [], False)
    assert response.closed
