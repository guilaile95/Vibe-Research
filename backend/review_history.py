"""每日复盘历史服务层 —— 显式保存策略与生产数据库路径解析。

位于 daily_review（聚合）与 review_store（SQLite）之间。

保存策略（必须遵守）：
- 每日复盘历史采用显式保存策略。
- GET /api/daily-review 不产生写入。
- POST /api/daily-review/analyze 不写 daily_review_snapshots；其已校验 AI 正文由
  独立 ai_generated_results 表按交易日保存。
- 只有显式调用 save_current_daily_review() 才会写入快照。

本模块不实现自动收盘保存、页面打开自动保存、AI 分析前自动保存、
后台定时任务、每日只保留一条、自动删除/覆盖旧快照。
同一交易日允许多个内容不同的快照，由 payload_hash 区分。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import daily_review
from review_db_path import REVIEW_DB_ENV, resolve_review_db_path
import review_store

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAVABLE_STATUS = frozenset({"normal", "partial"})


class ReviewSnapshotNotSavableError(ValueError):
    """当前每日复盘不满足历史保存策略（unavailable / 无交易日等）。"""


def validate_review_for_history(review: dict) -> None:
    """校验复盘是否允许写入历史库；通过返回 None，否则抛 ReviewSnapshotNotSavableError。"""
    if not isinstance(review, dict):
        raise ReviewSnapshotNotSavableError("review 必须是字典")

    status = review.get("status")
    if status == "unavailable":
        raise ReviewSnapshotNotSavableError(
            "每日复盘核心数据不可用，不保存历史快照"
        )
    if status not in _SAVABLE_STATUS:
        raise ReviewSnapshotNotSavableError(
            f"每日复盘状态不允许保存历史快照：{status!r}"
        )

    trade_date = review.get("trade_date")
    if trade_date is None or (isinstance(trade_date, str) and not trade_date.strip()):
        raise ReviewSnapshotNotSavableError(
            "每日复盘缺少明确交易日期，不保存历史快照"
        )
    if not isinstance(trade_date, str):
        raise ReviewSnapshotNotSavableError(
            "每日复盘缺少明确交易日期，不保存历史快照"
        )
    if not _DATE_RE.match(trade_date):
        raise ReviewSnapshotNotSavableError(
            f"每日复盘交易日期格式不合法：{trade_date!r}"
        )
    try:
        y, m, d = map(int, trade_date.split("-"))
        date(y, m, d)
    except ValueError as e:
        raise ReviewSnapshotNotSavableError(
            f"每日复盘交易日期不是有效日期：{trade_date!r}"
        ) from e


def save_current_daily_review(
    db_path: str | Path | None = None,
) -> dict:
    """显式生成当前每日复盘并写入历史库（仅 normal/partial 且有合法 trade_date）。

    generate_daily_review 只调用一次；不暴露数据库路径；不返回完整 review。
    """
    review = daily_review.generate_daily_review()
    validate_review_for_history(review)
    resolved = resolve_review_db_path(db_path)
    result = review_store.save_daily_review_snapshot(review, resolved)

    warnings = review.get("warnings")
    if not isinstance(warnings, list):
        warnings = []

    return {
        "snapshot": {
            "id": result["id"],
            "inserted": result["inserted"],
            "trade_date": result["trade_date"],
            "schema_version": result["schema_version"],
            "generated_at": result["generated_at"],
            "status": result["status"],
            "payload_hash": result["payload_hash"],
            "created_at": result["created_at"],
        },
        "review_status": review["status"],
        "review_warnings": list(warnings),
    }


def get_review_history_snapshot(
    snapshot_id: int,
    db_path: str | Path | None = None,
) -> dict | None:
    """按 ID 读取历史快照；不生成复盘、不写库。"""
    return review_store.get_daily_review_snapshot(
        snapshot_id,
        resolve_review_db_path(db_path),
    )


def get_latest_review_history_snapshot(
    trade_date: str | None = None,
    db_path: str | Path | None = None,
) -> dict | None:
    """读取最新历史快照；不生成复盘、不写库。"""
    return review_store.get_latest_daily_review_snapshot(
        resolve_review_db_path(db_path),
        trade_date=trade_date,
    )


def list_review_history(
    trade_date: str | None = None,
    limit: int = 30,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> list[dict]:
    """历史列表（仅元数据）；不生成复盘、不写库。"""
    return review_store.list_daily_review_snapshots(
        resolve_review_db_path(db_path),
        trade_date=trade_date,
        limit=limit,
        offset=offset,
    )
