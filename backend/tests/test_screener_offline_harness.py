"""Offline harness guards are tested without launching Uvicorn or a browser."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT/'frontend/tests/e2e/screener_offline_harness_app.py'


def environment(tmp_path):
    return {**os.environ, 'VR_DATA_DIR':str(tmp_path),
            'VIBE_RESEARCH_RESEARCH_DATA_DIR':str(tmp_path/'rdp'),
            'VR_SCREENER_NETWORK_LOG':str(tmp_path/'network.json'),
            'VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH':'1',
            'VR_ALLOW_ORIGINS':'http://127.0.0.1:41979',
            'PYTHONPATH':os.pathsep.join([str(HARNESS.parent),str(ROOT/'backend')])}


def test_network_guard_blocks_before_dns_tcp_udp_or_loopback(tmp_path):
    result = subprocess.run([sys.executable,str(HARNESS),'--verify-guard'],
                            env=environment(tmp_path),capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['blocked_before_network'] == 6
    assert json.loads((tmp_path/'network.json').read_text()) == [
        'external_dns', 'external_dns', 'socket.create_connection',
        'socket.connect', 'socket.connect', 'socket.sendto']


def test_actual_screener_route_runs_with_zero_forbidden_attempts(tmp_path):
    # Pre-create a loop before the audit hook, as Uvicorn does. Windows socketpair
    # initialization needs no broad loopback exception after guard installation.
    program = '''
import asyncio,json
loop=asyncio.SelectorEventLoop()
import screener_offline_harness_app as harness
from fastapi.testclient import TestClient
with TestClient(harness.app,backend_options={'loop_factory':lambda:loop}) as client:
    result=client.post('/api/screener/evaluate',json={'codes':['000001'],'conditions':[{'id':'price_gt_sma20'}]})
    assert result.status_code==200,result.text
    assert result.json()['status']=='unavailable'
assert harness.violations==[],harness.violations
print(json.dumps({'attempts':harness.violations}))
'''
    result = subprocess.run([sys.executable,'-c',program],env=environment(tmp_path),
                            capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['attempts'] == []
    assert json.loads((tmp_path/'network.json').read_text()) == []


def test_complete_browser_request_inventory_uses_real_origin_gate_and_routes(tmp_path):
    result = subprocess.run([sys.executable,str(HARNESS.parent/'screener_request_contract_probe.py')],
                            env=environment(tmp_path),capture_output=True,text=True,timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['forbidden_attempts'] == []
    assert receipt['fixture_files_unchanged'] is True
    assert len(receipt['inventory']) == 15
    assert [item['http_status'] for item in receipt['inventory'] if item['case']=='reject-other-origin'] == [403]*5
