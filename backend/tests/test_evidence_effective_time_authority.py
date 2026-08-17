"""P0-ET1 contract tests A-M for the temporal authority producer."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import decision_evidence_delta_projection as ec1
import evidence_effective_time_authority as authority
import evidence_thesis_service as evidence_service
import evidence_thesis_store as evidence_store


BASE = "2025-01-01T00:00:00.000000Z"
LATER = "2025-01-02T00:00:00.000000Z"
FUTURE = "2025-01-03T00:00:00.000000Z"
EVIDENCE_ID = "a" * 32


def _evidence() -> dict:
    return {
        "id": EVIDENCE_ID,
        "subject_type": "stock",
        "subject_id": "600519",
    }


def _row(**overrides) -> dict:
    row = {"evidence_id": EVIDENCE_ID}
    row.update(overrides)
    return row


def _intake(**overrides) -> tuple[dict, ...]:
    return (dict(_row(**overrides)),)


def test_a_source_published_at_is_proven_and_ec1_evaluated():
    result = authority.evaluate_temporal_authority(
        _evidence(), _intake(source_identity="wire:1", source_published_at=BASE)
    )
    assert result.temporal_state == authority.PROVEN
    assert result.effective_at == BASE
    assert result.temporal_basis == authority.SOURCE_PUBLISHED_AT
    assert result.ec1_evaluation == authority.EVALUATED
    assert result.ec1_safe_item is not None
    assert result.ec1_safe_item.effective_at == BASE


def test_b_event_occurred_at_is_proven():
    result = authority.evaluate_temporal_authority(
        _evidence(), _intake(event_identity="event:1", event_occurred_at=BASE)
    )
    assert result.temporal_state == authority.PROVEN
    assert result.effective_at == BASE
    assert result.temporal_basis == authority.EVENT_OCCURRED_AT


def test_c_observed_only_is_unproven_and_not_evaluated():
    result = authority.evaluate_temporal_authority(_evidence(), _intake(observed_at=LATER))
    assert result.temporal_state == authority.UNPROVEN
    assert result.effective_at is None
    assert result.ec1_evaluation == authority.NOT_EVALUATED
    assert result.ec1_safe_item is not None
    assert result.ec1_safe_item.effective_at is None
    assert "OBSERVED_TIME_NOT_EFFECTIVE_TIME" in result.reason_codes


def test_d_created_only_is_unproven():
    result = authority.evaluate_temporal_authority(_evidence(), _intake(created_at=LATER))
    assert result.temporal_state == authority.UNPROVEN
    assert result.effective_at is None
    assert "CREATED_TIME_NOT_EFFECTIVE_TIME" in result.reason_codes


def test_e_ingested_only_never_fakes_effective_time():
    result = authority.evaluate_temporal_authority(_evidence(), _intake(ingested_at=LATER))
    assert result.temporal_state == authority.UNPROVEN
    assert result.effective_at is None
    assert "INGESTED_TIME_NOT_EFFECTIVE_TIME" in result.reason_codes


def test_f_late_backfill_without_source_or_event_authority_stays_unproven():
    result = authority.evaluate_temporal_authority(
        _evidence(), _intake(observed_at=LATER, ingested_at=LATER)
    )
    assert result.temporal_state == authority.UNPROVEN
    assert result.effective_at is None


def test_g_future_effective_fact_is_not_current_ec1_evidence():
    result = authority.evaluate_temporal_authority(
        _evidence(),
        _intake(source_identity="wire:future", source_published_at=FUTURE),
        evaluation_as_of=LATER,
    )
    assert result.temporal_state == authority.PROVEN
    assert result.effective_at == FUTURE
    assert result.ec1_evaluation == authority.NOT_EVALUATED
    assert result.ec1_safe_item is not None
    assert result.ec1_safe_item.effective_at is None
    assert "EFFECTIVE_AFTER_EVALUATION_AS_OF" in result.reason_codes


def test_h_malformed_timestamp_fails_closed():
    result = authority.evaluate_temporal_authority(
        _evidence(), _intake(source_identity="wire:bad", source_published_at="2025-02-30T00:00:00.000000Z")
    )
    assert result.temporal_state == authority.ERROR
    assert result.effective_at is None
    assert result.ec1_safe_item is None


def test_i_conflicting_temporal_authorities_have_no_winner():
    result = authority.evaluate_temporal_authority(
        _evidence(),
        _intake(source_identity="wire:1", source_published_at=BASE, event_identity="event:1", event_occurred_at=BASE),
    )
    assert result.temporal_state == authority.ERROR
    assert result.temporal_basis == authority.NONE
    assert result.authority_refs == ()
    assert "CONFLICTING_TEMPORAL_AUTHORITIES" in result.reason_codes


def test_i_same_source_authority_reobserved_is_not_a_conflict():
    result = authority.evaluate_temporal_authority(
        _evidence(),
        (
            _row(source_identity="wire:1", source_published_at=BASE, observed_at=BASE),
            _row(source_identity="wire:1", source_published_at=BASE, observed_at=LATER),
        ),
    )
    assert result.temporal_state == authority.PROVEN
    assert result.effective_at == BASE


def test_j_public_intake_rejects_derived_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "evidence.db"
    evidence_store.initialize_store(db)
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(db))
    client = TestClient(app_module.app)
    created = client.post(
        "/api/evidence",
        json={
            "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
            "claim": "claim", "source_title": "source", "source_url": None,
            "source_date": None, "accessed_at": "2025-01-01T00:00:00+00:00",
            "classification": "fact", "confidence": "high",
        },
    )
    assert created.status_code == 200, created.text
    evidence_id = created.json()["data"]["id"]
    response = client.post(
        f"/api/evidence/{evidence_id}/temporal-authority",
        json={"source_identity": "wire:1", "effective_at": BASE, "temporal_state": "PROVEN", "new_after_decision": True},
    )
    assert response.status_code == 422


def test_k_same_input_is_deterministic():
    intake = _intake(source_identity="wire:1", source_published_at=BASE, observed_at=LATER)
    first = authority.evaluate_temporal_authority(_evidence(), intake).to_dict()
    second = authority.evaluate_temporal_authority(_evidence(), intake).to_dict()
    assert first == second


def test_l_durable_readback_survives_refresh(tmp_path: Path):
    db = tmp_path / "evidence.db"
    evidence_store.initialize_store(db)
    created = evidence_service.create_evidence(db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "claim", "source_title": "source", "source_url": None,
        "source_date": None, "accessed_at": "2025-01-01T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    intake = authority.TemporalIntake(
        evidence_id=created["id"], source_identity="wire:1", source_published_at=BASE
    )
    authority.record_temporal_intake(intake, db_path=db)
    authority.record_temporal_intake(intake, db_path=db)
    result = authority.get_temporal_authority(created["id"], db_path=db)
    assert result is not None
    assert result.temporal_state == authority.PROVEN
    assert result.effective_at == BASE
    with __import__("sqlite3").connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM evidence_temporal_intakes").fetchone()[0] == 1


def test_m_existing_ec1_projection_still_rejects_retrieved_time_as_new():
    context = ec1.DecisionContext(
        security_code="600519",
        strategy="SWING",
        campaign_id="campaign_" + "b" * 32,
        decision_id="decision_" + "c" * 32,
        decision_boundary_at=BASE,
    )
    item = ec1.NormalizedEvidenceItem(
        evidence_id=EVIDENCE_ID,
        scope_kind=ec1.SCOPE_SECURITY,
        scope_id="600519",
        effective_at=None,
        retrieved_at=FUTURE,
        time_semantics=ec1.TIME_SEMANTICS_UNKNOWN,
        authority_refs=(),
    )
    delta = ec1.project_decision_evidence_delta(context=context, evidence_items=(item,))
    assert delta.new_evidence == ()
    assert delta.unknown_temporal_evidence == (EVIDENCE_ID,)
