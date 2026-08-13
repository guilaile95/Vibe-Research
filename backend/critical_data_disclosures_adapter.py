"""P0-DS1 — cap.security.disclosures runtime evaluator.

组合既有真实公告数据能力（astock.announcements，东财公告）做
positive-proof 评估。语义区分（§5）：

- provider failure → ERROR（UNAVAILABLE 语义）；
- 查询成功但无公告 → EMPTY_BUT_VALID（有效空，映射 USABLE + empty 标记，
  绝不视为 provider failure）；
- fetched_at 缺失 / 非法 → UNKNOWN（无法证明 freshness）；
- fetched_at 晚于 as_of → NOT_EVALUATED；
- 有公告事实 → USABLE（refs 携带数据截止时间 / 来源 / 覆盖条数）。

本模块只读、零写入、不引入新 provider。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Mapping

from critical_data_dependency_policy import CAP_SECURITY_DISCLOSURES

DEPENDENCY_ID = CAP_SECURITY_DISCLOSURES
ADAPTER_AUTHORITY_REF = "critical_data:disclosures:v0.1"
EMPTY_BUT_VALID_REF = "disclosures:empty-but-valid"

_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DisclosuresCapabilityError(RuntimeError):
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
        raise DisclosuresCapabilityError(
            "security_code must be six ASCII digits"
        )
    if type(campaign_id) is not str \
            or _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise DisclosuresCapabilityError("campaign_id is invalid")
    if type(as_of) is not str \
            or _UTC_ZERO_OFFSET_RE.fullmatch(as_of) is None:
        raise DisclosuresCapabilityError(
            "as_of must be a canonical UTC instant"
        )


def _parse_utc_instant(value: Any) -> datetime | None:
    """解析 canonical UTC instant；非法 → None。"""
    if type(value) is not str:
        return None
    if _UTC_ZERO_OFFSET_RE.fullmatch(value) is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_disclosures_capability(
    *,
    security_code: str,
    campaign_id: str,
    as_of: str,
    announcements_reader: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """评估 disclosures capability（per-security 公告覆盖）。

    ``announcements_reader(security_code)`` 默认绑定生产读取路径（见
    assembler 生产端口），返回 ``{"announcements": [...], "fetched_at":
    <UTC instant>, "source": <str>}``；测试注入 isolated fake。
    """
    _require_inputs(security_code, campaign_id, as_of)
    refs = [ADAPTER_AUTHORITY_REF]
    as_of_dt = _parse_utc_instant(as_of)

    if announcements_reader is None:
        import astock as astock_module
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        def _production_reader(code: str) -> Mapping[str, Any]:
            rows = astock_module.announcements(code, limit=15)
            return {
                "announcements": rows,
                "fetched_at": _dt.now(_tz.utc).isoformat(
                    timespec="microseconds"
                ).replace("+00:00", "Z"),
                "source": "eastmoney-announcements",
            }

        announcements_reader = _production_reader

    try:
        payload = announcements_reader(security_code)
    except Exception:
        # provider failure 如实暴露（UNAVAILABLE）
        return _result("ERROR", as_of, refs)
    if payload is None or not isinstance(payload, Mapping):
        return _result("ERROR", as_of, refs)

    fetched_at_dt = _parse_utc_instant(payload.get("fetched_at"))
    if fetched_at_dt is None:
        # 无法证明 freshness → UNKNOWN，绝不因 HTTP 200 而 USABLE
        return _result("UNKNOWN", as_of, refs)
    if as_of_dt is not None and fetched_at_dt > as_of_dt:
        return _result("NOT_EVALUATED", as_of, refs)
    source = payload.get("source")
    if type(source) is str and source.strip() and source == source.strip():
        refs.append(f"disclosures:source={source}")
    refs.append(f"disclosures:fetched_at={payload.get('fetched_at')}")

    announcements = payload.get("announcements")
    if announcements is None or not isinstance(announcements, list):
        return _result("ERROR", as_of, refs)
    if not announcements:
        # 查询成功且无公告 = 有效空事实，不是 provider failure
        refs.append(EMPTY_BUT_VALID_REF)
        return _result("USABLE", as_of, refs)

    dates: list[str] = []
    for item in announcements:
        if not isinstance(item, Mapping):
            # 数据源返回结构损坏 → fail closed
            return _result("ERROR", as_of, refs)
        date = item.get("date")
        if type(date) is not str or _DATE_RE.fullmatch(date) is None:
            # 数据源返回结构损坏 → fail closed
            return _result("ERROR", as_of, refs)
        dates.append(date)
    latest_date = max(dates)
    refs.append(f"disclosures:count={len(announcements)}")
    refs.append(f"disclosures:latest_notice_date={latest_date}")
    return _result("USABLE", as_of, refs)


__all__ = [
    "ADAPTER_AUTHORITY_REF",
    "DEPENDENCY_ID",
    "DisclosuresCapabilityError",
    "EMPTY_BUT_VALID_REF",
    "evaluate_disclosures_capability",
]
