"""结构化每日复盘数据聚合器 —— 只聚合客观数据，不生成建议/AI 结论。

复用 market / astock 已有缓存入口，不直接请求外部数据源，不调用
market.get_overview / _sentiment / _sectors（避免隐式 AKShare）。

完整结果缓存：进程内 TTL 与 market 子缓存一致（300s）；仅缓存
status 为 normal / partial 的成功包；single-flight 避免并发重复聚合。

展示路径另支持磁盘「最近成功」结果：重启后可立即返回 stale 并后台刷新。
持仓建议等业务仍调用 generate_daily_review()，只用 fresh 内存/实时聚合。
"""

from __future__ import annotations

import copy
import re
import threading
import time
from datetime import datetime, timezone, timedelta

import logging

import astock
import daily_review_cache
import daily_review_errors
import market

_log = logging.getLogger("vibe.daily_review")

BEIJING = timezone(timedelta(hours=8))
SCHEMA_VERSION = "daily-review-v0.1"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 核心组件（决定整体 status）/ 可选组件
_CORE_COMPONENTS = ("indices", "breadth", "emotion", "industry_boards", "concept_boards")
_OPTIONAL_COMPONENTS = ("global_indices", "turnover", "region_boards")

_WARN_NO_CUTOFF = "各数据源尚未提供统一的数据截止时间"

# 完整复盘结果缓存（进程内；与 market 子缓存 TTL 对齐）
_REVIEW_TTL = 300
_REVIEW_CACHE_KEY = "default"
_review_cache: dict[str, tuple[float, dict]] = {}
_review_lock = threading.Lock()

# 后台刷新 single-flight（仅展示路径）
_bg_refresh_lock = threading.Lock()
_bg_refreshing = False
_refresh_failed = False
_refresh_error: str | None = None

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
        _log.warning("daily_review component failed source=%s: %s", source, e, exc_info=False)
        safe = daily_review_errors.sanitize_public_message(
            f"{type(e).__name__}: {e}",
            default=daily_review_errors.SAFE_MARKET_COMPONENT_UNAVAILABLE,
        )
        if "eastmoney" in source or "snapshot" in source or source == "eastmoney_push2":
            # 广度/东财类优先统一广度文案
            if "breadth" in label or "市场广度" in label or "clist" in str(e).lower() or "a_share" in str(e).lower():
                safe = daily_review_errors.SAFE_BREADTH_UNAVAILABLE
        return _wrap(
            "unavailable",
            source=source,
            data=None,
            warnings=[safe],
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
        add(daily_review_errors.sanitize_public_message(str(w)) if w else "")
    for label, warns in labeled:
        prefix = _PREFIX.get(label, label)
        for w in warns or []:
            text = daily_review_errors.sanitize_public_message(str(w))
            # 已带前缀则不再套一层
            full = text if text.startswith("[") else f"[{prefix}] {text}"
            add(full)
    return out


def _clear_review_cache() -> None:
    """清空进程内完整复盘缓存（仅测试 / 运维；默认不删磁盘）。"""
    _review_cache.clear()


def _clear_refresh_failure() -> None:
    global _refresh_failed, _refresh_error
    with _bg_refresh_lock:
        _refresh_failed = False
        _refresh_error = None


def _set_refresh_failure(msg: str | None = None) -> None:
    global _refresh_failed, _refresh_error
    with _bg_refresh_lock:
        _refresh_failed = True
        _refresh_error = msg or daily_review_errors.SAFE_REFRESH_FAILED


def _refresh_failure_state() -> tuple[bool, str | None]:
    with _bg_refresh_lock:
        return _refresh_failed, _refresh_error


def _cached_review() -> dict | None:
    """返回未过期的缓存包（原对象，调用方须 deepcopy）；未命中返回 None。"""
    hit = _review_cache.get(_REVIEW_CACHE_KEY)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts >= _REVIEW_TTL:
        return None
    if not isinstance(val, dict):
        return None
    return val


def _cached_review_age_seconds() -> float | None:
    hit = _review_cache.get(_REVIEW_CACHE_KEY)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts >= _REVIEW_TTL or not isinstance(val, dict):
        return None
    return max(0.0, time.time() - ts)


def _should_cache_review(result) -> bool:
    """仅缓存结构合法且 status 为 normal / partial 的成功包。"""
    if not isinstance(result, dict):
        return False
    return result.get("status") in ("normal", "partial")


def _should_replace_memory(result: dict) -> bool:
    """内存写入质量规则：关键组件不可用不写入；partial 不覆盖已有 normal。"""
    if not _should_cache_review(result):
        return False
    if daily_review_cache.has_critical_unavailable(result):
        return False
    existing = _cached_review()
    if (
        result.get("status") == "partial"
        and existing is not None
        and existing.get("status") == "normal"
    ):
        return False
    return True


def _store_review(result: dict) -> None:
    # 清洗对外 warnings，避免泄漏底层网络异常
    daily_review_errors.sanitize_review_public_fields(result)

    if not _should_replace_memory(result):
        return
    # 存独立副本，避免调用方修改污染缓存
    _review_cache[_REVIEW_CACHE_KEY] = (time.time(), copy.deepcopy(result))
    # 同步持久化（内部再判 partial 不覆盖 normal）
    saved_at = result.get("generated_at")
    if not isinstance(saved_at, str) or not saved_at.strip():
        saved_at = _now_str()
    try:
        daily_review_cache.save_latest_review(result, saved_at=saved_at)
    except Exception:  # noqa: BLE001
        pass

def _age_seconds_from_saved_at(saved_at: str | None) -> float | None:
    if not isinstance(saved_at, str) or not saved_at.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(saved_at.strip(), fmt).replace(tzinfo=BEIJING)
            return max(0.0, (datetime.now(BEIJING) - dt).total_seconds())
        except ValueError:
            continue
    return None


def _is_background_refreshing() -> bool:
    with _bg_refresh_lock:
        return _bg_refreshing


def _result_is_refresh_success(result: dict | None) -> bool:
    """后台刷新是否算成功：normal/partial 且关键组件均可用。"""
    if not isinstance(result, dict):
        return False
    if result.get("status") not in ("normal", "partial"):
        return False
    if daily_review_cache.has_critical_unavailable(result):
        return False
    return True


def _kick_background_refresh(*, force: bool = False) -> bool:
    """启动至多一个后台 fresh 刷新线程。

    已在刷新 / 内存已新鲜 / 已失败且未 force → 返回 False（避免轮询打满重试）。
    """
    global _bg_refreshing, _refresh_failed, _refresh_error
    with _bg_refresh_lock:
        if _bg_refreshing:
            return False
        if _cached_review() is not None:
            return False
        if _refresh_failed and not force:
            return False
        _bg_refreshing = True
        # 新一轮尝试开始时先清失败标记，完成后再按结果设置
        _refresh_failed = False
        _refresh_error = None

    def worker() -> None:
        global _bg_refreshing
        try:
            # 复用 generate_daily_review 的锁与聚合逻辑
            result = generate_daily_review()
            if _result_is_refresh_success(result):
                # 若因质量规则未写入内存，仍以磁盘/旧内存为准
                mem = _cached_review()
                if mem is not None and not daily_review_cache.has_critical_unavailable(mem):
                    _clear_refresh_failure()
                elif daily_review_cache.should_persist_review(
                    result, daily_review_cache.load_latest_review()[0]
                ):
                    _clear_refresh_failure()
                else:
                    # 生成了降级包且未覆盖旧 normal
                    if daily_review_cache.load_latest_review()[0] is not None:
                        _set_refresh_failure(daily_review_errors.SAFE_REFRESH_FAILED)
                    else:
                        _clear_refresh_failure()
            else:
                _log.warning("background refresh produced degraded review status=%s",
                             (result or {}).get("status"))
                if daily_review_cache.load_latest_review()[0] is not None:
                    _set_refresh_failure(daily_review_errors.SAFE_REFRESH_FAILED)
        except Exception as e:  # noqa: BLE001 — 后台失败保留旧磁盘结果
            _log.warning("background refresh failed: %s", e, exc_info=False)
            if daily_review_cache.load_latest_review()[0] is not None:
                _set_refresh_failure(daily_review_errors.SAFE_REFRESH_FAILED)
        finally:
            with _bg_refresh_lock:
                _bg_refreshing = False

    threading.Thread(
        target=worker,
        name="daily-review-bg-refresh",
        daemon=True,
    ).start()
    return True

def _build_daily_review() -> dict:
    """执行真实聚合（无缓存、无锁）。字段契约与历史版本一致。"""
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
        _log.warning("get_market_breadth failed: %s", e, exc_info=False)
        breadth_raw = {
            "status": "unavailable",
            "source": "eastmoney_push2",
            "trade_date": None,
            "data_time": None,
            "fetched_at": None,
            "is_stale": False,
            "warnings": [daily_review_errors.SAFE_BREADTH_UNAVAILABLE],
            "data": None,
        }
    breadth = _pass_envelope(breadth_raw)
    if isinstance(breadth, dict) and isinstance(breadth.get("warnings"), list):
        breadth["warnings"] = daily_review_errors.sanitize_warning_list(breadth["warnings"])
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


def generate_daily_review() -> dict:
    """聚合当日复盘客观数据（fresh；不调用 AI、不读磁盘 stale）。

    进程内完整结果缓存（TTL=300s）+ single-flight：
    - 命中返回 deepcopy（generated_at 为生成时时间，不刷新）；
    - 仅高质量 normal / partial 写入内存与磁盘；
    - 关键组件 unavailable 的 partial / unavailable 不覆盖已有 normal；
    - 并发时仅一线程执行真实聚合，其余等锁后读缓存。

    注意：持仓建议等必须走本函数，不得使用 get_daily_review_for_display 的 stale 结果。
    """
    cached = _cached_review()
    if cached is not None:
        return copy.deepcopy(cached)

    with _review_lock:
        cached = _cached_review()
        if cached is not None:
            return copy.deepcopy(cached)
        result = _build_daily_review()
        daily_review_errors.sanitize_review_public_fields(result)
        _store_review(result)
        return copy.deepcopy(result)


def _cache_meta(
    *,
    source: str,
    stale: bool,
    refreshing: bool,
    saved_at: str | None = None,
    age_seconds: float | None = None,
) -> dict:
    failed, err = _refresh_failure_state()
    return {
        "source": source,
        "stale": stale,
        "refreshing": refreshing,
        "saved_at": saved_at,
        "age_seconds": age_seconds,
        "refresh_failed": bool(failed and stale),
        "refresh_error": err if (failed and stale) else None,
    }


def get_daily_review_for_display() -> dict:
    """页面展示专用：可返回磁盘 stale + 后台刷新；结构 ``{data, cache_meta}``。

    1. 新鲜内存缓存 → 立即返回（stale=false）
    2. 无内存但有持久化成功包 → 返回旧结果（stale=true）并 single-flight 后台刷新
    3. 刷新失败时保留旧结果，refresh_failed=true，不再自动无限重试
    4. 皆无 → 同步 generate_daily_review（live）
    """
    cached = _cached_review()
    if cached is not None:
        data = copy.deepcopy(cached)
        daily_review_errors.sanitize_review_public_fields(data)
        return {
            "data": data,
            "cache_meta": _cache_meta(
                source="memory",
                stale=False,
                refreshing=_is_background_refreshing(),
                saved_at=None,
                age_seconds=_cached_review_age_seconds(),
            ),
        }

    review, saved_at = daily_review_cache.load_latest_review()
    if review is not None:
        daily_review_errors.sanitize_review_public_fields(review)
        # 窗口期：后台可能已写入内存
        cached = _cached_review()
        if cached is not None:
            data = copy.deepcopy(cached)
            daily_review_errors.sanitize_review_public_fields(data)
            return {
                "data": data,
                "cache_meta": _cache_meta(
                    source="memory",
                    stale=False,
                    refreshing=_is_background_refreshing(),
                    saved_at=None,
                    age_seconds=_cached_review_age_seconds(),
                ),
            }
        failed, _err = _refresh_failure_state()
        started = False
        if not failed:
            started = _kick_background_refresh()
        refreshing = started or _is_background_refreshing()
        return {
            "data": copy.deepcopy(review),
            "cache_meta": _cache_meta(
                source="persisted",
                stale=True,
                refreshing=refreshing and not failed,
                saved_at=saved_at,
                age_seconds=_age_seconds_from_saved_at(saved_at),
            ),
        }

    data = generate_daily_review()
    daily_review_errors.sanitize_review_public_fields(data)
    return {
        "data": data,
        "cache_meta": _cache_meta(
            source="live",
            stale=False,
            refreshing=False,
            saved_at=None,
            age_seconds=0.0,
        ),
    }
