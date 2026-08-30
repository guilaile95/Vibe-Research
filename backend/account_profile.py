"""账户资金手工填写层 —— 用户自己录入的账户总资产与可用现金。

存本地 ~/.vibe-research/account_profile.json（不上传、不进仓库）。
存储位置与 portfolio.json 一致（VR_DATA_DIR 可覆盖）。

文件不存在表示「未配置」，不把未解释为 0。旧文件只有 updated_at，仍是
LEGACY_UNPROVEN；只有用户显式确认才由后端生成 effective/recorded identity。
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone, timedelta

CACHE_DIR = os.environ.get("VR_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vibe-research")
# 向后兼容常量；新代码优先用 _account_path() 动态获取，以便测试隔离
ACCOUNT_FILE = os.path.join(CACHE_DIR, "account_profile.json")
BEIJING = timezone(timedelta(hours=8))
_LOCK = threading.Lock()
ACCOUNT_PROFILE_CORRUPTED_REASON = "ACCOUNT_PROFILE_CORRUPTED"
ACCOUNT_CONFIRMATION_AUTHORITY = "MANUAL_EXPLICIT_CONFIRMATION"
ACCOUNT_CONFIRMATION_ID_RE = re.compile(r"^account_confirmation_[0-9a-f]{32}$")


def _now(moment: datetime | None = None) -> str:
    value = moment or datetime.now(timezone.utc)
    return value.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _utc_timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _confirmation_metadata(raw: dict) -> dict:
    fields = ("confirmation_id", "effective_at", "recorded_at", "authority")
    present = [field in raw for field in fields]
    if not any(present):
        return {
            "confirmation_status": "LEGACY_UNPROVEN",
            "confirmation_id": None,
            "effective_at": None,
            "recorded_at": None,
            "authority": None,
        }
    if not all(present):
        raise ValueError("confirmation metadata incomplete")
    confirmation_id = raw.get("confirmation_id")
    effective_at = raw.get("effective_at")
    recorded_at = raw.get("recorded_at")
    authority = raw.get("authority")
    if (
        not isinstance(confirmation_id, str)
        or ACCOUNT_CONFIRMATION_ID_RE.fullmatch(confirmation_id) is None
        or authority != ACCOUNT_CONFIRMATION_AUTHORITY
    ):
        raise ValueError("confirmation metadata invalid")
    parsed: list[datetime] = []
    for value in (effective_at, recorded_at):
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError("confirmation timestamp invalid")
        try:
            timestamp = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as exc:
            raise ValueError("confirmation timestamp invalid") from exc
        parsed.append(timestamp)
    if parsed[0] != parsed[1]:
        raise ValueError("manual current confirmation must share one effective/recorded instant")
    return {
        "confirmation_status": "CONFIRMED",
        "confirmation_id": confirmation_id,
        "effective_at": effective_at,
        "recorded_at": recorded_at,
        "authority": authority,
    }


def _account_path() -> str:
    """返回当前 account_profile.json 完整路径（跟随 CACHE_DIR 变化）。"""
    return os.path.join(CACHE_DIR, "account_profile.json")


def load_account_profile() -> dict | None:
    """读取已验证的账户资金；未配置或损坏均无有效数据可返回。"""
    st = get_account_profile_status()
    if st["status"] == "valid":
        return st["data"]
    return None


def _status(status: str, data: dict | None = None) -> dict:
    """构造不泄漏文件细节的 Profile 状态 envelope。"""
    result = {"status": status, "data": data, "reason_code": None}
    if status == "corrupted":
        result["reason_code"] = ACCOUNT_PROFILE_CORRUPTED_REASON
    return result


def get_account_profile_status() -> dict:
    """安全读取账户资金并返回状态描述。

    Returns
    -------
    dict
        - status == "valid": includes validated ``data`` and ``reason_code=None``
        - status == "not_configured": ``data=None`` and ``reason_code=None``
        - status == "corrupted": ``data=None`` and ``reason_code=ACCOUNT_PROFILE_CORRUPTED``
    """
    account_file = _account_path()
    if not os.path.exists(account_file):
        return _status("not_configured")
    try:
        with open(account_file, encoding="utf-8") as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _status("corrupted")

    if not isinstance(d, dict):
        return _status("corrupted")

    try:
        total, cash = validate_account_payload({
            "total_assets": d.get("total_assets"),
            "available_cash": d.get("available_cash"),
        })
        updated_at = d.get("updated_at")
        if not isinstance(updated_at, str) or not updated_at.strip():
            return _status("corrupted")
        return _status("valid", {
            "total_assets": total,
            "available_cash": cash,
            "updated_at": updated_at.strip(),
            **_confirmation_metadata(d),
        })
    except Exception:
        return _status("corrupted")



def save_account_profile(
    total_assets: float,
    available_cash: float,
    *,
    confirm_current: bool = False,
) -> dict:
    """原子写入账户资金；只有显式确认才产生正式 effective identity。"""
    moment = datetime.now(timezone.utc)
    payload = {
        "total_assets": round(float(total_assets), 2),
        "available_cash": round(float(available_cash), 2),
        "updated_at": _now(moment),
    }
    if confirm_current:
        timestamp = _utc_timestamp(moment)
        payload.update({
            "confirmation_id": f"account_confirmation_{uuid.uuid4().hex}",
            "effective_at": timestamp,
            "recorded_at": timestamp,
            "authority": ACCOUNT_CONFIRMATION_AUTHORITY,
        })
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
    return {**payload, **_confirmation_metadata(payload)}


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
