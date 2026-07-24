"""E2E harness: daily review refresh + portfolio advice stubs (offline).

Isolated VR_DATA_DIR / VIBE_RESEARCH_REVIEW_DB. Not production.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

import app as app_module
import daily_review
import portfolio
import portfolio_advice_service as advice_svc
import ai_result_service
import market
import astock

app = app_module.app

BEIJING = timezone(timedelta(hours=8))
_gen_counter = {"n": 0}
# When True, next _build_daily_review raises (for failure-retention E2E).
_fail_next_build = {"on": False}


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _trade_date() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


def _packet() -> dict:
    _gen_counter["n"] += 1
    td = _trade_date()
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": _now(),
        "trade_date": td,
        "data_cutoff": _now(),
        "status": "normal",
        "warnings": [f"e2e-build-{_gen_counter['n']}"],
        "data_health": {
            "components": {
                "indices": "normal",
                "global_indices": "normal",
                "breadth": "normal",
                "emotion": "normal",
                "turnover": "normal",
                "industry_boards": "normal",
                "concept_boards": "normal",
                "region_boards": "normal",
            }
        },
        "market_environment": {
            "indices": {"status": "normal", "data": [{"code": "000001", "name": "上证", "price": 3000}]},
            "breadth": {"status": "normal", "data": {"up_count": 100}},
            "global_indices": {"status": "normal", "data": []},
        },
        "sector_rotation": {
            "industry": {"status": "normal", "list": []},
            "concept": {"status": "normal", "list": []},
            "region": {"status": "normal", "list": []},
            "highlights": {},
        },
        "short_term_emotion": {"status": "normal", "data": {"zt_count": 40, "date": td}},
        "capital_activity": {
            "total_amount": 1e12,
            "amount_top": [],
            "high_turnover": [],
            "turnover_top": [],
        },
    }


def _build_packet_or_fail() -> dict:
    if _fail_next_build["on"]:
        _fail_next_build["on"] = False
        raise RuntimeError("e2e forced refresh failure")
    return _packet()


# Bypass real aggregation; still exercise cache + true single-flight refresh path
daily_review._build_daily_review = _build_packet_or_fail  # type: ignore[assignment]


@app.post("/api/e2e/daily-review/arm-fail-next-build")
def e2e_arm_fail_next_build():
    """Test-only: next full-package build raises (does not clear success cache)."""
    _fail_next_build["on"] = True
    return {"data": {"armed": True, "build_count": _gen_counter["n"]}}


@app.get("/api/e2e/daily-review/build-count")
def e2e_build_count():
    return {"data": {"n": _gen_counter["n"]}}


def _seed_portfolio() -> None:
    try:
        # write minimal portfolio via public API store path
        import portfolio as pf

        # force holdings with valid prices
        data = {
            "holdings": [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "shares": 100,
                    "cost": 1500.0,
                    "price": 1600.0,
                }
            ],
            "closed": [],
        }
        # use internal write if available
        if hasattr(pf, "save_portfolio"):
            pf.save_portfolio(data)
        elif hasattr(pf, "_write_portfolio"):
            pf._write_portfolio(data)
        else:
            # fall back: add_holding path
            try:
                pf.add_holding("600519", 100, 1500.0)
            except Exception:
                pass
    except Exception:
        pass


def _fake_advice(cfg: Any, user_request: str | None = None, **_kw) -> dict:
    td = _trade_date()
    payload = {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": _now(),
        "trade_date": td,
        "market_status": "normal",
        "portfolio_summary": {
            "holding_count": 1,
            "market_value": 160000.0,
            "cost": 150000.0,
            "pnl": 10000.0,
            "pnl_pct": 6.67,
        },
        "account_action": {"action": "hold", "reason": "e2e", "confidence": "medium"},
        "holdings": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "shares": 100,
                "cost_price": 1500.0,
                "current_price": 1600.0,
                "market_value": 160000.0,
                "pnl_amount": 10000.0,
                "pnl_pct": 6.67,
                "holding_weight_pct": 100.0,
                "action": "hold",
                "execution_size_pct_of_holding": None,
                "execution_quantity": None,
                "trigger_conditions": [],
                "price_conditions": [],
                "execution_plan": [],
                "risk_conditions": [],
                "invalidation_conditions": [],
                "confidence": "medium",
                "data_limitations": [],
            }
        ],
        "warnings": [],
        "data_limitations": [],
    }
    # try real save path with stubbed review/portfolio
    try:
        portfolio_data = {
            "holdings": [
                {"code": "600519", "name": "贵州茅台", "shares": 100, "cost": 1500.0, "price": 1600.0}
            ]
        }
        review = _packet()
        fp = ai_result_service.compute_portfolio_fingerprint(portfolio_data["holdings"])
        ai_result_service.save_portfolio_advice(
            portfolio_data, review, payload, cfg or {}, input_fingerprint=fp
        )
    except Exception:
        pass
    return payload


advice_svc.generate_portfolio_advice = _fake_advice  # type: ignore[assignment]

# market stubs for any residual live calls
market.get_market_breadth = lambda: {"status": "normal", "data": {}}  # type: ignore
market.get_short_term_emotion = lambda: {"date": _trade_date(), "zt_count": 1}  # type: ignore
astock.tencent_quote = lambda codes: {c: {"price": 10.0, "name": c} for c in codes}  # type: ignore

_seed_portfolio()
