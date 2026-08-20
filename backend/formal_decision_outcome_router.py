"""OL1 Formal Decision Outcome API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import formal_decision_outcome_runtime as runtime


router = APIRouter(tags=["formal-decision-outcome"])


def _raise(exc: Exception) -> None:
    if isinstance(exc, runtime.FormalOutcomeNotFoundError):
        raise HTTPException(status_code=404, detail="Frozen Decision 不存在") from exc
    if isinstance(exc, runtime.FormalOutcomeValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(
        status_code=500,
        detail="Formal Decision Outcome authority unavailable",
    ) from exc


@router.get("/api/formal-decisions/{decision_id}/outcome")
def get_formal_decision_outcome(
    decision_id: str,
    evaluation_as_of: str | None = Query(None),
):
    try:
        return {
            "data": runtime.evaluate_outcome(
                decision_id,
                evaluation_as_of=evaluation_as_of,
            )
        }
    except Exception as exc:
        _raise(exc)


@router.get("/api/formal-decision-review-worklist")
def get_formal_decision_review_worklist():
    try:
        return {"data": runtime.build_review_worklist()}
    except Exception as exc:
        _raise(exc)


@router.get("/api/formal-decision-outcomes")
def list_formal_decision_outcomes(
    evaluation_as_of: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        return {
            "data": runtime.list_outcomes(
                evaluation_as_of=evaluation_as_of,
                limit=limit,
                offset=offset,
            )
        }
    except Exception as exc:
        _raise(exc)
