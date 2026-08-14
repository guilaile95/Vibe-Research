"""P0-DS1-R1 — production wrapper path tests（transport boundary 替换）。

执行 assembler 的**真实 production wrapper**（_production_*_evaluator），
仅替换 transport boundary（astock / market 的 provider 函数），验证完整
生产链路全部连通：

    real wrapper → provider parse → temporal semantics
    → capability result → Data Health observation event

CI 零网络（monkeypatch 替换 provider 函数本身）。isolated event store，
不写真实用户数据。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import astock
import data_health_adapters as health_adapters
import decision_inbox_runtime_assembler as runtime
import market as market_module

SECURITY = "600519"
CAMPAIGN = "campaign_" + "a" * 32


def _as_of_past() -> str:
    """取一个稍早于 now 的 as_of，模拟生产 snapshot 先冻结的顺序。"""
    now = datetime.now(timezone.utc)
    return (now.replace(microsecond=0)).isoformat().replace("+00:00", "Z")


def _definition(as_of: str) -> dict:
    return {
        "security_code": SECURITY,
        "strategy": "SWING",
        "campaign_id": CAMPAIGN,
        "as_of": as_of,
    }


@pytest.fixture(autouse=True)
def _isolate_health(tmp_path, monkeypatch):
    isolated = tmp_path / "health"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "review.db"))
    health_adapters.reset_adapters_for_tests()
    yield


def _health_record(source_id: str):
    for record in health_adapters.collect_all_records():
        if record["source_id"] == source_id:
            return record
    raise AssertionError(f"{source_id} 不在 health records")


# ---------------------------------------------------------------------------
# disclosures production wrapper（acceptance A / E）
# ---------------------------------------------------------------------------

def test_production_disclosures_wrapper_full_chain(monkeypatch):
    as_of = _as_of_past()

    # transport boundary 替换：provider 函数返回真实形状公告
    monkeypatch.setattr(
        astock,
        "announcements",
        lambda code, limit=15: [
            {"date": "2026-08-12", "title": "公告一", "type": "定期报告", "url": "u"},
            {"date": "2026-08-10", "title": "公告二", "type": "权益分派", "url": "u"},
        ],
    )

    result = runtime._production_disclosures_evaluator(None, _definition(as_of))
    # 生产顺序：as_of 冻结 → reader 执行（fetched_at = now > as_of）→
    # 正常网络耗时不天然 NOT_EVALUATED（acceptance A）
    assert result["state"] == "USABLE"
    assert result["as_of"] == as_of
    refs = result["authority_refs"]
    assert "disclosures:count=2" in refs
    assert "disclosures:latest_notice_date=2026-08-12" in refs

    # acceptance E：DI 成功读取后 announcements 不再 SOURCE_NOT_INITIALIZED
    record = _health_record("announcements")
    assert record["last_error_code"] != "SOURCE_NOT_INITIALIZED"


def test_production_disclosures_wrapper_failure_updates_health(monkeypatch):
    as_of = _as_of_past()

    def broken(_code, limit=15):
        raise RuntimeError("network down")

    monkeypatch.setattr(astock, "announcements", broken)
    result = runtime._production_disclosures_evaluator(None, _definition(as_of))
    assert result["state"] == "ERROR"
    record = _health_record("announcements")
    assert record["last_error_code"] != "SOURCE_NOT_INITIALIZED"


# ---------------------------------------------------------------------------
# financials production wrapper（acceptance F）
# ---------------------------------------------------------------------------

def test_production_financials_wrapper_full_chain(monkeypatch):
    as_of = _as_of_past()
    monkeypatch.setattr(
        astock,
        "financials",
        lambda code: {"period": "2025-12-31", "revenue": 1.0, "net_profit": 2.0},
    )

    result = runtime._production_financials_evaluator(None, _definition(as_of))
    # capability 因 report-period applicability 仍 NOT_EVALUATED
    assert result["state"] == "NOT_EVALUATED"
    assert any(
        ref.startswith("financials:blocker=") for ref in result["authority_refs"]
    )
    # acceptance F：业务读取成功 → financials 不再 SOURCE_NOT_INITIALIZED
    record = _health_record("financials")
    assert record["last_error_code"] != "SOURCE_NOT_INITIALIZED"


def test_production_financials_wrapper_failure_updates_health(monkeypatch):
    as_of = _as_of_past()

    def broken(_code):
        raise RuntimeError("network down")

    monkeypatch.setattr(astock, "financials", broken)
    result = runtime._production_financials_evaluator(None, _definition(as_of))
    assert result["state"] == "ERROR"
    record = _health_record("financials")
    assert record["last_error_code"] != "SOURCE_NOT_INITIALIZED"


# ---------------------------------------------------------------------------
# market_sector production wrapper（transport 替换：breadth + individual_info）
# ---------------------------------------------------------------------------

def _breadth_fake(trade_date: str):
    return {
        "status": "normal",
        "source": "eastmoney_push2",
        "trade_date": trade_date,
        "data_time": "15:00:00",
        "fetched_at": "2026-08-13 15:05:00",
        "is_stale": False,
        "warnings": [],
        "data": {
            "stock_count": 5400,
            "up_count": 2900,
            "down_count": 2400,
            "up_ratio": 53.7,
        },
    }


def test_production_market_sector_wrapper_full_chain(monkeypatch):
    from trade_calendar import completed_trade_date_at

    as_of = _as_of_past()
    trade_date = completed_trade_date_at(as_of)
    assert trade_date is not None
    monkeypatch.setattr(
        market_module,
        "get_market_breadth",
        lambda: _breadth_fake(trade_date),
    )
    monkeypatch.setattr(
        astock,
        "individual_info",
        lambda code: {"行业": "白酒", "总股本": 1.26e9},
    )
    monkeypatch.setattr(
        market_module,
        "get_overview",
        lambda: {
            "sentiment": {},
            "sectors": [
                {"name": "白酒", "pct": 1.23, "net": 4.5e8,
                 "inflow": 1.0e9, "outflow": 5.5e8, "firms": 40},
            ],
            "updated": f"{trade_date} 15:05",
        },
    )

    result = runtime._production_market_sector_evaluator(None, _definition(as_of))
    assert result["state"] == "USABLE"
    assert "market-sector:security-industry=白酒" in result["authority_refs"]
    # acceptance F：market/sector 真实 wrapper 成功后
    # sector_research 不再 SOURCE_NOT_INITIALIZED
    record = _health_record("sector_research")
    assert record["last_error_code"] != "SOURCE_NOT_INITIALIZED"


def test_production_market_sector_market_only_is_not_usable(monkeypatch):
    from trade_calendar import completed_trade_date_at

    as_of = _as_of_past()
    trade_date = completed_trade_date_at(as_of)
    assert trade_date is not None
    monkeypatch.setattr(
        market_module,
        "get_market_breadth",
        lambda: _breadth_fake(trade_date),
    )
    # sector context 无法证明（individual_info 无行业）
    monkeypatch.setattr(astock, "individual_info", lambda code: {})
    monkeypatch.setattr(
        market_module,
        "get_overview",
        lambda: {
            "sentiment": {},
            "sectors": [],
            "updated": f"{trade_date} 15:05",
        },
    )
    result = runtime._production_market_sector_evaluator(None, _definition(as_of))
    assert result["state"] != "USABLE"
    # partial observation 也如实记录（不再是 NOT_INITIALIZED）
    record = _health_record("sector_research")
    assert record["last_error_code"] != "SOURCE_NOT_INITIALIZED"
