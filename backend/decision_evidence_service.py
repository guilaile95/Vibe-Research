"""Decision evidence extraction and archiving service.

Extracts structured evidence items (market, sector, stock, portfolio, account, risk)
and explanations from portfolio advice authoritative results and context, then archives
them into the decision trace store.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import decision_trace_store as store

logger = logging.getLogger(__name__)

VALID_SCOPES = ("market", "sector", "stock", "portfolio", "account", "risk")
VALID_QUALITY_STATUSES = ("valid", "partial", "missing", "stale", "unavailable")


def generate_decision_run_id(trade_date: str, generated_at: str) -> str:
    """Generate a deterministic decision_run_id using SHA-256 hash of advice key fields."""
    content = f"portfolio_advice\n{trade_date}\n{generated_at}"
    return "dr_" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _gen_id(prefix: str, *args: Any) -> str:
    seed = ":".join(str(a) for a in args)
    return f"{prefix}_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def archive_decision_evidence(
    advice_result: Mapping[str, Any],
    context_data: Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Extract evidence and explanations from portfolio advice result and context, and archive them.

    Guaranteed not to raise exceptions to the caller; if archiving fails, logs a warning,
    marks trace_status as 'failed' if feasible, and returns a safe metadata dict.
    """
    if not isinstance(advice_result, dict):
        logger.warning("archive_decision_evidence received non-dict advice_result")
        return {"status": "failed", "reason": "invalid_advice_result"}

    trade_date = str(advice_result.get("trade_date") or "").strip()
    generated_at = str(advice_result.get("generated_at") or "").strip()

    if not trade_date or not generated_at:
        now_iso = _utc_now()
        trade_date = trade_date or now_iso[:10]
        generated_at = generated_at or now_iso

    run_id = generate_decision_run_id(trade_date, generated_at)
    now_str = _utc_now()

    try:
        context_data = context_data or advice_result.get("context") or {}

        evidence_items: list[dict[str, Any]] = []
        explanation_items: list[dict[str, Any]] = []

        # 1. Market scope evidence
        mkt_status = str(advice_result.get("market_status") or "normal").lower()
        mkt_ev_id = _gen_id("ev", run_id, "market", "status")
        mkt_quality = "valid" if mkt_status == "normal" else ("partial" if mkt_status == "partial" else "unavailable")
        evidence_items.append(
            {
                "evidence_id": mkt_ev_id,
                "decision_run_id": run_id,
                "scope": "market",
                "code": None,
                "evidence_key": "market_status",
                "value_json": {"status": mkt_status},
                "unit": None,
                "source_module": "daily_review",
                "observed_at": generated_at,
                "quality_status": mkt_quality,
                "source_ref_json": None,
                "created_at": now_str,
            }
        )

        # 2. Portfolio & Account scope evidence
        account_metrics = advice_result.get("account_funding_metrics") or advice_result.get("account") or {}
        acc_ev_id = _gen_id("ev", run_id, "account", "metrics")
        acc_quality = "valid" if account_metrics else "missing"
        evidence_items.append(
            {
                "evidence_id": acc_ev_id,
                "decision_run_id": run_id,
                "scope": "account",
                "code": None,
                "evidence_key": "funding_metrics",
                "value_json": account_metrics if isinstance(account_metrics, dict) else {},
                "unit": "yuan",
                "source_module": "portfolio_advice_account_metrics",
                "observed_at": generated_at,
                "quality_status": acc_quality,
                "source_ref_json": None,
                "created_at": now_str,
            }
        )

        pf_summary = advice_result.get("portfolio_summary") or {}
        pf_ev_id = _gen_id("ev", run_id, "portfolio", "summary")
        evidence_items.append(
            {
                "evidence_id": pf_ev_id,
                "decision_run_id": run_id,
                "scope": "portfolio",
                "code": None,
                "evidence_key": "portfolio_summary",
                "value_json": pf_summary if isinstance(pf_summary, dict) else {},
                "unit": None,
                "source_module": "portfolio_advice_context",
                "observed_at": generated_at,
                "quality_status": "valid" if pf_summary else "partial",
                "source_ref_json": None,
                "created_at": now_str,
            }
        )

        # Risk scope evidence
        risk_ev_id = _gen_id("ev", run_id, "risk", "constraints")
        evidence_items.append(
            {
                "evidence_id": risk_ev_id,
                "decision_run_id": run_id,
                "scope": "risk",
                "code": None,
                "evidence_key": "risk_constraints",
                "value_json": {
                    "cash_constraint_applied": "available_cash" in account_metrics or "cash" in account_metrics,
                    "sellable_quantity_applied": True,
                },
                "unit": None,
                "source_module": "portfolio_advice_policy",
                "observed_at": generated_at,
                "quality_status": "valid",
                "source_ref_json": None,
                "created_at": now_str,
            }
        )

        # Stock scope evidence & explanations
        stock_items = (
            advice_result.get("items")
            or advice_result.get("advices")
            or advice_result.get("holdings")
            or []
        )
        if isinstance(stock_items, dict):
            stock_items = list(stock_items.values())

        if isinstance(stock_items, list):
            for idx, item in enumerate(stock_items):
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code") or "").strip()
                if not code:
                    continue

                stock_ev_id = _gen_id("ev", run_id, "stock", code, "quote")
                price = item.get("current_price") or item.get("price")
                q_status = "valid" if price is not None else "partial"

                evidence_items.append(
                    {
                        "evidence_id": stock_ev_id,
                        "decision_run_id": run_id,
                        "scope": "stock",
                        "code": code,
                        "evidence_key": "stock_quote_and_holding",
                        "value_json": {
                            "name": item.get("name"),
                            "price": price,
                            "change_pct": item.get("change_pct"),
                            "holding_weight_pct": item.get("holding_weight_pct"),
                            "shares": item.get("shares"),
                            "sellable_shares": item.get("sellable_shares"),
                        },
                        "unit": None,
                        "source_module": "portfolio_advice_context",
                        "observed_at": generated_at,
                        "quality_status": q_status,
                        "source_ref_json": None,
                        "created_at": now_str,
                    }
                )

                # Stock level explanation
                action = str(item.get("action") or "hold")
                reason = str(item.get("reason") or item.get("explanation") or f"Stock {code} advice {action}")
                rule_id = None
                if item.get("execution_size_pct_of_holding") is not None:
                    rule_id = "rule_execution_size"
                if item.get("cash_constrained"):
                    rule_id = "rule_cash_constraint"

                exp_id = _gen_id("exp", run_id, code, "action", idx)
                explanation_items.append(
                    {
                        "explanation_id": exp_id,
                        "decision_run_id": run_id,
                        "code": code,
                        "conclusion_type": "action",
                        "conclusion_value": action,
                        "explanation_text": reason,
                        "supporting_evidence_ids": [stock_ev_id, mkt_ev_id],
                        "limiting_evidence_ids": [risk_ev_id] if rule_id else [],
                        "rule_id": rule_id,
                        "created_at": now_str,
                    }
                )

        # Portfolio level explanation if account action present
        account_action = advice_result.get("account_action") or advice_result.get("overall_action")
        if account_action:
            exp_id = _gen_id("exp", run_id, "portfolio", "account_action", 0)
            explanation_items.append(
                {
                    "explanation_id": exp_id,
                    "decision_run_id": run_id,
                    "code": None,
                    "conclusion_type": "account_action",
                    "conclusion_value": str(account_action),
                    "explanation_text": str(advice_result.get("account_reason") or advice_result.get("summary") or "Overall account position recommendation"),
                    "supporting_evidence_ids": [acc_ev_id, mkt_ev_id, pf_ev_id],
                    "limiting_evidence_ids": [risk_ev_id],
                    "rule_id": "rule_account_allocation",
                    "created_at": now_str,
                }
            )

        run_record = {
            "decision_run_id": run_id,
            "trade_date": trade_date,
            "generated_at": generated_at,
            "result_type": "portfolio_advice",
            "schema_version": advice_result.get("schema_version") or store.SCHEMA_VERSION,
            "market_status": mkt_status,
            "source_fingerprint": advice_result.get("source_fingerprint") or advice_result.get("input_fingerprint"),
            "trace_status": "archived",
            "created_at": now_str,
        }

        store.save_decision_run_bundle(
            run_record=run_record,
            evidence_items=evidence_items,
            explanation_items=explanation_items,
            db_path=db_path,
        )

        return {
            "status": "archived",
            "decision_run_id": run_id,
            "evidence_count": len(evidence_items),
            "explanation_count": len(explanation_items),
        }

    except store.DecisionTraceCorruptedError:
        logger.error("Decision trace store corrupted while archiving decision evidence for run_id %s", run_id)
        return {"status": "failed", "decision_run_id": run_id, "reason": "db_corrupted"}
    except Exception as exc:
        logger.exception("Failed to archive decision evidence for run_id %s: %s", run_id, exc)
        try:
            # Attempt to record failed status in DB if possible
            run_record = {
                "decision_run_id": run_id,
                "trade_date": trade_date,
                "generated_at": generated_at,
                "result_type": "portfolio_advice",
                "schema_version": store.SCHEMA_VERSION,
                "market_status": "unavailable",
                "source_fingerprint": None,
                "trace_status": "failed",
                "created_at": now_str,
            }
            store.save_decision_run_bundle(run_record, [], [], db_path=db_path)
        except Exception:
            pass
        return {"status": "failed", "decision_run_id": run_id, "reason": str(exc)}
