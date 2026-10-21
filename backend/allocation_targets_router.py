"""Bounded private target edits and cached read-only comparison."""
from fastapi import APIRouter, HTTPException
import allocation_targets as service
router = APIRouter(prefix='/api/portfolio/allocation-targets', tags=['allocation-targets'])

@router.get('')
def read():
    try: return {'data': service.current()}
    except Exception: raise HTTPException(503, '配置归档不可读取，请稍后重试') from None

@router.put('')
def save(body: service.TargetInput):
    try: return {'data': service.save(body)}
    except LookupError: raise HTTPException(409, '目标已变化，请刷新后重试；未覆盖其他版本') from None
    except ValueError: raise HTTPException(422, '目标配置无效或历史版本已达上限') from None
    except Exception: raise HTTPException(503, '目标保存失败，请重试') from None
