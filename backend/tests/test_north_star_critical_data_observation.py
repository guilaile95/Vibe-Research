"""P0-DS1 — North-Star critical-data real observation path（isolated）。

一个真实形状 A 股 security（600519）走完整 capability 链：
price_reference → market_sector → disclosures → financials。
每一步执行**真实 evaluator 判定逻辑** + 真实交易日历权威 +
实际 provenance / timestamp；数据源 reader 注入 isolated 真实形状数据
（不访问网络、不写真实用户数据）。

产品级接受（§11）：A 真实 USABLE 被 CCD 消费 / C provider failure →
ERROR / D STALE 不冒充 current / E 无公告 ≠ failure / F financial
applicability 未解决不伪造 USABLE / G 无 false clean。
"""
from __future__ import annotations

from copy import deepcopy

import pytest

import campaign_service
import critical_data_dependency_policy as dda
import critical_data_disclosures_adapter as disclosures_adapter
import critical_data_financials_adapter as financials_adapter
import critical_data_market_sector_adapter as market_sector_adapter
import critical_data_price_reference_adapter as price_adapter
import decision_inbox_projection as di
import decision_inbox_runtime_assembler as runtime
import formal_thesis_projection as thesis_projection
import holdings_campaign_composition as composition
from trade_calendar import completed_trade_date_at

AS_OF = "2026-08-13T04:00:00.000000Z"
SECURITY = "600519"
SECURITY_NAME = "贵州茅台"
STRATEGY_SWING = "SWING"
STRATEGY_MEDIUM = "MEDIUM"
CAMPAIGN_A = "campaign_" + "a" * 32
CAMPAIGN_B = "campaign_" + "b" * 32
THESIS_A = "t" * 32
FETCHED_AT = "2026-08-13T03:30:00.000000Z"


def _campaign(
    campaign_id: str = CAMPAIGN_A,
    strategy: str = STRATEGY_SWING,
    status: str = "ACTIVE",
) -> dict:
    return {
        "campaign_id": campaign_id,
        "security_code": SECURITY,
        "strategy": strategy,
        "status": status,
        "created_at": "2026-08-01T00:00:00.000000Z",
        "thesis_binding_status": "BOUND",
        "thesis_binding": {
            "thesis_id": THESIS_A,
            "thesis_revision_at_bind": 1,
            "campaign_strategy_at_bind": strategy,
            "bound_at": "2026-08-01T00:00:00.000000Z",
        },
    }


def _composition_item(campaigns: list[dict]) -> dict:
    return {
        "item_kind": "HOLDING_COMPOSITION",
        "security_code": SECURITY,
        "security_name": SECURITY_NAME,
        "holding": {
            "status": "OPEN",
            "shares": 100,
            "cost_basis": 150000.0,
            "avg_cost": 1500.0,
            "cost_known": True,
            "origin": "PRE_VIBE",
        },
        "composition_status": "ASSIGNED_HOLDING",
        "campaigns": campaigns,
        "allocation_status": "UNKNOWN",
    }


def _composition(campaigns: list[dict]) -> dict:
    return {
        "schema_version": "holdings-campaign-composition.v0.1",
        "evaluation_status": "EVALUATED",
        "canonical": True,
        "reason_codes": [],
        "items": [_composition_item(campaigns)],
        "total_holdings": 1,
    }


def _thesis_missing(campaign_id):
    raise campaign_service.ThesisBindingNotFoundError("no binding")


def _no_frozen(campaign_id):
    return []


def _breadth_reader(trade_date: str | None):
    def _reader():
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

    return _reader


def _announcements_reader(announcements: list[dict]):
    def _reader(code):
        return {
            "announcements": deepcopy(announcements),
            "fetched_at": FETCHED_AT,
            "source": "eastmoney-announcements",
        }

    return _reader


def _financials_reader(payload: dict):
    def _reader(code):
        return deepcopy(payload)

    return _reader


def _price_usable(_lake, definition):
    return {
        "dependency_id": price_adapter.DEPENDENCY_ID,
        "state": "USABLE",
        "as_of": definition["as_of"],
        "authority_refs": [price_adapter.ADAPTER_AUTHORITY_REF],
    }


def _ports(
    *,
    campaigns: list[dict],
    market_reader=None,
    announcements=None,
    financials_payload: dict | None = None,
    price_evaluator=_price_usable,
):
    """真实 evaluator 链（市场/公告/财务真实判定逻辑 + 注入数据）+ fake price。"""
    trade_date = completed_trade_date_at(AS_OF)

    def market(lake, definition):
        reader = market_reader or _breadth_reader(trade_date)
        return market_sector_adapter.evaluate_market_sector_capability(
            security_code=definition["security_code"],
            campaign_id=definition["campaign_id"],
            as_of=definition["as_of"],
            market_reader=reader,
        )

    def disclosures(lake, definition):
        if announcements is None:
            rows = [
                {"date": "2026-08-12", "title": "公告一", "type": "定期报告", "url": "u"},
                {"date": "2026-08-10", "title": "公告二", "type": "权益分派", "url": "u"},
            ]
        else:
            rows = announcements
        return disclosures_adapter.evaluate_disclosures_capability(
            security_code=definition["security_code"],
            campaign_id=definition["campaign_id"],
            as_of=definition["as_of"],
            announcements_reader=_announcements_reader(rows),
        )

    def financials(lake, definition):
        payload = financials_payload
        if payload is None:
            payload = {
                "period": "2025-12-31",
                "revenue": 123.45e8,
                "net_profit": 40.5e8,
                "roe": 20.1,
            }
        return financials_adapter.evaluate_financials_capability(
            security_code=definition["security_code"],
            campaign_id=definition["campaign_id"],
            as_of=definition["as_of"],
            financials_reader=_financials_reader(payload),
        )

    return runtime.RuntimePorts(
        composition_reader=lambda: _composition(campaigns),
        dependency_resolver=dda.resolve_strategy_dependencies,
        price_evaluator=price_evaluator,
        market_sector_evaluator=market,
        disclosures_evaluator=disclosures,
        financials_evaluator=financials,
        thesis_reader=_thesis_missing,
        frozen_decisions_reader=_no_frozen,
        lake_provider=lambda: object(),
    )


def _assemble(ports):
    return runtime.assemble_current_decision_inbox(as_of=AS_OF, ports=ports)


# ---------------------------------------------------------------------------
# §11-A / §9：全 capability 真实判定链（USABLE 被 CCD 消费）
# ---------------------------------------------------------------------------

def test_swing_full_observation_chain_usable_through_ccd():
    trade_date = completed_trade_date_at(AS_OF)
    assert trade_date is not None
    ports = _ports(campaigns=[_campaign()])
    item = _assemble(ports)["campaign_items"][0]

    assert item["critical_data_state"] == "USABLE"
    assert item["critical_data_evaluation"] == "EVALUATED"
    refs = item["explainability"]["authority_refs"]
    # 三个 capability 的 authority 链均进入 explainability
    assert price_adapter.ADAPTER_AUTHORITY_REF in refs
    assert market_sector_adapter.ADAPTER_AUTHORITY_REF in refs
    assert disclosures_adapter.ADAPTER_AUTHORITY_REF in refs
    # 实际 provenance / timestamp（market fact time 与 retrieval time 区分）
    assert f"market-breadth:trade_date={trade_date}" in refs
    assert any(ref.startswith("market-breadth:fetched_at=") for ref in refs)
    assert f"disclosures:fetched_at={FETCHED_AT}" in refs
    assert "disclosures:latest_notice_date=2026-08-12" in refs


# ---------------------------------------------------------------------------
# §11-D：STALE 不冒充 current
# ---------------------------------------------------------------------------

def test_market_sector_stale_is_not_current():
    trade_date = completed_trade_date_at(AS_OF)
    if trade_date is None:
        pytest.skip("calendar has no completed trade date for as_of")
    # 构造早于 completed trade date 的旧快照（2000-01-01 恒早于任何真实 trade date）
    ports = _ports(
        campaigns=[_campaign()],
        market_reader=_breadth_reader("2000-01-01"),
    )
    item = _assemble(ports)["campaign_items"][0]
    # STALE → CCD 域映射 STALE（绝不冒充 current USABLE）
    assert item["critical_data_state"] == "STALE"
    assert item["critical_data_evaluation"] == "EVALUATED"


# ---------------------------------------------------------------------------
# §11-E：无公告但查询成功 ≠ provider failure
# ---------------------------------------------------------------------------

def test_disclosures_empty_is_usable_not_error():
    ports = _ports(campaigns=[_campaign()], announcements=[])
    item = _assemble(ports)["campaign_items"][0]
    refs = item["explainability"]["authority_refs"]
    assert disclosures_adapter.EMPTY_BUT_VALID_REF in refs
    # 无公告维度不算 ERROR，也不拖累 critical data
    assert item["critical_data_state"] == "USABLE"
    assert "REASON_DEPENDENCY_ERROR" not in item["reason_codes"]


# ---------------------------------------------------------------------------
# §11-C：provider failure → ERROR / UNAVAILABLE
# ---------------------------------------------------------------------------

def test_provider_failure_is_error():
    def broken():
        raise RuntimeError("network down")

    ports = _ports(
        campaigns=[_campaign()],
        market_reader=broken,
    )
    item = _assemble(ports)["campaign_items"][0]
    assert item["critical_data_evaluation"] == "ERROR"
    assert di.REASON_CRITICAL_DATA_ERROR in item["reason_codes"]


# ---------------------------------------------------------------------------
# §11-F：financial applicability 未解决 → 不伪造 USABLE
# ---------------------------------------------------------------------------

def test_financials_applicability_unresolved_not_usable():
    medium = _campaign(campaign_id=CAMPAIGN_B, strategy=STRATEGY_MEDIUM)
    ports = _ports(
        campaigns=[medium],
        financials_payload={"period": "2025-12-31", "net_profit": 40.5e8},
    )
    item = _assemble(ports)["campaign_items"][0]
    # MEDIUM required = price + disclosures + financials；
    # financials 真实 retrieval 成功但 applicability 未解决 → 非 USABLE
    assert item["critical_data_state"] != "USABLE"
    assert item["critical_data_evaluation"] == "NOT_EVALUATED"
    refs = item["explainability"]["authority_refs"]
    assert financials_adapter.REPORT_PERIOD_BLOCKER_REF in refs
    assert "financials:provider-claimed-period=2025-12-31" in refs


# ---------------------------------------------------------------------------
# §11-G：无 false clean
# ---------------------------------------------------------------------------

def test_no_false_clean_even_when_capabilities_usable():
    """全部 critical-data USABLE + thesis 缺失 → 仍不得 NO_ACTION_REQUIRED。"""
    ports = _ports(campaigns=[_campaign()])
    item = _assemble(ports)["campaign_items"][0]
    assert item["current_thesis"]["thesis_state"] == "MISSING"
    assert item["critical_data_state"] == "USABLE"
    assert item["visible_state"] != "NO_ACTION_REQUIRED"
    assert item["coverage_complete"] is False
