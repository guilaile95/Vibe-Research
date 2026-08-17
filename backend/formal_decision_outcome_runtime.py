"""OL1 runtime authority: Frozen Decision + TAR1 + Trade Ledger only.

The runtime performs I/O and assembles exact inputs.  The pure OL1 projection
in ``formal_decision_outcome`` owns state transitions and the two-pass contract.
No legacy advice analytics or feedback row is treated as Formal Outcome.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

import formal_decision_outcome as domain
import formal_trade_attribution as fta
import formal_trade_attribution_store as attribution_store
import campaign_critical_data_runtime as critical_data_runtime
import frozen_decision_service
import performance_attribution_service
import security_price_point_authority as price_point_authority
from security_exchange_policy import POLICY_VERSION_V01 as SER_POLICY_VERSION
import trade_ledger_service
import trade_ledger_store
import trade_origin_store


_DECISION_ID_RE = re.compile(r"^decision_[0-9a-f]{32}$")
_PAGE_SIZE = 500
_SAFETY_BOUND = 10_000


class FormalOutcomeRuntimeError(RuntimeError):
    """A formal outcome cannot be truthfully assembled."""


class FormalOutcomeNotFoundError(FormalOutcomeRuntimeError, LookupError):
    pass


class FormalOutcomeValidationError(FormalOutcomeRuntimeError, ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _require_decision_id(value: object) -> str:
    if not isinstance(value, str) or not _DECISION_ID_RE.fullmatch(value):
        raise FormalOutcomeValidationError("decision_id 格式不合法")
    return value


def _load_decision(decision_id: str) -> dict[str, Any]:
    try:
        decision = frozen_decision_service.get_decision(decision_id)
    except Exception as exc:
        raise FormalOutcomeRuntimeError("Frozen Decision authority 读取失败") from exc
    if decision is None:
        raise FormalOutcomeNotFoundError("Frozen Decision 不存在")
    try:
        fta.verify_frozen_decision_witness(decision)
    except Exception as exc:
        raise FormalOutcomeRuntimeError("Frozen Decision witness 校验失败") from exc
    return decision


def _load_attributions(decision_id: str) -> list[dict[str, Any]]:
    db_path = attribution_store.resolve_formal_trade_attribution_db_path()
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < _SAFETY_BOUND:
        page = attribution_store.list_attributions(
            db_path=db_path,
            decision_id=decision_id,
            limit=_PAGE_SIZE,
            offset=offset,
        )
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            return rows
        offset += len(page)
    raise FormalOutcomeRuntimeError("Formal Attribution 分页超过安全上限")


def _load_trade_rows(
    decision: dict[str, Any],
    attributions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    trade_db_path = trade_ledger_service.resolve_db_path()
    origin_db_path = trade_origin_store.resolve_db_path()
    rows: list[dict[str, Any]] = []
    for attribution in attributions:
        trade_id = attribution["trade_id"]
        try:
            trade = trade_ledger_store.get_record(trade_db_path, trade_id)
        except Exception as exc:
            raise FormalOutcomeRuntimeError("Trade Ledger authority 读取失败") from exc
        if trade is None:
            raise FormalOutcomeRuntimeError(
                "Formal Attribution 引用的 Trade Ledger row 不存在"
            )
        if trade.get("voided_at") is None:
            try:
                expected = fta.create_attribution(
                    decision,
                    trade,
                    attribution_id=attribution["attribution_id"],
                    created_at=attribution["created_at"],
                ).to_dict()
            except Exception as exc:
                raise FormalOutcomeRuntimeError(
                    "Formal Attribution 与当前 Trade Ledger 不一致"
                ) from exc
            if expected != attribution:
                raise FormalOutcomeRuntimeError(
                    "Formal Attribution witness 与 Trade Ledger 不一致"
                )
        try:
            origin = trade_origin_store.get_for_trade(
                db_path=origin_db_path,
                trade_id=trade_id,
            )
        except Exception as exc:
            raise FormalOutcomeRuntimeError("Trade origin authority 读取失败") from exc
        if origin is not None:
            raise FormalOutcomeRuntimeError(
                "同一 Trade 同时存在 Formal Attribution 与 UNPLANNED authority"
            )
        rows.append(trade)
    return rows


def _unavailable_price_point(
    *,
    security_code: str,
    as_of: str,
    state: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": price_point_authority.SCHEMA_VERSION,
        "state": state,
        "security_code": security_code,
        "exchange": None,
        "provider_alias": None,
        "as_of": as_of,
        "trade_date": None,
        "close": None,
        "publication_id": None,
        "source_observation_id": None,
        "observation_fetched_at": None,
        "authority_refs": [],
        "reason_codes": [reason],
    }


def _build_counterfactual(
    decision: dict[str, Any],
    *,
    evaluation_as_of: str,
) -> dict[str, Any]:
    """Build CF1 from production Fact Lake authority, never caller fields."""
    anchor = fta.verify_frozen_decision_witness(decision)
    security_code = anchor["security_code"]
    start_as_of = anchor["decision_committed_at"]
    try:
        lake = critical_data_runtime.production_lake_provider()
    except Exception:
        lake = None
        start = _unavailable_price_point(
            security_code=security_code,
            as_of=start_as_of,
            state="ERROR",
            reason="FACT_LAKE_AUTHORITY_ERROR",
        )
        end = _unavailable_price_point(
            security_code=security_code,
            as_of=evaluation_as_of,
            state="ERROR",
            reason="FACT_LAKE_AUTHORITY_ERROR",
        )
        return domain.build_security_close_to_close_counterfactual(start, end)
    if lake is None:
        start = _unavailable_price_point(
            security_code=security_code,
            as_of=start_as_of,
            state="NOT_EVALUATED",
            reason="FACT_LAKE_UNAVAILABLE",
        )
        end = _unavailable_price_point(
            security_code=security_code,
            as_of=evaluation_as_of,
            state="NOT_EVALUATED",
            reason="FACT_LAKE_UNAVAILABLE",
        )
        return domain.build_security_close_to_close_counterfactual(start, end)
    try:
        start = price_point_authority.resolve_authoritative_price_point(
            lake=lake,
            security_code=security_code,
            as_of=start_as_of,
            security_exchange_policy_version=SER_POLICY_VERSION,
        )
        end = price_point_authority.resolve_authoritative_price_point(
            lake=lake,
            security_code=security_code,
            as_of=evaluation_as_of,
            security_exchange_policy_version=SER_POLICY_VERSION,
        )
    except price_point_authority.PricePointAuthorityError:
        start = _unavailable_price_point(
            security_code=security_code,
            as_of=start_as_of,
            state="ERROR",
            reason="PRICE_POINT_AUTHORITY_INPUT_ERROR",
        )
        end = _unavailable_price_point(
            security_code=security_code,
            as_of=evaluation_as_of,
            state="ERROR",
            reason="PRICE_POINT_AUTHORITY_INPUT_ERROR",
        )
    return domain.build_security_close_to_close_counterfactual(start, end)


def evaluate_outcome(
    decision_id: str,
    *,
    evaluation_as_of: str | None = None,
) -> dict[str, Any]:
    """Evaluate one exact Frozen Decision at a server-owned UTC boundary."""
    decision_id = _require_decision_id(decision_id)
    decision = _load_decision(decision_id)
    as_of = evaluation_as_of or _now()
    try:
        replay = domain.build_decision_time_replay(decision)
        # The pure projection owns the committed_at/review_by gates.  Avoid
        # loading later facts before the NOT_DUE branch to preserve two-pass
        # semantics and reduce accidental hindsight access.
        anchor = fta.verify_frozen_decision_witness(decision)
        evaluation = fta.to_canonical_utc(as_of, "evaluation_as_of")
        if fta.parse_utc_instant(evaluation, "evaluation_as_of") < fta.parse_utc_instant(
            anchor["decision_committed_at"], "decision.committed_at"
        ):
            raise domain.OutcomeValidationError(
                "evaluation_as_of 不得早于 Frozen Decision committed_at"
            )
        if fta.parse_utc_instant(evaluation, "evaluation_as_of") < fta.parse_utc_instant(
            anchor["decision_review_by"], "decision.review_by"
        ):
            return domain.project_ol1_outcome(
                decision,
                evaluation_as_of=evaluation,
                attributions=[],
                trades=[],
            )

        attributions = _load_attributions(decision_id)
        trades = _load_trade_rows(decision, attributions)
        trade_db_path = trade_ledger_service.resolve_db_path()
        executed_ids = [
            attribution["trade_id"]
            for attribution in attributions
            if attribution["trade_execution_status"] in ("full", "partial")
            and next(
                trade for trade in trades
                if trade["trade_id"] == attribution["trade_id"]
            ).get("voided_at") is None
        ]
        performance = None
        if executed_ids:
            try:
                performance = performance_attribution_service.compute_attribution_for_trade_ids(
                    executed_ids,
                    trade_db_path=trade_db_path,
                )
            except performance_attribution_service.PerformanceAttributionProvenanceError as exc:
                raise FormalOutcomeRuntimeError(
                    "精确交易集的 canonical P&L 无法证明"
                ) from exc
        counterfactual = _build_counterfactual(
            decision,
            evaluation_as_of=evaluation,
        )
        result = domain.project_ol1_outcome(
            decision,
            evaluation_as_of=evaluation,
            attributions=attributions,
            trades=trades,
            actual_performance=performance,
            counterfactual=counterfactual,
        )
        result["decision_time_replay"] = replay
        return result
    except domain.OutcomeValidationError as exc:
        raise FormalOutcomeValidationError(str(exc)) from exc
    except FormalOutcomeRuntimeError:
        raise
    except Exception as exc:
        raise FormalOutcomeRuntimeError("Formal Outcome evaluation failed") from exc


def _error_projection(decision: dict[str, Any], error: Exception) -> dict[str, Any]:
    try:
        anchor = fta.verify_frozen_decision_witness(decision)
        replay = domain.build_decision_time_replay(decision)
        return {
            "schema_version": domain.OL1_SCHEMA_VERSION,
            **anchor,
            "outcome_status": "ERROR",
            "due_state": "ERROR",
            "evaluation_as_of": None,
            "decision_time_replay": replay,
            "replay_future_fact_leak": False,
            "outcome_reveal": None,
            "actual_capital_outcome": {
                "state": "ERROR",
                "pnl_state": "NOT_EVALUATED",
                "trade_count": 0,
                "trade_ids": [],
                "pnl": None,
                "authority_refs": ["ol1:runtime"],
                "reason_codes": ["FORMAL_OUTCOME_ERROR"],
            },
            "counterfactual_outcome": {
                "state": "ERROR",
                "authority_refs": ["ol1:runtime"],
                "reason_codes": ["FORMAL_OUTCOME_ERROR"],
            },
            "process_quality": {
                "state": domain.PROCESS_QUALITY_STATE,
                "reason_codes": ["NO_PROCESS_QUALITY_AUTHORITY"],
            },
            "reason_codes": ["FORMAL_OUTCOME_ERROR"],
            "error_code": type(error).__name__,
        }
    except Exception:
        return {
            "schema_version": domain.OL1_SCHEMA_VERSION,
            "decision_id": decision.get("decision_id"),
            "outcome_status": "ERROR",
            "reason_codes": ["FORMAL_OUTCOME_ERROR"],
        }


def list_outcomes(
    *,
    evaluation_as_of: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or isinstance(offset, bool) or limit < 1 or limit > 100:
        raise FormalOutcomeValidationError("limit 必须在 1..100")
    if offset < 0:
        raise FormalOutcomeValidationError("offset 不得为负")
    as_of = evaluation_as_of or _now()
    try:
        decisions = frozen_decision_service.list_decisions(
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise FormalOutcomeRuntimeError("Frozen Decision list authority 读取失败") from exc
    results = []
    for decision in decisions:
        try:
            results.append(
                evaluate_outcome(
                    decision["decision_id"],
                    evaluation_as_of=as_of,
                )
            )
        except (FormalOutcomeRuntimeError, FormalOutcomeValidationError) as exc:
            results.append(_error_projection(decision, exc))
    return results


__all__ = [
    "FormalOutcomeNotFoundError",
    "FormalOutcomeRuntimeError",
    "FormalOutcomeValidationError",
    "evaluate_outcome",
    "list_outcomes",
]
