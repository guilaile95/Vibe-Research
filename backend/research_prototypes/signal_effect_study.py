"""单一信号有效性验证原型 v0.3 — RESEARCH ONLY，不进入正式决定/风险/推荐。

回答的问题：「某个固定定义的研究信号，历史上之后发生了什么？」
本脚本只做观察统计，不证明策略盈利，不产出交易建议。

在计算任何数字之前固定的协议（改任何一项都构成新实验，不得在结果上迭代）：

SIGNAL
  id        = sma20_gt_sma60（沿用既有 screener 条件词表，screener_service.evaluate_condition）
  version   = signal_effect_study.v0.2 @ stable 7485848
  definition= 会话 T 的 SMA20 与 SMA60 均可计算，且 SMA20 > SMA60
  sma_n(T)  = 最近 n 个收盘价的算术平均（含 T）；不足 n 个会话 → None（不可评估）
  availability = 信号在 T 收盘后即可计算；只用 ≤T 的数据 → 无前视
  crossing  = 事件仅取 False→True 穿越（三态：T-1 必须可评估且为 False）；
              连续 True 不重复计事件；T-1 不可评估 → excluded（unknown_prior_state）。

OBSERVATION（窗口口径 v0.2 明确）
  窗口 = 信号日后第 W 条已存储观测（W ∈ {5, 20} 条记录），**未应用交易日历**，
  因此称「观察条数窗口」而非「交易日窗口」；每个事件的实际起止日期逐条保留。
  forward_return(T, W) = close[T+W] / close[T] − 1（收盘对收盘，UNADJUSTED）。
  样本收益与基准收益使用**同一起始日与同一结束日**：基准缺失任一端点 →
  该事件无基准/超额值（null + 原因），不前向填充、不插值、不当零收益。

BENCHMARK
  基准是独立加载的对照序列（--benchmark-code），不因读取而加入样本；
  用户把同一 code 同时列为研究样本时保留该显式选择（样本计数不剔除）。
  样本严格来自显式 --codes；请求范围与实际可用范围在输出中完整记录。

EVENT LEDGER
  每个已检测事件在每个窗口下必有状态：EVALUATED / IMMATURE（距序列末尾
  不足 W，单独计数，不计成败，不删除）/ MISSING_EXIT（exit close 缺失）；
  另有 code 级 EXCLUDED_UNKNOWN_PRIOR。CSV 导出全部事件，汇总计数可与
  逐事件明细核对；不存在「只报告保留样本」的输出。

WORST / FAILURE
  worst_observation = 全部可评估事件中绝对收益 return_pct 最低者（不混用超额），
  只是描述性标注。FAILURE 预先定义：有基准时 excess_return_pct < 0；
  无基准时不做失败判定（failures=null）。全部为正 → failures=0，不制造失败。

HISTORICAL_VALIDITY = NOT_PROVEN（不可确认以下条件时不得改写本标记）
  - RDP dataset 为 LOCAL_BULK_DUMP / UNADJUSTED：除权日会产生假跳空收益；
  - 无历史时点成分股，样本由显式 --codes 指定，不能推广为全市场；
  - close-to-close 观察收益 ≠ 可实现交易收益（无成交/涨跌停/滑点/费用模拟）；
  - 本脚本输出只描述所选样本，不构成投资效果证明。

用法（读取既有 Research Data Plane，零新数据平台）：
  python -m research_prototypes.signal_effect_study \
    --data-root <RDP root> --codes 600519,000001 --benchmark-code 000300 \
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

SCHEMA_VERSION = "signal_effect_study.v0.3"
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


def run_study(
    series_by_code: dict[str, tuple[list[str], list[float]]],
    benchmark: tuple[list[str], list[float]] | None,
    windows: tuple[int, ...] = WINDOWS,
) -> dict[str, Any]:
    """对显式样本执行固定协议；基准是独立输入，绝不并入样本。"""
    studies = {
        code: study_series(dates, closes, windows)
        for code, (dates, closes) in series_by_code.items()
    }
    # 基准按「日期 → 收盘」索引；对齐在事件两侧端点上完成。
    benchmark_close_by_date: dict[str, float] | None = None
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
                    # IMMATURE 或 MISSING_EXIT：以序列长度与收盘可得性区分。
                    if event["index"] + window >= study["sessions"]:
                        row["status"] = "IMMATURE"
                    else:
                        row["status"] = "MISSING_EXIT"
                    ledger.append(row)
                    continue
                row.update({
                    "status": "EVALUATED",
                    "exit_date": evaluated["exit_date"],
                    "exit_close": evaluated["exit_close"],
                    "return_pct": evaluated["return_pct"],
                })
                if benchmark_close_by_date is not None:
                    start = benchmark_close_by_date.get(row["signal_date"])
                    end = benchmark_close_by_date.get(row["exit_date"])
                    if start is None or end is None or start <= 0:
                        # 端点缺失：null + 原因；不前向填充、不插值、不当零收益。
                        row["benchmark_missing_reason"] = (
                            "benchmark_start_missing" if start is None
                            else "benchmark_end_missing"
                        )
                    else:
                        row["benchmark_return_pct"] = round((end / start - 1) * 100, 4)
                        row["excess_return_pct"] = round(
                            row["return_pct"] - row["benchmark_return_pct"], 4
                        )
                ledger.append(row)
            # code 级排除（穿越语义要求 T-1 可评估）也进入台账，可逐条追溯。
            for _ in range(study["excluded_unknown_prior_state"]):
                ledger.append({
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
                })

        evaluated_rows = [row for row in ledger if row["status"] == "EVALUATED"]
        signal_stats = _stats([row["return_pct"] for row in evaluated_rows])
        with_benchmark = [
            row for row in evaluated_rows if row["excess_return_pct"] is not None
        ]
        excess_stats = _stats([row["excess_return_pct"] for row in with_benchmark])
        benchmark_stats = _stats([row["benchmark_return_pct"] for row in with_benchmark])
        # FAILURE 预定义：有基准时超额 < 0；无基准或无可计算超额时不做失败判定。
        failures = (
            len([row for row in with_benchmark if row["excess_return_pct"] < 0])
            if with_benchmark
            else None
        ) if benchmark_close_by_date is not None else None
        worst_observation = None
        if evaluated_rows:
            worst_observation = min(
                evaluated_rows,
                key=lambda row: row["return_pct"],
            )
        for row in ledger:
            row["is_worst"] = worst_observation is not None and row is worst_observation
            row["is_failure"] = bool(
                failures is not None
                and row["excess_return_pct"] is not None
                and row["excess_return_pct"] < 0
            )
        results[str(window)] = {
            "events_total": len(evaluated_rows)
            + sum(1 for row in ledger if row["status"] in {"IMMATURE", "MISSING_EXIT"}),
            "events_evaluated": len(evaluated_rows),
            "events_immature": sum(1 for row in ledger if row["status"] == "IMMATURE"),
            "events_missing_exit": sum(1 for row in ledger if row["status"] == "MISSING_EXIT"),
            "events_excluded_unknown_prior": sum(
                1 for row in ledger if row["status"] == "EXCLUDED_UNKNOWN_PRIOR"
            ),
            "benchmark_events_missing": sum(
                1 for row in evaluated_rows if row["benchmark_missing_reason"]
            ),
            "failures": failures,
            "failure_definition": (
                "excess_return_pct < 0 vs benchmark" if benchmark_close_by_date is not None
                else None
            ),
            "signal_return": signal_stats,
            "benchmark_return": benchmark_stats,
            "excess_return": excess_stats,
            "worst_observation": worst_observation,
            "worst_observation_basis": "return_pct",
            "worst_observation_scope": "all EVALUATED events",
            "worst_observation_eligible_count": len(evaluated_rows),
            "rows": ledger,
        }
    return {"studies_by_code": studies, "windows": results}


def _load_series_from_rdp(
    data_root: str, codes: list[str], date_from: str | None, date_to: str | None
) -> dict[str, tuple[list[str], list[float]]]:
    """按 code 逐个分页读取；同一次运行内 manifest 不变 → 单一 artifact。"""
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
    series_by_code: dict[str, tuple[list[str], list[float]]],
    benchmark: tuple[list[str], list[float]] | None,
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
    return {
        "schema_version": SCHEMA_VERSION,
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signal": {
            "id": SIGNAL_ID,
            "version": SIGNAL_VERSION,
            "definition": f"SMA{SMA_FAST} > SMA{SMA_SLOW} at close of session T (arithmetic mean of last n closes)",
            "availability": "computable after close of T; uses data <= T only",
            "crossing_rule": "False->True only on a tri-state series; T-1 must be evaluable and False",
        },
        "protocol": {
            "observation_windows_bars": list(windows),
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
                code: {"date_from": one["first_date"], "date_to": one["last_date"],
                       "observations": one["sessions"]}
                for code, one in per_code.items()
            },
            "actual_benchmark_range": {
                "date_from": benchmark[0][0], "date_to": benchmark[0][-1],
                "observations": len(benchmark[0]),
            } if benchmark and benchmark[0] else None,
        },
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
        writer.writerow([
            "code", "window", "signal_date", "exit_date", "status",
            "signal_close", "exit_close", "signal_return_pct",
            "benchmark_return_pct", "excess_return_pct",
            "benchmark_missing_reason", "is_worst", "is_failure",
        ])
        for window, bucket in report["results"].items():
            for row in bucket["rows"]:
                writer.writerow([
                    row["code"], window,
                    row["signal_date"] or "", row["exit_date"] or "",
                    row["status"], row["signal_close"] or "", row["exit_close"] or "",
                    row["return_pct"] if row["return_pct"] is not None else "",
                    row["benchmark_return_pct"] if row["benchmark_return_pct"] is not None else "",
                    row["excess_return_pct"] if row["excess_return_pct"] is not None else "",
                    row["benchmark_missing_reason"] or "",
                    "yes" if row["is_worst"] else "",
                    "yes" if row["is_failure"] else "",
                ])
    return [str(json_path), str(csv_path)]


def main() -> int:
    parser = argparse.ArgumentParser(description="sma20_gt_sma60 signal effect study (RESEARCH ONLY)")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--codes", required=True, help="comma separated 6-digit codes; the sample is exactly this list")
    parser.add_argument("--benchmark-code", default=None, help="independent comparison code; never added to the sample")
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--out-prefix", required=True)
    args = parser.parse_args()
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    if args.benchmark_code and args.benchmark_code not in codes:
        benchmark_series = _load_series_from_rdp(
            args.data_root, [args.benchmark_code], args.date_from, args.date_to
        ).get(args.benchmark_code)
    else:
        # 用户显式把基准 code 同时列入样本：保留该选择，基准独立按日期对齐。
        benchmark_series = None
        if args.benchmark_code:
            benchmark_series = _load_series_from_rdp(
                args.data_root, [args.benchmark_code], args.date_from, args.date_to
            ).get(args.benchmark_code)
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
        "requested_date_from": args.date_from,
        "requested_date_to": args.date_to,
        "requested_sample_codes": codes,
        "sample_codes_with_data": sorted(series.keys()),
        "sample_codes_missing_data": [code for code in codes if code not in series],
        "requested_benchmark_code": args.benchmark_code,
        "benchmark_available": benchmark_series is not None,
        "benchmark_in_sample_list": args.benchmark_code in codes if args.benchmark_code else False,
    }
    report = build_report(series, benchmark_series, provenance)
    outputs = write_outputs(report, args.out_prefix)
    print(json.dumps({"outputs": outputs, "historical_validity": HISTORICAL_VALIDITY}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
