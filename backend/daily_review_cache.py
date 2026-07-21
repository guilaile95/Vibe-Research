"""每日复盘「最近一次成功结果」磁盘缓存（纯 I/O，不聚合、不调模型）。

路径：VR_DATA_DIR/daily_review_latest.json
      或默认 ~/.vibe-research/daily_review_latest.json

质量规则：
- normal 可替换 normal / partial
- partial 不得覆盖已有 normal
- 关键组件（indices / breadth / emotion）unavailable → 不持久化
- unavailable 永不持久化
- 原子写入；坏文件安全忽略；不写 SQLite
"""

from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any

CACHE_SCHEMA_VERSION = "daily-review-cache-v0.1"
CACHE_FILENAME = "daily_review_latest.json"

# 与 daily_review.data_health.components 键对齐
CRITICAL_COMPONENT_KEYS = ("indices", "breadth", "emotion")

_IO_LOCK = threading.Lock()


def data_dir() -> str:
    return os.environ.get("VR_DATA_DIR") or os.path.join(
        os.path.expanduser("~"), ".vibe-research"
    )


def cache_path() -> str:
    return os.path.join(data_dir(), CACHE_FILENAME)


def has_critical_unavailable(review: Any) -> bool:
    """关键组件 indices / breadth / emotion 任一无可用则 True。"""
    if not isinstance(review, dict):
        return True
    health = review.get("data_health") if isinstance(review.get("data_health"), dict) else {}
    comps = health.get("components") if isinstance(health.get("components"), dict) else {}
    for key in CRITICAL_COMPONENT_KEYS:
        if comps.get(key) == "unavailable":
            return True
    return False


def _is_structurally_cacheable(review: Any) -> bool:
    if not isinstance(review, dict):
        return False
    return review.get("status") in ("normal", "partial")


def should_persist_review(new_review: Any, existing_review: Any | None = None) -> bool:
    """是否允许将 new_review 写入磁盘（相对 existing_review）。"""
    if not _is_structurally_cacheable(new_review):
        return False
    if new_review.get("status") == "unavailable":
        return False
    if has_critical_unavailable(new_review):
        return False
    if new_review.get("status") == "partial":
        if isinstance(existing_review, dict) and existing_review.get("status") == "normal":
            # partial 不得覆盖 normal
            return False
    return True


def save_latest_review(review: dict, *, saved_at: str) -> bool:
    """按质量规则原子写入。不满足时返回 False 且不改动旧文件。"""
    if not isinstance(saved_at, str) or not saved_at.strip():
        return False

    existing, _ = load_latest_review()
    if not should_persist_review(review, existing):
        return False

    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "saved_at": saved_at.strip(),
        "review": copy.deepcopy(review),
    }
    path = cache_path()
    parent = os.path.dirname(path)
    tmp = path + ".tmp"

    with _IO_LOCK:
        try:
            os.makedirs(parent, exist_ok=True)
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False
        except (TypeError, ValueError):
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False


def load_latest_review() -> tuple[dict | None, str | None]:
    """读取最近成功复盘。

    Returns
    -------
    (review, saved_at)
        review 为 deepcopy；坏 JSON / 结构错误 / 不可缓存 status → (None, None)。
    """
    path = cache_path()
    with _IO_LOCK:
        try:
            if not os.path.isfile(path):
                return None, None
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
            return None, None

    if not isinstance(raw, dict):
        return None, None
    review = raw.get("review")
    if not _is_structurally_cacheable(review):
        return None, None
    # 磁盘上若已是关键组件不可用，视为无效（不删除文件，但拒绝使用）
    if has_critical_unavailable(review):
        return None, None
    saved_at = raw.get("saved_at")
    if not isinstance(saved_at, str) or not saved_at.strip():
        saved_at = None
    else:
        saved_at = saved_at.strip()
    return copy.deepcopy(review), saved_at


def clear_latest_review_file() -> None:
    """删除磁盘缓存（测试用）。"""
    path = cache_path()
    with _IO_LOCK:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
