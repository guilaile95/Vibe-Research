"""Validate the browser harness's actual aggregation offline, without a browser."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_pool_browser_harness_actual_app_contract(tmp_path):
    root = Path(__file__).resolve().parents[2]
    code = '''
import json
import daily_review_harness_app as harness
from fastapi.testclient import TestClient
client = TestClient(harness.app)
results = []
for name in ("qualified", "secondary_failure", "empty_zt"):
    assert client.post("/api/e2e/daily-review/pool-scenario/" + name).status_code == 200
    response = client.get("/api/daily-review")
    assert response.status_code == 200, response.text
    review = response.json()["data"]
    emotion = review["short_term_emotion"]
    data = emotion["data"]
    assert emotion["status"] == "partial" and data["date_verified"] is False
    assert review["trade_date"] is None and data["source_business_date"] is None
    assert data["date"] == "2026-10-09" and data["requested_date"] == "2026-10-10"
    assert data["as_of"] == "2026-10-10T04:10:00Z"
    assert emotion["warnings"]
    pools = data["pool_observations"]
    assert set(pools) == {"zt", "zb", "dt", "yzt"}
    for key, observation in pools.items():
        expected_latest = None if name == "secondary_failure" and key != "zt" else "2026-10-09"
        assert observation["requested_trade_date"] == "2026-10-09"
        assert observation["provider_latest_trade_date"] == expected_latest
        assert observation["source_business_date"] is None and observation["date_verified"] is False
    if name == "qualified":
        assert data["zt_count"] == data["dt_count"] == 1
        assert data["seal_rate"] == data["break_rate"] == 0.5
        refreshed = client.post("/api/daily-review/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["data"]["short_term_emotion"]["status"] == "partial"
    elif name == "secondary_failure":
        assert data["zt_count"] == 1 and data["dt_count"] is None
        assert data["seal_rate"] is None
    else:
        assert data["zt_count"] is None and data["lianban_count"] is None
        assert data["pool_observations"]["zt"]["observed_empty"] is True
    results.append({"scenario": name, "status": emotion["status"]})
print("POOL_HARNESS_RESULT=" + json.dumps(results))
'''
    env = {**os.environ,
           "VR_E2E_POOL_PROVENANCE": "1", "VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH": "1",
           "VR_DATA_DIR": str(tmp_path / "data"), "VR_REPORTS_DIR": str(tmp_path / "reports"),
           "VIBE_RESEARCH_REVIEW_DB": str(tmp_path / "review.sqlite3"),
           "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join([str(root / "backend"), str(root / "frontend/tests/e2e")])}
    run = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                         text=True, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    line = next(line for line in run.stdout.splitlines() if line.startswith("POOL_HARNESS_RESULT="))
    assert len(json.loads(line.split("=", 1)[1])) == 3
