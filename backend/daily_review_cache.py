"""每日复盘「最近一次成功结果」磁盘缓存（纯 I/O，不聚合、不调模型）。

路径：VR_DATA_DIR/daily_review_latest.json
      或默认 ~/.vibe-research/daily_review_latest.json

仅持久化 status 为 normal / partial 的完整复盘包；原子写入；
坏文件安全忽略。不写 SQLite，不影响历史快照。
"""

from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any

CACHE_SCHEMA_VERSION = "daily-review-cache-v0.1"
CACHE_FILENAME = "daily_review_latest.json"

_IO_LOCK = threading.Lock()


def data_dir() -> str:
    return os.environ.get("VR_DATA_DIR") or os.path.join(
        os.path.expanduser("~"), ".vibe-research"
    )


def cache_path() -> str:
    return os.path.join(data_dir(), CACHE_FILENAME)


def _is_cacheable_review(review: Any) -> bool:
    if not isinstance(review, dict):
        return False
    return review.get("status") in ("normal", "partial")


def save_latest_review(review: dict, *, saved_at: str) -> bool:
    """将成功复盘原子写入磁盘。不可缓存时返回 False 且不改动旧文件。"""
    if not _is_cacheable_review(review):
        return False
    if not isinstance(saved_at, str) or not saved_at.strip():
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
    # schema 宽松：未知版本仍尝试读取 review
    review = raw.get("review")
    if not _is_cacheable_review(review):
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
