"""Trade Campaign Reconciliation State Core v0.1 (P0-TCR1).

Answers one question only:

> For an already-recorded Manual Trade, given current formal attribution
> coverage, is the trade explicitly allocated to a Campaign? If not, must
> it enter UNALLOCATED / RECONCILIATION REQUIRED?

```text
TCR1_ROLE =
TRADE_CAMPAIGN_RECONCILIATION_STATE_AUTHORITY
```

Reuses stable P0-TB1 ``formal_trade_attribution`` for Formal Decision ↔
Manual Trade attribution. Does not reimplement decision witness, hash,
or one-trade-one-decision conflict.

Does not create campaigns, guess FIFO / same-security / latest campaign,
fabricate POST-ENTRY bindings, or convert PRE-VIBE holdings into BUY.

```text
EMPTY_LIST_ALONE_PROVES_UNALLOCATED = NO
COMPLETE_EMPTY_SET_PROVES_UNALLOCATED = YES
CAMPAIGN_INFERENCE = NO
```

Pure domain: no SQLite / filesystem / env / network / FastAPI / AI /
wall clock / persistence. Does not import campaign_store, campaign_service,
trade_ledger_store, or trade_ledger_service.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Mapping

import formal_trade_attribution as fta
from formal_trade_attribution import (
    AttributionConflictError,
    AttributionSchemaVersionError,
    AttributionValidationError,
)

SCHEMA_VERSION = "trade_campaign_reconciliation.projection.v0.1"
AUTHORITY_REF = "tcr:trade_campaign_reconciliation:v0.1"

POLICY_VERSION_V01 = "tcr.trade_campaign_reconciliation.v0.1"
POLICY_AUTHORITY_REF_V01 = "tcr:trade_campaign_reconciliation_policy:v0.1"

ATTRIBUTION_COVERAGES: tuple[str, ...] = (
    "COMPLETE",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

ALLOCATION_STATES: tuple[str, ...] = (
    "ALLOCATED",
    "UNALLOCATED",
    "NOT_APPLICABLE",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

RECONCILIATION_REQUIREMENTS: tuple[str, ...] = (
    "NOT_REQUIRED",
    "REQUIRED",
    "NOT_APPLICABLE",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)

_POLICY_REGISTRY: dict[str, str] = {
    POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01,
}

_TRADE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SECURITY_CODE_RE = re.compile(r"^\d{6}$")

_FORBIDDEN_ACTION_VOCAB: frozenset[str] = frozenset(
    {
        "BUY NOW",
        "BUY_SMALL",
        "BUY SMALL",
        "SCALE IN",
        "HOLD",
        "REDUCE",
        "EXIT",
        "AVOID",
        "WAIT",
    }
)

_CROSS_ANCHOR_FIELDS: tuple[tuple[str, str], ...] = (
    ("trade_id", "trade_id"),
    ("security_code", "code"),
    ("trade_operation", "operation"),
    ("trade_execution_status", "execution_status"),
)


class TradeCampaignReconciliationError(Exception):
    """TCR1 domain base error."""


class TradeCampaignReconciliationValidationError(
    TradeCampaignReconciliationError, ValueError
):
    """Illegal caller input / contract violation → fail closed."""


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TradeCampaignReconciliationValidationError(
            f"{field} must be a non-empty string"
        )
    if value != value.strip():
        raise TradeCampaignReconciliationValidationError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def _require_enum(value: object, field: str, allowed: tuple[str, ...]) -> str:
    text = _require_nonempty_str(value, field)
    if text not in allowed:
        raise TradeCampaignReconciliationValidationError(
            f"{field} must be one of {allowed}, got {text!r}"
        )
    return text


def _require_authority_refs(value: object, field: str) -> list[str]:
    if value is None:
        raise TradeCampaignReconciliationValidationError(f"{field} is required")
    if not isinstance(value, (list, tuple)):
        raise TradeCampaignReconciliationValidationError(
            f"{field} must be a list/tuple of strings"
        )
    if len(value) == 0:
        raise TradeCampaignReconciliationValidationError(
            f"{field} must be non-empty (naked self-asserted proof rejected)"
        )
    refs: list[str] = []
    for i, ref in enumerate(value):
        if not isinstance(ref, str) or not ref.strip() or ref != ref.strip():
            raise TradeCampaignReconciliationValidationError(
                f"{field}[{i}] must be a non-empty stripped string"
            )
        refs.append(ref)
    return refs


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TradeCampaignReconciliationValidationError(f"{field} must be a mapping")
    return value


def _require_records(value: object) -> list[Any]:
    if value is None:
        raise TradeCampaignReconciliationValidationError(
            "attribution_records is required (use [] only with explicit coverage)"
        )
    if not isinstance(value, (list, tuple)):
        raise TradeCampaignReconciliationValidationError(
            "attribution_records must be a list/tuple"
        )
    return list(value)


def _parse_as_of(value: object) -> tuple[str, datetime]:
    raw = _require_nonempty_str(value, "as_of")
    try:
        dt = fta.parse_utc_instant(raw, "as_of")
    except AttributionValidationError as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc
    return raw, dt


def _parse_utc(value: object, field: str) -> datetime:
    try:
        return fta.parse_utc_instant(value, field)
    except AttributionValidationError as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc


def _canonical_utc(value: object, field: str) -> str:
    try:
        return fta.to_canonical_utc(value, field)
    except AttributionValidationError as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc


def _validate_trade_identity(trade: Mapping[str, Any]) -> None:
    trade_id = trade.get("trade_id")
    if not isinstance(trade_id, str) or not _TRADE_ID_RE.fullmatch(trade_id):
        raise TradeCampaignReconciliationValidationError(
            "trade.trade_id must be 32 lowercase hex"
        )
    code = trade.get("code")
    if not isinstance(code, str) or not _SECURITY_CODE_RE.fullmatch(code):
        raise TradeCampaignReconciliationValidationError(
            "trade.code must be a 6-digit A-share code"
        )
    if trade.get("operation") not in fta.TRADE_OPERATIONS:
        raise TradeCampaignReconciliationValidationError(
            f"trade.operation must be one of {fta.TRADE_OPERATIONS}"
        )
    if trade.get("execution_status") not in fta.TRADE_EXECUTION_STATUSES:
        raise TradeCampaignReconciliationValidationError(
            f"trade.execution_status must be one of {fta.TRADE_EXECUTION_STATUSES}"
        )
    if trade.get("created_at") is None:
        raise TradeCampaignReconciliationValidationError("trade.created_at is required")
    _parse_utc(trade.get("created_at"), "trade.created_at")


def _cross_anchor_or_fail(
    match: Mapping[str, Any], trade: Mapping[str, Any]
) -> None:
    for attr_field, trade_field in _CROSS_ANCHOR_FIELDS:
        left = match[attr_field]
        right = trade[trade_field] if trade_field != "trade_id" else trade["trade_id"]
        if left != right:
            raise TradeCampaignReconciliationValidationError(
                f"attribution/{trade_field} mismatch: {left!r} != {right!r}"
            )
    trade_created = _canonical_utc(trade["created_at"], "trade.created_at")
    if match["trade_created_at"] != trade_created:
        raise TradeCampaignReconciliationValidationError(
            "attribution/trade_created_at mismatch"
        )
    executed = trade.get("executed_at")
    if match["trade_executed_at"] is None:
        if executed is not None:
            raise TradeCampaignReconciliationValidationError(
                "attribution/trade_executed_at mismatch"
            )
    else:
        if executed is None:
            raise TradeCampaignReconciliationValidationError(
                "attribution/trade_executed_at mismatch"
            )
        if match["trade_executed_at"] != _canonical_utc(executed, "trade.executed_at"):
            raise TradeCampaignReconciliationValidationError(
                "attribution/trade_executed_at mismatch"
            )


def _unknown_policy_result(
    *,
    version: str,
    as_of_s: str,
    trade_id: str,
    security_code: str,
    execution_status: str,
    coverage: str,
    trade_refs: list[str],
    coverage_refs: list[str],
) -> dict[str, Any]:
    reason_codes = ["POLICY_VERSION_NOT_AVAILABLE"]
    authority_refs = [AUTHORITY_REF]
    for ref in trade_refs + coverage_refs:
        if ref not in authority_refs:
            authority_refs.append(ref)
    return copy.deepcopy(
        {
            "schema_version": SCHEMA_VERSION,
            "authority_ref": AUTHORITY_REF,
            "policy_version": version,
            "policy_authority_ref": None,
            "as_of": as_of_s,
            "trade_id": trade_id,
            "security_code": security_code,
            "execution_status": execution_status,
            "allocation_state": "NOT_EVALUATED",
            "reconciliation_requirement": "NOT_EVALUATED",
            "campaign_id": None,
            "decision_id": None,
            "attribution_id": None,
            "attribution_coverage": coverage,
            "reason_codes": reason_codes,
            "trade_authority_refs": list(trade_refs),
            "attribution_coverage_authority_refs": list(coverage_refs),
            "authority_refs": authority_refs,
            "explainability": {
                "why_this_state": (
                    "POLICY_VERSION_NOT_AVAILABLE; "
                    "POLICY_SEMANTICS_APPLIED=NO; "
                    "NO_IMPLICIT_V01_UNALLOCATED"
                ),
                "note": (
                    "EMPTY_LIST_ALONE_PROVES_UNALLOCATED=NO; "
                    "CAMPAIGN_INFERENCE=NO; "
                    "CAMPAIGN_EXISTENCE_VERIFIED=NO; "
                    "UPSTREAM_AUTHORITY_BINDING_VERIFIED=NO"
                ),
            },
        }
    )


def _result(
    *,
    version: str,
    policy_ref: str,
    as_of_s: str,
    trade_id: str,
    security_code: str,
    execution_status: str,
    allocation_state: str,
    reconciliation_requirement: str,
    campaign_id: str | None,
    decision_id: str | None,
    attribution_id: str | None,
    coverage: str,
    reason_codes: list[str],
    trade_refs: list[str],
    coverage_refs: list[str],
    extra_authority: list[str] | None = None,
) -> dict[str, Any]:
    authority_refs = [AUTHORITY_REF, policy_ref]
    for ref in trade_refs + coverage_refs + (extra_authority or []):
        if ref not in authority_refs:
            authority_refs.append(ref)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "authority_ref": AUTHORITY_REF,
        "policy_version": version,
        "policy_authority_ref": policy_ref,
        "as_of": as_of_s,
        "trade_id": trade_id,
        "security_code": security_code,
        "execution_status": execution_status,
        "allocation_state": allocation_state,
        "reconciliation_requirement": reconciliation_requirement,
        "campaign_id": campaign_id,
        "decision_id": decision_id,
        "attribution_id": attribution_id,
        "attribution_coverage": coverage,
        "reason_codes": list(reason_codes),
        "trade_authority_refs": list(trade_refs),
        "attribution_coverage_authority_refs": list(coverage_refs),
        "authority_refs": authority_refs,
        "explainability": {
            "why_this_state": (
                f"allocation_state={allocation_state}; "
                f"reconciliation_requirement={reconciliation_requirement}; "
                f"attribution_coverage={coverage}; "
                f"reasons={','.join(reason_codes)}"
            ),
            "note": (
                "EMPTY_LIST_ALONE_PROVES_UNALLOCATED=NO; "
                "COMPLETE_EMPTY_SET_PROVES_UNALLOCATED=YES; "
                "CAMPAIGN_INFERENCE=NO; "
                "FIFO=FORBIDDEN; "
                "CAMPAIGN_EXISTENCE_VERIFIED=NO; "
                "CAMPAIGN_STATUS_VERIFIED=NO; "
                "POST_ENTRY_BINDING_ENGINE=OUT_OF_SCOPE; "
                "PRE_VIBE_SYNTHETIC_BUY=FORBIDDEN; "
                "UPSTREAM_AUTHORITY_BINDING_VERIFIED=NO"
            ),
        },
    }
    flat: list[str] = []
    for v in payload.values():
        if isinstance(v, str):
            flat.append(v)
        elif isinstance(v, list):
            flat.extend(x for x in v if isinstance(x, str))
    for token in _FORBIDDEN_ACTION_VOCAB:
        if token in flat:
            raise TradeCampaignReconciliationValidationError(
                f"internal integrity: forbidden action token {token!r}"
            )
    return copy.deepcopy(payload)


def project_trade_campaign_reconciliation(
    *,
    as_of: str,
    policy_version: str,
    trade: object,
    attribution_records: object,
    attribution_coverage: str,
    attribution_coverage_authority_refs: object,
    trade_authority_refs: object,
) -> dict[str, Any]:
    """Project Campaign allocation / reconciliation requirement for one trade.

    ``attribution_coverage`` is an explicit upstream completeness claim.
    An empty attribution list alone does not prove UNALLOCATED.
    """
    trade_map = _require_mapping(trade, "trade")
    _validate_trade_identity(trade_map)
    as_of_s, as_of_dt = _parse_as_of(as_of)
    version = _require_nonempty_str(policy_version, "policy_version")
    coverage = _require_enum(
        attribution_coverage, "attribution_coverage", ATTRIBUTION_COVERAGES
    )
    coverage_refs = _require_authority_refs(
        attribution_coverage_authority_refs,
        "attribution_coverage_authority_refs",
    )
    trade_refs = _require_authority_refs(
        trade_authority_refs, "trade_authority_refs"
    )
    records = _require_records(attribution_records)

    trade_id = trade_map["trade_id"]
    security_code = trade_map["code"]
    execution_status = trade_map["execution_status"]

    policy_ref = _POLICY_REGISTRY.get(version)
    if policy_ref is None:
        return _unknown_policy_result(
            version=version,
            as_of_s=as_of_s,
            trade_id=trade_id,
            security_code=security_code,
            execution_status=execution_status,
            coverage=coverage,
            trade_refs=trade_refs,
            coverage_refs=coverage_refs,
        )

    voided_at = trade_map.get("voided_at")
    if voided_at is not None:
        _parse_utc(voided_at, "trade.voided_at")
        return _result(
            version=version,
            policy_ref=policy_ref,
            as_of_s=as_of_s,
            trade_id=trade_id,
            security_code=security_code,
            execution_status=execution_status,
            allocation_state="NOT_APPLICABLE",
            reconciliation_requirement="NOT_APPLICABLE",
            campaign_id=None,
            decision_id=None,
            attribution_id=None,
            coverage=coverage,
            reason_codes=["TRADE_VOIDED"],
            trade_refs=trade_refs,
            coverage_refs=coverage_refs,
        )

    try:
        trade_anchor = fta.verify_trade_record(trade_map)
    except AttributionValidationError as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc

    created_dt = _parse_utc(trade_anchor["trade_created_at"], "trade.created_at")
    if created_dt > as_of_dt:
        raise TradeCampaignReconciliationValidationError(
            "trade.created_at must be <= as_of"
        )
    if trade_anchor["trade_executed_at"] is not None:
        executed_dt = _parse_utc(
            trade_anchor["trade_executed_at"], "trade.executed_at"
        )
        if executed_dt > as_of_dt:
            raise TradeCampaignReconciliationValidationError(
                "trade.executed_at must be <= as_of"
            )

    if trade_anchor["trade_execution_status"] == "not_executed":
        return _result(
            version=version,
            policy_ref=policy_ref,
            as_of_s=as_of_s,
            trade_id=trade_id,
            security_code=security_code,
            execution_status=execution_status,
            allocation_state="NOT_APPLICABLE",
            reconciliation_requirement="NOT_APPLICABLE",
            campaign_id=None,
            decision_id=None,
            attribution_id=None,
            coverage=coverage,
            reason_codes=["TRADE_NOT_EXECUTED"],
            trade_refs=trade_refs,
            coverage_refs=coverage_refs,
        )

    if coverage == "NOT_EVALUATED":
        return _result(
            version=version,
            policy_ref=policy_ref,
            as_of_s=as_of_s,
            trade_id=trade_id,
            security_code=security_code,
            execution_status=execution_status,
            allocation_state="NOT_EVALUATED",
            reconciliation_requirement="NOT_EVALUATED",
            campaign_id=None,
            decision_id=None,
            attribution_id=None,
            coverage=coverage,
            reason_codes=["ATTRIBUTION_COVERAGE_NOT_EVALUATED"],
            trade_refs=trade_refs,
            coverage_refs=coverage_refs,
        )
    if coverage == "ERROR":
        return _result(
            version=version,
            policy_ref=policy_ref,
            as_of_s=as_of_s,
            trade_id=trade_id,
            security_code=security_code,
            execution_status=execution_status,
            allocation_state="ERROR",
            reconciliation_requirement="ERROR",
            campaign_id=None,
            decision_id=None,
            attribution_id=None,
            coverage=coverage,
            reason_codes=["ATTRIBUTION_COVERAGE_ERROR"],
            trade_refs=trade_refs,
            coverage_refs=coverage_refs,
        )
    if coverage == "UNKNOWN":
        return _result(
            version=version,
            policy_ref=policy_ref,
            as_of_s=as_of_s,
            trade_id=trade_id,
            security_code=security_code,
            execution_status=execution_status,
            allocation_state="UNKNOWN",
            reconciliation_requirement="UNKNOWN",
            campaign_id=None,
            decision_id=None,
            attribution_id=None,
            coverage=coverage,
            reason_codes=["ATTRIBUTION_COVERAGE_UNKNOWN"],
            trade_refs=trade_refs,
            coverage_refs=coverage_refs,
        )

    try:
        validated = fta.validate_attribution_set(records)
        matches = fta.attribution_for_trade(trade_id, validated)
    except (
        AttributionValidationError,
        AttributionConflictError,
        AttributionSchemaVersionError,
    ) as exc:
        raise TradeCampaignReconciliationValidationError(str(exc)) from exc

    for rec in validated:
        created = _parse_utc(rec["created_at"], "attribution.created_at")
        if created > as_of_dt:
            raise TradeCampaignReconciliationValidationError(
                "attribution.created_at must be <= as_of"
            )

    if not matches:
        return _result(
            version=version,
            policy_ref=policy_ref,
            as_of_s=as_of_s,
            trade_id=trade_id,
            security_code=security_code,
            execution_status=execution_status,
            allocation_state="UNALLOCATED",
            reconciliation_requirement="REQUIRED",
            campaign_id=None,
            decision_id=None,
            attribution_id=None,
            coverage=coverage,
            reason_codes=["CAMPAIGN_ALLOCATION_MISSING"],
            trade_refs=trade_refs,
            coverage_refs=coverage_refs,
        )

    match = matches[0]
    _cross_anchor_or_fail(match, trade_map)
    extra = [match["attribution_id"], match["decision_id"], match["campaign_id"]]
    return _result(
        version=version,
        policy_ref=policy_ref,
        as_of_s=as_of_s,
        trade_id=trade_id,
        security_code=security_code,
        execution_status=execution_status,
        allocation_state="ALLOCATED",
        reconciliation_requirement="NOT_REQUIRED",
        campaign_id=match["campaign_id"],
        decision_id=match["decision_id"],
        attribution_id=match["attribution_id"],
        coverage=coverage,
        reason_codes=["FORMAL_ATTRIBUTION_PRESENT"],
        trade_refs=trade_refs,
        coverage_refs=coverage_refs,
        extra_authority=extra,
    )
