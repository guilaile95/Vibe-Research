"""Local-only persisted manual annotations, append/read only."""
from fastapi import APIRouter, HTTPException, Response
import research_annotations as annotations

router = APIRouter(prefix='/api/research-annotations', tags=['research-annotations'])


def guarded(fn, response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return fn()
    except (ValueError, annotations.store.StoreError):
        raise HTTPException(422, '标注无法核对；请重新读取日 K 线并检查日期、关联记录或归档状态。原记录已保留。') from None


@router.get('')
def listing(code: str, response: Response):
    return guarded(lambda: {'records': annotations.records(code), 'limit': annotations.LIMIT}, response)


@router.post('')
def create(body: annotations.AnnotationInput, response: Response):
    return guarded(lambda: annotations.create(body), response)
