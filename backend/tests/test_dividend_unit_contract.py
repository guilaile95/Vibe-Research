"""Synthetic provider → adapter → AI/calendar contracts; no market/model calls."""
from datetime import date

import pytest

import ai_tools
import astock
import research_event_calendar as calendar


@pytest.mark.parametrize("provider, expected", [
    ({"PRETAX_BONUS_RMB": 12.5}, 12.5),
    ({"PRETAX_BONUS_RMB": 0.125}, 0.125),
    ({"PRETAX_BONUS_RMB": 0}, 0),
    ({"PRETAX_BONUS_RMB": None}, None),
    ({}, None),
])
def test_raw_cash_unit_and_missing_value_survive_consumers(monkeypatch, provider, expected):
    def fake_provider(report, **kwargs):
        assert report == "RPT_SHAREBONUS_DET"
        return [{**provider, "EX_DIVIDEND_DATE": "2026-09-01", "ASSIGN_PROGRESS": "已实施"}]
    monkeypatch.setattr(astock, "eastmoney_datacenter", fake_provider)
    direct = astock.dividend_history("600001")
    result = ai_tools.exec_tool("query_dividend", {"code": "600001"})
    assert isinstance(result, list) and result == direct
    assert result[0]["bonus_rmb"] == expected
    assert result[0]["bonus_rmb_unit"] == "CNY/10_shares"
    events, status = calendar._dividend_events(
        {"security_code": "600001", "security_name": None, "campaign_ids": []},
        result, "2026-10-11T00:00:00Z", date(2026, 8, 1), date(2026, 10, 11),
    )
    assert status == "NORMAL"
    assert len(events) == 1
    assert events[0]["details"]["bonus_rmb"] == expected
    assert events[0]["details"]["bonus_rmb_unit"] == "CNY/10_shares"
    assert events[0]["state"] == "HISTORY"


def test_tool_schema_does_not_mislabel_raw_ten_share_amount():
    schema = next(t["function"] for t in ai_tools.TOOLS if t["function"]["name"] == "query_dividend")
    assert "每10股税前派息" in schema["description"]
    assert "CNY/10_shares" in schema["description"]
    assert "每股派息" not in schema["description"]
    assert "股息率" not in schema["description"]  # provider result has no yield field
    assert "每10股派息" in astock.dividend_history.__doc__


def test_tool_keeps_empty_and_twelve_row_array_contract(monkeypatch):
    monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **kw: [])
    assert ai_tools.exec_tool("query_dividend", {"code": "600001"}) == []
    monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **kw: [
        {"PRETAX_BONUS_RMB": n + 0.125} for n in range(15)
    ])
    result = ai_tools.exec_tool("query_dividend", {"code": "600001"})
    assert len(result) == 12
    assert [r["bonus_rmb"] for r in result] == [n + 0.125 for n in range(12)]


def test_active_bundled_guidance_does_not_restore_per_share_contract():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for name in ("README.md", "SKILL.md"):
        guidance = (root / "a-stock-data" / name).read_text(encoding="utf-8")
        assert "每股派息" not in guidance
        assert "每10股税前派息" in guidance
