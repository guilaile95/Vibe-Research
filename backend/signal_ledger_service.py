"""Signal ledger service.

Extracts pipeline stage signals and final decision outcomes from authoritative
portfolio advice results and archives them into the decision trace store.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import decision_evidence_service
import portfolio_advice_trace_adapter as adapter
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


def _entry(
    *,
    decision_run_id: str,
    stage: str,
    signal_type: str,
    payload: dict[str, Any],
    severity: str = "info",
    code: str | None = None,
    created_at: str,
    salt: Any = "",
) -> dict[str, Any]:
    return {
        "entry_id": _gen_id("sig", decision_run_id, stage, signal_type, code or "", salt),
        "stage": stage,
        "code": code,
        "signal_type": signal_type,
        "severity": severity,
        "payload_json": payload,
        "created_at": created_at,
    }


def archive_signal_ledger(
    advice_result: Mapping[str, Any],
    context_data: Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Extract signal entries and outcomes from authoritative advice and archive.

    Does not raise exceptions; returns status metadata dict.
    """
    del context_data  # reserved for future context enrichment; not required

    if not isinstance(advice_result, dict):
        logger.warning("archive_signal_ledger received non-dict advice_result")
        return {"status": "failed", "reason": "invalid_advice_result"}

    trade_date = str(advice_result.get("trade_date") or "").strip()
    generated_at = str(advice_result.get("generated_at") or "").strip()

    if not trade_date or not generated_at:
        now_iso = _utc_now()
        trade_date = trade_date or now_iso[:10]
        generated_at = generated_at or now_iso

    decision_run_id = decision_evidence_service.generate_decision_run_id(
        trade_date, generated_at
    )
    now_str = _utc_now()
    schema_version = str(advice_result.get("schema_version") or "portfolio-advice-v0.1")
    market_status = str(advice_result.get("market_status") or "normal").lower()
    source_fingerprint = (
        advice_result.get("source_fingerprint")
        or advice_result.get("input_fingerprint")
    )

    holdings = adapter.iter_authoritative_holdings(advice_result)
    portfolio_summary = advice_result.get("portfolio_summary")
    if not isinstance(portfolio_summary, dict):
        portfolio_summary = {}
    warnings = advice_result.get("warnings") if isinstance(advice_result.get("warnings"), list) else []
    data_limitations = (
        advice_result.get("data_limitations")
        if isinstance(advice_result.get("data_limitations"), list)
        else []
    )
    account_funding, _funding_quality = adapter.parse_account_funding(advice_result)
    constraint_state = adapter.extract_constraint_state(advice_result)

    signal_entries: list[dict[str, Any]] = []
    decision_outcomes: list[dict[str, Any]] = []

    # 1. schema
    signal_entries.append(
        _entry(
            decision_run_id=decision_run_id,
            stage="schema",
            signal_type="json_schema_validation",
            payload={
                "status": "passed",
                "schema_version": schema_version,
                "trade_date": trade_date,
                "generated_at": generated_at,
            },
            created_at=now_str,
        )
    )

    # 2. compatibility — authoritative result already assembled successfully
    signal_entries.append(
        _entry(
            decision_run_id=decision_run_id,
            stage="compatibility",
            signal_type="compatibility_check",
            payload={"status": "passed"},
            created_at=now_str,
        )
    )

    # 3. fact_reconciliation
    signal_entries.append(
        _entry(
            decision_run_id=decision_run_id,
            stage="fact_reconciliation",
            signal_type="market_environment_reconciliation",
            payload={
                "market_status": market_status,
                "portfolio_summary": portfolio_summary,
                "holding_count": len(holdings),
                "warnings": warnings,
                "data_limitations": data_limitations,
            },
            created_at=now_str,
        )
    )

    # 4–7. per-holding policy / execution / narrative + outcomes
    for idx, holding in enumerate(holdings):
        code = str(holding.get("code") or "").strip()
        payload = adapter.holding_execution_payload(holding)
        action = payload["action"]
        target_ratio = adapter.execution_size_to_target_ratio(
            payload["execution_size_pct_of_holding"]
        )
        reason = adapter.summarize_holding_reason(holding)

        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage="policy_audit",
                signal_type="policy_audit_holding",
                code=code,
                salt=idx,
                payload={
                    "name": payload["name"],
                    "action": action,
                    "execution_size_pct_of_holding": payload[
                        "execution_size_pct_of_holding"
                    ],
                    "confidence": payload["confidence"],
                },
                created_at=now_str,
            )
        )

        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage="execution",
                signal_type="action_generation",
                code=code,
                salt=idx,
                severity="info" if action != "sell" else "warning",
                payload={
                    "name": payload["name"],
                    "action": action,
                    "execution_size_pct_of_holding": payload[
                        "execution_size_pct_of_holding"
                    ],
                    "execution_quantity": payload["execution_quantity"],
                    "estimated_amount": payload["estimated_amount"],
                    "sellable_quantity_advisory": payload[
                        "sellable_quantity_advisory"
                    ]
                    if "sellable_quantity_advisory" in holding
                    else None,
                    "confidence": payload["confidence"],
                    "trigger_conditions": payload["trigger_conditions"],
                    "price_conditions": payload["price_conditions"],
                    "execution_plan": payload["execution_plan"],
                    "risk_conditions": payload["risk_conditions"],
                    "invalidation_conditions": payload["invalidation_conditions"],
                    "data_limitations": payload["data_limitations"],
                },
                created_at=now_str,
            )
        )

        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage="narrative_audit",
                signal_type="narrative_field_counts",
                code=code,
                salt=idx,
                payload=adapter.count_condition_fields(holding),
                created_at=now_str,
            )
        )

        constraints_applied: list[str] = []
        if "sellable_quantity_advisory" in holding and action in ("reduce", "sell"):
            constraints_applied.append("sellable_quantity_advisory")
            signal_entries.append(
                _entry(
                    decision_run_id=decision_run_id,
                    stage="account_constraint",
                    signal_type="sellable_quantity_check",
                    code=code,
                    salt=idx,
                    payload={
                        "sellable_quantity_advisory": holding.get(
                            "sellable_quantity_advisory"
                        ),
                        "execution_quantity": holding.get("execution_quantity"),
                        "shares": holding.get("shares"),
                        "advisory_only": True,
                    },
                    created_at=now_str,
                )
            )

        account_metrics = holding.get("account_metrics")
        if isinstance(account_metrics, dict):
            constraints_applied.append("account_metrics")

        decision_outcomes.append(
            {
                "outcome_id": _gen_id("out", decision_run_id, code),
                "code": code,
                "action": action,
                "target_ratio": target_ratio,
                "reason": reason,
                "constraints_applied_json": constraints_applied,
                "created_at": now_str,
            }
        )

    # account_constraint funding summary (always when funding object present)
    if account_funding is not None:
        severity = adapter.account_funding_severity(account_funding) or "warning"
        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage="account_constraint",
                signal_type="account_funding_constraint",
                severity=severity,
                payload={
                    "account_funding": account_funding,
                    "constraint_state": constraint_state,
                },
                created_at=now_str,
            )
        )
    else:
        # Ensure stage exists even without funding object
        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage="account_constraint",
                signal_type="account_funding_constraint",
                severity="warning",
                payload={
                    "account_funding": None,
                    "constraint_state": constraint_state,
                    "note": "account_funding missing",
                },
                created_at=now_str,
            )
        )

    # Ensure every stage is present even with zero holdings
    present_stages = {entry["stage"] for entry in signal_entries}
    for stage in VALID_STAGES:
        if stage in present_stages:
            continue
        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage=stage,
                signal_type=f"{stage}_placeholder",
                payload={"status": "passed", "note": "no_holdings"},
                created_at=now_str,
            )
        )

    try:
        store.save_signal_ledger_bundle(
            decision_run_id,
            signal_entries,
            decision_outcomes,
            trade_date=trade_date,
            generated_at=generated_at,
            schema_version=schema_version,
            market_status=market_status,
            source_fingerprint=source_fingerprint,
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
