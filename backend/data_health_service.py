"""数据健康中心：统一记录类型、错误码映射、聚合与 stale 辅助。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo

DataHealthStatus = Literal["normal", "partial", "unavailable"]

BEIJING = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc

ERROR_SUMMARIES: dict[str, str] = {
    "SOURCE_NOT_INITIALIZED": "尚无该数据源的成功运行记录。",
    "SOURCE_STALE": "数据仍可读取，但已超过该来源的时效规则。",
    "SOURCE_PARTIAL": "数据源仅返回部分可用结果。",
    "SOURCE_UNAVAILABLE": "数据源当前不可用，且没有可用结果。",
    "SOURCE_CORRUPTED": "数据存储无法安全读取，请检查备份或恢复流程。",
    "SOURCE_SCHEMA_INCOMPATIBLE": "数据存储版本与当前程序不兼容。",
    "SOURCE_TIMEOUT": "数据源请求超时。",
    "SOURCE_DEGRADED": "当前使用降级结果，部分能力不可用。",
    "NO_HOLDINGS": "当前没有持仓，无法生成持仓建议。",
    "HOLDING_QUOTES_UNAVAILABLE": "部分持仓缺少有效行情，当前无法生成可靠的持仓建议。",
    "MARKET_BREADTH_UNAVAILABLE": "市场广度不可用，当前无法生成可靠的持仓建议。",
    "REVIEW_TRADE_DATE_UNAVAILABLE": "每日复盘缺少交易日，当前无法生成可靠的持仓建议。",
}

GATE_BUSINESS_CODES = frozenset({
    "NO_HOLDINGS",
    "HOLDING_QUOTES_UNAVAILABLE",
    "MARKET_BREADTH_UNAVAILABLE",
    "REVIEW_TRADE_DATE_UNAVAILABLE",
})

VALID_STATUSES = frozenset({"normal", "partial", "unavailable"})

# 注册顺序固定，列表与 summary 均按此顺序
SOURCE_REGISTRY: list[dict[str, str]] = [
    {"source_id": "daily_review", "module": "每日复盘", "display_name": "每日复盘"},
    {"source_id": "portfolio_advice_gate", "module": "持仓建议", "display_name": "持仓建议 Gate"},
    {"source_id": "portfolio_quotes", "module": "持仓行情", "display_name": "持仓行情覆盖"},
    {"source_id": "quotes", "module": "个股行情", "display_name": "个股行情"},
    {"source_id": "announcements", "module": "公告", "display_name": "个股公告"},
    {"source_id": "financials", "module": "财务", "display_name": "财务数据"},
    {"source_id": "news_radar", "module": "资讯雷达", "display_name": "资讯雷达"},
    {"source_id": "sector_research", "module": "板块研究", "display_name": "板块动态数据"},
    {"source_id": "my_reports", "module": "我的研报", "display_name": "我的研报"},
    {"source_id": "watchlist_portfolio_storage", "module": "本地存储", "display_name": "自选股与持仓存储"},
    {"source_id": "evidence_ledger", "module": "证据账本", "display_name": "投资逻辑与证据账本"},
]

REGISTERED_SOURCE_IDS = frozenset(s["source_id"] for s in SOURCE_REGISTRY)
REGISTERED_MODULES = frozenset(s["module"] for s in SOURCE_REGISTRY)

REQUEST_SCOPED_SOURCES = frozenset({
    "quotes",
    "announcements",
    "financials",
    "sector_research",
})

REQUEST_SCOPE_DISCLAIMER = (
    "该状态来自此数据源最近一次真实业务调用，不代表全部股票或板块均已验证。"
)


class DataHealthRecord(TypedDict):
    source_id: str
    module: str
    display_name: str
    status: DataHealthStatus
    is_stale: bool
    observed_at: str | None
    last_success_at: str | None
    data_trade_date: str | None
    data_cutoff: str | None
    stale_after_seconds: int | None
    is_cached: bool | None
    is_degraded: bool | None
    coverage_current: int | None
    coverage_expected: int | None
    last_error_code: str | None
    last_error_summary: str | None
    last_error_at: str | None
    blocks_advice: bool
    block_reason: str | None
    detail_path: str | None


def error_summary(code: str | None) -> str | None:
    if code is None:
        return None
    return ERROR_SUMMARIES.get(code, "数据源状态异常。")


def format_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"


def parse_flexible_time(
    value: Any,
    *,
    naive_as: Literal["utc", "beijing"] = "utc",
) -> datetime | None:
    """将多种时间字符串解析为 UTC datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            if naive_as == "beijing":
                dt = dt.replace(tzinfo=BEIJING)
            else:
                dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    # 北京时间无秒："2026-07-28 09:30"
    if len(s) == 16 and s[10] == " " and s[4] == "-" and s[13] == ":":
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
            return dt.replace(tzinfo=BEIJING).astimezone(UTC)
        except ValueError:
            pass
    # 北京时间带秒
    if len(s) == 19 and s[10] == " " and "T" not in s:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=BEIJING).astimezone(UTC)
        except ValueError:
            pass
    iso = s
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        if naive_as == "beijing":
            dt = dt.replace(tzinfo=BEIJING)
        else:
            dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def max_time(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return max(present)


def is_stale_continuous(
    basis: datetime | None,
    now_utc: datetime,
    stale_after_seconds: int | None,
) -> bool:
    if basis is None or stale_after_seconds is None:
        return False
    return (now_utc - basis).total_seconds() > stale_after_seconds


def _is_weekend(d) -> bool:
    return d.weekday() >= 5  # Sat=5 Sun=6


def previous_weekday(d):
    cur = d
    while _is_weekend(cur):
        cur = cur - timedelta(days=1)
    return cur


def expected_cn_trade_date(now_utc: datetime) -> str:
    """保守 A 股期望交易日（YYYY-MM-DD，北京时间）。无节假日日历。"""
    bj = now_utc.astimezone(BEIJING)
    d = bj.date()
    t = bj.time()
    # 周末 → 最近周五
    if _is_weekend(d):
        d = previous_weekday(d)
        return d.isoformat()
    # 工作日 09:30 前 → 上一工作日
    if (t.hour, t.minute) < (9, 30):
        prev = d - timedelta(days=1)
        prev = previous_weekday(prev)
        return prev.isoformat()
    return d.isoformat()


def is_stale_cn_trade_date(
    data_trade_date: str | None,
    basis: datetime | None,
    now_utc: datetime,
    *,
    fallback_hours: float = 36.0,
) -> bool:
    """日级 CN 来源 stale：优先交易日规则，否则 36h 回退。"""
    if data_trade_date and isinstance(data_trade_date, str) and len(data_trade_date) >= 10:
        td = data_trade_date[:10]
        expected = expected_cn_trade_date(now_utc)
        bj = now_utc.astimezone(BEIJING)
        # 15:00–15:30 落地宽限：允许上一期望交易日，更早则 stale
        if bj.weekday() < 5 and (15, 0) <= (bj.hour, bj.minute) < (15, 30):
            previous_trade_date = previous_weekday(bj.date() - timedelta(days=1))
            return td < previous_trade_date.isoformat()
        # 工作日 15:30 后期望当天
        if bj.weekday() < 5 and (bj.hour, bj.minute) >= (15, 30):
            return td < expected
        # 其它时段：落后于期望则 stale
        if td < expected:
            return True
        return False
    if basis is None:
        return False
    return (now_utc - basis).total_seconds() > fallback_hours * 3600


def is_cn_trading_session(now_utc: datetime) -> bool:
    bj = now_utc.astimezone(BEIJING)
    if bj.weekday() >= 5:
        return False
    hm = (bj.hour, bj.minute)
    # 简化：09:30–11:30 或 13:00–15:00
    return ((9, 30) <= hm <= (11, 30)) or ((13, 0) <= hm <= (15, 0))


def _obs_in_cn_session_hours(bj_obs: datetime) -> bool:
    """观察时间是否落在当日交易时段（含午休前的上午与下午）。"""
    if bj_obs.weekday() >= 5:
        return False
    hm = (bj_obs.hour, bj_obs.minute)
    return ((9, 30) <= hm <= (11, 30)) or ((13, 0) <= hm <= (15, 0))


def is_stale_cn_intraday_observation(
    observed_at: datetime | None,
    now_utc: datetime,
    stale_after_seconds: int = 300,
) -> bool:
    """A 股分钟级观察 stale（quotes / portfolio_quotes）。

    - 盘中：超过阈值 → stale
    - 午休：当日上午观察可继续使用；更早交易日 → stale
    - 收盘后：当日交易时段观察 → fresh；早于期望交易日 → stale
    - 盘前：上一期望交易日观察 → fresh；更早 → stale
    - 周末：最近周五观察 → fresh；更早 → stale
    """
    if observed_at is None:
        return False
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    else:
        observed_at = observed_at.astimezone(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    else:
        now_utc = now_utc.astimezone(UTC)

    bj_now = now_utc.astimezone(BEIJING)
    bj_obs = observed_at.astimezone(BEIJING)
    obs_date = bj_obs.date()
    now_date = bj_now.date()
    hm = (bj_now.hour, bj_now.minute)

    # 周末：最近周五观察 fresh
    if bj_now.weekday() >= 5:
        last_friday = previous_weekday(now_date)
        if obs_date == last_friday and _obs_in_cn_session_hours(bj_obs):
            return False
        if obs_date == last_friday:
            return False
        return True

    # 盘前 < 09:30：上一期望交易日观察 fresh
    if hm < (9, 30):
        expected = expected_cn_trade_date(now_utc)  # 上一工作日
        if obs_date.isoformat() >= expected:
            return False
        return True

    # 盘中：连续阈值
    if is_cn_trading_session(now_utc):
        return (now_utc - observed_at).total_seconds() > stale_after_seconds

    # 午休 11:30–13:00（严格开区间，11:30 仍算盘中边界）
    if (11, 30) < hm < (13, 0):
        # 当日上午观察可继续使用
        if obs_date == now_date and (bj_obs.hour, bj_obs.minute) <= (11, 30):
            return False
        # 更早交易日
        return True

    # 收盘后（含 15:00 起）
    if hm >= (15, 0):
        expected = expected_cn_trade_date(now_utc)
        # 当日交易时段观察 → fresh
        if obs_date == now_date and _obs_in_cn_session_hours(bj_obs):
            return False
        # 当日午休观察也可视为当日会话内
        if obs_date == now_date and (11, 30) < (bj_obs.hour, bj_obs.minute) < (13, 0):
            return False
        # 早于当前期望交易日 → stale
        if obs_date.isoformat() < expected:
            return True
        # 期望交易日当天但非交易时段观察（如盘前）
        if obs_date.isoformat() == expected and not _obs_in_cn_session_hours(bj_obs):
            # 盘前观察在收盘后视为过旧于“当日行情”
            if (bj_obs.hour, bj_obs.minute) < (9, 30):
                return True
        return obs_date.isoformat() < expected

    return False


def make_record(
    *,
    source_id: str,
    module: str,
    display_name: str,
    status: DataHealthStatus,
    is_stale: bool = False,
    observed_at: str | None = None,
    last_success_at: str | None = None,
    data_trade_date: str | None = None,
    data_cutoff: str | None = None,
    stale_after_seconds: int | None = None,
    is_cached: bool | None = None,
    is_degraded: bool | None = None,
    coverage_current: int | None = None,
    coverage_expected: int | None = None,
    last_error_code: str | None = None,
    last_error_at: str | None = None,
    blocks_advice: bool = False,
    block_reason: str | None = None,
    detail_path: str | None = None,
) -> DataHealthRecord:
    if status not in VALID_STATUSES:
        status = "unavailable"
        last_error_code = last_error_code or "SOURCE_UNAVAILABLE"
    return {
        "source_id": source_id,
        "module": module,
        "display_name": display_name,
        "status": status,
        "is_stale": bool(is_stale),
        "observed_at": observed_at,
        "last_success_at": last_success_at,
        "data_trade_date": data_trade_date,
        "data_cutoff": data_cutoff,
        "stale_after_seconds": stale_after_seconds,
        "is_cached": is_cached,
        "is_degraded": is_degraded,
        "coverage_current": coverage_current,
        "coverage_expected": coverage_expected,
        "last_error_code": last_error_code,
        "last_error_summary": error_summary(last_error_code),
        "last_error_at": last_error_at,
        "blocks_advice": bool(blocks_advice),
        "block_reason": block_reason,
        "detail_path": detail_path,
    }


def not_initialized_record(
    source_id: str,
    module: str,
    display_name: str,
    *,
    detail_path: str | None = None,
    stale_after_seconds: int | None = None,
) -> DataHealthRecord:
    return make_record(
        source_id=source_id,
        module=module,
        display_name=display_name,
        status="unavailable",
        last_error_code="SOURCE_NOT_INITIALIZED",
        detail_path=detail_path,
        stale_after_seconds=stale_after_seconds,
        blocks_advice=False,
        block_reason=None,
    )


def unavailable_record(
    source_id: str,
    module: str,
    display_name: str,
    error_code: str,
    *,
    detail_path: str | None = None,
    observed_at: str | None = None,
    last_success_at: str | None = None,
    last_error_at: str | None = None,
    is_stale: bool = False,
    stale_after_seconds: int | None = None,
    is_cached: bool | None = None,
    is_degraded: bool | None = None,
) -> DataHealthRecord:
    return make_record(
        source_id=source_id,
        module=module,
        display_name=display_name,
        status="unavailable",
        is_stale=is_stale,
        observed_at=observed_at,
        last_success_at=last_success_at,
        last_error_code=error_code,
        last_error_at=last_error_at,
        detail_path=detail_path,
        stale_after_seconds=stale_after_seconds,
        is_cached=is_cached,
        is_degraded=is_degraded,
        blocks_advice=False,
        block_reason=None,
    )


def map_event_quality(
    event: dict[str, Any] | None,
) -> tuple[DataHealthStatus, str | None, bool | None, str | None, str | None, str | None]:
    """通用事件状态机（不含 gate）。

    Returns
    -------
    status, last_error_code, is_degraded, last_success_at, last_error_at, observed_at
    """
    if not event:
        return (
            "unavailable",
            "SOURCE_NOT_INITIALIZED",
            None,
            None,
            None,
            None,
        )
    ls = event.get("last_success_at")
    le = event.get("last_error_at")
    code = event.get("last_error_code")
    ls_dt = parse_flexible_time(ls, naive_as="utc")
    le_dt = parse_flexible_time(le, naive_as="utc")
    # 非法时间 fail-closed
    if ls is not None and ls_dt is None:
        return ("unavailable", "SOURCE_CORRUPTED", None, None, None, None)
    if le is not None and le_dt is None:
        return ("unavailable", "SOURCE_CORRUPTED", None, None, None, None)

    obs_dt = max_time(ls_dt, le_dt)
    observed_at = format_utc(obs_dt)
    ls_s = format_utc(ls_dt) if ls_dt else None
    le_s = format_utc(le_dt) if le_dt else None

    if le_dt is not None and ls_dt is None:
        # 仅有错误：partial/degraded 也因无成功结果而 unavailable
        return ("unavailable", code or "SOURCE_UNAVAILABLE", None, None, le_s, observed_at)

    if ls_dt is not None and (le_dt is None or ls_dt > le_dt):
        return ("normal", code, None, ls_s, le_s, observed_at)

    # last_error_at >= last_success_at
    if code == "SOURCE_PARTIAL":
        return ("partial", code, False, ls_s, le_s, observed_at)
    if code == "SOURCE_DEGRADED":
        return ("partial", code, True, ls_s, le_s, observed_at)
    return ("unavailable", code or "SOURCE_UNAVAILABLE", None, ls_s, le_s, observed_at)


def map_gate_event(
    event: dict[str, Any] | None,
) -> tuple[DataHealthStatus, bool, str | None, str | None, str | None, str | None, str | None]:
    """Gate 专用映射。

    Returns
    -------
    status, blocks_advice, block_reason, last_error_code, last_success_at, last_error_at, observed_at

    Fail-closed 策略：
    - Gate 业务码必须满足：last_success_at == last_error_at 非 null
    - Gate 运行失败码必须满足：last_error_at 非 null 且不被解释为业务阻断
    - 非法 Gate 状态形状 → status=unavailable, blocks_advice=false,
      last_error_code=SOURCE_CORRUPTED（不再显示业务阻断摘要）
    """
    if not event:
        return (
            "unavailable",
            False,
            None,
            "SOURCE_NOT_INITIALIZED",
            None,
            None,
            None,
        )
    ls = event.get("last_success_at")
    le = event.get("last_error_at")
    code = event.get("last_error_code")
    ls_dt = parse_flexible_time(ls, naive_as="utc")
    le_dt = parse_flexible_time(le, naive_as="utc")
    if ls is not None and ls_dt is None:
        return ("unavailable", False, None, "SOURCE_CORRUPTED", None, None, None)
    if le is not None and le_dt is None:
        return ("unavailable", False, None, "SOURCE_CORRUPTED", None, None, None)

    obs_dt = max_time(ls_dt, le_dt)
    observed_at = format_utc(obs_dt)
    ls_s = format_utc(ls_dt) if ls_dt else None
    le_s = format_utc(le_dt) if le_dt else None

    # Gate 业务阻断码
    if code in GATE_BUSINESS_CODES:
        # 阻断状态：last_success_at == last_error_at 非 null
        if ls_dt is not None and le_dt is not None and ls_dt == le_dt:
            summary = error_summary(code)
            return ("normal", True, summary, code, ls_s, le_s, observed_at)
        # 恢复状态：last_success_at > last_error_at（业务码为历史保留）
        if ls_dt is not None and (le_dt is None or ls_dt > le_dt):
            return ("normal", False, None, code, ls_s, le_s, observed_at)
        # 非法状态：业务码但 last_error_at > last_success_at 或 last_success_at is None
        # → fail-closed（业务码不得由 record_failure 写入）
        return ("unavailable", False, None, "SOURCE_CORRUPTED", None, None, None)

    # 允许：success 严格晚于 error（或仅有 success）
    if ls_dt is not None and (le_dt is None or ls_dt > le_dt):
        return ("normal", False, None, code, ls_s, le_s, observed_at)

    # 运行失败码：last_error_at 非 null，不得解释成业务阻断
    if le_dt is not None and (ls_dt is None or le_dt >= ls_dt):
        # Gate 运行失败只允许 SOURCE_TIMEOUT / SOURCE_UNAVAILABLE
        if code not in ("SOURCE_TIMEOUT", "SOURCE_UNAVAILABLE"):
            # 非法 Gate 状态形状 → fail-closed
            return ("unavailable", False, None, "SOURCE_CORRUPTED", None, None, None)
        return (
            "unavailable",
            False,
            None,
            code,
            ls_s,
            le_s,
            observed_at,
        )

    return ("unavailable", False, None, "SOURCE_NOT_INITIALIZED", None, None, None)


def compute_overall(items: list[DataHealthRecord]) -> str:
    initialized = [
        it for it in items
        if it.get("last_error_code") != "SOURCE_NOT_INITIALIZED"
    ]
    if not initialized:
        return "unavailable"
    if all(it.get("status") == "unavailable" for it in initialized):
        return "unavailable"
    if any(
        it.get("status") in ("partial", "unavailable") or it.get("is_stale")
        for it in initialized
    ):
        return "partial"
    return "normal"


def compute_summary(items: list[DataHealthRecord]) -> dict[str, int]:
    summary = {
        "normal": 0,
        "partial": 0,
        "unavailable": 0,
        "stale": 0,
        "not_initialized": 0,
    }
    for it in items:
        st = it.get("status")
        if st in ("normal", "partial", "unavailable"):
            summary[st] += 1
        if it.get("is_stale"):
            summary["stale"] += 1
        if it.get("last_error_code") == "SOURCE_NOT_INITIALIZED":
            summary["not_initialized"] += 1
    return summary


def extract_gate_block_reasons(items: list[DataHealthRecord]) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    for it in items:
        if it.get("source_id") != "portfolio_advice_gate":
            continue
        if it.get("blocks_advice") and it.get("last_error_code") in GATE_BUSINESS_CODES:
            reasons.append({
                "source_id": "portfolio_advice_gate",
                "error_code": it["last_error_code"] or "",
                "summary": it.get("last_error_summary") or error_summary(it.get("last_error_code")) or "",
            })
    return reasons


def aggregate_health(items: list[DataHealthRecord]) -> dict[str, Any]:
    overall = compute_overall(items)
    summary = compute_summary(items)
    gate = next((it for it in items if it.get("source_id") == "portfolio_advice_gate"), None)
    blocks = bool(gate and gate.get("blocks_advice"))
    return {
        "overall_status": overall,
        "blocks_advice": blocks,
        "block_reasons": extract_gate_block_reasons(items),
        "summary": summary,
        "items": items,
    }


# 各来源详情计算说明（固定文案）
SOURCE_CALCULATION: dict[str, dict[str, Any]] = {
    "daily_review": {
        "quality_basis": ["daily_review.status", "daily_review.data_health.components"],
        "freshness_basis": "cache_meta.stale | data_trade_date | saved_at/generated_at",
        "calendar_type": "CN_MARKET_CONSERVATIVE",
        "rule_summary": "展示缓存 stale 优先；否则按交易日和 36 小时回退规则判断。",
    },
    "portfolio_advice_gate": {
        "quality_basis": ["portfolio_advice_gate event"],
        "freshness_basis": "observed_at=max(last_success_at,last_error_at)",
        "calendar_type": "CONTINUOUS",
        "rule_summary": "超过 300 秒，或持仓文件、portfolio_quotes、daily_review 任一观察时间更新时 stale；stale 不改变最近 gate 结论。",
    },
    "portfolio_quotes": {
        "quality_basis": ["portfolio_quotes event from get_portfolio data_status"],
        "freshness_basis": "event last_success_at/last_error_at",
        "calendar_type": "CN_MARKET_CONSERVATIVE",
        "rule_summary": "交易时段 300 秒阈值；非交易时段延续最近观察。",
    },
    "quotes": {
        "quality_basis": ["quotes event from real tencent_quote calls"],
        "freshness_basis": "event last_success_at/last_error_at",
        "calendar_type": "CN_MARKET_CONSERVATIVE",
        "rule_summary": "最近一次真实业务调用；交易时段 300 秒。",
        "disclaimer": REQUEST_SCOPE_DISCLAIMER,
    },
    "announcements": {
        "quality_basis": ["announcements event"],
        "freshness_basis": "event last_success_at/last_error_at",
        "calendar_type": "CONTINUOUS",
        "rule_summary": "最近一次真实业务调用；86400 秒阈值。",
        "disclaimer": REQUEST_SCOPE_DISCLAIMER,
    },
    "financials": {
        "quality_basis": ["financials event"],
        "freshness_basis": "event last_success_at/last_error_at",
        "calendar_type": "REPORTING_PERIOD",
        "rule_summary": "最近一次真实业务调用；604800 秒阈值。",
        "disclaimer": REQUEST_SCOPE_DISCLAIMER,
    },
    "news_radar": {
        "quality_basis": ["radar.json generated_at/stats"],
        "freshness_basis": "generated_at",
        "calendar_type": "CONTINUOUS",
        "rule_summary": "failed_sources 决定 partial；86400 秒决定 stale。",
    },
    "sector_research": {
        "quality_basis": ["sector_research event from get_sector_dynamic_data"],
        "freshness_basis": "event last_success_at/last_error_at",
        "calendar_type": "CONTINUOUS",
        "rule_summary": "最近一次真实业务调用；86400 秒阈值。",
        "disclaimer": REQUEST_SCOPE_DISCLAIMER,
    },
    "my_reports": {
        "quality_basis": ["myreports index.json"],
        "freshness_basis": "max(imported_at)",
        "calendar_type": "USER_MANAGED",
        "rule_summary": "用户档案不因时间自动过期；索引损坏为 unavailable。",
    },
    "watchlist_portfolio_storage": {
        "quality_basis": ["watchlist_store status", "portfolio.json structure"],
        "freshness_basis": "updated_at / file mtime",
        "calendar_type": "USER_MANAGED",
        "rule_summary": "用户配置不因时间变旧。",
    },
    "evidence_ledger": {
        "quality_basis": ["evidence_thesis.db readonly summary"],
        "freshness_basis": "max(updated_at)",
        "calendar_type": "USER_MANAGED",
        "rule_summary": "账本内容不因时间自动判坏。",
    },
}

SOURCE_RELATED_PAGES: dict[str, list[dict[str, str]]] = {
    "daily_review": [{"label": "查看每日复盘", "path": "/daily-review"}],
    "portfolio_advice_gate": [{"label": "查看我的持仓", "path": "/portfolio"}],
    "portfolio_quotes": [{"label": "查看我的持仓", "path": "/portfolio"}],
    "quotes": [{"label": "查看个股数据", "path": "/stock-data"}],
    "announcements": [{"label": "查看个股数据", "path": "/stock-data"}],
    "financials": [{"label": "查看个股数据", "path": "/stock-data"}],
    "news_radar": [{"label": "查看资讯雷达", "path": "/intel"}],
    "sector_research": [{"label": "查看板块中心", "path": "/sectors"}],
    "my_reports": [{"label": "查看我的研报", "path": "/my-reports"}],
    "watchlist_portfolio_storage": [
        {"label": "自选股", "path": "/watchlist"},
        {"label": "我的持仓", "path": "/portfolio"},
    ],
    "evidence_ledger": [
        {"label": "投资逻辑", "path": "/thesis"},
        {"label": "证据", "path": "/evidence"},
    ],
}
