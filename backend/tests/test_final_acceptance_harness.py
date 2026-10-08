"""The browser's real API fixture must fail closed and write only temporary data."""
from pathlib import Path
import os
import subprocess
import sys


def test_final_browser_harness_production_routes_and_guards(tmp_path):
    root = tmp_path / "isolated"
    root.mkdir()
    for name in ("home", "tmp", "reports", "data"):
        (root / name).mkdir()
    env = {**os.environ, "VR_FINAL_FIXTURE_ROOT": str(root), "VR_DATA_DIR": str(root / "data"),
           "VR_REPORTS_DIR": str(root / "reports"), "VIBE_RESEARCH_REVIEW_DB": str(root / "review.db"),
           "VIBE_RESEARCH_CAMPAIGN_DB": str(root / "campaign.db"), "VIBE_RESEARCH_EVIDENCE_THESIS_DB": str(root / "evidence.db"),
           "HOME": str(root / "home"), "USERPROFILE": str(root / "home"), "TMPDIR": str(root / "tmp"), "TEMP": str(root / "tmp"), "TMP": str(root / "tmp"),
           "PYTHONDONTWRITEBYTECODE": "1", "VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH": "1", "VR_API_KEY": "", "VR_ALLOW_ORIGINS": "http://127.0.0.1"}
    script = Path(__file__).resolve().parents[2] / "frontend/tests/e2e/final_acceptance_harness_app.py"
    result = subprocess.run([sys.executable, str(script), "--verify-fixture"], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"result": "PASS"' in result.stdout
    assert not (root.parent / "forbidden-probe").exists()
