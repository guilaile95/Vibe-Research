"""Compile real pytest IDs without executing any provider fixture."""
import os
from pathlib import Path
import subprocess
import sys


def test_public_capture_parameter_ids_are_bounded(tmp_path):
    backend=Path(__file__).resolve().parents[1]
    env=dict(os.environ, PYTHONPATH=str(backend), VR_DATA_DIR=str(tmp_path),
             VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH='1', VIBE_NATIVE_INTEL_DISABLE_SCHEDULER='1')
    result=subprocess.run([sys.executable,'-m','pytest','--collect-only','-q',
                           'tests/test_public_research_capture.py'],cwd=backend,env=env,
                          capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stderr
    ids=[line for line in result.stdout.splitlines() if '::test_' in line]
    assert len(ids)==20
    assert max(map(len,ids))<200
    rejected=[line for line in ids if 'test_transport_rejection_does_not_publish_receipt' in line]
    assert len(rejected)==6
    assert any('[stream-oversize]' in line for line in rejected)
