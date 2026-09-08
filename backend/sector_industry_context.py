"""Read-only Eastmoney current-industry context matrix.

This is deliberately a current-membership projection, not a sector index or a
historical industry authority.  Classification comes from the current
``a_share_snapshot`` ``industry`` field and historical features come only from
the local Research Data Plane.  The service never writes Formal state or user
data.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

import astock
import research_data_plane as rdp


SCHEMA_VERSION = "sector_industry_context.v0.1"
CLASSIFICATION_PROVIDER = "EASTMONEY"
MEMBERSHIP_SEMANTICS = "CURRENT_MEMBERSHIP_SNAPSHOT"
HISTORICAL_MEMBERSHIP_VALIDITY = "NOT_PROVEN"
CROWDING_SEMANTICS = "TRANSPARENT_PARTICIPATION_PROXY_ONLY"
VALUATION_STATUS = "UNAVAILABLE_IN_V0_1"
_CODE_RE = re.compile(r"^\d{6}$")
_UNKNOWN_INDUSTRY = "UNKNOWN"
_RDP_PAGE_SIZE = 1000
_RDP_MAX_PAGES = 10_000

SnapshotReader = Callable[[], list[dict[str, Any]]]
RdpReader = Callable[..., dict[str, Any]]


class _RdpUnavailable(RuntimeError):
    """The local RDP cannot provide a usable read model for this request."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sum_or_none(values: list[float]) -> float | None:
    return sum(values) if values else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _normalize_snapshot(snapshot: Any) -> tuple[dict[str, list[dict[str, Any]]], int]:
    if not isinstance(snapshot, list):
        raise TypeError("current industry snapshot must be a list")

    groups: dict[str, list[dict[str, Any]]] = {}
    seen_codes: set[str] = set()
    invalid_rows = 0
    for raw in snapshot:
        if not isinstance(raw, Mapping):
            invalid_rows += 1
            continue
        code = str(raw.get("code") or "").strip()
        if not _CODE_RE.fullmatch(code) or code in seen_codes:
            invalid_rows += 1
            continue
        seen_codes.add(code)
        industry = str(raw.get("industry") or "").strip() or _UNKNOWN_INDUSTRY
        groups.setdefault(industry, []).append(
            {
                "code": code,
                "name": str(raw.get("name") or code).strip() or code,
                "industry": industry,
                "change_pct": raw.get("change_pct"),
                "turnover_pct": raw.get("turnover_pct"),
                "amount": raw.get("amount"),
            }
        )
    return groups, invalid_rows


def _read_rdp_rows(rdp_reader: RdpReader) -> tuple[dict[str, dict[str, Any]], str | None, dict[str, Any] | None]:
    rows_by_code: dict[str, dict[str, Any]] = {}
    offset = 0
    as_of: str | None = None
    provenance: dict[str, Any] | None = None

    for _ in range(_RDP_MAX_PAGES):
        try:
            envelope = rdp_reader(
                latest=True,
                sort_by="code",
                sort_order="asc",
                limit=_RDP_PAGE_SIZE,
                offset=offset,
            )
        except Exception as exc:  # noqa: BLE001 — read-only boundary becomes unavailable
            raise _RdpUnavailable(type(exc).__name__) from exc
        if not isinstance(envelope, Mapping):
            raise _RdpUnavailable("invalid_envelope")
        if envelope.get("status") != "normal":
            raise _RdpUnavailable(str(envelope.get("status") or "unavailable"))

        as_of = as_of or (str(envelope.get("as_of")) if envelope.get("as_of") else None)
        if provenance is None and isinstance(envelope.get("provenance"), Mapping):
            provenance = dict(envelope["provenance"])
        raw_rows = envelope.get("rows")
        if not isinstance(raw_rows, list):
            raise _RdpUnavailable("invalid_rows")
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            code = str(raw.get("code") or "").strip()
            if _CODE_RE.fullmatch(code) and code not in rows_by_code:
                rows_by_code[code] = dict(raw)

        next_offset = envelope.get("next_offset")
        if next_offset is None:
            return rows_by_code, as_of, provenance
        try:
            next_offset = int(next_offset)
        except (TypeError, ValueError) as exc:
            raise _RdpUnavailable("invalid_pagination") from exc
        if next_offset <= offset:
            raise _RdpUnavailable("non_progressing_pagination")
        offset = next_offset
    raise _RdpUnavailable("pagination_bound_exceeded")


def _build_breadth(members: list[dict[str, Any]]) -> dict[str, Any]:
    changes = [value for value in (_number(member.get("change_pct")) for member in members) if value is not None]
    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = sum(1 for value in changes if value == 0)
    return {
        "up_member_count": up_count,
        "down_member_count": down_count,
        "flat_member_count": flat_count,
        "change_usable_count": len(changes),
        "change_unavailable_count": len(members) - len(changes),
        "up_ratio": _ratio(up_count, len(changes)),
        "down_ratio": _ratio(down_count, len(changes)),
        "flat_ratio": _ratio(flat_count, len(changes)),
        "basis": "CURRENT_MEMBERS_WITH_CHANGE_PCT",
    }


def _build_item(
    industry_name: str,
    members: list[dict[str, Any]],
    rdp_rows: dict[str, dict[str, Any]],
    *,
    snapshot_as_of: str,
    rdp_as_of: str | None,
    rdp_provenance: dict[str, Any] | None,
    rdp_available: bool,
    rdp_warning: str | None,
) -> dict[str, Any]:
    current_member_count = len(members)
    joined = [rdp_rows[member["code"]] for member in members if member["code"] in rdp_rows]
    return_5d = [value * 100 for value in (_number(row.get("return_5d")) for row in joined) if value is not None]
    return_20d = [value * 100 for value in (_number(row.get("return_20d")) for row in joined) if value is not None]
    ma20_rows = [
        row for row in joined
        if _number(row.get("close_vs_ma20")) is not None and row.get("ma20_status") == "normal"
    ]
    above_ma20_count = sum(1 for row in ma20_rows if float(row["close_vs_ma20"]) > 0)
    turnover = [value for value in (_number(member.get("turnover_pct")) for member in members) if value is not None]
    amounts = [value for value in (_number(member.get("amount")) for member in members) if value is not None and value >= 0]
    volume_ratios = [value for value in (_number(row.get("volume_ratio_20d")) for row in joined) if value is not None]
    missing_rdp = current_member_count - len(joined)
    metric_missing = current_member_count > 0 and (
        len(return_5d) < current_member_count
        or len(return_20d) < current_member_count
        or len(ma20_rows) < current_member_count
    )

    warnings: list[str] = []
    if industry_name == _UNKNOWN_INDUSTRY:
        warnings.append("部分当前成员缺少 Eastmoney industry 字段，保留为 UNKNOWN。")
    if missing_rdp:
        warnings.append(f"{missing_rdp} 个当前成员没有 RDP 可用历史行情，未按 0 参与聚合。")
    if metric_missing and joined:
        warnings.append("部分成员历史观测不足，指标仅对可用成员计算。")
    if rdp_warning:
        warnings.append(rdp_warning)

    if not rdp_available:
        status = "unavailable"
    elif not joined:
        status = "unavailable"
    elif industry_name == _UNKNOWN_INDUSTRY or missing_rdp or metric_missing:
        status = "partial"
    else:
        status = "normal"

    return {
        "industry_key": industry_name,
        "industry_name": industry_name,
        "classification_status": "UNKNOWN" if industry_name == _UNKNOWN_INDUSTRY else "KNOWN",
        "status": status,
        "expected_member_count": current_member_count,
        "current_member_count": current_member_count,
        "rdp_usable_member_count": len(joined),
        "unavailable_member_count": missing_rdp,
        "coverage_ratio": _ratio(len(joined), current_member_count),
        "as_of": snapshot_as_of,
        "snapshot_as_of": snapshot_as_of,
        "rdp_as_of": rdp_as_of,
        "provenance": {
            "classification_provider": CLASSIFICATION_PROVIDER,
            "membership_source": "astock.a_share_snapshot.industry=f100",
            "membership_semantics": MEMBERSHIP_SEMANTICS,
            "rdp": rdp_provenance,
        },
        "metrics": {
            "member_aggregate_return_5d_pct": _mean(return_5d),
            "member_aggregate_return_20d_pct": _mean(return_20d),
            "return_5d_usable_count": len(return_5d),
            "return_20d_usable_count": len(return_20d),
            "member_aggregate_acceleration_5d_pct": None,
            "acceleration_5d_status": "UNAVAILABLE_WITH_CURRENT_RDP_FEATURES",
        },
        "breadth": {
            **_build_breadth(members),
            "above_ma20_count": above_ma20_count,
            "ma20_usable_count": len(ma20_rows),
            "ma20_unavailable_count": current_member_count - len(ma20_rows),
            "above_ma20_ratio": _ratio(above_ma20_count, len(ma20_rows)),
            "ma20_basis": "RDP_MEMBERS_WITH_20_OBSERVATIONS",
        },
        "participation": {
            "turnover_pct_avg": _mean(turnover),
            "turnover_usable_count": len(turnover),
            "amount_total": _sum_or_none(amounts),
            "amount_usable_count": len(amounts),
            "volume_ratio_20d_avg": _mean(volume_ratios),
            "volume_ratio_20d_usable_count": len(volume_ratios),
            "semantics": CROWDING_SEMANTICS,
        },
        "crowding": {
            "status": "PROXY_ONLY",
            "semantics": CROWDING_SEMANTICS,
        },
        "valuation": {
            "status": VALUATION_STATUS,
            "message": "当前数据源未提供可信行业级估值。",
        },
        "warnings": warnings,
        "limitations": [
            "分类：Eastmoney 当前行业。",
            "成员口径：当前快照成员。",
            "历史强弱基于当前成员回看个股历史行情的聚合，不代表历史行业指数。",
            "历史成员有效性：未证明。",
            "缺失成员不按 0 参与聚合。",
            "行业级估值在 v0.1 不可用。",
        ],
    }


def _base_envelope(*, status: str, fetched_at: str, warnings: list[str], items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source": "EASTMONEY_A_SHARE_SNAPSHOT+RESEARCH_DATA_PLANE",
        "fetched_at": fetched_at,
        "as_of": fetched_at,
        "classification_provider": CLASSIFICATION_PROVIDER,
        "membership_semantics": MEMBERSHIP_SEMANTICS,
        "historical_membership_validity": HISTORICAL_MEMBERSHIP_VALIDITY,
        "crowding_semantics": CROWDING_SEMANTICS,
        "valuation_status": VALUATION_STATUS,
        "valuation_message": "当前数据源未提供可信行业级估值。",
        "universe_status": "normal",
        "universe": {"current_member_count": sum(item["current_member_count"] for item in items), "industry_count": len(items)},
        "items": items,
        "warnings": warnings,
        "limitations": [
            "当前行业来自 Eastmoney 快照 industry=f100。",
            "当前成员回看个股 RDP 历史行情，不代表历史行业指数。",
            "历史行业成员有效性未证明。",
            "CROWDING 仅为透明 participation proxy，不生成综合分数。",
            "行业级估值在 v0.1 不可用。",
        ],
    }


def build_sector_industry_context(
    *,
    snapshot_reader: SnapshotReader | None = None,
    rdp_reader: RdpReader | None = None,
) -> dict[str, Any]:
    """Build the deterministic current-industry matrix without any state writes."""
    fetched_at = _utc_now()
    read_snapshot = snapshot_reader or astock.a_share_snapshot
    read_rdp = rdp_reader or rdp.query_full_market

    try:
        snapshot = read_snapshot()
        groups, invalid_rows = _normalize_snapshot(snapshot)
    except Exception as exc:  # noqa: BLE001 — provider failure is an explicit envelope
        return _base_envelope(
            status="unavailable",
            fetched_at=fetched_at,
            warnings=[f"当前行业快照不可用：{type(exc).__name__}"],
            items=[],
        )

    if not groups:
        result = _base_envelope(status="normal", fetched_at=fetched_at, warnings=[], items=[])
        result["universe_status"] = "empty"
        result["warnings"] = ["当前行业快照为空；空结果不等于数据源不可用。"]
        return result

    rdp_rows: dict[str, dict[str, Any]] = {}
    rdp_as_of: str | None = None
    rdp_provenance: dict[str, Any] | None = None
    rdp_available = True
    rdp_warning: str | None = None
    try:
        rdp_rows, rdp_as_of, rdp_provenance = _read_rdp_rows(read_rdp)
    except _RdpUnavailable as exc:
        rdp_available = False
        rdp_warning = f"RDP 当前不可用（{str(exc)}），历史指标保持 UNKNOWN。"

    items = [
        _build_item(
            industry_name,
            members,
            rdp_rows,
            snapshot_as_of=fetched_at,
            rdp_as_of=rdp_as_of,
            rdp_provenance=rdp_provenance,
            rdp_available=rdp_available,
            rdp_warning=rdp_warning,
        )
        for industry_name, members in sorted(
            groups.items(), key=lambda pair: (pair[0] == _UNKNOWN_INDUSTRY, pair[0])
        )
    ]
    if all(item["status"] == "normal" for item in items):
        status = "normal"
    elif any(item["status"] == "normal" for item in items):
        status = "partial"
    else:
        status = "unavailable" if not rdp_available else "partial"

    warnings: list[str] = []
    if invalid_rows:
        warnings.append(f"{invalid_rows} 条快照记录缺少有效股票代码或重复，未纳入行业 universe。")
    if not rdp_available:
        warnings.append(rdp_warning or "RDP 当前不可用。")
    result = _base_envelope(status=status, fetched_at=fetched_at, warnings=warnings, items=items)
    result["universe"] = {
        "current_member_count": sum(item["current_member_count"] for item in items),
        "industry_count": len(items),
        "classified_member_count": sum(item["current_member_count"] for item in items if item["industry_name"] != _UNKNOWN_INDUSTRY),
        "unknown_member_count": next((item["current_member_count"] for item in items if item["industry_name"] == _UNKNOWN_INDUSTRY), 0),
    }
    result["rdp_as_of"] = rdp_as_of
    result["rdp_provenance"] = rdp_provenance
    return result
