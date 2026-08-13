"""P0-DS1 — cap.context.market_sector runtime evaluator.

组合既有真实市场数据能力（market.get_market_breadth 统一信封）做
positive-proof 评估。铁律：

- 绝不把 retrieval time（fetched_at）当作 market fact time（trade_date）；
- 不凭空产生 market regime / sector 推断；
- trade_date 落后于 as_of 的 completed trade date → STALE（旧快照不冒充 current）；
- provider 失败 / 数据不足 → 诚实 ERROR / UNKNOWN，绝不伪造 USABLE。

本模块只读、零写入、不引入新 provider。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from critical_data_dependency_policy import CAP_CONTEXT_MARKET_SECTOR
from trade_calendar import CALENDAR_AUTHORITY_REF, completed_trade_date_at

DEPENDENCY_ID = CAP_CONTEXT_MARKET_SECTOR
ADAPTER_AUTHORITY_REF = "critical_data:market_sector:v0.1"

_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)


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


def _require_text(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise MarketSectorCapabilityError(f"{field} must be non-empty text")
    return value


def evaluate_market_sector_capability(
    *,
    security_code: str,
    campaign_id: str,
    as_of: str,
    market_reader: Callable[[], Mapping[str, Any] | None] | None = None,
    calendar: Callable[[str], str | None] = completed_trade_date_at,
) -> dict[str, Any]:
    """评估 market_sector capability（context 能力，与 security 无关）。

    ``market_reader`` 默认绑定生产读取路径（见 assembler 的生产端口），
    测试注入 isolated fake。返回信封必须含 status / trade_date / source。
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
        # 无 market fact time：绝不拿 fetched_at 冒充
        return _result("UNKNOWN", as_of, refs)
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
    return _result("USABLE", as_of, refs)


__all__ = [
    "ADAPTER_AUTHORITY_REF",
    "DEPENDENCY_ID",
    "MarketSectorCapabilityError",
    "evaluate_market_sector_capability",
]
