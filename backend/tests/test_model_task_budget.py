"""Offline regression source reconstructed on 2026-10-16; execution pending.

Every model and tool call is synthetic. Run under a deny-all network guard.
Historical test counts do not validate this recovered file.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

import agent_runtime
import chat
import debate

CFG = {"provider": "api-compatible", "baseURL": "https://example.test/v1",
       "model": "fixture", "apiKey": "fixture"}
DONE = b"data: [DONE]\n\n"


def frame(delta):
    return ("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n").encode()


class Response:
    status_code = 200

    def __init__(self, *chunks):
        self.chunks = chunks
        self.closed = threading.Event()

    def iter_content(self, chunk_size=None):
        yield from self.chunks

    def close(self):
        self.closed.set()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def json(self):
        return {"cancelled": True}


def budget(**overrides):
    return chat.ModelTaskBudget(**{
        "timeout": 2, "max_calls": 1, "max_tokens": 23, "max_chars": 1000,
        **overrides,
    })


def cfg(task, **overrides):
    return {**CFG, "_task_budget": task, **overrides}


def wait_slot(slots):
    assert slots.acquire(timeout=3), "underlying transport/cleanup did not exit"
    slots.release()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("unexpected external model or data tool request")

    monkeypatch.setattr(chat, "_dispatch_config", lambda cfg: cfg)
    import ai_credential_store
    monkeypatch.setattr(ai_credential_store, "dispatch_config", lambda cfg: cfg)
    monkeypatch.setattr(chat, "_check_base_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat, "_TASK_STREAM_SLOTS", threading.BoundedSemaphore(4))
    monkeypatch.setattr(chat.model_transport, "post", forbidden)
    monkeypatch.setattr(agent_runtime.requests.Session, "request", forbidden)
    monkeypatch.setattr(chat, "_exec_tool", forbidden)
    monkeypatch.setattr(debate.tools, "exec_tool", forbidden)


def mock_runtime_post(monkeypatch, post):
    """Stub only HTTP dispatch; retain runtime Session and response ownership."""
    def request(session, method, url, **kwargs):
        assert session.trust_env is False
        assert method == "POST"
        assert kwargs.pop("allow_redirects") is False
        return post(url, **kwargs)

    monkeypatch.setattr(agent_runtime.requests.Session, "request", request)


def test_api_dispatch_limits_are_per_task_and_payload_is_bounded(monkeypatch):
    posts = []

    def post(*args, **kwargs):
        posts.append((args, kwargs))
        return Response(frame({"content": "ok"}), DONE)

    monkeypatch.setattr(chat.model_transport, "post", post)
    first, second = budget(), budget()
    for task in (first, second):
        events = list(chat.stream_messages(cfg(task), []))
        assert [event["type"] for event in events] == ["delta", "done"]
        assert (task.calls, task.output_chars) == (1, 2)
    with pytest.raises(chat.ModelTaskBudgetError, match="调用次数"):
        list(chat.stream_messages(cfg(first), []))
    assert len(posts) == 2
    for _, kwargs in posts:
        assert kwargs["json"]["max_tokens"] == 23
        assert 0 < kwargs["timeout"][0] <= 2
        assert 0 < kwargs["timeout"][1] <= 2


def test_default_request_receives_unified_budget(monkeypatch):
    captured = {}

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return Response(frame({"content": "ok"}), DONE)

    monkeypatch.setattr(chat.model_transport, "post", post)
    assert list(chat.stream_messages(CFG, []))[-1]["type"] == "done"
    assert captured["json"]["max_tokens"] == 4000
    assert captured["timeout"] == (10, 120)


@pytest.mark.parametrize("phase", ["prepare", "headers", "read", "close"])
def test_held_transport_retains_admission_until_actual_exit(monkeypatch, phase):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(chat, "_TASK_STREAM_SLOTS", slots)
    release, entered = threading.Event(), threading.Event()
    response = Response(frame({"content": "ok"}), DONE)
    posts = []
    original_prepare = chat._stream_request

    def hold():
        entered.set()
        assert release.wait(3), "test failed to release held operation"

    def prepare(*args, **kwargs):
        if phase == "prepare":
            hold()
        return original_prepare(*args, **kwargs)

    def post(*args, **kwargs):
        posts.append((args, kwargs))
        if phase == "headers":
            hold()
        return response

    if phase == "read":
        def read(chunk_size=None):
            yield frame({"content": "ok"})
            hold()  # Deliberately ignore close while held.
            yield DONE
        response.iter_content = read
    if phase == "close":
        def close():
            response.closed.set()
            hold()
        response.close = close
    monkeypatch.setattr(chat, "_stream_request", prepare)
    monkeypatch.setattr(chat.model_transport, "post", post)
    events = []
    source = chat.stream_messages(cfg(budget(timeout=.25)), [])
    started = time.monotonic()
    try:
        with pytest.raises(chat.ModelTaskBudgetError, match="超时"):
            for event in source:
                events.append(event)
        assert time.monotonic() - started < 1
        assert entered.is_set(), "test never reached the intended held operation"
        assert not any(event["type"] == "done" for event in events)
        count = len(posts)
        with pytest.raises(chat.ModelTransportError, match="清理"):
            list(chat.stream_messages(cfg(budget()), []))
        assert len(posts) == count
    finally:
        release.set()
        source.close()
        wait_slot(slots)
    if phase == "prepare":
        assert posts == []  # Expired preparation must not dispatch afterward.
    else:
        assert len(posts) == 1
        assert response.closed.is_set()


@pytest.mark.parametrize("kind", ["content", "tool_arguments"])
def test_output_overflow_never_forwards_fragment_or_executes_tool(monkeypatch, kind):
    overflow = {"content": "overflow"} if kind == "content" else {
        "tool_calls": [{"index": 0, "id": "call", "function": {
            "name": "fixture", "arguments": "x" * 30,
        }}],
    }
    response = Response(frame({"content": "ok"}), frame(overflow), DONE)
    monkeypatch.setattr(chat.model_transport, "post", lambda *_a, **_k: response)
    task = budget(max_chars=5)
    events = []
    with pytest.raises(chat.ModelTaskBudgetError, match="输出"):
        for event in chat.stream_messages(cfg(task), [], use_tools=kind != "content"):
            events.append(event)
    assert events == [{"type": "delta", "text": "ok"}]
    assert task.output_chars == 2
    assert response.closed.wait(1)


def tool_response():
    return Response(frame({"tool_calls": [{"index": 0, "id": "c", "function": {
        "name": "fixture", "arguments": "{}",
    }}]}), DONE)


def test_tool_continuation_and_final_synthesis_share_dispatch_budget(monkeypatch):
    posts, executions = [], []
    monkeypatch.setattr(chat, "MAX_ROUNDS", 1)

    def post(*_args, **_kwargs):
        posts.append(True)
        return tool_response()

    monkeypatch.setattr(chat.model_transport, "post", post)
    monkeypatch.setattr(chat, "_exec_tool", lambda *args: executions.append(args) or {"value": 1})
    task = budget()
    events = []
    with pytest.raises(chat.ModelTaskBudgetError, match="调用次数"):
        for event in chat.stream_messages(cfg(task), [], use_tools=True):
            events.append(event)
    assert len(posts) == len(executions) == task.calls == 1
    assert [event["type"] for event in events] == ["tool", "tool_result"]


def test_cancel_after_tool_event_prevents_execution(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(chat, "_TASK_STREAM_SLOTS", slots)
    response = tool_response()
    executions = MagicMock(return_value={"value": 1})
    monkeypatch.setattr(chat, "_exec_tool", executions)
    monkeypatch.setattr(chat.model_transport, "post", lambda *_a, **_k: response)
    stop = threading.Event()
    source = chat.stream_messages(cfg(budget(), _cancel_event=stop), [], use_tools=True)
    try:
        assert next(source)["type"] == "tool"
        stop.set()
        with pytest.raises(chat.ModelTransportError, match="停止"):
            next(source)
    finally:
        stop.set()
        source.close()
        wait_slot(slots)
    executions.assert_not_called()
    assert response.closed.is_set()


def test_dispatch_reservation_is_atomic():
    task = budget(max_calls=3)

    def reserve(_):
        try:
            task.reserve_dispatch()
            return True
        except chat.ModelTaskBudgetError:
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(reserve, range(30)))
    assert sum(results) == task.calls == 3


@pytest.mark.parametrize("reason", ["deadline", "cancel"])
def test_inactive_task_never_dispatches(reason):
    task, stop = budget(), threading.Event()
    if reason == "deadline":
        task.deadline = time.monotonic() - 1
    else:
        stop.set()
    with pytest.raises(chat.ModelTransportError):
        list(chat.stream_messages(cfg(task, _cancel_event=stop), []))
    assert task.calls == 0


@pytest.mark.parametrize("tail", ["late_delta", "late_error", "missing_done", "empty_done", "runtime_error"])
def test_cli_invalid_terminal_never_completes(monkeypatch, tail):
    captured = {}

    def stream(**kwargs):
        captured.update(kwargs)
        if tail == "runtime_error":
            raise agent_runtime.AgentRuntimeError("FIXTURE", "fixture unavailable")
        if tail != "empty_done":
            yield {"type": "delta", "text": "partial"}
        if tail != "missing_done":
            yield {"type": "done"}
        if tail == "late_delta":
            yield {"type": "delta", "text": "late"}
        if tail == "late_error":
            yield {"type": "error", "message": "private upstream detail"}

    monkeypatch.setattr(agent_runtime, "stream_chat", stream)
    task, events = budget(), []
    started = time.monotonic()
    with pytest.raises((chat.ModelTransportError, agent_runtime.AgentRuntimeError)):
        for event in chat.stream_messages(cfg(task, provider="cli-codex"), []):
            events.append(event)
    assert time.monotonic() - started < 1
    assert task.calls == 1
    assert captured["owned_cleanup"] is True
    assert not any(event["type"] == "done" for event in events)


@pytest.mark.parametrize("reason", ["deadline", "output", "cancel"])
def test_cli_adapter_closes_response_and_cancels_owned_session(monkeypatch, reason):
    response = Response()
    stop = threading.Event()
    posts = []

    def lines():
        yield json.dumps({"type": "delta", "text": "partial"}).encode()
        if reason == "output":
            yield json.dumps({"type": "delta", "text": "overflow"}).encode()
        assert response.closed.wait(2), "CLI response was not closed"
        yield json.dumps({"type": "done"}).encode()

    response.iter_lines = lines

    def post(url, **kwargs):
        posts.append((url.rsplit("/", 1)[-1], kwargs["json"]))
        return response if url.endswith("/chat") else Response()

    mock_runtime_post(monkeypatch, post)
    task = budget(timeout=.2 if reason == "deadline" else 2,
                  max_chars=7 if reason == "output" else 1000)
    source = chat.stream_messages(cfg(task, provider="cli-codex", _cancel_event=stop), [])
    assert next(source)["text"] == "partial"
    if reason == "cancel":
        stop.set()
    with pytest.raises(chat.ModelTransportError):
        list(source)
    assert response.closed.wait(1)
    chat_calls = [payload for name, payload in posts if name == "chat"]
    cancel_calls = [payload for name, payload in posts if name == "cancel"]
    assert len(chat_calls) == len(cancel_calls) == task.calls == 1
    assert chat_calls[0]["session"] == cancel_calls[0]["session"]


def test_cli_cancel_cleanup_retains_admission(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(chat, "_TASK_STREAM_SLOTS", slots)
    response = Response()
    release, cancelling = threading.Event(), threading.Event()
    posts = []

    def lines():
        yield json.dumps({"type": "delta", "text": "partial"}).encode()
        assert response.closed.wait(3)
        yield json.dumps({"type": "done"}).encode()

    response.iter_lines = lines

    def post(url, **kwargs):
        posts.append(url.rsplit("/", 1)[-1])
        if url.endswith("/cancel"):
            cancelling.set()
            assert release.wait(3)
            return Response()
        return response

    mock_runtime_post(monkeypatch, post)
    source = chat.stream_messages(cfg(budget(timeout=.2), provider="cli-codex"), [])
    try:
        assert next(source)["text"] == "partial"
        with pytest.raises(chat.ModelTaskBudgetError, match="超时"):
            list(source)
        assert cancelling.wait(1)
        with pytest.raises(chat.ModelTransportError, match="清理"):
            list(chat.stream_messages(cfg(budget(), provider="cli-codex"), []))
        assert posts.count("chat") == posts.count("cancel") == 1
    finally:
        release.set()
        source.close()
        wait_slot(slots)
    assert response.closed.is_set()


def fake_dossier(code):
    yield {"type": "dossier_progress", "title": "fixture", "ok": True}
    return {"code": code, "sections": [{
        "title": "fixture", "tool": "fixture", "status": "success", "truncated": False,
        "data": {"value": 1}, "body": "fixture",
    }], "missing": [], "partial": []}


def test_debate_model_budget_starts_after_dossier_and_is_shared(monkeypatch):
    gathered, tasks, posts = [], [], []
    response = Response()

    def dossier(code):
        result = yield from fake_dossier(code)
        gathered.append(True)
        return result

    def make_budget(stages):
        assert gathered
        assert stages == 3
        task = budget(timeout=.25, max_calls=stages)
        tasks.append(task)
        return task

    def held_read(chunk_size=None):
        yield frame({"content": "bear"})
        assert response.closed.wait(2)
        yield DONE

    response.iter_content = held_read

    def post(*_args, **_kwargs):
        posts.append(True)
        return Response(frame({"content": "bull"}), DONE) if len(posts) == 1 else response

    monkeypatch.setattr(debate, "collect_dossier", dossier)
    monkeypatch.setattr(chat, "debate_task_budget", make_budget)
    monkeypatch.setattr(chat.model_transport, "post", post)
    events = list(debate.run_debate_stream(CFG, "600000"))
    assert len(tasks) == 1
    assert tasks[0].calls == len(posts) == 2
    assert [event["stage"] for event in events if event["type"] == "stage"] == ["bull", "bear"]
    assert any(event["type"] == "error" for event in events)
    assert not any(event["type"] == "done" for event in events)


@pytest.mark.parametrize("boundary", ["bull", "referee"])
@pytest.mark.parametrize("reason", ["deadline", "cancel"])
def test_debate_rechecks_after_stage_done_including_final_referee(monkeypatch, boundary, reason):
    task, stop, posts = budget(max_calls=3), threading.Event(), []
    monkeypatch.setattr(debate, "collect_dossier", fake_dossier)
    monkeypatch.setattr(chat, "debate_task_budget", lambda stages: task)

    def post(*_args, **_kwargs):
        posts.append(True)
        return Response(frame({"content": "answer"}), DONE)

    monkeypatch.setattr(chat.model_transport, "post", post)
    source = debate.run_debate_stream({**CFG, "_cancel_event": stop}, "600000")
    for event in source:
        if event["type"] == "stage_done" and event["stage"] == boundary:
            break
    else:
        pytest.fail("did not reach requested stage boundary")
    if reason == "deadline":
        task.deadline = time.monotonic() - 1
    else:
        stop.set()
    assert [event["type"] for event in source] == ["error"]
    assert len(posts) == (1 if boundary == "bull" else 3)


@pytest.mark.parametrize("failure", ["output", "late_done"])
def test_daily_review_failure_never_saves_complete_result(monkeypatch, failure):
    from fastapi.testclient import TestClient
    import app as app_module
    import daily_review_context

    review = {"status": "normal", "trade_date": "2026-10-13",
              "generated_at": "2026-10-13 15:30:00", "data_cutoff": "2026-10-13 15:00:00"}
    monkeypatch.setattr(chat, "prepare_daily_review_analysis", lambda _request: {
        "review": review, "context_json": daily_review_context.render_daily_review_ai_context(review),
        "messages": [{"role": "user", "content": "fixture"}],
    })
    save = MagicMock()
    monkeypatch.setattr(app_module.ai_result_service, "save_daily_review_ai", save)
    task = budget(max_chars=4)
    monkeypatch.setattr(chat, "daily_review_task_budget", lambda: task)
    if failure == "output":
        monkeypatch.setattr(chat.model_transport, "post", lambda *_a, **_k: Response(
            frame({"content": "ok"}), frame({"content": "overflow"}), DONE,
        ))
    else:
        def late_stream(*_args, **_kwargs):
            yield {"type": "delta", "text": "ok"}
            task.deadline = time.monotonic() - 1
            yield {"type": "done"}
        monkeypatch.setattr(chat, "stream_messages", late_stream)
    client = TestClient(app_module.app)  # Do not start application lifespan schedulers.
    result = client.post("/api/daily-review/analyze", json={"llm": CFG})
    assert result.status_code == 200
    events = [json.loads(line) for line in result.text.splitlines()]
    assert [event["type"] for event in events] == ["delta", "error"]
    save.assert_not_called()
