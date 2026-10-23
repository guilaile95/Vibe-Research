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

SCHEMA_VERSION = "ai_credential.v2"
LEGACY_SCHEMA_VERSION = "ai_credential.v1"
MAX_REVISION = 2**63 - 1
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


class UnsafeCredentialURL(CredentialStoreError):
    """Known schema/revision, but URL cannot be used for authenticated dispatch."""


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
    from safe_outputs import safe_url_origin
    return safe_url_origin(url)


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
    try:
        parsed = urlparse(base_url)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError()
        parsed.port
    except ValueError:
        raise UnsafeCredentialURL("BAD_ARGUMENT: baseURL 不允许凭据或无效地址") from None
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "baseURL": base_url,
        "model": model,
        "apiKey": api_key,
        "updated_at": utc_now_iso(),
    }


class CredentialConflict(CredentialStoreError):
    pass


def _revision(value: Any) -> int:
    if not isinstance(value, str) or not value or not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise CredentialStoreError("CREDENTIAL_REVISION_INVALID")
    number = int(value)
    if str(number) != value or number > MAX_REVISION:
        raise CredentialStoreError("CREDENTIAL_REVISION_INVALID")
    return number


def _read_raw() -> dict[str, Any] | None:
    path = credential_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raise CredentialStoreError("CREDENTIAL_STATE_UNAVAILABLE") from None
    if not isinstance(data, dict):
        raise CredentialStoreError("CREDENTIAL_STATE_UNAVAILABLE")
    return data


def _state() -> tuple[int, dict[str, Any] | None, str | None]:
    """Read once under _LOCK. Legacy records are read-only generation zero."""
    raw = _read_raw()
    if raw is None:
        return 0, None, None
    schema = raw.get("schema_version")
    if schema == LEGACY_SCHEMA_VERSION:
        revision = 0
    elif schema == SCHEMA_VERSION:
        revision = raw.get("revision")
        if type(revision) is not int or not 0 <= revision <= MAX_REVISION or type(raw.get("configured")) is not bool:
            raise CredentialStoreError("CREDENTIAL_STATE_UNAVAILABLE")
        if raw["configured"] is False:
            if any(key in raw for key in ("provider", "model", "baseURL", "apiKey", "api_key", "base_url")):
                raise CredentialStoreError("CREDENTIAL_STATE_UNAVAILABLE")
            return revision, None, raw.get("updated_at")
    else:
        raise CredentialStoreError("CREDENTIAL_STATE_UNAVAILABLE")
    try:
        record = _validate_payload(raw)
    except UnsafeCredentialURL:
        # Preserve an already validated revision so the owner can explicitly
        # replace/clear unsafe legacy configuration. Never make it runnable.
        return revision, None, raw.get("updated_at")
    except CredentialStoreError:
        raise CredentialStoreError("CREDENTIAL_STATE_UNAVAILABLE") from None
    record["updated_at"] = str(raw.get("updated_at") or "")
    return revision, record, record["updated_at"]


def _status(revision: int | None, cfg: dict[str, Any] | None, updated_at=None) -> dict[str, Any]:
    return {
        "revision": str(revision) if revision is not None else None,
        "configured": cfg is not None,
        "provider": cfg["provider"] if cfg else None,
        "model": cfg["model"] if cfg else None,
        "baseURL": _sanitize_base_url(cfg.get("baseURL", "") if cfg else ""),
        "updated_at": updated_at,
        "scheduled_available": cfg is not None,
        "scheduled_credential_available": cfg is not None,
        "error": None if cfg else UNAVAILABLE_CREDENTIAL,
    }


def save(payload: dict[str, Any], *, expected_revision: str) -> dict[str, Any]:
    expected = _revision(expected_revision)
    record = _validate_payload(payload)
    with _LOCK:
        revision, _, _ = _state()
        if expected != revision or revision == MAX_REVISION:
            raise CredentialConflict("CREDENTIAL_REVISION_CONFLICT")
        revision += 1
        record.update(revision=revision, configured=True)
        _atomic_write(credential_path(), record)
        return _status(revision, record, record["updated_at"])


def delete(*, observed_revision: str) -> dict[str, Any]:
    """Clear barrier: stale observations may clear, future observations cannot.

    Never unlink: the nonsecret tombstone prevents old saves reviving a key.
    This lock assumes the documented single backend writer process.
    """
    observed = _revision(observed_revision)
    with _LOCK:
        revision, _, _ = _state()
        if observed > revision or revision == MAX_REVISION:
            raise CredentialConflict("CREDENTIAL_REVISION_CONFLICT")
        revision += 1
        timestamp = utc_now_iso()
        _atomic_write(credential_path(), {
            "schema_version": SCHEMA_VERSION, "revision": revision,
            "configured": False, "updated_at": timestamp,
        })
        return _status(revision, None, timestamp)


def load() -> dict[str, Any] | None:
    """Return the full record including apiKey. Scheduled AI only."""
    with _LOCK:
        try:
            _, record, _ = _state()
            return record
        except CredentialStoreError:
            return None


def scheduled_config() -> tuple[dict[str, Any] | None, str | None]:
    record = load()
    if record is None:
        return None, UNAVAILABLE_CREDENTIAL
    return {key: record[key] for key in ("provider", "model", "baseURL", "apiKey")}, None


def status() -> dict[str, Any]:
    with _LOCK:
        try:
            return _status(*_state())
        except CredentialStoreError:
            result = _status(None, None)
            result["error"] = "CREDENTIAL_STATE_UNAVAILABLE"
            return result
