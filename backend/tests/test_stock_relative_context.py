from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import stock_relative_context as context
import stock_relative_context_router as router


DATE = "2026-09-11"


def _snapshot(*, unknown: bool = False, fourth_industry: str = "银行") -> list[dict[str, Any]]:
    return [
        {"code": "000001", "industry": None if unknown else "电子"},
        {"code": "000002", "industry": "电子"},
        {"code": "000003", "industry": "电子"},
        {"code": "000004", "industry": fourth_industry},
    ]


def _row(
    code: str,
    five: Any,
    twenty: Any,
    sixty: Any,
    *,
    latest_date: str = DATE,
) -> dict[str, Any]:
    return {
        "code": code,
        "latest_date": latest_date,
        "return_5d": five,
        "return_20d": twenty,
        "return_60d": sixty,
    }


def _reader(rows: list[dict[str, Any]], *, page_size: int | None = None):
    calls: list[int] = []
    size = page_size or len(rows)

    def read(*, offset: int = 0, **_kwargs: Any) -> dict[str, Any]:
        calls.append(offset)
        page = rows[offset : offset + size]
        next_offset = offset + len(page) if offset + len(page) < len(rows) else None
        return {
            "status": "normal",
            "dataset_id": "ashare_daily_unadjusted",
            "provider_id": "local_bulk_dump",
            "adjustment": "UNADJUSTED",
            "latest_date": DATE,
            "as_of": DATE,
            "provenance": {"artifact_sha256": "fixture"},
            "rows": page,
            "next_offset": next_offset,
        }

    read.calls = calls  # type: ignore[attr-defined]
    return read


def test_complete_current_snapshot_uses_one_batch_and_percentage_points():
    snapshot_calls: list[int] = []

    def read_snapshot() -> list[dict[str, Any]]:
        snapshot_calls.append(1)
        return _snapshot()

    read_rdp = _reader(
        [
            _row("000001", 0.12, 0.10, 0.30),
            _row("000002", 0.04, 0.03, 0.20),
            _row("000003", 0.06, 0.08, 0.10),
            _row("000004", 0.02, 0.02, 0.05),
        ],
        page_size=2,
    )

    result = context.build_stock_relative_context(
        "000001", snapshot_reader=read_snapshot, rdp_reader=read_rdp
    )

    assert result["status"] == "normal"
    assert result["comparison_date"] == DATE
    assert result["industry_name"] == "电子"
    assert result["industry_membership_semantics"] == "CURRENT_MEMBERSHIP_SNAPSHOT"
    assert result["adjustment"] == "UNADJUSTED"
    assert result["return_semantics"] == "UNADJUSTED_RAW_PRICE_CHANGE"
    assert result["relative_unit"] == "PERCENTAGE_POINTS"
    assert result["provenance"]["membership_source"].endswith("industry=f100")
    assert result["periods"]["5D"] == {
        "stock_return_pct": pytest.approx(12.0),
        "industry_median_pct": pytest.approx(6.0),
        "vs_industry_pct_points": pytest.approx(6.0),
        "market_median_pct": pytest.approx(5.0),
        "vs_market_pct_points": pytest.approx(7.0),
        "industry_valid_count": 3,
        "industry_member_count": 3,
        "industry_coverage": pytest.approx(1.0),
        "market_valid_count": 4,
        "market_total_count": 4,
        "market_coverage": pytest.approx(1.0),
    }
    assert result["periods"]["20D"]["industry_median_pct"] == pytest.approx(8.0)
    assert result["periods"]["20D"]["vs_industry_pct_points"] == pytest.approx(2.0)
    assert result["periods"]["60D"]["market_median_pct"] == pytest.approx(15.0)
    assert snapshot_calls == [1]
    assert read_rdp.calls == [0, 2]  # type: ignore[attr-defined]


def test_exact_date_filter_has_independent_counts_and_excludes_nonfinite_values():
    read_rdp = _reader(
        [
            _row("000001", 0.12, 0.10, None),
            _row("000002", 0.08, float("inf"), 0.20),
            _row("000003", 0.99, 0.99, 0.99, latest_date="2026-09-10"),
            _row("000004", float("nan"), 0.02, 0.0),
            _row("000005", 0.02, 0.04, 0.04),
        ]
    )

    result = context.build_stock_relative_context(
        "000001",
        snapshot_reader=lambda: _snapshot(fourth_industry="电子")
        + [{"code": "000005", "industry": "银行"}],
        rdp_reader=read_rdp,
    )

    five = result["periods"]["5D"]
    twenty = result["periods"]["20D"]
    sixty = result["periods"]["60D"]
    assert result["status"] == "partial"
    assert five["market_total_count"] == twenty["market_total_count"] == sixty["market_total_count"] == 4
    assert five["market_valid_count"] == 3
    assert twenty["market_valid_count"] == 3
    assert sixty["market_valid_count"] == 3
    assert five["industry_valid_count"] == 2
    assert twenty["industry_valid_count"] == 2
    assert sixty["industry_valid_count"] == 2
    assert five["industry_member_count"] == twenty["industry_member_count"] == sixty["industry_member_count"] == 4
    assert five["industry_median_pct"] == pytest.approx(10.0)
    assert twenty["industry_median_pct"] == pytest.approx(6.0)
    assert sixty["industry_median_pct"] == pytest.approx(10.0)  # zero is a valid observed return
    assert five["stock_return_pct"] == pytest.approx(12.0)
    assert sixty["stock_return_pct"] is None
    assert any("stale" in warning for warning in result["warnings"])
    assert read_rdp.calls == [0]  # type: ignore[attr-defined]


def test_future_source_row_fails_closed_without_partial_benchmark():
    read_rdp = _reader(
        [
            _row("000001", 0.12, 0.10, 0.30),
            _row("000002", 0.08, 0.04, 0.20),
            _row("000005", 0.01, 0.01, 0.01, latest_date="2026-09-12"),
        ]
    )

    result = context.build_stock_relative_context(
        "000001", snapshot_reader=_snapshot, rdp_reader=read_rdp
    )

    assert result["status"] == "unavailable"
    assert result["comparison_date"] == DATE
    assert all(period["market_median_pct"] is None for period in result["periods"].values())
    assert any("fail closed" in warning for warning in result["warnings"])


def test_unknown_industry_and_snapshot_failure_do_not_break_market_comparison():
    rows = [_row("000001", 0.12, 0.10, 0.30), _row("000004", 0.02, 0.04, 0.05)]
    unknown = context.build_stock_relative_context(
        "000001", snapshot_reader=lambda: _snapshot(unknown=True), rdp_reader=_reader(rows)
    )
    assert unknown["industry_name"] == "UNKNOWN"
    assert unknown["industry_status"] == "unknown"
    assert unknown["periods"]["5D"]["industry_median_pct"] is None
    assert unknown["periods"]["5D"]["market_median_pct"] == pytest.approx(7.0)

    failed = context.build_stock_relative_context(
        "000001",
        snapshot_reader=lambda: (_ for _ in ()).throw(RuntimeError("fixture")),
        rdp_reader=_reader(rows),
    )
    assert failed["industry_name"] is None
    assert failed["industry_status"] == "unavailable"
    assert failed["periods"]["5D"]["industry_median_pct"] is None
    assert failed["periods"]["5D"]["market_median_pct"] == pytest.approx(7.0)
    assert failed["status"] == "partial"


def test_rdp_unavailable_does_not_fabricate_values():
    def unavailable(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "unavailable", "rows": [], "next_offset": None}

    result = context.build_stock_relative_context(
        "000001", snapshot_reader=_snapshot, rdp_reader=unavailable
    )

    assert result["status"] == "unavailable"
    assert result["comparison_date"] is None
    assert all(period["stock_return_pct"] is None for period in result["periods"].values())
    assert all(period["market_coverage"] is None for period in result["periods"].values())


def test_http_route_validates_code_and_keeps_read_only_envelope(monkeypatch):
    payload = {"schema_version": context.SCHEMA_VERSION, "status": "unavailable"}
    monkeypatch.setattr(router.service, "build_stock_relative_context", lambda code: payload)
    app = FastAPI()
    app.include_router(router.router)
    client = TestClient(app)

    assert client.get("/api/stock-relative-context?code=000001").json() == payload
    assert client.get("/api/stock-relative-context?code=ABC").status_code == 422
