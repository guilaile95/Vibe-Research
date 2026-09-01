"""Loopback client for the thin Codex Subscription Agent Runtime.

The runtime is a page-context-only text producer. This module never exposes a
filesystem path, account detail, token, CLI stderr or upstream URL to callers.
"""

from __future__ import annotations

import json
import os
import threading
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


def _safe_status_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise AgentRuntimeError("RUNTIME_BAD_RESPONSE", "Codex Subscription Runtime 返回无效")
    return {
        "runtime": "Codex Subscription",
        "installed": bool(payload.get("installed")),
        "authenticated": bool(payload.get("authenticated")),
        "available": bool(payload.get("available")),
        "status": str(payload.get("status") or "runtime_unavailable"),
        "version": str(payload.get("version")) if payload.get("version") else None,
    }


def status() -> dict:
    try:
        response = requests.get(f"{_base_url()}/status", timeout=4)
        response.raise_for_status()
        return _safe_status_payload(response.json())
    except AgentRuntimeError:
        raise
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
        response = requests.post(f"{_base_url()}/login", json={}, timeout=8)
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AgentRuntimeError("RUNTIME_UNAVAILABLE", "Codex Subscription Runtime 当前不可用") from exc
    if response.status_code >= 400 or not isinstance(payload, dict):
        raise AgentRuntimeError("LOGIN_FAILED", "Codex Subscription 登录未能启动", response.status_code)
    return {"runtime": "Codex Subscription", "state": str(payload.get("state") or "started")}


def cancel(session: str) -> bool:
    try:
        response = requests.post(f"{_base_url()}/cancel", json={"session": session}, timeout=4)
        return response.status_code < 400 and bool(response.json().get("cancelled"))
    except (requests.RequestException, ValueError, AttributeError):
        return False


def stream_chat(
    *, session: str, message: str, context: str, cancel_event: threading.Event,
    history: list[dict[str, str]] | tuple = (),
) -> Iterator[dict]:
    finished = threading.Event()

    def _cancel_when_disconnected() -> None:
        while not finished.wait(timeout=0.1):
            if cancel_event.is_set():
                cancel(session)
                return

    watcher = threading.Thread(
        target=_cancel_when_disconnected,
        name="vibe-agent-runtime-cancel",
        daemon=True,
    )
    watcher.start()
    try:
        with requests.post(
            f"{_base_url()}/chat",
            json={"session": session, "message": message, "context": context, "history": list(history)},
            stream=True,
            timeout=(4, 190),
        ) as response:
            if response.status_code >= 400:
                raise AgentRuntimeError(
                    "RUNTIME_REJECTED", "Codex Subscription Runtime 拒绝了本轮请求", response.status_code
                )
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
                yield event
    except AgentRuntimeError:
        raise
    except requests.RequestException as exc:
        raise AgentRuntimeError("RUNTIME_UNAVAILABLE", "Codex Subscription Runtime 当前不可用") from exc
    finally:
        finished.set()
