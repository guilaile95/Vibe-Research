"""单一信号有效性验证原型 v0.1 — RESEARCH ONLY，不进入正式决定/风险/推荐。

回答的问题：「某个固定定义的研究信号，历史上之后发生了什么？」
本脚本只做观察统计，不证明策略盈利，不产出交易建议。

在计算任何数字之前固定的协议（改任何一项都构成新实验，不得在结果上迭代）：

SIGNAL
  id        = sma20_gt_sma60（沿用既有 screener 条件词表，screener_service.evaluate_condition）
  version   = signal_effect_study.v0.1 @ stable 7485848
  definition= 会话 T 的 SMA20 与 SMA60 均可计算，且 SMA20 > SMA60
  sma_n(T)  = 最近 n 个收盘价的算术平均（含 T）；不足 n 个会话 → None（不可评估）
  availability = 信号在 T 收盘后即可计算；只用 ≤T 的数据 → 无前视
  crossing  = 事件仅取 False→True 穿越；T-1 必须可评估且为 False，
              否则（如 SMA 尚不可评估）跳过并计入 excluded.reason="unknown_prior_state"。
              连续 True 不重复计事件。

OBSERVATION
  forward_return(T, W) = close[T+W] / close[T] − 1（收盘对收盘，UNADJUSTED）
  windows              = (5, 20) 个交易日，固定，不做窗口搜索
  benchmark            = 同 dataset 内显式指定的对照 code，同一窗口、同一日期对齐；
                         对照缺该日期 → 该事件无对照值（不填 0，不做插值）
  immature             = T 距序列末尾不足 W → IMMATURE：单独计数，不计成败，不删除
  missing              = close[T] 或 close[T+W] 缺失 → excluded 并给原因，绝不填 0

HISTORICAL_VALIDITY = NOT_PROVEN（不可确认以下条件时不得改写本标记）
  - RDP dataset 为 LOCAL_BULK_DUMP / UNADJUSTED：除权日会产生假跳空收益；
  - 无历史时点成分股，样本由显式 --codes 指定，不能推广为全市场；
  - close-to-close 观察收益 ≠ 可实现交易收益（未模拟成交、涨跌停、滑点、费用）；
  - 本脚本输出只描述所选样本，不构成投资效果证明。

用法（读取既有 Research Data Plane，零新数据平台）：
  python -m research_prototypes.signal_effect_study \
    --data-root <RDP root> --codes 600519,000001 --benchmark-code 000001 \
    --date-from 2024-01-01 --date-to 2025-12-31 --out-prefix out/sma60_study
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import research_data_plane as rdp

SCHEMA_VERSION = "signal_effect_study.v0.1"
SIGNAL_ID = "sma20_gt_sma60"
SIGNAL_VERSION = "signal_effect_study.v0.1@7485848"
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
)


def _sma(closes: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    running = 0.0
    for index, value in enumerate(closes):
        running += value
        if index >= n:
            running -= closes[index - n]
        out.append(running / n if index >= n - 1 else None)
    return out


def study_series(
    dates: list[str],
    closes: list[float],
    windows: tuple[int, ...] = WINDOWS,
) -> dict[str, Any]:
    """对一个证券序列做信号会话标记与逐窗口观察（纯计算，无 I/O）。"""
    sma_fast = _sma(closes, SMA_FAST)
    sma_slow = _sma(closes, SMA_SLOW)
    # 三态：True / False / None（任一 SMA 不可评估 → None，不折叠成 False）
    signal = [
        None if (fast is None or slow is None) else (fast > slow)
        for fast, slow in zip(sma_fast, sma_slow)
    ]
    events: list[dict[str, Any]] = []
    excluded = 0
    for index, (current, previous) in enumerate(zip(signal, [None, *signal[:-1]])):
        if current is not True:
            continue
        if previous is None:
            excluded += 1  # T-1 不可评估（SMA 未就绪），无先验状态 → 不构成穿越
            continue
        if previous:
            continue  # 连续 True，非穿越
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
            evaluated.append({
                **event,
                "exit_date": dates[index + window],
                "exit_close": exit_close,
                "return_pct": round((exit_close / closes[index] - 1) * 100, 4),
            })
        per_window[str(window)] = {"evaluated": evaluated, "immature": immature, "missing": missing}
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


def _benchmark_return_by_date(
    benchmark_dates: list[str], benchmark_closes: list[float], window: int
) -> dict[str, float]:
    out: dict[str, float] = {}
    for index, date in enumerate(benchmark_dates):
        if index + window >= len(benchmark_closes):
            continue
        out[date] = round((benchmark_closes[index + window] / benchmark_closes[index] - 1) * 100, 4)
    return out


def run_study(
    series_by_code: dict[str, tuple[list[str], list[float]]],
    benchmark_code: str | None,
    windows: tuple[int, ...] = WINDOWS,
) -> dict[str, Any]:
    """对显式样本执行固定协议；输入来自调用方（RDP 查询或测试注入）。"""
    studies = {
        code: study_series(dates, closes, windows)
        for code, (dates, closes) in series_by_code.items()
    }
    benchmark_study = studies.get(benchmark_code) if benchmark_code else None
    benchmark_series = series_by_code.get(benchmark_code) if benchmark_code else None

    results: dict[str, Any] = {}
    for window in windows:
        rows: list[dict[str, Any]] = []
        immature = 0
        missing = 0
        for code, study in studies.items():
            bucket = study["per_window"][str(window)]
            immature += bucket["immature"]
            missing += bucket["missing"]
            for item in bucket["evaluated"]:
                rows.append({"code": code, **item})
        benchmark_by_signal_date: dict[str, float] | None = None
        if benchmark_study is not None and benchmark_series is not None:
            benchmark_by_signal_date = _benchmark_return_by_date(
                benchmark_series[0], benchmark_series[1], window,
            )
        for row in rows:
            if benchmark_by_signal_date is not None and row["date"] in benchmark_by_signal_date:
                row["benchmark_return_pct"] = benchmark_by_signal_date[row["date"]]
                row["excess_return_pct"] = round(row["return_pct"] - row["benchmark_return_pct"], 4)
            else:
                row["benchmark_return_pct"] = None
                row["excess_return_pct"] = None
        signal_stats = _stats([row["return_pct"] for row in rows])
        excess_stats = _stats([
            row["excess_return_pct"] for row in rows if row["excess_return_pct"] is not None
        ])
        benchmark_stats = _stats([
            row["benchmark_return_pct"] for row in rows if row["benchmark_return_pct"] is not None
        ])
        failure_case = None
        if rows:
            with_excess = [row for row in rows if row["excess_return_pct"] is not None]
            worst = min(
                with_excess or rows,
                key=lambda row: row["excess_return_pct"] if row["excess_return_pct"] is not None else row["return_pct"],
            )
            failure_case = worst
        results[str(window)] = {
            "events_total": len(rows) + immature + missing,
            "events_evaluated": len(rows),
            "events_immature": immature,
            "events_missing_exit": missing,
            "signal_return": signal_stats,
            "benchmark_return": benchmark_stats,
            "excess_return": excess_stats,
            "failure_case": failure_case,
            "rows": rows,
        }
    return {"studies_by_code": studies, "windows": results}


def _load_series_from_rdp(
    data_root: str, codes: list[str], date_from: str | None, date_to: str | None
) -> dict[str, tuple[list[str], list[float]]]:
    series: dict[str, tuple[list[str], list[float]]] = {}
    for code in codes:
        dates: list[str] = []
        closes: list[float] = []
        offset = 0
        while True:
            page = rdp.query_daily_bars(
                root=data_root, code=code, date_from=date_from, date_to=date_to,
                limit=1000, offset=offset,
            )
            rows = page.get("rows") or page.get("items") or []
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
    series_by_code: dict[str, tuple[list[str], list[float]]],
    benchmark_code: str | None,
    data_provenance: dict[str, Any],
    windows: tuple[int, ...] = WINDOWS,
) -> dict[str, Any]:
    study = run_study(series_by_code, benchmark_code, windows)
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
    return {
        "schema_version": SCHEMA_VERSION,
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signal": {
            "id": SIGNAL_ID,
            "version": SIGNAL_VERSION,
            "definition": f"SMA{SMA_FAST} > SMA{SMA_SLOW} at close of session T (arithmetic mean of last n closes)",
            "availability": "computable after close of T; uses data <= T only",
            "crossing_rule": "False->True only; T-1 must be evaluable and False",
        },
        "protocol": {
            "windows_trading_days": list(windows),
            "observation": "close-to-close forward return pct on UNADJUSTED bars",
            "benchmark_policy": "explicit benchmark code in the same dataset, aligned by signal date; missing alignment -> null, never 0",
            "immature_policy": "signals within the last W sessions are IMMATURE: counted, never scored as success or failure",
            "missing_policy": "missing closes -> excluded with reason, never filled with 0",
        },
        "data": data_provenance,
        "sample_codes": sorted(series_by_code.keys()),
        "per_code": per_code,
        "historical_validity": {"status": HISTORICAL_VALIDITY, "reasons": list(VALIDITY_REASONS)},
        "results": study["windows"],
        "limitations": list(LIMITATIONS),
    }


def write_outputs(report: dict[str, Any], out_prefix: str) -> list[str]:
    prefix = Path(out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    csv_path = prefix.with_suffix(".csv")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "window", "signal_date", "exit_date", "signal_close", "exit_close", "signal_return_pct", "benchmark_return_pct", "excess_return_pct", "status"])
        for window, bucket in report["results"].items():
            failure = bucket.get("failure_case") or {}
            for row in bucket.get("rows", []):
                is_failure = (
                    failure
                    and row["code"] == failure.get("code")
                    and row["date"] == failure.get("date")
                )
                writer.writerow([
                    row["code"], window, row["date"], row.get("exit_date"),
                    row.get("close"), row.get("exit_close"), row["return_pct"],
                    row.get("benchmark_return_pct"), row.get("excess_return_pct"),
                    "FAILURE_CASE" if is_failure else "EVALUATED",
                ])
    return [str(json_path), str(csv_path)]


def main() -> int:
    parser = argparse.ArgumentParser(description="sma20_gt_sma60 signal effect study (RESEARCH ONLY)")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--codes", required=True, help="comma separated 6-digit codes; the sample is exactly this list")
    parser.add_argument("--benchmark-code", default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--out-prefix", required=True)
    args = parser.parse_args()
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    series = _load_series_from_rdp(args.data_root, codes, args.date_from, args.date_to)
    manifest = rdp.read_manifest(args.data_root)
    provenance = {
        "root": str(args.data_root),
        "dataset_id": manifest.get("dataset_id"),
        "adjustment": manifest.get("adjustment"),
        "license_status": manifest.get("license_status"),
        "coverage_start": manifest.get("coverage_start"),
        "coverage_end": manifest.get("coverage_end"),
        "artifact_sha256": manifest.get("artifact_sha256"),
        "requested_codes": codes,
        "codes_with_data": sorted(series.keys()),
        "excluded_codes_no_data": [code for code in codes if code not in series],
    }
    report = build_report(series, args.benchmark_code, provenance)
    outputs = write_outputs(report, args.out_prefix)
    print(json.dumps({"outputs": outputs, "historical_validity": HISTORICAL_VALIDITY}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
