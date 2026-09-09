"""E2E-only uvicorn entry for the Dragon-Tiger discovery vertical.

The real FastAPI application and production route are served unchanged.  Only
the existing Eastmoney request function is replaced with a small, deterministic
fixture so the browser test cannot touch a user's account or depend on network
availability.  This module is never imported by production code.
"""

from __future__ import annotations

import math
from typing import Any

import app as app_module
import astock


app = app_module.app


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def _row(*, trade_date: str, code: str, reason: str, net: float | None, turnover: float | None, trade_id: str) -> dict[str, Any]:
    return {
        "TRADE_DATE": trade_date,
        "SECURITY_CODE": code,
        "SECURITY_NAME_ABBR": "E2E 龙虎榜样本",
        "EXPLANATION": reason,
        "BILLBOARD_NET_AMT": net,
        "TURNOVERRATE": turnover,
        "TRADE_ID": trade_id,
    }


def _multi_page_rows(trade_date: str, prefix: str) -> list[dict[str, Any]]:
    rows = [
        _row(
            trade_date=trade_date,
            code="000001",
            reason="收盘价格涨幅偏离值达到7%",
            net=123456.0,
            turnover=2.5,
            trade_id=f"{prefix}-a",
        ),
        _row(
            trade_date=trade_date,
            code="000001",
            reason="日价格振幅达到15%",
            net=0.0,
            turnover=None,
            trade_id=f"{prefix}-b",
        ),
        _row(
            trade_date=trade_date,
            code="600519",
            reason="换手率达到20%",
            net=-50000.0,
            turnover=20.0,
            trade_id=f"{prefix}-c",
        ),
    ]
    rows.extend(
        _row(
            trade_date=trade_date,
            code=f"{100000 + index:06d}",
            reason=f"测试上榜原因-{index}",
            net=float(index * 1000),
            turnover=float(index) / 10,
            trade_id=f"{prefix}-{index:02d}",
        )
        for index in range(3, 66)
    )
    return rows


_NORMAL_ROWS = _multi_page_rows("2026-09-09", "e2e-0909")
_OVERLAP_SOURCE_ROWS = _multi_page_rows("2026-09-08", "e2e-0908")
_OVERLAP_ROWS = _OVERLAP_SOURCE_ROWS[:50] + [_OVERLAP_SOURCE_ROWS[0]] + _OVERLAP_SOURCE_ROWS[51:]

_ROWS_BY_DATE = {
    "2026-09-09": _NORMAL_ROWS,
    "2026-09-08": _OVERLAP_ROWS,
}


def _payload(rows: list[dict[str, Any]], page_size: int, page_number: int) -> dict[str, Any]:
    count = len(rows)
    pages = math.ceil(count / page_size) if count else 0
    start = (page_number - 1) * page_size
    return {
        "code": 0,
        "success": True,
        "message": "ok",
        "result": {
            "count": count,
            "pages": pages,
            "data": rows[start : start + page_size],
        },
    }


def _fixture_em_get(_url: str, *, params: dict[str, Any] | None = None, **_kwargs: Any) -> _Response:
    params = params or {}
    if params.get("reportName") != "RPT_DAILYBILLBOARD_DETAILSNEW":
        return _Response({"code": 9501, "success": False, "result": None, "message": "unsupported fixture report"})

    filter_str = str(params.get("filter") or "")
    page_size = int(params.get("pageSize") or 50)
    page_number = int(params.get("pageNumber") or 1)
    if not filter_str:
        rows = _ROWS_BY_DATE["2026-09-09"]
    else:
        marker = "(TRADE_DATE='"
        if not filter_str.startswith(marker) or not filter_str.endswith("')"):
            return _Response({"code": 9501, "success": False, "result": None, "message": "unsupported fixture filter"})
        trade_date = filter_str[len(marker) : -2]
        if trade_date == "2026-09-06":
            return _Response({"code": 9201, "success": False, "result": None, "message": "no records"})
        rows = _ROWS_BY_DATE.get(trade_date, [])
    return _Response(_payload(rows, page_size, page_number))


# Keep the production route, cache, and source-to-sink code in use.
astock.em_get = _fixture_em_get  # type: ignore[assignment]
