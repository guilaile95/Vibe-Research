"""Offline API/stream contracts, isolated storage and mocked providers only."""
import asyncio
import json
import threading
from unittest.mock import MagicMock

import pytest
import httpx
import requests
from fastapi.testclient import TestClient

import app as app_module
import chat as chat_layer
from test_daily_review_lead import display_payload

URL = "/api/daily-review/lead-analysis"
LLM = {"provider": "api-compatible", "model": "test-model",
       "baseURL": "https://example.test/v1", "apiKey": "test-key"}
client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(requests.sessions.Session, "request", MagicMock(side_effect=AssertionError("network forbidden")))
    display = MagicMock(return_value=display_payload())
    monkeypatch.setattr(app_module.daily_review, "get_daily_review_for_display", display)
    forbidden = MagicMock(side_effect=AssertionError("fresh pipeline or save forbidden"))
    monkeypatch.setattr(app_module.daily_review, "generate_daily_review", forbidden)
    monkeypatch.setattr(chat_layer, "prepare_daily_review_analysis", forbidden)
    monkeypatch.setattr(app_module.ai_result_service, "save_daily_review_ai", forbidden)
    monkeypatch.setattr(app_module.agent_runtime, "status", lambda: {"available": True, "status": "ready"})
    monkeypatch.setattr(chat_layer, "_call_llm_stream", MagicMock(side_effect=AssertionError("real model forbidden")))
    monkeypatch.setattr(chat_layer.agent_runtime, "stream_chat", MagicMock(side_effect=AssertionError("real codex forbidden")))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request",
                        MagicMock(side_effect=AssertionError("external HTTP forbidden")))
    yield display
    forbidden.assert_not_called()


def mock_api_stream(monkeypatch, stream):
    async def async_stream(cfg, messages):
        source = stream(cfg, messages, use_tools=False)
        try:
            for event in source:
                yield event
        finally:
            close = getattr(source, "close", None)
            if close:
                close()
    monkeypatch.setattr(chat_layer, "stream_api_messages", async_stream)


def post(**overrides):
    return client.post(URL, json={"kind": "industry", "subject": "BK0002", "llm": LLM, **overrides})


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.text.endswith("\n")
    return [json.loads(line) for line in response.text.splitlines()]


@pytest.mark.parametrize("kind,subject", [("industry", "BK0002"), ("activity", "000001"), ("emotion", None)])
def test_complete_ndjson_context_first_single_prepare_no_tools(monkeypatch, isolated, kind, subject):
    closed = []

    def stream(cfg, messages, *, use_tools):
        assert not use_tools
        assert cfg["apiKey"] == "test-key"
        assert json.loads(messages[1]["content"].split("\n", 1)[1])["kind"] == kind
        try:
            yield {"type": "delta", "text": "已知事实"}
            yield {"type": "delta", "text": "与待核对问题"}
            yield {"type": "done", "trace": [{"private": "must-not-forward"}], "result": {"saved": True}}
        finally:
            closed.append(True)

    mocked = MagicMock(side_effect=stream)
    mock_api_stream(monkeypatch, mocked)
    result = events(post(kind=kind, subject=subject))
    assert [e["type"] for e in result] == ["lead_context", "delta", "delta", "done"]
    assert result[0]["context"]["subject"]["code"] == subject
    assert result[-1] == {"type": "done", "trace": [], "rounds": 1}
    assert closed == [True]
    isolated.assert_called_once_with()
    mocked.assert_called_once()


@pytest.mark.parametrize("extra", ["context", "facts", "url", "messages", "system_prompt", "user_request"])
def test_rejects_client_facts_and_extra_fields_before_preparation(isolated, extra):
    assert post(**{extra: {"injected": "buy"}}).status_code == 422
    isolated.assert_not_called()


@pytest.mark.parametrize("overrides", [
    {"kind": "other"}, {"subject": None}, {"subject": ""},
    {"kind": "emotion", "subject": "000001"},
    {"kind": "activity", "subject": "1"},
    {"kind": "activity", "subject": "000001.SZ"},
    {"kind": "activity", "subject": "１２３４５６"},
    {"kind": "activity", "subject": 1},
])
def test_invalid_selection_422(isolated, overrides):
    assert post(**overrides).status_code == 422
    isolated.assert_not_called()


def test_llm_configuration_checked_before_preparation(isolated):
    assert post(llm={**LLM, "apiKey": ""}).status_code == 400
    isolated.assert_not_called()


@pytest.mark.parametrize("kind,subject", [("industry", "BKexpired"), ("activity", "600001")])
def test_expired_object_is_safe_409_without_model(monkeypatch, isolated, kind, subject):
    stream = MagicMock()
    mock_api_stream(monkeypatch, stream)
    response = post(kind=kind, subject=subject)
    assert response.status_code == 409
    assert "已不在当前榜单" in response.json()["detail"]
    isolated.assert_called_once()
    stream.assert_not_called()


@pytest.mark.parametrize("broken", [None, {}, {"data": None}, {"data": {"short_term_emotion": {"status": "unavailable"}}}])
def test_unavailable_is_503_without_model(monkeypatch, isolated, broken):
    isolated.return_value = broken
    stream = MagicMock()
    mock_api_stream(monkeypatch, stream)
    assert post(kind="emotion", subject=None).status_code == 503
    stream.assert_not_called()


def test_preparation_failure_has_safe_message(isolated):
    isolated.side_effect = RuntimeError("ProxyError https://private.test SQL secret-key")
    response = post()
    assert response.status_code == 503
    assert "private" not in response.text and "secret-key" not in response.text


@pytest.mark.parametrize("upstream", [
    [], [{"type": "done"}], [{"type": "delta", "text": " "}, {"type": "done"}],
    [{"type": "delta", "text": "partial"}],
    [{"type": "delta", "text": "partial"}, {"type": "error", "message": "secret-key SQL"}, {"type": "done"}],
    [{"type": "delta", "text": "partial"}, {"type": "done"}, {"type": "done"}],
    [{"type": "delta", "text": "partial"}, {"type": "done"}, {"type": "delta", "text": "tail"}],
    [None], [{"type": "tool", "name": "write"}], [{"type": "delta", "text": None}],
])
def test_incomplete_invalid_and_failed_streams_no_success(monkeypatch, upstream):
    closed = []

    def stream(*args, **kwargs):
        try:
            yield from upstream
        finally:
            closed.append(True)

    mock_api_stream(monkeypatch, stream)
    response = post()
    result = events(response)
    assert result[0]["type"] == "lead_context"
    assert result[-1] == {"type": "error", "message": "单条线索AI解读失败，请稍后重试"}
    assert not any(e["type"] == "done" for e in result)
    assert "secret-key" not in response.text and '"tail"' not in response.text
    assert closed == [True]


@pytest.mark.parametrize("startup", [True, False])
def test_exception_on_start_or_after_done_never_reports_success(monkeypatch, startup):
    def stream(*args, **kwargs):
        yield {"type": "delta", "text": "partial"}
        yield {"type": "done"}
        raise RuntimeError("secret-key SQL")

    mock_api_stream(monkeypatch,
                        MagicMock(side_effect=RuntimeError("secret-key")) if startup else stream)
    response = post()
    result = events(response)
    assert result[0]["type"] == "lead_context"
    assert result[-1]["type"] == "error"
    assert not any(e["type"] == "done" for e in result)
    assert "secret-key" not in response.text


def test_done_is_yielded_only_after_iterator_exhaustion(monkeypatch):
    exhausted = []

    def stream(*args, **kwargs):
        yield {"type": "delta", "text": "complete"}
        yield {"type": "done"}
        exhausted.append(True)

    mock_api_stream(monkeypatch, stream)

    async def exercise():
        response = await app_module.analyze_daily_review_lead(
            app_module.DailyReviewLeadRequest(kind="industry", subject="BK0002", llm=LLM))
        async for line in response.body_iterator:
            if json.loads(line)["type"] == "done":
                assert exhausted == [True]

    asyncio.run(exercise())


@pytest.mark.parametrize("provider", ["api-compatible", "cli-codex"])
def test_real_stream_messages_routes_api_and_codex_without_tools(monkeypatch, isolated, provider):
    calls = []
    if provider == "api-compatible":
        def api(request):
            payload = json.loads(request.content)
            assert "tools" not in payload and "tool_choice" not in payload
            assert payload["messages"][0]["role"] == "system"
            assert payload["stream"] is True
            assert str(request.url) == "https://example.test/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer test-key"
            calls.append(payload)
            return httpx.Response(200, content=(
                'data: {"choices":[{"delta":{"content":"API结果"}}]}\n\n'
                'data: [DONE]\n\n').encode())
        real_client = httpx.AsyncClient
        monkeypatch.setattr(chat_layer.httpx, "AsyncClient",
                            lambda **kw: real_client(transport=httpx.MockTransport(api), **kw))
    else:
        def codex(**kwargs):
            calls.append(kwargs)
            assert kwargs["history"] == []
            assert "daily-review-lead-context.v1" in kwargs["context"]
            assert "不能升级为正式判断" in kwargs["message"]
            assert isinstance(kwargs["cancel_event"], threading.Event)
            yield {"type": "delta", "text": "Codex结果"}
            yield {"type": "done"}
        monkeypatch.setattr(chat_layer.agent_runtime, "stream_chat", codex)
    result = events(post(llm={**LLM, "provider": provider}))
    assert [e["type"] for e in result] == ["lead_context", "delta", "done"]
    assert len(calls) == 1
    isolated.assert_called_once()


def test_asgi_disconnect_cancels_codex_and_closes_iterator(monkeypatch):
    captured = {}
    closed = threading.Event()

    def codex(**kwargs):
        captured.update(kwargs)
        try:
            yield {"type": "delta", "text": "partial"}
            assert kwargs["cancel_event"].wait(2)
            yield {"type": "done"}
        finally:
            closed.set()

    monkeypatch.setattr(chat_layer.agent_runtime, "stream_chat", codex)
    sent = []

    async def exercise():
        first_delta = asyncio.Event()
        body_sent = False
        body = json.dumps({"kind": "emotion", "llm": {**LLM, "provider": "cli-codex"}}).encode()

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await first_delta.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and b'"type": "delta"' in message.get("body", b""):
                first_delta.set()

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                 "http_version": "1.1", "method": "POST", "scheme": "http", "path": URL,
                 "raw_path": URL.encode(), "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
                 "client": ("127.0.0.1", 1234), "server": ("testserver", 80), "state": {}}
        await app_module.app(scope, receive, send)

    asyncio.run(exercise())
    assert captured["cancel_event"].is_set()
    assert closed.is_set()
    chunks = b"".join(m.get("body", b"") for m in sent)
    assert b'"type": "done"' not in chunks
    assert b'"type": "error"' not in chunks
