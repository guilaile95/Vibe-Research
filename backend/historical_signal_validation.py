"""Read-only Historical Signal Validation v0.1 calculation and RDP adapter.

This module is the production home of the former signal-effect-study protocol.
It is deliberately research-only: it computes observations from the local RDP
read model and never writes a formal research, decision, signal, trade, or
portfolio record.
"""
from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import research_data_plane as rdp

SCHEMA_VERSION = "historical_signal_validation.v0.1"
SIGNAL_ID = "sma20_gt_sma60"
SIGNAL_VERSION = "signal_effect_study.v0.2@7485848"
SMA_FAST, SMA_SLOW = 20, 60
WINDOWS = (5, 20)
HISTORICAL_VALIDITY = "NOT_PROVEN"

VALIDITY_REASONS = (
    "RDP dataset is LOCAL_BULK_DUMP with ADJUSTMENT=UNADJUSTED; ex-dividend gaps distort close-to-close returns",
    "no historical constituent universe; the sample is the explicit --codes list and cannot be generalized",
    "close-to-close observation is not realizable trade return: no fills, limit-up/down, slippage or fees",
)

LIMITATIONS = (
    "观察收益不等于可实现交易收益；未计算策略净值、成本与成交约束。",
    "结果仅为所选样本的描述统计；没有可信历史股票池，不能推广成全市场有效。",
    "同一份数据上的任何规则改动都构成新实验，须重跑并另存输出，不得叠加比较。",
    "窗口按已存储观测条数计（未应用交易日历）；每事件实际起止日期见逐事件明细。",
)

SIGNAL_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "id": SIGNAL_ID,
        "version": SIGNAL_VERSION,
        "definition": "SMA20 > SMA60 at close of session T (arithmetic mean of the last 20/60 stored closes, including T)",
        "availability": "computable after close of T; uses data <= T only",
        "event_semantics": "False->True crossing only; T-1 must be evaluable and False; continuous True is deduplicated; unknown prior is excluded",
        "required_fields": ["trade_date", "close"],
        "evaluability": "SMA20 and SMA60 both require enough stored observations; missing close keeps the observation unevaluable",
        "stable": True,
    },
)


def signal_registry() -> list[dict[str, Any]]:
    """Return the deterministic public registry without exposing mutable state."""
    return [dict(item, required_fields=list(item["required_fields"])) for item in SIGNAL_REGISTRY]


def signal_definition(signal_id: str = SIGNAL_ID) -> dict[str, Any]:
    for item in SIGNAL_REGISTRY:
        if item["id"] == signal_id:
            return dict(item, required_fields=list(item["required_fields"]))
    raise ValueError(f"unknown historical validation signal: {signal_id}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sma(closes: list[float | None], n: int) -> list[float | None]:
    out: list[float | None] = []
    running = 0.0
    missing = 0
    for index, value in enumerate(closes):
        if value is None:
            missing += 1
        else:
            running += value
        if index >= n:
            old = closes[index - n]
            if old is None:
                missing -= 1
            else:
                running -= old
        out.append(running / n if index >= n - 1 and missing == 0 else None)
    return out


def study_series(
    dates: list[str],
    closes: list[float | None],
    windows: tuple[int, ...] = WINDOWS,
) -> dict[str, Any]:
    """Compute one code's tri-state signal and observation windows, with no I/O."""
    if len(dates) != len(closes):
        raise ValueError("dates and closes must have equal length")
    sma_fast = _sma(closes, SMA_FAST)
    sma_slow = _sma(closes, SMA_SLOW)
    signal = [
        None if fast is None or slow is None else fast > slow
        for fast, slow in zip(sma_fast, sma_slow)
    ]
    events: list[dict[str, Any]] = []
    excluded = 0
    for index, (current, previous) in enumerate(zip(signal, [None, *signal[:-1]])):
        if current is not True:
            continue
        if previous is None:
            excluded += 1
            continue
        if previous:
            continue
        events.append({"index": index, "date": dates[index], "close": closes[index]})

    per_window: dict[str, Any] = {}
    for window in windows:
        evaluated: list[dict[str, Any]] = []
        immature = 0
        missing = 0
        for event in events:
            index = event["index"]
            if index + window >= len(closes):
                immature += 1
                continue
            exit_close = closes[index + window]
            if exit_close is None:
                missing += 1
                continue
            evaluated.append(
                {
                    **event,
                    "exit_date": dates[index + window],
                    "exit_close": exit_close,
                    "return_pct": round((exit_close / event["close"] - 1) * 100, 4),
                }
            )
        per_window[str(window)] = {
            "evaluated": evaluated,
            "immature": immature,
            "missing_exit": missing,
        }
    return {
        "sessions": len(closes),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "events": events,
        "excluded_unknown_prior_state": excluded,
        "per_window": per_window,
    }


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)

    def pct(p: float) -> float:
        position = (len(ordered) - 1) * p
        low, high = int(position), min(int(position) + 1, len(ordered) - 1)
        return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 4)

    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "p10": pct(0.10),
        "p90": pct(0.90),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _benchmark_missing_reason(start: float | None, end: float | None) -> str | None:
    if start is None and end is None:
        return "benchmark_start_and_end_missing"
    if start is None:
        return "benchmark_start_missing"
    if end is None:
        return "benchmark_end_missing"
    if start <= 0:
        return "benchmark_start_invalid"
    return None


def run_study(
    series_by_code: dict[str, tuple[list[str], list[float | None]]],
    benchmark: tuple[list[str], list[float | None]] | None,
    windows: tuple[int, ...] = WINDOWS,
) -> dict[str, Any]:
    """Run the fixed protocol; benchmark input is independent from sample input."""
    studies = {
        code: study_series(dates, closes, windows)
        for code, (dates, closes) in series_by_code.items()
    }
    benchmark_close_by_date: dict[str, float | None] | None = None
    if benchmark is not None:
        benchmark_close_by_date = dict(zip(benchmark[0], benchmark[1]))

    results: dict[str, Any] = {}
    for window in windows:
        ledger: list[dict[str, Any]] = []
        for code, study in studies.items():
            bucket = study["per_window"][str(window)]
            for event in study["events"]:
                row = {
                    "code": code,
                    "signal_date": event["date"],
                    "signal_close": event["close"],
                    "status": None,
                    "exit_date": None,
                    "exit_close": None,
                    "return_pct": None,
                    "benchmark_return_pct": None,
                    "excess_return_pct": None,
                    "benchmark_missing_reason": None,
                }
                evaluated = next(
                    (item for item in bucket["evaluated"] if item["index"] == event["index"]),
                    None,
                )
                if evaluated is None:
                    row["status"] = "IMMATURE" if event["index"] + window >= study["sessions"] else "MISSING_EXIT"
                    ledger.append(row)
                    continue
                row.update(
                    {
                        "status": "EVALUATED",
                        "exit_date": evaluated["exit_date"],
                        "exit_close": evaluated["exit_close"],
                        "return_pct": evaluated["return_pct"],
                    }
                )
                if benchmark_close_by_date is not None:
                    start = benchmark_close_by_date.get(row["signal_date"])
                    end = benchmark_close_by_date.get(row["exit_date"])
                    reason = _benchmark_missing_reason(start, end)
                    if reason:
                        row["benchmark_missing_reason"] = reason
                    else:
                        row["benchmark_return_pct"] = round((end / start - 1) * 100, 4)
                        row["excess_return_pct"] = round(row["return_pct"] - row["benchmark_return_pct"], 4)
                ledger.append(row)
            for _ in range(study["excluded_unknown_prior_state"]):
                ledger.append(
                    {
                        "code": code,
                        "signal_date": None,
                        "signal_close": None,
                        "status": "EXCLUDED_UNKNOWN_PRIOR",
                        "exit_date": None,
                        "exit_close": None,
                        "return_pct": None,
                        "benchmark_return_pct": None,
                        "excess_return_pct": None,
                        "benchmark_missing_reason": None,
                    }
                )

        evaluated_rows = [row for row in ledger if row["status"] == "EVALUATED"]
        with_benchmark = [row for row in evaluated_rows if row["excess_return_pct"] is not None]
        failures = (
            len([row for row in with_benchmark if row["excess_return_pct"] < 0])
            if with_benchmark and benchmark_close_by_date is not None
            else None
        )
        worst_observation = min(evaluated_rows, key=lambda row: row["return_pct"]) if evaluated_rows else None
        for row in ledger:
            row["is_worst"] = worst_observation is not None and row is worst_observation
            row["is_failure"] = bool(
                failures is not None and row["excess_return_pct"] is not None and row["excess_return_pct"] < 0
            )
        results[str(window)] = {
            "events_total": len(evaluated_rows) + sum(
                1 for row in ledger if row["status"] in {"IMMATURE", "MISSING_EXIT"}
            ),
            "events_evaluated": len(evaluated_rows),
            "events_immature": sum(1 for row in ledger if row["status"] == "IMMATURE"),
            "events_missing_exit": sum(1 for row in ledger if row["status"] == "MISSING_EXIT"),
            "events_excluded_unknown_prior": sum(
                1 for row in ledger if row["status"] == "EXCLUDED_UNKNOWN_PRIOR"
            ),
            "benchmark_events_missing": sum(1 for row in evaluated_rows if row["benchmark_missing_reason"]),
            "failures": failures,
            "failure_definition": "excess_return_pct < 0 vs benchmark" if benchmark_close_by_date is not None else None,
            "signal_return": _stats([row["return_pct"] for row in evaluated_rows]),
            "benchmark_return": _stats([row["benchmark_return_pct"] for row in with_benchmark]),
            "excess_return": _stats([row["excess_return_pct"] for row in with_benchmark]),
            "worst_observation": worst_observation,
            "worst_observation_basis": "return_pct",
            "worst_observation_scope": "all EVALUATED events",
            "worst_observation_eligible_count": len(evaluated_rows),
            "rows": ledger,
        }
    return {"studies_by_code": studies, "windows": results}


def _load_series_from_rdp(
    data_root: str | Path | None, codes: list[str], date_from: str | None, date_to: str | None
) -> dict[str, tuple[list[str], list[float]]]:
    """Load explicit code series through RDP pagination; never writes an artifact."""
    series: dict[str, tuple[list[str], list[float]]] = {}
    for code in codes:
        dates: list[str] = []
        closes: list[float] = []
        offset = 0
        while True:
            page = rdp.query_daily_bars(
                root=data_root,
                code=code,
                date_from=date_from,
                date_to=date_to,
                limit=rdp._MAX_LIMIT,
                offset=offset,
            )
            rows = page.get("rows") or []
            if not rows:
                break
            for row in rows:
                dates.append(row["trade_date"])
                closes.append(float(row["close"]))
            offset += len(rows)
            if page.get("next_offset") is None:
                break
        if dates:
            series[code] = (dates, closes)
    return series


def build_report(
    series_by_code: dict[str, tuple[list[str], list[float | None]]],
    benchmark: tuple[list[str], list[float | None]] | None,
    data_provenance: dict[str, Any],
    windows: tuple[int, ...] = WINDOWS,
) -> dict[str, Any]:
    study = run_study(series_by_code, benchmark, windows)
    per_code = {
        code: {
            "sessions": one["sessions"],
            "first_date": one["first_date"],
            "last_date": one["last_date"],
            "excluded_unknown_prior_state": one["excluded_unknown_prior_state"],
            "event_dates": [event["date"] for event in one["events"]],
        }
        for code, one in study["studies_by_code"].items()
    }
    definition = signal_definition()
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "normal",
        "research_only": True,
        "generated_at": _utc_now(),
        "signal": definition,
        "protocol": {
            "observation_windows_stored_observations": list(windows),
            "window_semantics": "the W-th stored observation after the signal; no trading calendar applied; per-event start/end dates are kept in the ledger",
            "observation": "close-to-close forward return pct on UNADJUSTED bars",
            "benchmark_policy": "independent comparison series aligned on BOTH the signal date and the exit date; a missing endpoint -> null with reason, never forward-filled, interpolated or zero",
            "worst_observation_policy": "minimum return_pct among all EVALUATED events; never mixed with excess returns",
            "failure_definition": "excess_return_pct < 0 vs benchmark; without a benchmark no failure judgement is made (failures=null)",
            "immature_policy": "signals within the last W stored observations are IMMATURE: counted in the ledger, never scored as success or failure",
            "missing_policy": "missing closes -> MISSING_EXIT in the ledger, never filled with 0",
        },
        "data": {
            **data_provenance,
            "actual_sample_ranges": {
                code: {
                    "date_from": one["first_date"],
                    "date_to": one["last_date"],
                    "observations": one["sessions"],
                }
                for code, one in per_code.items()
            },
            "actual_benchmark_range": {
                "date_from": benchmark[0][0],
                "date_to": benchmark[0][-1],
                "observations": len(benchmark[0]),
            }
            if benchmark and benchmark[0]
            else None,
        },
        "sample_codes": sorted(series_by_code.keys()),
        "per_code": per_code,
        "historical_validity": {"status": HISTORICAL_VALIDITY, "reasons": list(VALIDITY_REASONS)},
        "results": study["windows"],
        "limitations": list(LIMITATIONS),
        "formal_state_write": {"performed": False, "scope": "research computation only"},
    }


def evaluate_rdp(
    *,
    signal_id: str,
    codes: list[str],
    benchmark_code: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    if signal_id != SIGNAL_ID:
        raise ValueError(f"unknown historical validation signal: {signal_id}")
    manifest = rdp.read_manifest()
    sample = _load_series_from_rdp(None, codes, date_from, date_to)
    benchmark = (
        _load_series_from_rdp(None, [benchmark_code], date_from, date_to).get(benchmark_code)
        if benchmark_code
        else None
    )
    provenance = {
        "dataset_id": manifest["dataset_id"],
        "provider_id": manifest.get("provider_id"),
        "adjustment": manifest.get("adjustment"),
        "source_kind": manifest.get("source_kind"),
        "source_name": manifest.get("source_name"),
        "license_status": manifest.get("license_status"),
        "artifact_sha256": manifest.get("artifact_sha256"),
        "as_of": manifest.get("coverage_end"),
        "coverage": {
            "start": manifest.get("coverage_start"),
            "end": manifest.get("coverage_end"),
            "row_count": manifest.get("row_count"),
            "code_count": manifest.get("code_count"),
        },
        "requested_date_from": date_from,
        "requested_date_to": date_to,
        "requested_sample_codes": list(codes),
        "sample_codes_with_data": sorted(sample),
        "sample_codes_missing_data": [code for code in codes if code not in sample],
        "requested_benchmark_code": benchmark_code,
        "benchmark_available": benchmark is not None,
        "benchmark_missing_data": bool(benchmark_code and benchmark is None),
        "benchmark_in_sample_list": benchmark_code in codes if benchmark_code else False,
    }
    report = build_report(sample, benchmark, provenance)
    report["request"] = {
        "signal_id": signal_id,
        "codes": list(codes),
        "benchmark_code": benchmark_code,
        "date_from": date_from,
        "date_to": date_to,
    }
    return report


def unavailable_report(signal_id: str, request: dict[str, Any], reason: str) -> dict[str, Any]:
    definition = signal_definition(signal_id)
    data = rdp.build_unavailable_envelope(reason)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "research_only": True,
        "generated_at": _utc_now(),
        "signal": definition,
        "protocol": {"observation_windows_stored_observations": list(WINDOWS)},
        "request": request,
        "data": data,
        "sample_codes": [],
        "per_code": {},
        "historical_validity": {"status": HISTORICAL_VALIDITY, "reasons": list(VALIDITY_REASONS)},
        "results": {},
        "limitations": [reason, *LIMITATIONS],
        "formal_state_write": {"performed": False, "scope": "research computation only"},
    }


def write_outputs(report: dict[str, Any], out_prefix: str) -> list[str]:
    prefix = Path(out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    csv_path = prefix.with_suffix(".csv")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "code", "window", "signal_date", "exit_date", "status", "signal_close", "exit_close",
                "signal_return_pct", "benchmark_return_pct", "excess_return_pct",
                "benchmark_missing_reason", "is_worst", "is_failure",
            ]
        )
        for window, bucket in report["results"].items():
            for row in bucket["rows"]:
                writer.writerow(
                    [
                        row["code"], window, row["signal_date"] or "", row["exit_date"] or "", row["status"],
                        row["signal_close"] if row["signal_close"] is not None else "",
                        row["exit_close"] if row["exit_close"] is not None else "",
                        row["return_pct"] if row["return_pct"] is not None else "",
                        row["benchmark_return_pct"] if row["benchmark_return_pct"] is not None else "",
                        row["excess_return_pct"] if row["excess_return_pct"] is not None else "",
                        row["benchmark_missing_reason"] or "",
                        "yes" if row["is_worst"] else "",
                        "yes" if row["is_failure"] else "",
                    ]
                )
    return [str(json_path), str(csv_path)]
