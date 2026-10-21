"""Synthetic regression for inherited user-store writes during direct pytest."""
import os
from pathlib import Path
import subprocess
import sys

from validation_environment import (
    AUTOMATIC_TASK_FLAGS, PATH_NAMES, configure_pytest_environment,
    legacy_private_inputs_present,
)


def test_policy_resets_future_overrides_and_credentials_on_all_platforms(tmp_path):
    env = {name: "SYNTHETIC_CANARY" for name in (
        "VIBE_NATIVE_INTEL_DB", "VIBE_RESEARCH_FUTURE_DB", "VR_FUTURE_PATH",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TUSHARE_TOKEN",
        "HITHINK_FINANCE_API_KEY", "http_proxy", "NETRC", "HOMEDRIVE",
        "HOMEPATH", "COMPANY_RESEARCH_GOLDEN_DIR",
    )}
    env.update(PATH="platform-executables", SystemRoot="platform-system")
    configure_pytest_environment(tmp_path, env)
    assert "SYNTHETIC_CANARY" not in env.values()
    assert env["PATH"] == "platform-executables"
    assert env["SystemRoot"] == "platform-system"
    for name in PATH_NAMES:
        assert Path(env[name]).resolve().is_relative_to(tmp_path.resolve())
    for name in AUTOMATIC_TASK_FLAGS:
        assert env[name] == "1"


def test_legacy_guard_checks_metadata_only(tmp_path, monkeypatch):
    cache = tmp_path / "backend" / ".cache"
    cache.mkdir(parents=True)
    assert not legacy_private_inputs_present(tmp_path)
    (cache / "portfolio.json").write_text("SYNTHETIC_PRIVATE_INPUT")
    monkeypatch.setattr(Path, "open", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not read legacy input")))
    assert legacy_private_inputs_present(tmp_path)


def test_direct_pytest_preserves_inherited_external_native_database(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    sentinel = tmp_path / "synthetic-external-native.sqlite3"
    script = r'''
import hashlib, json, os, pathlib, sqlite3, sys
import native_intel_store as intel
sentinel = pathlib.Path(sys.argv[1])
intel.start_run('synthetic-active-user-run', 'manual', 1, sentinel)
before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
os.environ['VIBE_NATIVE_INTEL_DB'] = str(sentinel)
os.environ['VIBE_RESEARCH_FUTURE_DB'] = str(sentinel)
os.environ['OPENAI_API_KEY'] = 'SYNTHETIC_NOT_A_REAL_KEY'
os.environ['VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH'] = '0'
os.environ['VIBE_NATIVE_INTEL_DISABLE_SCHEDULER'] = '0'
import pytest
code = pytest.main(['-q', 'tests/test_decision_evidence_api.py::test_list_decision_evidence_empty', '-p', 'no:cacheprovider'])
assert code == 0
assert 'VIBE_NATIVE_INTEL_DB' not in os.environ
assert 'VIBE_RESEARCH_FUTURE_DB' not in os.environ
assert 'OPENAI_API_KEY' not in os.environ
assert os.environ['VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH'] == '1'
assert os.environ['VIBE_NATIVE_INTEL_DISABLE_SCHEDULER'] == '1'
assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == before
with sqlite3.connect(sentinel) as connection:
    status = connection.execute("SELECT status FROM intel_fetch_runs WHERE run_id='synthetic-active-user-run'").fetchone()[0]
assert status == 'running'
print('SYNTHETIC_EXTERNAL_DATABASE_UNCHANGED')
'''
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(sentinel)], cwd=backend, env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "SYNTHETIC_EXTERNAL_DATABASE_UNCHANGED" in completed.stdout
