"""Archive-only public research API under the existing local session boundary."""
from fastapi import APIRouter, HTTPException, Query, Request
from public_research_archive import query_source

router = APIRouter(prefix='/api/public-research', tags=['public-research'])


@router.get('')
def get_public_research(request: Request, source_id: str = Query(...)):
    if set(request.query_params) != {'source_id'} or len(request.query_params.getlist('source_id')) != 1:
        raise HTTPException(422, '仅接受一个source_id，不接受路径、URL或采集参数')
    try:
        return {'data': query_source(source_id)}
    except ValueError:
        raise HTTPException(422, '不支持的公开数据源') from None
