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
    rank_available = service.store.any_source_has_real_rank(_db_path() or service.db_path())
    return {
        "status": plane["status"],
        "error": plane.get("error"),
        "items": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "rank_history": {
            "available": rank_available,
            "reason": None if rank_available else "registry_sources_have_no_real_rank",
            "note": "热榜条目自带真实 rank 与 delta；RSS 条目 rank 恒为 NULL",
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


# ---------------------------------------------------------------------------
# TREND-PARITY Wave 1：热榜板面 / 排名轨迹 / 来源管理
# 排名是数据事实（上游真实序号）；本组端点不提供任何「热度→投资建议」映射。
# ---------------------------------------------------------------------------


@router.get("/hotlist")
def get_hotlist(
    limit: int = Query(default=60, ge=1, le=200),
    mode: str = Query(default="all", pattern="^(all|my_interests)$"),
    profile_id: str = Query(default="default"),
) -> dict[str, Any]:
    """热榜板面：财联社 / 华尔街见闻等 hotlist 来源条目 + 真实排名与变化。

    支持 mode='my_interests' 个人兴趣过滤与 mode='all' 全量透传。
    """
    return service.hotlist_board(_db_path(), limit=limit, mode=mode, profile_id=profile_id)


@router.get("/items/{item_id}/rank-history")
def get_item_rank_history(item_id: int) -> dict[str, Any]:
    """单条目排名轨迹；真实观测全量返回，ON_LIST/OFF_LIST/UNKNOWN 由读取侧推导。"""
    if item_id < 1:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "item_id must be a positive integer"},
        )
    result = service.item_rank_history(item_id, _db_path())
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"status": "NOT_FOUND", "error": "item not found"},
        )
    return result


@router.get("/sources")
def get_sources() -> dict[str, Any]:
    """来源注册表（系统 seed + 用户自建；origin 区分删除权限）。"""
    return service.sources_list(_db_path())


@router.post("/sources")
def post_source(payload: dict[str, Any]) -> dict[str, Any]:
    """新增用户 RSS 源（origin=user）。输入非法 422；来源 ID 冲突 409。"""
    try:
        row = service.create_user_source(payload, _db_path())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": str(exc)},
        ) from exc
    except (service.store.SourceAlreadyExistsError, service._SourceConflictError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"status": "SOURCE_ALREADY_EXISTS", "error": "同名来源已存在"},
        ) from exc
    return {"data": row}


@router.patch("/sources/{source_id}")
def patch_source(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新来源：系统源仅允许 enabled；用户源允许 enabled + name。"""
    try:
        row = service.update_source(source_id, payload, _db_path())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": str(exc)},
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"status": "NOT_FOUND", "error": "source not found"},
        )
    return {"data": row}


@router.delete("/sources/{source_id}")
def remove_source(source_id: str) -> dict[str, Any]:
    """删除来源；系统来源 fail closed 拒绝（409，可停用不可删除）。"""
    try:
        row = service.delete_source(source_id, _db_path())
    except service.store.SystemSourceDeleteBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "SYSTEM_SOURCE_DELETE_BLOCKED",
                "error": "系统来源不可删除；可停用",
            },
        ) from exc
    except service.store.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"status": "NOT_FOUND", "error": "source not found"},
        ) from exc
    return {"data": row}


# ---------------------------------------------------------------------------
# TREND-PARITY Wave 2：个人兴趣与关键词过滤 API
# ---------------------------------------------------------------------------


@router.get("/filter/profile")
def get_filter_profile(
    profile_id: str = Query(default="default"),
) -> dict[str, Any]:
    """获取当前个人兴趣与关键词过滤配置 Profile。"""
    try:
        return service.get_filter_profile(profile_id, _db_path())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"status": "ERROR", "error": str(exc)},
        ) from exc


@router.put("/filter/profile")
def put_filter_profile(
    payload: dict[str, Any],
    profile_id: str = Query(default="default"),
) -> dict[str, Any]:
    """更新个人兴趣与关键词过滤配置 Profile（支持关键词/AI切换）。"""
    try:
        return service.update_filter_profile(profile_id, payload, _db_path())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"status": "ERROR", "error": str(exc)},
        ) from exc


@router.post("/filter/extract-tags")
def post_extract_tags(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """根据自然语言兴趣描述提取结构化分类标签（阶段 A）。"""
    interests_text = str((payload or {}).get("interests_text") or "").strip()
    if not interests_text:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "interests_text 不能为空"},
        )
    cfg = payload.get("ai_config")
    try:
        tags = service.extract_filter_tags(interests_text, cfg=cfg)
        return {"tags": tags}
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"status": "EXTRACTION_FAILED", "error": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"status": "AI_ERROR", "error": str(exc)},
        ) from exc


@router.post("/filter/update-tags")
def post_update_tags(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """对比旧标签与新兴趣描述，增量评估变化度与标签增删方案（阶段 A'）。"""
    interests_text = str((payload or {}).get("interests_text") or "").strip()
    if not interests_text:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "interests_text 不能为空"},
        )
    old_tags = (payload or {}).get("old_tags") or []
    if not isinstance(old_tags, list):
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "old_tags 必须为列表"},
        )
    cfg = payload.get("ai_config")
    try:
        plan = service.update_filter_tags(old_tags, interests_text, cfg=cfg)
        return plan
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"status": "UPDATE_FAILED", "error": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"status": "AI_ERROR", "error": str(exc)},
        ) from exc


@router.post("/filter/classify")
def post_classify_items(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """触发条目 AI 批量分类（阶段 B）。失败隔离，绝不返回假相关度。"""
    body = payload or {}
    profile_id = str(body.get("profile_id") or "default")
    limit = int(body.get("limit") or 100)
    item_ids = body.get("item_ids")
    cfg = body.get("ai_config")
    try:
        return service.classify_items(
            profile_id=profile_id,
            item_ids=item_ids,
            limit=limit,
            cfg=cfg,
            path=_db_path(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"status": "ERROR", "error": str(exc)},
        ) from exc


@router.get("/filter/status")
def get_filter_status(
    profile_id: str = Query(default="default"),
) -> dict[str, Any]:
    """查询过滤器运行状态与条目分类覆盖率统计。"""
    try:
        return service.filter_status(profile_id, _db_path())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"status": "ERROR", "error": str(exc)},
        ) from exc


@router.post("/filter/apply-interest-update")
def post_apply_interest_update(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """一键应用兴趣变更：自动执行阶段 A/A'、更新 Profile 并根据阈值分流。"""
    body = payload or {}
    interests_text = str(body.get("interests_text") or "").strip()
    if not interests_text:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "interests_text 不能为空"},
        )
    profile_id = str(body.get("profile_id") or "default")
    cfg = body.get("ai_config") or body.get("cfg")

    threshold: float | None = None
    if "full_reclassify_threshold" in body and body["full_reclassify_threshold"] is not None:
        try:
            threshold = float(body["full_reclassify_threshold"])
            if not (0.0 <= threshold <= 1.0):
                raise ValueError("full_reclassify_threshold 必须在 0.0 到 1.0 之间")
        except (ValueError, TypeError) as val_err:
            raise HTTPException(
                status_code=422,
                detail={"status": "BAD_ARGUMENT", "error": f"非法的 full_reclassify_threshold: {val_err}"},
            ) from val_err

    min_score: float | None = None
    if "min_score" in body and body["min_score"] is not None:
        try:
            min_score = float(body["min_score"])
            if not (0.0 <= min_score <= 1.0):
                raise ValueError("min_score 必须在 0.0 到 1.0 之间")
        except (ValueError, TypeError) as val_err:
            raise HTTPException(
                status_code=422,
                detail={"status": "BAD_ARGUMENT", "error": f"非法的 min_score: {val_err}"},
            ) from val_err

    try:
        return service.apply_interest_update(
            profile_id=profile_id,
            interests_text=interests_text,
            cfg=cfg,
            full_reclassify_threshold=threshold,
            min_score=min_score,
            path=_db_path(),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"status": "APPLY_UPDATE_FAILED", "error": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"status": "AI_ERROR", "error": str(exc)},
        ) from exc


@router.get("/filter/items")
def get_filtered_items(
    profile_id: str = Query(default="default"),
    source_type: str = Query(default="all", pattern="^(all|hotlist|rss)$"),
    mode: str = Query(default="my_interests", pattern="^(all|my_interests)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """统一过滤端点：支持全量(all)、仅热榜(hotlist)、仅RSS(rss)的个人兴趣或全量过滤查询。"""
    try:
        return service.list_filtered_items(
            profile_id=profile_id,
            source_type=source_type,
            mode=mode,
            limit=limit,
            path=_db_path(),
        )
    except Exception as exc:
        return {
            "status": service.STATUS_UNAVAILABLE,
            "error": str(exc),
            "items": [],
            "total": 0,
            "filter_meta": {
                "mode": mode,
                "status": "UNAVAILABLE",
                "error": str(exc),
            },
        }
