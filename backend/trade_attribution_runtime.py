"""TAR1 runtime authority: actual Trade + actual Frozen Decision only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import threading
import uuid

import formal_trade_attribution as fta
import formal_trade_attribution_store as attribution_store
import frozen_decision_service
import trade_campaign_reconciliation as reconciliation
import trade_ledger_service
import trade_origin_store as origin_store


class TradeAttributionRuntimeError(RuntimeError):
    pass


class TradeAttributionNotFoundError(TradeAttributionRuntimeError):
    pass


class TradeAttributionConflictError(TradeAttributionRuntimeError):
    pass


class TradeAttributionValidationError(TradeAttributionRuntimeError, ValueError):
    pass


TRADE_RESOLUTION_LOCK = threading.RLock()
_DECISION_PAGE_SIZE = 500
_DECISION_SAFETY_BOUND = 10_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _attribution_path():
    return attribution_store.resolve_formal_trade_attribution_db_path()


def _origin_path():
    return origin_store.resolve_db_path()


def _trade(trade_id: str) -> dict[str, Any]:
    value = trade_ledger_service.get_trade(trade_id)
    if value is None:
        raise TradeAttributionNotFoundError("交易记录不存在")
    return value


def _decision(decision_id: str) -> dict[str, Any]:
    value = frozen_decision_service.get_decision(decision_id)
    if value is None:
        raise TradeAttributionNotFoundError("冻结决策不存在")
    return value


def _eligible(decision: dict[str, Any], trade: dict[str, Any]) -> bool:
    try:
        witness = fta.verify_frozen_decision_witness(decision)
        anchor = fta.verify_trade_record(trade)
    except fta.AttributionValidationError:
        return False
    if witness["security_code"] != trade["code"]:
        return False
    if fta.parse_utc_instant(witness["decision_committed_at"], "decision.committed_at") > fta.parse_utc_instant(anchor["trade_created_at"], "trade.created_at"):
        return False
    if anchor["trade_executed_at"] is not None and fta.parse_utc_instant(witness["decision_committed_at"], "decision.committed_at") > fta.parse_utc_instant(anchor["trade_executed_at"], "trade.executed_at"):
        return False
    return True


def list_candidates(trade_id: str) -> list[dict[str, Any]]:
    trade = _trade(trade_id)
    if trade.get("voided_at") is not None or trade.get("execution_status") == "not_executed":
        return []
    decisions: list[dict[str, Any]] = []
    offset = 0
    while offset < _DECISION_SAFETY_BOUND:
        page = frozen_decision_service.list_decisions(
            security_code=trade["code"],
            limit=_DECISION_PAGE_SIZE,
            offset=offset,
        )
        decisions.extend(page)
        if len(page) < _DECISION_PAGE_SIZE:
            break
        offset += len(page)
    else:
        raise TradeAttributionRuntimeError("冻结决策候选超过安全分页上限，已停止读取")
    output = []
    for decision in decisions:
        if _eligible(decision, trade):
            output.append({
                "decision_id": decision["decision_id"],
                "campaign_id": decision["campaign_id"],
                "security_code": decision["security_code"],
                "strategy": decision["strategy"],
                "thesis_id": decision["thesis_id"],
                "thesis_revision": decision["thesis_revision"],
                "committed_at": decision["committed_at"],
                "review_by": decision["review_by"],
                "next_best_action": decision["next_best_action"],
                "snapshot_hash": decision["snapshot_hash"],
            })
    return output


def _request_keys(payload: object, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TradeAttributionValidationError("请求体必须是 JSON 对象")
    extra = set(payload) - allowed
    if extra:
        raise TradeAttributionValidationError("禁止调用方提交正式身份或归属字段")
    return payload


def attribute(trade_id: str, payload: object) -> dict[str, Any]:
    body = _request_keys(payload, {"decision_id"})
    decision_id = body.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id.strip():
        raise TradeAttributionValidationError("decision_id 必填")
    trade = _trade(trade_id)
    if trade.get("voided_at") is not None:
        raise TradeAttributionValidationError("作废交易不可归属")
    if trade.get("execution_status") == "not_executed":
        raise TradeAttributionValidationError("未执行交易不可归属")
    decision = _decision(decision_id)
    if not _eligible(decision, trade):
        raise TradeAttributionValidationError("冻结决策不是该交易的可归属候选")
    try:
        record = fta.create_attribution(decision, trade, attribution_id=fta.new_attribution_id(), created_at=_now()).to_dict()
        with TRADE_RESOLUTION_LOCK:
            existing_origin = origin_store.get_for_trade(db_path=_origin_path(), trade_id=trade_id)
            if existing_origin is not None:
                raise TradeAttributionConflictError("交易已明确为 UNPLANNED，不可再建立 Formal Attribution")
            existing = attribution_store.get_attribution_for_trade(db_path=_attribution_path(), trade_id=trade_id)
            if existing is not None:
                if existing["decision_id"] == record["decision_id"] and existing["decision_snapshot_hash"] == record["decision_snapshot_hash"]:
                    return {"record": existing, "idempotent": True}
                raise TradeAttributionConflictError("交易已归属其他冻结决策")
            saved = attribution_store.write_attribution(db_path=_attribution_path(), record=record)
            return {"record": saved, "idempotent": False}
    except (fta.AttributionValidationError, fta.AttributionSchemaVersionError) as exc:
        raise TradeAttributionValidationError(str(exc)) from exc
    except attribution_store.FormalTradeAttributionStoreConflictError as exc:
        raise TradeAttributionConflictError(str(exc)) from exc


def mark_unplanned(trade_id: str, payload: object) -> dict[str, Any]:
    body = _request_keys(payload, {"confirm"})
    if body.get("confirm") is not True:
        raise TradeAttributionValidationError("必须明确 confirm=true")
    trade = _trade(trade_id)
    if trade.get("voided_at") is not None or trade.get("execution_status") == "not_executed":
        raise TradeAttributionValidationError("作废或未执行交易不可标记 UNPLANNED")
    try:
        trade_anchor = fta.verify_trade_record(trade)
    except fta.AttributionValidationError as exc:
        raise TradeAttributionValidationError(str(exc)) from exc
    if trade_anchor["thesis_id"] is not None or trade_anchor["thesis_revision"] is not None:
        raise TradeAttributionConflictError(
            "该 Trade 已有 pre-trade Thesis authority，不能声明 UNPLANNED/NONE"
        )
    record = {
        "resolution_id": f"trade_origin_{uuid.uuid4().hex}",
        "trade_id": trade_id,
        "origin": "UNPLANNED",
        "pre_trade_decision": "NONE",
        "pre_trade_thesis": "NONE",
        "created_at": _now(),
    }
    try:
        with TRADE_RESOLUTION_LOCK:
            existing_attribution = attribution_store.get_attribution_for_trade(db_path=_attribution_path(), trade_id=trade_id)
            if existing_attribution is not None:
                raise TradeAttributionConflictError("交易已有 Formal Attribution，不可再声明 UNPLANNED")
            existing = origin_store.get_for_trade(db_path=_origin_path(), trade_id=trade_id)
            if existing is not None:
                if existing["origin"] == "UNPLANNED":
                    return {"record": existing, "idempotent": True}
                raise TradeAttributionConflictError("交易已有冲突的 origin resolution")
            saved = origin_store.write(db_path=_origin_path(), record=record)
            return {"record": saved, "idempotent": False}
    except origin_store.TradeOriginStoreConflictError as exc:
        raise TradeAttributionConflictError(str(exc)) from exc


def reconciliation_for_trade(trade_id: str) -> dict[str, Any]:
    trade = _trade(trade_id)
    # N/A is derived from the authoritative Trade Ledger execution state and
    # must not be downgraded by an unrelated attribution-ledger failure.
    if trade.get("voided_at") is not None or trade.get("execution_status") == "not_executed":
        result = reconciliation.project_trade_campaign_reconciliation(
            as_of=_now(), policy_version=reconciliation.POLICY_VERSION_V01,
            trade=trade, attribution_records=[], attribution_coverage="NOT_EVALUATED",
            attribution_coverage_authority_refs=["trade_ledger:execution_state"],
            trade_authority_refs=[f"trade_ledger:trade:{trade_id}"],
        )
        result["origin"] = None
        result["pre_trade_decision"] = None
        result["pre_trade_thesis"] = None
        return result
    try:
        origin = origin_store.get_for_trade(db_path=_origin_path(), trade_id=trade_id)
        attribution = attribution_store.get_attribution_for_trade(db_path=_attribution_path(), trade_id=trade_id)
    except (origin_store.TradeOriginStoreError, attribution_store.FormalTradeAttributionStoreError) as exc:
        return _resolution_error(trade, trade_id, "TRADE_RESOLUTION_STORE_ERROR", str(exc))
    if origin is not None and attribution is not None:
        return _resolution_error(
            trade,
            trade_id,
            "CONFLICTING_TRADE_RESOLUTION_AUTHORITIES",
            "UNPLANNED 与 Formal Attribution 同时存在",
        )
    if origin is not None:
        return {
            "schema_version": "trade_origin_reconciliation.v0.1",
            "authority_ref": "tar1:trade_origin_resolution:v0.1",
            "trade_id": trade_id,
            "security_code": trade["code"],
            "execution_status": trade["execution_status"],
            "allocation_state": "UNPLANNED",
            "reconciliation_requirement": "NOT_REQUIRED",
            "attribution_coverage": "COMPLETE",
            "campaign_id": None,
            "decision_id": None,
            "attribution_id": None,
            "origin": "UNPLANNED",
            "pre_trade_decision": "NONE",
            "pre_trade_thesis": "NONE",
            "origin_resolution_id": origin["resolution_id"],
            "authority_refs": ["tar1:trade_origin_resolution:v0.1", origin["resolution_id"]],
            "reason_codes": ["EXPLICIT_UNPLANNED"],
        }
    try:
        result = reconciliation.project_trade_campaign_reconciliation(
            as_of=_now(), policy_version=reconciliation.POLICY_VERSION_V01,
            trade=trade, attribution_records=[] if attribution is None else [attribution], attribution_coverage="COMPLETE",
            attribution_coverage_authority_refs=["formal_trade_attribution_store:per_trade_exact_lookup"],
            trade_authority_refs=[f"trade_ledger:trade:{trade_id}"],
        )
        result["origin"] = None
        result["pre_trade_decision"] = None
        result["pre_trade_thesis"] = None
        return result
    except reconciliation.TradeCampaignReconciliationError as exc:
        return _resolution_error(trade, trade_id, "TRADE_RESOLUTION_VALIDATION_ERROR", str(exc))


def _resolution_error(trade: dict[str, Any], trade_id: str, reason: str, detail: str) -> dict[str, Any]:
    return {
        "schema_version": reconciliation.SCHEMA_VERSION,
        "authority_ref": reconciliation.AUTHORITY_REF,
        "trade_id": trade_id,
        "security_code": trade["code"],
        "execution_status": trade["execution_status"],
        "allocation_state": "ERROR",
        "reconciliation_requirement": "ERROR",
        "attribution_coverage": "ERROR",
        "campaign_id": None, "decision_id": None, "attribution_id": None,
        "origin": None, "pre_trade_decision": None, "pre_trade_thesis": None,
        "reason_codes": [reason],
        "authority_refs": [reconciliation.AUTHORITY_REF, f"trade_resolution:{reason}"],
        "error": detail,
    }
