"""Pure Campaign allocation projection for an existing Manual Trade.

The caller must provide an explicit, runtime-proven completeness claim.  An
empty list without that claim is not evidence of an unallocated trade.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

import formal_trade_attribution as fta

SCHEMA_VERSION = "trade_campaign_reconciliation.projection.v0.1"
AUTHORITY_REF = "tcr:trade_campaign_reconciliation:v0.1"
POLICY_VERSION_V01 = "tcr.trade_campaign_reconciliation.v0.1"
POLICY_AUTHORITY_REF_V01 = "tcr.trade_campaign_reconciliation_policy:v0.1"
ATTRIBUTION_COVERAGES = ("COMPLETE", "UNKNOWN", "NOT_EVALUATED", "ERROR")
ALLOCATION_STATES = ("ALLOCATED", "UNALLOCATED", "NOT_APPLICABLE", "UNKNOWN", "NOT_EVALUATED", "ERROR")
RECONCILIATION_REQUIREMENTS = ("NOT_REQUIRED", "REQUIRED", "NOT_APPLICABLE", "UNKNOWN", "NOT_EVALUATED", "ERROR")
_TRADE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SECURITY_RE = re.compile(r"^\d{6}$")


class TradeCampaignReconciliationError(Exception):
    pass


class TradeCampaignReconciliationValidationError(TradeCampaignReconciliationError, ValueError):
    pass


def _str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise TradeCampaignReconciliationValidationError(f"{field} must be a non-empty string")
    return value


def _refs(value: object, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TradeCampaignReconciliationValidationError(f"{field} must be non-empty authority refs")
    return [_str(item, f"{field}[{i}]") for i, item in enumerate(value)]


def _utc(value: object, field: str) -> datetime:
    try:
        return fta.parse_utc_instant(value, field)
    except fta.AttributionValidationError as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc


def _canon(value: object, field: str) -> str:
    try:
        return fta.to_canonical_utc(value, field)
    except fta.AttributionValidationError as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc


def _trade(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TradeCampaignReconciliationValidationError("trade must be a mapping")
    if not isinstance(value.get("trade_id"), str) or not _TRADE_ID_RE.fullmatch(value["trade_id"]):
        raise TradeCampaignReconciliationValidationError("trade_id is invalid")
    if not isinstance(value.get("code"), str) or not _SECURITY_RE.fullmatch(value["code"]):
        raise TradeCampaignReconciliationValidationError("trade.code is invalid")
    if value.get("operation") not in fta.TRADE_OPERATIONS:
        raise TradeCampaignReconciliationValidationError("trade.operation is invalid")
    if value.get("execution_status") not in fta.TRADE_EXECUTION_STATUSES:
        raise TradeCampaignReconciliationValidationError("trade.execution_status is invalid")
    _utc(value.get("created_at"), "trade.created_at")
    return value


def _result(*, as_of: str, trade: Mapping[str, Any], coverage: str, trade_refs: list[str], coverage_refs: list[str], state: str, requirement: str, reason: str, campaign_id: str | None = None, decision_id: str | None = None, attribution_id: str | None = None, extra: list[str] | None = None) -> dict[str, Any]:
    refs = [AUTHORITY_REF, POLICY_AUTHORITY_REF_V01, *trade_refs, *coverage_refs, *(extra or [])]
    authority_refs = list(dict.fromkeys(refs))
    return {
        "schema_version": SCHEMA_VERSION,
        "authority_ref": AUTHORITY_REF,
        "policy_version": POLICY_VERSION_V01,
        "policy_authority_ref": POLICY_AUTHORITY_REF_V01,
        "as_of": as_of,
        "trade_id": trade["trade_id"],
        "security_code": trade["code"],
        "execution_status": trade["execution_status"],
        "allocation_state": state,
        "reconciliation_requirement": requirement,
        "campaign_id": campaign_id,
        "decision_id": decision_id,
        "attribution_id": attribution_id,
        "attribution_coverage": coverage,
        "reason_codes": [reason],
        "trade_authority_refs": trade_refs,
        "attribution_coverage_authority_refs": coverage_refs,
        "authority_refs": authority_refs,
        "explainability": {
            "why_this_state": f"{state}/{requirement}/{coverage}/{reason}",
            "note": "EMPTY_LIST_ALONE_PROVES_UNALLOCATED=NO; CAMPAIGN_INFERENCE=NO; FIFO=FORBIDDEN",
        },
    }


def project_trade_campaign_reconciliation(*, as_of: str, policy_version: str, trade: object, attribution_records: object, attribution_coverage: str, attribution_coverage_authority_refs: object, trade_authority_refs: object) -> dict[str, Any]:
    """Project one trade; no I/O, inference, or wall clock."""
    if policy_version != POLICY_VERSION_V01:
        raise TradeCampaignReconciliationValidationError("unsupported policy_version")
    trade_map = _trade(trade)
    as_of_s = _str(as_of, "as_of")
    as_of_dt = _utc(as_of_s, "as_of")
    if attribution_coverage not in ATTRIBUTION_COVERAGES:
        raise TradeCampaignReconciliationValidationError("invalid attribution_coverage")
    coverage_refs = _refs(attribution_coverage_authority_refs, "attribution_coverage_authority_refs")
    trade_refs = _refs(trade_authority_refs, "trade_authority_refs")
    if not isinstance(attribution_records, (list, tuple)):
        raise TradeCampaignReconciliationValidationError("attribution_records must be a list")
    if _utc(trade_map["created_at"], "trade.created_at") > as_of_dt:
        raise TradeCampaignReconciliationValidationError("trade.created_at must be <= as_of")
    if trade_map.get("voided_at") is not None:
        _utc(trade_map["voided_at"], "trade.voided_at")
        return _result(as_of=as_of_s, trade=trade_map, coverage=attribution_coverage, trade_refs=trade_refs, coverage_refs=coverage_refs, state="NOT_APPLICABLE", requirement="NOT_APPLICABLE", reason="TRADE_VOIDED")
    try:
        anchor = fta.verify_trade_record(trade_map)
    except fta.AttributionValidationError as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc
    if anchor["trade_execution_status"] == "not_executed":
        return _result(as_of=as_of_s, trade=trade_map, coverage=attribution_coverage, trade_refs=trade_refs, coverage_refs=coverage_refs, state="NOT_APPLICABLE", requirement="NOT_APPLICABLE", reason="TRADE_NOT_EXECUTED")
    if attribution_coverage != "COMPLETE":
        state = {"UNKNOWN": "UNKNOWN", "NOT_EVALUATED": "NOT_EVALUATED", "ERROR": "ERROR"}[attribution_coverage]
        return _result(as_of=as_of_s, trade=trade_map, coverage=attribution_coverage, trade_refs=trade_refs, coverage_refs=coverage_refs, state=state, requirement=state, reason=f"ATTRIBUTION_COVERAGE_{attribution_coverage}")
    try:
        records = fta.validate_attribution_set(list(attribution_records))
        matches = fta.attribution_for_trade(trade_map["trade_id"], records)
    except (fta.AttributionValidationError, fta.AttributionConflictError, fta.AttributionSchemaVersionError) as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc
    for record in records:
        if _utc(record["created_at"], "attribution.created_at") > as_of_dt:
            raise TradeCampaignReconciliationValidationError("attribution.created_at must be <= as_of")
    if not matches:
        return _result(as_of=as_of_s, trade=trade_map, coverage="COMPLETE", trade_refs=trade_refs, coverage_refs=coverage_refs, state="UNALLOCATED", requirement="REQUIRED", reason="CAMPAIGN_ALLOCATION_MISSING")
    match = matches[0]
    if match["security_code"] != trade_map["code"] or match["trade_operation"] != trade_map["operation"] or match["trade_execution_status"] != trade_map["execution_status"]:
        raise TradeCampaignReconciliationValidationError("attribution anchor mismatch")
    if match["trade_created_at"] != _canon(trade_map["created_at"], "trade.created_at"):
        raise TradeCampaignReconciliationValidationError("trade_created_at mismatch")
    executed = trade_map.get("executed_at")
    if (match["trade_executed_at"] is None) != (executed is None) or (executed is not None and match["trade_executed_at"] != _canon(executed, "trade.executed_at")):
        raise TradeCampaignReconciliationValidationError("trade_executed_at mismatch")
    return _result(as_of=as_of_s, trade=trade_map, coverage="COMPLETE", trade_refs=trade_refs, coverage_refs=coverage_refs, state="ALLOCATED", requirement="NOT_REQUIRED", reason="FORMAL_ATTRIBUTION_PRESENT", campaign_id=match["campaign_id"], decision_id=match["decision_id"], attribution_id=match["attribution_id"], extra=[match["campaign_id"], match["decision_id"], match["attribution_id"]])
