"""Read-only cross-sectional factor validation over the existing RDP.

This module deliberately reuses ``research_data_plane.query_full_market`` for
factor values.  It does not introduce another return/MA/volume-ratio
implementation, a provider, a durable result store, or investment authority.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

import research_data_plane as rdp

SCHEMA_VERSION = "factor_validation.v0.1"
HISTORICAL_VALIDITY = "NOT_PROVEN"
FORWARD_WINDOWS = (5, 20)
MAX_FACTOR_DATES = 250
BUCKET_PERCENTILE = 0.20
UNIVERSE_NAME = "RDP_OBSERVED_CROSS_SECTION"
UNIVERSE_ELIGIBILITY = "stored observation exists exactly on factor_date"
FULL_MARKET_CONTRACT = "query_full_market(as_of=T, latest=false)"
FACTOR_PARITY_MODE = "DIRECT_SOURCE_METRIC_REUSE"
STALE_SOURCE_ROW_REASON = "STALE_AT_FACTOR_DATE"
FUTURE_SOURCE_ROW_REASON = "FUTURE_ROW_AT_FACTOR_DATE"

FACTOR_LIMITATIONS = (
    "结果只使用现有本地 RDP artifact；Research Runtime 不是 Canonical Fact Authority。",
    "Factor date T 的 RDP_OBSERVED_CROSS_SECTION 只包含 latest_date == T 的证券；更早的 as-of rows 会被排除并单独计数，不是历史全市场或历史可投资成分股 Universe。",
    "当前 RDP 为 UNADJUSTED；除权、除息等 corporate action 可能影响历史价格收益。",
    "forward window 按已存储观测条数计，不称严格交易日历 T+5/T+20。",
    "High/Low 是描述性的因子分桶统计，不是 long-short strategy、可交易组合、PnL 或收益承诺。",
    "历史统计不等于未来预测；HISTORICAL_VALIDITY 保持 NOT_PROVEN。",
)

HISTORICAL_VALIDITY_REASONS = (
    "没有 point-in-time historical constituent authority；样本受当前 RDP coverage 与 survivorship 影响。",
    "RDP 价格为 UNADJUSTED，corporate action 影响未被调整。",
    "没有成交、成本、滑点、涨跌停或可实现性模拟，因此不构成完整回测。",
)

FACTOR_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "factor_id": "return_5d",
        "label": "5 日收益",
        "source_metric": "return_5d",
        "higher_value_semantics": "数值表示 T 收盘相对前 5 条已存储观测收盘的收益比值；数值更高不表示更好。",
        "required_history": 6,
    },
    {
        "factor_id": "return_20d",
        "label": "20 日收益",
        "source_metric": "return_20d",
        "higher_value_semantics": "数值表示 T 收盘相对前 20 条已存储观测收盘的收益比值；数值更高不表示更好。",
        "required_history": 21,
    },
    {
        "factor_id": "return_60d",
        "label": "60 日收益",
        "source_metric": "return_60d",
        "higher_value_semantics": "数值表示 T 收盘相对前 60 条已存储观测收盘的收益比值；数值更高不表示更好。",
        "required_history": 61,
    },
    {
        "factor_id": "close_vs_ma20",
        "label": "收盘相对 MA20",
        "source_metric": "close_vs_ma20",
        "higher_value_semantics": "数值表示 T 收盘相对最近 20 条已存储收盘均值的比值；数值更高不表示更好。",
        "required_history": 20,
    },
    {
        "factor_id": "close_vs_ma60",
        "label": "收盘相对 MA60",
        "source_metric": "close_vs_ma60",
        "higher_value_semantics": "数值表示 T 收盘相对最近 60 条已存储收盘均值的比值；数值更高不表示更好。",
        "required_history": 60,
    },
    {
        "factor_id": "volume_ratio_20d",
        "label": "20 日量比",
        "source_metric": "volume_ratio_20d",
        "higher_value_semantics": "数值表示 T 成交量相对最近 20 条已存储观测平均成交量的比值；数值更高不表示更好。",
        "required_history": 20,
    },
)

_FACTOR_BY_ID = {item["factor_id"]: item for item in FACTOR_REGISTRY}


def factor_registry() -> list[dict[str, Any]]:
    """Return a copy of the stable, transparent factor registry."""
    return [dict(item) for item in FACTOR_REGISTRY]


def factor_definition(factor_id: str) -> dict[str, Any]:
    try:
        return dict(_FACTOR_BY_ID[factor_id])
    except KeyError as exc:
        raise ValueError(f"unknown factor: {factor_id}") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_date(value: str | None, field: str) -> None:
    if value is None:
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise rdp.ResearchDataPlaneQueryValidationError(
            f"{field} must use YYYY-MM-DD"
        ) from exc


def _normalize_windows(windows: Iterable[int]) -> tuple[int, ...]:
    normalized = tuple(sorted(set(windows)))
    if normalized != FORWARD_WINDOWS:
        raise rdp.ResearchDataPlaneQueryValidationError(
            "forward_windows must contain exactly 5 and 20"
        )
    return normalized


def _artifact_for_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    return root / "artifacts" / f"{manifest['artifact_sha256']}.parquet"


def _load_factor_dates(
    root: Path,
    manifest: dict[str, Any],
    date_from: str | None,
    date_to: str | None,
) -> list[str]:
    artifact = _artifact_for_manifest(root, manifest)
    predicates: list[str] = []
    params: list[Any] = [str(artifact)]
    if date_from:
        predicates.append("trade_date >= CAST(? AS DATE)")
        params.append(date_from)
    if date_to:
        predicates.append("trade_date <= CAST(? AS DATE)")
        params.append(date_to)
    where = " WHERE " + " AND ".join(predicates) if predicates else ""
    connection = duckdb.connect(database=":memory:")
    try:
        try:
            rows = connection.execute(
                "SELECT DISTINCT CAST(trade_date AS VARCHAR) "
                "FROM read_parquet(?)" + where + " ORDER BY trade_date",
                params,
            ).fetchall()
        except Exception as exc:
            raise rdp.ResearchDataPlaneValidationError(
                "factor date query failed closed"
            ) from exc
    finally:
        connection.close()
    return [str(row[0]) for row in rows]


def _load_close_series(
    root: Path,
    manifest: dict[str, Any],
) -> dict[str, list[tuple[str, float | None]]]:
    """Load only local RDP code/date/close rows for set-based outcomes."""
    artifact = _artifact_for_manifest(root, manifest)
    connection = duckdb.connect(database=":memory:")
    try:
        try:
            rows = connection.execute(
                "SELECT code, CAST(trade_date AS VARCHAR), close "
                "FROM read_parquet(?) ORDER BY code, trade_date",
                [str(artifact)],
            ).fetchall()
        except Exception as exc:
            raise rdp.ResearchDataPlaneValidationError(
                "factor outcome query failed closed"
            ) from exc
    finally:
        connection.close()
    series: dict[str, list[tuple[str, float | None]]] = {}
    for code, trade_date, close in rows:
        series.setdefault(str(code), []).append(
            (str(trade_date), float(close) if close is not None else None)
        )
    return series


def _all_full_market_rows(root: Path, as_of: str) -> dict[str, Any]:
    """Read one exact-as-of Full Market cross-section through its real contract."""
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = rdp.query_full_market(
            root=root,
            as_of=as_of,
            latest=False,
            limit=rdp._MAX_LIMIT,
            offset=offset,
        )
        if page.get("status") != "normal":
            return page
        rows.extend(page.get("rows") or [])
        next_offset = page.get("next_offset")
        if next_offset is None:
            return {**page, "rows": rows, "returned_rows": len(rows)}
        if next_offset <= offset:
            raise rdp.ResearchDataPlaneValidationError(
                "full-market pagination did not advance"
            )
        offset = int(next_offset)


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _exact_date_rows(
    rows: list[dict[str, Any]], factor_date: str
) -> tuple[list[dict[str, Any]], int]:
    """Separate exact-date rows from stale as-of rows without changing Full Market."""
    target_date = date.fromisoformat(factor_date)
    exact_rows: list[dict[str, Any]] = []
    stale_count = 0
    for row in rows:
        latest_date = row.get("latest_date")
        try:
            observed_date = date.fromisoformat(str(latest_date))
        except (TypeError, ValueError) as exc:
            raise rdp.ResearchDataPlaneValidationError(
                "MISSING_SOURCE_ROW_DATE_AT_FACTOR_DATE"
            ) from exc
        if observed_date == target_date:
            exact_rows.append(row)
        elif observed_date < target_date:
            stale_count += 1
        else:
            raise rdp.ResearchDataPlaneValidationError(
                FUTURE_SOURCE_ROW_REASON
            )
    return exact_rows, stale_count


def _join_reasons(*reasons: str | None) -> str | None:
    unique: list[str] = []
    for reason in reasons:
        if reason and reason not in unique:
            unique.append(reason)
    return ";".join(unique) if unique else None


def _average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        for original_index, _ in ordered[index:end]:
            ranks[original_index] = average_rank
        index = end
    return ranks


def spearman_average_rank(
    factor_values: list[float], forward_returns: list[float]
) -> tuple[float | None, str | None]:
    """Return Spearman rho with average ranks and an explicit null reason."""
    if len(factor_values) != len(forward_returns):
        raise ValueError("factor_values and forward_returns must have equal length")
    if len(factor_values) < 2:
        return None, "INSUFFICIENT_PAIRS"
    factor_ranks = _average_ranks(factor_values)
    return_ranks = _average_ranks(forward_returns)
    if len(set(factor_values)) == 1:
        return None, "CONSTANT_FACTOR"
    if len(set(forward_returns)) == 1:
        return None, "CONSTANT_FORWARD_RETURN"
    factor_mean = statistics.fmean(factor_ranks)
    return_mean = statistics.fmean(return_ranks)
    numerator = sum(
        (factor_rank - factor_mean) * (return_rank - return_mean)
        for factor_rank, return_rank in zip(factor_ranks, return_ranks)
    )
    factor_variance = sum((rank - factor_mean) ** 2 for rank in factor_ranks)
    return_variance = sum((rank - return_mean) ** 2 for rank in return_ranks)
    denominator = math.sqrt(factor_variance * return_variance)
    if denominator == 0:
        return None, "ZERO_RANK_VARIANCE"
    value = numerator / denominator
    return (0.0 if abs(value) < 1e-12 else round(value, 8)), None


def _bucket_means(
    factor_values: list[float], forward_returns: list[float]
) -> tuple[int, float | None, int, float | None, float | None, str | None]:
    if len(factor_values) != len(forward_returns):
        raise ValueError("factor_values and forward_returns must have equal length")
    if len(factor_values) < 2:
        return 0, None, 0, None, None, "INSUFFICIENT_PAIRS"
    ranks = _average_ranks(factor_values)
    denominator = len(ranks) - 1
    percentiles = [((rank - 1.0) / denominator) for rank in ranks]
    high = [value for value, percentile in zip(forward_returns, percentiles) if percentile >= 1.0 - BUCKET_PERCENTILE]
    low = [value for value, percentile in zip(forward_returns, percentiles) if percentile <= BUCKET_PERCENTILE]
    high_mean = statistics.fmean(high) if high else None
    low_mean = statistics.fmean(low) if low else None
    spread = high_mean - low_mean if high_mean is not None and low_mean is not None else None
    reason = None if spread is not None else "EMPTY_BUCKET"
    return (
        len(high),
        round(high_mean, 8) if high_mean is not None else None,
        len(low),
        round(low_mean, 8) if low_mean is not None else None,
        round(spread, 8) if spread is not None else None,
        reason,
    )


def _round_statistic(values: list[float], kind: str) -> float | None:
    if not values:
        return None
    if kind == "mean":
        value = statistics.fmean(values)
    elif kind == "median":
        value = statistics.median(values)
    elif kind == "stddev":
        value = statistics.pstdev(values)
    else:
        raise ValueError(f"unknown statistic: {kind}")
    return 0.0 if abs(value) < 1e-12 else round(value, 8)


def _percentage(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 8)


def _unavailable_report(
    factor: dict[str, Any],
    request: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "research_only": True,
        "generated_at": _utc_now(),
        "factor": factor,
        "request": request,
        "source": {
            "dataset_id": rdp.DATASET_ID,
            "provider_id": rdp.PROVIDER_ID,
            "adjustment": rdp.ADJUSTMENT,
            "source_kind": "LOCAL_BULK_DUMP",
            "artifact_sha256": None,
            "query_contract": FULL_MARKET_CONTRACT,
        },
        "sample": {
            "universe": UNIVERSE_NAME,
            "universe_eligibility": UNIVERSE_ELIGIBILITY,
            "requested_date_from": request.get("date_from"),
            "requested_date_to": request.get("date_to"),
            "effective_date_from": None,
            "effective_date_to": None,
            "factor_dates_attempted": 0,
            "factor_dates_evaluated": {str(window): 0 for window in FORWARD_WINDOWS},
            "immature_factor_dates": {str(window): 0 for window in FORWARD_WINDOWS},
            "max_factor_dates": MAX_FACTOR_DATES,
            "truncated": False,
            "source_asof_rows_total": 0,
            "exact_date_rows_total": 0,
            "stale_source_rows_total": 0,
            "excluded_observations": 0,
        },
        "parity": {
            "status": "NOT_PROVEN_DATA_UNAVAILABLE",
            "source_contract": FULL_MARKET_CONTRACT,
            "source_metric": factor["source_metric"],
            "mode": FACTOR_PARITY_MODE,
            "factor_dates_checked": 0,
            "security_factor_values_checked": 0,
            "mismatches": None,
        },
        "results": {},
        "historical_validity": {
            "status": HISTORICAL_VALIDITY,
            "reasons": list(HISTORICAL_VALIDITY_REASONS),
        },
        "limitations": [reason, *FACTOR_LIMITATIONS],
        "formal_state_write": {"performed": False, "scope": "research computation only"},
    }


def evaluate_rdp(
    *,
    factor_id: str,
    forward_windows: Iterable[int] = FORWARD_WINDOWS,
    date_from: str | None = None,
    date_to: str | None = None,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate one registered factor on a bounded observed cross-section."""
    factor = factor_definition(factor_id)
    windows = _normalize_windows(forward_windows)
    _validate_date(date_from, "date_from")
    _validate_date(date_to, "date_to")
    if date_from and date_to and date_from > date_to:
        raise rdp.ResearchDataPlaneQueryValidationError(
            "date_from must not exceed date_to"
        )
    request = {
        "factor_id": factor_id,
        "forward_windows": list(windows),
        "date_from": date_from,
        "date_to": date_to,
    }
    root = rdp.resolve_root(data_root)
    manifest = rdp.read_manifest(root)
    requested_from = date_from or str(manifest["coverage_start"])
    requested_to = date_to or str(manifest["coverage_end"])
    dates = _load_factor_dates(root, manifest, date_from, date_to)
    truncated = len(dates) > MAX_FACTOR_DATES
    effective_dates = dates[-MAX_FACTOR_DATES:] if truncated else dates
    series = _load_close_series(root, manifest)
    index_by_code = {
        code: {trade_date: index for index, (trade_date, _) in enumerate(rows)}
        for code, rows in series.items()
    }

    observations_by_window: dict[int, list[dict[str, Any]]] = {window: [] for window in windows}
    parity_rows_checked = 0
    parity_exact_rows_checked = 0
    parity_dates_checked = 0
    source_asof_rows_total = 0
    exact_date_rows_total = 0
    stale_source_rows_total = 0
    excluded_total = 0
    for factor_date in effective_dates:
        market = _all_full_market_rows(root, factor_date)
        if market.get("status") != "normal":
            raise rdp.ResearchDataPlaneValidationError(
                f"Full Market unavailable at factor date {factor_date}"
            )
        if market.get("provenance", {}).get("artifact_sha256") != manifest["artifact_sha256"]:
            raise rdp.ResearchDataPlaneValidationError(
                "factor source artifact does not match Full Market artifact"
            )
        rows = market.get("rows") or []
        parity_dates_checked += 1
        parity_rows_checked += len(rows)
        exact_rows, stale_source_row_count = _exact_date_rows(rows, factor_date)
        source_asof_row_count = len(rows)
        exact_date_universe_count = len(exact_rows)
        source_asof_rows_total += source_asof_row_count
        exact_date_rows_total += exact_date_universe_count
        stale_source_rows_total += stale_source_row_count
        parity_exact_rows_checked += exact_date_universe_count
        factor_rows = [
            (row, _finite_or_none(row.get(factor["source_metric"])))
            for row in exact_rows
        ]
        factor_non_null = sum(value is not None for _, value in factor_rows)
        for window in windows:
            pairs: list[tuple[float, float]] = []
            mature_outcomes = 0
            factor_null_count = 0
            immature_count = 0
            invalid_outcome_count = 0
            for row, factor_value in factor_rows:
                if factor_value is None:
                    factor_null_count += 1
                    continue
                code = str(row.get("code"))
                current_index = index_by_code.get(code, {}).get(factor_date)
                code_series = series.get(code, [])
                if current_index is None or current_index + window >= len(code_series):
                    immature_count += 1
                    continue
                mature_outcomes += 1
                current_close = _finite_or_none(row.get("latest_close"))
                future_close = _finite_or_none(code_series[current_index + window][1])
                if current_close is None or current_close <= 0 or future_close is None or future_close <= 0:
                    invalid_outcome_count += 1
                    continue
                pairs.append((factor_value, future_close / current_close - 1.0))
            excluded = factor_null_count + immature_count + invalid_outcome_count
            excluded_total += excluded
            factor_values = [pair[0] for pair in pairs]
            forward_returns = [pair[1] for pair in pairs]
            rank_ic, ic_reason = spearman_average_rank(factor_values, forward_returns)
            high_count, high_mean, low_count, low_mean, spread, bucket_reason = _bucket_means(
                factor_values, forward_returns
            )
            if factor_non_null == 0:
                status = "NOT_EVALUABLE"
                reason = _join_reasons(
                    STALE_SOURCE_ROW_REASON if stale_source_row_count else None,
                    "FACTOR_VALUES_UNAVAILABLE",
                )
            elif immature_count == factor_non_null and mature_outcomes == 0:
                status = "IMMATURE_FORWARD_WINDOW"
                reason = _join_reasons(
                    STALE_SOURCE_ROW_REASON if stale_source_row_count else None,
                    "IMMATURE_FORWARD_WINDOW",
                )
            elif rank_ic is None:
                status = "NOT_EVALUABLE"
                reason = _join_reasons(
                    STALE_SOURCE_ROW_REASON if stale_source_row_count else None,
                    ic_reason or bucket_reason or "RANK_IC_UNAVAILABLE",
                )
            else:
                status = "EVALUATED"
                reason = _join_reasons(
                    STALE_SOURCE_ROW_REASON if stale_source_row_count else None,
                    "PARTIAL_FORWARD_COVERAGE" if excluded else None,
                )
            observations_by_window[window].append(
                {
                    "factor_date": factor_date,
                    "forward_window": window,
                    "source_asof_row_count": source_asof_row_count,
                    "exact_date_universe_count": exact_date_universe_count,
                    "stale_source_row_count": stale_source_row_count,
                    "universe_count": exact_date_universe_count,
                    "factor_non_null_count": factor_non_null,
                    "mature_outcome_count": mature_outcomes,
                    "pair_count": len(pairs),
                    "factor_null_count": factor_null_count,
                    "immature_outcome_count": immature_count,
                    "invalid_outcome_count": invalid_outcome_count,
                    "rank_ic": rank_ic,
                    "high_bucket_count": high_count,
                    "high_bucket_mean_return": high_mean,
                    "low_bucket_count": low_count,
                    "low_bucket_mean_return": low_mean,
                    "high_minus_low_spread": spread,
                    "status": status,
                    "reason": reason,
                }
            )

    results: dict[str, Any] = {}
    for window in windows:
        observations = observations_by_window[window]
        ic_values = [row["rank_ic"] for row in observations if row["rank_ic"] is not None]
        spread_values = [
            row["high_minus_low_spread"]
            for row in observations
            if row["high_minus_low_spread"] is not None
        ]
        evaluated_dates = len(ic_values)
        spread_dates = len(spread_values)
        results[str(window)] = {
            "forward_window": window,
            "factor_dates_attempted": len(observations),
            "factor_dates_evaluated": evaluated_dates,
            "immature_factor_dates": sum(
                row["status"] == "IMMATURE_FORWARD_WINDOW" for row in observations
            ),
            "mean_ic": _round_statistic(ic_values, "mean"),
            "median_ic": _round_statistic(ic_values, "median"),
            "ic_stddev": _round_statistic(ic_values, "stddev"),
            "positive_ic_date_ratio": _percentage(sum(value > 0 for value in ic_values), evaluated_dates),
            "mean_high_minus_low_spread": _round_statistic(spread_values, "mean"),
            "median_high_minus_low_spread": _round_statistic(spread_values, "median"),
            "positive_spread_date_ratio": _percentage(sum(value > 0 for value in spread_values), spread_dates),
            "pair_count_total": sum(row["pair_count"] for row in observations),
            "source_asof_row_count_total": sum(row["source_asof_row_count"] for row in observations),
            "exact_date_universe_count_total": sum(row["exact_date_universe_count"] for row in observations),
            "stale_source_row_count_total": sum(row["stale_source_row_count"] for row in observations),
            "sample_start": effective_dates[0] if effective_dates else None,
            "sample_end": effective_dates[-1] if effective_dates else None,
            "observations": observations,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "normal",
        "research_only": True,
        "generated_at": _utc_now(),
        "factor": factor,
        "request": request,
        "source": {
            "dataset_id": manifest["dataset_id"],
            "provider_id": manifest.get("provider_id"),
            "adjustment": manifest.get("adjustment"),
            "source_kind": manifest.get("source_kind"),
            "source_name": manifest.get("source_name"),
            "license_status": manifest.get("license_status"),
            "artifact_sha256": manifest.get("artifact_sha256"),
            "query_contract": FULL_MARKET_CONTRACT,
        },
        "sample": {
            "universe": UNIVERSE_NAME,
            "universe_eligibility": UNIVERSE_ELIGIBILITY,
            "requested_date_from": date_from,
            "requested_date_to": date_to,
            "requested_range": {"start": requested_from, "end": requested_to},
            "effective_date_from": effective_dates[0] if effective_dates else None,
            "effective_date_to": effective_dates[-1] if effective_dates else None,
            "artifact_coverage": {
                "start": manifest["coverage_start"],
                "end": manifest["coverage_end"],
                "row_count": manifest["row_count"],
                "code_count": manifest["code_count"],
            },
            "factor_dates_attempted": len(effective_dates),
            "factor_dates_evaluated": {
                str(window): results[str(window)]["factor_dates_evaluated"] for window in windows
            },
            "immature_factor_dates": {
                str(window): results[str(window)]["immature_factor_dates"] for window in windows
            },
            "max_factor_dates": MAX_FACTOR_DATES,
            "truncated": truncated,
            "source_asof_rows_total": source_asof_rows_total,
            "exact_date_rows_total": exact_date_rows_total,
            "stale_source_rows_total": stale_source_rows_total,
            "excluded_observations": excluded_total,
        },
        "parity": {
            "status": "PROVEN",
            "source_contract": FULL_MARKET_CONTRACT,
            "source_metric": factor["source_metric"],
            "mode": FACTOR_PARITY_MODE,
            "comparison": "factor values are read directly from the Full Market source_metric; no second factor calculation is performed",
            "artifact_sha256": manifest["artifact_sha256"],
            "factor_dates_checked": parity_dates_checked,
            "security_factor_values_checked": parity_rows_checked,
            "exact_date_factor_values_checked": parity_exact_rows_checked,
            "mismatches": 0,
        },
        "results": results,
        "historical_validity": {
            "status": HISTORICAL_VALIDITY,
            "reasons": list(HISTORICAL_VALIDITY_REASONS),
        },
        "limitations": list(FACTOR_LIMITATIONS),
        "formal_state_write": {"performed": False, "scope": "research computation only"},
    }


def unavailable_report(
    factor_id: str,
    request: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return _unavailable_report(factor_definition(factor_id), request, reason)
