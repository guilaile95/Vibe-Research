"""Real loopback restart + explicitly synthetic nextday; not browser/live evidence."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).with_name('saved_research_restart_harness.py')
NODE_REPLAY = REPO / 'frontend/tests/savedResearchRestartReplay.test.ts'
DAY_ONE = '2026-10-19T12:00:00.000000Z'
DAY_TWO = '2026-10-20T12:00:00.000000Z'


def environment(root, phase='capture', clock=DAY_ONE):
    # OS essentials only: no inherited keys, proxies, DB overrides, injection
    # flags, browser profile, or user's HOME.
    env = {key: os.environ[key] for key in ('PATH', 'SystemRoot', 'WINDIR') if key in os.environ}
    for name in ('home', 'tmp', 'data', 'reports'):
        (root / name).mkdir(parents=True, exist_ok=True)
    env.update({
        'VR_SAVED_JOURNEY_ROOT': str(root), 'VR_SAVED_JOURNEY_PHASE': phase,
        'VR_SAVED_JOURNEY_CLOCK': clock, 'VR_DATA_DIR': str(root / 'data'),
        'VR_REPORTS_DIR': str(root / 'reports'), 'HOME': str(root / 'home'),
        'USERPROFILE': str(root / 'home'), 'TMPDIR': str(root / 'tmp'),
        'TEMP': str(root / 'tmp'), 'TMP': str(root / 'tmp'),
        'PYTHONDONTWRITEBYTECODE': '1', 'VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH': '1',
        'VR_ALLOW_ORIGINS': 'http://127.0.0.1',
    })
    return env


def request(port, method, path, body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
    try:
        conn.request(method, path, None if body is None else json.dumps(body), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        raw = response.read().decode()
        assert response.status == 200, raw
        return raw
    finally:
        conn.close()


def ready(root, proc):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        assert proc.poll() is None, (root / 'server.log').read_text(errors='replace')
        try:
            value = json.loads((root / 'ready.json').read_text())
            receipt = json.loads(request(value['port'], 'GET', '/api/e2e/saved-audit'))
            assert receipt['pid'] == value['pid']
            return value
        except (OSError, ValueError, http.client.HTTPException):
            time.sleep(.05)
    raise AssertionError('Fixture did not become ready')


@contextmanager
def server(root, phase, clock):
    env = environment(root, phase, clock)
    (root / 'ready.json').unlink(missing_ok=True)
    with (root / 'server.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, str(HARNESS)], cwd=root, env=env,
                                stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            yield proc, ready(root, proc)
        finally:
            # Full kill and wait, not an in-process client/module reset.
            if proc.poll() is None: proc.kill()
            proc.wait(timeout=10)
            proc.stdin.close()


def node_replay(root, phase, clock):
    node = shutil.which('node')
    assert node, 'Node >=22 required; saved replay may not silently skip'
    env = environment(root, phase, clock)
    env.update(VR_SAVED_REPLAY_FILE=str(root / 'localstorage.json'),
               VR_SAVED_REPLAY_RECORD=str(root / 'record.json'), VR_SAVED_REPLAY_PHASE=phase)
    result = subprocess.run([node, '--experimental-strip-types', str(NODE_REPLAY)],
                            env=env, cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    marker = 'SAVED_REPLAY_RECEIPT='
    line = next(line for line in result.stdout.splitlines() if marker in line)
    return json.loads(line.split(marker, 1)[1])


def sqlite_state(root):
    raw = (root / 'data/company_research.sqlite3').read_bytes()
    conn = sqlite3.connect(':memory:')
    try:
        conn.deserialize(raw)
        rows = {table: conn.execute(f'SELECT * FROM {table} ORDER BY id').fetchall() for table in ('bundles', 'runs')}
        return hashlib.sha256(raw).hexdigest(), rows
    finally:
        conn.close()


def test_saved_research_full_restart_and_simulated_nextday(tmp_path):
    root = tmp_path / 'journey'
    with server(root, 'capture', DAY_ONE) as (first, endpoint):
        port = endpoint['port']
        bundle = json.loads(request(port, 'POST', '/api/company-research/capture', {
            'market': 'A', 'symbol': '600519', 'confirm_public_fetch': True}))['data']
        events = [json.loads(line) for line in request(port, 'POST', '/api/company-research/generate', {
            'market': 'A', 'symbol': '600519', 'bundle_id': bundle['bundle_id'],
            'expected_bundle_sha256': bundle['bundle_sha256'], 'confirm_model_calls': True,
            'llm': {'provider': 'fixture', 'model': 'fixture', 'baseURL': 'https://fixture.invalid/v1'},
        }).splitlines()]
        assert events[-1]['type'] == 'done', events
        record = events[-1]['record']
        assert record['status'] == 'COMPLETED' and len(record['stages']) == 6
        assert record['started_at'] == record['finished_at'] == bundle['captured_at'] == DAY_ONE
        assert all(stage['input_bundle_sha256'] == bundle['bundle_sha256'] for stage in record['stages'])
        receipt = json.loads(request(port, 'GET', '/api/e2e/saved-audit'))
        assert receipt['adapter_calls'] == {'public': 1, 'model': 6}
        assert receipt['violations'] == []
        (root / 'record.json').write_text(json.dumps(record))
        note = node_replay(root, 'capture', DAY_ONE)
        saved = sqlite_state(root)
    assert first.returncode is not None
    raw_storage = (root / 'localstorage.json').read_bytes()
    for phase, clock in [('restart', DAY_ONE), ('synthetic-nextday', DAY_TWO)]:
        with server(root, phase, clock) as (restarted, endpoint):
            assert first.poll() is not None
            assert json.loads(request(endpoint['port'], 'GET', '/api/company-research/runs'))['data'] == [record]
            assert json.loads(request(endpoint['port'], 'GET', '/api/company-research/bundles/' + bundle['bundle_id']))['data'] == bundle
            receipt = json.loads(request(endpoint['port'], 'GET', '/api/e2e/saved-audit'))
            assert receipt['clock'] == clock
            assert receipt['date_mode'] == 'SIMULATED_NOT_NATURAL_ELAPSED'
            assert receipt['adapter_calls'] == {'public': 0, 'model': 0}
            assert receipt['violations'] == []
            replay = node_replay(root, phase, clock)
            assert replay['note'] == note['note']
            assert replay['raw_sha256'] == note['raw_sha256'] and replay['writes'] == 0
            assert replay['external_attempts'] == []
            assert (root / 'localstorage.json').read_bytes() == raw_storage
            assert sqlite_state(root) == saved
        assert restarted.returncode is not None


def test_fixture_exits_after_abrupt_owner_death(tmp_path):
    root = tmp_path / 'owner-death'
    env = environment(root)
    owner_code = '''import subprocess,sys,time
with open('server.log','w') as log:
    child = subprocess.Popen([sys.executable, sys.argv[1]], stdin=subprocess.PIPE, stdout=log, stderr=log)
    time.sleep(120)
'''
    owner = subprocess.Popen([sys.executable, '-c', owner_code, str(HARNESS)], env=env, cwd=root)
    try:
        endpoint = ready(root, owner)
        owner.kill()
        owner.wait(timeout=10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                request(endpoint['port'], 'GET', '/api/e2e/saved-audit')
            except (OSError, http.client.HTTPException):
                break
            time.sleep(.05)
        else:
            raise AssertionError('Orphaned fixture still serves after owner death')
    finally:
        if owner.poll() is None: owner.kill()
        owner.wait(timeout=10)


def test_fixture_environment_does_not_inherit_secrets(tmp_path, monkeypatch):
    for key in ('OPENAI_API_KEY', 'HTTPS_PROXY', 'NODE_OPTIONS', 'PYTHONPATH', 'VIBE_RESEARCH_REVIEW_DB', 'VR_API_KEY'):
        monkeypatch.setenv(key, 'synthetic-secret-sentinel')
    assert not any(value == 'synthetic-secret-sentinel' for value in environment(tmp_path / 'environment').values())


def test_fixture_guards_record_blocked_attempts(tmp_path):
    root = tmp_path / 'probes'
    with server(root, 'guard-probes', DAY_ONE) as (_, endpoint):
        receipt = json.loads(request(endpoint['port'], 'GET', '/api/e2e/guard-probes'))
        assert receipt['violations'] == ['socket.connect', 'external_dns', 'write_outside_fixture', 'sqlite_outside_fixture', 'subprocess.Popen']
        assert receipt['adapter_calls'] == {'public': 0, 'model': 0}
    assert not (tmp_path / 'forbidden-probe').exists()
    assert not (tmp_path / 'forbidden-probe.db').exists()
