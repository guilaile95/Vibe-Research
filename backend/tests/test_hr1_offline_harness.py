"""Test-only provider isolation stays outside production app imports."""
from pathlib import Path
import os
import subprocess
import sys


def test_hr1_harness_keeps_authorities_and_blocks_unexpected_network(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = r'''
import socket
from fastapi.testclient import TestClient
import hr1_offline_harness_app as fixture
import app
import decision_inbox_runtime_assembler as inbox
import campaign_critical_data_runtime as cdr
import hard_risk_runtime
assert fixture.app is app.app
assert inbox.PRODUCTION_PORTS.hard_risk_evaluator is inbox._production_hard_risk_evaluator
assert inbox.PRODUCTION_PORTS.disclosures_evaluator is cdr.production_disclosures_evaluator
assert inbox.PRODUCTION_PORTS.financials_evaluator is cdr.production_financials_evaluator
with TestClient(fixture.app) as client:
    audit = client.get('/api/hr1-fixture-network-audit').json()['data']
    assert audit == {'mode': 'SYNTHETIC_PUBLIC_PROVIDERS', 'attempts': []}
    # Use documentation-only host/IP; the guard must fail before any DNS or I/O.
    for invoke in [lambda: socket.getaddrinfo('provider.invalid', 443),
                   lambda: socket.socket().connect(('192.0.2.1', 443)),
                   lambda: socket.socket().connect_ex(('192.0.2.1', 443))]:
        try:
            invoke()
        except OSError as exc:
            assert 'HR1 offline harness blocked' in str(exc)
        else:
            raise AssertionError('outbound operation was not blocked')
    assert len(client.get('/api/hr1-fixture-network-audit').json()['data']['attempts']) == 3
print('HR1_OFFLINE_GUARD_OK')
'''
    env = {**os.environ, 'VR_DATA_DIR': str(tmp_path), 'VR_REPORTS_DIR': str(tmp_path),
           'PYTHONPATH': os.pathsep.join([str(root / 'frontend/tests/e2e'), str(root / 'backend')])}
    result = subprocess.run([sys.executable, '-c', script], env=env, cwd=root,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'HR1_OFFLINE_GUARD_OK' in result.stdout
