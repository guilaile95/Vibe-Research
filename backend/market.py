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


def _breadth_label(up_ratio: float | None) -> str | None:
    """大盘宽度标签（按上涨占比机械分档，不再用绝对家数）。

    up_ratio is None → None
    <0.25 冰点 · <0.40 偏弱 · <=0.60 中性 · <=0.75 偏强 · >0.75 普涨
    """
    if up_ratio is None:
        return None
    if not isinstance(up_ratio, (int, float)) or isinstance(up_ratio, bool):
        return None
    if up_ratio != up_ratio:  # NaN
        return None
    r = float(up_ratio)
    if r < 0.25:
        return "冰点"
    if r < 0.40:
        return "偏弱"
    if r <= 0.60:
        return "中性"
    if r <= 0.75:
        return "偏强"
    return "普涨"


def _speculation_label(zt_count: int | None) -> str | None:
    """题材投机标签（按涨停家数机械分档）。"""
    if zt_count is None:
        return None
    if not isinstance(zt_count, (int, float)) or isinstance(zt_count, bool):
        return None
    z = int(zt_count)
    if z >= 100:
        return "亢奋"
    if z >= 60:
        return "活跃"
    if z >= 30:
        return "普通"
    return "冰点"


def _sentiment() -> dict:
    """市场情绪：涨跌家数来自全 A 快照广度；涨跌停来自东财涨停池。

    **不再调用** ``astock._akshare().stock_market_activity_legu()``。
    复用 ``get_market_breadth()`` / ``get_short_term_emotion()`` 的共享缓存。

    兼容字段说明：
    - ``zt_real`` / ``dt_real``：仅为兼容旧前端的别名，等于 ``zt`` / ``dt``；
      东财涨跌停池本身即进入对应池的股票数，并非两套独立口径。
    - ``active``：当前表示上涨占比（up_ratio 格式化为百分数字符串），
      **不再**代表乐咕「活跃度」；后续前端应改名为「上涨占比」。
    """
    # —— 广度（涨跌家数）——
    try:
        breadth_payload = get_market_breadth()
    except Exception as e:  # noqa: BLE001 — 意外逃逸，整段 unavailable
        return {
            "status": "unavailable",
            "source": "eastmoney_push2",
            "warnings": [f"市场广度异常：{type(e).__name__}: {e}"],
            "up": None, "down": None, "flat": None,
            "zt": None, "zt_real": None, "dt": None, "dt_real": None,
            "active": "", "active_metric": "up_ratio", "up_ratio": None,
            "breadth": None, "speculation": None,
            "stock_count": None, "valid_count": None,
            "up_3pct_count": None, "down_3pct_count": None, "total_amount": None,
            "date": "",
            "limit_count_source": "eastmoney_limit_pool",
        }

    # —— 涨停池（情绪）—— 单独失败不丢广度
    emotion: dict = {}
    emotion_warns: list[str] = []
    try:
        emotion = get_short_term_emotion() or {}
        if not isinstance(emotion, dict):
            emotion = {}
            emotion_warns.append("涨跌停池数据不可用")
    except Exception as e:  # noqa: BLE001
        emotion = {}
        emotion_warns.append(f"涨跌停池数据不可用：{type(e).__name__}: {e}")

    b_status = breadth_payload.get("status") if isinstance(breadth_payload, dict) else None
    b_warns = list(breadth_payload.get("warnings") or []) if isinstance(breadth_payload, dict) else []
    b_data = breadth_payload.get("data") if isinstance(breadth_payload, dict) else None
    if not isinstance(b_data, dict):
        b_data = None

    # 涨跌停：东财池计数；zt_real/dt_real 仅为兼容旧字段的别名（非独立来源）
    zt = emotion.get("zt_count") if emotion else None
    dt = emotion.get("dt_count") if emotion else None
    if zt is not None and not isinstance(zt, (int, float)):
        zt = None
    if dt is not None and not isinstance(dt, (int, float)):
        dt = None
    if isinstance(zt, float):
        zt = int(zt)
    if isinstance(dt, float):
        dt = int(dt)
    date = str(emotion.get("date") or "") if emotion else ""

    if b_status == "unavailable" or b_data is None:
        return {
            "status": "unavailable",
            "source": "eastmoney_push2",
            "warnings": b_warns + emotion_warns,
            "up": None, "down": None, "flat": None,
            "zt": zt, "zt_real": zt, "dt": dt, "dt_real": dt,
            "active": "",
            "active_metric": "up_ratio",
            "up_ratio": None,
            "breadth": None,
            "speculation": _speculation_label(zt),
            "stock_count": None, "valid_count": None,
            "up_3pct_count": None, "down_3pct_count": None, "total_amount": None,
            "date": date,
            "limit_count_source": "eastmoney_limit_pool",
        }

    up = b_data.get("up_count")
    down = b_data.get("down_count")
    flat = b_data.get("flat_count")
    up_ratio = b_data.get("up_ratio")
    stock_count = b_data.get("stock_count")
    valid_count = b_data.get("valid_count")
    up_3pct = b_data.get("up_3pct_count")
    down_3pct = b_data.get("down_3pct_count")
    total_amount = b_data.get("total_amount")

    # active：上涨占比字符串（兼容旧「活跃度」展示位，语义已变）
    if isinstance(up_ratio, (int, float)) and not isinstance(up_ratio, bool) and up_ratio == up_ratio:
        active = f"{float(up_ratio) * 100:.1f}%"
        up_ratio_f: float | None = float(up_ratio)
    else:
        active = ""
        up_ratio_f = None

    warnings = list(b_warns)
    status = "normal" if b_status == "normal" else "partial"
    if b_status == "partial":
        status = "partial"

    # 广度 normal 但情绪池缺失 → partial
    emotion_ok = (
        bool(emotion)
        and emotion.get("zt_count") is not None
        and emotion.get("dt_count") is not None
    )
    if not emotion_ok:
        status = "partial"
        if not any("涨跌停池" in w for w in emotion_warns):
            emotion_warns.append("涨跌停池数据不可用")
    warnings.extend(emotion_warns)

    return {
        "status": status,
        "source": "eastmoney_push2",
        "warnings": warnings,
        "up": up if isinstance(up, (int, float)) and not isinstance(up, bool) else None,
        "down": down if isinstance(down, (int, float)) and not isinstance(down, bool) else None,
        "flat": flat if isinstance(flat, (int, float)) and not isinstance(flat, bool) else None,
        "zt": zt,
        "zt_real": zt,  # 兼容别名：与 zt 同源（东财涨停池），非独立统计
        "dt": dt,
        "dt_real": dt,  # 兼容别名：与 dt 同源
        "active": active,
        "active_metric": "up_ratio",
        "up_ratio": up_ratio_f,
        "breadth": _breadth_label(up_ratio_f),
        "speculation": _speculation_label(zt),
        "stock_count": stock_count if isinstance(stock_count, (int, float)) else None,
        "valid_count": valid_count if isinstance(valid_count, (int, float)) else None,
        "up_3pct_count": up_3pct if isinstance(up_3pct, (int, float)) else None,
        "down_3pct_count": down_3pct if isinstance(down_3pct, (int, float)) else None,
        "total_amount": total_amount if isinstance(total_amount, (int, float)) else None,
        "date": date,
        "limit_count_source": "eastmoney_limit_pool",
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


_BREADTH_ENVELOPE_KEYS = (
    "status", "source", "trade_date", "data_time",
    "fetched_at", "is_stale", "warnings", "data",
)
_PARTIAL_MIN_STOCKS = 3000
_PARTIAL_FIELD_RATIO = 0.8
_SOURCE = "eastmoney_push2"
_WARN_NO_TRADE_META = "源数据未提供明确交易日期和行情时间"


def _breadth_envelope(
    status: str,
    *,
    data: dict | None,
    warnings: list[str] | None = None,
    is_stale: bool = False,
) -> dict:
    """市场广度统一状态信封（get_market_breadth 唯一出口形状）。"""
    return {
        "status": status,
        "source": _SOURCE,
        "trade_date": None,
        "data_time": None,
        "fetched_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "is_stale": is_stale,
        "warnings": list(warnings or []),
        "data": data,
    }


def _partial_warnings(breadth: dict) -> list[str]:
    """根据覆盖率生成 partial warnings；不足阈值才标记。"""
    stock_count = int(breadth.get("stock_count") or 0)
    if stock_count <= 0:
        return []
    warns: list[str] = []
    if stock_count < _PARTIAL_MIN_STOCKS:
        warns.append(
            f"全市场股票数量偏少：stock_count={stock_count}（阈值 {_PARTIAL_MIN_STOCKS}）"
        )
    valid_count = int(breadth.get("valid_count") or 0)
    valid_ratio = valid_count / stock_count
    if valid_ratio < _PARTIAL_FIELD_RATIO:
        warns.append(
            f"涨跌幅字段有效比例偏低：valid_count/stock_count="
            f"{valid_count}/{stock_count}={valid_ratio:.2%}（阈值 {_PARTIAL_FIELD_RATIO:.0%}）"
        )
    amount_valid = int(breadth.get("amount_valid_count") or 0)
    amount_ratio = amount_valid / stock_count
    if amount_ratio < _PARTIAL_FIELD_RATIO:
        warns.append(
            f"成交额字段有效比例偏低：amount_valid_count/stock_count="
            f"{amount_valid}/{stock_count}={amount_ratio:.2%}（阈值 {_PARTIAL_FIELD_RATIO:.0%}）"
        )
    return warns


def get_market_breadth() -> dict:
    """市场广度状态信封（始终返回统一结构，不抛出数据源异常）。

    - normal：覆盖充分的完整统计
    - partial：有数据但 stock 数或字段覆盖率不足
    - unavailable：空快照或获取/计算失败（data=None，不伪造全 0）
    """
    try:
        snapshot = get_a_share_snapshot()
    except Exception as e:  # noqa: BLE001 — 外部数据边界，转 unavailable
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=[f"全市场快照获取失败：{type(e).__name__}: {e}"],
            is_stale=False,
        )

    if not snapshot:
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=["全市场快照为空"],
            is_stale=False,
        )

    try:
        breadth = calculate_market_breadth(snapshot)
    except Exception as e:  # noqa: BLE001
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=[f"全市场快照获取失败：{type(e).__name__}: {e}"],
            is_stale=False,
        )

    stock_count = int(breadth.get("stock_count") or 0)
    if stock_count <= 0:
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=["全市场快照为空"],
            is_stale=False,
        )

    partial_warns = _partial_warnings(breadth)
    base_warns = [_WARN_NO_TRADE_META]
    if partial_warns:
        return _breadth_envelope(
            "partial",
            data=breadth,
            warnings=base_warns + partial_warns,
            is_stale=False,
        )
    return _breadth_envelope(
        "normal",
        data=breadth,
        warnings=base_warns,
        is_stale=False,
    )


# ---------------------------------------------------------------------------
# 板块排名共享缓存 + 状态信封（industry / concept / region）
# ---------------------------------------------------------------------------
_BOARD_TYPES = frozenset({"industry", "concept", "region"})
_BOARD_CACHE_TOP_N = 100  # 缓存固定抓取前 100，页面再切片


def get_cached_board_ranking(board_type: str) -> dict:
    """板块排名底层结果（共享缓存，TTL 同模块 5 分钟）。

    固定调用 ``astock.board_ranking(board_type, top_n=100)``。
    空结果不缓存；异常向上抛出，由 ``get_board_ranking`` 转为 unavailable。
    """
    if board_type not in _BOARD_TYPES:
        raise ValueError(f"不支持的板块类型：{board_type}")

    def fetch():
        return astock.board_ranking(board_type, top_n=_BOARD_CACHE_TOP_N)

    # valid：total>0 且有 ranked 才缓存；空/全不可用下次重试
    def _valid(raw) -> bool:
        if not isinstance(raw, dict):
            return False
        return bool(raw.get("total")) and bool(raw.get("ranked_count"))

    return _cached(f"board_ranking:{board_type}", fetch, valid=_valid)


def get_board_ranking(board_type: str = "industry", top_n: int = 20) -> dict:
    """板块排名状态信封（始终返回统一结构）。

    - 参数非法（类型 / top_n）→ 抛出 ValueError（不转 unavailable）
    - 数据源/结构异常、无有效排名 → status=unavailable, data=None
    - 有排名但存在缺涨跌幅 → partial
    - 全部有涨跌幅 → normal

    缓存抓取 top_n=100，本函数按请求 top_n 切片，不改数值、不重排。
    """
    if board_type not in _BOARD_TYPES:
        raise ValueError(f"不支持的板块类型：{board_type}")
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not (1 <= top_n <= 100):
        raise ValueError(f"top_n 必须在 1..100 之间，收到：{top_n!r}")

    try:
        raw = get_cached_board_ranking(board_type)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001 — 外部数据边界
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=[f"板块排名数据不可用：{type(e).__name__}: {e}"],
            is_stale=False,
        )

    if not isinstance(raw, dict):
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=["板块排名数据不可用：结果结构异常"],
            is_stale=False,
        )

    try:
        total = int(raw.get("total") or 0)
        ranked_count = int(raw.get("ranked_count") or 0)
        unknown_count = int(raw.get("unknown_count") or 0)
        top = list(raw.get("top") or [])
        bottom = list(raw.get("bottom") or [])
        amount_top = list(raw.get("amount_top") or [])
    except (TypeError, ValueError) as e:
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=[f"板块排名数据不可用：{type(e).__name__}: {e}"],
            is_stale=False,
        )

    if total <= 0 or ranked_count <= 0:
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=["板块排名数据不可用：无有效涨跌幅排名"],
            is_stale=False,
        )

    data = {
        "type": raw.get("type") or board_type,
        "total": total,
        "ranked_count": ranked_count,
        "unknown_count": unknown_count,
        "top": top[:top_n],
        "bottom": bottom[:top_n],
        "amount_top": amount_top[:top_n],
    }

    base_warns = [_WARN_NO_TRADE_META]
    if unknown_count > 0 or ranked_count < total:
        return _breadth_envelope(
            "partial",
            data=data,
            warnings=base_warns + [f"有 {unknown_count} 个板块缺少有效涨跌幅"],
            is_stale=False,
        )
    return _breadth_envelope(
        "normal",
        data=data,
        warnings=base_warns,
        is_stale=False,
    )


# ---------------------------------------------------------------------------
# 市场云图（全 A 股按行业分组 · 面积=流通市值 · 颜色=涨跌幅）
# ---------------------------------------------------------------------------
_MARKET_CLOUD_SCOPES = frozenset({"all", "cyb", "star", "sh", "sz"})
_MARKET_CLOUD_PERIODS = frozenset({"today"})


def _filter_by_scope(snapshot: list[dict], scope: str) -> list[dict]:
    """按市场范围过滤全 A 快照。V1 基于代码前缀，不使用估算成分。"""
    if scope == "all":
        return snapshot
    if scope == "cyb":
        return [s for s in snapshot if str(s.get("code", "")).startswith("30")]
    if scope == "star":
        return [s for s in snapshot if str(s.get("code", "")).startswith("68")]
    if scope == "sh":
        return [s for s in snapshot if str(s.get("code", "")).startswith(("60", "68"))]
    if scope == "sz":
        return [s for s in snapshot if str(s.get("code", "")).startswith(("00", "30"))]
    return snapshot


def get_market_cloud(scope: str = "all", period: str = "today") -> dict:
    """市场云图状态信封：全 A 股按行业分组，面积=流通市值，颜色=涨跌幅。

    V1 仅支持 period=today。scope 支持 all/cyb/star/sh/sz（基于代码前缀）。
    沪深300/A50/A500/自选需要真实成分数据，V1 不开放。
    缺流通市值或缺涨跌幅的股票不进入云图（不伪造 0），计入 partial。
    """
    if scope not in _MARKET_CLOUD_SCOPES:
        raise ValueError(f"不支持的市场范围：{scope}")
    if period not in _MARKET_CLOUD_PERIODS:
        raise ValueError(f"不支持的周期：{period}（V1 仅支持 today）")

    try:
        snapshot = get_a_share_snapshot()
    except Exception as e:  # noqa: BLE001
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=[f"全市场快照不可用：{type(e).__name__}: {e}"],
            is_stale=False,
        )

    if not isinstance(snapshot, list) or not snapshot:
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=["全市场快照为空"],
            is_stale=False,
        )

    filtered = _filter_by_scope(snapshot, scope)
    stock_count = len(filtered)

    # 有效股票：同时有流通市值和涨跌幅
    valid: list[dict] = []
    missing_cap = 0
    missing_pct = 0
    for s in filtered:
        cap = s.get("float_market_cap")
        pct = s.get("change_pct")
        has_cap = isinstance(cap, (int, float)) and not isinstance(cap, bool) and cap == cap and cap > 0
        has_pct = isinstance(pct, (int, float)) and not isinstance(pct, bool) and pct == pct
        if has_cap and has_pct:
            valid.append(s)
        else:
            if not has_cap:
                missing_cap += 1
            if not has_pct:
                missing_pct += 1

    if not valid:
        return _breadth_envelope(
            "unavailable",
            data=None,
            warnings=["无有效股票数据（缺流通市值或涨跌幅）"],
            is_stale=False,
        )

    # 按行业分组
    industry_map: dict[str, list[dict]] = {}
    no_industry: list[dict] = []
    for s in valid:
        ind = s.get("industry")
        if not ind:
            no_industry.append(s)
            continue
        industry_map.setdefault(ind, []).append(s)

    industries = []
    for ind_name, stocks in industry_map.items():
        total_cap = sum(float(s["float_market_cap"]) for s in stocks)
        up = sum(1 for s in stocks if float(s["change_pct"]) > 0)
        down = sum(1 for s in stocks if float(s["change_pct"]) < 0)
        avg_pct = round(sum(float(s["change_pct"]) for s in stocks) / len(stocks), 4)
        # 行业内按流通市值降序
        stocks_sorted = sorted(stocks, key=lambda x: float(x["float_market_cap"]), reverse=True)
        industries.append({
            "name": ind_name,
            "stock_count": len(stocks),
            "total_float_cap": total_cap,
            "avg_change_pct": avg_pct,
            "up_count": up,
            "down_count": down,
            "stocks": [
                {
                    "code": s["code"],
                    "name": s["name"],
                    "price": s.get("price"),
                    "change_pct": float(s["change_pct"]),
                    "amount": s.get("amount"),
                    "float_market_cap": float(s["float_market_cap"]),
                    "turnover_pct": s.get("turnover_pct"),
                    "industry": ind_name,
                }
                for s in stocks_sorted
            ],
        })

    # 行业按总流通市值降序
    industries.sort(key=lambda x: x["total_float_cap"], reverse=True)

    data = {
        "scope": scope,
        "period": period,
        "stock_count": stock_count,
        "valid_count": len(valid),
        "industry_count": len(industries),
        "no_industry_count": len(no_industry),
        "industries": industries,
    }

    warnings = []
    if missing_cap > 0 or missing_pct > 0:
        warnings.append(f"有 {missing_cap} 只缺流通市值、{missing_pct} 只缺涨跌幅，未进入云图")
    if no_industry:
        warnings.append(f"有 {len(no_industry)} 只股票无行业归属，未进入云图")

    if warnings:
        return _breadth_envelope("partial", data=data, warnings=warnings, is_stale=False)
    return _breadth_envelope("normal", data=data, warnings=[], is_stale=False)
