"""Loopback client for the thin Codex Subscription Agent Runtime.

The runtime is a page-context-only text producer. This module never exposes a
filesystem path, account detail, token, CLI stderr or upstream URL to callers.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from urllib.parse import urlparse

import requests


_DEFAULT_URL = "http://127.0.0.1:8911"
_SAFE_HOSTS = {"127.0.0.1", "::1", "localhost"}


class AgentRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _base_url() -> str:
    raw = (os.environ.get("VR_AGENT_RUNTIME_URL") or _DEFAULT_URL).strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in _SAFE_HOSTS or parsed.username or parsed.password:
        raise AgentRuntimeError("RUNTIME_CONFIG_INVALID", "Codex Subscription Runtime 配置无效")
    return raw


@contextmanager
def _request(method: str, url: str, **kwargs):
    # Loopback traffic must never inherit HTTP(S)_PROXY or follow redirects.
    with requests.Session() as session:
        session.trust_env = False
        with session.request(method, url, allow_redirects=False, **kwargs) as response:
            if 300 <= response.status_code < 400:
                raise requests.RequestException("Loopback redirect rejected")
            yield response


def _safe_status_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise AgentRuntimeError("RUNTIME_BAD_RESPONSE", "Codex Subscription Runtime 返回无效")
    result = {
        "runtime": "Codex Subscription",
        "installed": bool(payload.get("installed")),
        "authenticated": bool(payload.get("authenticated")),
        "available": bool(payload.get("available")),
        "status": str(payload.get("status") or "runtime_unavailable"),
        "version": str(payload.get("version")) if payload.get("version") else None,
    }

    if "dispatch_available" in payload:
        result["dispatch_available"] = payload.get("dispatch_available") is True
    if "modelConnectivity" in payload:
        result.update(runtimeFamily="codex-subscription", requestedModel=None,
                      resolvedModel=None, modelConnectivity="unknown", lastProbe=None)
    # Optional for compatibility with older runtime servers. Never copy raw details.
    if "auth_kind" in payload:
        kind = payload.get("auth_kind")
        result["auth_kind"] = kind if kind in ("chatgpt", "api_key", "logged_out", "unknown") else "unknown"
    if "probe_error" in payload:
        error = payload.get("probe_error")
        result["probe_error"] = error if error in (None, "timeout", "not_found", "malformed_output", "nonzero_exit", "process_error") else "process_error"
    return result


def status() -> dict:
    try:
        with _request("GET", f"{_base_url()}/status", timeout=4) as response:
            response.raise_for_status()
            return _safe_status_payload(response.json())
    except AgentRuntimeError:
        raise
    except requests.Timeout:
        # The outer HTTP budget can expire before either bounded CLI probe.
        # No conclusion about the account or installed binary is available.
        return {
            "runtime": "Codex Subscription", "installed": False,
            "authenticated": False, "available": False, "status": "probe_failed",
            "version": None, "auth_kind": "unknown", "probe_error": "timeout",
        }
    except (requests.RequestException, ValueError):
        return {
            "runtime": "Codex Subscription",
            "installed": False,
            "authenticated": False,
            "available": False,
            "status": "runtime_unavailable",
            "version": None,
        }


def start_login() -> dict:
    try:
        with _request("POST", f"{_base_url()}/login", json={}, timeout=8) as response:
            payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AgentRuntimeError("RUNTIME_UNAVAILABLE", "Codex Subscription Runtime 当前不可用") from exc
    if response.status_code >= 400 or not isinstance(payload, dict):
        raise AgentRuntimeError("LOGIN_FAILED", "Codex Subscription 登录未能启动", response.status_code)
    return {"runtime": "Codex Subscription", "state": str(payload.get("state") or "started")}


def cancel(session: str) -> bool:
    try:
        with _request("POST", f"{_base_url()}/cancel", json={"session": session}, timeout=4) as response:
            return response.status_code < 400 and bool(response.json().get("cancelled"))
    except (requests.RequestException, ValueError, AttributeError):
        return False


def stream_chat(
    *, session: str, message: str, context: str, cancel_event: threading.Event,
    history: list[dict[str, str]] | tuple = (),
    owned_cleanup: bool = False,
    config: dict | None = None,
) -> Iterator[dict]:
    finished = threading.Event()
    response = None
    cancel_lock = threading.Lock()
    cancellation_started = False

    def request_cancel():
        nonlocal cancellation_started
        with cancel_lock:
            if cancellation_started:
                return
            cancellation_started = True
        try:
            cancel(session)
        finally:
            if owned_cleanup and response is not None:
                try:
                    response.close()
                except Exception:
                    pass  # Cleanup cannot expose loopback transport internals.

    def _cancel_when_disconnected() -> None:
        while not finished.wait(timeout=0.1):
            if cancel_event.is_set():
                request_cancel()
                return

    watcher = threading.Thread(
        target=_cancel_when_disconnected,
        name="vibe-agent-runtime-cancel",
        daemon=True,
    )
    watcher.start()
    try:
        import ai_credential_store
        ai_credential_store.dispatch_config(config or {})
        with _request(
            "POST", f"{_base_url()}/chat",
            json={"session": session, "message": message, "context": context, "history": list(history)},
            stream=True,
            timeout=(4, 190),
        ) as response:
            if response.status_code >= 400:
                raise AgentRuntimeError(
                    "RUNTIME_REJECTED", "Codex Subscription Runtime 拒绝了本轮请求", response.status_code
                )
            terminal = None
            for raw in response.iter_lines():
                if cancel_event.is_set():
                    return
                if not raw:
                    continue
                try:
                    event = json.loads(raw.decode("utf-8", errors="strict"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise AgentRuntimeError(
                        "RUNTIME_BAD_RESPONSE", "Codex Subscription Runtime 返回无效"
                    ) from exc
                if not isinstance(event, dict) or event.get("type") not in {"delta", "done", "error"}:
                    raise AgentRuntimeError(
                        "RUNTIME_BAD_RESPONSE", "Codex Subscription Runtime 返回无效"
                    )
                if terminal:
                    raise AgentRuntimeError("RUNTIME_BAD_RESPONSE", "模型响应在终止后仍有数据")
                if event.get("type") in {"done", "error"}:
                    terminal = event
                else:
                    yield event
            if not terminal and not cancel_event.is_set():
                raise AgentRuntimeError("RUNTIME_BAD_RESPONSE", "模型响应流未完整结束")
            if terminal and not cancel_event.is_set():
                yield terminal
    except AgentRuntimeError:
        raise
    except requests.RequestException as exc:
        raise AgentRuntimeError("RUNTIME_UNAVAILABLE", "Codex Subscription Runtime 当前不可用") from exc
    finally:
        try:
            if owned_cleanup and cancel_event.is_set():
                request_cancel()
        finally:
            finished.set()
            if owned_cleanup:
                watcher.join()  # Keep the task admission slot through cleanup.
