"""每日复盘 → AI 上下文投影器（纯函数，不联网、不改输入、不生成结论）。

将 generate_daily_review() 的完整数据包压缩为有限长度、结构稳定、可审计的
事实上下文，供后续聊天接口注入。本模块不调用 AI、不写库、不给买卖建议。
"""

from __future__ import annotations

import copy
import json
from typing import Any

SCHEMA_VERSION = "daily-review-ai-context-v0.1"

_HIGHLIGHT_KEYS = (
    "strongest_industry",
    "weakest_industry",
    "strongest_concept",
    "weakest_concept",
    "strongest_region",
    "weakest_region",
)

# 与 daily_review.data_health.components 常见键顺序一致
_COMPONENT_ORDER = (
    "indices",
    "global_indices",
    "breadth",
    "emotion",
    "turnover",
    "industry_boards",
    "concept_boards",
    "region_boards",
)

_FORBIDDEN_KEYS = frozenset({
    "recommendation", "suggestion", "action", "position",
    "forecast", "prediction", "cause", "reason", "score",
    "market_summary", "market_regime", "risk_level",
    "opportunity", "threat",
})


def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _dedupe_strings(items: list[Any], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, str):
            continue
        s = it.strip() if it else ""
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _slice_list(value: Any, limit: int) -> list:
    """复制切片，不修改原列表。"""
    if not isinstance(value, list):
        return []
    return list(value[:limit])


def _envelope_status(env: Any) -> str:
    if not isinstance(env, dict):
        return "unavailable"
    st = env.get("status")
    if st in ("normal", "partial", "unavailable"):
        return st
    return "unavailable"


def _project_breadth(me: dict) -> dict | None:
    env = me.get("breadth")
    if not isinstance(env, dict):
        return None
    data = env.get("data")
    if not isinstance(data, dict):
        return None
    warns = _dedupe_strings(_as_list(env.get("warnings")), limit=20)
    return {
        "status": _envelope_status(env),
        "source": env.get("source") if isinstance(env.get("source"), str) else None,
        "warnings": warns,
        "stock_count": data.get("stock_count"),
        "valid_count": data.get("valid_count"),
        "up_count": data.get("up_count"),
        "down_count": data.get("down_count"),
        "flat_count": data.get("flat_count"),
        "up_ratio": data.get("up_ratio"),
        "up_3pct_count": data.get("up_3pct_count"),
        "down_3pct_count": data.get("down_3pct_count"),
        "total_amount": data.get("total_amount"),
        "amount_valid_count": data.get("amount_valid_count"),
    }


def _project_emotion(review: dict, *, stock_limit: int) -> dict | None:
    env = review.get("short_term_emotion")
    if not isinstance(env, dict):
        return None
    data = env.get("data")
    if not isinstance(data, dict):
        return None
    warns = _dedupe_strings(_as_list(env.get("warnings")), limit=20)
    return {
        "status": _envelope_status(env),
        "source": env.get("source") if isinstance(env.get("source"), str) else None,
        "warnings": warns,
        "date": data.get("date"),
        "zt_count": data.get("zt_count"),
        "dt_count": data.get("dt_count"),
        "zb_count": data.get("zb_count"),
        "max_boards": data.get("max_boards"),
        "lianban_count": data.get("lianban_count"),
        "seal_rate": data.get("seal_rate"),
        "break_rate": data.get("break_rate"),
        "promotion_rate": data.get("promotion_rate"),
        "yzt_count": data.get("yzt_count"),
        "ladder": _slice_list(data.get("ladder"), 20),
        "lianban_stocks": _slice_list(data.get("lianban_stocks"), stock_limit),
    }


def _project_board_side(env: Any, *, board_limit: int) -> dict:
    status = _envelope_status(env)
    if not isinstance(env, dict):
        return {"status": status, "strongest": [], "weakest": []}
    data = env.get("data")
    if not isinstance(data, dict) or status == "unavailable":
        # unavailable 不伪装成空的 normal 榜单数据
        return {"status": status, "strongest": [], "weakest": []}
    return {
        "status": status,
        "strongest": _slice_list(data.get("top"), board_limit),
        "weakest": _slice_list(data.get("bottom"), board_limit),
    }


def _project_highlights(sector: dict) -> dict:
    raw = sector.get("highlights") if isinstance(sector.get("highlights"), dict) else {}
    out: dict[str, Any] = {}
    for k in _HIGHLIGHT_KEYS:
        out[k] = raw.get(k) if k in raw else None
        # 允许 None；若值存在则浅拷贝字典，避免共享可变引用
        v = out[k]
        if isinstance(v, dict):
            out[k] = dict(v)
        elif v is not None and not isinstance(v, (str, int, float, bool)):
            out[k] = copy.deepcopy(v)
    return out


def _project_capital(review: dict, *, stock_limit: int) -> dict:
    ca = _as_dict(review.get("capital_activity"))
    return {
        "total_amount": ca.get("total_amount"),
        "amount_valid_count": ca.get("amount_valid_count"),
        "amount_top": _slice_list(ca.get("amount_top"), stock_limit),
        "high_turnover": _slice_list(ca.get("high_turnover"), stock_limit),
        # 刻意不纳入旧 turnover_top，避免与 amount_top 重复
    }


def _build_unknowns(
    review: dict,
    *,
    components: dict,
    unavailable: list[str],
    partial: list[str],
    breadth_proj: dict | None,
    emotion_proj: dict | None,
    sector_proj: dict,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(msg: str):
        if msg and msg not in seen:
            seen.add(msg)
            out.append(msg)

    status = review.get("status")
    if status == "partial":
        add("每日复盘数据部分缺失")
    elif status == "unavailable":
        add("每日复盘核心数据不可用")

    for name in unavailable:
        add(f"组件不可用：{name}")
    for name in partial:
        add(f"组件数据部分缺失：{name}")

    if not review.get("trade_date"):
        add("缺少明确交易日期")
    if review.get("data_cutoff") is None:
        add("缺少统一数据截止时间")

    if breadth_proj is None or components.get("breadth") == "unavailable":
        add("市场广度不可用")
    if emotion_proj is None or components.get("emotion") == "unavailable":
        add("短线情绪不可用")
    if sector_proj.get("industry", {}).get("status") == "unavailable":
        add("行业板块排名不可用")
    if sector_proj.get("concept", {}).get("status") == "unavailable":
        add("概念板块排名不可用")

    return out[:30]


def build_daily_review_ai_context(
    review: dict,
    board_limit: int = 5,
    stock_limit: int = 10,
) -> dict:
    """将完整每日复盘包投影为 AI 上下文（事实 + 数据状态，无结论）。"""
    if not isinstance(review, dict):
        raise TypeError("review 必须是字典")
    if not isinstance(board_limit, int) or isinstance(board_limit, bool) or not (1 <= board_limit <= 20):
        raise ValueError(f"board_limit 必须在 1..20 之间，收到：{board_limit!r}")
    if not isinstance(stock_limit, int) or isinstance(stock_limit, bool) or not (1 <= stock_limit <= 30):
        raise ValueError(f"stock_limit 必须在 1..30 之间，收到：{stock_limit!r}")

    # 只读访问，不修改 review
    me = _as_dict(review.get("market_environment"))
    health = _as_dict(review.get("data_health"))
    components_raw = _as_dict(health.get("components"))

    # 保持 components 原有顺序：先已知顺序，再补其余键
    components: dict[str, str] = {}
    for k in _COMPONENT_ORDER:
        if k in components_raw:
            components[k] = str(components_raw[k])
    for k, v in components_raw.items():
        if k not in components:
            components[k] = str(v)

    unavailable = [k for k, st in components.items() if st == "unavailable"]
    partial = [k for k, st in components.items() if st == "partial"]

    warnings = _dedupe_strings(_as_list(review.get("warnings")), limit=20)

    indices = _slice_list(_as_dict(me.get("indices")).get("data"), 20)
    global_indices = _slice_list(_as_dict(me.get("global_indices")).get("data"), 20)

    breadth_proj = _project_breadth(me)
    emotion_proj = _project_emotion(review, stock_limit=stock_limit)

    sector = _as_dict(review.get("sector_rotation"))
    sector_proj = {
        "industry": _project_board_side(sector.get("industry"), board_limit=board_limit),
        "concept": _project_board_side(sector.get("concept"), board_limit=board_limit),
        "region": _project_board_side(sector.get("region"), board_limit=board_limit),
        "highlights": _project_highlights(sector),
    }

    capital = _project_capital(review, stock_limit=stock_limit)

    unknowns = _build_unknowns(
        review,
        components=components,
        unavailable=unavailable,
        partial=partial,
        breadth_proj=breadth_proj,
        emotion_proj=emotion_proj,
        sector_proj=sector_proj,
    )

    ctx = {
        "schema_version": SCHEMA_VERSION,
        "review_metadata": {
            "review_schema_version": _str_or_none(review.get("schema_version")),
            "generated_at": _str_or_none(review.get("generated_at")),
            "trade_date": _str_or_none(review.get("trade_date")),
            "data_cutoff": review.get("data_cutoff") if review.get("data_cutoff") is not None else None,
            "status": str(review.get("status") or "unavailable"),
        },
        "data_health": {
            "components": components,
            "warnings": warnings,
            "unavailable_components": unavailable,
            "partial_components": partial,
        },
        "market_environment": {
            "indices": indices,
            "global_indices": global_indices,
            "breadth": breadth_proj,
        },
        "short_term_emotion": emotion_proj,
        "sector_rotation": sector_proj,
        "capital_activity": capital,
        "unknowns": unknowns,
    }
    return ctx


def render_daily_review_ai_context(
    review: dict,
    board_limit: int = 5,
    stock_limit: int = 10,
) -> str:
    """将 AI 上下文渲染为紧凑 JSON 字符串（无 Markdown、无前后缀）。"""
    context = build_daily_review_ai_context(
        review, board_limit=board_limit, stock_limit=stock_limit,
    )
    return json.dumps(
        context,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    )
