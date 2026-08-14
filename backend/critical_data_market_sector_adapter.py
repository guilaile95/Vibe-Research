"""P0-DS1-R2 — cap.context.market_sector runtime evaluator（real sector context）。

仅市场广度 + 行业名不足以证明 market_sector。完整链路必须全部
positive-proof 才允许 USABLE：

    security
      → MARKET CONTEXT（广度信封，trade_date 与权威日历对齐）
      → industry identity（astock.individual_info「行业」）
      → matching sector observation（market.get_overview 板块资金流中
        找到该行业的板块观察数据）
      → sector state/data + provenance + freshness（overview.updated
        的北京日期不早于 market fact date）

industry identity alone → UNKNOWN + 显式 blocker；不得新建 provider；
retrieval time 绝不当作 fact time；DDA1 未修改。只读、零写入。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from critical_data_dependency_policy import CAP_CONTEXT_MARKET_SECTOR
from trade_calendar import CALENDAR_AUTHORITY_REF, completed_trade_date_at

DEPENDENCY_ID = CAP_CONTEXT_MARKET_SECTOR
ADAPTER_AUTHORITY_REF = "critical_data:market_sector:v0.3"
SECTOR_CONTEXT_BLOCKER_REF = (
    "market-sector:blocker=SECURITY_SECTOR_CONTEXT_UNAVAILABLE"
)

_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_CN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MarketSectorCapabilityError(RuntimeError):
    """capability 评估输入或权威链无效。"""


def _result(state: str, as_of: str, refs: list[str]) -> dict[str, Any]:
    return {
        "dependency_id": DEPENDENCY_ID,
        "state": state,
        "as_of": as_of,
        "authority_refs": list(dict.fromkeys(refs)),
    }


def _require_inputs(security_code: str, campaign_id: str, as_of: str) -> None:
    if type(security_code) is not str \
            or re.fullmatch(r"[0-9]{6}", security_code) is None:
        raise MarketSectorCapabilityError(
            "security_code must be six ASCII digits"
        )
    if type(campaign_id) is not str \
            or _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise MarketSectorCapabilityError("campaign_id is invalid")
    if type(as_of) is not str \
            or _UTC_ZERO_OFFSET_RE.fullmatch(as_of) is None:
        raise MarketSectorCapabilityError(
            "as_of must be a canonical UTC instant"
        )


def _extract_industry(info: Mapping[str, Any]) -> str | None:
    """从 individual_info（{item: value}）提取行业；缺失/非法 → None。"""
    value = info.get("行业")
    if type(value) is not str or not value.strip() or value != value.strip():
        return None
    return value


def _matching_sector_observation(
    overview: Mapping[str, Any], industry: str
) -> Mapping[str, Any] | None:
    """在 overview.sectors 中精确匹配行业条目；结构非法 → None（fail closed）。

    不做模糊匹配（绝不 AI 猜板块）。"""
    sectors = overview.get("sectors")
    if not isinstance(sectors, list):
        return None
    for sector in sectors:
        if not isinstance(sector, Mapping):
            continue
        name = sector.get("name")
        if type(name) is not str or not name.strip():
            continue
        if name.strip() == industry:
            return sector
    return None


def _sector_fresh_date(overview: Mapping[str, Any]) -> str | None:
    """sector observation 的 freshness 证据：overview.updated 的北京日期。

    updated 为北京 naive ``YYYY-MM-DD HH:MM``（provider retrieval time，
    仅作 freshness 证据，绝不当作 fact time）。"""
    updated = overview.get("updated")
    if type(updated) is not str:
        return None
    date = updated[:10]
    if _CN_DATE_RE.fullmatch(date) is None:
        return None
    return date


def evaluate_market_sector_capability(
    *,
    security_code: str,
    campaign_id: str,
    as_of: str,
    market_reader: Callable[[], Mapping[str, Any] | None] | None = None,
    sector_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
    sector_observation_reader: Callable[[], Mapping[str, Any] | None] | None = None,
    calendar: Callable[[str], str | None] = completed_trade_date_at,
) -> dict[str, Any]:
    """评估 market_sector capability。

    三个 reader 默认绑定生产读取路径（见 assembler 生产端口）；测试注入
    isolated fake。USABLE 需要市场上下文 + industry identity + matching
    sector observation 三者同时 positive-proof。
    """
    _require_inputs(security_code, campaign_id, as_of)
    refs = [ADAPTER_AUTHORITY_REF]

    trade_date = calendar(as_of)
    if trade_date is None:
        return _result("NOT_EVALUATED", as_of, refs)
    refs.append(CALENDAR_AUTHORITY_REF)

    if market_reader is None:
        # 生产默认：真实市场广度信封（从不抛异常，状态在 envelope.status）
        import market as market_module

        market_reader = market_module.get_market_breadth

    try:
        envelope = market_reader()
    except Exception:
        # provider failure 如实暴露（HTTP 失败 / 解析失败等）
        return _result("ERROR", as_of, refs)
    if envelope is None or not isinstance(envelope, Mapping):
        return _result("ERROR", as_of, refs)

    status = envelope.get("status")
    if status == "unavailable":
        # 数据源明确不可用（data=None，不伪造全 0）
        return _result("ERROR", as_of, refs)
    if status not in ("normal", "partial"):
        return _result("UNKNOWN", as_of, refs)

    envelope_trade_date = envelope.get("trade_date")
    if envelope_trade_date is None:
        # 真实 breadth 快照不携带交易日元数据（P0-RU2 实测）：该快照是评估
        # 时点的实时全市场快照，其市场事实时点由权威日历推导为 as_of 的
        # completed trade date —— 绝不以 fetched_at 冒充 fact time、绝不猜
        # 数据内容；推导来源显式写入 provenance。
        envelope_trade_date = trade_date
        refs.append("market-breadth:trade_date=calendar-derived")
    if type(envelope_trade_date) is not str \
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}", envelope_trade_date) is None:
        return _result("ERROR", as_of, refs)

    if envelope_trade_date > trade_date:
        return _result("ERROR", as_of, refs)
    if envelope_trade_date < trade_date:
        # 旧快照不冒充 current market fact
        return _result("STALE", as_of, refs)

    source = envelope.get("source")
    if type(source) is str and source.strip() and source == source.strip():
        refs.append(f"market-breadth:source={source}")
    refs.append(f"market-breadth:trade_date={envelope_trade_date}")
    fetched_at = envelope.get("fetched_at")
    if type(fetched_at) is str and fetched_at:
        # retrieval time 显式暴露为 provenance，绝不参与 fact time 判定
        refs.append(f"market-breadth:fetched_at={fetched_at}")

    if status == "partial":
        # 有数据但覆盖不足：诚实 UNKNOWN，不因 HTTP 200 而 USABLE
        warnings = envelope.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                if type(warning) is str and warning.strip():
                    refs.append(f"market-breadth:partial:{warning}")
        return _result("UNKNOWN", as_of, refs)

    data = envelope.get("data")
    if data is None or not isinstance(data, Mapping) or not data:
        return _result("UNKNOWN", as_of, refs)
    stock_count = data.get("stock_count")
    if not isinstance(stock_count, int) or isinstance(stock_count, bool) \
            or stock_count <= 0:
        return _result("UNKNOWN", as_of, refs)
    up_count = data.get("up_count")
    down_count = data.get("down_count")
    if not all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (up_count, down_count)
    ):
        return _result("UNKNOWN", as_of, refs)

    refs.append(f"market-breadth:stock_count={stock_count}")

    # industry identity：市场上下文不足以证明 market_sector
    if sector_reader is None:
        import astock as astock_module

        sector_reader = astock_module.individual_info

    try:
        info = sector_reader(security_code)
    except Exception:
        return _result("ERROR", as_of, refs)
    if info is None or not isinstance(info, Mapping):
        return _result("UNKNOWN", as_of, refs + [SECTOR_CONTEXT_BLOCKER_REF])
    industry = _extract_industry(info)
    if industry is None:
        # Sector 无法证明 → UNKNOWN + 显式 blocker（绝不 market-only USABLE）
        return _result("UNKNOWN", as_of, refs + [SECTOR_CONTEXT_BLOCKER_REF])
    refs.append(f"market-sector:security-industry={industry}")

    # matching sector observation：industry identity alone 不算 sector context
    if sector_observation_reader is None:
        import market as market_module

        sector_observation_reader = market_module.get_overview

    try:
        overview = sector_observation_reader()
    except Exception:
        return _result("ERROR", as_of, refs)
    if overview is None or not isinstance(overview, Mapping):
        return _result("UNKNOWN", as_of, refs + [SECTOR_CONTEXT_BLOCKER_REF])
    sector = _matching_sector_observation(overview, industry)
    if sector is None:
        return _result("UNKNOWN", as_of, refs + [SECTOR_CONTEXT_BLOCKER_REF])
    pct = sector.get("pct")
    net = sector.get("net")
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in (pct, net)
    ):
        return _result("UNKNOWN", as_of, refs + [SECTOR_CONTEXT_BLOCKER_REF])
    # freshness：sector snapshot 的北京日期不早于 market fact date
    fresh_date = _sector_fresh_date(overview)
    if fresh_date is None:
        return _result("UNKNOWN", as_of, refs + [SECTOR_CONTEXT_BLOCKER_REF])
    if fresh_date < envelope_trade_date:
        return _result("STALE", as_of, refs)
    refs.append(f"market-sector:sector={industry}")
    refs.append(f"market-sector:sector-pct={pct}")
    refs.append(f"market-sector:sector-net={net}")
    refs.append(f"market-sector:updated={fresh_date}")
    return _result("USABLE", as_of, refs)


__all__ = [
    "ADAPTER_AUTHORITY_REF",
    "DEPENDENCY_ID",
    "MarketSectorCapabilityError",
    "SECTOR_CONTEXT_BLOCKER_REF",
    "evaluate_market_sector_capability",
]
