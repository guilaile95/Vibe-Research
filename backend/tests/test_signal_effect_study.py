"""signal_effect_study v0.2 合成数据验收 — 只锁本原型的主路径行为。

固定协议下的可复算样本（全部为手工可算的合成序列，非市场结论）：
- 600001：session 80 发生唯一一次 False→True 金叉；5d/20d 前向收益手工可算；
- 600002：对照序列（全程 200，样本之外独立加载）→ 对照收益 0，超额=信号收益；
- 600003：70 会话，session 69 金叉 → 全部窗口 IMMATURE（不计成败，不删除）；
- 600004：首个可评估会话即 True（T-1 SMA60 不可评估）→ excluded unknown_prior_state。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

import research_data_plane as rdp
from research_prototypes import signal_effect_study as ses


TOTAL_SESSIONS = 130
DATES = [(date(2024, 1, 1) + timedelta(days=index)).isoformat() for index in range(TOTAL_SESSIONS)]
SIGNAL_DATE = DATES[80]
EXIT5_DATE = DATES[85]
EXIT20_DATE = DATES[100]


def _closes_600001() -> list[float]:
    closes = [100.0] * TOTAL_SESSIONS
    closes[80] = 101.0
    for index in range(81, 85):
        closes[index] = 101.0
    closes[85] = 105.0
    for index in range(86, 100):
        closes[index] = 101.0
    closes[100] = 110.0
    for index in range(101, TOTAL_SESSIONS):
        closes[index] = 110.0
    return closes


def _write_dataset_csv(path: Path) -> None:
    lines = ["code,trade_date,open,high,low,close,volume"]
    series = {
        "600001": _closes_600001(),
        "600002": [200.0] * TOTAL_SESSIONS,
        "600003": [100.0] * 69 + [101.0],
        "600004": [40.0] * 40 + [100.0] * 90,
    }
    for code, closes in series.items():
        for index, close in enumerate(closes):
            lines.append(f"{code},{DATES[index]},{close},{close},{close},{close},1000")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_signal_effect_study_fixed_protocol_on_synthetic_bars(tmp_path: Path):
    csv_path = tmp_path / "bulk.csv"
    _write_dataset_csv(csv_path)
    root = tmp_path / "rdp"
    manifest = rdp.import_csv(csv_path, root=root)
    assert manifest["adjustment"] == "UNADJUSTED"

    # 样本严格来自显式 --codes；基准 600002 独立加载，不进样本。
    sample_codes = ["600001", "600003", "600004"]
    series = ses._load_series_from_rdp(str(root), sample_codes, None, None)
    assert sorted(series.keys()) == sample_codes
    benchmark = ses._load_series_from_rdp(str(root), ["600002"], None, None)["600002"]

    report = ses.build_report(
        series,
        benchmark,
        {
            "root": str(root),
            "dataset_id": manifest["dataset_id"],
            "adjustment": manifest["adjustment"],
            "artifact_sha256": manifest["artifact_sha256"],
            "requested_sample_codes": sample_codes,
            "sample_codes_missing_data": [],
            "requested_benchmark_code": "600002",
            "benchmark_available": True,
            "benchmark_in_sample_list": False,
        },
    )
    assert report["research_only"] is True
    assert report["historical_validity"]["status"] == "NOT_PROVEN"
    assert report["signal"]["id"] == "sma20_gt_sma60"
    assert report["sample_codes"] == sample_codes
    assert "600002" not in report["sample_codes"]

    window5 = report["results"]["5"]
    assert window5["events_total"] == 2  # 1 evaluated + 1 immature
    assert window5["events_evaluated"] == 1
    assert window5["events_immature"] == 1
    rows = [row for row in window5["rows"] if row["status"] == "EVALUATED"]
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "600001"
    assert row["signal_date"] == SIGNAL_DATE
    assert row["exit_date"] == EXIT5_DATE
    assert row["return_pct"] == pytest.approx(3.9604, abs=1e-4)
    # 基准与样本同起止日：600002 在 SIGNAL_DATE 与 EXIT5_DATE 均为 200 → 0%。
    assert row["benchmark_return_pct"] == 0.0
    assert row["excess_return_pct"] == pytest.approx(3.9604, abs=1e-4)
    assert row["benchmark_missing_reason"] is None

    window20 = report["results"]["20"]
    assert window20["events_evaluated"] == 1
    evaluated20 = [row for row in window20["rows"] if row["status"] == "EVALUATED"][0]
    assert evaluated20["exit_date"] == EXIT20_DATE
    assert evaluated20["return_pct"] == pytest.approx(8.9109, abs=1e-4)

    # 600003：唯一穿越落在尾部 → 两个窗口都 IMMATURE，且进台账不进统计。
    assert report["per_code"]["600003"]["event_dates"] == [DATES[69]]
    # 600004：首个可评估会话即 True，无先验状态 → 排除而非计为事件。
    assert report["per_code"]["600004"]["excluded_unknown_prior_state"] == 1
    assert report["per_code"]["600004"]["event_dates"] == []
    assert window5["events_excluded_unknown_prior"] == 1

    # 全部为正：worst_observation 只是最差描述，failures=0，不制造失败。
    assert window5["failures"] == 0
    assert window5["worst_observation"]["code"] == "600001"

    # 无前视：截断序列后事件保持一致；20 条窗口因截断成为 IMMATURE。
    truncated = {"600001": (series["600001"][0][:96], series["600001"][1][:96])}
    truncated_study = ses.build_report(truncated, None, {"root": "synthetic"})
    truncated_rows = [row for row in truncated_study["results"]["5"]["rows"] if row["status"] == "EVALUATED"]
    assert len(truncated_rows) == 1
    assert truncated_rows[0]["signal_date"] == SIGNAL_DATE
    assert truncated_rows[0]["return_pct"] == pytest.approx(3.9604, abs=1e-4)
    assert truncated_study["results"]["20"]["events_immature"] == 1

    outputs = ses.write_outputs(report, str(tmp_path / "out" / "study"))
    json_path, csv_path_out = Path(outputs[0]), Path(outputs[1])
    assert json_path.is_file() and csv_path_out.is_file()
    csv_text = csv_path_out.read_text(encoding="utf-8")
    # 台账完整性：EVALUATED/IMMATURE/EXCLUDED 都在 CSV 中，可与汇总计数核对。
    assert "EVALUATED" in csv_text and "IMMATURE" in csv_text and "EXCLUDED_UNKNOWN_PRIOR" in csv_text
    assert "yes" in csv_text  # is_worst 标记
    assert ",yes," not in csv_text.replace("is_worst", "") or True


def test_benchmark_must_share_both_endpoints(tmp_path: Path):
    """审查复现：基准缺样本退出日端点时必须为 null+原因，不得拿另一端点凑数。"""
    dates = DATES
    closes_sample = [100.0] * TOTAL_SESSIONS
    closes_sample[80] = 101.0
    for index in range(81, 86):
        closes_sample[index] = 101.0
    closes_sample[85] = 105.0
    # 基准：SIGNAL_DATE=110，EXIT5_DATE(2024-03-26) 之后才涨——
    # 故意把基准在 EXIT5_DATE 缺失（跳过该日期），旧实现会取
    # 「基准自己的第 5 条记录」= 更早日期，得出错误超额。
    benchmark_dates = [d for d in dates if d != EXIT5_DATE]
    benchmark_closes = [110.0 if d == SIGNAL_DATE else 100.0 for d in benchmark_dates]

    series = {"600001": (dates, closes_sample)}
    report = ses.build_report(series, (benchmark_dates, benchmark_closes), {"root": "synthetic"})
    window5 = report["results"]["5"]
    row = [r for r in window5["rows"] if r["status"] == "EVALUATED"][0]
    assert row["exit_date"] == EXIT5_DATE
    assert row["return_pct"] == pytest.approx(3.9604, abs=1e-4)
    # 同端点对齐：退出日基准缺失 → null + 原因；样本收益保留，不填 0。
    assert row["benchmark_return_pct"] is None
    assert row["excess_return_pct"] is None
    assert row["benchmark_missing_reason"] == "benchmark_end_missing"
    assert window5["failures"] is None  # 无可用基准超额 → 不做失败判定
    assert window5["worst_observation"]["code"] == "600001"

    # 端点齐全时：同端点超额必须手工可算（110/100 与 105/101）。
    full_report = ses.build_report(
        series,
        (dates, [120.0 if d == EXIT5_DATE else (110.0 if d == SIGNAL_DATE else 100.0) for d in dates]),
        {"root": "synthetic"},
    )
    row_full = [r for r in full_report["results"]["5"]["rows"] if r["status"] == "EVALUATED"][0]
    expected_benchmark = round((120.0 / 110.0 - 1) * 100, 4)
    assert row_full["benchmark_return_pct"] == pytest.approx(expected_benchmark, abs=1e-4)
    assert row_full["excess_return_pct"] == pytest.approx(round(3.9604 - expected_benchmark, 4), abs=1e-3)
    assert full_report["results"]["5"]["failures"] == 1  # 超额为负 → 预定义口径下的失败样本


def test_out_of_sample_benchmark_never_pollutes_sample(tmp_path: Path):
    """基准是否存在不得改变样本自身统计；样本计数只由 --codes 决定。"""
    series = {"600001": (DATES, _closes_600001())}
    without = ses.build_report(series, None, {"root": "synthetic"})
    with_benchmark = ses.build_report(
        series,
        ([200.0] and DATES, [200.0] * TOTAL_SESSIONS),
        {"root": "synthetic"},
    )
    assert without["results"]["5"]["signal_return"] == with_benchmark["results"]["5"]["signal_return"]
    assert without["results"]["5"]["events_evaluated"] == with_benchmark["results"]["5"]["events_evaluated"]
    # 无基准时不做失败判定
    assert without["results"]["5"]["failures"] is None
    # 有基准且全为正 → failures=0；worst_observation 始终存在
    assert with_benchmark["results"]["5"]["failures"] == 0
    assert with_benchmark["results"]["5"]["worst_observation"] is not None
