"""Bounded local document registration and read-only comparison."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import filing_evidence as svc

router = APIRouter(prefix='/api/filing-evidence', tags=['filing-evidence'])


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_edit_token: str = Field(max_length=100)
    source_identity: str = Field(min_length=1, max_length=300)
    revision: str = Field(min_length=1, max_length=300)
    source_title: str = Field(min_length=1, max_length=300)
    source_date: str | None = Field(default=None, max_length=10)
    source_url: str | None = Field(default=None, max_length=2000)
    form: str = Field(max_length=20)
    text: str = Field(min_length=1, max_length=svc.MAX_TEXT)
    corrects_id: str | None = Field(default=None, max_length=100)


class CompareIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    before_id: str = Field(max_length=100)
    after_id: str = Field(max_length=100)
    section: str = Field(max_length=100)


def call(fn):
    try:
        return {'data': fn()}
    except svc.Conflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else '证据不存在') from None
    except Exception:
        raise HTTPException(503, '本地文档暂不可用，请稍后重试') from None


@router.get('/context/{evidence_id}')
def context(evidence_id: str):
    return call(lambda: svc.context(evidence_id))


@router.post('/documents/{evidence_id}')
def register(evidence_id: str, payload: DocumentIn):
    return call(lambda: svc.register(evidence_id, payload.model_dump()))


@router.post('/compare')
def compare(payload: CompareIn):
    return call(lambda: svc.compare(payload.model_dump()))


@router.get('/documents/{document_id}')
def document(document_id: str):
    return call(lambda: svc.document(document_id))
