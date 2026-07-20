"""结构化每日复盘数据聚合器 —— 只聚合客观数据，不生成建议/AI 结论。

复用 market / astock 已有缓存入口，不直接请求外部数据源，不调用
market.get_overview / _sentiment / _sectors（避免隐式 AKShare）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta

import astock
import market

BEIJING = timezone(timedelta(hours=8))
SCHEMA_VERSION = "daily-review-v0.1"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 核心组件（决定整体 status）/ 可选组件
_CORE_COMPONENTS = ("indices", "breadth", "emotion", "industry_boards", "concept_boards")
_OPTIONAL_COMPONENTS = ("global_indices", "turnover", "region_boards")

_WARN_NO_CUTOFF = "各数据源尚未提供统一的数据截止时间"

# 组件展示前缀
_PREFIX = {
    "indices": "大盘指数",
    "global_indices": "全球指数",
    "breadth": "市场广度",
    "emotion": "短线情绪",
    "turnover": "成交额榜",
    "industry_boards": "行业板块",
    "concept_boards": "概念板块",
    "region_boards": "地域板块",
}


def _now_str() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _wrap(
    status: str,
    *,
    source: str,
    data,
    warnings: list[str] | None = None,
) -> dict:
    """将原始数据包装为统一组件信封（无 status 的源用此包装）。"""
    return {
        "status": status,
        "source": source,
        "warnings": list(warnings or []),
        "data": data,
    }


def _safe_call(fn, *, source: str, empty_check=None, label: str = ""):
    """调用无状态信封的数据函数；失败 → unavailable，不向外抛。"""
    try:
        raw = fn()
    except Exception as e:  # noqa: BLE001
        return _wrap(
            "unavailable",
            source=source,
            data=None,
            warnings=[f"{type(e).__name__}: {e}"],
        )
    if empty_check is not None and empty_check(raw):
        return _wrap(
            "unavailable",
            source=source,
            data=None,
            warnings=["无有效数据"],
        )
    return _wrap("normal", source=source, data=raw, warnings=[])


def _pass_envelope(env, *, fallback_source: str = "eastmoney_push2") -> dict:
    """已有状态信封的源：原样保留字段；异常输入 → unavailable。"""
    if not isinstance(env, dict) or "status" not in env:
        return {
            "status": "unavailable",
            "source": fallback_source,
            "trade_date": None,
            "data_time": None,
            "fetched_at": None,
            "is_stale": False,
            "warnings": ["状态信封结构异常"],
            "data": None,
        }
    return env


def _highlights_from_board(env: dict) -> tuple[dict | None, dict | None]:
    data = env.get("data") if isinstance(env, dict) else None
    if not isinstance(data, dict):
        return None, None
    top = data.get("top") or []
    bottom = data.get("bottom") or []
    strong = top[0] if top else None
    weak = bottom[0] if bottom else None
    return strong, weak


def _valid_trade_date(value) -> tuple[str | None, str | None]:
    """返回 (date|None, warning|None)。"""
    if value is None or value == "":
        return None, None
    s = str(value).strip()
    if _DATE_RE.match(s):
        return s, None
    return None, f"交易日期格式无效：{s!r}（期望 YYYY-MM-DD）"


def _component_status(comp: dict | None) -> str:
    if not isinstance(comp, dict):
        return "unavailable"
    st = comp.get("status")
    if st in ("normal", "partial", "unavailable"):
        return st
    return "unavailable"


def _overall_status(components: dict[str, str]) -> str:
    core = [components[k] for k in _CORE_COMPONENTS]
    if all(s == "unavailable" for s in core):
        return "unavailable"
    # indices + breadth 同时不可用，且其他核心也不足以形成有效 A 股复盘
    # 规格：indices 和 breadth 同时 unavailable，且其他核心数据不足以形成有效复盘
    if components["indices"] == "unavailable" and components["breadth"] == "unavailable":
        others = [components[k] for k in ("emotion", "industry_boards", "concept_boards")]
        if all(s == "unavailable" for s in others):
            return "unavailable"
        # 其他核心仍有可用 → partial
        return "partial"
    if all(s == "normal" for s in core):
        return "normal"
    # 至少一个核心 partial，或至少一个核心 unavailable 但仍有可用核心
    return "partial"


def _collect_warnings(
    *,
    top_level: list[str],
    labeled: list[tuple[str, list[str]]],
) -> list[str]:
    """去重、稳定顺序；组件 warning 加前缀。"""
    out: list[str] = []
    seen: set[str] = set()

    def add(msg: str):
        if msg and msg not in seen:
            seen.add(msg)
            out.append(msg)

    for w in top_level:
        add(w)
    for label, warns in labeled:
        prefix = _PREFIX.get(label, label)
        for w in warns or []:
            text = str(w)
            # 已带前缀则不再套一层
            full = text if text.startswith("[") else f"[{prefix}] {text}"
            add(full)
    return out


def generate_daily_review() -> dict:
    """聚合当日复盘客观数据（不调用 AI、不写库、不生成建议）。"""
    top_warnings: list[str] = [_WARN_NO_CUTOFF]
    labeled_warns: list[tuple[str, list[str]]] = []

    # —— 大盘指数 ——
    indices = _safe_call(
        astock.index_quote,
        source="tencent_quote",
        empty_check=lambda x: not x,
    )
    labeled_warns.append(("indices", indices.get("warnings") or []))

    # —— 全球指数 ——
    global_indices = _safe_call(
        market.get_global_indices,
        source="eastmoney_global_indices",
        empty_check=lambda x: not x,
    )
    labeled_warns.append(("global_indices", global_indices.get("warnings") or []))

    # —— 市场广度（已信封，只调一次）——
    try:
        breadth_raw = market.get_market_breadth()
    except Exception as e:  # noqa: BLE001
        breadth_raw = {
            "status": "unavailable",
            "source": "eastmoney_push2",
            "trade_date": None,
            "data_time": None,
            "fetched_at": None,
            "is_stale": False,
            "warnings": [f"{type(e).__name__}: {e}"],
            "data": None,
        }
    breadth = _pass_envelope(breadth_raw)
    labeled_warns.append(("breadth", breadth.get("warnings") or []))

    # —— 短线情绪 ——
    try:
        emo_raw = market.get_short_term_emotion()
    except Exception as e:  # noqa: BLE001
        emotion = _wrap(
            "unavailable",
            source="eastmoney_limit_pool",
            data=None,
            warnings=[f"{type(e).__name__}: {e}"],
        )
    else:
        if not isinstance(emo_raw, dict) or emo_raw.get("zt_count") is None:
            emotion = _wrap(
                "unavailable",
                source="eastmoney_limit_pool",
                data=None,
                warnings=["无有效涨跌停池数据"],
            )
        else:
            # 只保留约定字段子集（原样数值，不重算比率）
            emotion = _wrap(
                "normal",
                source="eastmoney_limit_pool",
                data={
                    "date": emo_raw.get("date", ""),
                    "zt_count": emo_raw.get("zt_count"),
                    "dt_count": emo_raw.get("dt_count"),
                    "zb_count": emo_raw.get("zb_count"),
                    "max_boards": emo_raw.get("max_boards"),
                    "lianban_count": emo_raw.get("lianban_count"),
                    "ladder": emo_raw.get("ladder") or [],
                    "seal_rate": emo_raw.get("seal_rate"),
                    "break_rate": emo_raw.get("break_rate"),
                    "promotion_rate": emo_raw.get("promotion_rate"),
                    "yzt_count": emo_raw.get("yzt_count"),
                    "lianban_stocks": emo_raw.get("lianban_stocks") or [],
                },
                warnings=[],
            )
    labeled_warns.append(("emotion", emotion.get("warnings") or []))

    # —— 成交额榜（旧兼容）——
    # amount_top 来自统一全 A 快照广度；turnover_top 是项目原有榜单，暂时同时保留
    turnover = _safe_call(
        market.get_turnover_top,
        source="eastmoney_market_snapshot",
        empty_check=lambda x: not isinstance(x, dict) or not x.get("stocks"),
    )
    labeled_warns.append(("turnover", turnover.get("warnings") or []))

    # —— 板块排名 ——
    def _board(kind: str):
        try:
            env = market.get_board_ranking(kind, top_n=10)
        except Exception as e:  # noqa: BLE001
            env = {
                "status": "unavailable",
                "source": "eastmoney_push2",
                "trade_date": None,
                "data_time": None,
                "fetched_at": None,
                "is_stale": False,
                "warnings": [f"{type(e).__name__}: {e}"],
                "data": None,
            }
        return _pass_envelope(env)

    industry = _board("industry")
    concept = _board("concept")
    region = _board("region")
    labeled_warns.append(("industry_boards", industry.get("warnings") or []))
    labeled_warns.append(("concept_boards", concept.get("warnings") or []))
    labeled_warns.append(("region_boards", region.get("warnings") or []))

    # —— 板块亮点 ——
    si, wi = _highlights_from_board(industry)
    sc, wc = _highlights_from_board(concept)
    sr, wr = _highlights_from_board(region)

    # —— 资金活跃：来自同一次 breadth ——
    b_data = breadth.get("data") if isinstance(breadth.get("data"), dict) else None
    if b_data and breadth.get("status") != "unavailable":
        total_amount = b_data.get("total_amount")
        amount_valid_count = b_data.get("amount_valid_count")
        amount_top = list(b_data.get("amount_top") or [])
        high_turnover = list(b_data.get("high_turnover") or [])
    else:
        total_amount = None
        amount_valid_count = None
        amount_top = []
        high_turnover = []

    # —— trade_date ——
    trade_date = None
    emo_date = None
    if emotion.get("status") == "normal" and isinstance(emotion.get("data"), dict):
        emo_date = emotion["data"].get("date")
    td, tw = _valid_trade_date(emo_date)
    if tw:
        top_warnings.append(tw)
    if td:
        trade_date = td
    else:
        bt = breadth.get("trade_date")
        td2, tw2 = _valid_trade_date(bt)
        if tw2:
            top_warnings.append(tw2)
        if td2:
            trade_date = td2

    # —— data_health ——
    components = {
        "indices": _component_status(indices),
        "global_indices": _component_status(global_indices),
        "breadth": _component_status(breadth),
        "emotion": _component_status(emotion),
        "turnover": _component_status(turnover),
        "industry_boards": _component_status(industry),
        "concept_boards": _component_status(concept),
        "region_boards": _component_status(region),
    }
    status = _overall_status(components)
    warnings = _collect_warnings(top_level=top_warnings, labeled=labeled_warns)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_str(),
        "trade_date": trade_date,
        "data_cutoff": None,
        "status": status,
        "warnings": warnings,
        "data_health": {"components": components},
        "market_environment": {
            "indices": indices,
            "global_indices": global_indices,
            "breadth": breadth,
        },
        "sector_rotation": {
            "industry": industry,
            "concept": concept,
            "region": region,
            "highlights": {
                "strongest_industry": si,
                "weakest_industry": wi,
                "strongest_concept": sc,
                "weakest_concept": wc,
                "strongest_region": sr,
                "weakest_region": wr,
            },
        },
        "short_term_emotion": emotion,
        "capital_activity": {
            "turnover_top": turnover,
            "total_amount": total_amount,
            "amount_valid_count": amount_valid_count,
            "amount_top": amount_top,
            "high_turnover": high_turnover,
        },
    }
