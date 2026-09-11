"""Isolated input fixture for the real Sector Industry Matrix vertical.

The production FastAPI app and the production matrix service are used as-is.
Only the external current snapshot is controlled and the RDP is imported into
the temporary root supplied by the browser runner; the matrix calculation is
never replaced by an HTTP mock or a harness endpoint.
"""
from __future__ import annotations

import csv
import os
from datetime import date, timedelta
from pathlib import Path

import app as app_module
import research_data_plane as rdp

# Reuse the existing real-app harness for unrelated sector endpoints so this
# vertical remains focused on the new matrix rather than duplicating fixtures.
from harness_app import app  # noqa: F401,E402


def _snapshot() -> list[dict]:
    return [
        {"code": "000001", "name": "电子甲", "industry": "电子", "change_pct": 2.0, "turnover_pct": 3.0, "amount": 100.0, "pe_ttm": 10.0, "pb": 1.0, "market_cap": 100.0},
        {"code": "000002", "name": "电子乙", "industry": "电子", "change_pct": -1.0, "turnover_pct": 0.0, "amount": 0.0, "pe_ttm": 20.0, "pb": 2.0, "market_cap": 200.0},
        {"code": "000003", "name": "电子丙", "industry": "电子", "change_pct": 0.0, "turnover_pct": None, "amount": None, "pe_ttm": 0.0, "pb": -1.0, "market_cap": 0.0},
        {"code": "000004", "name": "医药甲", "industry": "医药", "change_pct": 1.0, "turnover_pct": 4.0, "amount": 200.0, "pe_ttm": 5.0, "pb": 1.0, "market_cap": 300.0},
        {"code": "000005", "name": "传媒甲", "industry": "传媒", "change_pct": -2.0, "turnover_pct": 5.0, "amount": 300.0, "pe_ttm": -5.0, "pb": None, "market_cap": 500.0},
        {"code": "000007", "name": "医药乙", "industry": "医药", "change_pct": -1.0, "turnover_pct": 2.0, "amount": 50.0, "pe_ttm": None, "pb": 3.0, "market_cap": 400.0},
        {"code": "000006", "name": "未知甲", "industry": None, "change_pct": None, "turnover_pct": None, "amount": None, "pe_ttm": None, "pb": 0.0, "market_cap": 600.0},
    ]


def _write_rdp_fixture() -> None:
    root = Path(os.environ["VIBE_RESEARCH_RESEARCH_DATA_DIR"])
    source = root.parent / "sector-industry-context.csv"
    root.mkdir(parents=True, exist_ok=True)
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "trade_date", "open", "high", "low", "close", "volume"])
        start = date(2026, 1, 2)
        for index in range(30):
            trade_date = (start + timedelta(days=index)).isoformat()
            values = {
                "000001": (100.0 + index * 2, 1000.0 + index),
                "000002": (200.0 - index * 3, 1200.0 + index),
                "000004": (80.0 + index, 900.0 + index),
                "000005": (160.0 - index * 2, 800.0 + index),
            }
            for code, (close, volume) in values.items():
                writer.writerow([code, trade_date, close, close + 1, close - 1, close, volume])
        # Short history remains in the RDP but cannot prove 20d/MA20 metrics.
        for index in range(10):
            trade_date = (start + timedelta(days=index)).isoformat()
            close = 50.0 + index
            writer.writerow(["000003", trade_date, close, close + 1, close - 1, close, 500.0 + index])
    rdp.import_csv(source, root=root, imported_at="2026-09-08T00:00:00Z")


_write_rdp_fixture()
app_module.astock.a_share_snapshot = _snapshot  # type: ignore[assignment]

if os.environ.get("SECTOR_INDUSTRY_E2E_RDP_FAILURE") == "1":
    def _broken_rdp(**_kwargs):
        raise RuntimeError("isolated RDP failure fixture")

    app_module.sic.rdp.query_full_market = _broken_rdp
