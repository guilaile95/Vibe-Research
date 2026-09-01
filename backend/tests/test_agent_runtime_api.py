from __future__ import annotations

import json

from fastapi.testclient import TestClient

import agent_runtime
import app as app_module


client = TestClient(app_module.app)


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
    monkeypatch.setattr(
        app_module.chat_layer,
        "run_chat_cli_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy CLI fallback")),
    )

    response = client.post("/api/chat", json=_request())

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["classification"] == "NON_AUTHORITATIVE_AI_DRAFT"
    assert captured["session"] == "stock-600519"
    assert captured["message"] == "只解释当前页面"
    assert captured["context"] == "证券代码：600519"


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
