from __future__ import annotations

from datetime import date

import campaign_service
import evidence_thesis_service
import evidence_thesis_store
import formal_thesis_projection
import frozen_decision_service
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
        _evidence("same"),
        _evidence("removed", claim="removed claim"),
    ]
    current = [
        _evidence("same", confidence="medium"),
        _evidence("added", claim="new claim"),
        _evidence("conflict-a", source_title="source A", source_url="https://a.test", stance="support"),
        _evidence("conflict-b", source_title="source B", source_url="https://b.test", stance="oppose"),
    ]

    changes = service.compare_evidence(baseline, current)
    assert {item["change_type"] for item in changes} == set(service.CHANGE_TYPES)
    same = next(item for item in changes if item["change_type"] == "CHANGED" and item["record_key"] == "same")
    assert same["changed_fields"] == ["confidence"]
    assert same["before"]["values"]["confidence"] == "high"
    assert same["after"]["values"]["confidence"] == "medium"
    unsupported = {"period", "unit", "adjustment", "semantic_contract", "coverage_status"}
    assert unsupported.isdisjoint(same["before"])
    assert unsupported.isdisjoint(same["before"]["values"])


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

    monkeypatch.setattr(
        app_module.campaign_router.research_continuity_service,
        "get_research_continuities",
        lambda campaign_ids: [{**expected, "campaign_id": campaign_id} for campaign_id in campaign_ids],
    )
    batch = TestClient(app_module.app).get(
        "/api/campaigns/research-continuity/batch",
        params=[("campaign_id", CAMPAIGN_ID)],
    )
    assert batch.status_code == 200
    assert batch.json()["data"]["items"] == [expected]


def _decision_payload(campaign: dict, thesis_id: str, revision: int, evidence_id: str) -> dict:
    return {
        "security_code": campaign["security_code"],
        "strategy": campaign["strategy"],
        "campaign_id": campaign["campaign_id"],
        "thesis_id": thesis_id,
        "thesis_revision": revision,
        "asset_view": {}, "trade_view": {}, "portfolio_view": {},
        "next_best_action": "RESEARCH MORE",
        "action_envelope": {},
        "maintain_conditions": [], "upgrade_conditions": [],
        "downgrade_conditions": [], "invalidation_conditions": [],
        "strategy_horizon": "5-20 trading days",
        "review_by": "2026-09-30T00:00:00Z",
        "key_assumptions": [], "event_invalidation_conditions": [],
        "risk_policy_version": "test", "opportunity_policy_version": "test",
        "decision_policy_version": "test", "behavior_model_version": "test",
        "data_quality": {}, "evidence_confidence": 0.8,
        "inference_confidence": "medium", "decision_confidence": None,
        "evidence_refs": [evidence_id], "risk_refs": [], "source_refs": [],
        "user_confirmed": True,
    }


def test_persisted_chain_exposes_only_real_immutable_evidence_fields(tmp_path, monkeypatch):
    evidence_db = tmp_path / "evidence.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(evidence_db))
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(tmp_path / "campaigns.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(tmp_path / "decisions.sqlite3"))
    evidence_thesis_store.initialize_store(evidence_db)

    evidence = evidence_thesis_service.create_evidence(evidence_db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "原始事实", "source_title": "来源 A", "source_url": "https://a.test",
        "source_date": "2026-08-01", "accessed_at": "2026-08-01T01:00:00Z",
        "classification": "fact", "confidence": "high",
    })
    thesis = evidence_thesis_service.create_thesis(evidence_db, {
        "subject_type": "stock", "subject_id": "600519", "title": "正式 Thesis",
        "summary": "summary", "core_claims": ["a", "b", "c"], "catalysts": [],
        "risks": [], "invalidation_conditions": [],
    })
    thesis_id = thesis["thesis"]["id"]
    linked = evidence_thesis_service.link_evidence(
        evidence_db, thesis_id, evidence["id"], "support", 1,
    )
    evidence_thesis_service.begin_formalization(evidence_db, thesis_id)
    edited = evidence_thesis_service.update_thesis(evidence_db, thesis_id, {
        "title": "正式 Thesis", "summary": "summary", "status": "active",
        "core_claims": ["a", "b", "c"], "catalysts": [], "risks": [],
        "invalidation_conditions": [], "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
        "free_notes": "note",
    }, linked["thesis"]["current_revision"])
    revision = edited["thesis"]["current_revision"]
    evidence_thesis_service.confirm_formalization(evidence_db, thesis_id, revision)
    frozen = evidence_thesis_service.freeze_formalization(evidence_db, thesis_id, revision)
    campaign = campaign_service.create_campaign("600519", "SWING")
    campaign_service.bind_campaign_thesis(campaign["campaign_id"], thesis_id)

    evidence_thesis_service.update_evidence(evidence_db, evidence["id"], {
        "evidence_type": "news", "claim": "更新事实", "source_title": "来源 B",
        "source_url": "https://b.test", "source_date": "2026-08-02",
        "accessed_at": "2026-08-02T01:00:00Z", "classification": "fact",
        "confidence": "medium",
    })
    evidence_thesis_service.create_thesis_delta(
        evidence_db, thesis_id, "WEAKENED", "事实已更新", [evidence["id"]],
    )
    frozen_decision_service.freeze_decision(
        _decision_payload(campaign, thesis_id, frozen["frozen_revision"], evidence["id"]),
    )
    monkeypatch.setattr(service, "_calendar", lambda *_args: {
        "state": "NO_RECORD", "next": None, "latest_actual": None,
        "fetched_at": "x", "source": "test",
    })

    projection = formal_thesis_projection.project_current_thesis(campaign["campaign_id"])
    original_fields = set(projection["original_snapshot"]["evidence_links"][0])
    delta_fields = set(projection["deltas"][0]["evidence_links"][0])
    assert original_fields == {
        "evidence_id", "evidence_type", "stance", "claim", "classification",
        "confidence", "source_title", "source_url", "source_date", "accessed_at",
    }
    assert delta_fields == original_fields | {"delta_id", "captured_at"}
    result = service.get_research_continuity(campaign["campaign_id"])
    assert result["baseline"]["authority_type"] == "FROZEN_DECISION"
    assert result["changes"]["status"] == "NOT_EVALUATED"


def test_batch_fetches_disclosure_calendar_once_per_security(monkeypatch):
    campaign_ids = [f"campaign_{index:032x}" for index in range(20)]
    codes = ["600519"] * 10 + ["000001"] * 5 + ["300750"] * 5
    campaigns = {
        campaign_id: {"campaign_id": campaign_id, "security_code": code, "strategy": "SWING"}
        for campaign_id, code in zip(campaign_ids, codes, strict=True)
    }
    monkeypatch.setattr(service.campaign_service, "get_campaign", campaigns.__getitem__)
    monkeypatch.setattr(service, "_continuity", lambda _campaign: {
        "baseline": {"status": "NO_BASELINE", "authority_type": None},
        "changes": {"status": "NO_BASELINE", "items": [], "observation_count": 0},
        "authority_refs": [],
    })
    provider_calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"result": {"data": []}}

    def em_get(*_args, **kwargs):
        provider_calls.append(kwargs["params"]["filter"])
        return Response()

    monkeypatch.setattr(service.astock, "em_get", em_get)
    assert len(service.get_research_continuities(campaign_ids)) == 20
    assert len(provider_calls) == 3

    assert service.get_research_continuity(campaign_ids[0])["campaign_id"] == campaign_ids[0]
    assert len(provider_calls) == 4
