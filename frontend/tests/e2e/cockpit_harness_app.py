"""Decision-cockpit E2E uvicorn entry: real app + offline stubs for market/K-line.

Not production. Isolated VR_DATA_DIR / VIBE_RESEARCH_REVIEW_DB.
Seeds one daily_review_snapshots row so generate can bind an immutable snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import app as app_module
import market
import astock
import review_history
import review_store
import watchlist_store

app = app_module.app

BEIJING = timezone(timedelta(hours=8))
TRADE_DATE = datetime.now(BEIJING).strftime("%Y-%m-%d")


def _seed_review_snapshot() -> None:
    """Seed review for Beijing today and UTC today (frontend today() is UTC ISO date)."""
    db = review_history.resolve_review_db_path()
    now_bj = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    dates = {TRADE_DATE, datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    for td in dates:
        review = {
            "schema_version": "daily-review.v1",
            "trade_date": td,
            "generated_at": now_bj,
            "data_cutoff": now_bj,
            "status": "normal",
            "sections": {"summary": "e2e fixture review", "trade_date": td},
        }
        review_store.save_daily_review_snapshot(review, db)


def _seed_watchlist() -> None:
    # Ensure candidate pool non-empty even without holdings/sector online data
    try:
        watchlist_store.save_watchlist(["600519", "000001", "300750"])
    except Exception:
        pass


def _fake_breadth():
    return {
        "status": "normal",
        "source": "e2e",
        "trade_date": TRADE_DATE,
        "data_time": None,
        "fetched_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "is_stale": False,
        "warnings": [],
        "data": {
            "stock_count": 5000,
            "valid_count": 5000,
            "up_count": 2500,
            "down_count": 2000,
            "flat_count": 500,
            "up_ratio": 0.5,
            "amount_top": [{"code": "000001", "name": "平安银行", "amount": 1e9}],
            "high_turnover": [{"code": "300750", "name": "宁德时代", "turnover_pct": 20.0}],
        },
    }


def _fake_emotion():
    return {
        "date": TRADE_DATE,
        "zt_count": 40,
        "lianban_count": 5,
        "lianban_stocks": [
            {"code": "000002", "name": "万科A", "boards": 2, "amount": 1e8},
        ],
        "seal_rate": 0.7,
    }


def _fake_turnover_top():
    return {
        "stocks": [{"code": "600519", "name": "贵州茅台", "amount": 2e9}],
        "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
    }


def _fake_board_ranking(board_type: str = "industry", top_n: int = 20):
    return {
        "status": "normal",
        "data": [{"code": "BK0001", "name": "电子", "rank": 1}],
    }


def _fake_kline(code: str, category: int = 4, offset: int = 80):
    bars = []
    p = 100.0
    for i in range(max(offset, 80)):
        p *= 1.003
        bars.append({
            "open": p * 0.99,
            "close": p,
            "high": p * 1.01,
            "low": p * 0.98,
            "volume": 1_000_000 + i,
        })
    return bars


def _fake_financials(code: str):
    return {
        "period": "2025Q4",
        "revenue_yoy": 12.0,
        "net_profit_yoy": 8.0,
        "roe": 16.0,
        "gross_margin": 40.0,
        "op_cf_ps": 1.5,
    }


def _fake_valuation_percentile(code: str, period: str = "近五年"):
    return {
        "period": "近5年",
        "metrics": {
            "pe_ttm": {"current": 15, "percentile": 18, "min": 10, "max": 40, "p20": 12, "p50": 20, "p80": 30, "n": 100},
            "pb": {"current": 2, "percentile": 40, "min": 1, "max": 5, "p20": 1.5, "p50": 2, "p80": 3, "n": 100},
        },
    }


def _fake_full_valuation(code: str):
    return {
        "name": code, "code": code, "price": 100.0,
        "mcap_yi": 100.0, "pe_ttm": 15.0, "pb": 2.0,
        "eps_26e": 5.0, "eps_27e": 6.0, "pe_26e": 20.0,
        "cagr_pct": 20.0, "peg": 1.0, "digest_years": 5.0, "analyst_count": 8,
    }


def _fake_tencent_quote(codes: list):
    return {c: {"name": c, "price": 10.0, "pe_ttm": 15, "pb": 2, "mcap_yi": 50} for c in codes}


# Apply stubs
market.get_market_breadth = _fake_breadth  # type: ignore[assignment]
market.get_short_term_emotion = _fake_emotion  # type: ignore[assignment]
market.get_turnover_top = _fake_turnover_top  # type: ignore[assignment]
market.get_board_ranking = _fake_board_ranking  # type: ignore[assignment]
astock.kline = _fake_kline  # type: ignore[assignment]
astock.financials = _fake_financials  # type: ignore[assignment]
astock.valuation_percentile = _fake_valuation_percentile  # type: ignore[assignment]
astock.full_valuation = _fake_full_valuation  # type: ignore[assignment]
astock.tencent_quote = _fake_tencent_quote  # type: ignore[assignment]

_seed_review_snapshot()
_seed_watchlist()
