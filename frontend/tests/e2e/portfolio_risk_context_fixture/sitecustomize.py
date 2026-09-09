"""Synthetic adapter-boundary facts for the portfolio risk browser vertical."""

import astock
import os


_PRICES = {
    "600001": 100.0,
    "600002": 50.0,
    "600003": 20.0,
    "600004": 10.0,
}
_NAMES = {
    "600001": "Alpha电子",
    "600002": "Beta医药",
    "600003": "Gamma未分类",
    "600004": "Delta银行",
}
_MODE_FILE = os.environ.get("PORTFOLIO_RISK_CONTEXT_FIXTURE_MODE_FILE")


def _mode():
    if not _MODE_FILE:
        return "normal"
    try:
        with open(_MODE_FILE, "r", encoding="utf-8") as handle:
            return handle.read().strip() or "normal"
    except OSError:
        return "normal"


def _quote(codes):
    mode = _mode()
    missing = "600004" if mode == "partial" else None
    return {
        code: {"name": _NAMES.get(code, code), "price": _PRICES.get(code)}
        for code in codes
        if code in _PRICES and code != missing
    }


def _snapshot():
    if _mode() == "industry-failure":
        raise RuntimeError("synthetic Eastmoney current-industry failure")
    return [
        {"code": "600001", "name": _NAMES["600001"], "industry": "电子"},
        {"code": "600002", "name": _NAMES["600002"], "industry": "医药"},
        {"code": "600003", "name": _NAMES["600003"], "industry": None},
        {"code": "600004", "name": _NAMES["600004"], "industry": "银行"},
    ]


def _kline(code, category=4, offset=5):  # noqa: ARG001
    if code not in _PRICES:
        return []
    return [{"datetime": "2026-09-08 15:00:00", "close": _PRICES[code]}]


astock.tencent_quote = _quote
astock.a_share_snapshot = _snapshot
astock.kline = _kline
