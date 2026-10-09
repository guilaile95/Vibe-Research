"""Run a synthetic, local-only two-generation replay; print a portable JSON receipt.

From repository root: python tools/research/rdp_snapshot_replay_demo.py
Uses the project's installed DuckDB dependency. No user data or network is used.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import research_data_plane as rdp  # noqa: E402


CSV = """code,trade_date,open,high,low,close,volume
600519,2026-08-20,10,12,9,11,1000
600519,2026-08-21,11,15,10,12,1100
"""


def run_demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="rdp-replay-demo-") as directory:
        root = Path(directory) / "rdp"
        source = Path(directory) / "synthetic-bars.csv"
        source.write_text(CSV, encoding="utf-8")
        first = rdp.import_csv(source, root=root, imported_at="2026-08-25T00:00:00Z")
        query = {"as_of": "2026-08-21", "latest": False, "limit": 200, "offset": 0}
        before = rdp.query_full_market(root=root, **query)
        source.write_text(CSV.replace(",10,12,1100", ",10,14,1100"), encoding="utf-8")
        second = rdp.import_csv(source, root=root, imported_at="2026-08-26T00:00:00Z")
        latest = rdp.query_full_market(root=root, **query)
        replay = rdp.query_full_market(root=root, snapshot_id=first["snapshot_id"], **query)
        assert before["rows"][0]["latest_close"] == replay["rows"][0]["latest_close"] == 12
        assert latest["rows"][0]["latest_close"] == 14
        assert before["replay_receipt"] == replay["replay_receipt"]
        return {
            "fixture": "SYNTHETIC_OFFLINE_ONLY",
            "status": "PASS",
            "generation_a_close": before["rows"][0]["latest_close"],
            "current_generation_b_close": latest["rows"][0]["latest_close"],
            "replayed_generation_a_close": replay["rows"][0]["latest_close"],
            "generation_b_snapshot_id": second["snapshot_id"],
            "saved_replay_receipt": before["replay_receipt"],
            "replayed_receipt_matches": True,
            "limitations": [
                "Replay identifies the imported dataset, not what was publicly known on as_of.",
                "No market provider, model, profitability, UI, or natural workflow is evaluated.",
                "Snapshot IDs depend on exact Parquet bytes and manifest metadata; regenerate this demo under the installed dependency version.",
                "Temporary fixture files are removed on exit; retain real snapshot archives and artifacts for real replay.",
            ],
        }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2, sort_keys=True))
