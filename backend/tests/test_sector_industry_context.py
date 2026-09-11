from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import astock
import sector_industry_context as context


def _snapshot() -> list[dict]:
    return [
        {"code": "000001", "name": "甲", "industry": "电子", "change_pct": 2.0, "turnover_pct": 3.0, "amount": 0.0},
        {"code": "000002", "name": "乙", "industry": "电子", "change_pct": -1.0, "turnover_pct": 0.0, "amount": 100.0},
        {"code": "000003", "name": "丙", "industry": "电子", "change_pct": 0.0, "turnover_pct": None, "amount": None},
        {"code": "000004", "name": "丁", "industry": "医药", "change_pct": 1.0, "turnover_pct": 4.0, "amount": 20.0},
        {"code": "000005", "name": "戊", "industry": "医药", "change_pct": -2.0, "turnover_pct": 5.0, "amount": 30.0},
        {"code": "000006", "name": "己", "industry": None, "change_pct": None, "turnover_pct": None, "amount": None},
    ]


def _rdp_row(code: str, return_5d: float | None, return_20d: float | None, close_vs_ma20: float | None, *, ma20_status: str = "normal") -> dict:
    return {
        "code": code,
        "return_5d": return_5d,
        "return_20d": return_20d,
        "close_vs_ma20": close_vs_ma20,
        "ma20_status": ma20_status,
        "volume_ratio_20d": 1.5 if return_5d is not None else None,
    }


def _rdp_reader(rows: list[dict]):
    def read(*, offset: int = 0, **_kwargs):
        page = rows[offset : offset + 4]
        return {
            "status": "normal",
            "as_of": "2026-09-08",
            "provenance": {"artifact_sha256": "fixture"},
            "rows": page,
            "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
        }

    return read


def test_current_industry_membership_and_rdp_join_are_explicit():
    result = context.build_sector_industry_context(
        snapshot_reader=_snapshot,
        rdp_reader=_rdp_reader([
            _rdp_row("000001", 0.10, 0.20, 0.05),
            _rdp_row("000002", 0.00, -0.10, -0.02),
            _rdp_row("000003", -0.05, None, None, ma20_status="INSUFFICIENT_HISTORY"),
            _rdp_row("000004", 0.20, 0.40, 0.10),
        ]),
    )

    assert result["status"] == "partial"
    assert result["classification_provider"] == "EASTMONEY"
    assert result["membership_semantics"] == "CURRENT_MEMBERSHIP_SNAPSHOT"
    assert result["historical_membership_validity"] == "NOT_PROVEN"
    names = [item["industry_name"] for item in result["items"]]
    assert names[-1] == "UNKNOWN"
    assert names[:2] == sorted(["电子", "医药"])

    electronics = next(item for item in result["items"] if item["industry_name"] == "电子")
    assert electronics["expected_member_count"] == electronics["current_member_count"] == 3
    assert electronics["as_of"] == electronics["snapshot_as_of"]
    assert electronics["rdp_usable_member_count"] == 3
    assert electronics["coverage_ratio"] == pytest.approx(1.0)
    assert electronics["metrics"]["member_aggregate_return_5d_pct"] == pytest.approx(5 / 3)
    assert electronics["metrics"]["member_aggregate_return_20d_pct"] == pytest.approx(5.0)
    assert electronics["metrics"]["member_aggregate_acceleration_5d_pct"] is None
    assert electronics["breadth"]["up_ratio"] == pytest.approx(1 / 3)
    assert electronics["breadth"]["down_ratio"] == pytest.approx(1 / 3)
    assert electronics["breadth"]["flat_ratio"] == pytest.approx(1 / 3)
    assert electronics["breadth"]["ma20_usable_count"] == 2
    assert electronics["breadth"]["above_ma20_ratio"] == pytest.approx(0.5)
    assert electronics["participation"]["amount_total"] == pytest.approx(100.0)

    medicine = next(item for item in result["items"] if item["industry_name"] == "医药")
    assert medicine["rdp_usable_member_count"] == 1
    assert medicine["unavailable_member_count"] == 1
    assert medicine["coverage_ratio"] == pytest.approx(0.5)
    assert medicine["status"] == "partial"
    assert "未按 0 参与聚合" in " ".join(medicine["warnings"])

    unknown = next(item for item in result["items"] if item["industry_name"] == "UNKNOWN")
    assert unknown["classification_status"] == "UNKNOWN"
    assert unknown["status"] == "unavailable"


def test_zero_values_are_not_rewritten_as_null():
    result = context.build_sector_industry_context(
        snapshot_reader=lambda: [{"code": "000001", "name": "甲", "industry": "电子", "change_pct": 0.0, "turnover_pct": 0.0, "amount": 0.0}],
        rdp_reader=_rdp_reader([_rdp_row("000001", 0.0, 0.0, 0.0)]),
    )
    row = result["items"][0]
    assert row["metrics"]["member_aggregate_return_5d_pct"] == 0.0
    assert row["metrics"]["member_aggregate_return_20d_pct"] == 0.0
    assert row["breadth"]["up_ratio"] == 0.0
    assert row["breadth"]["above_ma20_ratio"] == 0.0
    assert row["participation"]["turnover_pct_avg"] == 0.0
    assert row["participation"]["amount_total"] == 0.0


def test_empty_universe_is_distinct_from_unavailable():
    result = context.build_sector_industry_context(snapshot_reader=lambda: [], rdp_reader=_rdp_reader([]))
    assert result["status"] == "normal"
    assert result["universe_status"] == "empty"
    assert result["items"] == []
    assert "空结果不等于数据源不可用" in result["warnings"][0]


def test_rdp_failure_is_unavailable_but_keeps_current_membership_breadth():
    def broken_rdp(**_kwargs):
        raise RuntimeError("fixture failure")

    result = context.build_sector_industry_context(snapshot_reader=_snapshot, rdp_reader=broken_rdp)
    assert result["status"] == "unavailable"
    electronics = next(item for item in result["items"] if item["industry_name"] == "电子")
    assert electronics["status"] == "unavailable"
    assert electronics["rdp_usable_member_count"] == 0
    assert electronics["metrics"]["member_aggregate_return_5d_pct"] is None
    assert electronics["breadth"]["up_ratio"] == pytest.approx(1 / 3)


def test_snapshot_failure_does_not_become_empty_success():
    result = context.build_sector_industry_context(
        snapshot_reader=lambda: (_ for _ in ()).throw(RuntimeError("snapshot failure")),
        rdp_reader=_rdp_reader([]),
    )
    assert result["status"] == "unavailable"
    assert result["items"] == []
    assert "当前行业快照不可用" in result["warnings"][0]


def test_one_bad_industry_rdp_row_does_not_erase_other_industries():
    result = context.build_sector_industry_context(
        snapshot_reader=_snapshot,
        rdp_reader=_rdp_reader([
            _rdp_row("000001", 0.10, 0.20, 0.05),
            {"code": "000004", "return_5d": "bad", "return_20d": None, "close_vs_ma20": None},
        ]),
    )

    electronics = next(item for item in result["items"] if item["industry_name"] == "电子")
    medicine = next(item for item in result["items"] if item["industry_name"] == "医药")
    assert electronics["status"] == "partial"
    assert electronics["metrics"]["member_aggregate_return_5d_pct"] == pytest.approx(10.0)
    assert medicine["status"] == "partial"
    assert medicine["metrics"]["member_aggregate_return_5d_pct"] is None
    assert any("历史观测不足" in warning for warning in medicine["warnings"])


def test_api_is_read_only_and_keeps_matrix_envelope(monkeypatch, tmp_path: Path):
    payload = context.build_sector_industry_context(
        snapshot_reader=lambda: [{"code": "000001", "name": "甲", "industry": "电子", "change_pct": 0.0}],
        rdp_reader=_rdp_reader([_rdp_row("000001", 0.0, 0.0, 0.0)]),
    )
    monkeypatch.setattr(app_module.sic, "build_sector_industry_context", lambda: payload)
    app_module._DC_CACHE._data.clear()
    before = list(tmp_path.iterdir())
    response = TestClient(app_module.app).get("/api/sector-research/industry-context")
    after = list(tmp_path.iterdir())
    assert response.status_code == 200
    assert response.json() == {"data": payload}
    assert after == before


def _valuation_snapshot() -> list[dict]:
    return [
        {"code": "000001", "name": "甲", "industry": "电子", "pe_ttm": 10.0, "pb": 1.0, "market_cap": 100.0},
        {"code": "000002", "name": "乙", "industry": "电子", "pe_ttm": 20.0, "pb": 2.0, "market_cap": 200.0},
        {"code": "000003", "name": "丙", "industry": "电子", "pe_ttm": 0.0, "pb": 0.0, "market_cap": 0.0},
        {"code": "000004", "name": "丁", "industry": "电子", "pe_ttm": -5.0, "pb": -2.0, "market_cap": 50.0},
        {"code": "000005", "name": "戊", "industry": "医药", "pe_ttm": 5.0, "pb": 1.0, "market_cap": 100.0},
        {"code": "000006", "name": "己", "industry": "医药", "pe_ttm": 15.0, "pb": 3.0, "market_cap": 200.0},
        {"code": "000007", "name": "庚", "industry": "医药", "pe_ttm": None, "pb": 5.0, "market_cap": 300.0},
    ]


def _valuation_rdp() -> list[dict]:
    return [{"code": f"00000{index}", "return_5d": 0.1, "return_20d": 0.2, "close_vs_ma20": 0.05} for index in range(1, 8)]


def test_valuation_aggregates_ttm_from_raw_provider_fields_without_f9_fallback():
    raw_rows = [
        {"f12": "000001", "f14": "甲", "f13": 0, "f9": 100.0, "f115": 10.0, "f20": 100.0, "f23": 1.0, "f100": "电子"},
        {"f12": "000002", "f14": "乙", "f13": 0, "f9": 200.0, "f115": 20.0, "f20": 200.0, "f23": 2.0, "f100": "电子"},
        {"f12": "000003", "f14": "丙", "f13": 0, "f9": 50.0, "f115": 0.0, "f20": 0.0, "f23": -1.0, "f100": "电子"},
        {"f12": "000004", "f14": "丁", "f13": 0, "f9": -60.0, "f115": 5.0, "f20": 50.0, "f23": 1.0, "f100": "医药"},
        {"f12": "000005", "f14": "戊", "f13": 0, "f9": 70.0, "f115": -5.0, "f20": 60.0, "f23": 3.0, "f100": "医药"},
        {"f12": "000006", "f14": "己", "f13": 0, "f9": 80.0, "f115": None, "f20": 70.0, "f23": 0.0, "f100": None},
        {"f12": "000007", "f14": "庚", "f13": 0, "f9": 90.0, "f115": "-", "f20": 80.0, "f23": 4.0, "f100": "医药"},
    ]

    def snapshot():
        return [mapped for raw in raw_rows if (mapped := astock._map_a_share_row(raw)) is not None]

    result = context.build_sector_industry_context(
        snapshot_reader=snapshot,
        rdp_reader=_rdp_reader(_valuation_rdp()),
    )

    electronics = next(item for item in result["items"] if item["industry_name"] == "电子")
    pe = electronics["valuation"]["pe_ttm"]
    assert pe["positive_median"] == pytest.approx(15.0)
    assert pe["positive_count"] == 2
    assert pe["zero_count"] == 1
    assert pe["negative_count"] == 0
    assert electronics["valuation"]["pb"]["positive_median"] == pytest.approx(1.5)
    assert electronics["valuation"]["market_cap"]["positive_total"] == pytest.approx(300.0)

    medicine = next(item for item in result["items"] if item["industry_name"] == "医药")
    assert medicine["valuation"]["pe_ttm"]["status"] == "PARTIAL"
    assert medicine["valuation"]["pe_ttm"]["positive_median"] == pytest.approx(5.0)
    assert medicine["valuation"]["pe_ttm"]["negative_count"] == 1
    assert medicine["valuation"]["pe_ttm"]["missing_count"] == 1


def test_current_member_valuation_distributions_preserve_signs_medians_and_market_cap_coverage():
    result = context.build_sector_industry_context(
        snapshot_reader=_valuation_snapshot,
        rdp_reader=_rdp_reader(_valuation_rdp()),
    )

    assert result["schema_version"] == "sector_industry_context.v0.2"
    assert result["valuation_status"] == "CURRENT_MEMBER_VALUATION_DISTRIBUTION_ONLY"
    electronics = next(item for item in result["items"] if item["industry_name"] == "电子")
    pe = electronics["valuation"]["pe_ttm"]
    assert pe["status"] == "NORMAL"
    assert pe["observed_count"] == 4
    assert pe["missing_count"] == 0
    assert pe["positive_count"] == 2
    assert pe["zero_count"] == 1
    assert pe["negative_count"] == 1
    assert pe["positive_median"] == pytest.approx(15.0)
    assert pe["observed_coverage_ratio"] == pytest.approx(1.0)
    assert pe["positive_coverage_ratio"] == pytest.approx(0.5)
    assert pe["positive_market_cap_coverage_ratio"] == pytest.approx(300 / 350)
    assert electronics["valuation"]["pb"]["positive_median"] == pytest.approx(1.5)
    assert electronics["valuation"]["market_cap"]["observed_count"] == 3
    assert electronics["valuation"]["market_cap"]["missing_count"] == 1
    assert electronics["valuation"]["market_cap"]["positive_total"] == pytest.approx(350.0)

    medicine = next(item for item in result["items"] if item["industry_name"] == "医药")
    assert medicine["valuation"]["pe_ttm"]["status"] == "PARTIAL"
    assert medicine["valuation"]["pe_ttm"]["positive_median"] == pytest.approx(10.0)
    assert medicine["valuation"]["pe_ttm"]["missing_count"] == 1
    assert medicine["valuation"]["pb"]["positive_median"] == pytest.approx(3.0)


def test_valuation_no_positive_values_is_not_missing_and_has_no_median():
    result = context.build_sector_industry_context(
        snapshot_reader=lambda: [
            {"code": "000001", "name": "甲", "industry": "电子", "pe_ttm": 0.0, "pb": -1.0, "market_cap": 100.0},
            {"code": "000002", "name": "乙", "industry": "电子", "pe_ttm": -2.0, "pb": 0.0, "market_cap": 200.0},
            {"code": "000003", "name": "丙", "industry": "电子", "pe_ttm": None, "pb": None, "market_cap": None},
        ],
        rdp_reader=_rdp_reader([_rdp_row("000001", 0.1, 0.1, 0.1), _rdp_row("000002", 0.1, 0.1, 0.1), _rdp_row("000003", 0.1, 0.1, 0.1)]),
    )
    valuation = result["items"][0]["valuation"]
    assert valuation["pe_ttm"]["status"] == "PARTIAL"
    assert valuation["pe_ttm"]["positive_median"] is None
    assert valuation["pe_ttm"]["median_status"] == "NO_POSITIVE_VALUES"
    assert valuation["pe_ttm"]["zero_count"] == 1
    assert valuation["pe_ttm"]["negative_count"] == 1
    assert valuation["pb"]["positive_median"] is None
    assert valuation["pb"]["median_status"] == "NO_POSITIVE_VALUES"


def test_duplicate_security_uses_one_current_snapshot_row_and_snapshot_is_read_once(monkeypatch):
    calls = 0

    def snapshot():
        nonlocal calls
        calls += 1
        return [
            {"code": "000001", "name": "首条", "industry": "电子", "pe_ttm": 10.0, "pb": 1.0, "market_cap": 100.0},
            {"code": "000001", "name": "重复", "industry": "医药", "pe_ttm": 99.0, "pb": 9.0, "market_cap": 999.0},
        ]

    monkeypatch.setattr(context.astock, "a_share_snapshot", snapshot)
    result = context.build_sector_industry_context(rdp_reader=_rdp_reader([_rdp_row("000001", 0.1, 0.1, 0.1)]))
    assert calls == 1
    assert result["universe"]["current_member_count"] == 1
    assert [item["industry_name"] for item in result["items"]] == ["电子"]
    assert result["items"][0]["valuation"]["pe_ttm"]["positive_median"] == pytest.approx(10.0)


def test_rdp_and_valuation_failures_are_isolated():
    complete = lambda: [{"code": "000001", "name": "甲", "industry": "电子", "pe_ttm": 10.0, "pb": 1.0, "market_cap": 100.0}]
    rdp_failure = context.build_sector_industry_context(snapshot_reader=complete, rdp_reader=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture")))
    assert rdp_failure["status"] == "unavailable"
    assert rdp_failure["items"][0]["valuation"]["pe_ttm"]["status"] == "NORMAL"
    assert rdp_failure["items"][0]["valuation"]["pe_ttm"]["positive_median"] == pytest.approx(10.0)

    valuation_failure = context.build_sector_industry_context(
        snapshot_reader=lambda: [{"code": "000001", "name": "甲", "industry": "电子", "pe_ttm": None, "pb": None, "market_cap": 100.0}],
        rdp_reader=_rdp_reader([_rdp_row("000001", 0.1, 0.1, 0.1)]),
    )
    assert valuation_failure["items"][0]["status"] == "normal"
    assert valuation_failure["items"][0]["valuation"]["pe_ttm"]["status"] == "UNAVAILABLE"
    assert valuation_failure["items"][0]["metrics"]["member_aggregate_return_5d_pct"] == pytest.approx(10.0)
