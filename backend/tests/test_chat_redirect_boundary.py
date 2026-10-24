"""Real Requests Session with in-memory adapters; never opens a socket."""
import io
import socket

import pytest
import requests

import chat

CFG = {"provider": "openai-compatible", "baseURL": "https://provider.invalid/v1",
       "model": "synthetic", "apiKey": "synthetic-not-a-key"}
BODY = b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n'


class BodyTrap:
    def read(self, *args, **kwargs):
        raise AssertionError("redirect body must not be drained")

    def stream(self, *args, **kwargs):
        raise AssertionError("redirect body must not be drained")

    def close(self):
        pass

    def release_conn(self):
        pass


class MemoryResponse(requests.Response):
    def __init__(self, status, request, body):
        super().__init__()
        self.status_code = status
        self.request = request
        self.url = request.url
        self.close_count = 0
        self.raw = BodyTrap() if 300 <= status < 400 else io.BytesIO(body)
        if 300 <= status < 400:
            self.headers['Location'] = 'http://169.254.169.254/PRIVATE-LOCATION'

    def close(self):
        self.close_count += 1
        super().close()


class MemoryAdapter(requests.adapters.BaseAdapter):
    def __init__(self, status, body):
        self.status, self.body = status, body
        self.requests, self.responses = [], []

    def send(self, request, **kwargs):
        self.requests.append(request)
        assert len(self.requests) == 1, 'redirect issued another request'
        response = MemoryResponse(self.status, request, self.body)
        self.responses.append(response)
        return response

    def close(self):
        pass


@pytest.fixture
def transport(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, port, **k: [(0, 0, 0, '', (host if host[0].isdigit() else '8.8.8.8', port))])
    monkeypatch.setattr(chat.model_transport.requests.utils, 'get_environ_proxies', lambda *_: {})
    monkeypatch.setattr(chat, '_dispatch_config', lambda cfg: cfg)
    monkeypatch.setattr(chat, '_PUBLIC_MODE', False)
    sessions = []
    def install(status, body=b'{}'):
        session = requests.Session()
        session.trust_env = False
        adapter = MemoryAdapter(status, body)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        monkeypatch.setattr(chat.model_transport, 'post', lambda *a, endpoint=None, **kw: session.post(*a, **kw))
        sessions.append(session)
        return adapter
    yield install
    for session in sessions:
        session.close()


@pytest.mark.parametrize('status', [300, 301, 302, 303, 304, 307, 308, 399])
@pytest.mark.parametrize('stream', [False, True])
def test_redirect_rejected_at_headers_without_body_or_next_request(transport, status, stream):
    adapter = transport(status)
    call = chat._call_llm_stream if stream else chat._call_llm
    with pytest.raises(chat.ModelTransportError, match='跳转') as error:
        call(CFG, [{'role': 'user', 'content': 'synthetic'}], False)
    assert str(error.value) == '模型接口返回跳转，请配置最终 API 地址'
    assert adapter.responses[0].close_count == 1
    assert len(adapter.requests) == 1
    assert adapter.requests[0].headers['Authorization'] == 'Bearer synthetic-not-a-key'
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.parametrize('use_tools', [False, True])
def test_redirect_does_not_emit_done_or_execute_tools(transport, monkeypatch, use_tools):
    adapter = transport(307)
    monkeypatch.setattr(chat, '_exec_tool', lambda *a, **k: pytest.fail('tool executed'))
    events = []
    with pytest.raises(chat.ModelTransportError):
        for event in chat.stream_messages(CFG, [], use_tools=use_tools):
            events.append(event)
    assert events == []
    assert adapter.responses[0].close_count == 1
    assert len(adapter.requests) == 1


def test_nonstream_200_parses_and_closes(transport):
    adapter = transport(200, b'{"choices": []}')
    assert chat._call_llm(CFG, [], False) == {'choices': []}
    assert adapter.responses[0].close_count == 1


def test_stream_200_retains_completion_and_cleanup(transport):
    adapter = transport(200, BODY)
    events = list(chat.stream_messages(CFG, []))
    assert [event['type'] for event in events] == ['delta', 'done']
    assert adapter.responses[0].close_count == 1


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('status', [400, 401, 429, 500])
def test_nonredirect_http_errors_remain_sanitized(transport, stream, status):
    adapter = transport(status, b'PRIVATE-BODY')
    call = chat._call_llm_stream if stream else chat._call_llm
    with pytest.raises(chat.ModelTransportError, match=f'HTTP {status}') as error:
        call(CFG, [], False)
    assert 'PRIVATE' not in str(error.value)
    assert adapter.responses[0].close_count == 1
    assert len(adapter.requests) == 1


def test_local_provider_still_allowed_and_metadata_denied_before_http(transport):
    adapter = transport(200, b'{}')
    assert chat._call_llm({**CFG, 'baseURL': 'http://127.0.0.1:11434'}, [], False) == {}
    assert adapter.requests[0].url.startswith('http://127.0.0.1:11434/')
    adapter = transport(200)
    with pytest.raises(RuntimeError, match='不允许'):
        chat._call_llm({**CFG, 'baseURL': 'http://169.254.169.254'}, [], False)
    assert adapter.requests == []


@pytest.mark.parametrize('stream', [False, True])
def test_request_explicitly_disables_redirects(transport, monkeypatch, stream):
    adapter = transport(200, b'{}')
    post = chat.model_transport.post
    def checked_post(*args, **kwargs):
        assert kwargs['allow_redirects'] is False
        assert kwargs['hooks']['response'] is chat._reject_model_redirect
        return post(*args, **kwargs)
    monkeypatch.setattr(chat.model_transport, 'post', checked_post)
    if stream:
        chat._call_llm_stream(CFG, [], False).close()
    else:
        chat._call_llm(CFG, [], False)
    assert len(adapter.requests) == 1


def test_redirect_close_failure_cannot_leak_details():
    class BrokenClose:
        status_code = 307
        def close(self):
            raise RuntimeError('PRIVATE-KEY-LOCATION')
    with pytest.raises(chat.ModelTransportError, match='跳转') as error:
        chat._reject_model_redirect(BrokenClose())
    assert 'PRIVATE' not in str(error.value)


def test_public_mode_still_blocks_loopback_before_http(transport, monkeypatch):
    adapter = transport(200)
    monkeypatch.setattr(chat, '_PUBLIC_MODE', True)
    with pytest.raises(RuntimeError, match='不允许'):
        chat._call_llm_stream({**CFG, 'baseURL': 'http://127.0.0.1:11434'}, [], False)
    assert adapter.requests == []
