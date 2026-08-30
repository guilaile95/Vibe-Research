"""Offline harness: real Portfolio Advice pipeline with deterministic externals."""
from __future__ import annotations

import json

import astock
import daily_review
import portfolio_advice_service


def _quotes(codes):
    rows = {
        "600519": {"name": "贵州茅台", "price": 12.0},
        "000001": {"name": "平安银行", "price": 10.0},
    }
    return {code: rows[code] for code in codes if code in rows}


def _kline(code, category=4, offset=5):  # noqa: ARG001
    close = 12.0 if code == "600519" else 10.0
    return [{"datetime": "2026-08-28 15:00:00", "close": close}]


def _review():
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-08-28 15:30:00",
        "trade_date": "2026-08-28",
        "data_cutoff": None,
        "status": "normal",
        "warnings": [],
        "data_health": {
            "components": {
                "indices": "normal",
                "breadth": "normal",
                "emotion": "normal",
                "turnover": "normal",
                "industry_boards": "normal",
                "concept_boards": "normal",
                "region_boards": "normal",
            }
        },
        "market_environment": {
            "indices": {"status": "normal", "data": []},
            "global_indices": {"status": "normal", "data": []},
            "breadth": {
                "status": "normal",
                "source": "test",
                "warnings": [],
                "data": {
                    "stock_count": 5000,
                    "valid_count": 5000,
                    "up_count": 3000,
                    "down_count": 1900,
                    "flat_count": 100,
                    "up_ratio": 0.6,
                    "up_3pct_count": 500,
                    "down_3pct_count": 200,
                    "total_amount": 1.2e12,
                    "amount_valid_count": 5000,
                },
            },
        },
        "short_term_emotion": {
            "status": "normal",
            "source": "test",
            "warnings": [],
            "data": {
                "date": "2026-08-28",
                "zt_count": 80,
                "dt_count": 10,
                "zb_count": 20,
                "max_boards": 5,
                "lianban_count": 15,
                "seal_rate": 0.8,
                "break_rate": 0.2,
                "promotion_rate": 0.3,
                "yzt_count": 50,
                "ladder": [],
                "lianban_stocks": [],
            },
        },
        "sector_rotation": {
            "industry": {"status": "normal", "data": {"top": [], "bottom": []}},
            "concept": {"status": "normal", "data": {"top": [], "bottom": []}},
            "region": {"status": "normal", "data": {"top": [], "bottom": []}},
            "highlights": {},
        },
        "capital_activity": {
            "total_amount": 1.2e12,
            "amount_valid_count": 5000,
            "amount_top": [],
            "high_turnover": [],
        },
    }


def _model(_cfg, _messages):
    holding = {
        "confidence": "medium",
        "trigger_conditions": ["保持确定性条件"],
        "price_conditions": [],
        "execution_plan": ["仅按系统约束执行"],
        "risk_conditions": ["账户事实不完整"],
        "invalidation_conditions": ["条件失效"],
        "data_limitations": [],
    }
    return json.dumps(
        {
            "schema_version": "portfolio-advice-v0.1",
            "generated_at": "2026-08-28T15:30:00+08:00",
            "market_status": "normal",
            "account_action": {
                "action": "reduce_risk",
                "reason": "验证账户 authority gate",
                "confidence": "medium",
            },
            "holdings": [
                {
                    **holding,
                    "code": "600519",
                    "action": "add",
                    "execution_size_pct_of_holding": 10,
                },
                {
                    **holding,
                    "code": "000001",
                    "action": "reduce",
                    "execution_size_pct_of_holding": 20,
                },
            ],
            "warnings": [],
            "data_limitations": [],
        },
        ensure_ascii=False,
    )


astock.tencent_quote = _quotes
astock.kline = _kline
daily_review.generate_daily_review = _review
portfolio_advice_service._default_model_runner = _model

from app import app  # noqa: E402,F401
