"""Signal ledger service.

Extracts pipeline execution signals and final decision outcomes from portfolio advice
authoritative results and archives them into the decision trace store.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import decision_evidence_service
import signal_ledger_store as store

logger = logging.getLogger(__name__)

VALID_STAGES = (
    "schema",
    "compatibility",
    "fact_reconciliation",
    "policy_audit",
    "execution",
    "narrative_audit",
    "account_constraint",
)

VALID_SEVERITIES = ("info", "warning", "error")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _gen_id(prefix: str, *args: Any) -> str:
    seed = ":".join(str(a) for a in args)
    return f"{prefix}_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def archive_signal_ledger(
    advice_result: Mapping[str, Any],
    context_data: Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Extract signal entries and outcomes from advice result and archive into database.

    Does not raise exceptions; returns status metadata dict.
    """
    if not isinstance(advice_result, dict):
        logger.warning("archive_signal_ledger received non-dict advice_result")
        return {"status": "failed", "reason": "invalid_advice_result"}

    trade_date = str(advice_result.get("trade_date") or "").strip()
    generated_at = str(advice_result.get("generated_at") or "").strip()

    if not trade_date or not generated_at:
        now_iso = _utc_now()
        trade_date = trade_date or now_iso[:10]
        generated_at = generated_at or now_iso

    decision_run_id = decision_evidence_service.generate_decision_run_id(trade_date, generated_at)
    now_str = _utc_now()

    signal_entries: list[dict[str, Any]] = []
    decision_outcomes: list[dict[str, Any]] = []

    # 1. Pipeline stage signals extraction
    # Stage: schema
    signal_entries.append(
        {
            "entry_id": _gen_id("sig", decision_run_id, "schema", "validator"),
            "stage": "schema",
            "code": None,
            "signal_type": "json_schema_validation",
            "severity": "info",
            "payload_json": {
                "status": "passed",
                "trade_date": trade_date,
                "generated_at": generated_at,
            },
            "created_at": now_str,
        }
    )

    # Stage: fact_reconciliation
    market_overview = advice_result.get("market_overview")
    if isinstance(market_overview, dict):
        signal_entries.append(
            {
                "entry_id": _gen_id("sig", decision_run_id, "fact_reconciliation", "market"),
                "stage": "fact_reconciliation",
                "code": None,
                "signal_type": "market_environment_reconciliation",
                "severity": "info",
                "payload_json": {
                    "market_sentiment": market_overview.get("market_sentiment"),
                    "position_recommendation": market_overview.get("position_recommendation"),
                },
                "created_at": now_str,
            }
        )

    # Stage: account_constraint
    account_metrics = advice_result.get("account_funding_metrics")
    if isinstance(account_metrics, dict):
        signal_entries.append(
            {
                "entry_id": _gen_id("sig", decision_run_id, "account_constraint", "funding"),
                "stage": "account_constraint",
                "code": None,
                "signal_type": "account_funding_constraint",
                "severity": "info" if account_metrics.get("is_sufficient", True) else "warning",
                "payload_json": account_metrics,
                "created_at": now_str,
            }
        )

    # Stage: execution & policy_audit per holding action
    actions = advice_result.get("actions") or advice_result.get("holdings_advice") or []
    if isinstance(actions, list):
        for idx, item in enumerate(actions):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            action = str(item.get("action") or item.get("operation") or "hold").lower()
            target_ratio = item.get("target_ratio") or item.get("target_position_pct")
            reason = str(item.get("reason") or item.get("analysis") or "").strip()

            # Record signal entry for execution
            signal_entries.append(
                {
                    "entry_id": _gen_id("sig", decision_run_id, "execution", code, idx),
                    "stage": "execution",
                    "code": code or None,
                    "signal_type": "action_generation",
                    "severity": "info" if action != "sell" else "warning",
                    "payload_json": {
                        "name": name,
                        "action": action,
                        "target_ratio": target_ratio,
                        "reason": reason,
                    },
                    "created_at": now_str,
                }
            )

            # Check for sellable quantity constraints / sellable advice
            sellable_info = item.get("sellable_quantity_advisory") or item.get("sellable_info")
            constraints_applied: list[str] = []
            if isinstance(sellable_info, dict):
                constraints_applied.append("sellable_quantity_advisory")
                signal_entries.append(
                    {
                        "entry_id": _gen_id("sig", decision_run_id, "account_constraint", code, idx),
                        "stage": "account_constraint",
                        "code": code or None,
                        "signal_type": "sellable_quantity_check",
                        "severity": "info",
                        "payload_json": sellable_info,
                        "created_at": now_str,
                    }
                )

            # Record final outcome
            if code:
                decision_outcomes.append(
                    {
                        "outcome_id": _gen_id("out", decision_run_id, code),
                        "code": code,
                        "action": action,
                        "target_ratio": float(target_ratio) if target_ratio is not None else None,
                        "reason": reason,
                        "constraints_applied_json": constraints_applied,
                        "created_at": now_str,
                    }
                )

    try:
        store.save_signal_ledger_bundle(
            decision_run_id,
            signal_entries,
            decision_outcomes,
            trade_date=trade_date,
            generated_at=generated_at,
            db_path=db_path,
        )
        return {
            "status": "success",
            "decision_run_id": decision_run_id,
            "signal_entries_count": len(signal_entries),
            "decision_outcomes_count": len(decision_outcomes),
        }
    except Exception as exc:
        logger.warning("Failed to save signal ledger bundle: %s", exc)
        return {
            "status": "failed",
            "decision_run_id": decision_run_id,
            "reason": str(exc),
        }
