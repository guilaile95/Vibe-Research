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

    ``context_data`` is intentionally unused: the authoritative advice result is
    the sole source of truth for production archives.
    """
    del context_data

    if not isinstance(advice_result, dict):
        logger.warning("archive_signal_ledger received non-dict advice_result")
        return {"status": "failed", "reason": "invalid_advice_result"}

    trade_date = str(advice_result.get("trade_date") or "").strip()
    generated_at = str(advice_result.get("generated_at") or "").strip()

    # Identity fields are required for decision_run_id / cross-store linkage.
    # Fail closed: no clock fill-in, no decision_run_id, no SQLite writes.
    if not trade_date or not generated_at:
        logger.warning(
            "archive_signal_ledger missing decision identity trade_date=%r generated_at=%r",
            trade_date,
            generated_at,
        )
        return {"status": "failed", "reason": "missing_decision_identity"}

    decision_run_id = decision_evidence_service.generate_decision_run_id(
        trade_date, generated_at
    )
    now_str = _utc_now()
    schema_version = adapter.resolve_advice_schema_version(advice_result)
    market_status = str(advice_result.get("market_status") or "normal").lower()
    source_fingerprint = (
        advice_result.get("source_fingerprint")
        or advice_result.get("input_fingerprint")
    )
    if source_fingerprint is not None:
        source_fingerprint = str(source_fingerprint)

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

    # 1. schema — only reached after identity validation
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

    # 2. compatibility — snapshot of successful final assembly only
    signal_entries.append(
        _entry(
            decision_run_id=decision_run_id,
            stage="compatibility",
            signal_type="compatibility_check",
            payload={
                "status": "passed",
                "note": "final_authoritative_snapshot",
            },
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

        policy_payload = {
            "name": payload["name"],
            "action": action,
            "execution_size_pct_of_holding": payload["execution_size_pct_of_holding"],
            "confidence": payload["confidence"],
        }
        if payload.get("execution_size_invalid"):
            policy_payload["execution_size_invalid"] = True
        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage="policy_audit",
                signal_type="policy_audit_holding",
                code=code,
                salt=idx,
                payload=policy_payload,
                created_at=now_str,
            )
        )

        # Use normalized payload as-is (includes execution_size_invalid when set)
        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage="execution",
                signal_type="action_generation",
                code=code,
                salt=idx,
                severity="info" if action != "sell" else "warning",
                payload=payload,
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

        # constraints_evaluated (not "applied") — honest naming in outcome JSON
        constraints_evaluated: list[str] = []
        if "sellable_quantity_advisory" in holding and action in ("reduce", "sell"):
            constraints_evaluated.append("sellable_quantity_advisory")
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
            constraints_evaluated.append("account_metrics_present")

        if adapter.holding_is_cash_constrained(holding):
            constraints_evaluated.append("add_quantity_null_with_positive_size")

        decision_outcomes.append(
            {
                "outcome_id": _gen_id("out", decision_run_id, code, idx),
                "code": code,
                "action": action,
                "target_ratio": target_ratio,
                "reason": reason,
                # column name remains constraints_applied_json (no schema migration)
                # values are evaluation tags, not claims of quantity mutation
                "constraints_applied_json": constraints_evaluated,
                "created_at": now_str,
            }
        )

    # account_constraint funding summary (always present for stage completeness)
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
                    "status": "not_applicable",
                },
                created_at=now_str,
            )
        )

    # Fill missing per-holding stages with not_applicable (not passed)
    present_stages = {entry["stage"] for entry in signal_entries}
    for stage in VALID_STAGES:
        if stage in present_stages:
            continue
        signal_entries.append(
            _entry(
                decision_run_id=decision_run_id,
                stage=stage,
                signal_type=f"{stage}_placeholder",
                payload={
                    "status": "not_applicable",
                    "note": "no_valid_holdings",
                },
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
