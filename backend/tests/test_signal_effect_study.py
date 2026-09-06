"""signal_effect_study v0.1 合成数据验收 — 只锁本原型的主路径行为。

固定协议下的可复算样本：
- 600001：session 80 发生唯一一次 False→True 金叉；5d/20d 前向收益手工可算；
- 600002：对照序列（全程 200）→ 对照收益 0，超额=信号收益；
- 600003：70 会话，session 69 金叉 → 全部窗口 IMMATURE（不计成败、不删除）；
- 600004：首个可评估会话即 True（T-1 SMA60 不可评估）→ excluded unknown_prior_state。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

import research_data_plane as rdp
from research_prototypes import signal_effect_study as ses


TOTAL_SESSIONS = 130


def _dates(count: int) -> list[str]:
    base = date(2024, 1, 1)
    return [(base + timedelta(days=index)).isoformat() for index in range(count)]


def _closes_600001() -> list[float]:
    closes = [100.0] * TOTAL_SESSIONS
    closes[80] = 101.0
    closes[81] = 101.0
    closes[82] = 101.0
    closes[83] = 101.0
    closes[84] = 101.0
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
            lines.append(f"{code},{_dates(TOTAL_SESSIONS)[index]},{close},{close},{close},{close},1000")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_signal_effect_study_fixed_protocol_on_synthetic_bars(tmp_path: Path):
    csv_path = tmp_path / "bulk.csv"
    _write_dataset_csv(csv_path)
    root = tmp_path / "rdp"
    manifest = rdp.import_csv(csv_path, root=root)
    assert manifest["adjustment"] == "UNADJUSTED"

    codes = ["600001", "600002", "600003", "600004"]
    series = ses._load_series_from_rdp(str(root), codes, None, None)
    assert sorted(series.keys()) == codes

    report = ses.build_report(
        series,
        "600002",
        {"root": str(root), "dataset_id": manifest["dataset_id"], "adjustment": manifest["adjustment"]},
    )
    assert report["research_only"] is True
    assert report["historical_validity"]["status"] == "NOT_PROVEN"
    assert report["signal"]["id"] == "sma20_gt_sma60"

    window5 = report["results"]["5"]
    assert window5["events_total"] == 2  # 1 evaluated + 1 immature
    assert window5["events_evaluated"] == 1
    assert window5["events_immature"] == 1
    rows = window5["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "600001"
    assert row["date"] == _dates(TOTAL_SESSIONS)[80]
    assert row["return_pct"] == pytest.approx(3.9604, abs=1e-4)
    # 对照全程 200 → 对照收益 0，超额=信号收益；不因对照缺失填 0。
    assert row["benchmark_return_pct"] == 0.0
    assert row["excess_return_pct"] == pytest.approx(3.9604, abs=1e-4)
    assert window5["failure_case"]["code"] == "600001"

    window20 = report["results"]["20"]
    assert window20["events_evaluated"] == 1
    assert window20["rows"][0]["return_pct"] == pytest.approx(8.9109, abs=1e-4)

    # 600003：T-1 可评估且为 False 的唯一穿越落在尾部 → 两个窗口都 IMMATURE。
    assert report["per_code"]["600003"]["event_dates"] == [_dates(TOTAL_SESSIONS)[69]]
    # 600004：首个可评估会话即 True，无先验状态 → 排除而非计为事件。
    assert report["per_code"]["600004"]["excluded_unknown_prior_state"] == 1
    assert report["per_code"]["600004"]["event_dates"] == []

    # 无前视：只改变事件之后的收盘价不改变事件本身；截断序列后事件保持一致。
    truncated = {"600001": (series["600001"][0][:96], series["600001"][1][:96])}
    truncated_study = ses.build_report(truncated, None, {"root": "synthetic"})
    truncated_rows = truncated_study["results"]["5"]["rows"]
    assert len(truncated_rows) == 1
    assert truncated_rows[0]["date"] == _dates(TOTAL_SESSIONS)[80]
    assert truncated_rows[0]["return_pct"] == pytest.approx(3.9604, abs=1e-4)
    assert truncated_study["results"]["20"]["events_immature"] == 1

    outputs = ses.write_outputs(report, str(tmp_path / "out" / "study"))
    json_path, csv_path_out = Path(outputs[0]), Path(outputs[1])
    assert json_path.is_file() and csv_path_out.is_file()
    csv_text = csv_path_out.read_text(encoding="utf-8")
    assert "FAILURE_CASE" in csv_text
    assert "600003" not in csv_text  # IMMATURE 事件不进 CSV 明细行，只在 JSON 计数
