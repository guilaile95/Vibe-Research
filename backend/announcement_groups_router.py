"""Manual relationship registration only; GET never creates groups."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import announcement_groups as svc
router = APIRouter(prefix='/api/announcement-groups', tags=['announcement-groups'])

class Member(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence_id: str = Field(min_length=1, max_length=100)
    expected_edit_token: str = Field(min_length=1, max_length=100)
    role: Literal['original', 'commentary', 'unknown', 'correction', 'amendment']
    relates_to: str | None = Field(default=None, max_length=100)

class GroupIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=100)
    group_id: str | None = Field(default=None, max_length=150)
    anchor_id: str = Field(min_length=1, max_length=100)
    period: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0)
    members: list[Member] = Field(min_length=2, max_length=50)

def call(fn):
    try:
        return {'data': fn()}
    except svc.Conflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else '证据不存在') from None
    except Exception:
        raise HTTPException(503, '分组暂不可用，请刷新核对保存状态后重试') from None

@router.get('/context/{evidence_id}')
def context(evidence_id: str):
    return call(lambda: svc.context(evidence_id))

@router.post('')
def save(payload: GroupIn):
    return call(lambda: svc.save(payload.model_dump()))
