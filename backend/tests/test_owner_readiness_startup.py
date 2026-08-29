"""Owner-readiness checks for cold startup and the Windows one-click launcher."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

import native_intel_service as service


REPO_ROOT = Path(__file__).resolve().parents[2]


def _registry() -> dict:
    return {
        "sources": [
            {
                "source_id": "startup-test",
                "name": "Startup Test",
                "hint": "a-share",
                "url": "https://example.test/feed.xml",
                "source_type": "rss",
                "has_real_rank": False,
            }
        ],
        "registry_version": "startup-test-v1",
        "redline": [],
        "recent_days": 7,
        "per_source": 6,
    }


def test_startup_recover_schedules_stale_fetch_without_blocking_and_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = str(tmp_path / "native-intel.sqlite3")
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls: list[tuple[str, str]] = []

    monkeypatch.delenv(service._ENV_DISABLE_STARTUP_FETCH, raising=False)
    monkeypatch.setattr(service, "load_registry", _registry)

    def fake_run_fetch(trigger: str, target: str, *, registry=None, **_kwargs):
        calls.append((trigger, target))
        started.set()
        assert release.wait(5), "test did not release background startup fetch"
        finished.set()
        return {"status": "ok", "trigger": trigger}

    monkeypatch.setattr(service, "run_fetch", fake_run_fetch)

    try:
        first = service.startup_recover(path)
        assert first["initial_fetch"] == {"status": "scheduled", "trigger": "startup"}
        assert started.wait(1), "background startup fetch did not start"

        # The first fetch is still blocked, so a second lifespan/recovery call must
        # return immediately and must not mark the in-flight run as stale or duplicate it.
        second = service.startup_recover(path)
        assert second["reclaimed_runs"] == 0
        assert second["initial_fetch"] == {
            "status": "already_running",
            "trigger": "startup",
        }
        assert calls == [("startup", path)]
    finally:
        release.set()

    assert finished.wait(2), "background startup fetch did not finish"
    deadline = time.monotonic() + 2
    while service._startup_fetch_is_running(path) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not service._startup_fetch_is_running(path)


def test_startup_recover_keeps_explicit_synchronous_maintenance_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = str(tmp_path / "native-intel.sqlite3")
    expected = {"status": "ok", "trigger": "startup", "run_id": "fixture"}
    calls: list[tuple[str, str]] = []

    monkeypatch.delenv(service._ENV_DISABLE_STARTUP_FETCH, raising=False)
    monkeypatch.setattr(service, "load_registry", _registry)

    def fake_run_fetch(trigger: str, target: str, *, registry=None, **_kwargs):
        calls.append((trigger, target))
        return expected

    monkeypatch.setattr(service, "run_fetch", fake_run_fetch)

    result = service.startup_recover(path, background_fetch=False)

    assert result["initial_fetch"] == expected
    assert calls == [("startup", path)]


def test_offline_startup_fetch_disable_is_explicit_and_zero_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = str(tmp_path / "native-intel.sqlite3")
    monkeypatch.setenv(service._ENV_DISABLE_STARTUP_FETCH, "1")
    monkeypatch.setattr(service, "load_registry", _registry)

    def forbidden_fetch(*_args, **_kwargs):
        raise AssertionError("startup fetch must remain disabled")

    monkeypatch.setattr(service, "run_fetch", forbidden_fetch)

    result = service.startup_recover(path)

    assert result["initial_fetch"] == {
        "status": "disabled",
        "reason": "startup_fetch_disabled",
    }


def test_windows_launcher_contract_uses_pwsh_and_keeps_runtime_state_private() -> None:
    cmd_path = REPO_ROOT / "Start-Vibe.cmd"
    script_path = REPO_ROOT / "start-vibe.ps1"
    ignore_path = REPO_ROOT / ".gitignore"

    cmd = cmd_path.read_text(encoding="utf-8").lower()
    script = script_path.read_text(encoding="utf-8")
    ignore = ignore_path.read_text(encoding="utf-8")

    assert "pwsh.exe" in cmd
    assert "powershell.exe" not in cmd
    assert "%*" in cmd
    assert script.startswith("#requires -Version 7.0")
    assert "[switch]$ValidateOnly" in script
    assert "[switch]$SmokeTest" in script
    assert "One-click launcher smoke: PASS" in script
    assert "app:app" in script
    assert 'Get-Command "node.exe"' in script
    assert "'^v22\\.'" in script
    assert '$FrontendUrl = "http://127.0.0.1:5899"' in script
    assert "npm.cmd" in script
    assert ".vibe-runtime/" in ignore


def test_all_browser_e2e_scripts_preload_the_deterministic_runtime_environment() -> None:
    package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    e2e_scripts = {
        name: command
        for name, command in package["scripts"].items()
        if name.startswith("test:e2e:")
    }
    assert e2e_scripts
    for name, command in e2e_scripts.items():
        assert "node --import ./tests/e2e/runtime-env.mjs " in command, name

    runtime_env = (
        REPO_ROOT / "frontend" / "tests" / "e2e" / "runtime-env.mjs"
    ).read_text(encoding="utf-8")
    assert "VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH" in runtime_env
    assert 'process.env.VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH = "1"' in runtime_env


@pytest.mark.skipif(os.name != "nt", reason="PowerShell launcher syntax is validated on Windows CI")
def test_windows_launcher_validate_only_under_pwsh() -> None:
    proc = subprocess.run(
        [
            "pwsh.exe",
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(REPO_ROOT / "start-vibe.ps1"),
            "-ValidateOnly",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert proc.returncode == 0, (
        f"pwsh launcher validation failed\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "One-click launcher validation: PASS" in proc.stdout
