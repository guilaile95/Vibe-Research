from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

import agent_runtime
import app as app_module


client = TestClient(app_module.app)


class _StreamResponse:
    def __init__(self, lines=(), *, status_code=200):
        self.lines = lines
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_lines(self):
        return iter(self.lines)


def _watcher_count() -> int:
    return sum(thread.name == "vibe-agent-runtime-cancel" for thread in threading.enumerate())


def _wait_for_watcher_count(expected: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _watcher_count() != expected:
        time.sleep(0.02)
    assert _watcher_count() == expected


def _request(provider: str = "cli-codex") -> dict:
    return {
        "messages": [{"role": "user", "content": "只解释当前页面"}],
        "context": "证券代码：600519",
        "session": "stock-600519",
        "llm": {"provider": provider, "model": "codex", "baseURL": "", "apiKey": ""},
    }


def test_codex_chat_uses_agent_runtime_without_cli_or_api_fallback(monkeypatch):
    monkeypatch.setattr(
        agent_runtime,
        "status",
        lambda: {
            "runtime": "Codex Subscription",
            "installed": True,
            "authenticated": True,
            "available": True,
            "status": "ready",
            "version": "codex-cli 0.149.0",
        },
    )
    captured = {}

    def stream_chat(**kwargs):
        captured.update(kwargs)
        yield {"type": "delta", "text": "页面草稿"}
        yield {
            "type": "done",
            "runtime": "Codex Subscription",
            "classification": "NON_AUTHORITATIVE_AI_DRAFT",
        }

    monkeypatch.setattr(agent_runtime, "stream_chat", stream_chat)
    monkeypatch.setattr(
        app_module.chat_layer,
        "run_chat_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("API fallback")),
    )
    body = _request()
    body["messages"] = [
        {"role": "user", "content": "第一轮问题"},
        {"role": "assistant", "content": "第一轮回答"},
        {"role": "user", "content": "只解释当前页面"},
    ]
    response = client.post("/api/chat", json=body)

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["classification"] == "NON_AUTHORITATIVE_AI_DRAFT"
    assert captured["session"] == "stock-600519"
    assert captured["message"] == "只解释当前页面"
    assert captured["context"] == "证券代码：600519"
    assert captured["history"] == [
        {"role": "user", "content": "第一轮问题"},
        {"role": "assistant", "content": "第一轮回答"},
    ]


def test_structured_codex_messages_use_agent_runtime(monkeypatch):
    captured = {}

    def stream_chat(**kwargs):
        captured.update(kwargs)
        yield {"type": "delta", "text": '{"ok":true}'}
        yield {"type": "done", "runtime": "Codex Subscription"}

    monkeypatch.setattr(agent_runtime, "stream_chat", stream_chat)
    events = list(app_module.chat_layer.stream_messages(
        {"provider": "cli-codex", "model": "codex", "baseURL": "", "apiKey": ""},
        [
            {"role": "system", "content": "只返回 JSON"},
            {"role": "user", "content": "当前组合数据"},
        ],
        use_tools=False,
    ))

    assert captured["session"].startswith("ai-")
    assert "只返回 JSON" in captured["message"]
    assert "当前组合数据" in captured["context"]
    assert captured["history"] == []
    assert [event["type"] for event in events] == ["delta", "done"]
    assert events[-1]["rounds"] == 1
    assert events[-1]["trace"] == []


def test_codex_unavailable_fails_explicitly_without_fallback(monkeypatch):
    monkeypatch.setattr(
        agent_runtime,
        "status",
        lambda: {
            "runtime": "Codex Subscription",
            "installed": False,
            "authenticated": False,
            "available": False,
            "status": "runtime_unavailable",
            "version": None,
        },
    )
    monkeypatch.setattr(
        app_module.chat_layer,
        "run_chat_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("API fallback")),
    )

    response = client.post("/api/chat", json=_request())

    assert response.status_code == 503
    assert response.json()["detail"] == "Codex Subscription 尚未连接，请先在设置页登录"


def test_agent_runtime_status_and_login_are_safe_projections(monkeypatch):
    monkeypatch.setattr(
        agent_runtime,
        "status",
        lambda: {
            "runtime": "Codex Subscription",
            "installed": True,
            "authenticated": False,
            "available": False,
            "status": "not_authenticated",
            "version": "codex-cli 0.149.0",
        },
    )
    monkeypatch.setattr(
        agent_runtime,
        "start_login",
        lambda: {"runtime": "Codex Subscription", "state": "started"},
    )

    status_response = client.get("/api/agent-runtime/status")
    login_response = client.post("/api/agent-runtime/login")

    assert status_response.status_code == 200
    assert status_response.json() == {
        "runtime": "Codex Subscription",
        "installed": True,
        "authenticated": False,
        "available": False,
        "status": "not_authenticated",
        "version": "codex-cli 0.149.0",
    }
    assert login_response.status_code == 202
    assert login_response.json() == {"runtime": "Codex Subscription", "state": "started"}


def test_agent_runtime_forwards_complete_history_as_conversation_data(monkeypatch):
    captured = {}

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return _StreamResponse([b'{"type":"done"}'])

    monkeypatch.setattr(agent_runtime.requests, "post", post)
    history = [
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "上一轮回答"},
    ]

    assert list(agent_runtime.stream_chat(
        session="history-forward",
        message="继续",
        context="最新页面",
        history=history,
        cancel_event=threading.Event(),
    )) == [{"type": "done"}]
    assert captured["json"] == {
        "session": "history-forward",
        "message": "继续",
        "context": "最新页面",
        "history": history,
    }


def test_api_compatible_chat_path_is_unchanged(monkeypatch):
    monkeypatch.setattr(app_module, "_require_llm_ready", lambda _llm: False)

    def api_stream(_cfg, _messages, _context):
        yield {"type": "delta", "text": "api"}
        yield {"type": "done", "trace": [], "rounds": 1}

    monkeypatch.setattr(app_module.chat_layer, "run_chat_stream", api_stream)
    body = _request(provider="openai-compatible")
    body["llm"].update({"model": "model", "baseURL": "https://example.com", "apiKey": "test"})

    response = client.post("/api/chat", json=body)

    assert response.status_code == 200
    assert [json.loads(line)["type"] for line in response.text.splitlines()] == ["delta", "done"]


def test_agent_runtime_watchers_exit_after_normal_completion_and_error(monkeypatch):
    baseline = _watcher_count()
    monkeypatch.setattr(
        agent_runtime.requests,
        "post",
        lambda *_args, **_kwargs: _StreamResponse([b'{"type":"done"}']),
    )

    for index in range(50):
        assert list(
            agent_runtime.stream_chat(
                session=f"normal-{index}",
                message="test",
                context="context",
                cancel_event=threading.Event(),
            )
        ) == [{"type": "done"}]

    _wait_for_watcher_count(baseline)

    monkeypatch.setattr(
        agent_runtime.requests,
        "post",
        lambda *_args, **_kwargs: _StreamResponse(status_code=500),
    )
    with pytest.raises(agent_runtime.AgentRuntimeError, match="拒绝"):
        list(
            agent_runtime.stream_chat(
                session="runtime-error",
                message="test",
                context="context",
                cancel_event=threading.Event(),
            )
        )
    _wait_for_watcher_count(baseline)


def test_agent_runtime_user_cancel_calls_cancel_once_and_exits(monkeypatch):
    baseline = _watcher_count()
    cancelled = threading.Event()
    calls = []

    def fake_cancel(session):
        calls.append(session)
        cancelled.set()
        return True

    class CancelledResponse(_StreamResponse):
        def iter_lines(self):
            assert cancelled.wait(timeout=1)
            return iter(())

    monkeypatch.setattr(agent_runtime, "cancel", fake_cancel)
    monkeypatch.setattr(
        agent_runtime.requests,
        "post",
        lambda *_args, **_kwargs: CancelledResponse(),
    )
    cancel_event = threading.Event()
    cancel_event.set()

    assert list(
        agent_runtime.stream_chat(
            session="user-cancel",
            message="test",
            context="context",
            cancel_event=cancel_event,
        )
    ) == []
    _wait_for_watcher_count(baseline)
    assert calls == ["user-cancel"]


def test_agent_runtime_http_disconnect_cancels_once_and_exits(monkeypatch):
    baseline = _watcher_count()
    cancelled = threading.Event()
    calls = []

    monkeypatch.setattr(
        agent_runtime,
        "status",
        lambda: {
            "runtime": "Codex Subscription",
            "installed": True,
            "authenticated": True,
            "available": True,
            "status": "ready",
            "version": "test",
        },
    )

    def fake_cancel(session):
        calls.append(session)
        cancelled.set()
        return True

    class DisconnectResponse(_StreamResponse):
        def iter_lines(self):
            yield b'{"type":"delta","text":"chunk"}'
            assert cancelled.wait(timeout=2)

    monkeypatch.setattr(agent_runtime, "cancel", fake_cancel)
    monkeypatch.setattr(
        agent_runtime.requests,
        "post",
        lambda *_args, **_kwargs: DisconnectResponse(),
    )
    body = json.dumps(_request()).encode("utf-8")

    async def exercise_disconnect():
        first_body_sent = asyncio.Event()
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await first_body_sent.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                first_body_sent.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/chat",
            "raw_path": b"/api/chat",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "state": {},
        }
        await app_module.app(scope, receive, send)

    asyncio.run(exercise_disconnect())
    _wait_for_watcher_count(baseline)
    assert calls == ["stock-600519"]
