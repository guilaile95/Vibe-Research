"""Native Intel API（NATIVE-INTEL1）—— Vibe 自有资讯能力的唯一读写入口。

不需要任何 sidecar、MCP 或外部 URL 配置。

HTTP 语义：能被如实回答的状态（unavailable / partial / stale）都返回 200 + 显式
status 字段，前端按 status 渲染；只有输入非法返回 422。
"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import native_intel_service as service

router = APIRouter(prefix="/api/native-intel", tags=["native-intel"])

_CODE_RE = re.compile(r"^\d{6}$")


def _db_path() -> str | None:
    value = os.environ.get("VIBE_NATIVE_INTEL_DB", "").strip()
    return value or None


@router.get("/status")
def get_status() -> dict[str, Any]:
    """Native Intel 运行状态：存储 / 最近抓取 / 来源健康 / 目录 / 调度器。"""
    return service.status(_db_path())


@router.get("/items")
def get_items(
    hint: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    include: str | None = Query(default=None, description="逗号分隔，标题或摘要需包含"),
    exclude: str | None = Query(default=None, description="逗号分隔，标题与摘要需排除"),
    search: str | None = Query(default=None),
    since: str | None = Query(default=None, description="ISO8601，按末见时间过滤"),
    until: str | None = Query(default=None),
    order_by: str = Query(default="last_seen", pattern="^(last_seen|first_seen|published)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """统一条目查询（include / exclude / search / 赛道 / 来源 / 时间窗）。"""
    try:
        rows, total = service.store.query_items(
            _db_path(),
            hint=hint,
            source_id=source_id,
            include=_split_terms(include),
            exclude=_split_terms(exclude),
            search=(search or "").strip() or None,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
            order_by=order_by,
        )
    except service.store.NativeIntelStoreError as exc:
        return {
            "status": service.STATUS_UNAVAILABLE,
            "error": str(exc),
            "items": [],
            "total": 0,
        }
    plane = service.data_status(_db_path())
    return {
        "status": plane["status"],
        "error": plane.get("error"),
        "items": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "rank_history": {
            "available": False,
            "reason": "registry_sources_have_no_real_rank",
        },
    }


def _split_terms(value: str | None) -> list[str] | None:
    if not value or not value.strip():
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


@router.post("/refresh")
def refresh() -> dict[str, Any]:
    """立即抓取全部来源。单源失败不影响其他源，结果里显式列出失败来源。"""
    try:
        outcome = service.run_fetch("manual", _db_path())
    except Exception as exc:  # noqa: BLE001 - 刷新失败必须如实上报，不伪装成空数据
        return {
            "status": service.STATUS_UNAVAILABLE,
            "error": type(exc).__name__,
            "accepted": False,
        }
    return {
        "status": _run_status_to_surface(outcome.get("status")),
        "accepted": True,
        **outcome,
    }


def _run_status_to_surface(run_status: str | None) -> str:
    if run_status == service.store.RUN_STATUS_OK:
        return service.STATUS_NORMAL
    if run_status == service.store.RUN_STATUS_PARTIAL:
        return service.STATUS_PARTIAL
    return service.STATUS_UNAVAILABLE


@router.get("/trending")
def get_trending(
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    top_n: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """关注度趋势：热门条目 + 实体词热度与环比。不提供伪造排名。"""
    return service.trending(_db_path(), window_hours=window_hours, top_n=top_n)


@router.get("/security-context/{code}")
def get_security_context(
    code: str,
    window_hours: int = Query(default=24 * 7, ge=1, le=24 * 90),
    limit: int = Query(default=30, ge=1, le=200),
) -> dict[str, Any]:
    """单证券资讯上下文；只读观察面，不进入投资权威链。"""
    if not _CODE_RE.fullmatch(code or ""):
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "code must be a 6-digit A-share code"},
        )
    return service.security_context(code, _db_path(), window_hours=window_hours, limit=limit)


@router.get("/watchlist-context")
def get_watchlist_context(
    window_hours: int = Query(default=24 * 7, ge=1, le=24 * 90),
    per_code_limit: int = Query(default=8, ge=1, le=50),
) -> dict[str, Any]:
    """Watchlist 权威列表的批量资讯上下文。"""
    try:
        return service.watchlist_context(
            _db_path(), window_hours=window_hours, per_code_limit=per_code_limit
        )
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "watchlist contains invalid codes"},
        ) from None
