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


def _params(request, expected):
    if set(request.query_params)!=set(expected) or any(len(request.query_params.getlist(k))!=1 for k in expected):
        raise HTTPException(422, '查询字段必须精确匹配，不接受URL、路径或采集参数')


@router.get('/market-context')
def get_market_context(request: Request, as_of: str = Query(...)):
    _params(request, ['as_of'])
    from public_research_extended_service import market_context
    try: return {'data':market_context(as_of)}
    except (ValueError,TypeError): raise HTTPException(422, '无效的研究截止日期') from None


@router.get('/company-inputs')
def get_company_inputs(request: Request, market: str = Query(...), symbol: str = Query(...), as_of: str = Query(...)):
    _params(request,['market','symbol','as_of'])
    from public_research_extended_service import company_inputs
    try: return {'data':company_inputs(market,symbol,as_of)}
    except (ValueError,TypeError): raise HTTPException(422, '无效的市场、证券或研究截止日期') from None
