"""Storage-level tests: invalid ratios and missing identity never pollute SQLite."""

from __future__ import annotations

import json

import decision_evidence_service as evidence_svc
import decision_trace_store as trace_store
import signal_ledger_service as ledger_svc
import signal_ledger_store as ledger_store


def _base_holding(**overrides):
    h = {
        "code": "600519",
        "name": "贵州茅台",
        "action": "reduce",
        "execution_size_pct_of_holding": 30,
        "execution_quantity": 100,
        "shares": 300,
        "current_price": 1800.0,
        "holding_weight_pct": 100.0,
        "sellable_quantity_advisory": 100,
        "execution_plan": ["分批减仓"],
        "trigger_conditions": ["估值偏高"],
        "price_conditions": [],
        "risk_conditions": [],
        "invalidation_conditions": [],
        "data_limitations": [],
        "confidence": "medium",
    }
    h.update(overrides)
    return h


def _advice(holding=None, **top):
    data = {
        "schema_version": "portfolio-advice-v0.1",
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00+00:00",
        "market_status": "normal",
        "portfolio_summary": {"holding_count": 1},
        "account_action": {"action": "hold", "reason": "x", "confidence": "low"},
        "account_funding": {
            "configured": True,
            "total_assets": 100000.0,
            "available_cash": 20000.0,
            "quote_coverage": {"valid_holdings": 1, "total_holdings": 1, "complete": True},
        },
        "holdings": [holding or _base_holding()],
        "warnings": [],
        "data_limitations": [],
    }
    data.update(top)
    return data


def _count(db_path, table: str) -> int:
    conn = trace_store._get_read_connection(db_path)
    try:
        # table may not exist yet
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if row is None:
            return 0
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"])
    finally:
        conn.close()


def _all_payload_json_text(db_path) -> str:
    conn = trace_store._get_read_connection(db_path)
    try:
        chunks: list[str] = []
        for table, col in (
            ("signal_entries", "payload_json"),
            ("decision_outcomes", "reason"),
            ("evidence_items", "value_json"),
            ("explanation_items", "explanation_text"),
        ):
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists is None:
                continue
            for row in conn.execute(f"SELECT {col} AS v FROM {table}").fetchall():
                chunks.append(str(row["v"] or ""))
        return "\n".join(chunks)
    finally:
        conn.close()


INVALID_SIZES = [
    True,
    False,
    float("nan"),
    float("inf"),
    float("-inf"),
    -10,
    101,
    {"a": 1},
    [30],
]

VALID_SIZES = [0, 10, 30, 100]


def test_invalid_ratios_not_persisted_in_signal_or_evidence(tmp_path):
    for raw in INVALID_SIZES:
        db_path = tmp_path / f"bad_{id(raw)}.sqlite3"
        advice = _advice(_base_holding(execution_size_pct_of_holding=raw))

        sres = ledger_svc.archive_signal_ledger(advice, db_path=db_path)
        eres = evidence_svc.archive_decision_evidence(advice, db_path=db_path)
        assert sres["status"] == "success", raw
        assert eres["status"] == "archived", raw

        timeline = ledger_store.get_run_signal_ledger(sres["decision_run_id"], db_path=db_path)
        outcome = timeline["decision_outcomes"][0]
        assert outcome["target_ratio"] is None, raw

        policy = next(
            e for e in timeline["signal_entries"] if e["stage"] == "policy_audit"
        )
        execution = next(
            e for e in timeline["signal_entries"] if e["stage"] == "execution"
        )
        assert policy["payload_json"]["execution_size_pct_of_holding"] is None, raw
        assert execution["payload_json"]["execution_size_pct_of_holding"] is None, raw
        assert execution["payload_json"].get("execution_size_invalid") is True, raw

        bundle = trace_store.get_decision_run(eres["decision_run_id"], db_path=db_path)
        stock_ev = next(ev for ev in bundle["evidence_items"] if ev["scope"] == "stock")
        assert stock_ev["value_json"]["execution_size_pct_of_holding"] is None, raw
        assert stock_ev["value_json"].get("execution_size_invalid") is True, raw

        raw_json = _all_payload_json_text(db_path)
        assert "NaN" not in raw_json, raw
        assert "Infinity" not in raw_json, raw


def test_valid_ratios_persisted_consistently(tmp_path):
    for size in VALID_SIZES:
        db_path = tmp_path / f"ok_{size}.sqlite3"
        advice = _advice(_base_holding(execution_size_pct_of_holding=size))

        sres = ledger_svc.archive_signal_ledger(advice, db_path=db_path)
        eres = evidence_svc.archive_decision_evidence(advice, db_path=db_path)
        assert sres["status"] == "success"
        assert eres["status"] == "archived"

        timeline = ledger_store.get_run_signal_ledger(sres["decision_run_id"], db_path=db_path)
        outcome = timeline["decision_outcomes"][0]
        assert abs(float(outcome["target_ratio"]) - float(size) / 100.0) < 1e-9

        policy = next(
            e for e in timeline["signal_entries"] if e["stage"] == "policy_audit"
        )
        execution = next(
            e for e in timeline["signal_entries"] if e["stage"] == "execution"
        )
        assert policy["payload_json"]["execution_size_pct_of_holding"] == float(size)
        assert execution["payload_json"]["execution_size_pct_of_holding"] == float(size)

        bundle = trace_store.get_decision_run(eres["decision_run_id"], db_path=db_path)
        stock_ev = next(ev for ev in bundle["evidence_items"] if ev["scope"] == "stock")
        assert stock_ev["value_json"]["execution_size_pct_of_holding"] == float(size)


def test_missing_identity_fail_closed_signal_ledger(tmp_path):
    cases = [
        {"trade_date": None, "generated_at": "2026-07-29T10:00:00+00:00"},
        {"trade_date": "2026-07-29", "generated_at": None},
        {"trade_date": None, "generated_at": None},
        {"trade_date": "", "generated_at": "2026-07-29T10:00:00+00:00"},
        {"trade_date": "2026-07-29", "generated_at": ""},
        {"trade_date": "  ", "generated_at": "  "},
    ]
    for i, top in enumerate(cases):
        db_path = tmp_path / f"id_sig_{i}.sqlite3"
        advice = _advice(**top)
        # force missing keys if None
        if top.get("trade_date") is None:
            advice.pop("trade_date", None)
        if top.get("generated_at") is None:
            advice.pop("generated_at", None)
        res = ledger_svc.archive_signal_ledger(advice, db_path=db_path)
        assert res["status"] == "failed"
        assert res["reason"] == "missing_decision_identity"
        assert _count(db_path, "decision_runs") == 0
        assert _count(db_path, "signal_entries") == 0
        assert _count(db_path, "decision_outcomes") == 0


def test_missing_identity_fail_closed_decision_evidence(tmp_path):
    cases = [
        {"trade_date": None, "generated_at": "2026-07-29T10:00:00+00:00"},
        {"trade_date": "2026-07-29", "generated_at": None},
        {"trade_date": None, "generated_at": None},
        {"trade_date": "", "generated_at": "2026-07-29T10:00:00+00:00"},
        {"trade_date": "2026-07-29", "generated_at": ""},
    ]
    for i, top in enumerate(cases):
        db_path = tmp_path / f"id_ev_{i}.sqlite3"
        advice = _advice(**top)
        if top.get("trade_date") is None:
            advice.pop("trade_date", None)
        if top.get("generated_at") is None:
            advice.pop("generated_at", None)
        res = evidence_svc.archive_decision_evidence(advice, db_path=db_path)
        assert res["status"] == "failed"
        assert res["reason"] == "missing_decision_identity"
        assert _count(db_path, "decision_runs") == 0
        assert _count(db_path, "evidence_items") == 0
        assert _count(db_path, "explanation_items") == 0
