"""Import the aggregate router in a fresh interpreter, without pytest import ordering."""
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("first_module", ["technical_indicators_router", "app"])
def test_router_import_order_preserves_all_registered_routes(first_module, tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VR_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(tmp_path / "review.sqlite3"))
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "1")
    result = subprocess.run(
        [sys.executable, "-c", f"""
import importlib
importlib.import_module({first_module!r})
import app
import technical_indicators_router as aggregate
expected = {{
    '/api/market/technical-indicators',
    '/api/market/dragon-tiger',
    '/api/market/northbound/history',
    '/api/screener/discovery',
    '/api/alert-rules',
}}
assert expected <= {{route.path for route in aggregate.router.routes}}
assert expected <= set(app.app.openapi()["paths"])
"""],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
