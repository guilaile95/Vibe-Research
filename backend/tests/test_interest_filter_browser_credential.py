"""Offline contract for the browser harness's real saved credential mirror."""
import os
from pathlib import Path
import subprocess
import sys


def test_interest_filter_harness_saves_generation_and_classifies_offline(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = r'''
from fastapi.testclient import TestClient
import interest_filter_harness_app as harness
import chat

def forbidden(*args, **kwargs):
    raise AssertionError("real model dispatch is forbidden")
chat.stream_messages = forbidden
client = TestClient(harness.app)
before = client.get('/api/ai/credential-status').json()
assert before['configured'] is False
model = {'provider': 'cli-codex', 'model': 'gpt-5-codex'}
saved_response = client.put('/api/ai/credential', json={**model, 'expectedRevision': before['revision']})
assert saved_response.status_code == 200, saved_response.text
saved = saved_response.json()
status = client.get('/api/ai/credential-status').json()
assert saved['configured'] is True
assert status['revision'] == saved['revision'] != before['revision']
assert 'apiKey' not in status
result = client.post('/api/native-intel/filter/apply-interest-update', json={
    'profile_id': 'default', 'interests_text': '重点关注芯片半导体以及大模型前沿技术',
    'min_score': 0.85, 'ai_config': {**model, 'revision': saved['revision']},
})
assert result.status_code == 200, result.text
profile = client.get('/api/native-intel/filter/profile').json()
assert profile['method'] == 'ai'
assert profile['min_score'] == 0.85
assert profile['profile_fingerprint']
assert len(profile['tags']) >= 2
'''
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=tmp_path,
        env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(root / 'backend'), str(root / 'frontend/tests/e2e')]),
             'VR_DATA_DIR': str(tmp_path / 'data'), 'VIBE_NATIVE_INTEL_DB': str(tmp_path / 'native.sqlite3'),
             'VR_API_KEY': '', 'VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH': '1'},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
