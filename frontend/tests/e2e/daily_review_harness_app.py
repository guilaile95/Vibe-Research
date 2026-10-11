"""E2E harness: daily review refresh + portfolio advice stubs (offline).

Isolated VR_DATA_DIR / VIBE_RESEARCH_REVIEW_DB. Not production.
"""
from __future__ import annotations

import copy
import os
import socket

from datetime import datetime, timezone, timedelta
from typing import Any

# Pool acceptance is strictly offline. Permit only local harness connections.
_POOL_MODE = os.environ.get("VR_E2E_POOL_PROVENANCE") == "1"
if _POOL_MODE:
    _connect = socket.socket.connect
    _connect_ex = socket.socket.connect_ex
    _getaddrinfo = socket.getaddrinfo
    def _local_connect(self, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("External network forbidden in synthetic pool harness")
        return _connect(self, address)
    def _local_connect_ex(self, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("External network forbidden in synthetic pool harness")
        return _connect_ex(self, address)
    def _local_dns(host, *args, **kwargs):
        if host not in {"127.0.0.1", "::1", "localhost", None}:
            raise AssertionError("External DNS forbidden in synthetic pool harness")
        return _getaddrinfo(host, *args, **kwargs)
    socket.socket.connect = _local_connect
    socket.socket.connect_ex = _local_connect_ex
    socket.getaddrinfo = _local_dns

import app as app_module
import daily_review
import daily_review_cache
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
_pool_scenario = {"name": "qualified"}
_POOL_AS_OF = "2026-10-10T04:10:00Z"
_real_build_daily_review = daily_review._build_daily_review


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
    if _POOL_MODE:
        _gen_counter["n"] += 1
        return _real_build_daily_review()
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


if _POOL_MODE:
    class PoolClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime.fromisoformat(_POOL_AS_OF.replace("Z", "+00:00"))
            return instant.astimezone(tz or BEIJING)

    daily_review.datetime = PoolClock
    _row = {"c": "600001", "n": "合成样本", "lbc": 2, "p": 10000,
            "zdp": 10, "amount": 1000, "ltsz": 2000, "hybk": "合成行业"}

    class PoolResponse:
        status_code = 200
        def __init__(self, payload):
            self.payload = payload
        def json(self):
            return copy.deepcopy(self.payload)

    def _pool_get(url, params, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint not in {"getTopicZTPool", "getTopicDTPool", "getTopicZBPool", "getYesterdayZTPool"}:
            raise AssertionError("Unexpected provider in synthetic pool harness")
        if params["date"] != "20261009":
            raise AssertionError("Unexpected pool query session")
        if _pool_scenario["name"] == "secondary_failure" and endpoint != "getTopicZTPool":
            return PoolResponse({"rc": 102, "data": None})
        rows = [] if _pool_scenario["name"] == "empty_zt" and endpoint == "getTopicZTPool" else [_row]
        return PoolResponse({"rc": 0, "data": {"qdate": 20261009, "pool": rows}})

    def _envelope(data):
        return {"status": "normal", "source": "synthetic_offline_fixture",
                "trade_date": None, "data_time": None, "fetched_at": None,
                "is_stale": False, "warnings": [], "data": data}

    astock.em_get = _pool_get
    astock.index_quote = lambda: [{"code": "000001", "name": "合成指数", "price": 3000, "change_pct": 0}]
    market.get_short_term_emotion = lambda: market._emotion(_POOL_AS_OF)
    market.get_global_indices = lambda: [{"name": "合成全球指数", "price": 100, "change_pct": 0}]
    market.get_market_breadth = lambda: _envelope({
        "stock_count": 1, "valid_count": 1, "up_count": 1, "down_count": 0,
        "flat_count": 0, "up_ratio": 1, "total_amount": 1000, "amount_valid_count": 1,
        "amount_top": [], "high_turnover": [],
    })
    market.get_turnover_top = lambda: {"stocks": [{"code": "600001", "name": "合成样本", "amount": 1000}]}
    market.get_board_ranking = lambda board_type="industry", top_n=10: _envelope({
        "type": board_type, "top": [], "bottom": [], "total": 0,
    })
    market.get_market_cloud = lambda *args, **kwargs: {
        "status": "unavailable", "data": None, "warnings": ["合成情绪验收未提供云图"],
    }

    @app.post("/api/e2e/daily-review/pool-scenario/{scenario}")
    def e2e_pool_scenario(scenario: str):
        from fastapi import HTTPException
        if scenario not in {"qualified", "secondary_failure", "empty_zt"}:
            raise HTTPException(400, "Unknown synthetic scenario")
        _pool_scenario["name"] = scenario
        daily_review._clear_review_cache()
        daily_review_cache.clear_latest_review_file()  # isolated temporary latest only
        daily_review._clear_refresh_failure()
        market._CACHE.clear()
        return {"data": {"scenario": scenario, "as_of": _POOL_AS_OF}}
