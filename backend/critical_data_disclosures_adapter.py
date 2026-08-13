"""P0-DS1 — cap.security.disclosures runtime evaluator（R1 时间语义修正）。

组合既有真实公告数据能力（astock.announcements，东财公告）做
positive-proof 评估。三种时间明确区分：

- FACT TIME = 公告日 notice_date（北京时间日历日）；
- RETRIEVAL TIME = fetched_at（仅 provenance，绝不参与 gate）；
- EVALUATION/SNAPSHOT TIME = as_of（评估时点）。

生产实际顺序：snapshot as_of 先固定 → provider request → retrieval 完成
（fetched_at 晚于 as_of 是正常网络耗时，绝不因此 NOT_EVALUATED）。
look-ahead 防护只针对 FACT TIME：公告日晚于 as_of 北京时间日的条目
从判定中排除（历史 as_of 无 look-ahead）。

语义区分（§5）：

- provider failure → ERROR（UNAVAILABLE 语义）；
- 查询成功但无（可见）公告 → EMPTY_BUT_VALID（有效空，映射 USABLE +
  标记，绝不视为 provider failure）；
- fetched_at 缺失 / 非法 → UNKNOWN（无法证明 freshness）；
- 有可见公告事实 → USABLE（refs 携带数据截止时间 / 来源 / 覆盖条数）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from critical_data_dependency_policy import CAP_SECURITY_DISCLOSURES

DEPENDENCY_ID = CAP_SECURITY_DISCLOSURES
ADAPTER_AUTHORITY_REF = "critical_data:disclosures:v0.2"
EMPTY_BUT_VALID_REF = "disclosures:empty-but-valid"
LOOKAHEAD_EXCLUDED_REF = "disclosures:lookahead-excluded"

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


def _beijing_calendar_date(as_of_dt: datetime) -> str:
    """as_of → 北京日历日（公告日为北京时间日历日；精确 +8，无任意容差）。"""
    return (as_of_dt + timedelta(hours=8)).date().isoformat()


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
    assert as_of_dt is not None  # _require_inputs 已保证
    beijing_today = _beijing_calendar_date(as_of_dt)

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
    # RETRIEVAL TIME 只作 provenance：fetched_at 晚于 as_of 是正常网络耗时，
    # 不参与任何 gate（不因正常检索而 NOT_EVALUATED）。
    source = payload.get("source")
    if type(source) is str and source.strip() and source == source.strip():
        refs.append(f"disclosures:source={source}")
    refs.append(f"disclosures:fetched_at={payload.get('fetched_at')}")

    announcements = payload.get("announcements")
    if announcements is None or not isinstance(announcements, list):
        return _result("ERROR", as_of, refs)

    # FACT TIME gate：公告日晚于 as_of 北京时间日 → look-ahead，排除出判定
    # （历史 as_of 不得看到未来公告；live 请求数据源偶发未来脏数据同样排除）。
    visible: list[dict] = []
    excluded = 0
    for item in announcements:
        if not isinstance(item, Mapping):
            # 数据源返回结构损坏 → fail closed
            return _result("ERROR", as_of, refs)
        date = item.get("date")
        if type(date) is not str or _DATE_RE.fullmatch(date) is None:
            return _result("ERROR", as_of, refs)
        if date > beijing_today:
            excluded += 1
            continue
        visible.append(dict(item))
    if excluded:
        refs.append(f"{LOOKAHEAD_EXCLUDED_REF}={excluded}")

    if not visible:
        # 查询成功且 as_of 时点无可见公告 = 有效空事实，不是 provider failure
        refs.append(EMPTY_BUT_VALID_REF)
        return _result("USABLE", as_of, refs)

    dates = [item["date"] for item in visible]
    latest_date = max(dates)
    refs.append(f"disclosures:count={len(visible)}")
    refs.append(f"disclosures:latest_notice_date={latest_date}")
    return _result("USABLE", as_of, refs)


__all__ = [
    "ADAPTER_AUTHORITY_REF",
    "DEPENDENCY_ID",
    "DisclosuresCapabilityError",
    "EMPTY_BUT_VALID_REF",
    "LOOKAHEAD_EXCLUDED_REF",
    "evaluate_disclosures_capability",
]
