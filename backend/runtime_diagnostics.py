"""Read-only, allowlisted deployment metadata. Never opens private data or probes services."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from urllib.parse import urlparse

import agent_runtime

_CONFIG_NAMES = (
    "VR_AGENT_RUNTIME_URL", "VR_AGENT_RUNTIME_PORT", "VR_DATA_DIR", "VR_REPORTS_DIR",
    "VR_API_KEY", "HITHINK_FINANCE_API_KEY", "TUSHARE_TOKEN", "VR_SEC_CONTACT",
    "VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "VIBE_NATIVE_INTEL_DISABLE_SCHEDULER",
)


def _runtime_configuration():
    target = None
    try:
        parsed = urlparse(agent_runtime._base_url())
        target = parsed.port if parsed.port is not None else 80
        valid = 1 <= target <= 65535 and not (parsed.path or parsed.query or parsed.fragment)
    except (agent_runtime.AgentRuntimeError, ValueError):
        valid = False
    # Match server.mjs Number.parseInt(..., 10), including its permissive suffix rule.
    raw = os.environ.get("VR_AGENT_RUNTIME_PORT") or "8911"
    match = re.match(r"^\s*([+-]?[0-9]+)", raw)
    declared = None
    if match:
        digits = match[1].lstrip("+-").lstrip("0") or "0"
        if len(digits) <= 5:
            declared = int(("-" if match[1].startswith("-") else "") + digits)
    port_valid = declared is not None and 0 <= declared <= 65535
    state = "INVALID_CONFIGURATION"
    if valid and port_valid:
        state = "DYNAMIC_PORT_UNVERIFIED" if declared == 0 else (
            "PORTS_MATCH" if target == declared else "PORT_MISMATCH")
    return {
        "backend_target_port": target if valid else None,
        "backend_target_provenance": "VR_AGENT_RUNTIME_URL" if os.environ.get("VR_AGENT_RUNTIME_URL") else "DEFAULT",
        "declared_runtime_port": declared if port_valid else None,
        "declared_runtime_port_provenance": "VR_AGENT_RUNTIME_PORT" if os.environ.get("VR_AGENT_RUNTIME_PORT") else "DEFAULT",
        "configuration_status": state,
        "declaration_scope": "BACKEND_PROCESS_ENVIRONMENT_NOT_RUNNING_SIDECAR",
        "availability": "NOT_EVALUATED",
        "probe_performed": False,
    }


def _directory_status(path):
    """Metadata only; no mkdir, test-write, listing, file reads or returned paths."""
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return "LINK_NOT_INSPECTED"
        if not stat.S_ISDIR(info.st_mode):
            return "NOT_DIRECTORY"
        return "ACCESS_CHECK_OK" if os.access(path, os.R_OK | os.W_OK | os.X_OK) else "ACCESS_CHECK_FAILED"
    except FileNotFoundError:
        return "MISSING"
    except (OSError, ValueError):
        return "UNAVAILABLE"


def build_report(startup):
    """Startup identity is supplied by runtime-info; other metadata is observed now."""
    data = Path(os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research")
    reports = Path(os.environ.get("VR_REPORTS_DIR") or data / "myreports")
    env_names = frozenset(os.environ)  # Iteration reads names only; Mapping.__contains__ reads values.
    presence = [{"name": name, "present": name in env_names} for name in _CONFIG_NAMES]
    capabilities = [
        {"capability": "public_market_adapters", "configuration": "BUILTIN", "verification": "NOT_EVALUATED"},
        {"capability": "hithink", "configuration": "ENV_NAME_PRESENT_VALUE_NOT_INSPECTED" if "HITHINK_FINANCE_API_KEY" in env_names else "ENV_NAME_ABSENT", "verification": "NOT_EVALUATED"},
        {"capability": "tushare", "configuration": "ENV_NAME_PRESENT_VALUE_NOT_INSPECTED" if "TUSHARE_TOKEN" in env_names else "ENV_NAME_ABSENT", "verification": "NOT_EVALUATED"},
        {"capability": "sec", "configuration": "ENV_NAME_PRESENT_VALUE_NOT_INSPECTED" if "VR_SEC_CONTACT" in env_names else "PRIVATE_SETTINGS_NOT_INSPECTED", "verification": "NOT_EVALUATED"},
        {"capability": "model_provider", "configuration": "PRIVATE_SETTINGS_NOT_INSPECTED", "verification": "NOT_EVALUATED"},
        {"capability": "native_intel_sources", "configuration": "PRIVATE_SETTINGS_NOT_INSPECTED", "verification": "NOT_EVALUATED"},
    ]
    return {
        "schema": "runtime_diagnostics.v1",
        "mode": "READ_ONLY_NO_PROBES",
        "startup": {key: startup[key] for key in ("service", "version", "git_sha", "source_state")},
        "agent_runtime": _runtime_configuration(),
        "configuration_presence": presence,
        "directories": {"data": _directory_status(data), "reports": _directory_status(reports),
                        "write_verification": "NOT_EVALUATED"},
        "source_capabilities": capabilities,
        "limitations": ["ENV_PRESENCE_IS_NOT_VALIDITY", "DECLARED_PORT_IS_NOT_LISTENING_PORT",
                        "DIRECTORY_ACCESS_IS_NOT_WRITE_VERIFICATION", "NO_CREDENTIAL_OR_USER_DATA_READS"],
    }
