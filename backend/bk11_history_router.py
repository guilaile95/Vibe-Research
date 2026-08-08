"""BK-11 短线市场历史 HTTP 路由：/api/market/bk11-history。

只负责 HTTP 适配（参数校验、错误映射）；只读查询委托给
``bk11_history_service``。GET 不写数据库、不创建数据库文件。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

import bk11_history_service as service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market/bk11-history", tags=["bk11-history"])


@router.get("")
def get_bk11_history(
    days: int = Query(service.DEFAULT_DAYS),
):
    """BK-11 短线市场历史只读查询（有界窗口，确定性结果）。

    - days：默认 5，允许 1..MAX_DAYS（60）；bool / 零 / 负数 / 超界拒绝。
    - 数据库不存在 / 空历史 / 损坏均返回 HTTP 200 的稳定 envelope。
    - 未预期异常返回 HTTP 502 稳定文案，不泄漏异常文本或路径。
    """
    if isinstance(days, bool):
        raise HTTPException(400, "days 必须是整数，收到 bool")
    if not (1 <= days <= service.MAX_DAYS):
        raise HTTPException(
            400,
            f"days 必须在 1..{service.MAX_DAYS} 之间，收到：{days}",
        )

    try:
        envelope = service.query_history(days=days)
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except Exception:  # noqa: BLE001
        logger.exception("bk11 history query failed")
        raise HTTPException(502, "短线市场历史查询异常。") from None
    return {"data": envelope}
