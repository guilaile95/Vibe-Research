"""Decision-cockpit E2E uvicorn entry: real app + offline stubs for market/K-line.

Not production. Isolated VR_DATA_DIR / VIBE_RESEARCH_REVIEW_DB.
Seeds one daily_review_snapshots row so generate can bind an immutable snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

import app as app_module
import market
import astock
import portfolio
import position_reality_service
import review_history
import review_store
import watchlist_store

app = app_module.app

BEIJING = timezone(timedelta(hours=8))
TRADE_DATE = datetime.now(BEIJING).strftime("%Y-%m-%d")


def _seed_review_snapshot() -> None:
    """Seed最新不可变复盘：仅北京今日（前端 today() 也用 Asia/Shanghai）。

    生成接口只允许最新已保存复盘 trade_date，故只种一条最新日。
    """
    db = review_history.resolve_review_db_path()
    now_bj = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    review = {
        "schema_version": "daily-review.v1",
        "trade_date": TRADE_DATE,
        "generated_at": now_bj,
        "data_cutoff": now_bj,
        "status": "normal",
        "sections": {"summary": "e2e fixture review", "trade_date": TRADE_DATE},
    }
    review_store.save_daily_review_snapshot(review, db)


def _seed_watchlist() -> None:
    # Ensure candidate pool non-empty even without holdings/sector online data
    try:
        watchlist_store.save_watchlist(["600519", "000001", "300750"])
    except Exception:
        pass


def _seed_canonical_holding_with_stale_legacy_archive() -> None:
    position_reality_service.bootstrap_commit(
        {
            "ledger_start_at": "2026-08-01",
            "opening_cash": 100_000,
            "note": "cockpit holding-authority e2e",
            "positions": [
                {"code": "600519", "shares": 200, "cost_basis": 8.0},
            ],
        }
    )
    legacy_path = Path(portfolio.PF_FILE)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "holdings": [
                    {"code": "600519", "name": "legacy", "shares": 999, "cost": 1.0},
                    {"code": "601318", "name": "legacy-only", "shares": 77, "cost": 1.0},
                ],
                "last_refresh": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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


def _fake_financials(code: str, **_kwargs):
    latest = {
        "period": "2026-06-30", "period_end": "2026-06-30", "report_date": None,
        "revenue": "1000亿", "revenue_yoy": "8%",
        "net_profit": "200亿", "net_profit_yoy": "10%",
        "deduct_net_profit": "190亿", "deduct_net_profit_yoy": "9%",
        "eps": "1.50", "bvps": "15.0", "roe": "12%",
        "gross_margin": "40%", "net_margin": "20%", "op_cf_ps": "2.1",
        "current_ratio": "1.8", "quick_ratio": "1.4",
        "debt_to_equity_ratio": "0.5", "debt_ratio": "33%",
        "revenue_amount": 100_000_000_000, "net_profit_amount": 20_000_000_000,
        "parent_holder_net_profit_amount": 19_000_000_000,
        "operating_cash_flow": 30_000_000_000, "capital_expenditure": 4_000_000_000,
        "free_cash_flow": 26_000_000_000, "assets_total": 200_000_000_000,
        "cash": 50_000_000_000, "accounts_receivable": 10_000_000_000,
        "total_debt": 80_000_000_000, "holder_equity_total": 120_000_000_000,
        "cash_conversion_ratio": 1.5, "free_cash_flow_margin": 0.26,
        "accrual_ratio": -0.05, "receivables_pressure": 0.1, "net_cash_ratio": -0.15,
    }
    return {
        **latest,
        "history": [latest, {**latest, "period": "2026-03-31", "period_end": "2026-03-31"}],
        "data_quality": {
            "status": "normal", "source": "tonghuashun_via_akshare",
            "fetch_mode": "snapshot", "report_basis": "cumulative_report_period",
            "point_in_time_supported": False, "publication_date_known": False,
            "missing_fields": [], "warnings": [],
        },
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
_seed_canonical_holding_with_stale_legacy_archive()


@app.get("/api/decision-cockpit/e2e-status")
def e2e_status():
    """隔离验收计数（非生产）。"""
    import decision_cockpit_store as dcs

    db = review_history.resolve_review_db_path()
    return {
        "data": {
            "trade_date": TRADE_DATE,
            "plan_count": dcs.count_plans(db),
            "signal_count": dcs.count_signals(db),
            "review_db": str(db),
        }
    }
