"""Read-only stock versus current-industry valuation context.

The comparison uses one Eastmoney A-share snapshot.  Industry membership is the
current ``industry=f100`` snapshot, PE-TTM is ``f115``, and PB is ``f23``.
This is not historical membership, not a sector-index valuation, and not a
cheap/expensive or BUY/SELL recommendation.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

import astock
import sector_industry_context as sic


SCHEMA_VERSION = "stock-valuation-context.v0.1"
SOURCE = "EASTMONEY_A_SHARE_SNAPSHOT"
PE_SOURCE = "eastmoney_clist_f115"
PB_SOURCE = "eastmoney_clist_f23"
UNKNOWN_INDUSTRY = "UNKNOWN"
_CODE_RE = re.compile(r"^\d{6}$")

SnapshotReader = Callable[[], list[dict[str, Any]]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _normalize_code(code: str) -> str:
    normalized = str(code).strip()
    if not _CODE_RE.fullmatch(normalized):
        raise ValueError("code must be a six-digit A-share code")
    return normalized


def _sign_class(value: float | None) -> str:
    if value is None:
        return "missing"
    if value > 0:
        return "positive"
    if value == 0:
        return "zero"
    return "negative"


def _positive_values(members: list[Mapping[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for member in members:
        value = _number(member.get(field))
        if value is not None and value > 0:
            values.append(value)
    return values


def _compare_metric(
    *,
    stock_row: Mapping[str, Any] | None,
    members: list[Mapping[str, Any]],
    field: str,
    industry_metric: Mapping[str, Any] | None,
) -> dict[str, Any]:
    stock_value = _number(stock_row.get(field) if stock_row else None)
    sign = _sign_class(stock_value)
    positive_values = _positive_values(members, field)
    median = None
    if isinstance(industry_metric, Mapping):
        median = _number(industry_metric.get("positive_median"))
    comparable = sign == "positive" and median is not None
    rank = None
    if sign == "positive" and positive_values:
        rank = sum(1 for value in positive_values if value < stock_value) + 1
    return {
        "stock_value": stock_value,
        "stock_sign": sign,
        "industry_positive_median": median,
        "vs_industry_positive_median": (stock_value - median) if comparable else None,
        "rank_among_positive": rank,
        "positive_sample_count": len(positive_values),
        "rank_order": "ASCENDING_POSITIVE_VALUES",
        "industry_observed_count": industry_metric.get("observed_count") if isinstance(industry_metric, Mapping) else 0,
        "industry_missing_count": industry_metric.get("missing_count") if isinstance(industry_metric, Mapping) else 0,
        "industry_positive_count": industry_metric.get("positive_count") if isinstance(industry_metric, Mapping) else 0,
        "industry_zero_count": industry_metric.get("zero_count") if isinstance(industry_metric, Mapping) else 0,
        "industry_negative_count": industry_metric.get("negative_count") if isinstance(industry_metric, Mapping) else 0,
        "industry_median_status": (
            industry_metric.get("median_status") if isinstance(industry_metric, Mapping) else "NO_POSITIVE_VALUES"
        ),
    }


def _empty_metric() -> dict[str, Any]:
    return _compare_metric(stock_row=None, members=[], field="pe_ttm", industry_metric=None)


def _base_envelope(
    *,
    code: str,
    fetched_at: str,
    status: str,
    industry_name: str | None,
    industry_status: str,
    industry_member_count: int,
    pe_ttm: dict[str, Any],
    pb: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source": SOURCE,
        "fetched_at": fetched_at,
        "code": code,
        "industry_name": industry_name,
        "industry_status": industry_status,
        "industry_membership_semantics": sic.MEMBERSHIP_SEMANTICS,
        "valuation_semantics": sic.VALUATION_SEMANTICS,
        "historical_valuation_status": sic.HISTORICAL_VALUATION_STATUS,
        "sector_index_valuation_authority": "NOT_AVAILABLE",
        "industry_member_count": industry_member_count,
        "pe_source": PE_SOURCE,
        "pb_source": PB_SOURCE,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "provenance": {
            "classification_provider": sic.CLASSIFICATION_PROVIDER,
            "membership_source": "astock.a_share_snapshot.industry=f100",
            "membership_semantics": sic.MEMBERSHIP_SEMANTICS,
            "pe_ttm_field": "f115",
            "pb_field": "f23",
            "dynamic_pe_field": "f9",
            "dynamic_pe_used": False,
        },
        "warnings": warnings,
        "limitations": [
            sic.VALUATION_MESSAGE,
            sic.VALUATION_LIMITATION,
            "个股 PE-TTM 只读 Eastmoney clist f115，缺失时不回退到动态市盈率 f9。",
            "相对行业的差值是当前正值中位数差，不是历史分位，也不是便宜/贵或买卖建议。",
            "正值样本位次按从小到大排列，仅描述当前成员快照，不构成评分。",
        ],
    }


def build_stock_valuation_context(
    code: str,
    *,
    snapshot_reader: SnapshotReader | None = None,
) -> dict[str, Any]:
    """Build one read-only current stock versus current-industry valuation view."""
    normalized_code = _normalize_code(code)
    fetched_at = _utc_now()
    warnings: list[str] = []

    try:
        groups, _invalid_rows = sic.read_current_membership_groups(
            snapshot_reader=snapshot_reader or astock.a_share_snapshot
        )
    except Exception:  # noqa: BLE001 — snapshot failure is isolated and fail-closed
        warnings.append("当前行业估值快照不可用；未将缺失估值伪装成 0。")
        return _base_envelope(
            code=normalized_code,
            fetched_at=fetched_at,
            status="unavailable",
            industry_name=None,
            industry_status="unavailable",
            industry_member_count=0,
            pe_ttm=_empty_metric(),
            pb=_empty_metric(),
            warnings=warnings,
        )

    stock_row: dict[str, Any] | None = None
    industry_name: str | None = None
    for name, members in groups.items():
        for member in members:
            if member.get("code") == normalized_code:
                stock_row = member
                industry_name = name
                break
        if stock_row is not None:
            break

    if stock_row is None:
        warnings.append("当前快照没有该股票；未生成个股或行业估值。")
        return _base_envelope(
            code=normalized_code,
            fetched_at=fetched_at,
            status="unavailable",
            industry_name=None,
            industry_status="unavailable",
            industry_member_count=0,
            pe_ttm=_empty_metric(),
            pb=_empty_metric(),
            warnings=warnings,
        )

    if industry_name == UNKNOWN_INDUSTRY or not industry_name:
        industry_status = "unknown"
        members: list[dict[str, Any]] = []
        industry_metric_pe = None
        industry_metric_pb = None
        warnings.append("当前股票行业为 UNKNOWN；不计算行业估值中位数。")
        industry_name = UNKNOWN_INDUSTRY
    else:
        industry_status = "normal"
        members = list(groups.get(industry_name) or [])
        industry_valuation = sic.build_current_member_valuation(members)
        industry_metric_pe = industry_valuation.get("pe_ttm")
        industry_metric_pb = industry_valuation.get("pb")

    pe_ttm = _compare_metric(
        stock_row=stock_row,
        members=members,
        field="pe_ttm",
        industry_metric=industry_metric_pe,
    )
    pb = _compare_metric(
        stock_row=stock_row,
        members=members,
        field="pb",
        industry_metric=industry_metric_pb,
    )

    complete = (
        industry_status == "normal"
        and pe_ttm["stock_sign"] == "positive"
        and pb["stock_sign"] == "positive"
        and pe_ttm["industry_positive_median"] is not None
        and pb["industry_positive_median"] is not None
    )
    status = "normal" if complete else "partial"
    return _base_envelope(
        code=normalized_code,
        fetched_at=fetched_at,
        status=status,
        industry_name=industry_name,
        industry_status=industry_status,
        industry_member_count=len(members),
        pe_ttm=pe_ttm,
        pb=pb,
        warnings=warnings,
    )


__all__ = [
    "SCHEMA_VERSION",
    "SOURCE",
    "PE_SOURCE",
    "PB_SOURCE",
    "build_stock_valuation_context",
]
