"""Read-only stock relative context over the existing Research Data Plane.

The service deliberately joins one paged Full Market read with the existing
Eastmoney current-industry snapshot.  It is a descriptive comparison only:
the current membership snapshot is not historical membership authority, and
the RDP returns remain unadjusted raw price changes.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from statistics import median
from typing import Any

import astock
import research_data_plane as rdp
import sector_industry_context


SCHEMA_VERSION = "stock-relative-context.v0.1"
SOURCE = "RESEARCH_DATA_PLANE+EASTMONEY_CURRENT_INDUSTRY"
MEMBERSHIP_SEMANTICS = "CURRENT_MEMBERSHIP_SNAPSHOT"
ADJUSTMENT = "UNADJUSTED"
RETURN_SEMANTICS = "UNADJUSTED_RAW_PRICE_CHANGE"
RELATIVE_UNIT = "PERCENTAGE_POINTS"
UNKNOWN_INDUSTRY = "UNKNOWN"
HORIZONS = (5, 20, 60)
_CODE_RE = re.compile(r"^\d{6}$")
_RDP_PAGE_SIZE = rdp._MAX_LIMIT
_RDP_MAX_PAGES = 10_000

SnapshotReader = Callable[[], list[dict[str, Any]]]
RdpReader = Callable[..., dict[str, Any]]


class _RdpUnavailable(RuntimeError):
    """The local RDP did not provide a safe read model for this request."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_value(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _normalize_code(code: str) -> str:
    normalized = str(code).strip()
    if not _CODE_RE.fullmatch(normalized):
        raise ValueError("code must be a six-digit A-share code")
    return normalized


def _metric_value(row: Mapping[str, Any], horizon: int) -> float | None:
    status = row.get(f"return_{horizon}d_status")
    if status is not None and str(status).lower() != "normal":
        return None
    value = _finite_number(row.get(f"return_{horizon}d"))
    # RDP stores returns as decimals; this service exposes percentage values.
    return value * 100 if value is not None else None


def _relative(stock: float | None, benchmark: float | None) -> float | None:
    if stock is None or benchmark is None:
        return None
    return stock - benchmark


def _coverage(valid_count: int, total_count: int, *, source_available: bool) -> float | None:
    if not source_available or total_count <= 0:
        return None
    return valid_count / total_count


def _empty_period(
    *,
    industry_member_count: int = 0,
    market_total_count: int = 0,
    source_available: bool = False,
) -> dict[str, Any]:
    return {
        "stock_return_pct": None,
        "industry_median_pct": None,
        "vs_industry_pct_points": None,
        "market_median_pct": None,
        "vs_market_pct_points": None,
        "industry_valid_count": 0,
        "industry_member_count": industry_member_count,
        "industry_coverage": _coverage(
            0, industry_member_count, source_available=source_available
        ),
        "market_valid_count": 0,
        "market_total_count": market_total_count,
        "market_coverage": _coverage(
            0, market_total_count, source_available=source_available
        ),
    }


def _base_envelope(
    *,
    code: str,
    fetched_at: str,
    status: str,
    comparison_date: str | None,
    industry_name: str | None,
    industry_status: str,
    periods: dict[str, dict[str, Any]],
    warnings: list[str],
    provenance: Mapping[str, Any] | None,
    dataset_id: str = rdp.DATASET_ID,
    provider_id: str = rdp.PROVIDER_ID,
    adjustment: str = ADJUSTMENT,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source": SOURCE,
        "fetched_at": fetched_at,
        "code": code,
        "comparison_date": comparison_date,
        "industry_name": industry_name,
        "industry_status": industry_status,
        "industry_membership_semantics": MEMBERSHIP_SEMANTICS,
        "dataset_id": dataset_id,
        "provider_id": provider_id,
        "adjustment": adjustment,
        "return_semantics": RETURN_SEMANTICS,
        "relative_unit": RELATIVE_UNIT,
        "stock": {
            "return_5d_pct": periods["5D"]["stock_return_pct"],
            "return_20d_pct": periods["20D"]["stock_return_pct"],
            "return_60d_pct": periods["60D"]["stock_return_pct"],
        },
        "periods": periods,
        "provenance": {
            "classification_provider": "EASTMONEY",
            "membership_source": "astock.a_share_snapshot.industry=f100",
            "membership_semantics": MEMBERSHIP_SEMANTICS,
            "rdp": dict(provenance) if isinstance(provenance, Mapping) else None,
        },
        "warnings": warnings,
        "limitations": [
            "行业来自 Eastmoney 当前成员快照，仅表示 CURRENT_MEMBERSHIP_SNAPSHOT，不代表历史行业成员或历史行业指数。",
            "RDP 指标是未复权原始价格变化（UNADJUSTED），可能受分红、送转和除权影响，不等同于总回报。",
            "行业和市场 benchmark 只纳入 latest_date 等于 comparison_date 的记录；stale、future、缺失、非有限值和观测不足不按 0 参与。",
            "这是只读研究事实展示，不生成推荐、评分或正式状态写入。",
        ],
    }


def _read_full_market(
    read_rdp: RdpReader,
) -> tuple[list[dict[str, Any]], date, dict[str, Any] | None, str, str, str]:
    rows: list[dict[str, Any]] = []
    offset = 0
    comparison_date: date | None = None
    provenance: dict[str, Any] | None = None
    dataset_id = rdp.DATASET_ID
    provider_id = rdp.PROVIDER_ID
    adjustment = ADJUSTMENT

    for _ in range(_RDP_MAX_PAGES):
        try:
            envelope = read_rdp(
                latest=True,
                sort_by="code",
                sort_order="asc",
                limit=_RDP_PAGE_SIZE,
                offset=offset,
            )
        except Exception as exc:  # noqa: BLE001 — source failure is fail-closed
            raise _RdpUnavailable(type(exc).__name__) from exc

        if not isinstance(envelope, Mapping) or envelope.get("status") != "normal":
            raise _RdpUnavailable("unavailable_envelope")

        envelope_date = _date_value(envelope.get("latest_date") or envelope.get("as_of"))
        if envelope_date is None:
            raise _RdpUnavailable("missing_comparison_date")
        if comparison_date is None:
            comparison_date = envelope_date
        elif envelope_date != comparison_date:
            raise _RdpUnavailable("inconsistent_comparison_date")

        if provenance is None and isinstance(envelope.get("provenance"), Mapping):
            provenance = dict(envelope["provenance"])
        dataset_id = str(envelope.get("dataset_id") or dataset_id)
        provider_id = str(envelope.get("provider_id") or provider_id)
        envelope_adjustment = str(envelope.get("adjustment") or adjustment)
        if envelope_adjustment != ADJUSTMENT:
            raise _RdpUnavailable("unsupported_adjustment")
        adjustment = envelope_adjustment

        raw_rows = envelope.get("rows")
        if not isinstance(raw_rows, list):
            raise _RdpUnavailable("invalid_rows")
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                raise _RdpUnavailable("invalid_row")
            rows.append(dict(raw))

        next_offset = envelope.get("next_offset")
        if next_offset is None:
            return rows, comparison_date, provenance, dataset_id, provider_id, adjustment
        try:
            next_offset = int(next_offset)
        except (TypeError, ValueError) as exc:
            raise _RdpUnavailable("invalid_pagination") from exc
        if next_offset <= offset:
            raise _RdpUnavailable("non_progressing_pagination")
        offset = next_offset

    raise _RdpUnavailable("pagination_bound_exceeded")


def _periods_for_rows(
    *,
    code: str,
    exact_rows: list[dict[str, Any]],
    industry_codes: list[str],
    source_available: bool,
) -> dict[str, dict[str, Any]]:
    rows_by_code = {str(row.get("code") or "").strip(): row for row in exact_rows}
    target_row = rows_by_code.get(code)
    periods: dict[str, dict[str, Any]] = {}

    for horizon in HORIZONS:
        key = f"{horizon}D"
        stock_value = _metric_value(target_row, horizon) if target_row else None
        market_values = [
            value
            for value in (_metric_value(row, horizon) for row in exact_rows)
            if value is not None
        ]
        industry_values = [
            value
            for member_code in industry_codes
            for row in [rows_by_code.get(member_code)]
            if row is not None
            for value in [_metric_value(row, horizon)]
            if value is not None
        ]
        industry_median = median(industry_values) if industry_values else None
        market_median = median(market_values) if market_values else None
        periods[key] = {
            "stock_return_pct": stock_value,
            "industry_median_pct": industry_median,
            "vs_industry_pct_points": _relative(stock_value, industry_median),
            "market_median_pct": market_median,
            "vs_market_pct_points": _relative(stock_value, market_median),
            "industry_valid_count": len(industry_values),
            "industry_member_count": len(industry_codes),
            "industry_coverage": _coverage(
                len(industry_values), len(industry_codes), source_available=source_available
            ),
            "market_valid_count": len(market_values),
            "market_total_count": len(exact_rows),
            "market_coverage": _coverage(
                len(market_values), len(exact_rows), source_available=source_available
            ),
        }
    return periods


def _all_complete(periods: Mapping[str, Mapping[str, Any]]) -> bool:
    required = (
        "stock_return_pct",
        "industry_median_pct",
        "vs_industry_pct_points",
        "market_median_pct",
        "vs_market_pct_points",
    )
    return all(all(period.get(field) is not None for field in required) for period in periods.values())


def build_stock_relative_context(
    code: str,
    *,
    snapshot_reader: SnapshotReader | None = None,
    rdp_reader: RdpReader | None = None,
) -> dict[str, Any]:
    """Build one read-only current stock/industry/market comparison."""
    normalized_code = _normalize_code(code)
    fetched_at = _utc_now()
    read_snapshot = snapshot_reader or astock.a_share_snapshot
    read_rdp = rdp_reader or rdp.query_full_market

    industry_by_code: dict[str, str] | None = None
    try:
        # This calls the existing Eastmoney snapshot exactly once.
        industry_by_code = sector_industry_context.read_current_industry_classification(
            snapshot_reader=read_snapshot
        )
    except Exception:  # noqa: BLE001 — industry failure is isolated from market data
        industry_by_code = None

    industry_name: str | None
    industry_status: str
    industry_codes: list[str]
    warnings: list[str] = []
    if industry_by_code is None:
        industry_name = None
        industry_status = "unavailable"
        industry_codes = []
        warnings.append("当前行业快照不可用；市场比较仍独立基于 RDP exact-date 横截面。")
    else:
        industry_name = industry_by_code.get(normalized_code, UNKNOWN_INDUSTRY)
        if industry_name == UNKNOWN_INDUSTRY:
            industry_status = "unknown"
            industry_codes = []
            warnings.append("当前股票行业为 UNKNOWN；不计算行业 benchmark。")
        else:
            industry_status = "normal"
            industry_codes = [
                member_code
                for member_code, member_industry in industry_by_code.items()
                if member_industry == industry_name
            ]

    try:
        (
            source_rows,
            comparison_date,
            provenance,
            dataset_id,
            provider_id,
            adjustment,
        ) = _read_full_market(read_rdp)
    except _RdpUnavailable:
        periods = {
            f"{horizon}D": _empty_period(
                industry_member_count=len(industry_codes), source_available=False
            )
            for horizon in HORIZONS
        }
        warnings.append("Research Data Plane 当前不可用；未将缺失数据伪装成个股或 benchmark 数值。")
        return _base_envelope(
            code=normalized_code,
            fetched_at=fetched_at,
            status="unavailable",
            comparison_date=None,
            industry_name=industry_name,
            industry_status=industry_status,
            periods=periods,
            warnings=warnings,
            provenance=None,
        )

    comparison_date_text = comparison_date.isoformat()
    exact_rows: list[dict[str, Any]] = []
    stale_count = 0
    for row in source_rows:
        observed_date = _date_value(row.get("latest_date"))
        if observed_date is None:
            warnings.append("RDP source row 缺少合法 latest_date；相对表现整体 fail closed。")
            periods = {
                f"{horizon}D": _empty_period(
                    industry_member_count=len(industry_codes), source_available=False
                )
                for horizon in HORIZONS
            }
            return _base_envelope(
                code=normalized_code,
                fetched_at=fetched_at,
                status="unavailable",
                comparison_date=comparison_date_text,
                industry_name=industry_name,
                industry_status=industry_status,
                periods=periods,
                warnings=warnings,
                provenance=provenance,
                dataset_id=dataset_id,
                provider_id=provider_id,
                adjustment=adjustment,
            )
        if observed_date > comparison_date:
            warnings.append("RDP source row 日期晚于 comparison_date；相对表现整体 fail closed。")
            periods = {
                f"{horizon}D": _empty_period(
                    industry_member_count=len(industry_codes), source_available=False
                )
                for horizon in HORIZONS
            }
            return _base_envelope(
                code=normalized_code,
                fetched_at=fetched_at,
                status="unavailable",
                comparison_date=comparison_date_text,
                industry_name=industry_name,
                industry_status=industry_status,
                periods=periods,
                warnings=warnings,
                provenance=provenance,
                dataset_id=dataset_id,
                provider_id=provider_id,
                adjustment=adjustment,
            )
        if observed_date == comparison_date:
            exact_rows.append(row)
        else:
            stale_count += 1

    if stale_count:
        warnings.append(f"{stale_count} 条 stale RDP source row 未纳入 comparison_date 横截面。")
    if not exact_rows:
        warnings.append("comparison_date 没有可用 RDP 横截面；未生成 benchmark 数值。")
        periods = {
            f"{horizon}D": _empty_period(
                industry_member_count=len(industry_codes), source_available=False
            )
            for horizon in HORIZONS
        }
        return _base_envelope(
            code=normalized_code,
            fetched_at=fetched_at,
            status="unavailable",
            comparison_date=comparison_date_text,
            industry_name=industry_name,
            industry_status=industry_status,
            periods=periods,
            warnings=warnings,
            provenance=provenance,
            dataset_id=dataset_id,
            provider_id=provider_id,
            adjustment=adjustment,
        )

    periods = _periods_for_rows(
        code=normalized_code,
        exact_rows=exact_rows,
        industry_codes=industry_codes,
        source_available=True,
    )
    target_row_present = any(str(row.get("code") or "").strip() == normalized_code for row in exact_rows)
    if not target_row_present:
        warnings.append("目标股票没有 latest_date 等于 comparison_date 的 RDP 记录；个股值保持 null。")
    if industry_status == "normal" and not industry_codes:
        warnings.append("当前行业没有可用成员；行业 benchmark 保持 null。")

    complete = _all_complete(periods)
    status = "normal" if complete and industry_status == "normal" else "partial"
    return _base_envelope(
        code=normalized_code,
        fetched_at=fetched_at,
        status=status,
        comparison_date=comparison_date_text,
        industry_name=industry_name,
        industry_status=industry_status,
        periods=periods,
        warnings=warnings,
        provenance=provenance,
        dataset_id=dataset_id,
        provider_id=provider_id,
        adjustment=adjustment,
    )


__all__ = [
    "ADJUSTMENT",
    "HORIZONS",
    "MEMBERSHIP_SEMANTICS",
    "RELATIVE_UNIT",
    "RETURN_SEMANTICS",
    "SCHEMA_VERSION",
    "build_stock_relative_context",
]
