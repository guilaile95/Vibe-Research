"""Archive-only research GET under the existing application's API boundary."""
from fastapi import APIRouter, HTTPException, Query, Request
from short_term_theme_research_service import query_theme_research

router = APIRouter(prefix='/api/market/theme-research', tags=['theme-research'])


@router.get('')
def theme_research(request: Request, trade_date: str = Query(...)):
    if set(request.query_params) != {'trade_date'} or len(request.query_params.getlist('trade_date')) != 1:
        raise HTTPException(status_code=422, detail='仅允许一个 trade_date 参数')
    try:
        return {'data': query_theme_research(trade_date)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
