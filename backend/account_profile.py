"""账户资金手工填写层 —— 用户自己录入的账户总资产与可用现金。

存本地 ~/.vibe-research/account_profile.json（不上传、不进仓库）。
存储位置与 portfolio.json 一致（VR_DATA_DIR 可覆盖）。

文件不存在表示「未配置」，不把未解释为 0；updated_at 由后端生成。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone, timedelta

CACHE_DIR = os.environ.get("VR_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vibe-research")
ACCOUNT_FILE = os.path.join(CACHE_DIR, "account_profile.json")
BEIJING = timezone(timedelta(hours=8))
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def load_account_profile() -> dict | None:
    """读账户资金。文件不存在或损坏 → None（未配置，不是 0）。"""
    try:
        with open(ACCOUNT_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(d, dict):
        return None
    return d


def save_account_profile(total_assets: float, available_cash: float) -> dict:
    """原子写入账户资金，updated_at 由后端生成。返回保存后的数据（含 updated_at）。"""
    payload = {
        "total_assets": round(float(total_assets), 2),
        "available_cash": round(float(available_cash), 2),
        "updated_at": _now(),
    }
    with _LOCK:
        os.makedirs(CACHE_DIR, exist_ok=True)
        # 使用随机后缀避免跨进程固定文件名冲突
        tmp = ACCOUNT_FILE + f".tmp.{os.urandom(4).hex()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, ACCOUNT_FILE)
        except BaseException:
            # 任何写入或替换失败：尽力清理临时文件，不覆盖原始异常
            try:
                os.remove(tmp)
            except OSError:
                pass  # 清理临时文件失败只忽略，不掩盖原始写入异常
            raise
        try:
            os.remove(tmp)
        except OSError:
            pass  # 成功替换后清理临时文件，清理失败可忽略
    return payload


def validate_account_payload(raw: dict) -> tuple[float, float]:
    """校验客户端提交的原始 dict。

    - total_assets > 0
    - available_cash >= 0
    - available_cash <= total_assets
    - 拒绝 NaN、Infinity、非数字类型、布尔值
    - 拒绝未知字段与 updated_at 客户端注入
    返回 (total_assets, available_cash)；不通过则抛 ValueError。
    """
    if not isinstance(raw, dict):
        raise ValueError("请求体必须是 JSON 对象")

    # 拒绝客户端提交 updated_at（由后端生成）
    if "updated_at" in raw:
        updated = raw["updated_at"]
        if updated is not None:
            raise ValueError("updated_at 由后端生成，禁止客户端提交")

    # 拒绝未知字段
    unknown = set(raw.keys()) - {"total_assets", "available_cash"}
    if unknown:
        raise ValueError(f"未知字段：{sorted(unknown)}")

    total = raw.get("total_assets")
    cash = raw.get("available_cash")

    # 布尔值是 int 子类，必须先拒
    if isinstance(total, bool) or isinstance(cash, bool):
        raise ValueError("金额必须是数字，不能是布尔值")

    if not isinstance(total, (int, float)) or not isinstance(cash, (int, float)):
        raise ValueError("金额必须是数字")

    # NaN / Infinity
    if not (isinstance(total, (int, float)) and isinstance(cash, (int, float))):
        raise ValueError("金额必须是数字")
    if not (total == total and cash == cash):  # NaN check
        raise ValueError("金额不能为 NaN")
    if total in (float("inf"), float("-inf")) or cash in (float("inf"), float("-inf")):
        raise ValueError("金额不能为 Infinity")

    total = float(total)
    cash = float(cash)

    if not (total > 0):
        raise ValueError("账户总资产必须大于 0")
    if not (cash >= 0):
        raise ValueError("可用现金不能小于 0")
    if cash > total:
        raise ValueError("可用现金不能大于账户总资产")

    return total, cash
