"""数据健康中心只读 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

import data_health_adapters as adapters
import data_health_service as svc

router = APIRouter(prefix="/api", tags=["data-health"])

_SERVICE_UNAVAILABLE_DETAIL = "数据健康服务暂不可用"


def _parse_bool_param(name: str, raw: str | None) -> bool | None:
    """仅接受字面量 true/false（大小写不敏感）；1/0/yes/no/空串等一律 422。"""
    if raw is None:
        return None
    v = raw.strip()
    if v == "true":
        return True
    if v == "false":
        return False
    raise HTTPException(status_code=422, detail=f"非法参数 {name}")


def _extract_single_query(request: Request, name: str) -> str | None:
    """仅允许单个精确值；重复或逗号分隔 → 422。"""
    values = request.query_params.getlist(name)
    if not values:
        return None
    if len(values) > 1:
        raise HTTPException(status_code=422, detail=f"参数 {name} 仅允许单个值")
    val = values[0]
    if val is None:
        return None
    if "," in val:
        raise HTTPException(status_code=422, detail=f"参数 {name} 不支持逗号分隔")
    return val


@router.get("/data-health")
def get_data_health(request: Request) -> dict[str, Any]:
    """聚合 11 个来源的健康状态。筛选只影响 items，不改变 overall/summary/gate。"""
    try:
        module = _extract_single_query(request, "module")
        status_raw = _extract_single_query(request, "status")
        is_stale_raw = _extract_single_query(request, "is_stale")
        blocks_raw = _extract_single_query(request, "blocks_advice")

        if module is not None and module not in svc.REGISTERED_MODULES:
            raise HTTPException(status_code=422, detail="未知 module")
        status_filter: str | None = None
        if status_raw is not None:
            if status_raw not in svc.VALID_STATUSES:
                raise HTTPException(status_code=422, detail="非法 status")
            status_filter = status_raw
        is_stale_filter = _parse_bool_param("is_stale", is_stale_raw)
        blocks_filter = _parse_bool_param("blocks_advice", blocks_raw)

        overview = adapters.get_health_overview()
        items = list(overview["items"])
        filtered = items
        if module is not None:
            filtered = [it for it in filtered if it.get("module") == module]
        if status_filter is not None:
            filtered = [it for it in filtered if it.get("status") == status_filter]
        if is_stale_filter is not None:
            filtered = [it for it in filtered if bool(it.get("is_stale")) is is_stale_filter]
        if blocks_filter is not None:
            filtered = [it for it in filtered if bool(it.get("blocks_advice")) is blocks_filter]

        return {
            "data": {
                "overall_status": overview["overall_status"],
                "blocks_advice": overview["blocks_advice"],
                "block_reasons": overview["block_reasons"],
                "summary": overview["summary"],
                "items": filtered,
            }
        }
    except HTTPException:
        raise
    except Exception:
        # 注册表、聚合框架或序列化错误 → 500
        raise HTTPException(status_code=500, detail=_SERVICE_UNAVAILABLE_DETAIL) from None


@router.get("/data-health/{source_id}")
def get_data_health_source(source_id: str) -> dict[str, Any]:
    try:
        if source_id not in svc.REGISTERED_SOURCE_IDS:
            raise HTTPException(status_code=404, detail="未知数据来源")
        detail = adapters.get_source_detail(source_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="未知数据来源")
        return {"data": detail}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=_SERVICE_UNAVAILABLE_DETAIL) from None
