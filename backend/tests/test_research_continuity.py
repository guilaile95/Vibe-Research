from __future__ import annotations

from datetime import date

import campaign_service
import research_continuity_service as service
from fastapi.testclient import TestClient

import app as app_module


CAMPAIGN_ID = "campaign_" + "a" * 32


def _evidence(evidence_id: str, **overrides) -> dict:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "financial",
        "claim": "revenue growth",
        "classification": "fact",
        "confidence": "high",
        "stance": "support",
        "source_title": "annual report",
        "source_url": "https://example.test/report",
        "source_date": "2026-08-01",
        **overrides,
    }


def test_evidence_change_types_and_unknown_are_distinct():
    baseline = [
        _evidence("same", coverage_status="UNKNOWN"),
        _evidence("removed", claim="removed claim"),
    ]
    current = [
        _evidence("same", confidence="medium", coverage_status="PARTIAL"),
        _evidence("added", claim="new claim"),
        _evidence("conflict-a", source_title="source A", source_url="https://a.test", stance="support"),
        _evidence("conflict-b", source_title="source B", source_url="https://b.test", stance="oppose"),
    ]

    changes = service.compare_evidence(baseline, current)
    assert {item["change_type"] for item in changes} == set(service.CHANGE_TYPES)
    same = next(item for item in changes if item["change_type"] == "CHANGED" and item["record_key"] == "same")
    assert same["before"]["field_states"]["period"] == "UNKNOWN"
    assert same["before"]["field_states"]["coverage_status"] == "UNKNOWN"
    assert same["after"]["field_states"]["coverage_status"] == "VALUE"


def test_disclosure_calendar_semantics(monkeypatch):
    rows = [
        {
            "REPORT_DATE": "2026-06-30 00:00:00",
            "APPOINT_PUBLISH_DATE": "2026-08-15 00:00:00",
            "ACTUAL_PUBLISH_DATE": "2026-08-15 00:00:00",
        },
        {
            "REPORT_DATE": "2026-09-30 00:00:00",
            "APPOINT_PUBLISH_DATE": "2026-10-28 00:00:00",
            "ACTUAL_PUBLISH_DATE": None,
        },
    ]
    projected = service.project_disclosure_calendar(
        rows, as_of=date(2026, 9, 1), fetched_at="2026-09-01T00:00:00.000000Z",
    )
    assert projected["state"] == "EXPECTED"
    assert projected["next"]["appointment_date"] == "2026-10-28"
    assert projected["next"]["semantics"] == "EXPECTED"
    assert projected["latest_actual"]["semantics"] == "CONFIRMED"

    rows[1]["APPOINT_PUBLISH_DATE"] = "2026-08-31 00:00:00"
    assert service.project_disclosure_calendar(
        rows, as_of=date(2026, 9, 1), fetched_at="x",
    )["state"] == "DELAYED_SIGNAL"
    assert service.project_disclosure_calendar([], as_of=date(2026, 9, 1), fetched_at="x")["state"] == "NO_RECORD"
    assert service.project_disclosure_calendar(
        [{"REPORT_DATE": "bad"}], as_of=date(2026, 9, 1), fetched_at="x",
    )["state"] == "UNAVAILABLE"
    monkeypatch.setattr(service.astock, "em_get", lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("offline")))
    assert service._calendar("600519", "x")["state"] == "ERROR"


def test_frozen_candidate_and_no_baseline_paths(monkeypatch):
    original = _evidence("original")
    added = _evidence("added", claim="later immutable fact")
    projection = {
        "formal_status": "READY", "ready": True, "thesis_id": "b" * 32,
        "frozen_revision": 2,
        "binding": {"bound_at": "2026-08-01T00:00:00.000000Z"},
        "original_snapshot": {"evidence_links": [original]},
        "deltas": [{
            "delta_id": "d" * 32, "delta_sequence": 1,
            "confirmed_at": "2026-08-20T00:00:00.000000Z",
            "evidence_links": [added],
        }],
    }
    monkeypatch.setattr(service.campaign_service, "get_campaign", lambda _id: {
        "campaign_id": CAMPAIGN_ID, "security_code": "600519", "strategy": "SWING",
    })
    monkeypatch.setattr(service.formal_thesis_projection, "project_current_thesis", lambda _id: projection)
    monkeypatch.setattr(service, "_calendar", lambda *_args: {
        "state": "NO_RECORD", "next": None, "latest_actual": None,
        "fetched_at": "x", "source": "test",
    })
    monkeypatch.setattr(service.frozen_decision_service, "list_decisions", lambda **_kwargs: [{
        "decision_id": "decision_" + "c" * 32,
        "committed_at": "2026-08-10T00:00:00.000000Z",
        "snapshot_hash": "e" * 64,
        "evidence_refs": ["original"],
    }])

    frozen = service.get_research_continuity(CAMPAIGN_ID)
    assert frozen["baseline"]["authority_type"] == "FROZEN_DECISION"
    assert frozen["changes"]["status"] == "NORMAL"
    assert [item["record_key"] for item in frozen["changes"]["items"] if item["change_type"] == "ADDED"] == ["added"]
    assert frozen["writes"] == {"thesis": 0, "decision": 0, "campaign": 0, "trade": 0}

    monkeypatch.setattr(service.frozen_decision_service, "list_decisions", lambda **_kwargs: [])
    candidate = service.get_research_continuity(CAMPAIGN_ID)
    assert candidate["baseline"]["authority_type"] == "CANDIDATE_RESEARCH_FORMAL_ORIGINAL"
    assert candidate["changes"]["observation_count"] == 1

    def no_binding(_id):
        raise campaign_service.ThesisBindingNotFoundError("missing")

    monkeypatch.setattr(service.formal_thesis_projection, "project_current_thesis", no_binding)
    none = service.get_research_continuity(CAMPAIGN_ID)
    assert none["baseline"]["status"] == "NO_BASELINE"
    assert none["changes"]["status"] == "NO_BASELINE"


def test_campaign_continuity_api_is_read_only(monkeypatch):
    expected = {
        "schema_version": "research_continuity.v0.1",
        "campaign_id": CAMPAIGN_ID,
        "writes": {"thesis": 0, "decision": 0, "campaign": 0, "trade": 0},
    }
    monkeypatch.setattr(
        app_module.campaign_router.research_continuity_service,
        "get_research_continuity",
        lambda campaign_id: {**expected, "campaign_id": campaign_id},
    )
    response = TestClient(app_module.app).get(f"/api/campaigns/{CAMPAIGN_ID}/research-continuity")
    assert response.status_code == 200
    assert response.json()["data"] == expected
