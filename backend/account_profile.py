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
# 向后兼容常量；新代码优先用 _account_path() 动态获取，以便测试隔离
ACCOUNT_FILE = os.path.join(CACHE_DIR, "account_profile.json")
BEIJING = timezone(timedelta(hours=8))
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _account_path() -> str:
    """返回当前 account_profile.json 完整路径（跟随 CACHE_DIR 变化）。"""
    return os.path.join(CACHE_DIR, "account_profile.json")


def load_account_profile() -> dict | None:
    """读账户资金。文件不存在或损坏 → None（未配置，不是 0）。"""
    st = get_account_profile_status()
    if st["status"] == "valid":
        return st["data"]
    return None


def get_account_profile_status() -> dict:
    """安全读取账户资金并返回状态描述。

    Returns
    -------
    dict
        - status == "valid": {"status": "valid", "data": {"total_assets": ..., "available_cash": ..., "updated_at": ...}}
        - status == "not_configured": {"status": "not_configured", "data": None}
        - status == "corrupted": {"status": "corrupted", "data": None}
    """
    account_file = _account_path()
    if not os.path.exists(account_file):
        return {"status": "not_configured", "data": None}
    try:
        with open(account_file, encoding="utf-8") as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"status": "corrupted", "data": None}

    if not isinstance(d, dict):
        return {"status": "corrupted", "data": None}

    try:
        total, cash = validate_account_payload({
            "total_assets": d.get("total_assets"),
            "available_cash": d.get("available_cash"),
        })
        updated_at = d.get("updated_at")
        if not isinstance(updated_at, str) or not updated_at.strip():
            return {"status": "corrupted", "data": None}
        return {
            "status": "valid",
            "data": {
                "total_assets": total,
                "available_cash": cash,
                "updated_at": updated_at.strip(),
            },
        }
    except Exception:
        return {"status": "corrupted", "data": None}



def save_account_profile(total_assets: float, available_cash: float) -> dict:
    """原子写入账户资金，updated_at 由后端生成。返回保存后的数据（含 updated_at）。"""
    payload = {
        "total_assets": round(float(total_assets), 2),
        "available_cash": round(float(available_cash), 2),
        "updated_at": _now(),
    }
    account_file = _account_path()
    with _LOCK:
        os.makedirs(CACHE_DIR, exist_ok=True)
        # 使用随机后缀避免跨进程固定文件名冲突
        tmp = account_file + f".tmp.{os.urandom(4).hex()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, account_file)
        finally:
            # 无论写入/替换成功或失败，都尽力清理临时文件
            # 使用 try/except 而非 except BaseException，避免捕获 KeyboardInterrupt/SystemExit
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass  # 清理失败只忽略，不掩盖原始业务异常
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
