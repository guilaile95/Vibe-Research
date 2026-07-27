"""持仓数据层 —— 用户自己录入的持仓 + 实时行情叠加浮动盈亏。

持仓存本地 ~/.vibe-research/portfolio.json（不上传、不进仓库）。
盈亏红涨绿跌（A股口径）。含每半小时后台定时刷新 + 手动刷新。

存储位置：默认用户目录 ~/.vibe-research/（可用 VR_DATA_DIR 覆盖）——
放仓库外，重新下载/覆盖项目文件夹不会丢数据（issue #12）。
≤v0.1.1 存在 backend/.cache/ 仓库内，首次启动自动迁移（复制，旧文件保留作备份）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import copy
from datetime import datetime, timezone, timedelta
from typing import Any

import astock

HERE = os.path.dirname(os.path.abspath(__file__))
_OLD_PF_FILE = os.path.join(HERE, ".cache", "portfolio.json")  # ≤v0.1.1 旧位置
# CACHE_DIR 名字保留（测试/外部按此名 monkeypatch），实际已是用户数据目录
CACHE_DIR = os.environ.get("VR_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vibe-research")
PF_FILE = os.path.join(CACHE_DIR, "portfolio.json")
BEIJING = timezone(timedelta(hours=8))
_LOCK = threading.Lock()



def _migrate_legacy() -> None:
    """旧版持仓在仓库内 .cache/ 里，重下载项目会丢；迁到用户目录（新位置已有则不动）。"""
    try:
        if not os.path.exists(PF_FILE) and os.path.exists(_OLD_PF_FILE):
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = PF_FILE + ".migrate.tmp"
            shutil.copy2(_OLD_PF_FILE, tmp)
            os.replace(tmp, PF_FILE)  # 原子落位：复制中断不会留半截 portfolio.json 挡住下次重试
    except OSError as e:
        # 迁移失败不阻塞启动，但要出声——旧数据原样保留在 _OLD_PF_FILE，可手工复制
        print(f"[vibe-research] 持仓数据迁移失败（旧数据仍在 {_OLD_PF_FILE}）: {e}", file=sys.stderr)


_migrate_legacy()


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")



class PortfolioDataCorruptedError(RuntimeError):
    """持仓数据文件损坏，已停止读写以避免覆盖。"""
    MESSAGE = (
        "本地持仓数据文件损坏，已停止读写以避免覆盖；"
        "请检查 portfolio.json，并在有备份时从 portfolio.json.bak 恢复"
    )

    def __init__(self):
        super().__init__(self.MESSAGE)


def _validate_data(data):
    if not isinstance(data, dict):
        raise PortfolioDataCorruptedError()
    hs = data.get("holdings")
    if hs is None or not isinstance(hs, list):
        raise PortfolioDataCorruptedError()
    closed = data.get("closed")
    if closed is not None and not isinstance(closed, list):
        raise PortfolioDataCorruptedError()


def _load():
    try:
        with open(PF_FILE, encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return {"holdings": [], "last_refresh": None}
    except (UnicodeDecodeError, UnicodeError):
        raise PortfolioDataCorruptedError() from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise PortfolioDataCorruptedError() from None
    _validate_data(data)
    return data


def _tmp_name(base):
    return f"{base}.tmp.{os.urandom(4).hex()}"





def _save(d):
    os.makedirs(CACHE_DIR, exist_ok=True)
    bak_tmp = None
    data_tmp = None
    try:
        if os.path.exists(PF_FILE):
            with open(PF_FILE, encoding="utf-8") as f:
                existing_raw = f.read()
            try:
                existing_data = json.loads(existing_raw)
            except (json.JSONDecodeError, UnicodeDecodeError, UnicodeError):
                raise PortfolioDataCorruptedError() from None
            _validate_data(existing_data)

            bak_file = PF_FILE + ".bak"
            bak_tmp = _tmp_name(bak_file)
            shutil.copy2(PF_FILE, bak_tmp)
            os.replace(bak_tmp, bak_file)
            bak_tmp = None

        data_tmp = _tmp_name(PF_FILE)
        with open(data_tmp, "w", encoding="utf-8", newline="") as f:
            json.dump(d, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(data_tmp, PF_FILE)
        data_tmp = None
    finally:
        for tmp in (bak_tmp, data_tmp):
            if tmp is not None and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def add_holding(code: str, shares: float, cost: float) -> dict:
    """加一笔持仓；同代码则按加权平均成本合并（加仓）。"""
    with _LOCK:
        d = _load()
        for h in d["holdings"]:
            if h["code"] == code:
                total = h["shares"] + shares
                # 4 位小数：ETF/基金成本常见 3-4 位（issue #13），2-3 位会让市值/盈亏对不上账
                h["cost"] = round((h["shares"] * h["cost"] + shares * cost) / total, 4) if total else cost
                h["shares"] = total
                break
        else:
            d["holdings"].append({"code": code, "shares": shares, "cost": cost})
        _save(d)
    return get_portfolio()


def remove_holding(code: str) -> dict:
    with _LOCK:
        d = _load()
        d["holdings"] = [h for h in d["holdings"] if h["code"] != code]
        _save(d)
    return get_portfolio()


def update_holding(code: str, shares: int, cost: float) -> dict:
    """精确替换指定代码的 shares 和 cost；不执行加权平均；code 不存在时抛 ValueError。"""
    with _LOCK:
        d = _load()
        for h in d["holdings"]:
            if h["code"] == code:
                h["shares"] = shares
                h["cost"] = cost
                break
        else:
            raise ValueError(f"股票代码 {code} 不在持仓中")
        _save(d)
    return get_portfolio()


def close_position(code: str, date: str, price: float, shares: float, cost: float) -> dict:
    """记一笔已清仓：算已实现盈亏，存入 closed 列表。"""
    pnl = (price - cost) * shares
    with _LOCK:
        d = _load()
        d.setdefault("closed", [])
        try:
            name = astock.tencent_quote([code]).get(code, {}).get("name", code)
        except Exception:
            name = code
        d["closed"].append({
            "code": code, "name": name, "date": date, "price": price,
            "shares": shares, "cost": cost, "pnl": round(pnl, 2),
            "pnl_pct": round((price - cost) / cost * 100, 2) if cost else 0.0,
        })
        _save(d)
    return get_portfolio()


def remove_closed(index: int) -> dict:
    with _LOCK:
        d = _load()
        cl = d.get("closed", [])
        if 0 <= index < len(cl):
            cl.pop(index)
            _save(d)
    return get_portfolio()


def _is_valid_price(px: Any) -> bool:
    if isinstance(px, bool) or not isinstance(px, (int, float)):
        return False
    if px <= 0 or px != px or px in (float("inf"), float("-inf")):
        return False
    return True


def get_portfolio_holdings_snapshot() -> dict:
    """Read local holdings only; no quotes, calculations, writes, or timestamp updates."""
    with _LOCK:
        d = _load()
    return {"holdings": copy.deepcopy(d.get("holdings", []))}


def get_portfolio() -> dict:
    """读持仓 + 实时行情，算每笔与汇总的市值/浮动盈亏。"""
    with _LOCK:
        d = _load()
    hs = d.get("holdings", [])
    rows = []
    valid_count = 0
    tmv_sum = 0.0
    tcost = 0.0
    if hs:
        try:
            quotes = astock.tencent_quote([h["code"] for h in hs])
        except Exception:
            quotes = {}
        if not isinstance(quotes, dict):
            quotes = {}

        for h in hs:
            q = quotes.get(h["code"], {}) if isinstance(quotes, dict) else {}
            if not isinstance(q, dict):
                q = {}
            name = q.get("name", h.get("code", ""))
            shares = h.get("shares", 0.0)
            cost = h.get("cost", 0.0)
            cv = cost * shares
            tcost += cv

            raw_px = q.get("price")
            if _is_valid_price(raw_px):
                price = float(raw_px)
                mv = price * shares
                pnl = mv - cv
                pnl_pct = round((price - cost) / cost * 100, 2) if cost else 0.0
                rows.append({
                    "code": h["code"],
                    "name": name,
                    "price": price,
                    "shares": shares,
                    "cost": cost,
                    "market_value": round(mv, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": pnl_pct,
                    "data_status": "normal",
                })
                valid_count += 1
                tmv_sum += mv
            else:
                rows.append({
                    "code": h["code"],
                    "name": name,
                    "price": None,
                    "shares": shares,
                    "cost": cost,
                    "market_value": None,
                    "pnl": None,
                    "pnl_pct": None,
                    "data_status": "unavailable",
                })

    total_count = len(hs)
    complete = (total_count > 0 and valid_count == total_count)
    quote_coverage = {
        "valid_holdings": valid_count,
        "total_holdings": total_count,
        "complete": complete,
    }

    if total_count == 0 or complete:
        data_status = "normal"
    elif valid_count > 0:
        data_status = "partial"
    else:
        data_status = "unavailable"

    if total_count == 0 or complete:
        total_pnl = tmv_sum - tcost
        totals = {
            "market_value": round(tmv_sum, 2),
            "cost": round(tcost, 2),
            "pnl": round(total_pnl, 2),
            "pnl_pct": round(total_pnl / tcost * 100, 2) if tcost else 0.0,
        }
    else:
        totals = {
            "market_value": None,
            "cost": round(tcost, 2),
            "pnl": None,
            "pnl_pct": None,
        }

    closed = d.get("closed", [])
    return {
        "holdings": rows,
        "totals": totals,
        "closed": closed,
        "realized_pnl": round(sum(c.get("pnl", 0) for c in closed), 2),
        "updated": _now(),
        "last_refresh": d.get("last_refresh"),
        "data_status": data_status,
        "quote_coverage": quote_coverage,
    }


def _refresh_snapshot() -> None:
    """后台定时任务：刷新时间戳（GET 本就实时算，这里记录后台刷新点）。"""
    with _LOCK:
        d = _load()
        d["last_refresh"] = _now()
        _save(d)


_scheduler_started = False
_scheduler_lock = threading.Lock()


def start_scheduler(interval: int = 1800) -> None:
    """启动持仓后台刷新调度器（daemon 线程，幂等：重复调用不会创建多个线程）。

    线程 start() 成功后才置 _scheduler_started=True；若 start() 抛异常，
    标志保持 False，锁正常释放，后续调用可重新尝试。
    """
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return

        def loop():
            while True:
                time.sleep(interval)
                try:
                    _refresh_snapshot()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True, name="portfolio-refresh").start()
        _scheduler_started = True
