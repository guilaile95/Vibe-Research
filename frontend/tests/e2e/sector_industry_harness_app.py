"""Isolated input fixture for the real Sector Industry Matrix vertical.

The production FastAPI app and the production matrix service are used as-is.
Only the external raw current snapshot is controlled and the RDP is imported
into the temporary root supplied by the browser runner; the production
Eastmoney mapper still converts raw fields into the normalized snapshot, and
the matrix calculation is never replaced by an HTTP mock or a harness endpoint.
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


def _raw_row(
    code: str,
    name: str,
    industry: str | None,
    *,
    change_pct: float | None,
    turnover_pct: float | None,
    amount: float | None,
    dynamic_pe: float | str | None,
    ttm_pe: float | str | None,
    pb: float | str | None,
    market_cap: float | str | None,
) -> dict:
    return {
        "f2": 10.0,
        "f3": change_pct,
        "f4": 0.1,
        "f5": 1000.0,
        "f6": amount,
        "f7": 1.0,
        "f8": turnover_pct,
        "f9": dynamic_pe,
        "f12": code,
        "f13": 0,
        "f14": name,
        "f15": 11.0,
        "f16": 9.0,
        "f17": 10.0,
        "f18": 9.9,
        "f20": market_cap,
        "f21": market_cap,
        "f23": pb,
        "f26": 20200102,
        "f100": industry,
        "f115": ttm_pe,
    }


# Raw Eastmoney-shaped fixture: f9 is intentionally different from f115 so
# the old dynamic-PE-as-TTM mapper fails this vertical.
_RAW_SNAPSHOT = [
    _raw_row("000001", "电子甲", "电子", change_pct=2.0, turnover_pct=3.0, amount=100.0, dynamic_pe=100.0, ttm_pe=10.0, pb=1.0, market_cap=100.0),
    _raw_row("000002", "电子乙", "电子", change_pct=-1.0, turnover_pct=0.0, amount=0.0, dynamic_pe=200.0, ttm_pe=20.0, pb=2.0, market_cap=200.0),
    _raw_row("000003", "电子丙", "电子", change_pct=0.0, turnover_pct=None, amount=None, dynamic_pe=50.0, ttm_pe=0.0, pb=-1.0, market_cap=0.0),
    _raw_row("000004", "医药甲", "医药", change_pct=1.0, turnover_pct=4.0, amount=200.0, dynamic_pe=50.0, ttm_pe=5.0, pb=1.0, market_cap=300.0),
    _raw_row("000005", "传媒甲", "传媒", change_pct=-2.0, turnover_pct=5.0, amount=300.0, dynamic_pe=-50.0, ttm_pe=-5.0, pb=None, market_cap=500.0),
    _raw_row("000007", "医药乙", "医药", change_pct=-1.0, turnover_pct=2.0, amount=50.0, dynamic_pe=999.0, ttm_pe="-", pb=3.0, market_cap=400.0),
    _raw_row("000006", "未知甲", None, change_pct=None, turnover_pct=None, amount=None, dynamic_pe=777.0, ttm_pe=None, pb=0.0, market_cap=600.0),
]


def _snapshot() -> list[dict]:
    snapshot = []
    for raw in _RAW_SNAPSHOT:
        mapped = app_module.astock._map_a_share_row(raw)
        if mapped is not None:
            snapshot.append(mapped)
    return snapshot


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
