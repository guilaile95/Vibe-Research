"""Real FastAPI harness for the Research Event Calendar browser vertical.

Only the existing provider adapter boundaries are deterministic fixtures.  The
new event aggregation route, Campaign universe projection, router, and
production frontend remain real.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend")))

import app as app_module
import astock
import campaign_store
import decision_inbox_runtime_assembler
import research_continuity_service
from fastapi.responses import JSONResponse


AS_OF = datetime.now(ZoneInfo("Asia/Shanghai")).date()
CAMPAIGN_A = "campaign_" + "a" * 32
CAMPAIGN_B = "campaign_" + "b" * 32
CAMPAIGN_C = "campaign_" + "c" * 32


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _day(offset: int) -> str:
    return (AS_OF + timedelta(days=offset)).isoformat()


def _seed_campaign(campaign_id: str, code: str, path: tuple[str, ...]) -> None:
    campaign_store.create_campaign(
        campaign_id=campaign_id,
        security_code=code,
        strategy="SWING",
        status="DRAFT",
        created_at=_timestamp(),
    )
    previous = "DRAFT"
    for index, target in enumerate(path, start=1):
        campaign_store.transition_campaign(
            campaign_id=campaign_id,
            expected_status=previous,
            to_status=target,
            transition_id="campaign_transition_" + (campaign_id[-1] * 31) + f"{index:01x}",
            transitioned_at=_timestamp(),
        )
        previous = target


def _seed_stores() -> None:
    _seed_campaign(CAMPAIGN_A, "600001", ("RESEARCHING", "PRE-ENTRY", "ACTIVE"))
    _seed_campaign(CAMPAIGN_B, "600001", ("RESEARCHING",))
    _seed_campaign(CAMPAIGN_C, "000002", ("RESEARCHING", "PRE-ENTRY", "ACTIVE"))


def _fixture_calendar(code: str, fetched_at: str) -> dict:
    if code == "600001":
        return research_continuity_service.project_disclosure_calendar(
            [{
                "REPORT_DATE": _day(21),
                "APPOINT_PUBLISH_DATE": _day(11),
                "ACTUAL_PUBLISH_DATE": None,
            }],
            as_of=AS_OF,
            fetched_at=fetched_at,
        )
    return research_continuity_service.project_disclosure_calendar(
        [{
            "REPORT_DATE": _day(-71),
            "APPOINT_PUBLISH_DATE": _day(-15),
            "ACTUAL_PUBLISH_DATE": _day(-1),
        }],
        as_of=AS_OF,
        fetched_at=fetched_at,
    )


def _fixture_lockup(code: str, **_kwargs) -> dict:
    if code == "000002":
        raise RuntimeError("fixture lockup source unavailable")
    return {
        "history": [{"date": _day(-8), "type": "历史解禁", "shares": 100, "able_shares": 80, "ratio": 1}],
        "upcoming": [{"date": _day(11), "type": "首发原股东", "shares": 200, "able_shares": 160, "ratio": 2}],
    }


def _fixture_dividend(code: str, **_kwargs) -> list[dict]:
    return [{"date": _day(-8), "bonus_rmb": 0.5, "transfer_ratio": 0, "bonus_ratio": 0, "plan": "已实施"}]


def _fixture_announcements(code: str, **_kwargs) -> list[dict]:
    return [{
        "date": _day(-1),
        "notice_at": f"{_day(-1)} 10:00:00",
        "title": "一条用于窄屏验证的很长公告标题：仅展示公开 publication event，不做重要性判断",
        "type": "公司公告",
        "url": f"https://example.test/notices/{code}",
    }]


def _fixture_inbox() -> dict:
    return {
        "schema_version": "decision_inbox_runtime.v0.1",
            "as_of": f"{AS_OF.isoformat()}T04:00:00.000000Z",
        "evaluation_status": "EVALUATED",
        "canonical": True,
        "reason_codes": [],
        "holding_setup_items": [],
        "campaign_items": [
            {
                "schema_version": "decision_inbox_projection.v0.1",
                "visible_state": "REVIEW_REQUIRED",
                "reason_codes": ["THESIS_MISSING"],
                "security_code": "600001",
                "strategy": "SWING",
                "campaign_id": CAMPAIGN_A,
                "campaign_status": "ACTIVE",
                "as_of": f"{AS_OF.isoformat()}T04:00:00.000000Z",
            },
            {
                "schema_version": "decision_inbox_projection.v0.1",
                "visible_state": "REVIEW_REQUIRED",
                "reason_codes": ["THESIS_MISSING"],
                "security_code": "000002",
                "strategy": "SWING",
                "campaign_id": CAMPAIGN_C,
                "campaign_status": "ACTIVE",
                "as_of": "2026-09-09T04:00:00.000000Z",
            },
        ],
        "total_holdings": 2,
        "total_campaign_items": 2,
    }


_seed_stores()
research_continuity_service._calendar = _fixture_calendar
astock.lockup_expiry = _fixture_lockup
astock.dividend_history = _fixture_dividend
astock.announcements = _fixture_announcements
decision_inbox_runtime_assembler.assemble_current_decision_inbox = _fixture_inbox

app = app_module.app


@app.middleware("http")
async def empty_unbound_thesis_read(request, call_next):
    """Keep the fixture focused on the event vertical's read path.

    Production keeps the 404 ``thesis-binding`` contract.  This isolated
    browser fixture has no thesis ledger, so it returns the same UI-level
    empty binding branch without producing expected-resource 404 console
    noise.  It does not touch the event-calendar route or its aggregation.
    """
    if request.method == "GET" and request.url.path.startswith("/api/campaigns/") and request.url.path.endswith("/thesis-binding"):
        return JSONResponse({"data": None})
    return await call_next(request)
