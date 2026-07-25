"""后端权威自选股（关注股）存储层。

关注股以后端 JSON 文件为准（VR_DATA_DIR/watchlist.json）；前端 localStorage
仅作本地缓存 / 离线草稿。前端启动时可把本地草稿 ``POST /api/watchlist/import-local``
显式并入后端，冲突时以后端 etag 为准（乐观并发）。

不联网、不写 SQLite；只做原子文件写入 + etag 乐观锁。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

BEIJING = timezone(timedelta(hours=8))

SCHEMA_VERSION = "watchlist.v1"
MAX_CODES = 50
_CODE_RE = __import__("re").compile(r"^\d{6}$")

_CACHE_DIR = os.environ.get("VR_DATA_DIR") or os.path.join(
    os.path.expanduser("~"), ".vibe-research"
)
_LOCK = threading.Lock()


class WatchlistVersionConflictError(ValueError):
    """etag 与后端当前版本不一致，需前端先 GET 最新版本再决定。"""

    def __init__(self, current_etag: str):
        super().__init__("关注股已被其他会话修改，请刷新后重试")
        self.current_etag = current_etag


class WatchlistLimitExceededError(ValueError):
    """去重后代码数超过 MAX_CODES，拒绝静默截断。"""

    def __init__(self, count: int, limit: int = MAX_CODES):
        super().__init__(f"关注股超过上限 {limit}（去重后 {count} 只），请删减后再保存")
        self.count = count
        self.limit = limit


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _watchlist_path() -> str:
    return os.path.join(_CACHE_DIR, "watchlist.json")


def _bak_path(path: str) -> str:
    return path + ".bak"


def _codes_etag(codes: list[str]) -> str:
    """由排序后的代码列表派生 etag（内容 hash，不含时间戳）。"""
    blob = json.dumps(sorted(codes), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _normalize_codes(codes: Any, *, enforce_limit: bool = True) -> list[str]:
    """校验并归一化输入代码列表：6 位数字、去重、保序。

    ``enforce_limit=True``（默认）时，去重后超过 MAX_CODES 抛
    ``WatchlistLimitExceededError``（不静默截断）。
    读取损坏恢复场景可 ``enforce_limit=False`` 并截断。
    """
    if not isinstance(codes, list):
        raise ValueError("关注股必须是代码数组")
    seen: set[str] = set()
    out: list[str] = []
    for c in codes:
        if not isinstance(c, str):
            raise ValueError(f"关注股代码必须是字符串，收到 {type(c).__name__}")
        code = c.strip()
        if not _CODE_RE.match(code):
            raise ValueError(f"非法的关注股代码：{code}")
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    if enforce_limit and len(out) > MAX_CODES:
        raise WatchlistLimitExceededError(len(out), MAX_CODES)
    if not enforce_limit and len(out) > MAX_CODES:
        out = out[:MAX_CODES]
    return out


def _read_status_unlocked() -> dict:
    """在已持锁或只读路径下读取状态。"""
    path = _watchlist_path()
    if not os.path.exists(path):
        return {"status": "not_configured", "data": None, "etag": None}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"status": "corrupted", "data": None, "etag": None}
    if not isinstance(d, dict):
        return {"status": "corrupted", "data": None, "etag": None}
    if d.get("schema_version") != SCHEMA_VERSION:
        return {"status": "corrupted", "data": None, "etag": None}
    codes = d.get("codes")
    if not isinstance(codes, list):
        return {"status": "corrupted", "data": None, "etag": None}
    try:
        codes = _normalize_codes(codes, enforce_limit=False)
    except ValueError:
        return {"status": "corrupted", "data": None, "etag": None}
    updated_at = d.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        return {"status": "corrupted", "data": None, "etag": None}
    return {
        "status": "valid",
        "data": {"codes": codes, "updated_at": updated_at.strip()},
        "etag": d.get("etag") or _codes_etag(codes),
    }


def _atomic_write_unlocked(payload: dict) -> None:
    path = _watchlist_path()
    os.makedirs(_CACHE_DIR, exist_ok=True)
    tmp = path + f".tmp.{os.urandom(4).hex()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        try:
            if os.path.exists(path):
                os.replace(path, _bak_path(path))
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def load_watchlist() -> list[str]:
    """读取后端关注股；未配置或损坏返回 []（不把缺失解释为错误）。"""
    status = get_watchlist_status()
    if status["status"] == "valid":
        return list(status["data"]["codes"])
    return []


def get_watchlist_status() -> dict:
    """读取关注股 + 状态 + etag。

    Returns
    -------
    dict
        - status == "valid":   {"status", "data": {"codes", "updated_at"}, "etag"}
        - status == "not_configured": {"status": "not_configured", "data": None, "etag": None}
        - status == "corrupted": {"status": "corrupted", "data": None, "etag": None}
    """
    with _LOCK:
        return _read_status_unlocked()


def save_watchlist(codes: Any, *, expected_etag: str | None = None) -> dict:
    """全量保存关注股（原子写入 + .bak 备份）。

    etag 校验、读取、写备份、落盘均在同一文件锁内，避免并发丢更新。
    去重后 > MAX_CODES → ``WatchlistLimitExceededError``（不静默截断）。

    Returns
    -------
    dict 保存后的数据 {"codes", "updated_at", "etag"}
    """
    codes = _normalize_codes(codes, enforce_limit=True)

    with _LOCK:
        if expected_etag is not None:
            current = _read_status_unlocked()
            cur_etag = current.get("etag")
            if cur_etag is not None and cur_etag != expected_etag:
                raise WatchlistVersionConflictError(cur_etag)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "codes": codes,
            "updated_at": _now(),
            "etag": _codes_etag(codes),
        }
        _atomic_write_unlocked(payload)

    return {
        "codes": codes,
        "updated_at": payload["updated_at"],
        "etag": payload["etag"],
    }


def merge_watchlist(incoming: Any, *, expected_etag: str | None = None) -> dict:
    """显式并入（前端 localStorage → 后端）。

    保留后端已有代码 + 去重并入新代码。合并后若超过 MAX_CODES 抛
    ``WatchlistLimitExceededError``（不静默丢码）。

    整个 check / read / merge / backup / write 在同一文件锁内。
    返回并入结果 {"codes", "added", "updated_at", "etag"}。
    """
    incoming = _normalize_codes(
        incoming if isinstance(incoming, list) else [],
        enforce_limit=False,  # 单方可能已超，合并后再强制
    )

    with _LOCK:
        if expected_etag is not None:
            current = _read_status_unlocked()
            cur_etag = current.get("etag")
            if cur_etag is not None and cur_etag != expected_etag:
                raise WatchlistVersionConflictError(cur_etag)

        status = _read_status_unlocked()
        existing_codes = (
            list(status["data"]["codes"]) if status["status"] == "valid" else []
        )
        existing = set(existing_codes)
        added_codes = [c for c in incoming if c not in existing]
        merged = existing_codes + added_codes
        # 强制上限：超限明确报错
        merged = _normalize_codes(merged, enforce_limit=True)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "codes": merged,
            "updated_at": _now(),
            "etag": _codes_etag(merged),
        }
        _atomic_write_unlocked(payload)

    return {
        "codes": merged,
        "added": added_codes,
        "updated_at": payload["updated_at"],
        "etag": payload["etag"],
    }
