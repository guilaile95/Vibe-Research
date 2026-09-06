"""Minimal local server-side mirror of the single Settings AI authority.

The file lives under VR_DATA_DIR/private/ and is excluded from Git, SQLite,
logs, and complete-data backups. It is not a second provider authority.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = "ai_credential.v1"
CLI_PROVIDER = "cli-codex"
DEFAULT_CODEX_MODEL = "gpt-5-codex"
UNAVAILABLE_CREDENTIAL = "UNAVAILABLE_CREDENTIAL"

_LOCK = threading.Lock()
_LOGGER = logging.getLogger("ai_credential")

_API_PROVIDERS = frozenset(
    {
        "deepseek",
        "silicon",
        "openai",
        "minimax",
        "openrouter",
        "groq",
        "together",
        "mimo",
        "openai-compatible",
    }
)


class CredentialStoreError(ValueError):
    """Public credential error; message must never contain an API key."""


def data_dir() -> Path:
    env = os.environ.get("VR_DATA_DIR", "").strip()
    return Path(env) if env else Path.home() / ".vibe-research"


def credential_path() -> Path:
    return data_dir() / "private" / "ai_credentials.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact(text: str, secret: str = "") -> str:
    value = str(text or "")
    if secret and secret in value:
        return value.replace(secret, "***")
    return value


def _chmod_owner_only(path: Path) -> None:
    try:
        if path.is_dir():
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        else:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        return


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    _chmod_owner_only(parent)
    tmp = path.with_name(path.name + f".tmp.{os.urandom(4).hex()}")
    try:
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _chmod_owner_only(path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _sanitize_base_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return parsed.netloc or parsed.path.split("/")[0]


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    base_url = str(payload.get("baseURL") or payload.get("base_url") or "").strip()
    api_key = str(payload.get("apiKey") or payload.get("api_key") or "").strip()
    if provider == CLI_PROVIDER:
        return {
            "schema_version": SCHEMA_VERSION,
            "provider": CLI_PROVIDER,
            "baseURL": "",
            "model": model or DEFAULT_CODEX_MODEL,
            "apiKey": "",
            "updated_at": utc_now_iso(),
        }
    if provider not in _API_PROVIDERS:
        raise CredentialStoreError("BAD_ARGUMENT: 不支持的 AI provider")
    if not base_url or not api_key or not model:
        raise CredentialStoreError(
            "BAD_ARGUMENT: API Compatible 需要 baseURL、apiKey 和 model"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "baseURL": base_url,
        "model": model,
        "apiKey": api_key,
        "updated_at": utc_now_iso(),
    }


def save(payload: dict[str, Any]) -> dict[str, Any]:
    record = _validate_payload(payload)
    with _LOCK:
        _atomic_write(credential_path(), record)
    _LOGGER.info(
        "AI credential mirror saved provider=%s model=%s",
        record["provider"],
        record["model"],
    )
    return status()


def delete() -> dict[str, Any]:
    path = credential_path()
    with _LOCK:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            raise CredentialStoreError("后台凭据删除失败") from exc
    _LOGGER.info("AI credential mirror deleted")
    return status()


def _read_raw() -> dict[str, Any] | None:
    path = credential_path()
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"_corrupt": True}
    if not isinstance(data, dict):
        return {"_corrupt": True}
    return data


def load() -> dict[str, Any] | None:
    """Return the full record including apiKey. Scheduled AI only."""
    with _LOCK:
        data = _read_raw()
    if data is None or data.get("_corrupt"):
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        return None
    provider = str(data.get("provider") or "").strip()
    model = str(data.get("model") or "").strip()
    if provider == CLI_PROVIDER:
        return {
            "schema_version": SCHEMA_VERSION,
            "provider": CLI_PROVIDER,
            "baseURL": "",
            "model": model or DEFAULT_CODEX_MODEL,
            "apiKey": "",
            "updated_at": str(data.get("updated_at") or ""),
        }
    if provider not in _API_PROVIDERS:
        return None
    base_url = str(data.get("baseURL") or "")
    api_key = str(data.get("apiKey") or "")
    if not base_url or not api_key or not model:
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "baseURL": base_url,
        "model": model,
        "apiKey": api_key,
        "updated_at": str(data.get("updated_at") or ""),
    }


def scheduled_config() -> tuple[dict[str, Any] | None, str | None]:
    """Return (cfg, error_code). cfg is suitable for chat.stream_messages."""
    with _LOCK:
        data = _read_raw()
    if data is None:
        return None, UNAVAILABLE_CREDENTIAL
    if data.get("_corrupt") or data.get("schema_version") != SCHEMA_VERSION:
        return None, UNAVAILABLE_CREDENTIAL
    provider = str(data.get("provider") or "").strip()
    model = str(data.get("model") or "").strip()
    if provider == CLI_PROVIDER:
        return {
            "provider": CLI_PROVIDER,
            "model": model or DEFAULT_CODEX_MODEL,
            "baseURL": "",
            "apiKey": "",
        }, None
    if provider not in _API_PROVIDERS:
        return None, UNAVAILABLE_CREDENTIAL
    base_url = str(data.get("baseURL") or "").strip()
    api_key = str(data.get("apiKey") or "").strip()
    if not base_url or not api_key or not model:
        return None, UNAVAILABLE_CREDENTIAL
    return {
        "provider": provider,
        "model": model,
        "baseURL": base_url,
        "apiKey": api_key,
    }, None


def status() -> dict[str, Any]:
    cfg, error = scheduled_config()
    record = load()
    configured = cfg is not None
    provider = cfg["provider"] if cfg else None
    model = cfg["model"] if cfg else None
    return {
        "configured": configured,
        "provider": provider,
        "model": model,
        "baseURL": _sanitize_base_url(cfg.get("baseURL", "") if cfg else ""),
        "updated_at": record.get("updated_at") if record else None,
        "scheduled_available": configured,
        "scheduled_credential_available": configured,
        "error": error,
    }
