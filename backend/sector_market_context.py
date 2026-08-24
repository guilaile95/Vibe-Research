"""Current sector strength projected onto the existing Vibe sector catalog."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

import hithink_finance_client as hithink
import sector_research_data as srd


# Explicit catalog matches only. Ambiguous Vibe themes intentionally stay unmapped.
THS_INDEX_BY_SECTOR: dict[str, dict[str, str]] = {
    "humanoid": {"thscode": "886069.TI", "name": "人形机器人", "kind": "concept"},
    "pcb": {"thscode": "884092.TI", "name": "印制电路板", "kind": "industry"},
    "cpo": {"thscode": "886033.TI", "name": "共封装光学(CPO)", "kind": "concept"},
    "solid-state-battery": {"thscode": "886032.TI", "name": "固态电池", "kind": "concept"},
    "low-altitude": {"thscode": "886067.TI", "name": "低空经济", "kind": "concept"},
    "innovative-drug": {"thscode": "886015.TI", "name": "创新药", "kind": "concept"},
    "defense": {"thscode": "885700.TI", "name": "军工", "kind": "concept"},
    "fusion": {"thscode": "886065.TI", "name": "可控核聚变", "kind": "concept"},
    "business-space": {"thscode": "886078.TI", "name": "商业航天", "kind": "concept"},
    "ai-application": {"thscode": "886108.TI", "name": "AI应用", "kind": "concept"},
    "energy-storage": {"thscode": "885921.TI", "name": "储能", "kind": "concept"},
    "data-element": {"thscode": "886041.TI", "name": "数据要素", "kind": "concept"},
}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _return_pct(history: list[dict[str, Any]], sessions: int, end: int | None = None) -> float | None:
    end_index = len(history) - 1 if end is None else end
    start_index = end_index - sessions
    if start_index < 0 or end_index >= len(history):
        return None
    start_close = _finite(history[start_index].get("close"))
    end_close = _finite(history[end_index].get("close"))
    if start_close is None or end_close is None or start_close <= 0:
        return None
    return round((end_close / start_close - 1) * 100, 4)


def _history_metrics(history: list[dict[str, Any]]) -> dict[str, Any]:
    current_5d = _return_pct(history, 5)
    previous_5d = _return_pct(history, 5, len(history) - 6)
    current_20d = _return_pct(history, 20)
    previous_20d = _return_pct(history, 20, len(history) - 6)
    turnover_ratio = None
    if len(history) >= 21:
        latest = _finite(history[-1].get("turnover"))
        previous = [_finite(row.get("turnover")) for row in history[-21:-1]]
        if latest is not None and all(value is not None for value in previous):
            average = sum(value for value in previous if value is not None) / len(previous)
            if average > 0:
                turnover_ratio = round(latest / average, 4)
    return {
        "trade_date": history[-1].get("date") if history else None,
        "return_5d_pct": current_5d,
        "return_20d_pct": current_20d,
        "return_60d_pct": _return_pct(history, 60),
        "return_5d_delta_vs_previous_5d_pct": (
            round(current_5d - previous_5d, 4)
            if current_5d is not None and previous_5d is not None
            else None
        ),
        "turnover_vs_prior_20d": turnover_ratio,
        "prior_20d_return_pct": previous_20d,
    }


def _current_breadth(
    constituents: list[dict[str, str]],
    snapshot_by_code: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    up = down = flat = 0
    changes: list[float] = []
    sample: list[dict[str, Any]] = []
    for member in constituents:
        code = member["ticker"]
        pct = _finite((snapshot_by_code.get(code) or {}).get("change_pct"))
        if pct is not None:
            changes.append(pct)
            if pct > 0:
                up += 1
            elif pct < 0:
                down += 1
            else:
                flat += 1
        if len(sample) < 12:
            sample.append({"code": code, "name": member["name"], "change_pct": pct})
    total = len(constituents)
    valid = len(changes)
    return {
        "constituents_total": total,
        "snapshot_valid_count": valid,
        "coverage_ratio": round(valid / total, 4) if total else None,
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "up_ratio": round(up / valid, 4) if valid else None,
        "equal_weight_change_pct": round(sum(changes) / valid, 4) if valid else None,
        "constituents_sample": sample,
        "constituent_semantics": "CURRENT_CONSTITUENTS_ONLY",
    }


def build_sector_market_context(
    *,
    sector_key: str | None = None,
    index_reader: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the overview batch, or one detail with current-constituent breadth."""
    if sector_key is not None and sector_key not in srd.SECTOR_SOURCES:
        raise ValueError(f"未注册的板块：{sector_key}")
    include_constituents = sector_key is not None
    read_index = index_reader or (
        lambda thscode: hithink.fetch_index_market_observation(
            thscode,
            include_constituents=include_constituents,
            include_constituent_snapshots=include_constituents,
        )
    )
    labels = {key: source.label for key, source in srd.SECTOR_SOURCES.items()}
    observations: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    selected = (
        {sector_key: THS_INDEX_BY_SECTOR[sector_key]}
        if sector_key in THS_INDEX_BY_SECTOR
        else (THS_INDEX_BY_SECTOR if sector_key is None else {})
    )

    with ThreadPoolExecutor(max_workers=min(8, len(selected)) or 1) as pool:
        futures = {
            key: pool.submit(read_index, mapping["thscode"])
            for key, mapping in selected.items()
        }
        for key, future in futures.items():
            try:
                result = future.result()
                if not isinstance(result, dict):
                    raise TypeError("index observation must be an object")
                observations[key] = result
            except Exception as exc:  # noqa: BLE001 — partial isolation at provider boundary
                errors[key] = type(exc).__name__
    items: list[dict[str, Any]] = []
    catalog = (
        {sector_key: srd.SECTOR_SOURCES[sector_key]}
        if sector_key is not None
        else srd.SECTOR_SOURCES
    )
    for key, source in catalog.items():
        mapping = THS_INDEX_BY_SECTOR.get(key)
        base = {
            "sector_key": key,
            "sector_label": labels.get(key) or source.label or key,
            "mapping_status": "mapped" if mapping else "unavailable",
            "index": mapping,
            "status": "unavailable",
            "warnings": [],
            "metrics": None,
            "breadth": None,
            "constituents_as_of_ms": None,
            "constituent_snapshot_as_of_ms": None,
            "rank_20d_within_mapped": None,
            "rank_change_vs_5_sessions_ago": None,
            "rank_universe_count": None,
        }
        if mapping is None:
            base["warnings"] = ["未配置可核验的 Vibe Sector → THS Index 映射"]
            items.append(base)
            continue
        observation = observations.get(key)
        if observation is None:
            base["warnings"] = [f"指数市场观察暂不可用（{errors.get(key, 'unknown')}）"]
            items.append(base)
            continue
        history = observation.get("history")
        constituents = observation.get("constituents")
        constituent_snapshots = observation.get("constituent_snapshots")
        if not isinstance(history, list) or not history:
            base["warnings"] = ["指数市场观察结构不可用"]
            items.append(base)
            continue
        metrics = _history_metrics(history)
        breadth = None
        if include_constituents and isinstance(constituents, list) and isinstance(constituent_snapshots, list):
            snapshot_by_code = {
                row["ticker"]: {"change_pct": row.get("change_pct")}
                for row in constituent_snapshots
                if isinstance(row, dict) and isinstance(row.get("ticker"), str)
            }
            breadth = _current_breadth(constituents, snapshot_by_code)
        warnings: list[str] = []
        status = "normal"
        if any(metrics[name] is None for name in ("return_5d_pct", "return_20d_pct", "return_60d_pct")):
            status = "partial"
            warnings.append("指数历史不足，部分收益窗口不可用")
        if include_constituents and not isinstance(constituents, list):
            status = "partial"
            warnings.append("当前成分股列表暂不可用")
        elif include_constituents and breadth is None:
            status = "partial"
            warnings.append("当前成分股行情快照暂不可用")
        elif breadth is not None and (breadth.get("coverage_ratio") or 0) < 0.8:
            status = "partial"
            warnings.append("当前成分股行情覆盖不足 80%")
        if metrics.get("turnover_vs_prior_20d") is not None:
            warnings.append("成交活跃度为最新交易日成交额/此前20日均值，未做盘中时段归一")
        base.update({
            "status": status,
            "warnings": warnings,
            "metrics": metrics,
            "breadth": breadth,
            "constituents_as_of_ms": observation.get("constituents_as_of_ms"),
            "constituent_snapshot_as_of_ms": observation.get("constituent_snapshot_as_of_ms"),
        })
        items.append(base)

    if sector_key is None:
        current_ranked = sorted(
            [item for item in items if _finite((item.get("metrics") or {}).get("return_20d_pct")) is not None],
            key=lambda item: (-float(item["metrics"]["return_20d_pct"]), item["sector_key"]),
        )
        previous_ranked = sorted(
            [item for item in items if _finite((item.get("metrics") or {}).get("prior_20d_return_pct")) is not None],
            key=lambda item: (-float(item["metrics"]["prior_20d_return_pct"]), item["sector_key"]),
        )
        current_rank = {item["sector_key"]: rank for rank, item in enumerate(current_ranked, 1)}
        previous_rank = {item["sector_key"]: rank for rank, item in enumerate(previous_ranked, 1)}
        for item in items:
            key = item["sector_key"]
            if key not in current_rank:
                continue
            item["rank_20d_within_mapped"] = current_rank[key]
            item["rank_universe_count"] = len(current_ranked)
            if len(current_ranked) == len(previous_ranked) and key in previous_rank:
                item["rank_change_vs_5_sessions_ago"] = previous_rank[key] - current_rank[key]

    successful = sum(item["status"] in {"normal", "partial"} for item in items)
    if successful == 0:
        overall_status = "unavailable"
    elif sector_key is not None:
        overall_status = items[0]["status"]
    else:
        overall_status = "partial" if len(THS_INDEX_BY_SECTOR) < len(items) else "normal"
    warnings = (
        [f"{len(THS_INDEX_BY_SECTOR)}/{len(items)} 个 Vibe Sector 有显式 THS 指数映射"]
        if sector_key is None
        else ["宽度仅使用当前成分股截面，不代表历史成分或指数贡献"]
    )
    return {
        "schema_version": "sector_market_context.v0.1",
        "status": overall_status,
        "source": (
            "hithink_index+hithink_stock_snapshot"
            if sector_key is not None
            else "hithink_index"
        ),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "mapped_count": sum(item["mapping_status"] == "mapped" for item in items),
        "total_count": len(items),
        "warnings": warnings,
        "items": items,
    }


__all__ = [
    "THS_INDEX_BY_SECTOR",
    "_current_breadth",
    "_history_metrics",
    "build_sector_market_context",
]
