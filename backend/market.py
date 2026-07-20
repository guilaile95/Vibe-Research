"""市场总览数据层 —— 市场情绪 + 板块资金流（板块/大盘级公开数据，不涉个股推荐）。

省流量：全站共享一份缓存（TTL 默认 5 分钟），多个用户/多次打开只抓一次；
盘中 5 分钟刷新足够，非交易时段数据本就不变。数据源全免费、无 key。
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone, timedelta

import astock
import gstock

BEIJING = timezone(timedelta(hours=8))
_CACHE: dict = {}
_TTL = 300  # 5 分钟；全站共享，省数据源压力


def _cached(key: str, fn, valid=bool):
    """TTL 缓存。数据源故障的空结果不缓存（valid 判否），下次请求直接重试。"""
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    val = fn()
    if valid(val):
        _CACHE[key] = (now, val)
    return val


def _num(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _sentiment() -> dict:
    """市场情绪：涨跌家数/涨停跌停/活跃度 + 大盘宽度、题材投机。"""
    try:
        # akshare 惰性导入（同 astock 模式）：未装时降级返回空，不挡整个服务启动
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception:
        return {}
    up, down, flat = _num(d.get("上涨")), _num(d.get("下跌")), _num(d.get("平盘"))
    zt, zt_real = _num(d.get("涨停")), _num(d.get("真实涨停"))
    dt, dt_real = _num(d.get("跌停")), _num(d.get("真实跌停"))
    r = up / max(down, 1)
    if up < 600:
        breadth = "冰点"
    elif r < 0.7:
        breadth = "偏弱"
    elif r < 1.2:
        breadth = "中性"
    elif r < 2.5:
        breadth = "偏强"
    else:
        breadth = "普涨"
    speculation = "亢奋" if zt_real >= 100 else "活跃" if zt_real >= 60 else "普通" if zt_real >= 30 else "冰点"
    return {
        "up": up, "down": down, "flat": flat,
        "zt": zt, "zt_real": zt_real, "dt": dt, "dt_real": dt_real,
        "active": str(d.get("活跃度", "")),
        "breadth": breadth, "speculation": speculation,
        "date": str(d.get("统计日期", "")),
    }


def _sectors() -> list[dict]:
    """行业资金流（按净额降序）。不含领涨股等个股字段。"""
    try:
        f = astock._akshare().stock_fund_flow_industry(symbol="即时")
        f = f.sort_values("净额", ascending=False)
    except Exception:
        return []
    out = []
    for _, row in f.iterrows():
        out.append({
            "name": str(row["行业"]),
            "pct": round(float(row.get("行业-涨跌幅", 0) or 0), 2),
            "net": round(float(row.get("净额", 0) or 0), 2),
            "inflow": round(float(row.get("流入资金", 0) or 0), 2),
            "outflow": round(float(row.get("流出资金", 0) or 0), 2),
            "firms": _num(row.get("公司家数")),
        })
    return out


def get_overview() -> dict:
    """市场情绪 + 板块资金（含缓存）。资金轮动由前端从 sectors 头尾取。"""
    def build():
        return {
            "sentiment": _sentiment(),
            "sectors": _sectors(),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return _cached("overview", build, valid=lambda v: bool(v.get("sentiment") or v.get("sectors")))


def _emotion() -> dict:
    """短线情绪：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数 + 连板股清单。

    数据源＝东财涨停板四池（push2ex）。
    """
    # 定位最近交易日：从今天往前回溯，第一日有涨停池即取（非交易日/盘前返空则继续回溯）。
    today = datetime.now(BEIJING).date()
    resolved, zt = "", []
    for back in range(8):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        zt = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
        if zt:
            resolved = d
            break
    if not resolved:
        return {}

    zb = astock.em_zt_topic_pool("getTopicZBPool", resolved, "fbt:asc")    # 炸板池
    dt = astock.em_zt_topic_pool("getTopicDTPool", resolved, "fund:asc")   # 跌停池
    yzt = astock.em_zt_topic_pool("getYesterdayZTPool", resolved, "zs:desc")  # 昨涨停池

    boards = [_num(p.get("lbc")) or 1 for p in zt]      # 每只连板数（缺省按 1 板）
    lianban = [b for b in boards if b >= 2]             # 2 板及以上（连板）
    # 连板梯队：2/3/4/5+ 各多少家（5 代表 5 板及以上），只保留有家数的档
    tiers = Counter(min(b, 5) for b in lianban)
    ladder = [{"boards": b, "count": tiers[b], "plus": b >= 5} for b in sorted(tiers)]

    # 连板股清单（2 板+；按连板数、成交额降序）。
    lianban_stocks = sorted(
        ({
            "code": str(p.get("c", "")), "name": p.get("n", ""),
            "boards": _num(p.get("lbc")) or 1,
            "price": round((astock._numf(p.get("p")) or 0) / 1000, 2),
            "pct": round(astock._numf(p.get("zdp")) or 0, 2),
            "amount": astock._numf(p.get("amount")),      # 成交额,元（'-' 占位归一为 None，防排序对 str 取负崩溃）
            "float_cap": astock._numf(p.get("ltsz")),     # 流通市值,元
            "industry": p.get("hybk", ""),  # 概念/行业
        } for p in zt if (_num(p.get("lbc")) or 1) >= 2),
        key=lambda x: (-x["boards"], -(x["amount"] or 0)),
    )

    zt_count, zb_count, yzt_count = len(zt), len(zb), len(yzt)
    attempts = zt_count + zb_count                       # 尝试涨停 = 封住 + 炸板
    seal_rate = round(zt_count / attempts, 3) if attempts else None      # 封板率
    break_rate = round(zb_count / attempts, 3) if attempts else None     # 炸板率
    # 晋级率＝今日 2 板+（＝昨涨停今又停）÷ 昨日涨停家数
    promotion_rate = round(len(lianban) / yzt_count, 3) if yzt_count else None

    return {
        "date": f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}",
        "zt_count": zt_count,
        "dt_count": len(dt),
        "zb_count": zb_count,
        "max_boards": max(boards) if boards else 0,
        "lianban_count": len(lianban),
        "ladder": ladder,
        "lianban_stocks": lianban_stocks,
        "seal_rate": seal_rate,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "yzt_count": yzt_count,
    }


def get_short_term_emotion() -> dict:
    """短线情绪（含缓存，5 分钟）。"""
    return _cached("emotion", _emotion)


def get_turnover_top() -> dict:
    """全市场成交额榜 Top20（含缓存 5 分钟）。"""
    def build():
        return {
            "stocks": astock.market_turnover_rank(20),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return _cached("turnover_top", build, valid=lambda v: bool(v.get("stocks")))


def get_global_indices() -> list[dict]:
    """全球指数快照（美股 / 港股，含缓存 5 分钟）。空结果不缓存。"""
    return _cached("global_indices", gstock.global_indices, valid=bool)


# ---------------------------------------------------------------------------
# 全 A 股快照共享缓存 + 市场广度（纯计算）
# ---------------------------------------------------------------------------
_AMOUNT_TOP_N = 30
_HIGH_TURNOVER_N = 30
_HIGH_TURNOVER_MIN = 15.0  # 换手率 %


def get_a_share_snapshot() -> list[dict]:
    """全 A 股行情快照（共享缓存，TTL 同模块 5 分钟）。

    调用 ``astock.a_share_snapshot()``；空列表不缓存；异常向上抛出，不伪装成空市场。
    同缓存周期内市场广度等调用方应复用本入口，避免重复分页抓取。
    """
    return _cached("a_share_snapshot", astock.a_share_snapshot, valid=bool)


def _stock_subset(s: dict, *, amount_required: bool) -> dict:
    """榜单行：从快照取必要字段子集。"""
    row = {
        "code": s.get("code", ""),
        "name": s.get("name", ""),
        "price": s.get("price"),
        "change_pct": s.get("change_pct"),
        "amount": s.get("amount"),
        "turnover_pct": s.get("turnover_pct"),
        "market_cap": s.get("market_cap"),
    }
    if amount_required:
        # amount_top 保证 amount 为 float
        row["amount"] = float(s["amount"])
    return row


def calculate_market_breadth(
    snapshot: list[dict],
    *,
    amount_top_n: int = _AMOUNT_TOP_N,
    high_turnover_n: int = _HIGH_TURNOVER_N,
    high_turnover_min: float = _HIGH_TURNOVER_MIN,
) -> dict:
    """由全 A 快照纯计算市场广度。不联网、不读缓存。

    涨跌统计仅使用 ``change_pct`` 为有效数值的股票；上涨/下跌/平盘互斥。
    """
    if not isinstance(snapshot, list):
        raise TypeError(f"snapshot must be a list, got {type(snapshot).__name__}")

    stock_count = len(snapshot)
    up_count = down_count = flat_count = 0
    up_3pct_count = down_3pct_count = 0
    valid_count = 0

    total_amount = 0.0
    amount_valid_count = 0
    has_amount = False

    amount_candidates: list[dict] = []
    turnover_candidates: list[dict] = []

    for s in snapshot:
        if not isinstance(s, dict):
            continue
        pct = s.get("change_pct")
        if isinstance(pct, (int, float)) and not isinstance(pct, bool):
            # 排除 NaN
            if pct == pct:  # noqa: PLR0124 — NaN != NaN
                valid_count += 1
                if pct > 0:
                    up_count += 1
                elif pct < 0:
                    down_count += 1
                else:
                    flat_count += 1
                if pct >= 3:
                    up_3pct_count += 1
                if pct <= -3:
                    down_3pct_count += 1

        amt = s.get("amount")
        if isinstance(amt, (int, float)) and not isinstance(amt, bool) and amt == amt and amt >= 0:
            has_amount = True
            amount_valid_count += 1
            total_amount += float(amt)
            amount_candidates.append(s)

        to = s.get("turnover_pct")
        if (
            isinstance(to, (int, float))
            and not isinstance(to, bool)
            and to == to
            and to >= high_turnover_min
        ):
            turnover_candidates.append(s)

    up_ratio = round(up_count / valid_count, 4) if valid_count else None

    amount_candidates.sort(key=lambda x: float(x["amount"]), reverse=True)
    amount_top = [
        _stock_subset(s, amount_required=True)
        for s in amount_candidates[: max(0, amount_top_n)]
    ]

    turnover_candidates.sort(key=lambda x: float(x["turnover_pct"]), reverse=True)
    high_turnover = [
        {
            "code": s.get("code", ""),
            "name": s.get("name", ""),
            "price": s.get("price"),
            "change_pct": s.get("change_pct"),
            "amount": s.get("amount"),
            "turnover_pct": float(s["turnover_pct"]),
            "market_cap": s.get("market_cap"),
        }
        for s in turnover_candidates[: max(0, high_turnover_n)]
    ]

    return {
        "stock_count": stock_count,
        "valid_count": valid_count,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "up_ratio": up_ratio,
        "up_3pct_count": up_3pct_count,
        "down_3pct_count": down_3pct_count,
        "total_amount": total_amount if has_amount else None,
        "amount_valid_count": amount_valid_count,
        "amount_top": amount_top,
        "high_turnover": high_turnover,
    }


def get_market_breadth() -> dict:
    """市场广度：取共享全 A 快照后纯计算（快照异常向上抛出）。"""
    snapshot = get_a_share_snapshot()
    return calculate_market_breadth(snapshot)
