"""HTTP surface for factual Evidence temporal intake and derived readback."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

import evidence_effective_time_authority as authority
import evidence_thesis_service as evidence_service
import evidence_thesis_store as evidence_store

router = APIRouter(prefix="/api", tags=["evidence-temporal-authority"])


class TemporalIntakeIn(BaseModel):
    """Factual source/event metadata only.

    Derived fields such as effective_at, temporal_state, authority_refs,
    evaluation, EC1 state, and NEW_AFTER_DECISION are deliberately absent and
    rejected by ``extra='forbid'``.
    """

    model_config = ConfigDict(extra="forbid")

    source_identity: str | None = None
    event_identity: str | None = None
    source_published_at: str | None = None
    event_occurred_at: str | None = None
    observed_at: str | None = None
    created_at: str | None = None
    ingested_at: str | None = None


def _db_path():
    return evidence_service.resolve_db_path()


def _raise_error(exc: Exception) -> None:
    if isinstance(exc, authority.TemporalAuthorityError):
        raise HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, authority.TemporalAuthorityCorruptedError):
        raise HTTPException(status_code=500, detail="Evidence temporal authority 数据损坏，已停止读写")
    if isinstance(exc, evidence_store.EvidenceLedgerSchemaVersionError):
        raise HTTPException(status_code=500, detail=evidence_store.EvidenceLedgerSchemaVersionError.MESSAGE)
    if isinstance(exc, evidence_store.EvidenceLedgerCorruptedError):
        raise HTTPException(status_code=500, detail=evidence_store.EvidenceLedgerCorruptedError.MESSAGE)
    raise HTTPException(status_code=500, detail="Evidence temporal authority 查询失败")


@router.post("/evidence/{evidence_id}/temporal-authority")
def record_temporal_authority(evidence_id: str, body: TemporalIntakeIn):
    try:
        intake = authority.TemporalIntake(evidence_id=evidence_id, **body.model_dump())
        authority.record_temporal_intake(intake, db_path=_db_path())
        result = authority.get_temporal_authority(evidence_id, db_path=_db_path())
        if result is None:
            raise HTTPException(status_code=404, detail=f"证据 {evidence_id} 不存在")
        return {"data": result.to_dict()}
    except HTTPException:
        raise
    except Exception as exc:
        _raise_error(exc)


@router.get("/evidence/{evidence_id}/temporal-authority")
def get_temporal_authority(
    evidence_id: str,
    evaluation_as_of: str | None = Query(None),
):
    try:
        result = authority.get_temporal_authority(
            evidence_id,
            db_path=_db_path(),
            evaluation_as_of=evaluation_as_of,
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"证据 {evidence_id} 不存在")
        return {"data": result.to_dict()}
    except HTTPException:
        raise
    except Exception as exc:
        _raise_error(exc)
