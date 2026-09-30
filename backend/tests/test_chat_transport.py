"""Synthetic transport regression coverage. Never contacts a model provider."""
import asyncio
import json
import threading
from unittest.mock import patch

import pytest
import requests

import chat

CFG = {"provider": "openai-compatible", "baseURL": "https://opencode.ai/zen/go/v1",
       "model": "deepseek-v4.1-flash", "apiKey": "synthetic-not-a-key"}
DONE = b'data: [DONE]\n\n'


def frame(delta):
    return ('data: ' + json.dumps({'choices': [{'delta': delta}]}, ensure_ascii=False) + '\n\n').encode()


class Response:
    status_code = 200
    text = 'PRIVATE-PROVIDER-SENTINEL'

    def __init__(self, *chunks):
        self.chunks = chunks
        self.closed = threading.Event()

    def iter_content(self, chunk_size=None):
        yield from self.chunks

    def close(self):
        self.closed.set()


@pytest.mark.parametrize('payload', [
    b'data: {"error":{"message":"PRIVATE-PROVIDER-SENTINEL"}}\n',
    b'data: {broken}\n', b'data: []\n', b'data: {}\n',
    frame({'refusal': 'private refusal'}), b'', frame({'role': 'assistant'}),
])
@pytest.mark.parametrize('use_tools', [False, True])
def test_invalid_or_empty_stream_never_completes(payload, use_tools):
    response = Response(payload, DONE)
    with patch.object(chat, '_call_llm_stream', return_value=response):
        events = []
        with pytest.raises(chat.ModelTransportError) as error:
            for event in chat.stream_messages(CFG, [], use_tools=use_tools):
                events.append(event)
    assert not any(event['type'] == 'done' for event in events)
    assert 'PRIVATE' not in str(error.value)
    assert response.closed.is_set()


def test_usage_utf8_and_generator_close():
    raw = frame({'content': '中文🙂'}) + b'data: {"choices":[],"usage":{"total_tokens":9}}\r\n\r\n' + DONE
    response = Response(*(bytes([byte]) for byte in raw))
    with patch.object(chat, '_call_llm_stream', return_value=response):
        events = list(chat.stream_messages(CFG, []))
    assert events[0] == {'type': 'delta', 'text': '中文🙂'}
    assert events[-1]['type'] == 'done'
    assert response.closed.is_set()
    response = Response(frame({'content': 'first'}), DONE)
    with patch.object(chat, '_call_llm_stream', return_value=response):
        stream = chat.stream_messages(CFG, [])
        next(stream)
        stream.close()
    assert response.closed.is_set()


def test_pre_cancel_never_requests():
    cancelled = threading.Event()
    cancelled.set()
    with patch.object(chat, '_call_llm_stream') as request:
        with pytest.raises(chat.ModelTransportError, match='停止'):
            list(chat.stream_messages({**CFG, '_cancel_event': cancelled}, []))
    request.assert_not_called()


@pytest.mark.parametrize('deadline', [False, True])
def test_blocked_reader_closed_on_cancel_or_deadline(monkeypatch, deadline):
    cancelled = threading.Event()
    response = Response()
    def chunks(chunk_size=None):
        yield frame({'content': 'first'})
        if not deadline:
            cancelled.set()
        assert response.closed.wait(2), 'watchdog did not close upstream'
        yield frame({'content': 'late'})
    response.iter_content = chunks
    if deadline:
        monkeypatch.setattr(chat, '_TURN_TIMEOUT', .1)
    with patch.object(chat, '_call_llm_stream', return_value=response):
        stream = chat.stream_messages({**CFG, '_cancel_event': cancelled}, [])
        assert next(stream)['text'] == 'first'
        with pytest.raises(chat.ModelTransportError, match='超时' if deadline else '停止'):
            next(stream)
    assert response.closed.is_set()


def test_http_and_transport_errors_sanitized():
    response = Response()
    response.status_code = 401
    with patch.object(chat.requests, 'post', return_value=response):
        with pytest.raises(chat.ModelTransportError, match='HTTP 401') as error:
            chat._call_llm_stream(CFG, [], False)
    assert 'PRIVATE' not in str(error.value)
    assert response.closed.is_set()
    with patch.object(chat.requests, 'post', side_effect=requests.ConnectionError('PRIVATE URL / KEY')):
        with pytest.raises(chat.ModelTransportError) as error:
            chat._call_llm_stream(CFG, [], False)
    assert 'PRIVATE' not in str(error.value)


def test_go_headers_scoped_and_stable():
    cfg = {**CFG, '_session': 'same-conversation'}
    with patch.object(chat.requests, 'post', return_value=Response()) as request:
        chat._call_llm_stream(cfg, [], False).close()
    assert request.call_args.args[0] == 'https://opencode.ai/zen/go/v1/chat/completions'
    assert request.call_args.kwargs['timeout'] == (10, 120)
    headers = request.call_args.kwargs['headers']
    assert headers['User-Agent'] == 'Vibe-Research/1.0'
    assert headers['x-opencode-session'] == chat._request_headers(cfg)['x-opencode-session']
    assert headers['x-opencode-session'] != chat._request_headers({**cfg, '_session': 'other'})['x-opencode-session']
    for url in ['https://api.openai.com/v1', 'https://opencode.ai/zen/v1', 'https://opencode.ai.evil.test/zen/go/v1']:
        assert 'x-opencode-session' not in chat._request_headers({**cfg, 'baseURL': url})


def test_chat_route_hides_untrusted_exception():
    import app
    from fastapi.testclient import TestClient
    with patch.object(chat, 'run_chat_stream', side_effect=RuntimeError('PRIVATE-PROVIDER-SENTINEL')):
        response = TestClient(app.app).post('/api/chat', json={'messages': [{'role': 'user', 'content': 'hi'}], 'llm': CFG})
    assert 'PRIVATE' not in response.text
    assert json.loads(response.text)['type'] == 'error'


def test_route_disconnect_closes_blocking_response():
    import app
    response = Response()
    started = threading.Event()
    def chunks(chunk_size=None):
        yield frame({'content': 'first'})
        started.set()
        assert response.closed.wait(2)
        yield frame({'content': 'late'})
    response.iter_content = chunks
    async def run():
        route = app.chat(app.ChatReq(messages=[{'role': 'user', 'content': 'hi'}], llm=app.LLMConfig(**CFG)))
        sent = []
        async def send(message):
            sent.append(message)
        async def receive():
            while not started.is_set():
                await asyncio.sleep(.001)
            return {'type': 'http.disconnect'}
        await asyncio.wait_for(route({'type': 'http', 'asgi': {'version': '3.0'}}, receive, send), 3)
        assert response.closed.is_set()
        assert all(b'late' not in msg.get('body', b'') for msg in sent)
    with patch.object(chat, '_call_llm_stream', return_value=response):
        asyncio.run(run())


@pytest.mark.parametrize('ending', ['success', 'malformed', 'truncated', 'consumer-close'])
def test_stream_watchers_terminate_on_all_exits(monkeypatch, ending):
    threads = []
    original = threading.Thread
    def thread(*args, **kwargs):
        value = original(*args, **kwargs)
        threads.append(value)
        return value
    monkeypatch.setattr(chat.threading, 'Thread', thread)
    tail = DONE if ending == 'success' else b'data: {broken}\n' if ending == 'malformed' else b''
    response = Response(frame({'content': 'first'}), tail)
    with patch.object(chat, '_call_llm_stream', return_value=response):
        stream = chat.stream_messages(CFG, [])
        next(stream)
        if ending == 'consumer-close':
            stream.close()
        elif ending == 'success':
            assert list(stream)[-1]['type'] == 'done'
        else:
            with pytest.raises(chat.ModelTransportError):
                list(stream)
    for value in threads:
        value.join(1)
        assert not value.is_alive()
    assert response.closed.is_set()


def test_cancellation_between_tool_event_and_execution_skips_tool():
    cancelled = threading.Event()
    tool = {'tool_calls': [{'index': 0, 'id': 'call-1', 'function': {'name': 'query_quote', 'arguments': '{}'}}]}
    response = Response(frame(tool), DONE)
    with patch.object(chat, '_call_llm_stream', return_value=response), patch.object(chat, '_exec_tool') as execute:
        stream = chat.stream_messages({**CFG, '_cancel_event': cancelled}, [], use_tools=True)
        assert next(stream)['type'] == 'tool'
        cancelled.set()
        with pytest.raises(chat.ModelTransportError, match='停止'):
            next(stream)
    execute.assert_not_called()


@pytest.mark.parametrize('reason', ['length', 'content_filter', 'provider_cancelled'])
@pytest.mark.parametrize('use_tools', [False, True])
def test_pr353_abnormal_finish_contract_survives_done_marker(reason, use_tools):
    terminal = ('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': reason}]}) + '\n').encode()
    response = Response(frame({'content': 'incomplete'}), terminal, DONE)
    events = []
    with patch.object(chat, '_call_llm_stream', return_value=response):
        with pytest.raises(chat.ModelTransportError):
            for event in chat.stream_messages(CFG, [], use_tools=use_tools):
                events.append(event)
    assert not any(event['type'] == 'done' for event in events)
    assert response.closed.is_set()


@pytest.mark.parametrize('reason', [None, 'stop', 'tool_calls', 'function_call'])
def test_pr353_compatible_gateway_and_tool_endings_remain_allowed(reason):
    raw = ('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': reason}]})).encode()
    assert chat._parse_sse_line(raw) == (False, {})
