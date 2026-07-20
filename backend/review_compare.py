"""每日复盘历史快照纯比较器（不读库、不联网、不调 AI、不改输入）。

接受两份历史详情结构（含 review），输出结构化差异：
原值 / 目标值 / delta / change_pct / 排名进入退出变化 / 状态与缺失项。

不生成投资建议、市场原因或自然语言结论。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

SCHEMA_VERSION = "daily-review-comparison-v0.1"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_BREADTH_FIELDS = (
    "stock_count",
    "valid_count",
    "up_count",
    "down_count",
    "flat_count",
    "up_ratio",
    "up_3pct_count",
    "down_3pct_count",
    "total_amount",
    "amount_valid_count",
)

_EMOTION_FIELDS = (
    "zt_count",
    "dt_count",
    "zb_count",
    "max_boards",
    "lianban_count",
    "seal_rate",
    "break_rate",
    "promotion_rate",
    "yzt_count",
)

_HIGHLIGHT_KEYS = (
    "strongest_industry",
    "weakest_industry",
    "strongest_concept",
    "weakest_concept",
    "strongest_region",
    "weakest_region",
)

_FORBIDDEN_KEYS = frozenset({
    "recommendation", "action", "position", "forecast",
    "prediction", "cause", "reason", "score",
})


def _is_number(v: Any) -> bool:
    """有效数值：int/float，排除 bool（bool 是 int 子类）。"""
    if isinstance(v, bool) or v is None:
        return False
    return isinstance(v, (int, float)) and v == v  # NaN 排除


def _round4(v: float) -> float:
    return round(v, 4)


def _num_compare(base: Any, target: Any) -> dict:
    b = base if _is_number(base) else None
    t = target if _is_number(target) else None
    # 保留真实 0；None 表示缺失
    if b is not None and t is not None:
        delta: int | float | None = t - b
        if b != 0:
            change_pct: float | None = _round4((t - b) / abs(b))
        else:
            change_pct = None
    else:
        delta = None
        change_pct = None
    return {
        "base": b if b is not None else (base if base is None else (None if isinstance(base, bool) else None)),
        "target": t if t is not None else (target if target is None else (None if isinstance(target, bool) else None)),
        "delta": delta,
        "change_pct": change_pct,
    }


def _num_compare_from_maps(base_map: dict | None, target_map: dict | None, field: str) -> dict:
    bv = base_map.get(field) if isinstance(base_map, dict) else None
    tv = target_map.get(field) if isinstance(target_map, dict) else None
    # 非数值（含 bool）在比较结构中 base/target 记为 None（不把 bool 当数）
    b = bv if _is_number(bv) else (None if bv is None or isinstance(bv, bool) else None)
    t = tv if _is_number(tv) else (None if tv is None or isinstance(tv, bool) else None)
    # 若原值是非 bool 非数值对象，仍输出 None
    if b is not None and t is not None:
        delta: int | float | None = t - b
        change_pct: float | None = _round4((t - b) / abs(b)) if b != 0 else None
    else:
        delta = None
        change_pct = None
    return {"base": b, "target": t, "delta": delta, "change_pct": change_pct}


def _as_dict(v: Any) -> dict | None:
    return v if isinstance(v, dict) else None


def _item_key(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    code = item.get("code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    name = item.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _slice_list(value: Any, limit: int) -> list:
    """复制切片，不修改原列表。"""
    if not isinstance(value, list):
        return []
    return list(value[:limit])


def _compare_ranked_lists(
    base_list: Any,
    target_list: Any,
    limit: int,
) -> dict:
    """比较排名列表。

    rank 从 1 开始。
    rank_delta = base_rank - target_rank
    （正数 → 排名上升；负数 → 排名下降；0 → 未变）
    """
    base_items = _slice_list(base_list, limit)
    target_items = _slice_list(target_list, limit)

    base_map: dict[str, tuple[int, dict]] = {}
    for i, it in enumerate(base_items):
        k = _item_key(it)
        if k is None or not isinstance(it, dict):
            continue
        if k not in base_map:  # 首次出现保留更靠前排名
            base_map[k] = (i + 1, it)

    target_map: dict[str, tuple[int, dict]] = {}
    for i, it in enumerate(target_items):
        k = _item_key(it)
        if k is None or not isinstance(it, dict):
            continue
        if k not in target_map:
            target_map[k] = (i + 1, it)

    entered: list[dict] = []
    for k, (trank, tit) in target_map.items():
        if k not in base_map:
            entered.append({"key": k, "target_rank": trank, "item": tit})
    entered.sort(key=lambda x: x["target_rank"])

    exited: list[dict] = []
    for k, (brank, bit) in base_map.items():
        if k not in target_map:
            exited.append({"key": k, "base_rank": brank, "item": bit})
    exited.sort(key=lambda x: x["base_rank"])

    rank_changes: list[dict] = []
    for k, (trank, tit) in target_map.items():
        if k in base_map:
            brank, bit = base_map[k]
            rank_changes.append({
                "key": k,
                "base_rank": brank,
                "target_rank": trank,
                "rank_delta": brank - trank,  # 正=上升，负=下降
                "base_item": bit,
                "target_item": tit,
            })
    rank_changes.sort(key=lambda x: x["target_rank"])

    return {
        "base_count": len(base_items),
        "target_count": len(target_items),
        "entered": entered,
        "exited": exited,
        "rank_changes": rank_changes,
    }


def _empty_ranked() -> dict:
    return {
        "base_count": 0,
        "target_count": 0,
        "entered": [],
        "exited": [],
        "rank_changes": [],
    }


def _highlight_pair(base_item: Any, target_item: Any) -> dict:
    b = base_item if isinstance(base_item, dict) else None
    t = target_item if isinstance(target_item, dict) else None
    if b is None and t is None:
        return {"base": None, "target": None, "changed": False}
    if b is None or t is None:
        return {"base": b, "target": t, "changed": True}
    bk = _item_key(b)
    tk = _item_key(t)
    if bk is None or tk is None:
        return {"base": b, "target": t, "changed": None}
    return {"base": b, "target": t, "changed": bk != tk}


def _meta(snapshot: dict) -> dict:
    sid = snapshot.get("id")
    if sid is not None:
        if not isinstance(sid, int) or isinstance(sid, bool) or sid < 1:
            raise ValueError("snapshot id 必须是正整数")
    return {
        "id": sid if isinstance(sid, int) and not isinstance(sid, bool) else None,
        "trade_date": snapshot.get("trade_date") if isinstance(snapshot.get("trade_date"), str) else None,
        "schema_version": snapshot.get("schema_version") if isinstance(snapshot.get("schema_version"), str) else None,
        "generated_at": snapshot.get("generated_at") if isinstance(snapshot.get("generated_at"), str) else None,
        "status": snapshot.get("status") if isinstance(snapshot.get("status"), str) else None,
    }


def _envelope_data_list(sector: dict | None, kind: str, side: str) -> list | None:
    """从 sector_rotation[kind] envelope 取 top/bottom 列表；结构不可用返回 None。"""
    if not isinstance(sector, dict):
        return None
    env = sector.get(kind)
    if not isinstance(env, dict):
        return None
    data = env.get("data")
    if not isinstance(data, dict):
        return None
    lst = data.get(side)
    if not isinstance(lst, list):
        return None
    return lst


def _board_side_comparable(base_sector: dict | None, target_sector: dict | None, kind: str) -> bool:
    """双方 top 与 bottom 均可作为 list 比较。"""
    for side in ("top", "bottom"):
        if _envelope_data_list(base_sector, kind, side) is None:
            return False
        if _envelope_data_list(target_sector, kind, side) is None:
            return False
    return True


def compare_daily_review_snapshots(
    base_snapshot: dict,
    target_snapshot: dict,
    board_limit: int = 10,
    stock_limit: int = 10,
) -> dict:
    """比较两份每日复盘历史详情，返回结构化差异（纯函数）。"""
    if not isinstance(base_snapshot, dict):
        raise TypeError("base_snapshot 必须是字典")
    if not isinstance(target_snapshot, dict):
        raise TypeError("target_snapshot 必须是字典")

    if not isinstance(board_limit, int) or isinstance(board_limit, bool) or not (1 <= board_limit <= 20):
        raise ValueError("board_limit 必须是 1 到 20 的整数")
    if not isinstance(stock_limit, int) or isinstance(stock_limit, bool) or not (1 <= stock_limit <= 30):
        raise ValueError("stock_limit 必须是 1 到 30 的整数")

    base_review = base_snapshot.get("review")
    target_review = target_snapshot.get("review")
    if not isinstance(base_review, dict):
        raise ValueError("base_snapshot.review 必须是字典")
    if not isinstance(target_review, dict):
        raise ValueError("target_snapshot.review 必须是字典")

    # id 校验（允许缺失）
    for label, snap in (("base", base_snapshot), ("target", target_snapshot)):
        sid = snap.get("id", None)
        if sid is not None and (not isinstance(sid, int) or isinstance(sid, bool) or sid < 1):
            raise ValueError(f"{label}_snapshot.id 必须是正整数")

    base_meta = _meta(base_snapshot)
    target_meta = _meta(target_snapshot)

    warnings: list[str] = []
    unknowns: list[str] = []
    status_rank = {"normal": 0, "partial": 1, "unavailable": 2}
    comparison_status = "normal"

    def elevate(to: str) -> None:
        nonlocal comparison_status
        if status_rank[to] > status_rank[comparison_status]:
            comparison_status = to

    # schema
    schema_compatible = (
        base_snapshot.get("schema_version") == target_snapshot.get("schema_version")
    )
    if not schema_compatible:
        elevate("partial")
        warnings.append("基础快照与目标快照的 schema_version 不一致")

    # snapshot status
    for label, st in (("基础", base_meta.get("status")), ("目标", target_meta.get("status"))):
        if st == "partial":
            elevate("partial")
            warnings.append(f"{label}快照状态为 partial")
        elif st == "unavailable":
            elevate("partial")
            warnings.append(f"{label}快照状态为 unavailable")

    # trade_date
    btd = base_meta.get("trade_date")
    ttd = target_meta.get("trade_date")
    if btd and ttd and _DATE_RE.match(btd) and _DATE_RE.match(ttd):
        try:
            bd = date.fromisoformat(btd)
            td = date.fromisoformat(ttd)
            if bd == td:
                warnings.append("两份快照交易日期相同")
            elif td < bd:
                warnings.append("目标交易日期早于基础交易日期")
        except ValueError:
            elevate("partial")
            warnings.append("交易日期不可比较")
    else:
        if btd is not None or ttd is not None:
            # 有值但不合法，或一侧缺失
            if (btd and not (isinstance(btd, str) and _DATE_RE.match(btd))) or (
                ttd and not (isinstance(ttd, str) and _DATE_RE.match(ttd))
            ):
                elevate("partial")
                warnings.append("交易日期不可比较")
            elif btd is None or ttd is None:
                elevate("partial")
                warnings.append("交易日期不可比较")

    # —— 市场广度 ——
    base_me = _as_dict(base_review.get("market_environment"))
    target_me = _as_dict(target_review.get("market_environment"))
    base_breadth_env = _as_dict(base_me.get("breadth")) if base_me else None
    target_breadth_env = _as_dict(target_me.get("breadth")) if target_me else None
    base_breadth = _as_dict(base_breadth_env.get("data")) if base_breadth_env else None
    target_breadth = _as_dict(target_breadth_env.get("data")) if target_breadth_env else None
    breadth_both = base_breadth is not None and target_breadth is not None
    if base_breadth is None:
        unknowns.append("基础快照市场广度不可用")
        elevate("partial")
    if target_breadth is None:
        unknowns.append("目标快照市场广度不可用")
        elevate("partial")
    market_breadth: dict[str, Any] = {"available": breadth_both}
    for f in _BREADTH_FIELDS:
        market_breadth[f] = _num_compare_from_maps(base_breadth, target_breadth, f)

    # —— 短线情绪 ——
    base_emo_env = _as_dict(base_review.get("short_term_emotion"))
    target_emo_env = _as_dict(target_review.get("short_term_emotion"))
    base_emo = _as_dict(base_emo_env.get("data")) if base_emo_env else None
    target_emo = _as_dict(target_emo_env.get("data")) if target_emo_env else None
    emo_both = base_emo is not None and target_emo is not None
    if base_emo is None:
        unknowns.append("基础快照短线情绪不可用")
        elevate("partial")
    if target_emo is None:
        unknowns.append("目标快照短线情绪不可用")
        elevate("partial")
    short_term_emotion: dict[str, Any] = {"available": emo_both}
    for f in _EMOTION_FIELDS:
        short_term_emotion[f] = _num_compare_from_maps(base_emo, target_emo, f)

    # —— 板块 ——
    base_sector = _as_dict(base_review.get("sector_rotation"))
    target_sector = _as_dict(target_review.get("sector_rotation"))

    def board_block(kind: str) -> dict:
        top_b = _envelope_data_list(base_sector, kind, "top")
        top_t = _envelope_data_list(target_sector, kind, "top")
        bot_b = _envelope_data_list(base_sector, kind, "bottom")
        bot_t = _envelope_data_list(target_sector, kind, "bottom")
        return {
            "top": _compare_ranked_lists(
                top_b if top_b is not None else [],
                top_t if top_t is not None else [],
                board_limit,
            ) if (top_b is not None or top_t is not None) else _empty_ranked(),
            "bottom": _compare_ranked_lists(
                bot_b if bot_b is not None else [],
                bot_t if bot_t is not None else [],
                board_limit,
            ) if (bot_b is not None or bot_t is not None) else _empty_ranked(),
        }

    industry_ok = _board_side_comparable(base_sector, target_sector, "industry")
    concept_ok = _board_side_comparable(base_sector, target_sector, "concept")
    region_ok = _board_side_comparable(base_sector, target_sector, "region")

    if not industry_ok:
        unknowns.append("行业板块排名不可比较")
        elevate("partial")
    if not concept_ok:
        unknowns.append("概念板块排名不可比较")
        elevate("partial")
    if not region_ok:
        unknowns.append("地域板块排名不可比较")
        elevate("partial")

    base_hl = _as_dict((_as_dict(base_sector) or {}).get("highlights")) if base_sector else None
    target_hl = _as_dict((_as_dict(target_sector) or {}).get("highlights")) if target_sector else None
    highlights = {}
    for hk in _HIGHLIGHT_KEYS:
        highlights[hk] = _highlight_pair(
            base_hl.get(hk) if base_hl else None,
            target_hl.get(hk) if target_hl else None,
        )

    sector_rotation = {
        "industry": board_block("industry"),
        "concept": board_block("concept"),
        "region": board_block("region"),
        "highlights": highlights,
    }

    # —— 资金活跃 ——
    base_cap = _as_dict(base_review.get("capital_activity"))
    target_cap = _as_dict(target_review.get("capital_activity"))
    amount_top_b = base_cap.get("amount_top") if base_cap else None
    amount_top_t = target_cap.get("amount_top") if target_cap else None
    high_to_b = base_cap.get("high_turnover") if base_cap else None
    high_to_t = target_cap.get("high_turnover") if target_cap else None

    amount_top_ok = isinstance(amount_top_b, list) and isinstance(amount_top_t, list)
    high_to_ok = isinstance(high_to_b, list) and isinstance(high_to_t, list)
    if not amount_top_ok:
        unknowns.append("成交额榜不可比较")
        elevate("partial")
    if not high_to_ok:
        unknowns.append("高换手榜不可比较")
        elevate("partial")
    if base_cap is None or target_cap is None:
        elevate("partial")

    capital_activity = {
        "total_amount": _num_compare_from_maps(base_cap, target_cap, "total_amount"),
        "amount_valid_count": _num_compare_from_maps(base_cap, target_cap, "amount_valid_count"),
        "amount_top": _compare_ranked_lists(
            amount_top_b if isinstance(amount_top_b, list) else [],
            amount_top_t if isinstance(amount_top_t, list) else [],
            stock_limit,
        ),
        "high_turnover": _compare_ranked_lists(
            high_to_b if isinstance(high_to_b, list) else [],
            high_to_t if isinstance(high_to_t, list) else [],
            stock_limit,
        ),
    }

    # —— comparison_status 最终判定 ——
    # 核心：breadth, emotion, industry, concept
    core_none = (
        not breadth_both
        and not emo_both
        and not industry_ok
        and not concept_ok
    )
    if core_none:
        comparison_status = "unavailable"
    elif comparison_status == "normal":
        # normal 需全部核心可用且 schema 兼容（schema 已在前面 elevate）
        if not (breadth_both and emo_both and industry_ok and concept_ok and schema_compatible):
            comparison_status = "partial"

    # unknowns 去重、稳定顺序、≤30
    seen: set[str] = set()
    uniq_unknowns: list[str] = []
    for u in unknowns:
        if u not in seen:
            seen.add(u)
            uniq_unknowns.append(u)
        if len(uniq_unknowns) >= 30:
            break

    # warnings 去重
    seen_w: set[str] = set()
    uniq_warnings: list[str] = []
    for w in warnings:
        if w not in seen_w:
            seen_w.add(w)
            uniq_warnings.append(w)

    return {
        "schema_version": SCHEMA_VERSION,
        "base": base_meta,
        "target": target_meta,
        "comparison_status": comparison_status,
        "schema_compatible": schema_compatible,
        "warnings": uniq_warnings,
        "market_breadth": market_breadth,
        "short_term_emotion": short_term_emotion,
        "sector_rotation": sector_rotation,
        "capital_activity": capital_activity,
        "unknowns": uniq_unknowns,
    }
