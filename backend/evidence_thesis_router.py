"""投资逻辑与证据账本 API 路由。

通过 app.include_router(evidence_thesis_router) 接入 app.py。
不修改现有路由。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import evidence_thesis_service as svc
import evidence_thesis_store as store

router = APIRouter(prefix="/api", tags=["evidence-thesis"])


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------

class EvidenceCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_type: str
    subject_id: str
    evidence_type: str
    claim: str
    source_title: str
    source_url: str | None = None
    source_date: str | None = None
    accessed_at: str
    classification: str
    confidence: str


class EvidenceUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_type: str
    claim: str
    source_title: str
    source_url: str | None = None
    source_date: str | None = None
    accessed_at: str
    classification: str
    confidence: str


class ThesisCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_type: str
    subject_id: str
    title: str
    summary: str
    core_claims: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    change_summary: str | None = None


class ThesisUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    summary: str
    status: str = "active"
    core_claims: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    expected_revision: int
    change_summary: str | None = None


class ThesisArchiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    change_summary: str | None = None


class LinkEvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    stance: str
    expected_revision: int
    change_summary: str | None = None


class UpdateStanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stance: str
    expected_revision: int
    change_summary: str | None = None


class UnlinkEvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    change_summary: str | None = None


# ---------------------------------------------------------------------------
# 异常转换
# ---------------------------------------------------------------------------

def _raise_service_error(e: Exception):
    """将服务层异常转换为 HTTP 异常并 raise。"""
    if isinstance(e, svc.ValidationError):
        raise HTTPException(status_code=422, detail=str(e))
    if isinstance(e, svc.EvidenceNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, svc.ThesisNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, svc.ArchivedThesisError):
        raise HTTPException(status_code=409, detail="已归档的投资逻辑不可修改")
    if isinstance(e, svc.RevisionConflictError):
        # 409 响应：detail + current_revision 顶层字段（非标准 HTTPException.detail）
        raise RevisionConflictHTTPException(
            message="投资逻辑已发生变化，请重新加载后重试",
            current_revision=e.current_revision,
        )
    if isinstance(e, svc.SubjectMismatchError):
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(e, store.EvidenceLedgerCorruptedError):
        raise HTTPException(status_code=500, detail=store.EvidenceLedgerCorruptedError.MESSAGE)
    raise HTTPException(status_code=500, detail="内部错误")


class RevisionConflictHTTPException(Exception):
    """409 响应：body = {"detail": ..., "current_revision": ...}（顶层 current_revision）。

    不继承 HTTPException，避免 FastAPI 默认 handler 把 dict 再包一层 detail。
    由 app.py 中注册的 exception_handler 统一处理。
    """

    def __init__(self, message: str, current_revision: int | None):
        self.message = message
        self.current_revision = current_revision
        super().__init__(message)


def _resolve_db():
    return svc.resolve_db_path()


# ---------------------------------------------------------------------------
# Evidence 路由
# ---------------------------------------------------------------------------

@router.get("/evidence")
def list_evidence(
    subject_type: str | None = Query(None),
    subject_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = _resolve_db()
    try:
        return {"data": svc.list_evidence(db, subject_type, subject_id, limit, offset)}
    except Exception as e:
        _raise_service_error(e)


@router.post("/evidence")
def create_evidence(body: EvidenceCreateIn):
    db = _resolve_db()
    try:
        result = svc.create_evidence(db, body.model_dump())
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str):
    db = _resolve_db()
    try:
        result = svc.get_evidence(db, evidence_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"证据 {evidence_id} 不存在")
        return {"data": result}
    except HTTPException:
        raise
    except Exception as e:
        _raise_service_error(e)


@router.put("/evidence/{evidence_id}")
def update_evidence(evidence_id: str, body: EvidenceUpdateIn):
    db = _resolve_db()
    try:
        result = svc.update_evidence(db, evidence_id, body.model_dump())
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)


@router.delete("/evidence/{evidence_id}")
def delete_evidence(evidence_id: str, confirm: bool = Query(False)):
    if not confirm:
        raise HTTPException(status_code=400, detail="删除操作需要 confirm=true 确认")
    db = _resolve_db()
    try:
        result = svc.soft_delete_evidence(db, evidence_id)
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)


# ---------------------------------------------------------------------------
# Thesis 路由
# ---------------------------------------------------------------------------

@router.get("/thesis")
def list_thesis(
    subject_type: str | None = Query(None),
    subject_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = _resolve_db()
    try:
        return {"data": svc.list_thesis(db, subject_type, subject_id, status, limit, offset)}
    except Exception as e:
        _raise_service_error(e)


@router.post("/thesis")
def create_thesis(body: ThesisCreateIn):
    db = _resolve_db()
    try:
        result = svc.create_thesis(db, body.model_dump())
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)


@router.get("/thesis/{thesis_id}")
def get_thesis(thesis_id: str):
    db = _resolve_db()
    try:
        result = svc.get_thesis(db, thesis_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"投资逻辑 {thesis_id} 不存在")
        return {"data": result}
    except HTTPException:
        raise
    except Exception as e:
        _raise_service_error(e)


@router.put("/thesis/{thesis_id}")
def update_thesis(thesis_id: str, body: ThesisUpdateIn):
    db = _resolve_db()
    try:
        result = svc.update_thesis(db, thesis_id, body.model_dump(), body.expected_revision)
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)


@router.delete("/thesis/{thesis_id}")
def delete_thesis(
    thesis_id: str,
    confirm: bool = Query(False),
    expected_revision: int = Query(...),
    change_summary: str | None = Query(None),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="归档操作需要 confirm=true 确认")
    db = _resolve_db()
    try:
        result = svc.archive_thesis(db, thesis_id, expected_revision, change_summary)
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)


# ---------------------------------------------------------------------------
# Revision 路由
# ---------------------------------------------------------------------------

@router.get("/thesis/{thesis_id}/revisions")
def list_revisions(thesis_id: str):
    db = _resolve_db()
    try:
        result = svc.list_revisions(db, thesis_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"投资逻辑 {thesis_id} 不存在")
        return {"data": result}
    except HTTPException:
        raise
    except Exception as e:
        _raise_service_error(e)


@router.get("/thesis/{thesis_id}/revisions/{revision_number}")
def get_revision(thesis_id: str, revision_number: int):
    db = _resolve_db()
    try:
        result = svc.get_revision(db, thesis_id, revision_number)
        if result is None:
            raise HTTPException(status_code=404, detail="版本不存在")
        return {"data": result}
    except HTTPException:
        raise
    except Exception as e:
        _raise_service_error(e)


@router.get("/thesis/{thesis_id}/diff")
def diff_revisions(
    thesis_id: str,
    from_rev: int = Query(..., alias="from", ge=1),
    to_rev: int = Query(..., alias="to", ge=1),
):
    db = _resolve_db()
    try:
        result = svc.diff_revisions(db, thesis_id, from_rev, to_rev)
        if result is None:
            raise HTTPException(status_code=404, detail="投资逻辑或版本不存在")
        return {"data": result}
    except HTTPException:
        raise
    except Exception as e:
        _raise_service_error(e)


# ---------------------------------------------------------------------------
# 证据关联路由
# ---------------------------------------------------------------------------

@router.post("/thesis/{thesis_id}/evidence")
def link_evidence(thesis_id: str, body: LinkEvidenceIn):
    db = _resolve_db()
    try:
        result = svc.link_evidence(
            db, thesis_id, body.evidence_id, body.stance,
            body.expected_revision, body.change_summary,
        )
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)


@router.put("/thesis/{thesis_id}/evidence/{evidence_id}")
def update_stance(thesis_id: str, evidence_id: str, body: UpdateStanceIn):
    db = _resolve_db()
    try:
        result = svc.update_stance(
            db, thesis_id, evidence_id, body.stance,
            body.expected_revision, body.change_summary,
        )
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)


@router.delete("/thesis/{thesis_id}/evidence/{evidence_id}")
def unlink_evidence(
    thesis_id: str,
    evidence_id: str,
    expected_revision: int = Query(...),
    change_summary: str | None = Query(None),
):
    db = _resolve_db()
    try:
        result = svc.unlink_evidence(
            db, thesis_id, evidence_id, expected_revision, change_summary,
        )
        return {"data": result}
    except Exception as e:
        _raise_service_error(e)
